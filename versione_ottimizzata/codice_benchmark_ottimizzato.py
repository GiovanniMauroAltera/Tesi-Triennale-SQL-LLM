"""Fa girare la versione ottimizzata su tutti i casi e salva i risultati, come codice_benchmark.py per l'originale.

Ogni modello viene provato da solo (cosi' si vede quanto vale ciascuno), una o piu' volte per caso. Per ogni
prova salva in versione_ottimizzata/risultati_benchmark/ un file .json con: la query finale, se riproduce la
tabella finale, se copia a mano i valori della tabella finale, se regge sui dati modificati (lo stesso
controllo della versione originale: 3 copie dei dati con il 30% delle righe tolte a caso, stessi semi), chi
ha scritto la query (il modello o il programma) e il tempo.

Se si interrompe riparte da dove era rimasto. Le prove fallite per colpa del fornitore (server sovraccarico,
quota giornaliera finita) non vengono salvate: si rifanno lanciando di nuovo lo script piu' tardi.

Come si usa (dalla cartella principale della repository):
  python versione_ottimizzata/codice_benchmark_ottimizzato.py --modelli qwen3-4b --prove 4
  python versione_ottimizzata/codice_benchmark_ottimizzato.py --modelli gemma --casi nuovi
"""
import argparse
import glob
import json
import os
import random
import time

from modelli import MODELLI, MODELLI_DI_BASE
from verifica import apri_database, confronta, copia_per_il_modello, esegui, leggi_info_caso, leggi_righe, nome_sql
from versione_ottimizzata import ricostruisci_misto

CARTELLA_RISULTATI = os.path.join("versione_ottimizzata", "risultati_benchmark")
CASO_PC = os.path.join("caso_PC", "pc_multivaluta.sqlite")
# Come nella versione originale: per il caso dei PC la "query vera" e' la trasformazione che ho usato per crearlo.
SQL_GOLD_PC = """SELECT VENDITE_PC.Modello AS Modello_PC,
       AVG(VENDITE_PC.Prezzo_Locale * CASE VENDITE_PC.Valuta_Locale
           WHEN 'EUR' THEN 1.08 WHEN 'GBP' THEN 1.25 WHEN 'JPY' THEN 0.0065 END) AS Prezzo_Medio_USD
FROM VENDITE_PC GROUP BY VENDITE_PC.Modello"""

# Controllo sui dati modificati, uguale a quello della versione originale (controllo_copiatura.py).
N_VARIANTI = 3
FRAZIONE_TOLTA = 0.3
MAX_TENTATIVI_VARIANTE = 20


def firma(righe):
    """Le righe in un ordine fisso, per confrontare due risultati senza badare all'ordine."""
    testi = []
    for riga in righe:
        testi.append(repr(riga))
    testi.sort()
    return testi


def elenco_casi(quali):
    """I casi originali (i 30 di BIRD e quello dei PC) oppure i 90 casi nuovi."""
    if quali == "nuovi":
        return sorted(glob.glob(os.path.join("casi_BIRD_nuovi", "*.sqlite")))
    return [CASO_PC] + sorted(glob.glob(os.path.join("casi_BIRD", "*.sqlite")))


def togli_righe(conn, tabelle, seme):
    """Toglie a caso il 30% delle righe di ogni tabella di partenza (sempre le stesse, dato il seme)."""
    generatore = random.Random(seme)
    for tabella in tabelle:
        numeri_di_riga = []
        for riga in conn.execute(f"SELECT rowid FROM {nome_sql(tabella)}"):
            numeri_di_riga.append(riga[0])
        da_togliere = generatore.sample(numeri_di_riga, int(len(numeri_di_riga) * FRAZIONE_TOLTA))
        for numero in da_togliere:
            conn.execute(f"DELETE FROM {nome_sql(tabella)} WHERE rowid = ?", (numero,))


def regge_sui_dati_modificati(percorso, query):
    """True se la query da' lo stesso risultato della query vera anche sui dati modificati, False se no,
    None se nessuna variante cambia il risultato della query vera (allora non si puo' controllare)."""
    base = apri_database(percorso)
    partenza, finale = leggi_info_caso(base)
    if os.path.normpath(percorso) == os.path.normpath(CASO_PC):
        query_vera = SQL_GOLD_PC
    else:
        query_vera = base.execute("SELECT sql_gold FROM _bird_info").fetchone()[0].strip().rstrip(";")
    colonne_finali, righe_finali = leggi_righe(base, nome_sql(finale))
    originale = firma(righe_finali)
    esiti = []
    for k in range(MAX_TENTATIVI_VARIANTE):
        seme = f"{os.path.basename(percorso)[:-7]}-{k}"
        variante = copia_per_il_modello(base, finale)
        togli_righe(variante, partenza, seme)
        righe_vere = variante.execute(query_vera).fetchall()
        # Serve una variante in cui il risultato vero cambia: altrimenti anche una copia passerebbe.
        if not righe_vere or firma(righe_vere) == originale:
            continue
        try:
            colonne, righe, totale = esegui(variante, query)
            esiti.append(confronta(righe, righe_vere, totale)["corretto"])
        except ValueError:
            esiti.append(False)
        if len(esiti) == N_VARIANTI:
            break
    if not esiti:
        return None
    for esito in esiti:
        if not esito:
            return False
    return True


