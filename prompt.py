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


def _accorcia(valore):
    if isinstance(valore, str) and len(valore) > MAX_CARATTERI_VALORE:
        return valore[:MAX_CARATTERI_VALORE] + "..."
    return valore


def _righe_come_testo(righe):
    return "\n".join(repr(tuple(_accorcia(v) for v in riga)) for riga in righe)


def _sql_di_creazione(conn, tabella):
    return conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (tabella,)).fetchone()[0]


def descrivi_tabella_di_partenza(conn, tabella):
    # Le prime righe e non righe a caso: stesso prompt a ogni esecuzione, e su tabelle grandi
    # ORDER BY RANDOM() costa una lettura completa.
    totale = conn.execute(f"SELECT COUNT(*) FROM {nome_sql(tabella)}").fetchone()[0]
    colonne, esempi = leggi_righe(conn, nome_sql(tabella), N_ESEMPI)
    parti = [f"{_sql_di_creazione(conn, tabella)};",
             f"-- {totale} righe. Le prime {len(esempi)}:", _righe_come_testo(esempi),
             "-- Alcuni valori di ogni colonna:"]
    for colonna in colonne:
        # Basta sapere se i valori diversi sono al massimo 25: contarli tutti su testi lunghi costa secondi.
        valori = [riga[0] for riga in conn.execute(
            f"SELECT DISTINCT {nome_sql(colonna)} FROM {nome_sql(tabella)} LIMIT {MAX_VALORI_COMPLETI + 1}")]
        pochi = len(valori) <= MAX_VALORI_COMPLETI
        valori = valori if pochi else valori[:N_VALORI_PER_COLONNA]
        quanti = f"tutti i {len(valori)} valori" if pochi else f"piu' di {MAX_VALORI_COMPLETI} valori diversi, alcuni"
        parti.append(f"--   {colonna} ({quanti}): {[_accorcia(v) for v in valori]}")
    return "\n".join(parti)


def _significativo(valore):
    return valore is not None and not (isinstance(valore, str) and len(valore) < 2)


def _righe_che_contengono(conn, tabella, valore):
    """Le righe (con il rowid) in cui una qualsiasi colonna vale `valore`, ma solo se sono poche."""
    colonne = colonne_di(conn, tabella)
    condizione = " OR ".join(f"{nome_sql(c)} = ?" for c in colonne)
    righe = conn.execute(f"SELECT rowid, * FROM {nome_sql(tabella)} WHERE {condizione} LIMIT {MAX_RIGHE_PER_VALORE + 1}",
                         [valore] * len(colonne)).fetchall()
    return righe if len(righe) <= MAX_RIGHE_PER_VALORE else []


def descrivi_indizi(conn, tabelle_di_partenza, tabella_finale):
    """Le righe di partenza da cui probabilmente nasce la tabella finale, e quelle collegate a loro.

    Di solito il prompt mostra solo le prime righe di ogni tabella e le righe da cui nasce la tabella
    finale non ci sono: il modello deve indovinare il filtro senza vederne le prove. Qui le cerchiamo
    noi (es. i 3 soci della tabella finale e, collegate dal loro CAP, le righe dei CAP con lo stato).
    Usa solo dati che nell'uso reale ci sono sempre: le tabelle di partenza e la tabella finale.
    """
    _, righe_finali = leggi_righe(conn, nome_sql(tabella_finale), MAX_RIGHE_FINALI_CERCATE)
    valori_per_riga = [{v for v in riga if _significativo(v)} for riga in righe_finali]
    tutti_i_valori = set().union(*valori_per_riga) if valori_per_riga else set()
    # Se la tabella finale ha piu' colonne, una riga di partenza conta solo se contiene almeno due valori
    # della stessa riga finale (nome E cognome): un solo valore puo' coincidere per caso (una citta' "Smith").
    minimo = 2 if any(len(v) >= 2 for v in valori_per_riga) else 1

    def forza(riga):
        return max((len(valori & set(riga)) for valori in valori_per_riga), default=0)

    candidate, trovate = {}, {}
    for tabella in tabelle_di_partenza:
        righe = {}
        for valore in tutti_i_valori:
            for riga in _righe_che_contengono(conn, tabella, valore):
                righe[riga[0]] = riga[1:]
        candidate[tabella] = list(righe.values())
        trovate[tabella] = [r for r in candidate[tabella] if forza(r) >= minimo][:MAX_RIGHE_INDIZIO]
    if not any(trovate.values()):  # nessuna riga con due valori insieme: si accontenta di quelle con uno
        trovate = {t: [r for r in rr if forza(r) >= 1][:MAX_RIGHE_INDIZIO] for t, rr in candidate.items()}

    # Righe collegate: nelle altre tabelle, quelle raggiungibili con un JOIN dalle righe gia' trovate.
    collegate = {t: [] for t in tabelle_di_partenza}
    for origine in tabelle_di_partenza:
        if not trovate[origine]:
            continue
        colonne_origine = colonne_di(conn, origine)
        for destinazione in tabelle_di_partenza:
            if destinazione == origine or trovate[destinazione]:
                continue
            for colonna_a, colonna_b in chiavi_di_collegamento(conn, origine, destinazione)[:1]:
                chiavi = sorted({r[colonne_origine.index(colonna_a)] for r in trovate[origine]} - {None}, key=str)
                segnaposti = ",".join("?" * len(chiavi))
                righe = conn.execute(f"SELECT * FROM {nome_sql(destinazione)} WHERE {nome_sql(colonna_b)} IN ({segnaposti}) "
                                     f"LIMIT {MAX_RIGHE_INDIZIO}", chiavi).fetchall()
                collegate[destinazione] += [r for r in righe if r not in collegate[destinazione]]

    parti = []
    for tabella in tabelle_di_partenza:
        intestazione = f"({', '.join(colonne_di(conn, tabella))})"
        if trovate[tabella]:
            parti += [f"-- {tabella} {intestazione}, righe con valori dello STATO B:", _righe_come_testo(trovate[tabella])]
        if collegate[tabella]:
            parti += [f"-- {tabella} {intestazione}, righe collegate a quelle sopra:", _righe_come_testo(collegate[tabella])]
    return "\n".join(parti)


