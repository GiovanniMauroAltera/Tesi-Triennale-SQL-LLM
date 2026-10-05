"""Apre il database, esegue la query proposta da un modello e la confronta con la tabella finale."""
import re
import sqlite3
import time

TOLLERANZA = 0.01             # differenza relativa ammessa sui numeri (i modelli arrotondano in modo diverso)
SECONDI_MAX_QUERY = 30        # oltre, la query viene fermata (di solito e' un prodotto cartesiano)
MAX_RIGHE_LETTE = 5000        # un risultato piu' grande non serve leggerlo tutto: e' sbagliato di sicuro
TABELLA_RISULTATO = "_risultato_del_modello"
TABELLE_DI_SERVIZIO = ["_caso_info", "_bird_info"]  # metadati dei file dei casi, mai visibili al modello


def nome_sql(nome):
    # I nomi delle tabelle e delle colonne possono contenere spazi o parentesi (es. "First Date"):
    # tra virgolette SQLite li accetta sempre.
    return '"' + nome.replace('"', '""') + '"'


def apri_database(percorso):
    """Copia il database in memoria: il file originale non viene mai modificato."""
    originale = sqlite3.connect(percorso)
    conn = sqlite3.connect(":memory:")
    originale.backup(conn)
    originale.close()
    return conn


def leggi_info_caso(conn):
    """Nei file dei casi (BIRD e caso dei PC) i nomi delle tabelle sono scritti nella tabella _caso_info."""
    partenza, finale = conn.execute("SELECT tabelle_sorgente, tabella_target FROM _caso_info").fetchone()
    tabelle_di_partenza = []
    for nome in partenza.split(","):
        tabelle_di_partenza.append(nome.strip())
    return tabelle_di_partenza, finale


def leggi_righe(conn, tabella, limite=None):
    """(nomi delle colonne, righe) di una tabella, al massimo `limite` righe se indicato."""
    sql = f"SELECT * FROM {tabella}"
    if limite:
        sql += f" LIMIT {limite}"
    cursore = conn.execute(sql)
    colonne = []
    for descrizione in cursore.description:
        colonne.append(descrizione[0])
    return colonne, cursore.fetchall()


def colonne_di(conn, tabella):
    """I nomi delle colonne di una tabella."""
    colonne = []
    for informazioni in conn.execute(f"PRAGMA table_info({nome_sql(tabella)})"):
        colonne.append(informazioni[1])  # ogni riga di PRAGMA table_info e' (posizione, nome, tipo, ...)
    return colonne


def valori_diversi(conn, tabella, colonna):
    """I valori diversi (non vuoti) di una colonna."""
    valori = set()
    for riga in conn.execute(f"SELECT DISTINCT {nome_sql(colonna)} FROM {nome_sql(tabella)} "
                             f"WHERE {nome_sql(colonna)} IS NOT NULL"):
        valori.add(riga[0])
    return valori


def chiavi_di_collegamento(conn, tabella_a, tabella_b, min_diversi=5, min_sovrapposizione=0.8):
    """Coppie di colonne (di a, di b) su cui le due tabelle probabilmente si collegano con un JOIN.

    Una colonna di a si collega a una di b se quasi tutti i suoi valori compaiono anche in b
    (es. member.zip in zip_code.zip_code). Si ignorano le colonne con pochi valori diversi
    (es. 'Yes'/'No'), che si sovrappongono per caso. Prima le coppie che si sovrappongono di piu'.
    """
    valori_b = {}
    for colonna_b in colonne_di(conn, tabella_b):
        valori_b[colonna_b] = valori_diversi(conn, tabella_b, colonna_b)
    coppie = []
    for colonna_a in colonne_di(conn, tabella_a):
        valori_a = valori_diversi(conn, tabella_a, colonna_a)
        if len(valori_a) < min_diversi:
            continue
        for colonna_b, valori in valori_b.items():
            if len(valori) < min_diversi:
                continue
            sovrapposizione = len(valori_a & valori) / len(valori_a)
            if sovrapposizione >= min_sovrapposizione:
                coppie.append((sovrapposizione, colonna_a, colonna_b))
    coppie.sort(reverse=True)
    risultato = []
    for sovrapposizione, colonna_a, colonna_b in coppie:
        risultato.append((colonna_a, colonna_b))
    return risultato


