"""Prende da BIRD i 90 casi nuovi, quelli mai usati per mettere a punto la versione ottimizzata.

Usa le funzioni di estrazione_casi_BIRD.py della versione originale, con gli stessi criteri (al massimo 2
tabelle di partenza, risultato non ridotto a un solo numero) tranne il limite sulla lunghezza del prompt,
che serviva ai modelli della versione originale. Tiene solo i casi con tabelle di partenza fino a 400.000
righe, per avere file di dimensioni ragionevoli. I 30 casi originali vengono esclusi.

I casi sono scelti in quattro gruppi, sempre nello stesso ordine (seme 42, come per i 30 originali):
  - tutti i casi "simple" rimasti (sono 15);
  - 30 casi "moderate";
  - altri 30 casi "moderate";
  - 15 casi "challenging".
Finiscono in casi_BIRD_nuovi/, che come casi_BIRD/ non e' su GitHub.

Come si usa (dalla cartella principale della repository, con BIRD Mini-Dev in bird-mini-dev/):
  python versione_ottimizzata/codice_estrazione_casi_nuovi.py
  python versione_ottimizzata/codice_estrazione_casi_nuovi.py --solo-elenco    (scrive solo quali casi sceglie)
"""
import argparse
import json
import os
import sqlite3
import sys

CARTELLA_ORIGINALE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "versione_originale")
sys.path.insert(0, CARTELLA_ORIGINALE)
import estrazione_casi_BIRD as estrazione  # noqa: E402  (lo script di estrazione della versione originale)

CARTELLA_USCITA = "casi_BIRD_nuovi"
MAX_RIGHE_SORGENTE = 400_000  # i 30 casi originali arrivano a 48 MB: oltre questo limite i file diventano enormi
GRUPPI = [("simple", 30), ("moderate", 30), ("moderate", 30), ("challenging", 15)]


def righe_totali(candidato):
    """Quante righe hanno in tutto le tabelle di partenza di un caso."""
    db_id = candidato["esempio"]["db_id"]
    conn = sqlite3.connect(os.path.join(estrazione.CARTELLA_DB, db_id, f"{db_id}.sqlite"))
    totale = 0
    for tabella in candidato["tabelle"]:
        totale += conn.execute(f'SELECT COUNT(*) FROM "{tabella}"').fetchone()[0]
    conn.close()
    return totale


def main():
    parser = argparse.ArgumentParser(description="Estrae da BIRD i 90 casi nuovi per la versione ottimizzata.")
    parser.add_argument("--solo-elenco", action="store_true", help="scrive solo quali casi sceglie, senza crearli")
    argomenti = parser.parse_args()

    # Esclusi i 30 casi originali (dal loro elenco, cosi' non servono i file .sqlite).
    with open(os.path.join("casi_BIRD", "_manifest.json"), encoding="utf-8") as f:
        gia_usati = set()
        for caso in json.load(f)["riusciti"]:
            gia_usati.add(caso["question_id"])
    with open(estrazione.PERCORSO_JSON, encoding="utf-8") as f:
        tutti_gli_esempi = json.load(f)

    scelti = []
    for difficolta, quanti in GRUPPI:
        esempi = []
        for esempio in tutti_gli_esempi:
            if esempio["question_id"] not in gia_usati:
                esempi.append(esempio)
        # None = nessun limite sulla lunghezza del prompt: serviva ai contesti piccoli dei modelli della
        # versione originale, il prompt della versione ottimizzata si adatta da solo.
        candidati = []
        for candidato in estrazione.filtra_candidati(esempi, difficolta, None):
            if righe_totali(candidato) <= MAX_RIGHE_SORGENTE:
                candidati.append(candidato)
        # Stesso ordine di scelta dell'estrazione originale: prima i risultati di piu' righe, seme 42.
        del_gruppo = estrazione.seleziona(candidati)[:quanti]
        print(f"{difficolta}: {len(candidati)} candidati, ne prendo {len(del_gruppo)}", flush=True)
        for candidato in del_gruppo:
            gia_usati.add(candidato["esempio"]["question_id"])
            scelti.append(candidato)

    for candidato in scelti:
        esempio = candidato["esempio"]
        if argomenti.solo_elenco:
            print(f"{esempio['question_id']}_{esempio['db_id']}  ({esempio['difficulty']})")
        else:
            print("OK", estrazione.estrai_caso(esempio, candidato["tabelle"], CARTELLA_USCITA), flush=True)
    print(f"{len(scelti)} casi nuovi")


if __name__ == "__main__":
    main()
