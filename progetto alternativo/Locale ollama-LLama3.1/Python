import re
import sqlite3
import ollama
import sys

conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

cursor.execute("CREATE TABLE VENDITE_PC (Modello TEXT, Prezzo_Locale REAL, Valuta_Locale TEXT)")
cursor.execute("CREATE TABLE VALUTE (Valuta TEXT, Cambio REAL)")
acquisti = [("PC_Alfa", 1000.0, "EUR"), ("PC_Gamma", 150000.0, "JPY"), ("PC_Beta", 800.0, "GBP")]
cursor.executemany("INSERT INTO VENDITE_PC VALUES (?, ?, ?)", acquisti)
tassi_cambio = [("EUR", 1.08), ("GBP", 1.25), ("JPY", 0.0065)]
cursor.executemany("INSERT INTO VALUTE VALUES (?, ?)", tassi_cambio)

cursor.execute("CREATE TABLE TABELLA_FINALE_TARGET (Modello_PC TEXT, Prezzo_Medio_USD REAL)")
conn.commit()

####################Estrazione schemi
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name IN ('VENDITE_PC', 'VALUTE')")
schema_partenza = "".join([riga[0] + ";\n" for riga in cursor.fetchall() if riga[0]])

cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name = 'TABELLA_FINALE_TARGET'")
schema_arrivo = cursor.fetchone()[0] + ";"

#########Prompt
print("-> Llama 3.1 in fase di ragionamento...")
bt = "```"
prompt_lineage = f"""
Sei un Data Architect esperto in Reverse Engineering per pipeline ETL su SQLite.

STATO A (Schema tabelle sorgente con esempi di dati reali):
{schema_partenza}

STATO B (Schema tabella target da popolare):
{schema_arrivo}

COMPITO:
Confronta lo STATO A e lo STATO B. Deduci in totale autonomia quali trasformazioni logiche o matematiche (JOIN, GROUP BY) mancano per passare dalle fonti al target.

REGOLE TASSATIVE STRUTTURALI:
1. TABELLE INTERMEDIE: Usa tabelle temporanee (es. CREATE TEMP TABLE nome AS SELECT...) per spezzare il ragionamento.
2. NOMI COMPLETI (ANTI-ERRORE): È ASSOLUTAMENTE VIETATO usare alias brevi per le tabelle (come V, C, T1). Devi SEMPRE scrivere il nome completo della tabella davanti alla colonna (es. VENDITE_PC.Prezzo_Locale * VALUTE.Cambio).
3. COERENZA COLONNE: Assicurati che il nome delle colonne selezionate in una tabella temporanea corrisponda esattamente a quello che cercherai di leggere nello step successivo (es. se selezioni Modello, dopo non puoi chiamarlo Modello_PC).
4. TARGET ESISTENTE: La tabella TABELLA_FINALE_TARGET ESISTE GIÀ. È VIETATO usare CREATE TABLE per generarla.
5. POPOLAMENTO TARGET: L'ultimo passaggio deve popolare il target usando: INSERT INTO TABELLA_FINALE_TARGET SELECT ... 
6. Restituisci SOLO codice SQL sequenziale, scritto una volta sola, racchiuso tra i tag ```sql e ```.
"""
response = ollama.chat(
    model='llama3.1', 
    messages=[{'role': 'user', 'content': prompt_lineage}],
    options={'temperature': 0}
)
testo_risposta = response['message']['content'].strip()

###############Estrazione e stampa
blocchi_grezzi = re.findall(r'```(.*?)```', testo_risposta, re.DOTALL)
blocchi_sql = [b[3:].strip() if b.strip().lower().startswith('sql') else b.strip() for b in blocchi_grezzi if b.strip()]

print("\n" + "="*50)
print("="*50 + "\n")
if not blocchi_sql:
    print("[ATTENZIONE] Il modello non ha usato i tag SQL. Ecco la risposta grezza:")
    print(testo_risposta)
else:
    for i, query in enumerate(blocchi_sql, 1):
        print(f"\n--- Query {i} ---")
        print(query)

###########Esecuzione
print("\n" + "="*50)
print("="*50 + "\n")

successo = True
for query in blocchi_sql:
    try:
        cursor.executescript(query)
    except Exception as e:
        print(f"\n[ERRORE CRITICO SQLITE]: {e}")
        print(f"Query che ha fallito:\n{query}")
        successo = False
        break

if successo and blocchi_sql:
    try:
        cursor.execute("SELECT * FROM TABELLA_FINALE_TARGET")
        risultati = cursor.fetchall()
        print("\nESECUZIONE COMPLETATA! Dati nella TABELLA_FINALE_TARGET:")
        for riga in risultati:
            print(riga)
    except Exception as e:
        print(f"Errore nella lettura della tabella finale: {e}")

conn.close()
