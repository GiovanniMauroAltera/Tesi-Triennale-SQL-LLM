"""Le parti usate da tutti gli script della versione originale: caso, prompt, estrazione dell'SQL, valutazione."""
import re
import sqlite3


def nome_sql(identificatore):
    # I nomi di tabelle/colonne BIRD possono contenere spazi o parentesi (es. "First Date"):
    # tra virgolette SQLite li accetta sempre.
    return '"' + identificatore.replace('"', '""') + '"'


def carica_caso(percorso_db):
    """Carica un caso di test da un file .sqlite standalone.

    Il file deve contenere le tabelle sorgente, la tabella target già popolata,
    e una tabella '_caso_info' (tabelle_sorgente, tabella_target) con i loro nomi.
    I dati vengono copiati in una connessione in memoria: il file su disco non
    viene mai modificato, e le tabelle temporanee create dal modello restano isolate.
    """
    origine = sqlite3.connect(percorso_db)
    conn = sqlite3.connect(":memory:")
    origine.backup(conn)
    origine.close()

    cursor = conn.cursor()
    cursor.execute("SELECT tabelle_sorgente, tabella_target FROM _caso_info")
    tabelle_sorgente_raw, tabella_target = cursor.fetchone()
    nomi_tabelle_sorgente = []
    for nome in tabelle_sorgente_raw.split(","):
        nomi_tabelle_sorgente.append(nome.strip())
    return conn, cursor, nomi_tabelle_sorgente, tabella_target


def crea_dataset_demo(cursor):
    cursor.execute("CREATE TABLE VENDITE_PC (Modello TEXT, Prezzo_Locale REAL, Valuta_Locale TEXT)")
    vendite = [
        ("PC_Alfa", 1000.0, "EUR"), ("PC_Alfa", 1200.0, "EUR"), ("PC_Alfa", 1100.0, "EUR"),
        ("PC_Beta", 800.0, "GBP"), ("PC_Beta", 850.0, "GBP"), ("PC_Beta", 900.0, "GBP"), ("PC_Beta", 800.0, "GBP"),
        ("PC_Gamma", 150000.0, "JPY"), ("PC_Gamma", 160000.0, "JPY"), ("PC_Gamma", 140000.0, "JPY"),
        ("PC_Delta", 2000.0, "EUR"), ("PC_Delta", 2100.0, "EUR"),
        ("PC_Epsilon", 500.0, "GBP"), ("PC_Epsilon", 600.0, "GBP"), ("PC_Epsilon", 550.0, "GBP"), ("PC_Epsilon", 600.0, "GBP"),
        ("PC_Zeta", 200000.0, "JPY"), ("PC_Zeta", 220000.0, "JPY"), ("PC_Zeta", 210000.0, "JPY"), ("PC_Zeta", 205000.0, "JPY")
    ]
    cursor.executemany("INSERT INTO VENDITE_PC VALUES (?, ?, ?)", vendite)

    # Popoliamo lo Stato B (Target finale GIA' ESISTENTE) - Medie matematiche esatte
    cursor.execute("CREATE TABLE TABELLA_FINALE_TARGET (Modello_PC TEXT, Prezzo_Medio_USD REAL)")
    target_dati = [
        ('PC_Alfa', 1188.0),
        ('PC_Beta', 1046.875),
        ('PC_Gamma', 975.0),
        ('PC_Delta', 2214.0),
        ('PC_Epsilon', 703.125),
        ('PC_Zeta', 1356.875)
    ]
    cursor.executemany("INSERT INTO TABELLA_FINALE_TARGET VALUES (?, ?)", target_dati)
    cursor.connection.commit()


