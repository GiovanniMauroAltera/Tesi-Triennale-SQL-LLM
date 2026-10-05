"""Prepara cosa mandare ai modelli: la descrizione delle tabelle, il prompt iniziale e l'estrazione dell'SQL."""
import re

from verifica import chiavi_di_collegamento, colonne_di, leggi_righe, nome_sql

N_ESEMPI = 5                 # righe di esempio per ogni tabella di partenza
N_VALORI_PER_COLONNA = 8     # valori diversi mostrati per ogni colonna...
MAX_VALORI_COMPLETI = 25     # ...ma se una colonna ne ha al massimo 25 (stati, categorie) li mostra tutti
MAX_RIGHE_FINALE = 10        # righe della tabella finale mostrate (piu' il numero totale)
MAX_CARATTERI_VALORE = 60    # i testi lunghi vengono accorciati: costano token senza aiutare

# Indizi dai dati: le righe di partenza che contengono i valori della tabella finale.
INDIZI = True
MAX_RIGHE_INDIZIO = 8        # righe mostrate per ogni tabella
MAX_RIGHE_PER_VALORE = 5     # un valore che compare in piu' righe di cosi' non indica nulla (es. 1, 'Yes')
MAX_RIGHE_FINALI_CERCATE = 20  # per gli indizi bastano alcune righe finali (il caso 532 ne ha 4430)

# Senza questa istruzione Gemma scrive il ragionamento nella risposta (il 95% del testo):
# con l'istruzione e' passata da 173 a 43 secondi sullo stesso caso, con lo stesso risultato.
ISTRUZIONE_DI_SISTEMA = "Rispondi subito con la query SQL. Non scrivere il ragionamento."


def accorcia(valore):
    """I testi troppo lunghi vengono tagliati: costano token senza aiutare il modello."""
    if isinstance(valore, str) and len(valore) > MAX_CARATTERI_VALORE:
        return valore[:MAX_CARATTERI_VALORE] + "..."
    return valore


def righe_come_testo(righe):
    """Una riga per riga di tabella, scritta come in Python: ('Mario', 'Rossi', 42)."""
    testi = []
    for riga in righe:
        valori = []
        for valore in riga:
            valori.append(accorcia(valore))
        testi.append(repr(tuple(valori)))
    return "\n".join(testi)


def sql_di_creazione(conn, tabella):
    """L'istruzione CREATE TABLE con cui e' stata creata la tabella."""
    return conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (tabella,)).fetchone()[0]


def descrivi_tabella_di_partenza(conn, tabella):
    # Le prime righe e non righe a caso: stesso prompt a ogni esecuzione, e su tabelle grandi
    # ORDER BY RANDOM() costa una lettura completa.
    totale = conn.execute(f"SELECT COUNT(*) FROM {nome_sql(tabella)}").fetchone()[0]
    colonne, esempi = leggi_righe(conn, nome_sql(tabella), N_ESEMPI)
    parti = [f"{sql_di_creazione(conn, tabella)};",
             f"-- {totale} righe. Le prime {len(esempi)}:",
             righe_come_testo(esempi),
             "-- Alcuni valori di ogni colonna:"]
    for colonna in colonne:
        # Basta sapere se i valori diversi sono al massimo 25: contarli tutti su testi lunghi costa secondi.
        valori = []
        for riga in conn.execute(f"SELECT DISTINCT {nome_sql(colonna)} FROM {nome_sql(tabella)} "
                                 f"LIMIT {MAX_VALORI_COMPLETI + 1}"):
            valori.append(riga[0])
        if len(valori) <= MAX_VALORI_COMPLETI:
            quanti = f"tutti i {len(valori)} valori"
        else:
            valori = valori[:N_VALORI_PER_COLONNA]
            quanti = f"piu' di {MAX_VALORI_COMPLETI} valori diversi, alcuni"
        valori_accorciati = []
        for valore in valori:
            valori_accorciati.append(accorcia(valore))
        parti.append(f"--   {colonna} ({quanti}): {valori_accorciati}")
    return "\n".join(parti)


