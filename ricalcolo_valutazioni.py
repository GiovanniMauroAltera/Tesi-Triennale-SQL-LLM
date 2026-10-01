"""Ricalcola la valutazione dei risultati gia' salvati rieseguendo la query memorizzata.

Non richiama nessun modello: utile quando cambia la logica di valuta_accuratezza.
"""
import contextlib
import glob
import io
import json
import os

from funzioni_comuni import carica_caso, esegui_e_stampa, valuta_accuratezza
from codice_benchmark import CARTELLA_RISULTATI, elenco_casi, id_caso


def main():
    percorsi_casi = {id_caso(p): p for p in elenco_casi()}
    aggiornati = 0
    for percorso_json in sorted(glob.glob(os.path.join(CARTELLA_RISULTATI, "*.json"))):
        with open(percorso_json, encoding="utf-8") as f:
            risultato = json.load(f)
        if risultato.get("query_generata") is None or risultato["caso"] not in percorsi_casi:
            continue

        conn, cursor, _, nome_target = carica_caso(percorsi_casi[risultato["caso"]])
        with contextlib.redirect_stdout(io.StringIO()):
            tabelle_create = esegui_e_stampa(cursor, risultato["query_generata"])
        risultato["valutazione"] = valuta_accuratezza(cursor, tabelle_create, nome_target)
        conn.close()

        with open(percorso_json, "w", encoding="utf-8") as f:
            json.dump(risultato, f, indent=2, ensure_ascii=False, default=str)
        aggiornati += 1
        v = risultato["valutazione"]
        print(f"{os.path.basename(percorso_json)}: esatto={'SI' if v['esatto'] else 'NO'} F1={v['f1'] * 100:.0f}%")

    print(f"\nRivalutati {aggiornati} risultati.")


if __name__ == "__main__":
    main()