def estrai_schema_e_campioni(cursor, nomi_tabelle, n_campioni=3, casuale=True):
    """La descrizione delle tabelle sorgente per il prompt: CREATE TABLE, alcune righe e alcuni valori."""
    if casuale:
        ordine = "ORDER BY RANDOM()"
    else:
        ordine = ""
    schema = ""
    segnaposti = ",".join("?" * len(nomi_tabelle))
    cursor.execute(f"SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN ({segnaposti})", nomi_tabelle)

    for nome_tabella, sql in cursor.fetchall():
        schema += f"{sql};\n"
        cursor.execute(f"SELECT * FROM {nome_sql(nome_tabella)} {ordine} LIMIT {n_campioni}")
        schema += f"/* Esempio dati {nome_tabella}: {cursor.fetchall()} */\n"

        cursor.execute(f"PRAGMA table_info({nome_sql(nome_tabella)})")
        colonne = []
        for informazioni in cursor.fetchall():
            colonne.append(informazioni[1])  # ogni riga di PRAGMA table_info e' (posizione, nome, tipo, ...)
        for col in colonne:
            cursor.execute(f"SELECT DISTINCT {nome_sql(col)} FROM {nome_sql(nome_tabella)} LIMIT 10")
            valori_unici = []
            for riga in cursor.fetchall():
                valori_unici.append(riga[0])
            schema += f"/* Valori unici colonna '{col}': {valori_unici} */\n"
        schema += "\n"

    return schema


def estrai_schema_target(cursor, nome_tabella_target):
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (nome_tabella_target,))
    schema = cursor.fetchone()[0] + ";\n"
    cursor.execute(f"SELECT * FROM {nome_sql(nome_tabella_target)} LIMIT 10")
    schema += f"/* Dati target completi: {cursor.fetchall()} */\n"
    return schema


def costruisci_prompt(schema_a: str, schema_b: str, nome_target: str) -> str:
    return f"""Sei un Data Architect esperto in Reverse Engineering per pipeline ETL su SQLite.

STATO A (Schema tabelle sorgente con esempi di dati reali):
{schema_a}

STATO B (Schema tabella target con esempi del risultato finale atteso):
{schema_b}

COMPITO:
Confronta i dati dello STATO A con i dati dello STATO B. Deduci in totale autonomia quali trasformazioni (JOIN, GROUP BY, calcoli) sono state fatte per arrivare a quel risultato.

REGOLE TASSATIVE STRUTTURALI:
1. SOLO PASSAGGI INTERMEDI: Mostrami il processo logico creando SOLO tabelle temporanee (es. CREATE TEMP TABLE step_1 AS SELECT...).
2. NESSUN INSERT SUL TARGET: È ASSOLUTAMENTE VIETATO usare INSERT INTO {nome_target}. La tabella finale esiste già. L'ultima tabella temporanea che crei dovrà avere la stessa struttura (inclusi i nomi delle colonne) e gli stessi dati dello STATO B.
3. NOMI COMPLETI (ANTI-ERRORE): È vietato usare alias brevi per le tabelle. Usa sempre il nome completo.
4. Restituisci SOLO codice SQL sequenziale, racchiuso tra i tag ```sql e ```.
5. DATI LATENTI E MAPPATURE MANCANTI: Se per passare dallo STATO A allo STATO B noti che manca un tassello logico (es. costanti matematiche, coefficienti di conversione, traduzioni di categorie o dizionari di stato),
DEVI dedurlo osservando i dati campione. PRIMA di usare un valore dedotto, verificalo su ALMENO due righe campione della stessa categoria, se disponibili: se non torna su entrambe, non è quello giusto, continua a cercare.
Crea tu stesso una tabella temporanea statica (usando costrutti come SELECT ... UNION ALL) che contenga questa "mappatura" dedotta, e usala come ponte per le operazioni successive.
"""


