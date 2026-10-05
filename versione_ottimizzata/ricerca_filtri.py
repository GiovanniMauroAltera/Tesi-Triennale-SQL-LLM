"""Prima parte della versione ottimizzata: cerca nei dati le regole che selezionano le righe giuste.

Non usa modelli linguistici: prova le regole possibili una per una. Il procedimento:
1. per ogni colonna della tabella finale cerca la colonna di partenza che ne contiene tutti i valori
   (anche unendo le due tabelle con il loro collegamento);
2. divide le righe di partenza in "giuste" (finiscono nella tabella finale) e "sbagliate";
3. prova le regole dalla piu' semplice alla piu' complicata e tiene quelle che lasciano passare le righe
   giuste e nessuna sbagliata. Ogni query trovata e' verificata come quelle dei modelli.

Le regole trovate diventano i "suggerimenti del programma" che versione_ottimizzata.py manda ai modelli.
Da sole non bastano: il programma non sa fare calcoli (conteggi, somme, medie) ne' dedurre valori che non
sono nei dati, e puo' trovare una regola che funziona per coincidenza (un intervallo di CAP al posto
dello stato). Per questo le regole semplici vengono provate per prime e la scelta finale la fa il modello.
"""
import bisect
import random
import re
import time

from verifica import chiavi_di_collegamento, colonne_di, leggi_righe, nome_sql, verifica

MAX_RIGHE_BASE = 300_000            # tabelle (o coppie di tabelle unite) piu' grandi si saltano: troppo lente
MAX_CANDIDATI_PER_COLONNA = 3       # colonne di partenza provate per ogni colonna finale
MAX_PROIEZIONI = 12                 # combinazioni di colonne provate per ogni tabella
MAX_SBAGLIATE_CONTROLLATE = 20_000  # il primo controllo si fa su un campione, la verifica finale su tutto
MAX_VALORI_IN = 3
MAX_COLLEGAMENTI = 4                # per verso: superhero ha eye_colour_id, hair_colour_id, skin_colour_id...
MAX_COPPIE = 5_000
MAX_RIGHE_PRIMI_N_CON_FILTRO = 20_000
DATA = re.compile(r"^\d{4}-\d{2}-\d{2}")
IDENTIFICATIVO = re.compile(r'(^|_)id$|(^|[a-z_])(Id|ID)$')  # id, member_id, circuitId, GasStationID (non "paid")

# I livelli delle regole, dal piu' semplice. Ogni livello si prova su tutte le tabelle prima di passare al
# successivo: cosi' "state = 'Illinois'" (tabella collegata) viene prima di un intervallo di CAP che funziona per caso.
NESSUN_FILTRO = 0
UGUALE = 1
PARTE = 2
DUE_UGUALI = 3
INTERVALLO = 4
ELENCO = 5
DUE_REGOLE = 6
PRIMI_N = 7
NOMI_DEI_LIVELLI = ["nessun filtro", "colonna = valore", "parte di un valore (anno, mese, inizio) o valore non vuoto",
                    "due condizioni '='", "intervallo di numeri", "elenco di valori", "due condizioni", "primi N in ordine"]


# ---------------------------------------------------------------------------------------------------------
# Piccole funzioni di aiuto
# ---------------------------------------------------------------------------------------------------------

def letterale(valore):
    """Il valore scritto come in SQL: i testi tra apici, con l'apice raddoppiato ('Ancestor''s Chosen')."""
    if isinstance(valore, str):
        return "'" + valore.replace("'", "''") + "'"
    return repr(valore)


def e_un_numero(valore):
    # True e False in Python sono anche numeri: qui non li vogliamo.
    return isinstance(valore, (int, float)) and not isinstance(valore, bool)


def solo_numeri_o_date(valori):
    """True se i valori (tolti quelli vuoti) sono tutti numeri o tutti date 'AAAA-MM-GG'."""
    presenti = []
    for v in valori:
        if v is not None:
            presenti.append(v)
    if not presenti:
        return False
    tutti_numeri = True
    tutte_date = True
    for v in presenti:
        if not e_un_numero(v):
            tutti_numeri = False
        if not (isinstance(v, str) and DATA.match(v)):
            tutte_date = False
    return tutti_numeri or tutte_date


