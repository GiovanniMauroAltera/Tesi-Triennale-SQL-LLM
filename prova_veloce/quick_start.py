"""Prova veloce: la versione ottimizzata su alcuni casi di esempio, senza scaricare niente.

Per ogni caso mostra le tabelle di partenza (Stato A) e la tabella finale (Stato B), poi cerca la query che
porta dall'una all'altra e la confronta con la query vera. I casi sono quelli di questa cartella (tre casi
presi da BIRD) piu' il caso dei PC.

Senza modelli usa solo il programma che cerca i filtri (la prima parte della versione ottimizzata): funziona
subito, in pochi secondi, senza chiavi e senza Ollama. Con --modelli usa la versione ottimizzata completa:
il programma cerca i filtri e il modello sceglie quello che ha senso e scrive la query, aggiungendo i calcoli.

Come si usa (dalla cartella principale della repository):
  python prova_veloce/quick_start.py
  python prova_veloce/quick_start.py --caso 781_superhero
  python prova_veloce/quick_start.py --modelli qwen3-4b         (serve Ollama con qwen3:4b-instruct)
  python prova_veloce/quick_start.py --modelli gpt-oss-120b     (serve una chiave gratuita di Groq)
"""
import argparse
import glob
import os
import sys
import time

# Il codice della versione ottimizzata e' nella cartella versione_ottimizzata/, accanto a questa.
CARTELLA = os.path.dirname(os.path.abspath(__file__))
REPOSITORY = os.path.dirname(CARTELLA)
sys.path.insert(0, os.path.join(REPOSITORY, "versione_ottimizzata"))
from codice_benchmark_ottimizzato import SQL_GOLD_PC  # noqa: E402
from modelli import MODELLI  # noqa: E402
from modelli_in_parallelo import accettabile, descrivi  # noqa: E402
from prompt import righe_come_testo  # noqa: E402
from ricerca_filtri import cerca_filtri  # noqa: E402
from verifica import apri_database, colonne_di, leggi_info_caso, leggi_righe, nome_sql  # noqa: E402
from versione_ottimizzata import (MAX_SUGGERIMENTI, SECONDI_RICERCA, SUGGERIMENTI_PER_LIVELLO,  # noqa: E402
                                  ricostruisci_misto)

CASO_PC = os.path.join(REPOSITORY, "caso_PC", "pc_multivaluta.sqlite")
RIGHE_FINALI_MOSTRATE = 5


def casi_di_esempio():
    """I file dei casi: quelli di questa cartella e il caso dei PC."""
    casi = sorted(glob.glob(os.path.join(CARTELLA, "*.sqlite")))
    casi.append(CASO_PC)
    return casi


def nome_del_caso(percorso):
    return os.path.basename(percorso)[:-len(".sqlite")]


def domanda_e_query_vera(conn, percorso):
    """La domanda di BIRD e la query vera. Il programma e i modelli non le vedono mai: servono solo a noi."""
    if percorso == CASO_PC:
        return "Qual e' il prezzo medio in dollari di ogni modello di PC?", SQL_GOLD_PC
    domanda, query_vera = conn.execute("SELECT question, sql_gold FROM _bird_info").fetchone()
    return domanda, query_vera


def mostra_il_caso(conn, partenza, finale):
    print("STATO A - tabelle di partenza:")
    for tabella in partenza:
        quante = conn.execute(f"SELECT COUNT(*) FROM {nome_sql(tabella)}").fetchone()[0]
        print(f"  {tabella}: {quante} righe; colonne: {', '.join(colonne_di(conn, tabella))}")
    quante = conn.execute(f"SELECT COUNT(*) FROM {nome_sql(finale)}").fetchone()[0]
    colonne, righe = leggi_righe(conn, nome_sql(finale), RIGHE_FINALI_MOSTRATE)
    print(f"STATO B - tabella finale ({quante} righe; colonne: {', '.join(colonne)}):")
    for riga in righe_come_testo(righe).split("\n"):
        print("  " + riga)
    if quante > RIGHE_FINALI_MOSTRATE:
        print("  ...")


def solo_il_programma(conn, partenza, finale):
    """La prima parte della versione ottimizzata: il programma cerca i filtri, senza modelli."""
    inizio = time.time()
    trovate, provate = cerca_filtri(conn, partenza, finale, SECONDI_RICERCA, quanti=MAX_SUGGERIMENTI,
                                    per_livello=SUGGERIMENTI_PER_LIVELLO)
    print(f"\nIn {time.time() - inizio:.1f} s il programma ha trovato {len(trovate)} regole che selezionano "
          f"esattamente le righe giuste:")
    for numero, trovata in enumerate(trovate, start=1):
        if trovata["completa"]:
            nota = ""
        else:
            nota = "; solo il filtro, le colonne calcolate mancano"
        print(f"  {numero}. {trovata['sql']}   (regola: {trovata['livello']}{nota})")
    for trovata in trovate:
        if trovata["completa"] and accettabile(trovata["esito"]):
            return trovata["sql"]
    return None


def con_i_modelli(conn, partenza, finale, modelli):
    """La versione ottimizzata completa: il programma propone i filtri, i modelli scelgono e scrivono la query."""
    print()
    migliore, proposte, trovate = ricostruisci_misto(conn, partenza, finale, modelli, 600)
    if migliore is None:
        print("Nessun modello ha dato una query (i motivi sono nei messaggi qui sopra).")
        return None
    if not accettabile(migliore["esito"]):
        print(f"La query migliore non e' verificata: {descrivi(migliore['esito'])}")
        return None
    print(f"Query scritta da: {migliore['modello']}")
    return migliore["sql"]


def prova_un_caso(percorso, modelli):
    conn = apri_database(percorso)
    partenza, finale = leggi_info_caso(conn)
    domanda, query_vera = domanda_e_query_vera(conn, percorso)
    print("=" * 100)
    print(f"CASO {nome_del_caso(percorso)}")
    print(f"La domanda (il programma non la vede): {domanda}\n")
    mostra_il_caso(conn, partenza, finale)
    if modelli:
        query = con_i_modelli(conn, partenza, finale, modelli)
    else:
        query = solo_il_programma(conn, partenza, finale)
    print()
    if query is None:
        print("NESSUNA QUERY VERIFICATA.")
        if not modelli:
            print("Il programma da solo non sa fare calcoli (somme, medie, conversioni): per questo caso serve un "
                  "modello, vedi --modelli.")
        elif percorso == CASO_PC:
            print("Nelle prove della tesi il caso dei PC l'ha risolto solo Gemma 4 31B (--modelli gemma, serve una "
                  "chiave gratuita di Google AI Studio).")
    else:
        print("QUERY TROVATA (riproduce la tabella finale senza copiarla):")
        for riga in query.strip().split("\n"):
            print("  " + riga)
    print(f"\nLa query vera, per confronto:\n  {' '.join(query_vera.split())}\n")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Prova veloce della versione ottimizzata sui casi di esempio.")
    nomi = []
    for percorso in casi_di_esempio():
        nomi.append(nome_del_caso(percorso))
    parser.add_argument("--caso", choices=nomi, help="un solo caso (di base tutti)")
    parser.add_argument("--modelli", nargs="+", choices=list(MODELLI),
                        help="i modelli da usare (di base nessuno: solo il programma che cerca i filtri)")
    argomenti = parser.parse_args()
    for percorso in casi_di_esempio():
        if argomenti.caso is None or argomenti.caso == nome_del_caso(percorso):
            prova_un_caso(percorso, argomenti.modelli)


if __name__ == "__main__":
    main()