def copia_per_il_modello(conn, tabella_finale):
    """Copia del database su cui far girare la query del modello, senza la tabella finale.

    Senza questa precauzione al modello basterebbe un SELECT * dalla tabella finale.
    """
    copia = sqlite3.connect(":memory:")
    conn.backup(copia)
    for tabella in [tabella_finale] + TABELLE_DI_SERVIZIO:
        copia.execute(f"DROP TABLE IF EXISTS {nome_sql(tabella)}")
    return copia


def senza_commenti(sql):
    """Il codice SQL senza i commenti (-- fino a fine riga, e /* ... */)."""
    return re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.DOTALL).strip()


def dividi_istruzioni(sql):
    """Divide il codice in istruzioni, senza farsi ingannare dai ';' dentro le stringhe."""
    istruzioni = []
    corrente = ""
    for pezzo in sql.split(";"):
        corrente += pezzo + ";"
        # complete_statement dice se fin qui c'e' un'istruzione intera (un ';' in una stringa non la chiude).
        if sqlite3.complete_statement(corrente):
            if senza_commenti(corrente).strip(";").strip():
                istruzioni.append(corrente.strip())
            corrente = ""
    if senza_commenti(corrente).strip(";").strip():
        istruzioni.append(corrente.strip())
    return istruzioni


def esegui(conn, sql):
    """Esegue la query e restituisce (colonne, righe, numero totale di righe) del risultato finale.

    Il risultato finale e' l'ultima SELECT se la query finisce con una SELECT, altrimenti
    l'ultima tabella temporanea creata. Se la query non funziona solleva ValueError con un
    messaggio da poter rimandare al modello.
    """
    istruzioni = dividi_istruzioni(sql)
    if not istruzioni:
        raise ValueError("la risposta non contiene codice SQL")

    inizio = time.time()

    def troppo_tempo():
        # SQLite chiama questa funzione ogni tanto mentre lavora: se restituisce True, la query si ferma.
        return time.time() - inizio > SECONDI_MAX_QUERY

    conn.set_progress_handler(troppo_tempo, 100_000)
    try:
        ultima = senza_commenti(istruzioni[-1]).rstrip(";").strip()
        if re.match(r"(SELECT|WITH)\b", ultima, flags=re.IGNORECASE):
            # Le istruzioni prima dell'ultima (tabelle temporanee), poi il risultato in una tabella da leggere.
            if len(istruzioni) > 1:
                conn.executescript("\n".join(istruzioni[:-1]))
            conn.execute(f"CREATE TEMP TABLE {TABELLA_RISULTATO} AS {ultima}")
            tabella = TABELLA_RISULTATO
        else:
            conn.executescript("\n".join(istruzioni))
            temporanee = []
            for riga in conn.execute("SELECT name FROM sqlite_temp_master WHERE type = 'table'"):
                temporanee.append(riga[0])
            if not temporanee:
                raise ValueError("la query non restituisce nessun risultato: l'ultima istruzione deve essere una SELECT")
            tabella = nome_sql(temporanee[-1])
        totale = conn.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]
        colonne, righe = leggi_righe(conn, tabella, MAX_RIGHE_LETTE)
    except sqlite3.Error as errore:
        if "interrupted" in str(errore):
            raise ValueError(f"la query impiega piu' di {SECONDI_MAX_QUERY} secondi (probabile prodotto cartesiano)")
        raise ValueError(f"errore SQLite: {errore}")
    finally:
        conn.set_progress_handler(None, 0)
    return colonne, righe, totale


def valori_uguali(atteso, ottenuto):
    """Due valori sono uguali; se sono numeri basta che siano vicini (tolleranza dell'1%)."""
    if isinstance(atteso, (int, float)) and isinstance(ottenuto, (int, float)):
        return abs(atteso - ottenuto) <= max(1e-6, TOLLERANZA * abs(atteso))
    return atteso == ottenuto


def righe_uguali(attesa, ottenuta):
    if len(attesa) != len(ottenuta):
        return False
    for atteso, ottenuto in zip(attesa, ottenuta):
        if not valori_uguali(atteso, ottenuto):
            return False
    return True