def misura_un_modello(modello, casi, prove, secondi_max, correzioni):
    """Fa girare la versione ottimizzata con un solo modello. Restituisce False se il fornitore non risponde."""
    errori_di_fila = 0
    for prova in range(1, prove + 1):
        for percorso in casi:
            caso = os.path.basename(percorso)[:-7]
            destinazione = os.path.join(CARTELLA_RISULTATI, f"{caso}__{modello}__prova{prova}.json")
            if os.path.exists(destinazione):
                continue
            conn = apri_database(percorso)
            partenza, finale = leggi_info_caso(conn)
            inizio = time.time()
            migliore, proposte, trovate = ricostruisci_misto(conn, partenza, finale, [modello], secondi_max, correzioni)
            secondi = time.time() - inizio

            ha_risposto = False
            errore_del_fornitore = None
            for proposta in proposte:
                if proposta.get("modello") == modello and "esito" in proposta:
                    ha_risposto = True
                if "errore_chiamata" in proposta:
                    errore_del_fornitore = proposta["errore_chiamata"]
            if not ha_risposto and (errore_del_fornitore or MODELLI[modello]["fornitore"] != "ollama"):
                # Colpa del fornitore: niente file, la prova si rifa' lanciando di nuovo lo script.
                errore = "nessuna risposta"
                if errore_del_fornitore:
                    errore = errore_del_fornitore
                print(f"SALTATO {caso} {modello}: {errore[:150]}", flush=True)
                if "quota giornaliera" in errore:
                    print("QUOTA FINITA: per oggi mi fermo con questo modello", flush=True)
                    return False
                errori_di_fila += 1
                if errori_di_fila >= 2:
                    # Server sovraccarico: continuare consumerebbe le richieste gratuite senza risultati.
                    print("ERRORI DI FILA: il fornitore non risponde, riprova piu' tardi", flush=True)
                    return False
                continue
            errori_di_fila = 0

            suggerimenti = []
            for trovata in trovate:
                suggerimenti.append(trovata["sql"])
            risultato = {"caso": caso, "modello": modello, "prova": prova, "secondi": secondi,
                         "suggerimenti": suggerimenti}
            if migliore is None:
                # Un modello sul computer che non risponde entro il tempo massimo ha fallito il caso.
                risultato.update({"sql": None, "corretto": False, "copiatura_nel_testo": False,
                                  "correttezza_parziale": 0.0, "errore_sql": "tempo massimo scaduto", "troncata": None,
                                  "tentativi": 0, "risolto_da": modello, "regge_dati_modificati": False})
            else:
                esito = migliore["esito"]
                risultato.update({"sql": migliore["sql"], "corretto": esito["corretto"],
                                  "copiatura_nel_testo": esito["copiatura_sospetta"],
                                  "correttezza_parziale": esito["correttezza_parziale"], "errore_sql": esito["errore"],
                                  "troncata": migliore.get("troncata"), "tentativi": migliore.get("tentativo", 1),
                                  "risolto_da": migliore["modello"]})
                if esito["corretto"]:
                    risultato["regge_dati_modificati"] = regge_sui_dati_modificati(percorso, migliore["sql"])
                else:
                    risultato["regge_dati_modificati"] = False
            with open(destinazione, "w", encoding="utf-8") as f:
                json.dump(risultato, f, indent=2, ensure_ascii=False, default=str)
            print(f"PROVA {prova} {caso} {modello}: corretto={risultato['corretto']} "
                  f"copiato={risultato['copiatura_nel_testo']} regge={risultato['regge_dati_modificati']} "
                  f"({secondi:.0f} s)", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description="Misura la versione ottimizzata su tutti i casi.")
    parser.add_argument("--modelli", nargs="+", choices=list(MODELLI), default=MODELLI_DI_BASE,
                        help="i modelli da misurare, uno alla volta (di base quelli di MODELLI_DI_BASE)")
    parser.add_argument("--casi", choices=["originali", "nuovi"], default="originali",
                        help="i 30 casi di BIRD piu' quello dei PC, oppure i 90 casi nuovi")
    parser.add_argument("--prove", type=int, default=1, help="quante volte provare ogni caso")
    parser.add_argument("--correzioni", type=int, default=0,
                        help="tentativi di correzione per modello (nelle misure del README: 0)")
    parser.add_argument("--secondi-max", type=int, default=900, help="tempo massimo per un caso")
    argomenti = parser.parse_args()
    os.makedirs(CARTELLA_RISULTATI, exist_ok=True)
    casi = elenco_casi(argomenti.casi)
    for modello in argomenti.modelli:
        print(f"== {modello}: {len(casi)} casi, {argomenti.prove} prove", flush=True)
        misura_un_modello(modello, casi, argomenti.prove, argomenti.secondi_max, argomenti.correzioni)
    print("MISURA FINITA", flush=True)


if __name__ == "__main__":
    main()
