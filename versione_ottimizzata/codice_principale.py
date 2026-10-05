"""Ricostruisce la query SQL che trasforma le tabelle di partenza nella tabella finale.

Chiede la query a piu' modelli contemporaneamente, la esegue e tiene la prima che riproduce
davvero la tabella finale senza copiarne i valori.

Come si usa:
  python codice_principale.py --caso casi_BIRD/850_formula_1.sqlite
  python codice_principale.py --database dati.sqlite --partenza VENDITE_PC --finale TABELLA_FINALE_TARGET
  python codice_principale.py --caso ... --modelli gemma qwen3-4b --salva risultato.json
"""
import argparse
import json
import queue
import sys
import threading
import time

from modelli import MODELLI, MODELLI_DI_BASE, ModelloNonDisponibile, chiama
from prompt import estrai_sql, messaggi_iniziali, messaggio_di_correzione
from verifica import apri_database, leggi_info_caso, verifica

CORREZIONI = 2   # dopo la prima risposta, quante volte un modello puo' correggersi
TENTATIVI_PER_ERRORE_DI_RETE = 2
SECONDI_TRA_I_TENTATIVI = 10


# ---------------------------------------------------------------------------------------------------------
# Come si chiedono le query a piu' modelli insieme
# ---------------------------------------------------------------------------------------------------------
# Ogni richiesta a un modello parte in un "thread", cioe' un pezzo di programma che gira in parallelo agli
# altri: cosi' non si aspetta un modello prima di chiedere al successivo. Quando un thread ha la risposta la
# mette in una "coda" (queue.Queue), una lista sicura da usare da piu' thread insieme; il programma principale
# prende le risposte dalla coda una alla volta, nell'ordine in cui arrivano.

def chiedi_al_modello(modello, messaggi, risposte):
    """Gira in un thread: chiama il modello e mette la risposta (o l'errore) nella coda `risposte`."""
    inizio = time.time()
    messaggio_errore = ""
    for tentativo in range(1, TENTATIVI_PER_ERRORE_DI_RETE + 1):
        try:
            testo, tagliata = chiama(modello, messaggi)
            risposte.put({"modello": modello, "testo": testo, "troncata": tagliata, "secondi": time.time() - inizio})
            return
        except ModelloNonDisponibile as errore:
            messaggio_errore = str(errore)
            break  # quota finita o chiave mancante: inutile riprovare
        except Exception as errore:  # rete o server: vale la pena riprovare una volta
            messaggio_errore = str(errore)
            if tentativo < TENTATIVI_PER_ERRORE_DI_RETE:
                time.sleep(SECONDI_TRA_I_TENTATIVI)
    risposte.put({"modello": modello, "errore_chiamata": messaggio_errore, "secondi": time.time() - inizio})


def fai_partire(modello, messaggi, risposte):
    """Avvia la richiesta a un modello in un thread nuovo.

    daemon=True: se il programma finisce, i thread ancora in attesa di un modello lento si chiudono con lui
    invece di tenerlo aperto.
    """
    thread = threading.Thread(target=chiedi_al_modello, args=(modello, list(messaggi), risposte), daemon=True)
    thread.start()


def accettabile(esito):
    """La query riproduce la tabella finale senza copiarne i valori."""
    return esito["corretto"] and not esito["copiatura_sospetta"]


def descrivi(esito):
    """L'esito della verifica in una riga, da stampare."""
    if esito["errore"]:
        return f"query non valida ({esito['errore']})"
    if accettabile(esito):
        return "RIPRODUCE LA TABELLA FINALE"
    if esito["corretto"]:
        copiati = []
        for valore in esito["valori_copiati"][:3]:
            copiati.append(str(valore))
        return f"risultato giusto ma copiato dalla tabella finale ({', '.join(copiati)}...)"
    return (f"risultato sbagliato: {esito['righe_ottenute']} righe invece di {esito['righe_attese']}, "
            f"{esito['righe_giuste']} giuste (correttezza parziale {esito['correttezza_parziale']:.0%})")


def piu_vicina(proposte):
    """Tra le proposte verificate, la migliore: prima quelle accettabili, poi quelle giuste ma copiate,
    poi quella con la correttezza parziale piu' alta. None se nessuna e' stata verificata."""
    migliore = None
    punteggio_migliore = None
    for proposta in proposte:
        if "esito" not in proposta:
            continue  # il modello non ha risposto
        esito = proposta["esito"]
        punteggio = (accettabile(esito), esito["corretto"], esito["correttezza_parziale"])
        # Le tuple si confrontano un elemento alla volta: (True, ...) batte (False, ...).
        if punteggio_migliore is None or punteggio > punteggio_migliore:
            migliore = proposta
            punteggio_migliore = punteggio
    return migliore