def confronta(righe_ottenute, righe_attese, totale_ottenute=None):
    """Confronta le righe come insiemi: l'ordine non conta, i numeri hanno una piccola tolleranza.

    Prima abbina le righe identiche (veloce anche con molte righe), poi cerca tra quelle
    rimaste le corrispondenze con tolleranza sui numeri.
    """
    if totale_ottenute is None:
        totale_ottenute = len(righe_ottenute)

    # Quante volte compare ogni riga ottenuta: ogni riga attesa ne "consuma" una uguale.
    disponibili = {}
    for riga in righe_ottenute:
        disponibili[riga] = disponibili.get(riga, 0) + 1
    mancanti = []
    for riga in righe_attese:
        if disponibili.get(riga, 0) > 0:
            disponibili[riga] -= 1
        else:
            mancanti.append(riga)
    rimaste = []  # le righe ottenute non ancora abbinate
    for riga, quante in disponibili.items():
        for volta in range(quante):
            rimaste.append(riga)

    # Per le righe attese che mancano, una riga rimasta uguale a meno della tolleranza sui numeri.
    ancora_mancanti = []
    for riga in mancanti:
        trovata = None
        for i, altra in enumerate(rimaste):
            if righe_uguali(riga, altra):
                trovata = i
                break
        if trovata is None:
            ancora_mancanti.append(riga)
        else:
            rimaste.pop(trovata)

    # Correttezza parziale: la media armonica (F1) tra precisione e richiamo.
    giuste = len(righe_attese) - len(ancora_mancanti)
    if totale_ottenute:
        precisione = giuste / totale_ottenute
    else:
        precisione = float(not righe_attese)
    if righe_attese:
        richiamo = giuste / len(righe_attese)
    else:
        richiamo = float(not totale_ottenute)
    if precisione + richiamo:
        parziale = 2 * precisione * richiamo / (precisione + richiamo)
    else:
        parziale = 0.0
    return {
        "corretto": not ancora_mancanti and totale_ottenute == len(righe_attese),
        "righe_attese": len(righe_attese),
        "righe_ottenute": totale_ottenute,
        "righe_giuste": giuste,
        "correttezza_parziale": parziale,
        "esempi_mancanti": ancora_mancanti[:5],
        "esempi_in_piu": rimaste[:5],
        "errore": None,
    }


def esito_fallito(errore):
    return {"corretto": False, "righe_attese": None, "righe_ottenute": 0, "righe_giuste": 0,
            "correttezza_parziale": 0.0, "esempi_mancanti": [], "esempi_in_piu": [], "errore": errore}


def valori_copiati(sql, righe_finali):
    """Testi della tabella finale scritti a mano nella query (es. SELECT 'Trent', 'Smith' UNION ALL ...).

    Un filtro come WHERE state = 'Illinois' e' legittimo; diventa sospetto quando nella query
    compaiono almeno meta' dei testi della tabella finale (e almeno due): vuol dire che il
    modello li ha ricopiati invece di ricavarli dalle tabelle di partenza.
    """
    # I testi tra apici scritti nella query (un apice dentro un testo si scrive '').
    scritti_a_mano = set()
    for testo in re.findall(r"'((?:[^']|'')*)'", senza_commenti(sql)):
        scritti_a_mano.add(testo.replace("''", "'"))
    testi_finali = set()
    for riga in righe_finali:
        for valore in riga:
            if isinstance(valore, str) and len(valore.strip()) >= 2:
                testi_finali.add(valore)
    copiati = sorted(testi_finali & scritti_a_mano)
    sospetto = len(testi_finali) >= 2 and len(copiati) >= max(2, len(testi_finali) / 2)
    return sospetto, copiati


def verifica(conn, tabella_finale, sql):
    """Esegue la query del modello su una copia del database e dice se riproduce la tabella finale."""
    colonne_finali, righe_finali = leggi_righe(conn, nome_sql(tabella_finale))
    copia = copia_per_il_modello(conn, tabella_finale)
    try:
        colonne, righe, totale = esegui(copia, sql)
        esito = confronta(righe, righe_finali, totale)
    except ValueError as errore:
        esito = esito_fallito(str(errore))
        esito["righe_attese"] = len(righe_finali)
    finally:
        copia.close()
    sospetto, copiati = valori_copiati(sql, righe_finali)
    esito["copiatura_sospetta"] = sospetto
    esito["valori_copiati"] = copiati
    return esito
