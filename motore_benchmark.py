import contextlib
import glob
import io
import json
import os
import sys
import time

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
ATTESA_TRA_CHIAMATE_OPENROUTER = 5
N_CAMPIONI = 5  # stesso valore per tutti i modelli, per un confronto equo


def attesa_dopo_errore(errore_testo, tentativo):
    if "429" in errore_testo or "rate" in errore_testo.lower():
        return ATTESA_RETRY_RATE_LIMIT_SECONDI * tentativo
    return ATTESA_RETRY_SECONDI

CARTELLA_RISULTATI = "risultati_bird"
CARTELLA_CASI_BIRD = "casi_bird"
CASO_DEMO = os.path.join("casi", "pc_multivaluta.sqlite")

MODELLI = {
    "llama3.1": {"provider": "ollama", "model": "llama3.1"},
    "qwen2.5-coder-7b": {"provider": "ollama", "model": "qwen2.5-coder:7b"},
    "nemotron": {"provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    "gemma": {"provider": "openrouter", "model": "google/gemma-4-31b-it:free"},
    "qwen": {"provider": "openrouter", "model": "qwen/qwen3.8-27b:free"},
}


def elenco_casi():
    casi = [CASO_DEMO]
    casi += sorted(glob.glob(os.path.join(CARTELLA_CASI_BIRD, "*.sqlite")))
    return casi


def id_caso(percorso):
    return os.path.splitext(os.path.basename(percorso))[0]


def client_per(provider):
    if provider == "ollama":
        return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])


def chiama_modello(config, prompt):
    client = client_per(config["provider"])
    response = client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    contenuto = response.choices[0].message.content
    if not contenuto:
        raise ValueError("risposta vuota dal modello")
    return contenuto.strip()


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
    tempo_inizio = time.time()
    for tentativo in range(1, MAX_TENTATIVI + 1):
        try:
            testo_risposta = chiama_modello(config, prompt)
            errore_finale = None
            break
        except Exception as e:
            errore_finale = str(e)
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

    if config["provider"] == "openrouter":
        time.sleep(ATTESA_TRA_CHIAMATE_OPENROUTER)

    return risultato


def main(limite_casi=None, limite_run=None, solo_modelli=None):
    casi = elenco_casi()
    if limite_casi:
        casi = casi[:limite_casi]
    modelli_da_usare = solo_modelli or list(MODELLI.keys())
    n_run = limite_run or N_RUN

    totale = len(casi) * len(modelli_da_usare) * n_run
    print(f"{len(casi)} casi, {len(modelli_da_usare)} modelli, {n_run} run -> {totale} combinazioni totali")

    completate = 0
    saltate = 0
    for percorso_caso in casi:
        for nome_modello in modelli_da_usare:
            for indice_run in range(1, n_run + 1):
                risultato = esegui_run(percorso_caso, nome_modello, indice_run)
                if risultato is None:
                    saltate += 1
                    continue
                completate += 1
                acc = None
                if risultato["valutazione"]:
                    acc = risultato["valutazione"]["accuratezza"]
                stato = f"acc={acc*100:.0f}%" if acc is not None else f"ERRORE: {risultato['errore_chiamata']}"
                print(f"[{id_caso(percorso_caso)}] {nome_modello} run{indice_run}: {stato} ({risultato['tempo_secondi']}s)")

    print(f"\nCompletate {completate} nuove combinazioni, {saltate} gia' presenti da run precedenti.")


if __name__ == "__main__":
    main()
