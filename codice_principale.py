"""Ricostruisce la query SQL che trasforma le tabelle di partenza nella tabella finale.

Chiede la query a piu' modelli contemporaneamente, la esegue e tiene la prima che riproduce
davvero la tabella finale senza copiarne i valori.

Come si usa:
  python codice_principale.py --caso casi_BIRD/850_formula_1.sqlite
  python codice_principale.py --database dati.sqlite --partenza VENDITE_PC --finale TABELLA_FINALE_TARGET
  python codice_principale.py --caso ... --modelli gemma qwen2.5-coder-7b --salva risultato.json
"""
import argparse
import json
import queue
import sys
import threading
import time

from modelli import MODELLI, ModelloNonDisponibile, chiama
from prompt import estrai_sql, messaggi_iniziali, messaggio_di_correzione
from verifica import apri_database, leggi_info_caso, verifica

CORREZIONI = 2   # dopo la prima risposta, quante volte un modello puo' correggersi
TENTATIVI_PER_ERRORE_DI_RETE = 2
SECONDI_TRA_I_TENTATIVI = 10


def chiedi_al_modello(modello, messaggi, risposte):
    """Gira in un thread: chiama il modello e mette la risposta (o l'errore) nella coda."""
    inizio = time.time()
    messaggio_errore = ""
    for tentativo in range(1, TENTATIVI_PER_ERRORE_DI_RETE + 1):
        try:
            testo, troncata = chiama(modello, messaggi)
            risposte.put({"modello": modello, "testo": testo, "troncata": troncata, "secondi": time.time() - inizio})
            return
        except ModelloNonDisponibile as errore:
            messaggio_errore = str(errore)
            break
        except Exception as errore:  # rete o server: vale la pena riprovare una volta
            messaggio_errore = str(errore)
            if tentativo < TENTATIVI_PER_ERRORE_DI_RETE:
                time.sleep(SECONDI_TRA_I_TENTATIVI)
    risposte.put({"modello": modello, "errore_chiamata": messaggio_errore, "secondi": time.time() - inizio})


def _accettabile(esito):
    return esito["corretto"] and not esito["copiatura_sospetta"]


def _descrivi(esito):
    if esito["errore"]:
        return f"query non valida ({esito['errore']})"
    if _accettabile(esito):
        return "RIPRODUCE LA TABELLA FINALE"
    if esito["corretto"]:
        return f"risultato giusto ma copiato dalla tabella finale ({', '.join(map(str, esito['valori_copiati'][:3]))}...)"
    return (f"risultato sbagliato: {esito['righe_ottenute']} righe invece di {esito['righe_attese']}, "
            f"{esito['righe_giuste']} giuste (correttezza parziale {esito['correttezza_parziale']:.0%})")


def ricostruisci(conn, tabelle_di_partenza, tabella_finale, modelli, secondi_max, correzioni=CORREZIONI):
    """Chiede la query a tutti i modelli insieme; a chi sbaglia spiega cosa non va e da' un altro tentativo.

    Si ferma alla prima query che riproduce la tabella finale senza copiarne i valori.
    Restituisce la proposta migliore e l'elenco di tutte le proposte ricevute.
    """
    conversazioni = {m: messaggi_iniziali(conn, tabelle_di_partenza, tabella_finale) for m in modelli}
    tentativo = {m: 1 for m in modelli}
    risposte = queue.Queue()

    def lancia(modello):
        threading.Thread(target=chiedi_al_modello, args=(modello, list(conversazioni[modello]), risposte),
                         daemon=True).start()

    for modello in modelli:
        lancia(modello)
    in_attesa, inizio, proposte = len(modelli), time.time(), []
    while in_attesa:
        try:
            risposta = risposte.get(timeout=max(0.1, secondi_max - (time.time() - inizio)))
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
        print(f"[{time.time() - inizio:5.0f} s] {modello} (tentativo {tentativo[modello]}): {_descrivi(risposta['esito'])}"
              + (" (risposta tagliata perche' troppo lunga)" if risposta["troncata"] else ""), flush=True)
        if _accettabile(risposta["esito"]):
            break  # gli altri modelli possono smettere: abbiamo una query verificata
        if tentativo[modello] <= correzioni:
            # Nella conversazione rimetto solo la query, non tutta la risposta: meno testo, stesso contenuto.
            conversazioni[modello] += [{"role": "assistant", "content": f"```sql\n{risposta['sql']}\n```"},
                                       {"role": "user", "content": messaggio_di_correzione(risposta["esito"])}]
            tentativo[modello] += 1
            lancia(modello)
            in_attesa += 1

    valide = [p for p in proposte if "esito" in p]
    migliore = max(valide, key=lambda p: (_accettabile(p["esito"]), p["esito"]["corretto"],
                                         p["esito"]["correttezza_parziale"]), default=None)
    return migliore, proposte


def main():
    parser = argparse.ArgumentParser(description="Ricostruisce la query che porta dalle tabelle di partenza alla tabella finale.")
    parser.add_argument("--caso", help="file .sqlite di un caso (BIRD o caso dei PC): le tabelle le legge da solo")
    parser.add_argument("--database", help="un database SQLite qualsiasi")
    parser.add_argument("--partenza", nargs="+", help="le tabelle di partenza (con --database)")
    parser.add_argument("--finale", help="la tabella finale (con --database)")
    parser.add_argument("--modelli", nargs="+", choices=list(MODELLI), default=list(MODELLI),
                        help="i modelli da interrogare in parallelo (di base tutti)")
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
    if migliore is None:
        print("Nessun modello ha dato una risposta utilizzabile.")
    else:
        verificata = _accettabile(migliore["esito"])
        print(("QUERY TROVATA" if verificata else "NESSUNA QUERY VERIFICATA, la migliore e'")
              + f" ({migliore['modello']}, {secondi:.0f} s):\n")
        print(migliore["sql"])
        if not verificata:
            print(f"\nAttenzione: {_descrivi(migliore['esito'])}")

    if argomenti.salva:
        with open(argomenti.salva, "w", encoding="utf-8") as f:
            json.dump({"secondi": round(secondi, 1), "migliore": migliore["modello"] if migliore else None,
                       "proposte": [{k: v for k, v in p.items() if k != "testo"} for p in proposte]},
                      f, indent=2, ensure_ascii=False, default=str)
    sys.exit(0 if migliore and _accettabile(migliore["esito"]) else 1)


if __name__ == "__main__":
    main()