def ricostruisci(conn, tabelle_di_partenza, tabella_finale, modelli, secondi_max, correzioni=CORREZIONI, messaggi=None):
    """Chiede la query a tutti i modelli insieme; a chi sbaglia spiega cosa non va e da' un altro tentativo.

    Si ferma alla prima query che riproduce la tabella finale senza copiarne i valori.
    Restituisce la proposta migliore e l'elenco di tutte le proposte ricevute.
    `messaggi`: i messaggi iniziali gia' pronti (li usa il metodo misto), altrimenti li prepara qui.
    """
    if not messaggi:
        messaggi = messaggi_iniziali(conn, tabelle_di_partenza, tabella_finale)
    conversazioni = {}  # modello -> i messaggi scambiati finora con lui
    tentativo = {}      # modello -> a che tentativo e' arrivato
    for modello in modelli:
        conversazioni[modello] = list(messaggi)
        tentativo[modello] = 1

    risposte = queue.Queue()
    for modello in modelli:
        fai_partire(modello, conversazioni[modello], risposte)
    in_attesa = len(modelli)  # quante risposte devono ancora arrivare
    inizio = time.time()
    proposte = []

    while in_attesa > 0:
        tempo_rimasto = max(0.1, secondi_max - (time.time() - inizio))
        try:
            risposta = risposte.get(timeout=tempo_rimasto)  # aspetta la prossima risposta, al massimo tempo_rimasto
        except queue.Empty:
            print(f"Tempo massimo ({secondi_max} s) scaduto: mi fermo con le risposte arrivate.")
            break
        in_attesa -= 1
        modello = risposta["modello"]
        risposta["tentativo"] = tentativo[modello]
        proposte.append(risposta)
        if "errore_chiamata" in risposta:
            print(f"[{time.time() - inizio:5.0f} s] {modello}: non risponde ({risposta['errore_chiamata'][:150]})")
            continue

        risposta["sql"] = estrai_sql(risposta["testo"])
        risposta["esito"] = verifica(conn, tabella_finale, risposta["sql"])
        avviso = ""
        if risposta["troncata"]:
            avviso = " (risposta tagliata perche' troppo lunga)"
        print(f"[{time.time() - inizio:5.0f} s] {modello} (tentativo {tentativo[modello]}): "
              f"{descrivi(risposta['esito'])}{avviso}", flush=True)
        if accettabile(risposta["esito"]):
            break  # gli altri modelli possono smettere: abbiamo una query verificata

        if tentativo[modello] <= correzioni:
            # Nella conversazione rimetto solo la query, non tutta la risposta: meno testo, stesso contenuto.
            conversazioni[modello].append({"role": "assistant", "content": f"```sql\n{risposta['sql']}\n```"})
            conversazioni[modello].append({"role": "user", "content": messaggio_di_correzione(risposta["esito"])})
            tentativo[modello] += 1
            fai_partire(modello, conversazioni[modello], risposte)
            in_attesa += 1

    return piu_vicina(proposte), proposte


def main():
    parser = argparse.ArgumentParser(description="Ricostruisce la query che porta dalle tabelle di partenza alla tabella finale.")
    parser.add_argument("--caso", help="file .sqlite di un caso (BIRD o caso dei PC): le tabelle le legge da solo")
    parser.add_argument("--database", help="un database SQLite qualsiasi")
    parser.add_argument("--partenza", nargs="+", help="le tabelle di partenza (con --database)")
    parser.add_argument("--finale", help="la tabella finale (con --database)")
    parser.add_argument("--modelli", nargs="+", choices=list(MODELLI), default=MODELLI_DI_BASE,
                        help="i modelli da interrogare in parallelo (di base quelli di MODELLI_DI_BASE)")
    parser.add_argument("--correzioni", type=int, default=CORREZIONI,
                        help="quante volte un modello puo' correggersi dopo la prima risposta (0 = nessuna)")
    parser.add_argument("--secondi-max", type=int, default=900, help="tempo massimo di attesa")
    parser.add_argument("--salva", help="file .json in cui salvare il risultato")
    argomenti = parser.parse_args()

    if argomenti.caso:
        conn = apri_database(argomenti.caso)
        partenza, finale = leggi_info_caso(conn)
    elif argomenti.database and argomenti.partenza and argomenti.finale:
        conn = apri_database(argomenti.database)
        partenza, finale = argomenti.partenza, argomenti.finale
    else:
        parser.error("indica --caso oppure --database con --partenza e --finale")

    print(f"Tabelle di partenza: {', '.join(partenza)}  ->  tabella finale: {finale}")
    print(f"Chiedo la query a: {', '.join(argomenti.modelli)}\n")
    inizio = time.time()
    migliore, proposte = ricostruisci(conn, partenza, finale, argomenti.modelli, argomenti.secondi_max,
                                      argomenti.correzioni)
    secondi = time.time() - inizio

    print()
    verificata = migliore is not None and accettabile(migliore["esito"])
    if migliore is None:
        print("Nessun modello ha dato una risposta utilizzabile.")
    else:
        if verificata:
            print(f"QUERY TROVATA ({migliore['modello']}, {secondi:.0f} s):\n")
        else:
            print(f"NESSUNA QUERY VERIFICATA, la migliore e' ({migliore['modello']}, {secondi:.0f} s):\n")
        print(migliore["sql"])
        if not verificata:
            print(f"\nAttenzione: {descrivi(migliore['esito'])}")

    if argomenti.salva:
        da_salvare = []
        for proposta in proposte:
            senza_testo = dict(proposta)
            senza_testo.pop("testo", None)  # il testo intero della risposta e' lungo e non serve
            da_salvare.append(senza_testo)
        nome_migliore = None
        if migliore:
            nome_migliore = migliore["modello"]
        with open(argomenti.salva, "w", encoding="utf-8") as f:
            json.dump({"secondi": round(secondi, 1), "migliore": nome_migliore, "proposte": da_salvare},
                      f, indent=2, ensure_ascii=False, default=str)
    if verificata:
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
