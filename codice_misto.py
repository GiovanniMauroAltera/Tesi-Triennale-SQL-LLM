"""Metodo D misto: prima un programma cerca i filtri possibili, poi il modello sceglie quello sensato.

1. Il programma (codice_ricerca_noLLM.py) prova in pochi secondi migliaia di regole semplici e tiene
   quelle che selezionano esattamente le righe da cui nasce la tabella finale.
2. Il modello riceve il solito prompt con gli indizi piu' queste query, sceglie la regola che ha senso
   e scrive la query completa, aggiungendo i calcoli se servono. La query viene verificata e, se e'
   sbagliata, il modello puo' correggerla come nel codice principale.
3. Se il modello non ci riesce, resta la query del programma (se ne ha trovata una completa).

Perche' insieme: il programma e' velocissimo ma non sa fare calcoli e a volte trova una regola che
funziona per coincidenza (un intervallo di CAP al posto dello stato); il modello capisce il significato
delle colonne, ma da solo spesso non trova il filtro giusto.

Come si usa:
  python codice_misto.py --caso casi_BIRD/1334_student_club.sqlite --modelli qwen3-4b
  python codice_misto.py --database dati.sqlite --partenza A B --finale C
"""
import argparse
import sys
import time

from codice_principale import CORREZIONI, _accettabile, _descrivi, ricostruisci
from codice_ricerca_noLLM import cerca_filtri
from modelli import MODELLI
from prompt import messaggi_iniziali
from verifica import apri_database, leggi_info_caso

SECONDI_RICERCA = 60
MAX_SUGGERIMENTI = 12
SUGGERIMENTI_PER_LIVELLO = 2   # regole di tipo diverso, non dieci varianti della stessa


def descrivi_suggerimenti(trovate):
    if not trovate:
        return ("Il programma non ha trovato nessun filtro semplice che selezioni le righe dello STATO B: probabilmente "
                "servono calcoli (conteggi, somme, medie, conversioni) o condizioni piu' complicate.")
    righe = []
    for n, trovata in enumerate(trovate, 1):
        nota = ("riproduce gia' lo STATO B" if trovata["completa"]
                else "seleziona le righe giuste, ma le colonne calcolate vanno ancora aggiunte")
        righe.append(f"{n}. {trovata['sql']}\n   -- regola: {trovata['livello']}; {nota}")
    return ("Un programma ha provato in automatico molti filtri sulle tabelle di partenza. Queste query selezionano "
            "esattamente le righe da cui nasce lo STATO B:\n" + "\n".join(righe) + "\n"
            "Attenzione: alcune funzionano solo per coincidenza (per esempio un identificativo o un intervallo di numeri "
            "che per caso contiene solo le righe giuste). Scegli la regola che ha piu' senso per il significato delle "
            "colonne (i limiti numerici sono il minimo e il massimo trovati nei dati: la regola vera puo' usare un numero "
            "piu' tondo). Se servono calcoli, aggiungili tu. Non aggiungere condizioni, ORDER BY o LIMIT che non servono: "
            "un LIMIT con il numero di righe dello STATO B e' come copiarlo.")


def ricostruisci_misto(conn, tabelle_di_partenza, tabella_finale, modelli, secondi_max, correzioni=CORREZIONI):
    """Come ricostruisci() del codice principale, ma con i suggerimenti del programma nel prompt.

    Restituisce (migliore, proposte, trovate): `trovate` sono le query proposte dal programma.
    """
    inizio = time.time()
    trovate, _ = cerca_filtri(conn, tabelle_di_partenza, tabella_finale, SECONDI_RICERCA, quanti=MAX_SUGGERIMENTI,
                              solo_complete=False, per_livello=SUGGERIMENTI_PER_LIVELLO)
    print(f"[{time.time() - inizio:5.0f} s] programma: {len(trovate)} regole che selezionano le righe giuste", flush=True)
    messaggi = messaggi_iniziali(conn, tabelle_di_partenza, tabella_finale, descrivi_suggerimenti(trovate))
    rimasti = max(1, secondi_max - (time.time() - inizio))
    migliore, proposte = ricostruisci(conn, tabelle_di_partenza, tabella_finale, modelli, rimasti, correzioni, messaggi)
    complete = [t for t in trovate if t["completa"]]
    if complete and (migliore is None or not _accettabile(migliore["esito"])):
        # Il modello non ce l'ha fatta: resta la prima query del programma, che riproduce la tabella finale.
        migliore = {"modello": "programma", "sql": complete[0]["sql"], "esito": complete[0]["esito"], "tentativo": 0}
        proposte.append(migliore)
    return migliore, proposte, trovate


def main():
    parser = argparse.ArgumentParser(description="Metodo misto: il programma propone i filtri, il modello sceglie e completa.")
    parser.add_argument("--caso", help="file .sqlite di un caso (BIRD o caso dei PC)")
    parser.add_argument("--database", help="un database SQLite qualsiasi")
    parser.add_argument("--partenza", nargs="+", help="le tabelle di partenza (con --database)")
    parser.add_argument("--finale", help="la tabella finale (con --database)")
    parser.add_argument("--modelli", nargs="+", choices=list(MODELLI), default=list(MODELLI))
    parser.add_argument("--correzioni", type=int, default=CORREZIONI)
    parser.add_argument("--secondi-max", type=int, default=900)
    argomenti = parser.parse_args()
    if argomenti.caso:
        conn = apri_database(argomenti.caso)
        partenza, finale = leggi_info_caso(conn)
    elif argomenti.database and argomenti.partenza and argomenti.finale:
        conn = apri_database(argomenti.database)
        partenza, finale = argomenti.partenza, argomenti.finale
    else:
        parser.error("indica --caso oppure --database con --partenza e --finale")

    print(f"Tabelle di partenza: {', '.join(partenza)}  ->  tabella finale: {finale}\n")
    inizio = time.time()
    migliore, _, _ = ricostruisci_misto(conn, partenza, finale, argomenti.modelli, argomenti.secondi_max,
                                        argomenti.correzioni)
    secondi = time.time() - inizio
    print()
    if migliore is None:
        print("Nessuna query: il programma non ha trovato regole e nessun modello ha risposto.")
        sys.exit(1)
    verificata = _accettabile(migliore["esito"])
    print(("QUERY TROVATA" if verificata else "NESSUNA QUERY VERIFICATA, la migliore e'")
          + f" ({migliore['modello']}, {secondi:.0f} s):\n\n{migliore['sql']}")
    if not verificata:
        print(f"\nAttenzione: {_descrivi(migliore['esito'])}")
    sys.exit(0 if verificata else 1)


if __name__ == "__main__":
    main()
