import os
import re
import sqlite3
import google.generativeai as genai

conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

# Fonti Dati (Stato A)
cursor.execute("CREATE TABLE VENDITE_PC (Modello TEXT, Prezzo_Locale REAL, Valuta_Locale TEXT)")
cursor.execute("CREATE TABLE VALUTE (Valuta TEXT, Cambio REAL)")
acquisti = [("PC_Alfa", 1000.0, "EUR"), ("PC_Gamma", 150000.0, "JPY"), ("PC_Beta", 800.0, "GBP")]
cursor.executemany("INSERT INTO VENDITE_PC VALUES (?, ?, ?)", acquisti)
tassi_cambio = [("EUR", 1.08), ("GBP", 1.25), ("JPY", 0.0065)]
cursor.executemany("INSERT INTO VALUTE VALUES (?, ?)", tassi_cambio)

# Tabella Target da raggiungere (Stato B)
cursor.execute("CREATE TABLE TABELLA_FINALE_TARGET (Modello_PC TEXT, Prezzo_Medio_USD REAL)")
conn.commit()

###############Estrazione schemi
schema_partenza = ""
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN ('VENDITE_PC', 'VALUTE')")
for nome_tabella, sql in cursor.fetchall():
    schema_partenza += f"{sql};\n"
    cursor.execute(f"SELECT * FROM {nome_tabella} LIMIT 3")
    campioni = cursor.fetchall()
    schema_partenza += f"/* Esempio dati {nome_tabella}: {campioni} */\n\n"

cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name = 'TABELLA_FINALE_TARGET'")
schema_arrivo = cursor.fetchone()[0] + ";"

######################Prompt
API_KEY = os.environ.get("GOOGLE_API_KEY", "********************")
genai.configure(api_key=API_KEY)

model = genai.GenerativeModel("gemini-3.6-flash")

def genera_sql_intermedio(schema_a: str, schema_b: str) -> str:
    """Chiede a Gemini di generare le tabelle SQL intermedie per passare da A a B."""
    prompt = f"""Sei un Data Architect esperto in Reverse Engineering per pipeline ETL su SQLite.

STATO A (Schema tabelle sorgente con esempi di dati reali):
{schema_a}

STATO B (Schema tabella target da popolare):
{schema_b}

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
    try:
        response = model.generate_content(prompt, generation_config={"temperature": 0.0})
        print("Chiamata a Gemini riuscita!")
        return response.text
    except Exception as e:
        print("Errore nella chiamata all'API:")
        print(e)
        return ""

testo_risposta = genera_sql_intermedio(schema_partenza, schema_arrivo)

#################Estrazione e Stamapa
blocchi_grezzi = re.findall(r'```(.*?)```', testo_risposta, re.DOTALL)
blocchi_sql = [b[3:].strip() if b.strip().lower().startswith('sql') else b.strip() for b in blocchi_grezzi if b.strip()]

print("\n" + "=" * 50)
print("=" * 50 + "\n")
if not blocchi_sql:
    print("[ATTENZIONE] Il modello non ha usato i tag SQL. Ecco la risposta grezza:")
    print(testo_risposta)
else:
    for i, query in enumerate(blocchi_sql, 1):
        print(f"\n--- Query {i} ---")
        print(query)

############Esecuzione
print("\n" + "=" * 50)
print("=" * 50 + "\n")

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
