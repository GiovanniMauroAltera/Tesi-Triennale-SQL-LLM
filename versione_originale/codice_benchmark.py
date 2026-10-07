"""Il benchmark della versione originale: ogni modello prova ogni caso piu' volte, e ogni prova viene valutata.

Per ogni prova salva in versione_originale/risultati_benchmark/ un file .json (query, valutazione, tempo) e un
file .log.txt (la risposta completa del modello). Se si interrompe riparte da dove era rimasto.

Come si usa (dalla cartella principale della repository):
  python versione_originale/codice_benchmark.py
  python versione_originale/codice_benchmark.py --modelli gemma nemotron
  python versione_originale/codice_benchmark.py --modelli llama3.1 --parte 1/2    (e in un altro terminale 2/2)
"""
import argparse
import contextlib
import ctypes
import glob
import io
import json
import os
import sys
import time

import httpx
from openai import OpenAI

from funzioni_comuni import (
    carica_caso,
    estrai_schema_e_campioni,
    estrai_schema_target,
    costruisci_prompt,
    estrai_query_sql,
    esegui_e_stampa,
    valuta_accuratezza,
)

N_RUN = 3
N_RUN_PER_MODELLO = {"gemma": 8, "qwen2.5-coder-7b": 8, "llama3.1": 5}
MAX_TENTATIVI = 5
ATTESA_RETRY_SECONDI = 10
ATTESA_RETRY_RATE_LIMIT_SECONDI = 30  # backoff piu' lungo, progressivo, per errori 429
ATTESA_TRA_CHIAMATE_CLOUD = 5
N_CAMPIONI = 5  # stesso valore per tutti i modelli, per un confronto equo
CONTESTO_OLLAMA = 8192  # misurato: prompt fino a ~3700 token reali + risposta; costo in velocita' <= 13%
MAX_TOKEN_RISPOSTA_OLLAMA = 3072  # senza tetto un modello locale puo' entrare in un ciclo di ripetizioni infinito
# Solo rete di sicurezza: le risposte infinite le ferma MAX_TOKEN_RISPOSTA_OLLAMA. Llama 3.1 su questo PC
# genera ~3,5 token/s, quindi arrivare al tetto richiede ~15 minuti (894 s osservati sul caso 1220).
TIMEOUT_OLLAMA_SECONDI = 1800
PAUSA_DOPO_GUASTO_SECONDI = 600  # dopo un run rimandato per guasto del fornitore, prima di passare al successivo

# Tutti gli script si lanciano dalla cartella principale della repository: i casi sono in comune con la
# versione ottimizzata, i risultati restano nella cartella di questa versione.
CARTELLA_RISULTATI = os.path.join("versione_originale", "risultati_benchmark")
CARTELLA_CASI_BIRD = "casi_BIRD"
CASO_DEMO = os.path.join("caso_PC", "pc_multivaluta.sqlite")

MODELLI = {
    "llama3.1": {"provider": "ollama", "model": "llama3.1"},
    "qwen2.5-coder-7b": {"provider": "ollama", "model": "qwen2.5-coder:7b"},
    "nemotron": {"provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    "gemma": {"provider": "google", "model": "gemma-4-31b-it"},
    "gpt-oss-120b": {"provider": "groq", "model": "openai/gpt-oss-120b"},
}

# Tarati sui tempi osservati: Nemotron ha impiegato fino a 29 minuti per una risposta valida,
# Gemma via Google ~8 minuti. Senza timeout espliciti una richiesta bloccata dal server
# restava appesa 10 minuti per tentativo (default della libreria openai).
TIMEOUT_CLOUD_SECONDI = {"openrouter": 2400, "google": 900, "groq": 300}

ENDPOINT_OPENAI_COMPATIBILI = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_API_KEY"),
}


# Due tipi di errore "nostri": esegui_run li solleva (raise) e main li riconosce (except) per decidere
# se mettere in pausa il modello fino al giorno dopo o rimandare solo quel run.
class QuotaGiornalieraEsaurita(Exception):
    pass


