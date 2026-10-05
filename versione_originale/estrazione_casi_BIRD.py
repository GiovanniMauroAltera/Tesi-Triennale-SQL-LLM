"""Prende da BIRD Mini-Dev i 30 casi del benchmark e li salva in casi_BIRD/, un file .sqlite per caso.

Ogni file contiene le tabelle di partenza (copiate dal database BIRD), la tabella finale RISULTATO_ATTESO
(il risultato della query vera di BIRD) e due tabelle di informazioni: _caso_info (i nomi delle tabelle) e
_bird_info (domanda, difficolta' e query vera).

Come si usa (dalla cartella principale della repository, con BIRD Mini-Dev in bird-mini-dev/):
  python versione_originale/estrazione_casi_BIRD.py
"""
import json
import os
import random
import re
import sqlite3
import time

from funzioni_comuni import estrai_schema_e_campioni, costruisci_prompt

CARTELLA_BIRD = "bird-mini-dev"
PERCORSO_JSON = os.path.join(CARTELLA_BIRD, "mini_dev_sqlite.json")
CARTELLA_DB = os.path.join(CARTELLA_BIRD, "dev_databases")
CARTELLA_CASI_OUT = "casi_BIRD"

N_TOTALE = 30
SEED = 42
DIFFICOLTA = "simple"
MAX_TABELLE_SORGENTE = 2
MAX_TOKEN_PROMPT = 3500  # stima ~4 caratteri/token: entra nel contesto locale e nei limiti gratuiti di Groq
TIMEOUT_QUERY_SECONDI = 20
NOME_TABELLA_TARGET = "RISULTATO_ATTESO"


def tabelle_del_db(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    nomi = []
    for riga in cursor.fetchall():
        nomi.append(riga[0])
    return nomi


def tabelle_referenziate(sql, nomi_tabelle):
    """Le tabelle del database che compaiono nella query."""
    trovate = []
    for nome in nomi_tabelle:
        if re.search(r'\b' + re.escape(nome) + r'\b', sql, flags=re.IGNORECASE):
            trovate.append(nome)
    return trovate


def copia_tabella(cursor_origine, cursor_destinazione, nome_tabella):
    cursor_origine.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (nome_tabella,))
    ddl = cursor_origine.fetchone()[0]
    cursor_destinazione.execute(ddl)

    cursor_origine.execute(f'SELECT * FROM "{nome_tabella}"')
    righe = cursor_origine.fetchall()
    if righe:
        placeholders = ",".join(["?"] * len(righe[0]))
        cursor_destinazione.executemany(f'INSERT INTO "{nome_tabella}" VALUES ({placeholders})', righe)


def crea_tabella_target(cursor_destinazione, colonne, righe):
    # Una colonna senza nome diventa col_0, col_1...; due colonne con lo stesso nome diventano nome, nome_1...
    nomi_colonna_sicuri = []
    usati = set()
    for i, nome in enumerate(colonne):
        if nome:
            nome_sicuro = nome
        else:
            nome_sicuro = f"col_{i}"
        base = nome_sicuro
        contatore = 1
        while nome_sicuro in usati:
            nome_sicuro = f"{base}_{contatore}"
            contatore += 1
        usati.add(nome_sicuro)
        nomi_colonna_sicuri.append(nome_sicuro)

    tra_virgolette = []
    for nome in nomi_colonna_sicuri:
        tra_virgolette.append(f'"{nome}"')
    colonne_ddl = ", ".join(tra_virgolette)
    cursor_destinazione.execute(f'CREATE TABLE {NOME_TABELLA_TARGET} ({colonne_ddl})')
    if righe:
        placeholders = ",".join(["?"] * len(nomi_colonna_sicuri))
        cursor_destinazione.executemany(f'INSERT INTO {NOME_TABELLA_TARGET} VALUES ({placeholders})', righe)


