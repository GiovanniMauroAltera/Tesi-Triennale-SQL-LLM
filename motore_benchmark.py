import contextlib
import glob
import io
import json
import os
import sys
import time

import httpx
from openai import OpenAI

from common.pipeline import (
    carica_caso,
    estrai_schema_e_campioni,
    estrai_schema_target,
    costruisci_prompt,
    estrai_query_sql,
    esegui_e_stampa,
    valuta_accuratezza,
)

N_RUN = 3
MAX_TENTATIVI = 5
ATTESA_RETRY_SECONDI = 10
ATTESA_RETRY_RATE_LIMIT_SECONDI = 30  # backoff piu' lungo, progressivo, per errori 429
ATTESA_TRA_CHIAMATE_CLOUD = 5
N_CAMPIONI = 5  # stesso valore per tutti i modelli, per un confronto equo
CONTESTO_OLLAMA = 8192  # misurato: prompt fino a ~3700 token reali + risposta; costo in velocita' <= 13%
MAX_TOKEN_RISPOSTA_OLLAMA = 3072  # senza tetto un modello locale puo' entrare in un ciclo di ripetizioni infinito
TIMEOUT_OLLAMA_SECONDI = 900


def attesa_dopo_errore(errore_testo, tentativo):
    # 429 (rate limit) ed errori 5xx del server tendono a durare qualche minuto: attesa progressiva.
    testo = errore_testo.lower()
    if "429" in testo or "rate" in testo or any(f"error code: {c}" in testo for c in ("500", "502", "503", "504")):
        return ATTESA_RETRY_RATE_LIMIT_SECONDI * tentativo
    return ATTESA_RETRY_SECONDI

CARTELLA_RISULTATI = "risultati_bird"
CARTELLA_CASI_BIRD = "casi_bird"
CASO_DEMO = os.path.join("casi", "pc_multivaluta.sqlite")

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


class QuotaGiornalieraEsaurita(Exception):
    pass


def e_limite_giornaliero(errore_testo):
    testo = errore_testo.lower()
    return "429" in testo and ("per day" in testo or "per-day" in testo)


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


def main(limite_casi=None, limite_run=None, solo_modelli=None):
    casi = elenco_casi()
    if limite_casi:
        casi = casi[:limite_casi]
    modelli_da_usare = solo_modelli or list(MODELLI.keys())
    n_run = limite_run or N_RUN

    totale = len(casi) * len(modelli_da_usare) * n_run
    print(f"{len(casi)} casi, {len(modelli_da_usare)} modelli, {n_run} run -> {totale} combinazioni totali", flush=True)

    completate = 0
    saltate = 0
    modelli_in_pausa = set()
    for percorso_caso in casi:
        for nome_modello in modelli_da_usare:
            for indice_run in range(1, n_run + 1):
                if nome_modello in modelli_in_pausa:
                    break
                try:
                    risultato = esegui_run(percorso_caso, nome_modello, indice_run)
                except QuotaGiornalieraEsaurita as e:
                    modelli_in_pausa.add(nome_modello)
                    print(f"[{id_caso(percorso_caso)}] {nome_modello}: QUOTA GIORNALIERA ESAURITA, modello in pausa fino al prossimo avvio: {e}", flush=True)
                    break
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
                else:
                    stato = f"esatto={'SI' if v['esatto'] else 'NO'} F1={v['f1'] * 100:.0f}%"
                print(f"[{id_caso(percorso_caso)}] {nome_modello} run{indice_run}: {stato} ({risultato['tempo_secondi']}s)", flush=True)

    print(f"\nCompletate {completate} nuove combinazioni, {saltate} gia' presenti da run precedenti.", flush=True)
    if modelli_in_pausa:
        print(f"Modelli in pausa per quota giornaliera (rilanciare dopo il reset): {sorted(modelli_in_pausa)}", flush=True)


if __name__ == "__main__":
    main()