def conta(elementi):
    """Quante volte compare ogni elemento: ['a', 'b', 'a'] -> {'a': 2, 'b': 1}."""
    conteggio = {}
    for elemento in elementi:
        conteggio[elemento] = conteggio.get(elemento, 0) + 1
    return conteggio


def prefisso_comune(testi):
    """L'inizio comune a tutti i testi: ['1:54.1', '1:54.9'] -> '1:54.'."""
    primo = min(testi)
    ultimo = max(testi)
    n = 0
    while n < min(len(primo), len(ultimo)) and primo[n] == ultimo[n]:
        n += 1
    return primo[:n]


def tutte_le_combinazioni(liste):
    """Una scelta da ogni lista: [[1, 2], [3, 4]] -> [(1, 3), (1, 4), (2, 3), (2, 4)]."""
    combinazioni = [()]
    for lista in liste:
        nuove = []
        for combinazione in combinazioni:
            for elemento in lista:
                nuove.append(combinazione + (elemento,))
        combinazioni = nuove
    return combinazioni


# ---------------------------------------------------------------------------------------------------------
# 1. Dove cercare: ogni tabella da sola, e le due tabelle unite dai loro collegamenti
# ---------------------------------------------------------------------------------------------------------

def parole_del_nome(nome):
    """Le parole di un nome di colonna: circuitId -> {circuit, id}; link_to_member -> {link, to, member}."""
    parole = set()
    for parola in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", nome):
        parole.add(parola.lower())
    return parole


def nomi_compatibili(colonna_a, colonna_b):
    """Due colonne si collegano se i nomi hanno una parola in comune (zip e zip_code, link_to_member e
    member_id), oppure se una si chiama "id" e l'altra e' un riferimento (eye_colour_id)."""
    parole_a = parole_del_nome(colonna_a)
    parole_b = parole_del_nome(colonna_b)
    if colonna_a.lower() == "id" or colonna_b.lower() == "id":
        return "id" in parole_a and "id" in parole_b
    in_comune = (parole_a & parole_b) - {"id"}
    return len(in_comune) > 0


def basi_possibili(conn, tabelle):
    """Le "basi" in cui cercare: per ognuna il FROM della query e l'elenco delle colonne."""
    basi = []
    for tabella in tabelle:
        colonne = []
        for colonna in colonne_di(conn, tabella):
            colonne.append(f"t0.{nome_sql(colonna)}")
        basi.append({"from": f"{nome_sql(tabella)} AS t0", "colonne": colonne})
    if len(tabelle) != 2:
        return basi

    a, b = tabelle
    colonne_a = colonne_di(conn, a)
    colonne_b = colonne_di(conn, b)
    collegamenti = []
    # Le colonne con molti valori in comune (verifica.chiavi_di_collegamento), in tutti e due i versi.
    # Valori simili pero' non bastano: circuitId e raceId sono tutti e due numeri da 1 in su, ma non si
    # collegano. Per questo servono anche nomi compatibili.
    for colonna_a, colonna_b in chiavi_di_collegamento(conn, a, b)[:MAX_COLLEGAMENTI]:
        if nomi_compatibili(colonna_a, colonna_b):
            collegamenti.append((colonna_a, colonna_b))
    for colonna_b, colonna_a in chiavi_di_collegamento(conn, b, a)[:MAX_COLLEGAMENTI]:
        if nomi_compatibili(colonna_a, colonna_b):
            collegamenti.append((colonna_a, colonna_b))
    # Anche le colonne con lo stesso nome (ID e ID): a volte solo poche righe hanno il corrispondente
    # nell'altra tabella e chiavi_di_collegamento, che ne chiede l'80%, non le riconosce.
    for colonna_a in colonne_a:
        for colonna_b in colonne_b:
            if colonna_a.lower() == colonna_b.lower():
                collegamenti.append((colonna_a, colonna_b))
    # E i nomi del tipo superhero.alignment_id -> alignment.id (tabelle piccole, che l'altra regola scarta).
    if "id" in colonne_b:
        for colonna_a in colonne_a:
            if colonna_a.lower() in (f"{b.lower()}_id", f"{b.lower()}id"):
                collegamenti.append((colonna_a, "id"))
    if "id" in colonne_a:
        for colonna_b in colonne_b:
            if colonna_b.lower() in (f"{a.lower()}_id", f"{a.lower()}id"):
                collegamenti.append(("id", colonna_b))

    gia_usati = []
    for colonna_a, colonna_b in collegamenti:
        if (colonna_a, colonna_b) in gia_usati:
            continue  # lo stesso collegamento trovato in due modi
        gia_usati.append((colonna_a, colonna_b))
        colonne = []
        for colonna in colonne_a:
            colonne.append(f"t0.{nome_sql(colonna)}")
        for colonna in colonne_b:
            colonne.append(f"t1.{nome_sql(colonna)}")
        basi.append({"from": f"{nome_sql(a)} AS t0 JOIN {nome_sql(b)} AS t1 "
                             f"ON t0.{nome_sql(colonna_a)} = t1.{nome_sql(colonna_b)}",
                     "colonne": colonne})
    return basi


