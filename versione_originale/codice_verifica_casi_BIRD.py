"""Controlla i casi estratti da BIRD: la query vera di ogni caso deve riprodurre esattamente la sua tabella finale.

Come si usa (dalla cartella principale della repository):
  python versione_originale/codice_verifica_casi_BIRD.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from funzioni_comuni import carica_caso, esegui_e_stampa, valuta_accuratezza

CARTELLA_CASI = "casi_BIRD"

with open(os.path.join(CARTELLA_CASI, "_manifest.json"), encoding="utf-8") as f:
    manifest = json.load(f)

falliti = []
for voce in manifest["riusciti"]:
    percorso = voce["percorso"]
    conn, cursor, nomi_sorgente, nome_target = carica_caso(percorso)

    cursor.execute("SELECT sql_gold FROM _bird_info")
    sql_gold = cursor.fetchone()[0].strip().rstrip(";")

    query_verifica = f"CREATE TEMP TABLE verifica AS\n{sql_gold};"
    tabelle_create = esegui_e_stampa(cursor, query_verifica)
    risultato = valuta_accuratezza(cursor, tabelle_create, nome_target)

    if risultato["esatto"]:
        stato = "OK"
    else:
        stato = "FALLITO"
    print(f"[{stato}] {voce['question_id']} ({voce['db_id']}): esatto={risultato['esatto']} F1={risultato['f1']*100:.1f}% errore={risultato['errore']}")
    if not risultato["esatto"]:
        falliti.append(voce)

    conn.close()

print(f"\n{len(manifest['riusciti']) - len(falliti)}/{len(manifest['riusciti'])} casi verificati correttamente.")
if falliti:
    numeri = []
    for voce in falliti:
        numeri.append(voce["question_id"])
    print("Casi falliti:", numeri)
