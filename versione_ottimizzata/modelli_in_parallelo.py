"""Seconda parte della versione ottimizzata: chiede la query a piu' modelli contemporaneamente.

Ogni risposta viene eseguita e confrontata con la tabella finale (verifica.py). A un modello che sbaglia
si spiega cosa non va (prompt.py) e gli si da' un altro tentativo; ci si ferma alla prima query che
riproduce davvero la tabella finale senza copiarne i valori. Lo usa versione_ottimizzata.py.
"""
import queue
import threading
import time

from modelli import ModelloNonDisponibile, chiama
from prompt import estrai_sql, messaggio_di_correzione
from verifica import verifica

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


def ricostruisci(conn, tabella_finale, messaggi, modelli, secondi_max, correzioni=CORREZIONI):
    """Chiede la query a tutti i modelli insieme; a chi sbaglia spiega cosa non va e da' un altro tentativo.

    `messaggi` e' la conversazione iniziale (il prompt preparato da versione_ottimizzata.py).
    Si ferma alla prima query che riproduce la tabella finale senza copiarne i valori.
    Restituisce la proposta migliore e l'elenco di tutte le proposte ricevute.
    """
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