# ---------------------------------------------------------------------------------------------------------
# 2. Le regole su una colonna
# ---------------------------------------------------------------------------------------------------------
# Una regola e' un dizionario: il livello, la colonna, il pezzo di SQL e i dati per controllarla in Python
# (con righe_che_passano).
#   tipo "vuoto"       colonna IS NULL
#   tipo "non_vuoto"   colonna IS NOT NULL
#   tipo "uguale"      colonna = valore
#   tipo "inizia_con"  il testo inizia con valore (anno o mese di una data, inizio di un testo)
#   tipo "almeno"      colonna >= valore
#   tipo "al_massimo"  colonna <= valore
#   tipo "tra"         colonna BETWEEN valore AND massimo
#   tipo "in_elenco"   colonna IN (valori)

def nuova_regola(livello, colonna, sql, tipo, valore=None, massimo=None):
    return {"livello": livello, "colonna": colonna, "sql": sql, "tipo": tipo, "valore": valore, "massimo": massimo}


def righe_che_passano(regola, righe):
    """I numeri (le posizioni nella lista) delle righe che passano la regola: lo stesso controllo che
    fara' SQLite con il pezzo di SQL.

    C'e' un ciclo per ogni tipo di regola invece di una funzione chiamata per ogni riga: questi controlli
    si fanno centinaia di milioni di volte e cosi' sono molto piu' veloci.
    """
    i = regola["colonna"]
    tipo = regola["tipo"]
    valore = regola["valore"]
    passano = set()
    if tipo == "vuoto":
        for k, riga in enumerate(righe):
            if riga[i] is None:
                passano.add(k)
    elif tipo == "non_vuoto":
        for k, riga in enumerate(righe):
            if riga[i] is not None:
                passano.add(k)
    elif tipo == "uguale":
        for k, riga in enumerate(righe):
            if riga[i] == valore:
                passano.add(k)
    elif tipo == "inizia_con":
        for k, riga in enumerate(righe):
            if isinstance(riga[i], str) and riga[i].startswith(valore):
                passano.add(k)
    elif tipo == "in_elenco":
        for k, riga in enumerate(righe):
            if riga[i] in valore:
                passano.add(k)
    # Gli intervalli valgono solo per i numeri.
    elif tipo == "almeno":
        for k, riga in enumerate(righe):
            if e_un_numero(riga[i]) and riga[i] >= valore:
                passano.add(k)
    elif tipo == "al_massimo":
        for k, riga in enumerate(righe):
            if e_un_numero(riga[i]) and riga[i] <= valore:
                passano.add(k)
    elif tipo == "tra":
        massimo = regola["massimo"]
        for k, riga in enumerate(righe):
            if e_un_numero(riga[i]) and valore <= riga[i] <= massimo:
                passano.add(k)
    return passano