def estrai_caso(esempio, nomi_sorgente, cartella_uscita):
    """Crea il file .sqlite del caso nella cartella indicata e restituisce il suo percorso."""
    db_id = esempio["db_id"]
    percorso_db_origine = os.path.join(CARTELLA_DB, db_id, f"{db_id}.sqlite")

    conn_origine = sqlite3.connect(percorso_db_origine)
    cursor_origine = conn_origine.cursor()

    cursor_origine.execute(esempio["SQL"])
    colonne = []
    for descrizione in cursor_origine.description:
        colonne.append(descrizione[0])
    righe_target = cursor_origine.fetchall()

    os.makedirs(cartella_uscita, exist_ok=True)
    nome_file = f"{esempio['question_id']}_{db_id}.sqlite"
    percorso_out = os.path.join(cartella_uscita, nome_file)
    if os.path.exists(percorso_out):
        os.remove(percorso_out)

    conn_out = sqlite3.connect(percorso_out)
    cursor_out = conn_out.cursor()

    for nome_tabella in nomi_sorgente:
        copia_tabella(cursor_origine, cursor_out, nome_tabella)

    crea_tabella_target(cursor_out, colonne, righe_target)

    cursor_out.execute("CREATE TABLE _caso_info (tabelle_sorgente TEXT, tabella_target TEXT)")
    cursor_out.execute("INSERT INTO _caso_info VALUES (?, ?)", (",".join(nomi_sorgente), NOME_TABELLA_TARGET))

    cursor_out.execute(
        "CREATE TABLE _bird_info (question_id INTEGER, db_id TEXT, difficulty TEXT, question TEXT, evidence TEXT, sql_gold TEXT)"
    )
    cursor_out.execute(
        "INSERT INTO _bird_info VALUES (?, ?, ?, ?, ?, ?)",
        (esempio["question_id"], db_id, esempio["difficulty"], esempio["question"], esempio["evidence"], esempio["SQL"]),
    )

    conn_out.commit()
    conn_out.close()
    conn_origine.close()
    return percorso_out


def esegui_con_timeout(conn, sql):
    """Esegue la query e restituisce (nomi delle colonne, righe); si ferma dopo TIMEOUT_QUERY_SECONDI."""
    inizio = time.time()

    def troppo_tempo():
        # SQLite chiama questa funzione ogni tanto mentre lavora: se restituisce 1, la query si ferma.
        if time.time() - inizio > TIMEOUT_QUERY_SECONDI:
            return 1
        return 0

    conn.set_progress_handler(troppo_tempo, 100000)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        righe = cursor.fetchall()
        colonne = []
        for descrizione in cursor.description:
            colonne.append(descrizione[0])
        return colonne, righe
    finally:
        conn.set_progress_handler(None, 0)


def stima_token_prompt(cursor, nomi_sorgente, colonne, righe):
    # Campioni deterministici (prime righe), non casuali: la selezione deve essere riproducibile.
    schema_a = estrai_schema_e_campioni(cursor, nomi_sorgente, n_campioni=5, casuale=False)
    schema_b = f"CREATE TABLE {NOME_TABELLA_TARGET} ({', '.join(colonne)});\n/* Dati target completi: {righe[:10]} */\n"
    return len(costruisci_prompt(schema_a, schema_b, NOME_TABELLA_TARGET)) // 4