class GuastoTemporaneoFornitore(Exception):
    pass


def e_errore_del_server(testo):
    """Gli errori 500, 502, 503 e 504: il server del fornitore e' in difficolta'."""
    for codice in ("500", "502", "503", "504"):
        if f"error code: {codice}" in testo:
            return True
    return False


def attesa_dopo_errore(errore_testo, tentativo):
    # 429 (rate limit) ed errori 5xx del server tendono a durare qualche minuto: attesa progressiva.
    testo = errore_testo.lower()
    if "429" in testo or "rate" in testo or e_errore_del_server(testo):
        return ATTESA_RETRY_RATE_LIMIT_SECONDI * tentativo
    return ATTESA_RETRY_SECONDI


def e_limite_giornaliero(errore_testo):
    testo = errore_testo.lower()
    return "429" in testo and ("per day" in testo or "per-day" in testo)


def e_guasto_temporaneo(errore_testo):
    # Server sovraccarico o in errore, limite al minuto, rete assente, richiesta rimasta appesa oltre il
    # timeout (tarato ben sopra i tempi di risposta osservati): non dice nulla sul modello.
    testo = errore_testo.lower()
    return ("429" in testo or "connection error" in testo or "timed out" in testo
            or e_errore_del_server(testo))


def n_run(nome_modello):
    return N_RUN_PER_MODELLO.get(nome_modello, N_RUN)


def elenco_casi():
    casi = [CASO_DEMO]
    casi += sorted(glob.glob(os.path.join(CARTELLA_CASI_BIRD, "*.sqlite")))
    return casi


def id_caso(percorso):
    return os.path.splitext(os.path.basename(percorso))[0]


def chiama_ollama(modello, prompt):
    # API nativa: a differenza di quella compatibile OpenAI permette di fissare il contesto;
    # il default di Ollama (4096 token) taglierebbe in silenzio i prompt piu' lunghi.
    risposta = httpx.post(
        "http://localhost:11434/api/chat",
        json={
            "model": modello,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": CONTESTO_OLLAMA, "num_predict": MAX_TOKEN_RISPOSTA_OLLAMA},
        },
        timeout=TIMEOUT_OLLAMA_SECONDI,
    )
    risposta.raise_for_status()
    dati = risposta.json()
    return dati["message"]["content"], dati.get("done_reason") == "length"