def regole_di_una_colonna(nome, i, giuste, chiavi_giuste, tutte, sbagliate, proiettata):
    """Le regole su una colonna che lasciano passare almeno una riga giusta per ogni riga finale.

    "Almeno una" e non "tutte": con DISTINCT una squadra con piu' stagioni finisce nella tabella finale
    anche se solo una stagione rispetta il filtro.
    """
    # Per ogni valore della colonna, le righe finali che hanno una riga di partenza con quel valore.
    copertura = {}
    for riga, chiave in zip(giuste, chiavi_giuste):
        valore = riga[i]
        if valore not in copertura:
            copertura[valore] = set()
        copertura[valore].add(chiave)

    def copre(valori):
        """True se tenendo le righe con questi valori resta almeno una riga per ogni riga finale."""
        coperte = set()
        for valore in valori:
            # "|=" aggiunge all'insieme che c'e' gia'. Scrivere "coperte = coperte | ..." creerebbe ogni volta
            # un insieme nuovo: con migliaia di valori diventa lentissimo.
            coperte |= copertura.get(valore, set())
        return len(coperte) == len(tutte)

    regole = []
    if copre([None]):
        regole.append(nuova_regola(UGUALE, i, f"{nome} IS NULL", "vuoto"))
    non_nulli = []
    for valore in copertura:
        if valore is not None:
            non_nulli.append(valore)
    if not non_nulli or not copre(non_nulli):
        return regole
    regole.append(nuova_regola(PARTE, i, f"{nome} IS NOT NULL", "non_vuoto"))
    if proiettata:
        return regole  # filtrare sugli stessi valori che si vogliono ottenere vorrebbe dire copiarli

    # colonna = valore
    for valore in non_nulli:
        if copre([valore]):
            regole.append(nuova_regola(UGUALE, i, f"{nome} = {letterale(valore)}", "uguale", valore))

    # Anno o mese di una data, oppure l'inizio comune di tutti i testi.
    testi = []
    date = []
    for valore in non_nulli:
        if isinstance(valore, str):
            testi.append(valore)
            if DATA.match(valore):
                date.append(valore)
    for lunghezza, formato in ((4, "%Y"), (7, "%Y-%m")):
        date_per_parte = {}  # '2005' (o '2005-09') -> le date che iniziano cosi'
        for data in date:
            parte = data[:lunghezza]
            if parte not in date_per_parte:
                date_per_parte[parte] = []
            date_per_parte[parte].append(data)
        for parte, valori in date_per_parte.items():
            if len(valori) > 1 and copre(valori):
                regole.append(nuova_regola(PARTE, i, f"STRFTIME('{formato}', {nome}) = '{parte}'", "inizia_con", parte))
    if len(testi) == len(non_nulli) and len(testi) > 1 and not date:
        prefisso = prefisso_comune(testi)
        if len(prefisso) >= 3:
            regole.append(nuova_regola(PARTE, i, f"SUBSTR({nome}, 1, {len(prefisso)}) = {letterale(prefisso)}",
                                       "inizia_con", prefisso))

    # Intervalli di numeri. I valori delle righe sbagliate sono "vietati": un intervallo buono sta in un
    # buco tra due valori vietati e contiene almeno una riga giusta per ogni riga finale.
    numeri = []
    for valore in non_nulli:
        if e_un_numero(valore):
            numeri.append(valore)
    numeri.sort()
    vietati = set()
    for riga in sbagliate:
        if e_un_numero(riga[i]):
            vietati.add(riga[i])
    vietati_in_ordine = sorted(vietati)
    numeri_per_buco = {}  # numero del buco (quanti valori vietati ci sono prima) -> i numeri giusti che ci cadono
    for numero in numeri:
        if numero in vietati:
            continue
        # bisect_left conta, con una ricerca veloce nella lista ordinata, i valori vietati piu' piccoli di numero.
        buco = bisect.bisect_left(vietati_in_ordine, numero)
        if buco not in numeri_per_buco:
            numeri_per_buco[buco] = []
        numeri_per_buco[buco].append(numero)
    for buco, valori in numeri_per_buco.items():
        if len(valori) < 2 or not copre(valori):
            continue  # con un valore solo basta la regola "="
        minimo = valori[0]
        massimo = valori[-1]
        if buco == len(vietati_in_ordine):  # nessun valore vietato sopra: basta ">="
            regole.append(nuova_regola(INTERVALLO, i, f"{nome} >= {letterale(minimo)}", "almeno", minimo))
        elif buco == 0:  # nessun valore vietato sotto: basta "<="
            regole.append(nuova_regola(INTERVALLO, i, f"{nome} <= {letterale(massimo)}", "al_massimo", massimo))
        else:
            regole.append(nuova_regola(INTERVALLO, i, f"{nome} BETWEEN {letterale(minimo)} AND {letterale(massimo)}",
                                       "tra", minimo, massimo))

    # Un elenco di pochi valori: colonna IN (...)
    if 1 < len(non_nulli) <= MAX_VALORI_IN:
        valori_scritti = []
        for valore in sorted(non_nulli, key=str):
            valori_scritti.append(letterale(valore))
        regole.append(nuova_regola(ELENCO, i, f"{nome} IN ({', '.join(valori_scritti)})", "in_elenco", set(non_nulli)))
    return regole


