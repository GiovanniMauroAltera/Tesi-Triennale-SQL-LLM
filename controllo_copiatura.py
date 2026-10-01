"""Controllo anti-copiatura: il risultato esatto regge anche su dati modificati?

Con risultati piccoli il prompt mostra per intero la tabella target, e un modello puo' "risolvere"
il caso ricopiandone i valori (es. WHERE Symptoms = 'CNS susp') invece di capire la trasformazione:
l'Execution Accuracy lo conta come esatto. Qui, per ogni run esatto, si rieseguono la query del
modello e la query gold su copie dei dati di partenza con il 30% delle righe rimosse a caso:
chi ha copiato i valori fallisce, chi ha trovato una trasformazione coerente coi dati no.

Le varianti dipendono solo dal caso (seme fisso), quindi sono identiche per tutti i modelli.
Si tengono solo varianti in cui la query gold da' un risultato diverso dall'originale, altrimenti
copiare passerebbe comunque. Aggiunge "valutazione_robusta" ai JSON in risultati_benchmark/; non
richiama nessun modello e puo' girare mentre il benchmark e' in corso.
"""
import glob
import json
import os
import random
import time

from funzioni_comuni import _q, carica_caso, valuta_accuratezza
from codice_benchmark import CARTELLA_RISULTATI, CASO_DEMO, elenco_casi, id_caso

N_VARIANTI = 3
FRAZIONE_RIMOSSA = 0.3
MAX_TENTATIVI_VARIANTE = 20
TIMEOUT_QUERY_SECONDI = 60
TABELLA_ATTESA_VARIANTE = "RISULTATO_ATTESO_VARIANTE"

# Il caso demo non viene da BIRD: la "query gold" e' la trasformazione vera (tassi di cambio nascosti).
SQL_GOLD_DEMO = """SELECT VENDITE_PC.Modello AS Modello_PC,
       AVG(VENDITE_PC.Prezzo_Locale * CASE VENDITE_PC.Valuta_Locale
           WHEN 'EUR' THEN 1.08 WHEN 'GBP' THEN 1.25 WHEN 'JPY' THEN 0.0065 END) AS Prezzo_Medio_USD
FROM VENDITE_PC GROUP BY VENDITE_PC.Modello"""


def sql_gold(percorso_caso, cursor):
    if id_caso(percorso_caso) == id_caso(CASO_DEMO):
        return SQL_GOLD_DEMO
    return cursor.execute("SELECT sql_gold FROM _bird_info").fetchone()[0].strip().rstrip(";")


def con_timeout(conn, funzione):
    inizio = time.time()
    conn.set_progress_handler(lambda: 1 if time.time() - inizio > TIMEOUT_QUERY_SECONDI else 0, 100000)
    try:
        return funzione()
    finally:
        conn.set_progress_handler(None, 0)


def perturba(conn, tabelle, seme):
    rng = random.Random(seme)
    cursor = conn.cursor()
    for tabella in tabelle:
        rowid = [r[0] for r in cursor.execute(f"SELECT rowid FROM {_q(tabella)}")]
        da_rimuovere = rng.sample(rowid, int(len(rowid) * FRAZIONE_RIMOSSA))
        cursor.executemany(f"DELETE FROM {_q(tabella)} WHERE rowid = ?", [(r,) for r in da_rimuovere])


def firma(righe):
    return sorted(repr(r) for r in righe)


def varianti_del_caso(percorso_caso):
    """Semi delle varianti in cui la query gold cambia risultato (e non diventa vuota)."""
    conn, cursor, sorgenti, nome_target = carica_caso(percorso_caso)
    gold = sql_gold(percorso_caso, cursor)
    originale = firma(cursor.execute(f"SELECT * FROM {_q(nome_target)}").fetchall())
    conn.close()

    semi = []
    for k in range(MAX_TENTATIVI_VARIANTE):
        seme = f"{id_caso(percorso_caso)}-{k}"
        conn, cursor, sorgenti, _ = carica_caso(percorso_caso)
        perturba(conn, sorgenti, seme)
        try:
            righe = con_timeout(conn, lambda: cursor.execute(gold).fetchall())
        except Exception:
            righe = []
        conn.close()
        if righe and firma(righe) != originale:
            semi.append(seme)
            if len(semi) == N_VARIANTI:
                break
    return semi, gold


def valuta_su_variante(percorso_caso, gold, seme, query_modello):
    conn, cursor, sorgenti, _ = carica_caso(percorso_caso)
    perturba(conn, sorgenti, seme)
    cursor.execute(f"CREATE TABLE main.{_q(TABELLA_ATTESA_VARIANTE)} AS {gold}")
    try:
        con_timeout(conn, lambda: conn.executescript(query_modello))
        tabelle_create = [r[0] for r in cursor.execute("SELECT name FROM sqlite_temp_master WHERE type='table'")]
    except Exception:
        tabelle_create = []
    valutazione = valuta_accuratezza(cursor, tabelle_create, TABELLA_ATTESA_VARIANTE)
    conn.close()
    return valutazione


def main():
    percorsi_casi = {id_caso(p): p for p in elenco_casi()}
    cache_varianti = {}
    aggiornati = 0
    for percorso_json in sorted(glob.glob(os.path.join(CARTELLA_RISULTATI, "*.json"))):
        try:
            with open(percorso_json, encoding="utf-8") as f:
                risultato = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # file in scrittura dal benchmark in corso: verra' ripreso al prossimo avvio
        if "valutazione_robusta" in risultato or risultato["caso"] not in percorsi_casi:
            continue

        esatto = bool((risultato.get("valutazione") or {}).get("esatto"))
        if not esatto:
            robusta = {"esatto_robusto": False, "verificabile": True, "nota": "non esatto sui dati originali"}
        else:
            percorso_caso = percorsi_casi[risultato["caso"]]
            if percorso_caso not in cache_varianti:
                cache_varianti[percorso_caso] = varianti_del_caso(percorso_caso)
            semi, gold = cache_varianti[percorso_caso]
            if not semi:
                robusta = {"esatto_robusto": True, "verificabile": False,
                           "nota": "nessuna variante cambia il risultato gold: copiatura non rilevabile"}
            else:
                esiti = []
                for seme in semi:
                    v = valuta_su_variante(percorso_caso, gold, seme, risultato["query_generata"])
                    esiti.append({"seme": seme, "esatto": v["esatto"], "f1": v["f1"]})
                robusta = {"esatto_robusto": all(e["esatto"] for e in esiti), "verificabile": True, "varianti": esiti}

        risultato["valutazione_robusta"] = robusta
        with open(percorso_json, "w", encoding="utf-8") as f:
            json.dump(risultato, f, indent=2, ensure_ascii=False, default=str)
        aggiornati += 1
        if esatto:
            stato = "ROBUSTO" if robusta["esatto_robusto"] else "NON ROBUSTO"
            if not robusta["verificabile"]:
                stato += " (non verificabile)"
            print(f"{os.path.basename(percorso_json)}: {stato}", flush=True)

    print(f"\nAggiornati {aggiornati} risultati.", flush=True)


if __name__ == "__main__":
    main()
