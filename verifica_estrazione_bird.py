import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.pipeline import carica_caso, esegui_e_stampa, valuta_accuratezza

CARTELLA_CASI = "casi_bird"

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

    stato = "OK" if risultato["esatto"] else "FALLITO"
    print(f"[{stato}] {voce['question_id']} ({voce['db_id']}): esatto={risultato['esatto']} F1={risultato['f1']*100:.1f}% errore={risultato['errore']}")
    if not risultato["esatto"]:
        falliti.append(voce)

    conn.close()

print(f"\n{len(manifest['riusciti']) - len(falliti)}/{len(manifest['riusciti'])} casi verificati correttamente.")
if falliti:
    print("Casi falliti:", [v["question_id"] for v in falliti])
