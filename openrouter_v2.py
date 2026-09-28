import sqlite3
from openai import OpenAI

from common.pipeline import (
    crea_dataset_demo,
    estrai_schema_e_campioni,
    estrai_schema_target,
    costruisci_prompt,
    estrai_query_sql,
    esegui_e_stampa,
    valuta_accuratezza,
    stampa_valutazione,
)

#Tabelle da analizzare
NOMI_TABELLE_SORGENTE = ['VENDITE_PC']
NOME_TABELLA_TARGET = 'TABELLA_FINALE_TARGET'

conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

crea_dataset_demo(cursor)

######################### Estrazione schemi e dati
schema_partenza = estrai_schema_e_campioni(cursor, NOMI_TABELLE_SORGENTE, n_campioni=5)
schema_arrivo = estrai_schema_target(cursor, NOME_TABELLA_TARGET)

#######Prompt
def genera_sql_intermedio(schema_a: str, schema_b: str, nome_target: str) -> str:
    prompt = costruisci_prompt(schema_a, schema_b, nome_target)
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key="************",
        )
        response = client.chat.completions.create(
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            #google/gemma-4-31b-it:free
            #nvidia/nemotron-3-ultra-550b-a55b:free
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        print("Chiamata a OpenRouter (Nemotron 550B) riuscita!")
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Errore nella chiamata API: {e}")
        return ""

print("\n3. Analisi logica in corso tramite IA...")
testo_risposta = genera_sql_intermedio(schema_partenza, schema_arrivo, NOME_TABELLA_TARGET)

#############Estrazione, esecuzione e stampa
query_completa = estrai_query_sql(testo_risposta)
tabelle_create = esegui_e_stampa(cursor, query_completa)

################Valutazione automatica dell'accuratezza
risultato = valuta_accuratezza(cursor, tabelle_create, NOME_TABELLA_TARGET)
stampa_valutazione(risultato)

conn.close()