# ---------------------------------------------------------------------------------------------------------
# 3. Il "contesto": una base (tabella o tabelle unite) e la scelta delle colonne da cui vengono quelle finali
# ---------------------------------------------------------------------------------------------------------
# Se qualche colonna finale e' un calcolo (non si trova tra quelle di partenza) il contesto e' "parziale":
# si puo' cercare il filtro sulle altre colonne, ma non la query completa.

def proietta(contesto, riga):
    """I valori della riga nelle colonne scelte, nell'ordine delle colonne finali."""
    valori = []
    for i in contesto["proiezione"]:
        valori.append(riga[i])
    return tuple(valori)


def crea_contesto(base, righe, valori_colonna, posizioni, proiezione, righe_finali):
    contesto = {"base": base, "righe": righe, "proiezione": proiezione, "colonne_sql": base["colonne"]}

    # Peso di ogni colonna (piu' basso = regola piu' credibile): le colonne "di categoria" (paese, stato,
    # colore) hanno pochi valori diversi; un filtro su un ID o su un codice e' piu' spesso una coincidenza.
    # Per i "primi N" si ordina solo per numeri o date (punti, punteggio, data di nascita): i primi N
    # in ordine di un ID o di un codice ("ORDER BY hero_id LIMIT 4") sono quasi sempre una coincidenza.
    contesto["pesi"] = []
    contesto["ordinabili"] = set()
    for i, nome in enumerate(contesto["colonne_sql"]):
        nome_semplice = nome.split(".", 1)[1].strip('"')  # t0."circuitId" -> circuitId
        identificativo = IDENTIFICATIVO.search(nome_semplice) is not None
        peso = len(valori_colonna[i])
        if identificativo:
            peso = peso * 10
        contesto["pesi"].append(peso)
        if not identificativo and solo_numeri_o_date(valori_colonna[i]):
            contesto["ordinabili"].add(i)

    # Le righe finali, contate: quante volte deve comparire ogni riga (sulle colonne scelte).
    contesto["completo"] = len(posizioni) == len(righe_finali[0])
    finali = []
    for riga in righe_finali:
        valori = []
        for j in posizioni:
            valori.append(riga[j])
        finali.append(tuple(valori))
    contesto["attese"] = conta(finali)
    contesto["doppioni"] = False
    for quante in contesto["attese"].values():
        if quante > 1:
            contesto["doppioni"] = True

    # Righe giuste (finiscono nella tabella finale) e sbagliate.
    giuste = []
    sbagliate = []
    for riga in righe:
        if proietta(contesto, riga) in contesto["attese"]:
            giuste.append(riga)
        else:
            sbagliate.append(riga)
    chiavi_giuste = []
    for riga in giuste:
        chiavi_giuste.append(proietta(contesto, riga))
    # Il contesto serve solo se ogni riga finale si puo' ottenere da qualche riga di partenza.
    contesto["utile"] = set(chiavi_giuste) == set(contesto["attese"])
    if len(sbagliate) > MAX_SBAGLIATE_CONTROLLATE:
        sbagliate = random.Random(0).sample(sbagliate, MAX_SBAGLIATE_CONTROLLATE)
    contesto["giuste"] = giuste
    contesto["sbagliate"] = sbagliate
    contesto["chiavi_giuste"] = chiavi_giuste

    tutte = set(contesto["attese"])
    contesto["regole"] = []
    for i, nome in enumerate(contesto["colonne_sql"]):
        proiettata = i in proiezione
        contesto["regole"] += regole_di_una_colonna(nome, i, giuste, chiavi_giuste, tutte, sbagliate, proiettata)

    # Memoria dei controlli gia' fatti: ogni regola si prova sulle righe una volta sola.
    contesto["memoria_sbagliate"] = {}
    contesto["memoria_giuste"] = {}
    return contesto