# ---------------------------------------------------------------------------------------------------------
# Gli indizi
# ---------------------------------------------------------------------------------------------------------

def significativo(valore):
    """Un valore utile per cercare le righe: non vuoto e non un testo di un solo carattere."""
    return valore is not None and not (isinstance(valore, str) and len(valore) < 2)


def righe_che_contengono(conn, tabella, valore):
    """Le righe (con il rowid) in cui una qualsiasi colonna vale `valore`, ma solo se sono poche."""
    colonne = colonne_di(conn, tabella)
    condizioni = []
    for colonna in colonne:
        condizioni.append(f"{nome_sql(colonna)} = ?")
    righe = conn.execute(f"SELECT rowid, * FROM {nome_sql(tabella)} WHERE {' OR '.join(condizioni)} "
                         f"LIMIT {MAX_RIGHE_PER_VALORE + 1}", [valore] * len(colonne)).fetchall()
    if len(righe) <= MAX_RIGHE_PER_VALORE:
        return righe
    return []


def forza(riga, valori_per_riga):
    """Quanti valori di una stessa riga finale ci sono nella riga di partenza (il massimo tra le righe finali)."""
    valori_della_riga = set(riga)
    massimo = 0
    for valori in valori_per_riga:
        in_comune = len(valori & valori_della_riga)
        if in_comune > massimo:
            massimo = in_comune
    return massimo


def righe_abbastanza_forti(righe, valori_per_riga, minimo):
    """Le righe con almeno `minimo` valori di una stessa riga finale (al massimo MAX_RIGHE_INDIZIO)."""
    scelte = []
    for riga in righe:
        if forza(riga, valori_per_riga) >= minimo:
            scelte.append(riga)
    return scelte[:MAX_RIGHE_INDIZIO]


def descrivi_indizi(conn, tabelle_di_partenza, tabella_finale):
    """Le righe di partenza da cui probabilmente nasce la tabella finale, e quelle collegate a loro.

    Di solito il prompt mostra solo le prime righe di ogni tabella e le righe da cui nasce la tabella
    finale non ci sono: il modello deve indovinare il filtro senza vederne le prove. Qui le cerchiamo
    noi (es. i 3 soci della tabella finale e, collegate dal loro CAP, le righe dei CAP con lo stato).
    Usa solo dati che nell'uso reale ci sono sempre: le tabelle di partenza e la tabella finale.
    """
    _, righe_finali = leggi_righe(conn, nome_sql(tabella_finale), MAX_RIGHE_FINALI_CERCATE)
    valori_per_riga = []  # per ogni riga finale, i suoi valori utili
    for riga in righe_finali:
        valori = set()
        for valore in riga:
            if significativo(valore):
                valori.add(valore)
        valori_per_riga.append(valori)
    tutti_i_valori = set()
    for valori in valori_per_riga:
        tutti_i_valori |= valori

    # Se la tabella finale ha piu' colonne, una riga di partenza conta solo se contiene almeno due valori
    # della stessa riga finale (nome E cognome): un solo valore puo' coincidere per caso (una citta' "Smith").
    minimo = 1
    for valori in valori_per_riga:
        if len(valori) >= 2:
            minimo = 2

    candidate = {}  # tabella -> le righe che contengono almeno un valore della tabella finale
    trovate = {}    # tabella -> quelle abbastanza "forti" da mostrare
    for tabella in tabelle_di_partenza:
        righe = {}  # rowid -> riga (senza rowid): la stessa riga trovata con due valori si mostra una volta
        for valore in tutti_i_valori:
            for riga in righe_che_contengono(conn, tabella, valore):
                righe[riga[0]] = riga[1:]
        candidate[tabella] = list(righe.values())
        trovate[tabella] = righe_abbastanza_forti(candidate[tabella], valori_per_riga, minimo)
    nessuna_trovata = True
    for righe in trovate.values():
        if righe:
            nessuna_trovata = False
    if nessuna_trovata:  # nessuna riga con due valori insieme: ci si accontenta di quelle con uno
        for tabella in candidate:
            trovate[tabella] = righe_abbastanza_forti(candidate[tabella], valori_per_riga, 1)

    # Righe collegate: nelle altre tabelle, quelle raggiungibili con un JOIN dalle righe gia' trovate.
    collegate = {}
    for tabella in tabelle_di_partenza:
        collegate[tabella] = []
    for origine in tabelle_di_partenza:
        if not trovate[origine]:
            continue
        colonne_origine = colonne_di(conn, origine)
        for destinazione in tabelle_di_partenza:
            if destinazione == origine or trovate[destinazione]:
                continue
            # Solo il collegamento piu' probabile.
            for colonna_a, colonna_b in chiavi_di_collegamento(conn, origine, destinazione)[:1]:
                posizione = colonne_origine.index(colonna_a)
                valori_chiave = set()
                for riga in trovate[origine]:
                    valori_chiave.add(riga[posizione])
                valori_chiave = valori_chiave - {None}
                chiavi = sorted(valori_chiave, key=str)
                segnaposti = ",".join("?" * len(chiavi))
                righe = conn.execute(f"SELECT * FROM {nome_sql(destinazione)} WHERE {nome_sql(colonna_b)} "
                                     f"IN ({segnaposti}) LIMIT {MAX_RIGHE_INDIZIO}", chiavi).fetchall()
                nuove = []
                for riga in righe:
                    if riga not in collegate[destinazione]:
                        nuove.append(riga)
                collegate[destinazione] += nuove

    parti = []
    for tabella in tabelle_di_partenza:
        intestazione = f"({', '.join(colonne_di(conn, tabella))})"
        if trovate[tabella]:
            parti.append(f"-- {tabella} {intestazione}, righe con valori dello STATO B:")
            parti.append(righe_come_testo(trovate[tabella]))
        if collegate[tabella]:
            parti.append(f"-- {tabella} {intestazione}, righe collegate a quelle sopra:")
            parti.append(righe_come_testo(collegate[tabella]))
    return "\n".join(parti)