def estrai_query_sql(testo_risposta: str) -> str:
    """Il codice SQL della risposta del modello, senza il ragionamento e senza gli INSERT."""
    # <think> (es. DeepSeek-R1) e <thought> (Gemma via API Google): il ragionamento puo'
    # contenere bozze di SQL che non devono essere eseguite insieme alla risposta finale.
    testo_risposta = re.sub(r'<(think|thought)>.*?</\1>', '', testo_risposta, flags=re.DOTALL)
    blocchi_grezzi = re.findall(r'```(.*?)```', testo_risposta, re.DOTALL)

    blocchi_sql = []
    if blocchi_grezzi:
        for blocco in blocchi_grezzi:
            if not blocco.strip():
                continue
            if blocco.strip().lower().startswith('sql'):
                blocchi_sql.append(blocco[3:].strip())  # toglie la parola "sql" dopo i tre apici
            else:
                blocchi_sql.append(blocco.strip())
    else:
        blocchi_sql.append(testo_risposta.strip())

    query_completa = "\n".join(blocchi_sql)
    query_completa = re.sub(r'INSERT\s+INTO\s+.*?;', '', query_completa, flags=re.IGNORECASE | re.DOTALL)
    query_completa = re.sub(r'INSERT\s+INTO\s+.*', '', query_completa, flags=re.IGNORECASE | re.DOTALL)
    return query_completa


def esegui_e_stampa(cursor, query_completa: str):
    """Esegue il codice del modello e stampa le tabelle temporanee create; restituisce i loro nomi."""
    print("\n" + "=" * 50)
    print("=" * 50)

    if not query_completa.strip():
        print("[ATTENZIONE] Nessun codice SQL valido estratto.")
        return []

    print(query_completa)
    try:
        cursor.executescript(query_completa)
    except Exception as e:
        print(f"\n[ERRORE CRITICO SQLITE]: {e}")
        print(f"Query che ha fallito:\n{query_completa}")
        return []

    cursor.execute("SELECT name FROM sqlite_temp_master WHERE type='table'")
    tabelle_create = []
    for riga in cursor.fetchall():
        tabelle_create.append(riga[0])

    if not tabelle_create:
        print("L'IA non ha creato tabelle temporanee.")
        return []

    for i, nome_tabella in enumerate(tabelle_create, 1):
        cursor.execute(f"SELECT * FROM {nome_sql(nome_tabella)}")
        risultati = cursor.fetchall()
        colonne = []
        for descrizione in cursor.description:
            colonne.append(descrizione[0])

        print(f"PASSAGGIO {i} - Tabella logica: [{nome_tabella}]")
        print("-" * (16 * len(colonne)))
        intestazioni = []
        for col in colonne:
            intestazioni.append(f"{col:^14}")
        print(" | ".join(intestazioni))
        print("-" * (16 * len(colonne)))

        for riga in risultati:
            celle = []
            for val in riga:
                if isinstance(val, float):
                    testo = str(round(val, 4))
                else:
                    testo = str(val)
                celle.append(f"{testo:^14}")
            print(" | ".join(celle))
        print("\n")

    return tabelle_create


def valori_vicini(atteso, ottenuto, tol_rel, tol_abs):
    """Due valori sono uguali; se sono numeri basta che siano vicini (tolleranza relativa o assoluta)."""
    if isinstance(atteso, (int, float)) and isinstance(ottenuto, (int, float)):
        return abs(atteso - ottenuto) <= max(tol_abs, tol_rel * abs(atteso))
    return atteso == ottenuto


def righe_vicine(riga_a, riga_b, tol_rel, tol_abs):
    if len(riga_a) != len(riga_b):
        return False
    for a, b in zip(riga_a, riga_b):
        if not valori_vicini(a, b, tol_rel, tol_abs):
            return False
    return True