def sbagliate_che_passano(contesto, regola):
    """I numeri delle righe sbagliate (del campione) che la regola lascerebbe passare."""
    memoria = contesto["memoria_sbagliate"]
    if regola["sql"] not in memoria:
        memoria[regola["sql"]] = righe_che_passano(regola, contesto["sbagliate"])
    return memoria[regola["sql"]]


def giuste_che_passano(contesto, regola):
    """I numeri delle righe giuste che la regola lascia passare."""
    memoria = contesto["memoria_giuste"]
    if regola["sql"] not in memoria:
        memoria[regola["sql"]] = righe_che_passano(regola, contesto["giuste"])
    return memoria[regola["sql"]]


def regole_funzionano(contesto, regole):
    """Con queste regole insieme (una o due) non passa nessuna riga sbagliata, e passa almeno una riga
    giusta per ogni riga finale."""
    sbagliate = sbagliate_che_passano(contesto, regole[0])
    for regola in regole[1:]:
        sbagliate = sbagliate & sbagliate_che_passano(contesto, regola)
    if sbagliate:
        return False
    giuste = giuste_che_passano(contesto, regole[0])
    for regola in regole[1:]:
        giuste = giuste & giuste_che_passano(contesto, regola)
    righe_finali_coperte = set()
    for k in giuste:
        righe_finali_coperte.add(contesto["chiavi_giuste"][k])
    return len(righe_finali_coperte) == len(contesto["attese"])


def candidate_del_livello(contesto, livello, scadenza):
    """Le query candidate di un livello: (peso, condizione WHERE, ORDER BY ... LIMIT ...).

    Restituisce anche True se il tempo e' finito a meta' (allora la lista e' incompleta).
    """
    candidate = []
    if livello == NESSUN_FILTRO:
        if not contesto["sbagliate"]:
            candidate.append((0, "", ""))
            if time.time() > scadenza:
                return candidate, True

    elif livello in (UGUALE, PARTE, INTERVALLO, ELENCO):
        for regola in contesto["regole"]:
            if regola["livello"] == livello and regole_funzionano(contesto, [regola]):
                candidate.append((contesto["pesi"][regola["colonna"]], regola["sql"], ""))
                if time.time() > scadenza:
                    return candidate, True

    elif livello in (DUE_UGUALI, DUE_REGOLE):
        # Tutte le coppie di regole su colonne diverse: con DUE_UGUALI solo coppie di "=", con DUE_REGOLE le altre.
        regole = contesto["regole"]
        coppie_provate = 0
        for x in range(len(regole)):
            for y in range(x + 1, len(regole)):
                a = regole[x]
                b = regole[y]
                if a["colonna"] == b["colonna"]:
                    continue
                tutte_e_due_uguale = a["livello"] == UGUALE and b["livello"] == UGUALE
                if tutte_e_due_uguale != (livello == DUE_UGUALI):
                    continue
                coppie_provate += 1
                if coppie_provate > MAX_COPPIE:
                    return candidate, False
                # Se una delle due da sola non lascia passare righe sbagliate, la coppia non serve.
                if not sbagliate_che_passano(contesto, a) or not sbagliate_che_passano(contesto, b):
                    continue
                if regole_funzionano(contesto, [a, b]):
                    peso = contesto["pesi"][a["colonna"]] + contesto["pesi"][b["colonna"]]
                    candidate.append((peso, f"{a['sql']} AND {b['sql']}", ""))
                    if time.time() > scadenza:
                        return candidate, True

    elif livello == PRIMI_N and contesto["completo"]:
        return candidate_primi_n(contesto, scadenza)

    return candidate, False


def ordina_per_colonna(righe, i, verso):
    """Le righe ordinate secondo la colonna i: dal valore piu' grande (DESC) o dal piu' piccolo (ASC)."""
    coppie = []
    for posizione, riga in enumerate(righe):
        # La posizione serve a parita' di valore: cosi' Python non confronta mai due righe intere.
        coppie.append((riga[i], posizione))
    coppie.sort(reverse=(verso == "DESC"))
    ordinate = []
    for valore, posizione in coppie:
        ordinate.append(righe[posizione])
    return ordinate