def filtra_candidati(tutti_esempi, difficolta, max_token_prompt):
    """Esempi della difficolta' indicata, con al massimo 2 tabelle, prompt piccolo e risultato non ridotto a un
    singolo valore. Con max_token_prompt = None la lunghezza del prompt non conta.

    Un risultato di 1 riga x 1 colonna (un conteggio, una percentuale) non permette di risalire
    alla trasformazione: infinite query diverse danno lo stesso numero.
    """
    connessioni = {}
    tabelle_per_db = {}
    candidati = []
    for esempio in tutti_esempi:
        if esempio["difficulty"] != difficolta:
            continue
        db_id = esempio["db_id"]
        if db_id not in connessioni:
            connessioni[db_id] = sqlite3.connect(os.path.join(CARTELLA_DB, db_id, f"{db_id}.sqlite"))
            tabelle_per_db[db_id] = tabelle_del_db(connessioni[db_id].cursor())
        conn = connessioni[db_id]

        nomi_sorgente = tabelle_referenziate(esempio["SQL"], tabelle_per_db[db_id])
        if len(nomi_sorgente) < 1 or len(nomi_sorgente) > MAX_TABELLE_SORGENTE:
            continue
        try:
            colonne, righe = esegui_con_timeout(conn, esempio["SQL"])
        except Exception:
            continue
        if not righe or (len(righe) == 1 and len(colonne) == 1):
            continue
        token = None
        if max_token_prompt is not None:
            token = stima_token_prompt(conn.cursor(), nomi_sorgente, colonne, righe)
            if token > max_token_prompt:
                continue
        candidati.append({"esempio": esempio, "tabelle": nomi_sorgente, "righe": len(righe), "token": token})

    for conn in connessioni.values():
        conn.close()
    return candidati


def ordina_per_numero_di_domanda(candidati):
    coppie = []
    for posizione, candidato in enumerate(candidati):
        coppie.append((candidato["esempio"]["question_id"], posizione))
    coppie.sort()
    ordinati = []
    for numero, posizione in coppie:
        ordinati.append(candidati[posizione])
    return ordinati


def seleziona(candidati):
    # Prima tutti i casi con risultato di piu' righe (i piu' deducibili), poi si completa
    # con casi a una riga ma piu' colonne, scelti a caso con seed fisso.
    multi_riga = []
    una_riga = []
    for candidato in candidati:
        if candidato["righe"] >= 2:
            multi_riga.append(candidato)
        elif candidato["righe"] == 1:
            una_riga.append(candidato)
    multi_riga = ordina_per_numero_di_domanda(multi_riga)
    una_riga = ordina_per_numero_di_domanda(una_riga)
    random.seed(SEED)
    random.shuffle(multi_riga)
    random.shuffle(una_riga)
    return (multi_riga + una_riga)[:N_TOTALE]


def main():
    with open(PERCORSO_JSON, encoding="utf-8") as f:
        tutti_esempi = json.load(f)

    candidati = filtra_candidati(tutti_esempi, DIFFICOLTA, MAX_TOKEN_PROMPT)
    n_multi = 0
    for candidato in candidati:
        if candidato["righe"] >= 2:
            n_multi += 1
    print(f"Candidati: {len(candidati)} ({n_multi} con risultato di piu' righe, {len(candidati) - n_multi} a una riga e piu' colonne)")

    riusciti = []
    falliti = []
    for c in seleziona(candidati):
        esempio = c["esempio"]
        nomi_sorgente = c["tabelle"]
        try:
            percorso_out = estrai_caso(esempio, nomi_sorgente, CARTELLA_CASI_OUT)
            riusciti.append({
                "question_id": esempio["question_id"],
                "db_id": esempio["db_id"],
                "difficulty": esempio["difficulty"],
                "percorso": percorso_out,
                "tabelle_sorgente": nomi_sorgente,
                "righe_risultato": c["righe"],
                "token_stimati": c["token"],
            })
            print(f"[OK] {esempio['question_id']} ({esempio['db_id']}, {len(nomi_sorgente)} tab, {c['righe']} righe, ~{c['token']} token) -> {percorso_out}")
        except Exception as e:
            falliti.append({"question_id": esempio["question_id"], "db_id": esempio["db_id"], "errore": str(e)})
            print(f"[SALTATO] {esempio['question_id']} ({esempio['db_id']}): {e}")

    print(f"\nEstratti {len(riusciti)} casi su {N_TOTALE} richiesti, {len(falliti)} saltati.")

    manifest_path = os.path.join(CARTELLA_CASI_OUT, "_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"riusciti": riusciti, "falliti": falliti}, f, indent=2, ensure_ascii=False)
    print(f"Manifest salvato in {manifest_path}")


if __name__ == "__main__":
    main()