def valuta_accuratezza(cursor, tabelle_create, nome_tabella_target, tol_rel=1e-2, tol_abs=1e-6):
    """Confronta l'ultima tabella temporanea creata dal modello con la tabella target.

    Per costruzione del prompt, l'ultima tabella temporanea creata è quella che il
    modello dichiara equivalente allo Stato B. Il confronto è per insieme di righe
    (l'ordine non conta, nessuna colonna è assunta come chiave): ogni riga attesa
    cerca una corrispondenza tra le righe generate, con tolleranza numerica sui
    campi numerici e uguaglianza esatta sugli altri. Le righe generate rimaste senza
    corrispondenza contano come errori (precisione), cosi' come quelle attese non trovate
    (richiamo).
    """
    if not tabelle_create:
        return valutazione_fallita(None, "Nessuna tabella temporanea creata: impossibile valutare.")

    tabella_generata = tabelle_create[-1]

    # "main." e' necessario: se il modello chiama la sua tabella temporanea con lo
    # stesso nome (anche solo case-insensitive) della tabella target, SQLite la fa
    # ombreggiare quella vera per i riferimenti non qualificati, e la valutazione
    # finirebbe per confrontare la tabella target con se stessa.
    cursor.execute(f"SELECT * FROM main.{nome_sql(nome_tabella_target)}")
    righe_target = cursor.fetchall()

    try:
        cursor.execute(f"SELECT * FROM {nome_sql(tabella_generata)}")
        righe_disponibili = list(cursor.fetchall())
    except Exception as e:
        return valutazione_fallita(tabella_generata, f"Impossibile leggere la tabella generata '{tabella_generata}': {e}")

    n_generate = len(righe_disponibili)
    righe_mancanti = []
    righe_corrette = 0
    for riga_attesa in righe_target:
        # La prima riga generata uguale a quella attesa (a meno della tolleranza sui numeri).
        indice_trovato = None
        for i, riga_generata in enumerate(righe_disponibili):
            if righe_vicine(riga_attesa, riga_generata, tol_rel, tol_abs):
                indice_trovato = i
                break
        if indice_trovato is not None:
            righe_corrette += 1
            righe_disponibili.pop(indice_trovato)
        else:
            righe_mancanti.append(riga_attesa)
    righe_in_piu = righe_disponibili

    # Precisione penalizza le righe generate in piu' (es. una query che restituisce "tutto"),
    # richiamo quelle attese mancanti. "Esatto" e' l'Execution Accuracy di BIRD (ordine ignorato).
    if n_generate:
        precisione = righe_corrette / n_generate
    else:
        precisione = float(not righe_target)
    if righe_target:
        richiamo = righe_corrette / len(righe_target)
    else:
        richiamo = float(not n_generate)
    if precisione + richiamo:
        f1 = 2 * precisione * richiamo / (precisione + richiamo)
    else:
        f1 = 0.0

    return {
        "tabella_valutata": tabella_generata,
        "righe_attese": len(righe_target),
        "righe_generate": n_generate,
        "righe_corrette": righe_corrette,
        "precisione": precisione,
        "richiamo": richiamo,
        "f1": f1,
        "esatto": not righe_mancanti and not righe_in_piu,
        "esempi_righe_mancanti": righe_mancanti[:20],
        "esempi_righe_in_piu": righe_in_piu[:20],
        "errore": None,
    }


def valutazione_fallita(tabella_generata, errore):
    return {
        "tabella_valutata": tabella_generata,
        "righe_attese": 0,
        "righe_generate": 0,
        "righe_corrette": 0,
        "precisione": 0.0,
        "richiamo": 0.0,
        "f1": 0.0,
        "esatto": False,
        "esempi_righe_mancanti": [],
        "esempi_righe_in_piu": [],
        "errore": errore,
    }


def stampa_valutazione(risultato):
    print("\n" + "=" * 50)
    print("VALUTAZIONE")
    print("=" * 50)
    if risultato["errore"]:
        print(f"[NON VALUTABILE] {risultato['errore']}")
        return
    print(f"Tabella valutata: {risultato['tabella_valutata']}")
    if risultato["esatto"]:
        print("Risultato esatto: SI")
    else:
        print("Risultato esatto: NO")
    print(
        f"Righe corrette: {risultato['righe_corrette']} su {risultato['righe_attese']} attese "
        f"e {risultato['righe_generate']} generate (precisione {risultato['precisione'] * 100:.1f}%, "
        f"richiamo {risultato['richiamo'] * 100:.1f}%, F1 {risultato['f1'] * 100:.1f}%)"
    )
    for riga in risultato["esempi_righe_mancanti"]:
        print(f"  [MANCANTE] {riga}")
    for riga in risultato["esempi_righe_in_piu"]:
        print(f"  [IN PIU']  {riga}")