def candidate_primi_n(contesto, scadenza):
    """ORDER BY ... LIMIT N: le righe finali sono le prime N in ordine di una colonna (anche dopo un filtro)."""
    candidate = []
    n = sum(contesto["attese"].values())
    filtri = [None]
    if len(contesto["righe"]) <= MAX_RIGHE_PRIMI_N_CON_FILTRO:
        # Solo i filtri che da soli non bastano: se bastano, ORDER BY ... LIMIT non aggiunge niente.
        for regola in contesto["regole"]:
            if regola["livello"] in (UGUALE, PARTE) and sbagliate_che_passano(contesto, regola):
                filtri.append(regola)

    for filtro in filtri:
        if filtro is None:
            righe = contesto["righe"]
        else:
            righe = []
            for k in sorted(righe_che_passano(filtro, contesto["righe"])):  # nello stesso ordine di prima
                righe.append(contesto["righe"][k])
        for i, nome in enumerate(contesto["colonne_sql"]):
            if filtro is not None and filtro["colonna"] == i:
                continue
            if i not in contesto["ordinabili"]:
                continue
            valide = []
            for riga in righe:
                if riga[i] is not None:
                    valide.append(riga)
            for verso in ("DESC", "ASC"):
                ordinate = ordina_per_colonna(valide, i, verso)
                primi = ordinate[:n + 1]
                if len(primi) > n and primi[n - 1][i] == primi[n][i]:
                    continue  # pari merito al confine: quali righe restano dipende dal caso, non e' una regola
                primi = primi[:n]
                chiavi_dei_primi = []
                for riga in primi:
                    chiavi_dei_primi.append(proietta(contesto, riga))
                if primi and conta(chiavi_dei_primi) == contesto["attese"]:
                    if filtro is None:
                        condizione = f"{nome} IS NOT NULL"
                        peso = 0  # ordinare per una data o un numero e' normale
                    else:
                        condizione = f"{filtro['sql']} AND {nome} IS NOT NULL"
                        peso = contesto["pesi"][filtro["colonna"]]
                    candidate.append((peso, condizione, f" ORDER BY {nome} {verso} LIMIT {n}"))
                    if time.time() > scadenza:
                        return candidate, True
    return candidate, False


def scrivi_sql(contesto, condizione, ordine):
    """La query completa: SELECT colonne FROM base WHERE condizione ORDER BY ..."""
    if ordine or (contesto["completo"] and contesto["doppioni"]):
        distinct = ""
    else:
        distinct = "DISTINCT "
    where = ""
    if condizione:
        where = f" WHERE {condizione}"
    colonne = []
    for i in contesto["proiezione"]:
        colonne.append(contesto["colonne_sql"][i])
    return f"SELECT {distinct}{', '.join(colonne)} FROM {contesto['base']['from']}{where}{ordine}"


# ---------------------------------------------------------------------------------------------------------
# 4. Tutti i contesti possibili
# ---------------------------------------------------------------------------------------------------------

def contesti_possibili(conn, tabelle_di_partenza, righe_finali):
    """Tutti i contesti utili. Se qualcuno e' completo, quelli parziali non servono: si tengono solo i completi."""
    numero_colonne_finali = len(righe_finali[0])
    contesti = []
    for base in basi_possibili(conn, tabelle_di_partenza):
        righe = conn.execute(f"SELECT {', '.join(base['colonne'])} FROM {base['from']} "
                             f"LIMIT {MAX_RIGHE_BASE + 1}").fetchall()
        if not righe or len(righe) > MAX_RIGHE_BASE:
            continue
        # I valori diversi di ogni colonna della base. zip(*righe) "gira" la tabella: invece delle righe
        # da' le colonne, ed e' molto piu' veloce di un ciclo su centinaia di migliaia di righe.
        valori_colonna = []
        for colonna in zip(*righe):
            valori_colonna.append(set(colonna))

        # Per ogni colonna finale, le colonne di partenza che contengono tutti i suoi valori
        # (prima le piu' "specifiche", cioe' con meno valori diversi).
        candidati = []
        for j in range(numero_colonne_finali):
            richiesti = set()
            for riga in righe_finali:
                if riga[j] is not None:
                    richiesti.add(riga[j])
            adatte = []
            if richiesti:
                for i, valori in enumerate(valori_colonna):
                    if richiesti <= valori:  # tutti i valori richiesti sono nella colonna
                        adatte.append((len(valori), i))  # (quanti valori diversi ha, posizione della colonna)
            adatte.sort()
            scelte = []
            for quanti_valori, i in adatte[:MAX_CANDIDATI_PER_COLONNA]:
                scelte.append(i)
            candidati.append(scelte)

        posizioni = []
        for j, adatte in enumerate(candidati):
            if adatte:
                posizioni.append(j)
        if not posizioni:
            continue
        scelte_per_colonna = []
        for j in posizioni:
            scelte_per_colonna.append(candidati[j])
        for proiezione in tutte_le_combinazioni(scelte_per_colonna)[:MAX_PROIEZIONI]:
            contesto = crea_contesto(base, righe, valori_colonna, posizioni, proiezione, righe_finali)
            if contesto["utile"]:
                contesti.append(contesto)

    completi = []
    for contesto in contesti:
        if contesto["completo"]:
            completi.append(contesto)
    if completi:
        return completi
    return contesti