def descrivi_tabella_finale(conn, tabella):
    totale = conn.execute(f"SELECT COUNT(*) FROM {nome_sql(tabella)}").fetchone()[0]
    _, righe = leggi_righe(conn, nome_sql(tabella), MAX_RIGHE_FINALE)
    quante = "tutte" if totale <= MAX_RIGHE_FINALE else f"le prime {MAX_RIGHE_FINALE}"
    return "\n".join([f"{_sql_di_creazione(conn, tabella)};", f"-- {totale} righe, {quante}:", _righe_come_testo(righe)])


# Senza questa istruzione Gemma scrive il ragionamento nella risposta (il 95% del testo):
# con l'istruzione e' passata da 173 a 43 secondi sullo stesso caso, con lo stesso risultato.
ISTRUZIONE_DI_SISTEMA = "Rispondi subito con la query SQL. Non scrivere il ragionamento."


def messaggi_iniziali(conn, tabelle_di_partenza, tabella_finale, suggerimenti=""):
    return [{"role": "system", "content": ISTRUZIONE_DI_SISTEMA},
            {"role": "user", "content": prompt_iniziale(conn, tabelle_di_partenza, tabella_finale, suggerimenti)}]


def prompt_iniziale(conn, tabelle_di_partenza, tabella_finale, suggerimenti=""):
    """`suggerimenti`: testo in piu' del metodo misto (le query trovate dal programma), vuoto di base."""
    stato_a = "\n\n".join(descrivi_tabella_di_partenza(conn, t) for t in tabelle_di_partenza)
    stato_b = descrivi_tabella_finale(conn, tabella_finale)
    indizi = descrivi_indizi(conn, tabelle_di_partenza, tabella_finale) if INDIZI else ""
    sezione_indizi = (f"\nINDIZI - righe delle tabelle di partenza da cui probabilmente nasce lo STATO B "
                      f"(cercale con un filtro: cosa hanno in comune che le altre righe non hanno?)\n{indizi}\n") if indizi else ""
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
        copiati = ", ".join(repr(_accorcia(v)) for v in esito["valori_copiati"][:6])
        problema = (f"La query restituisce la tabella finale, ma scrivendo a mano i suoi valori ({copiati}). "
                    "Cosi' non e' una soluzione: trova nelle tabelle di partenza il filtro o il JOIN che seleziona "
                    "proprio quelle righe, senza scrivere quei valori nella query.")
    else:
        righe = [f"La query restituisce {esito['righe_ottenute']} righe, la tabella finale ne ha {esito['righe_attese']} "
                 f"({esito['righe_giuste']} delle tue sono giuste)."]
        if esito["esempi_in_piu"]:
            righe.append("Righe che non dovrebbero esserci, per esempio:\n" + _righe_come_testo(esito["esempi_in_piu"][:3]))
        if esito["esempi_mancanti"]:
            righe.append("Righe che mancano, per esempio:\n" + _righe_come_testo(esito["esempi_mancanti"][:3]))
        if esito["righe_ottenute"] > esito["righe_attese"]:
            righe.append("Probabilmente manca un filtro, o e' troppo largo: cerca nelle tabelle di partenza "
                         "cosa distingue le righe giuste da quelle in piu'.")
        elif esito["righe_ottenute"] < esito["righe_attese"]:
            righe.append("Probabilmente il filtro e' troppo stretto, oppure manca un JOIN.")
        problema = "\n".join(righe)
    return problema + "\n\nScrivi di nuovo la query completa, solo il blocco ```sql ... ```."


def senza_ragionamento(risposta):
    """La risposta da rimettere nella conversazione: il ragionamento si toglie, occupa spazio e non serve."""
    return re.sub(r"<(think|thought)>.*?</\1>", "", risposta, flags=re.DOTALL).strip()


def estrai_sql(risposta):
    """Tiene solo il codice SQL della risposta, scartando il ragionamento e il testo intorno."""
    # Alcuni modelli scrivono il ragionamento tra <think> o <thought>: puo' contenere bozze di SQL da non eseguire.
    risposta = re.sub(r"<(think|thought)>.*?</\1>", "", risposta, flags=re.DOTALL)
    blocchi = re.findall(r"```(?:sql|SQL|sqlite)?\s*\n?(.*?)```", risposta, flags=re.DOTALL)
    return "\n".join(b.strip() for b in blocchi if b.strip()) if blocchi else risposta.strip()