# ---------------------------------------------------------------------------------------------------------
# Il prompt
# ---------------------------------------------------------------------------------------------------------

def descrivi_tabella_finale(conn, tabella):
    totale = conn.execute(f"SELECT COUNT(*) FROM {nome_sql(tabella)}").fetchone()[0]
    _, righe = leggi_righe(conn, nome_sql(tabella), MAX_RIGHE_FINALE)
    if totale <= MAX_RIGHE_FINALE:
        quante = "tutte"
    else:
        quante = f"le prime {MAX_RIGHE_FINALE}"
    return "\n".join([f"{sql_di_creazione(conn, tabella)};", f"-- {totale} righe, {quante}:", righe_come_testo(righe)])


def messaggi_iniziali(conn, tabelle_di_partenza, tabella_finale, suggerimenti=""):
    """La conversazione da mandare al modello: l'istruzione di sistema e il prompt."""
    return [{"role": "system", "content": ISTRUZIONE_DI_SISTEMA},
            {"role": "user", "content": prompt_iniziale(conn, tabelle_di_partenza, tabella_finale, suggerimenti)}]


def prompt_iniziale(conn, tabelle_di_partenza, tabella_finale, suggerimenti=""):
    """`suggerimenti`: testo in piu' del metodo misto (le query trovate dal programma), vuoto di base."""
    descrizioni = []
    for tabella in tabelle_di_partenza:
        descrizioni.append(descrivi_tabella_di_partenza(conn, tabella))
    stato_a = "\n\n".join(descrizioni)
    stato_b = descrivi_tabella_finale(conn, tabella_finale)

    sezione_indizi = ""
    if INDIZI:
        indizi = descrivi_indizi(conn, tabelle_di_partenza, tabella_finale)
        if indizi:
            sezione_indizi = ("\nINDIZI - righe delle tabelle di partenza da cui probabilmente nasce lo STATO B "
                              "(cercale con un filtro: cosa hanno in comune che le altre righe non hanno?)\n"
                              f"{indizi}\n")
    if suggerimenti:
        sezione_indizi += f"\nSUGGERIMENTI DEL PROGRAMMA\n{suggerimenti}\n"

    return f"""In un database SQLite le tabelle di partenza (STATO A) sono state trasformate da una query che non conosciamo nella tabella finale (STATO B). Scrivi quella query.

STATO A - tabelle di partenza
{stato_a}

STATO B - tabella finale
{stato_b}
{sezione_indizi}
REGOLE
1. SQL per SQLite. Puoi creare tabelle temporanee per i passaggi intermedi (CREATE TEMP TABLE ... AS SELECT ...), ma l'ultima istruzione deve essere una SELECT che restituisce esattamente le righe e le colonne dello STATO B.
2. Ricava filtri e valori dalle tabelle di partenza. Non scrivere a mano i valori che vedi nello STATO B (per esempio SELECT 'valore' UNION ALL ... oppure WHERE colonna IN ('valore1', 'valore2')): una query che li copia non e' una soluzione.
3. Se serve un dato che non e' nelle tabelle (per esempio un tasso di conversione), deducilo dagli esempi e controllalo su almeno due righe prima di usarlo.
4. Non modificare le tabelle esistenti: niente INSERT, UPDATE o DELETE.
5. Rispondi solo con un blocco ```sql ... ```, senza spiegazioni."""