def verifica_parziale(conn, contesto, sql):
    """Per un contesto parziale: il filtro da' esattamente le righe giuste sulle colonne che conosciamo?"""
    try:
        return set(conn.execute(sql).fetchall()) == set(contesto["attese"])
    except Exception:
        return False


# ---------------------------------------------------------------------------------------------------------
# 5. La ricerca
# ---------------------------------------------------------------------------------------------------------

def cerca_filtri(conn, tabelle_di_partenza, tabella_finale, secondi_max, quanti, per_livello):
    """Prova le regole dalla piu' semplice e restituisce (trovate, numero di regole verificate).

    Ogni trovata e' un dizionario con la query, il livello della regola e se e' "completa" (riproduce
    la tabella finale, verificata) o solo un filtro (le colonne calcolate mancano). Si ferma dopo
    `quanti` regole, e da ogni livello ne prende al massimo `per_livello`: cosi' al modello arrivano
    regole di tipo diverso, non dieci varianti della stessa.
    """
    inizio = time.time()
    scadenza = inizio + secondi_max
    colonne_finali, righe_finali = leggi_righe(conn, nome_sql(tabella_finale))
    if not righe_finali:
        return [], 0
    contesti = contesti_possibili(conn, tabelle_di_partenza, righe_finali)
    trovate = []
    condizioni_viste = set()  # la stessa condizione su un'altra unione di tabelle non e' una regola diversa
    provate = 0

    for livello in range(len(NOMI_DEI_LIVELLI)):
        # Prima le candidate di tutti i contesti, poi la verifica dalla piu' credibile (peso piu' basso).
        da_provare = []
        for numero_contesto, contesto in enumerate(contesti):
            candidate, tempo_finito = candidate_del_livello(contesto, livello, scadenza)
            for peso, condizione, ordine in candidate:
                # Il numero in terza posizione e' l'ordine di arrivo: a parita' di peso e di contesto si prova
                # prima la candidata trovata prima (e cosi' il confronto non arriva mai al contesto).
                da_provare.append((peso, numero_contesto, len(da_provare), condizione, ordine, contesto))
            if tempo_finito:
                return trovate, provate
        da_provare.sort()

        trovate_nel_livello = 0
        for peso, numero_contesto, arrivo, condizione, ordine, contesto in da_provare:
            if time.time() > scadenza:
                return trovate, provate
            if trovate_nel_livello >= per_livello:
                break
            if (condizione, ordine) in condizioni_viste:
                continue
            sql = scrivi_sql(contesto, condizione, ordine)
            provate += 1
            if contesto["completo"]:
                esito = verifica(conn, tabella_finale, sql)
                valida = esito["corretto"] and not esito["copiatura_sospetta"]
            else:
                esito = None
                valida = verifica_parziale(conn, contesto, sql)
            if valida:
                condizioni_viste.add((condizione, ordine))
                trovate_nel_livello += 1
                trovate.append({"sql": sql, "livello": NOMI_DEI_LIVELLI[livello], "completa": contesto["completo"],
                                "esito": esito})
                if len(trovate) >= quanti:
                    return trovate, provate
    return trovate, provate

