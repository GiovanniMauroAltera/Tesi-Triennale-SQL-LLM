"""Controllo anti-copiatura: il risultato esatto regge anche su dati modificati?

Con risultati piccoli il prompt mostra per intero la tabella target, e un modello puo' "risolvere"
il caso ricopiandone i valori (es. WHERE Symptoms = 'CNS susp') invece di capire la trasformazione:
l'Execution Accuracy lo conta come esatto. Qui, per ogni run esatto, si rieseguono la query del
modello e la query gold su copie dei dati di partenza con il 30% delle righe rimosse a caso:
chi ha copiato i valori fallisce, chi ha trovato una trasformazione coerente coi dati no.

Le varianti dipendono solo dal caso (seme fisso), quindi sono identiche per tutti i modelli.
Si tengono solo varianti in cui la query gold da' un risultato diverso dall'originale, altrimenti
copiare passerebbe comunque.

Secondo controllo, sul testo della query: alcuni modelli scrivono a mano i valori della tabella
target e poi li uniscono alle tabelle di partenza con un JOIN, o li usano in un filtro IN (...).
Togliendo righe a caso la loro query e quella gold perdono le stesse righe, quindi il primo
controllo non le vede; il secondo si' (vedi valori_copiati). Un esatto e' robusto solo se passa
entrambi i controlli.

Aggiunge "valutazione_robusta" ai JSON in versione_originale/risultati_benchmark/; non richiama nessun modello e puo'
girare mentre il benchmark e' in corso.

Come si usa (dalla cartella principale della repository):
  python versione_originale/controllo_copiatura.py
"""
import glob
import json
import os
import random
import re
import time

from funzioni_comuni import nome_sql, carica_caso, valuta_accuratezza
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


def esegui_con_timeout(conn, sql, e_uno_script):
    """Esegue sql e si ferma dopo TIMEOUT_QUERY_SECONDI.

    Con e_uno_script=False sql e' una sola query e la funzione restituisce le sue righe; con True sql puo'
    contenere piu' istruzioni (come le risposte dei modelli) e la funzione non restituisce niente.
    """
    inizio = time.time()

    def troppo_tempo():
        # SQLite chiama questa funzione ogni tanto mentre lavora: se restituisce 1, la query si ferma.
        if time.time() - inizio > TIMEOUT_QUERY_SECONDI:
            return 1
        return 0

    conn.set_progress_handler(troppo_tempo, 100000)
    try:
        if e_uno_script:
            conn.executescript(sql)
            return None
        return conn.execute(sql).fetchall()
    finally:
        conn.set_progress_handler(None, 0)


def perturba(conn, tabelle, seme):
    """Toglie a caso il 30% delle righe di ogni tabella di partenza (sempre le stesse, dato il seme)."""
    rng = random.Random(seme)
    cursor = conn.cursor()
    for tabella in tabelle:
        rowid = []
        for riga in cursor.execute(f"SELECT rowid FROM {nome_sql(tabella)}"):
            rowid.append(riga[0])
        da_rimuovere = rng.sample(rowid, int(len(rowid) * FRAZIONE_RIMOSSA))
        parametri = []
        for numero in da_rimuovere:
            parametri.append((numero,))  # executemany vuole una tupla di valori per ogni esecuzione
        cursor.executemany(f"DELETE FROM {nome_sql(tabella)} WHERE rowid = ?", parametri)


def firma(righe):
    """Le righe in un ordine fisso, per confrontare due risultati senza badare all'ordine."""
    testi = []
    for riga in righe:
        testi.append(repr(riga))
    testi.sort()
    return testi


def varianti_del_caso(percorso_caso):
    """Semi delle varianti in cui la query gold cambia risultato (e non diventa vuota)."""
    conn, cursor, sorgenti, nome_target = carica_caso(percorso_caso)
    gold = sql_gold(percorso_caso, cursor)
    originale = firma(cursor.execute(f"SELECT * FROM {nome_sql(nome_target)}").fetchall())
    conn.close()

    semi = []
    for k in range(MAX_TENTATIVI_VARIANTE):
        seme = f"{id_caso(percorso_caso)}-{k}"
        conn, cursor, sorgenti, nome_target = carica_caso(percorso_caso)
        perturba(conn, sorgenti, seme)
        try:
            righe = esegui_con_timeout(conn, gold, False)
        except Exception:
            righe = []
        conn.close()
        if righe and firma(righe) != originale:
            semi.append(seme)
            if len(semi) == N_VARIANTI:
                break
    return semi, gold


def valuta_su_variante(percorso_caso, gold, seme, query_modello):
    conn, cursor, sorgenti, nome_target = carica_caso(percorso_caso)
    perturba(conn, sorgenti, seme)
    cursor.execute(f"CREATE TABLE main.{nome_sql(TABELLA_ATTESA_VARIANTE)} AS {gold}")
    try:
        esegui_con_timeout(conn, query_modello, True)
        tabelle_create = []
        for riga in cursor.execute("SELECT name FROM sqlite_temp_master WHERE type='table'"):
            tabelle_create.append(riga[0])
    except Exception:
        tabelle_create = []
    valutazione = valuta_accuratezza(cursor, tabelle_create, TABELLA_ATTESA_VARIANTE)
    conn.close()
    return valutazione