def chiama_modello(config, prompt):
    """Ritorna (testo della risposta, True se la risposta e' stata troncata per lunghezza)."""
    if config["provider"] == "ollama":
        contenuto, troncata = chiama_ollama(config["model"], prompt)
    else:
        base_url, variabile_chiave = ENDPOINT_OPENAI_COMPATIBILI[config["provider"]]
        # max_retries=0: gli unici tentativi sono i nostri (MAX_TENTATIVI), niente ripetizioni nascoste della libreria.
        client = OpenAI(base_url=base_url, api_key=os.environ[variabile_chiave],
                        timeout=TIMEOUT_CLOUD_SECONDI[config["provider"]], max_retries=0)
        response = client.chat.completions.create(
            model=config["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        if not response.choices:
            # OpenRouter a volte risponde 200 con l'errore del fornitore nel corpo al posto di "choices":
            # lo rendiamo leggibile, con il codice nel formato che attesa_dopo_errore riconosce.
            errore = None
            if response.model_extra:
                errore = response.model_extra.get("error")
            codice = "?"
            if isinstance(errore, dict):
                codice = errore.get("code", "?")
            raise RuntimeError(f"Error code: {codice} - risposta senza choices dal fornitore: {errore}")
        contenuto = response.choices[0].message.content
        troncata = response.choices[0].finish_reason == "length"
    if not contenuto:
        raise ValueError("risposta vuota dal modello")
    return contenuto.strip(), troncata


def esegui_run(percorso_caso, nome_modello, indice_run):
    id_c = id_caso(percorso_caso)
    nome_base = f"{id_c}__{nome_modello}__run{indice_run}"
    percorso_json = os.path.join(CARTELLA_RISULTATI, nome_base + ".json")
    if os.path.exists(percorso_json):
        return None  # gia' completato in una run precedente dello script

    config = MODELLI[nome_modello]
    conn, cursor, nomi_sorgente, nome_target = carica_caso(percorso_caso)
    schema_a = estrai_schema_e_campioni(cursor, nomi_sorgente, n_campioni=N_CAMPIONI)
    schema_b = estrai_schema_target(cursor, nome_target)
    prompt = costruisci_prompt(schema_a, schema_b, nome_target)

    errore_finale = None
    testo_risposta = ""
    risposta_troncata = False
    tempo_inizio = time.time()
    for tentativo in range(1, MAX_TENTATIVI + 1):
        try:
            testo_risposta, risposta_troncata = chiama_modello(config, prompt)
            errore_finale = None
            break
        except Exception as e:
            errore_finale = str(e)
            if e_limite_giornaliero(errore_finale):
                # Riprovare tra pochi minuti non serve: nessun risultato salvato, il run
                # verra' rifatto al prossimo avvio dopo il reset della quota.
                conn.close()
                raise QuotaGiornalieraEsaurita(errore_finale)
            if tentativo < MAX_TENTATIVI:
                time.sleep(attesa_dopo_errore(errore_finale, tentativo))
    tempo_totale = time.time() - tempo_inizio

    if errore_finale is not None and e_guasto_temporaneo(errore_finale):
        # Un guasto del fornitore non e' un errore del modello: nessun risultato salvato,
        # il run verra' rifatto al prossimo avvio.
        conn.close()
        raise GuastoTemporaneoFornitore(errore_finale)

    log_buffer = io.StringIO()
    risultato = {
        "caso": id_c,
        "modello": nome_modello,
        "run": indice_run,
        "tempo_secondi": round(tempo_totale, 1),
        "errore_chiamata": errore_finale,
        "risposta_troncata": risposta_troncata,
        "valutazione": None,
        "query_generata": None,
    }

    if errore_finale is None:
        query_completa = estrai_query_sql(testo_risposta)
        # Quello che esegui_e_stampa scriverebbe sullo schermo finisce in log_buffer, e poi nel file di log.
        with contextlib.redirect_stdout(log_buffer):
            tabelle_create = esegui_e_stampa(cursor, query_completa)
        risultato["query_generata"] = query_completa
        risultato["valutazione"] = valuta_accuratezza(cursor, tabelle_create, nome_target)

    conn.close()

    os.makedirs(CARTELLA_RISULTATI, exist_ok=True)
    with open(percorso_json, "w", encoding="utf-8") as f:
        json.dump(risultato, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(CARTELLA_RISULTATI, nome_base + ".log.txt"), "w", encoding="utf-8") as f:
        f.write(f"RISPOSTA GREZZA DEL MODELLO:\n{testo_risposta}\n\n")
        f.write(f"LOG ESECUZIONE:\n{log_buffer.getvalue()}")

    if config["provider"] != "ollama":
        time.sleep(ATTESA_TRA_CHIAMATE_CLOUD)

    return risultato


def main(limite_casi=None, limite_run=None, solo_modelli=None, parte=None):
    casi = elenco_casi()
    if limite_casi:
        casi = casi[:limite_casi]
    if parte:
        # (k, n): solo un caso ogni n a partire dal k-esimo, per dividere un modello lento tra n processi
        # paralleli senza che due processi facciano mai la stessa combinazione.
        k, n = parte
        scelti = []
        for posizione, caso in enumerate(casi):
            if posizione % n == k - 1:
                scelti.append(caso)
        casi = scelti
    if solo_modelli:
        modelli_da_usare = solo_modelli
    else:
        modelli_da_usare = list(MODELLI.keys())
    run_per_modello = {}
    for m in modelli_da_usare:
        if limite_run:
            run_per_modello[m] = limite_run
        else:
            run_per_modello[m] = n_run(m)

    totale = len(casi) * sum(run_per_modello.values())
    pezzi = []
    for m, k in run_per_modello.items():
        pezzi.append(f"{m}: {k} run")
    descrizione_run = ", ".join(pezzi)
    print(f"{len(casi)} casi, {descrizione_run} -> {totale} combinazioni totali", flush=True)

    completate = 0
    saltate = 0
    rimandate = 0
    modelli_in_pausa = set()
    for percorso_caso in casi:
        for nome_modello in modelli_da_usare:
            for indice_run in range(1, run_per_modello[nome_modello] + 1):
                if nome_modello in modelli_in_pausa:
                    break
                try:
                    risultato = esegui_run(percorso_caso, nome_modello, indice_run)
                except QuotaGiornalieraEsaurita as e:
                    modelli_in_pausa.add(nome_modello)
                    print(f"[{id_caso(percorso_caso)}] {nome_modello}: QUOTA GIORNALIERA ESAURITA, modello in pausa fino al prossimo avvio: {e}", flush=True)
                    break
                except GuastoTemporaneoFornitore as e:
                    rimandate += 1
                    print(f"[{id_caso(percorso_caso)}] {nome_modello} run{indice_run}: GUASTO DEL FORNITORE dopo {MAX_TENTATIVI} tentativi, run rimandato al prossimo avvio: {e}", flush=True)
                    time.sleep(PAUSA_DOPO_GUASTO_SECONDI)
                    continue
                except Exception as e:
                    print(f"[{id_caso(percorso_caso)}] {nome_modello} run{indice_run}: ERRORE IMPREVISTO, saltato (verra' ritentato al prossimo avvio): {e}", flush=True)
                    continue
                if risultato is None:
                    saltate += 1
                    continue
                completate += 1
                v = risultato["valutazione"]
                if v is None:
                    stato = f"ERRORE: {risultato['errore_chiamata']}"
                elif v["esatto"]:
                    stato = f"esatto=SI F1={v['f1'] * 100:.0f}%"
                else:
                    stato = f"esatto=NO F1={v['f1'] * 100:.0f}%"
                print(f"[{id_caso(percorso_caso)}] {nome_modello} run{indice_run}: {stato} ({risultato['tempo_secondi']}s)", flush=True)

    print(f"\nCompletate {completate} nuove combinazioni, {saltate} gia' presenti da run precedenti.", flush=True)
    if rimandate:
        print(f"Rimandate {rimandate} combinazioni per guasti temporanei del fornitore: rilanciare per rifarle.", flush=True)
    if modelli_in_pausa:
        print(f"Modelli in pausa per quota giornaliera (rilanciare dopo il reset): {sorted(modelli_in_pausa)}", flush=True)


# Chiede a Windows di non andare in sospensione finche' il benchmark e' in esecuzione.
#
# E' una richiesta del programma (come quella dei lettori video), non un cambio di impostazioni:
# Windows la annulla da solo quando il processo termina. Sui portatili con Modern Standby lo
# standby parte quando lo schermo si spegne, quindi serve anche tenere acceso lo schermo.
# Il coperchio chiuso manda comunque in sospensione.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def tieni_sveglio_il_pc():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)


def lascia_dormire_il_pc():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Esegue il benchmark caso x modello x run.")
    parser.add_argument("--modelli", nargs="+", choices=list(MODELLI),
                        help="solo questi modelli (per lanciare un processo per fornitore in parallelo)")
    parser.add_argument("--parte", metavar="K/N",
                        help="solo un caso ogni N a partire dal K-esimo (es. 1/2 e 2/2 in due processi paralleli)")
    argomenti = parser.parse_args()
    parte = None
    if argomenti.parte:
        k, n = argomenti.parte.split("/")
        parte = (int(k), int(n))
    tieni_sveglio_il_pc()
    try:
        main(solo_modelli=argomenti.modelli, parte=parte)
    finally:
        lascia_dormire_il_pc()