def messaggio_di_correzione(esito):
    """Cosa dire al modello quando la sua query non riproduce la tabella finale.

    Usa solo informazioni che nell'uso reale ci sono sempre (la tabella finale e il risultato
    della query), mai la query vera.
    """
    if esito["errore"]:
        problema = f"La query non funziona: {esito['errore']}."
    elif esito["corretto"] and esito["copiatura_sospetta"]:
        copiati = []
        for valore in esito["valori_copiati"][:6]:
            copiati.append(repr(accorcia(valore)))
        problema = (f"La query restituisce la tabella finale, ma scrivendo a mano i suoi valori ({', '.join(copiati)}). "
                    "Cosi' non e' una soluzione: trova nelle tabelle di partenza il filtro o il JOIN che seleziona "
                    "proprio quelle righe, senza scrivere quei valori nella query.")
    else:
        righe = [f"La query restituisce {esito['righe_ottenute']} righe, la tabella finale ne ha {esito['righe_attese']} "
                 f"({esito['righe_giuste']} delle tue sono giuste)."]
        if esito["esempi_in_piu"]:
            righe.append("Righe che non dovrebbero esserci, per esempio:\n" + righe_come_testo(esito["esempi_in_piu"][:3]))
        if esito["esempi_mancanti"]:
            righe.append("Righe che mancano, per esempio:\n" + righe_come_testo(esito["esempi_mancanti"][:3]))
        if esito["righe_ottenute"] > esito["righe_attese"]:
            righe.append("Probabilmente manca un filtro, o e' troppo largo: cerca nelle tabelle di partenza "
                         "cosa distingue le righe giuste da quelle in piu'.")
        elif esito["righe_ottenute"] < esito["righe_attese"]:
            righe.append("Probabilmente il filtro e' troppo stretto, oppure manca un JOIN.")
        problema = "\n".join(righe)
    return problema + "\n\nScrivi di nuovo la query completa, solo il blocco ```sql ... ```."


def estrai_sql(risposta):
    """Tiene solo il codice SQL della risposta, scartando il ragionamento e il testo intorno."""
    # Alcuni modelli scrivono il ragionamento tra <think> o <thought>: puo' contenere bozze di SQL da non eseguire.
    risposta = re.sub(r"<(think|thought)>.*?</\1>", "", risposta, flags=re.DOTALL)
    # I blocchi ```sql ... ``` (o ``` ... ```): se ce ne sono piu' d'uno si uniscono.
    blocchi = re.findall(r"```(?:sql|SQL|sqlite)?\s*\n?(.*?)```", risposta, flags=re.DOTALL)
    if not blocchi:
        return risposta.strip()
    pezzi = []
    for blocco in blocchi:
        if blocco.strip():
            pezzi.append(blocco.strip())
    return "\n".join(pezzi)