def valori_copiati(sql, righe_finali):
    """Testi della tabella target scritti a mano nella query (es. SELECT 'Trent', 'Smith' UNION ALL ...).

    Un filtro come WHERE state = 'Illinois' e' legittimo; diventa una copiatura quando nella query
    compaiono almeno meta' dei testi della tabella target (e almeno due). Serve per le copiature che
    il controllo sui dati modificati non vede: valori scritti a mano e poi uniti alle tabelle di
    partenza con un JOIN, o usati in un filtro IN (...). Togliendo righe a caso, la query copiata e
    quella gold perdono le stesse righe e il risultato coincide ancora.

    Restituisce (True se e' una copiatura, i testi copiati in ordine alfabetico).
    """
    if not sql:
        sql = ""
    senza_commenti = re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.DOTALL)
    # I testi tra apici nella query: '' dentro un testo e' un apice scritto due volte.
    scritti_a_mano = set()
    for testo in re.findall(r"'((?:[^']|'')*)'", senza_commenti):
        scritti_a_mano.add(testo.replace("''", "'"))
    testi_finali = set()
    for riga in righe_finali:
        for valore in riga:
            if isinstance(valore, str) and len(valore.strip()) >= 2:
                testi_finali.add(valore)
    copiati = sorted(testi_finali & scritti_a_mano)  # i testi presenti in tutti e due gli insiemi
    copiatura = len(testi_finali) >= 2 and len(copiati) >= max(2, len(testi_finali) / 2)
    return copiatura, copiati


def righe_target(percorso_caso):
    conn, cursor, sorgenti, nome_target = carica_caso(percorso_caso)
    righe = cursor.execute(f"SELECT * FROM {nome_sql(nome_target)}").fetchall()
    conn.close()
    return righe


def e_esatto(risultato):
    """True se la prova ha dato il risultato esatto sui dati originali."""
    valutazione = risultato.get("valutazione")
    if not valutazione:
        return False
    return bool(valutazione.get("esatto"))


def main():
    percorsi_casi = {}  # nome del caso -> percorso del file
    for percorso in elenco_casi():
        percorsi_casi[id_caso(percorso)] = percorso
    cache_varianti = {}
    cache_target = {}
    aggiornati = 0
    for percorso_json in sorted(glob.glob(os.path.join(CARTELLA_RISULTATI, "*.json"))):
        try:
            with open(percorso_json, encoding="utf-8") as f:
                risultato = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # file in scrittura dal benchmark in corso: verra' ripreso al prossimo avvio
        if risultato["caso"] not in percorsi_casi:
            continue
        esatto = e_esatto(risultato)
        robusta = risultato.get("valutazione_robusta")
        if robusta is not None and "copiatura_nel_testo" in robusta:
            continue  # gia' controllato con entrambi i metodi
        if robusta is not None:
            # Risultato gia' controllato sui dati modificati: manca solo il controllo sul testo.
            aggiungi_controllo_testo(risultato, percorsi_casi, cache_target)
            salva(percorso_json, risultato)
            aggiornati += 1
            if risultato["valutazione_robusta"]["copiatura_nel_testo"]:
                print(f"{os.path.basename(percorso_json)}: COPIATURA NEL TESTO "
                      f"{risultato['valutazione_robusta']['valori_copiati'][:4]}", flush=True)
            continue

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
                tutte_esatte = True
                for seme in semi:
                    v = valuta_su_variante(percorso_caso, gold, seme, risultato["query_generata"])
                    esiti.append({"seme": seme, "esatto": v["esatto"], "f1": v["f1"]})
                    if not v["esatto"]:
                        tutte_esatte = False
                robusta = {"esatto_robusto": tutte_esatte, "verificabile": True, "varianti": esiti}

        risultato["valutazione_robusta"] = robusta
        aggiungi_controllo_testo(risultato, percorsi_casi, cache_target)
        salva(percorso_json, risultato)
        aggiornati += 1
        if esatto:
            if robusta["esatto_robusto"]:
                stato = "ROBUSTO"
            else:
                stato = "NON ROBUSTO"
            if robusta["copiatura_nel_testo"]:
                stato += " (copiatura nel testo)"
            elif not robusta["verificabile"]:
                stato += " (non verificabile)"
            print(f"{os.path.basename(percorso_json)}: {stato}", flush=True)

    print(f"\nAggiornati {aggiornati} risultati.", flush=True)


def aggiungi_controllo_testo(risultato, percorsi_casi, cache_target):
    """Un risultato esatto che contiene i valori della tabella target scritti a mano non e' robusto."""
    robusta = risultato["valutazione_robusta"]
    robusta["copiatura_nel_testo"] = False
    if not e_esatto(risultato):
        return
    caso = risultato["caso"]
    if caso not in cache_target:
        cache_target[caso] = righe_target(percorsi_casi[caso])
    copiata, valori = valori_copiati(risultato.get("query_generata"), cache_target[caso])
    if copiata:
        robusta["copiatura_nel_testo"] = True
        robusta["valori_copiati"] = valori[:10]
        robusta["esatto_robusto"] = False


def salva(percorso_json, risultato):
    with open(percorso_json, "w", encoding="utf-8") as f:
        json.dump(risultato, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
