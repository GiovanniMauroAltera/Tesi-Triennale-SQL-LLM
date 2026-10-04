"""Metodo D: ricostruisce la query senza modelli linguistici, provando le regole possibili una per una.

Serve come confronto con i modelli, ed e' il primo passo del metodo misto (codice_misto.py). Il procedimento:
1. per ogni colonna della tabella finale cerca la colonna di partenza che ne contiene tutti i valori
   (anche unendo le due tabelle con il loro collegamento);
2. divide le righe di partenza in "giuste" (finiscono nella tabella finale) e "sbagliate";
3. prova i filtri dal piu' semplice al piu' complicato e tiene quelli che lasciano passare tutte le righe
   giuste e nessuna sbagliata. Ogni query trovata e' verificata come quelle dei modelli.

Non sa fare calcoli (conteggi, somme, medie) ne' dedurre valori che non sono nei dati: in quei casi trova
al massimo il filtro, senza la query completa. E puo' trovare una regola che funziona per coincidenza
(un intervallo di CAP al posto dello stato): per questo i filtri semplici vengono provati per primi.

Come si usa:
  python codice_ricerca_noLLM.py --caso casi_BIRD/1334_student_club.sqlite
  python codice_ricerca_noLLM.py --database dati.sqlite --partenza A B --finale C
"""
import argparse
import bisect
import heapq
import itertools
import random
import re
import time
from collections import Counter, defaultdict, namedtuple

from verifica import (apri_database, chiavi_di_collegamento, colonne_di, leggi_info_caso, leggi_righe, nome_sql,
                      verifica)

MAX_RIGHE_BASE = 300_000          # tabelle (o coppie di tabelle unite) piu' grandi si saltano: troppo lente
MAX_CANDIDATI_PER_COLONNA = 3     # colonne di partenza provate per ogni colonna finale
MAX_PROIEZIONI = 12               # combinazioni di colonne provate per ogni tabella
MAX_SBAGLIATE_CONTROLLATE = 20_000  # il primo controllo si fa su un campione, la verifica finale su tutto
MAX_VALORI_IN = 3
MAX_COLLEGAMENTI = 4              # per verso: superhero ha eye_colour_id, hair_colour_id, skin_colour_id...
MAX_COPPIE = 5_000
MAX_RIGHE_PRIMI_N_CON_FILTRO = 20_000
DATA = re.compile(r"^\d{4}-\d{2}-\d{2}")
IDENTIFICATIVO = re.compile(r'(^|_)id$|(^|[a-z_])(Id|ID)$')  # id, member_id, circuitId, GasStationID (non "paid")

# I livelli delle regole, dal piu' semplice. Ogni livello si prova su tutte le tabelle prima di passare al
# successivo: cosi' "state = 'Illinois'" (tabella collegata) viene prima di un intervallo di CAP che funziona per caso.
NESSUN_FILTRO, UGUALE, PARTE, DUE_UGUALI, INTERVALLO, ELENCO, DUE_REGOLE, PRIMI_N = range(8)
NOMI_DEI_LIVELLI = ["nessun filtro", "colonna = valore", "parte di un valore (anno, mese, inizio) o valore non vuoto",
                    "due condizioni '='", "intervallo di numeri", "elenco di valori", "due condizioni", "primi N in ordine"]

Regola = namedtuple("Regola", "livello colonna sql funzione")


def letterale(valore):
    if isinstance(valore, str):
        return "'" + valore.replace("'", "''") + "'"
    return repr(valore)


def _numero(valore):
    return isinstance(valore, (int, float)) and not isinstance(valore, bool)


def _numeri_o_date(valori):
    presenti = [v for v in valori if v is not None]
    return bool(presenti) and (all(_numero(v) for v in presenti)
                               or all(isinstance(v, str) and DATA.match(v) for v in presenti))


def _prefisso_comune(testi):
    primo, ultimo = min(testi), max(testi)
    n = 0
    while n < min(len(primo), len(ultimo)) and primo[n] == ultimo[n]:
        n += 1
    return primo[:n]


def _parole(nome):
    """circuitId -> {circuit, id}; link_to_member -> {link, to, member}."""
    return {p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", nome)}


def _nomi_compatibili(colonna_a, colonna_b):
    """Due colonne si collegano se i nomi hanno una parola in comune (zip e zip_code, link_to_member e
    member_id), oppure se una si chiama "id" e l'altra e' un riferimento (eye_colour_id)."""
    a, b = _parole(colonna_a), _parole(colonna_b)
    if colonna_a.lower() == "id" or colonna_b.lower() == "id":
        return "id" in a and "id" in b
    return bool((a & b) - {"id"})


def basi_possibili(conn, tabelle):
    """Dove cercare: ogni tabella da sola, e le coppie unite dai loro collegamenti."""
    basi = [{"from": f"{nome_sql(t)} AS t0", "colonne": [f"t0.{nome_sql(c)}" for c in colonne_di(conn, t)]}
            for t in tabelle]
    if len(tabelle) == 2:
        a, b = tabelle
        collegamenti = (chiavi_di_collegamento(conn, a, b)[:MAX_COLLEGAMENTI]
                        + [(ca, cb) for cb, ca in chiavi_di_collegamento(conn, b, a)[:MAX_COLLEGAMENTI]])
        # Valori simili non bastano: circuitId e raceId sono tutti e due numeri da 1 in su, ma non si collegano.
        collegamenti = [(ca, cb) for ca, cb in collegamenti if _nomi_compatibili(ca, cb)]
        # Anche le colonne con lo stesso nome (ID e ID): a volte solo poche righe hanno il corrispondente
        # nell'altra tabella e chiavi_di_collegamento, che ne chiede l'80%, non le riconosce.
        colonne_a, colonne_b = colonne_di(conn, a), colonne_di(conn, b)
        collegamenti += [(ca, cb) for ca in colonne_a for cb in colonne_b if ca.lower() == cb.lower()]
        # E i nomi del tipo superhero.alignment_id -> alignment.id (tabelle piccole, che l'altra regola scarta).
        collegamenti += [(ca, "id") for ca in colonne_a if "id" in colonne_b and ca.lower() in (f"{b.lower()}_id", f"{b.lower()}id")]
        collegamenti += [("id", cb) for cb in colonne_b if "id" in colonne_a and cb.lower() in (f"{a.lower()}_id", f"{a.lower()}id")]
        for ca, cb in dict.fromkeys(collegamenti):
            basi.append({"from": f"{nome_sql(a)} AS t0 JOIN {nome_sql(b)} AS t1 ON t0.{nome_sql(ca)} = t1.{nome_sql(cb)}",
                         "colonne": [f"t0.{nome_sql(c)}" for c in colonne_di(conn, a)]
                                    + [f"t1.{nome_sql(c)}" for c in colonne_di(conn, b)]})
    return basi


def regole_di_una_colonna(nome, i, giuste, chiavi_giuste, tutte, sbagliate, proiettata):
    """Le condizioni su una colonna che lasciano passare almeno una riga giusta per ogni riga finale.

    "Almeno una" e non "tutte": con DISTINCT una squadra con piu' stagioni finisce nella tabella finale
    anche se solo una stagione rispetta il filtro.
    """
    copertura = defaultdict(set)  # valore -> righe finali che hanno una riga di partenza con quel valore
    for riga, chiave in zip(giuste, chiavi_giuste):
        copertura[riga[i]].add(chiave)

    def copre(valori):
        return len(set().union(*(copertura[v] for v in valori))) == len(tutte)

    regole = []
    if copre([None]):
        regole.append(Regola(UGUALE, i, f"{nome} IS NULL", lambda r: r[i] is None))
    non_nulli = [v for v in copertura if v is not None]
    if not non_nulli or not copre(non_nulli):
        return regole
    regole.append(Regola(PARTE, i, f"{nome} IS NOT NULL", lambda r: r[i] is not None))
    if proiettata:
        return regole  # filtrare sugli stessi valori che si vogliono ottenere vorrebbe dire copiarli
    for v in non_nulli:
        if copre([v]):
            regole.append(Regola(UGUALE, i, f"{nome} = {letterale(v)}", lambda r, v=v: r[i] == v))

    testi = [v for v in non_nulli if isinstance(v, str)]
    date = [t for t in testi if DATA.match(t)]
    for lunghezza, formato in ((4, "%Y"), (7, "%Y-%m")):
        per_parte = defaultdict(list)
        for t in date:
            per_parte[t[:lunghezza]].append(t)
        for p, valori in per_parte.items():
            if len(valori) > 1 and copre(valori):
                regole.append(Regola(PARTE, i, f"STRFTIME('{formato}', {nome}) = '{p}'",
                                     lambda r, p=p, n=lunghezza: isinstance(r[i], str) and r[i][:n] == p))
    if len(testi) == len(non_nulli) > 1 and not date:
        prefisso = _prefisso_comune(testi)
        if len(prefisso) >= 3:
            regole.append(Regola(PARTE, i, f"SUBSTR({nome}, 1, {len(prefisso)}) = {letterale(prefisso)}",
                                 lambda r, p=prefisso: isinstance(r[i], str) and r[i].startswith(p)))

    # Intervalli di numeri: i valori delle righe sbagliate sono "vietati"; un intervallo buono sta in un
    # buco tra due valori vietati e contiene almeno una riga giusta per ogni riga finale.
    numeri = sorted(v for v in non_nulli if _numero(v))
    vietati = sorted({r[i] for r in sbagliate if _numero(r[i])})
    vietati_insieme = set(vietati)
    per_buco = defaultdict(list)
    for v in numeri:
        if v not in vietati_insieme:
            per_buco[bisect.bisect_left(vietati, v)].append(v)
    for buco, valori in per_buco.items():
        if len(valori) < 2 or not copre(valori):
            continue  # con un valore solo basta la regola "="
        a, b = valori[0], valori[-1]
        if buco == len(vietati):
            regole.append(Regola(INTERVALLO, i, f"{nome} >= {letterale(a)}", lambda r, a=a: _numero(r[i]) and r[i] >= a))
        elif buco == 0:
            regole.append(Regola(INTERVALLO, i, f"{nome} <= {letterale(b)}", lambda r, b=b: _numero(r[i]) and r[i] <= b))
        else:
            regole.append(Regola(INTERVALLO, i, f"{nome} BETWEEN {letterale(a)} AND {letterale(b)}",
                                 lambda r, a=a, b=b: _numero(r[i]) and a <= r[i] <= b))

    if 1 < len(non_nulli) <= MAX_VALORI_IN:
        elenco = ", ".join(letterale(v) for v in sorted(non_nulli, key=str))
        regole.append(Regola(ELENCO, i, f"{nome} IN ({elenco})", lambda r, s=frozenset(non_nulli): r[i] in s))
    return regole


class Contesto:
    """Una tabella (o due tabelle unite) e la scelta delle colonne da cui vengono le colonne finali.

    Se qualche colonna finale e' un calcolo (non si trova tra quelle di partenza) il contesto e'
    "parziale": si puo' cercare il filtro sulle altre colonne, ma non la query completa.
    """

    def __init__(self, base, righe, valori_colonna, posizioni, proiezione, righe_finali):
        self.base, self.righe, self.proiezione = base, righe, proiezione
        self.colonne_sql = base["colonne"]
        # Peso di ogni colonna (piu' basso = regola piu' credibile): le colonne "di categoria" (paese, stato,
        # colore) hanno pochi valori diversi; un filtro su un ID o su un codice e' piu' spesso una coincidenza.
        identificativi = [bool(IDENTIFICATIVO.search(nome.split(".", 1)[1].strip('"'))) for nome in self.colonne_sql]
        self.pesi = [len(v) * (10 if identificativo else 1) for identificativo, v in zip(identificativi, valori_colonna)]
        # Per i "primi N" si ordina solo per numeri o date (punti, punteggio, data di nascita): i primi N
        # in ordine di un ID o di un codice ("ORDER BY hero_id LIMIT 4") sono quasi sempre una coincidenza.
        self.ordinabili = {i for i, v in enumerate(valori_colonna) if not identificativi[i] and _numeri_o_date(v)}
        self.completo = len(posizioni) == len(righe_finali[0])
        self.attese = Counter(tuple(riga[j] for j in posizioni) for riga in righe_finali)
        self.doppioni = any(n > 1 for n in self.attese.values())
        giuste = [r for r in righe if self.proietta(r) in self.attese]
        sbagliate = [r for r in righe if self.proietta(r) not in self.attese]
        self.utile = {self.proietta(r) for r in giuste} == set(self.attese)  # ogni riga finale si puo' ottenere
        if len(sbagliate) > MAX_SBAGLIATE_CONTROLLATE:
            sbagliate = random.Random(0).sample(sbagliate, MAX_SBAGLIATE_CONTROLLATE)
        self.sbagliate, self.giuste = sbagliate, giuste
        self.chiavi_giuste = [self.proietta(r) for r in giuste]
        tutte = set(self.attese)
        self.regole = [regola for i, nome in enumerate(self.colonne_sql)
                       for regola in regole_di_una_colonna(nome, i, giuste, self.chiavi_giuste, tutte, sbagliate,
                                                           i in proiezione)]
        self._accettate, self._passano = {}, {}

    def proietta(self, riga):
        return tuple(riga[i] for i in self.proiezione)

    def accettate(self, regola):
        """Le righe sbagliate (del campione) che la regola lascerebbe passare."""
        if regola.sql not in self._accettate:
            self._accettate[regola.sql] = frozenset(k for k, r in enumerate(self.sbagliate) if regola.funzione(r))
        return self._accettate[regola.sql]

    def passano(self, regola):
        """Le righe giuste che la regola lascia passare."""
        if regola.sql not in self._passano:
            self._passano[regola.sql] = frozenset(k for k, r in enumerate(self.giuste) if regola.funzione(r))
        return self._passano[regola.sql]

    def funziona(self, *regole):
        """Nessuna riga sbagliata passa, e passa almeno una riga giusta per ogni riga finale."""
        if frozenset.intersection(*(self.accettate(r) for r in regole)):
            return False
        passano = frozenset.intersection(*(self.passano(r) for r in regole))
        return len({self.chiavi_giuste[k] for k in passano}) == len(self.attese)

    def condizioni(self, livello):
        """Le condizioni di un livello che lasciano passare solo le righe giuste: (peso, WHERE, ORDER BY)."""
        if livello == NESSUN_FILTRO:
            if not self.sbagliate:
                yield 0, "", ""
        elif livello in (UGUALE, PARTE, INTERVALLO, ELENCO):
            for regola in self.regole:
                if regola.livello == livello and self.funziona(regola):
                    yield self.pesi[regola.colonna], regola.sql, ""
        elif livello in (DUE_UGUALI, DUE_REGOLE):
            coppie = ((a, b) for a, b in itertools.combinations(self.regole, 2)
                      if a.colonna != b.colonna and (a.livello == b.livello == UGUALE) == (livello == DUE_UGUALI))
            for a, b in itertools.islice(coppie, MAX_COPPIE):
                if self.accettate(a) and self.accettate(b) and self.funziona(a, b):
                    yield self.pesi[a.colonna] + self.pesi[b.colonna], f"{a.sql} AND {b.sql}", ""
        elif livello == PRIMI_N and self.completo:
            yield from self._primi_n()

    def _primi_n(self):
        """ORDER BY ... LIMIT N: le righe finali sono le prime N in ordine di una colonna (anche dopo un filtro)."""
        n = sum(self.attese.values())
        filtri = [None]
        if len(self.righe) <= MAX_RIGHE_PRIMI_N_CON_FILTRO:
            # Solo i filtri che da soli non bastano: se bastano, ORDER BY ... LIMIT non aggiunge niente.
            filtri += [r for r in self.regole if r.livello in (UGUALE, PARTE) and self.accettate(r)]
        for filtro in filtri:
            righe = self.righe if filtro is None else [r for r in self.righe if filtro.funzione(r)]
            for i, nome in enumerate(self.colonne_sql):
                if (filtro is not None and filtro.colonna == i) or i not in self.ordinabili:
                    continue
                valide = [r for r in righe if r[i] is not None]
                for verso, scegli in (("DESC", heapq.nlargest), ("ASC", heapq.nsmallest)):
                    primi = scegli(n + 1, valide, key=lambda r: r[i])
                    if len(primi) > n and primi[n - 1][i] == primi[n][i]:
                        continue  # pari merito al confine: quali righe restano dipende dal caso, non e' una regola
                    primi = primi[:n]
                    if primi and Counter(map(self.proietta, primi)) == self.attese:
                        condizione = " AND ".join(c for c in (filtro.sql if filtro else "", f"{nome} IS NOT NULL") if c)
                        peso = self.pesi[filtro.colonna] if filtro else 0  # ordinare per una data o un numero e' normale
                        yield peso, condizione, f" ORDER BY {nome} {verso} LIMIT {n}"

    def sql(self, condizione, ordine):
        distinct = "" if ordine or (self.completo and self.doppioni) else "DISTINCT "
        where = f" WHERE {condizione}" if condizione else ""
        select = ", ".join(self.colonne_sql[i] for i in self.proiezione)
        return f"SELECT {distinct}{select} FROM {self.base['from']}{where}{ordine}"


def contesti_possibili(conn, tabelle_di_partenza, righe_finali, solo_completi):
    """Tutti i contesti utili. Se qualcuno e' completo, quelli parziali non servono: si tengono solo i completi."""
    contesti = list(_tutti_i_contesti(conn, tabelle_di_partenza, righe_finali, solo_completi))
    completi = [c for c in contesti if c.completo]
    return completi or contesti


def _tutti_i_contesti(conn, tabelle_di_partenza, righe_finali, solo_completi):
    colonne_finali = list(zip(*righe_finali))
    for base in basi_possibili(conn, tabelle_di_partenza):
        righe = conn.execute(f"SELECT {', '.join(base['colonne'])} FROM {base['from']} LIMIT {MAX_RIGHE_BASE + 1}").fetchall()
        if not righe or len(righe) > MAX_RIGHE_BASE:
            continue
        valori_colonna = [set(colonna) for colonna in zip(*righe)]
        candidati = []
        for valori in colonne_finali:
            richiesti = set(valori) - {None}
            adatte = sorted((i for i, v in enumerate(valori_colonna) if richiesti and richiesti <= v),
                            key=lambda i: len(valori_colonna[i]))  # prima le colonne piu' "specifiche"
            candidati.append(adatte[:MAX_CANDIDATI_PER_COLONNA])
        posizioni = [j for j, c in enumerate(candidati) if c]
        if not posizioni or (solo_completi and len(posizioni) < len(candidati)):
            continue
        for proiezione in itertools.islice(itertools.product(*(candidati[j] for j in posizioni)), MAX_PROIEZIONI):
            contesto = Contesto(base, righe, valori_colonna, posizioni, proiezione, righe_finali)
            if contesto.utile:
                yield contesto


def _verifica_parziale(conn, contesto, sql):
    """Per un contesto parziale: il filtro da' esattamente le righe giuste sulle colonne che conosciamo?"""
    try:
        return set(conn.execute(sql).fetchall()) == set(contesto.attese)
    except Exception:
        return False


def cerca_filtri(conn, tabelle_di_partenza, tabella_finale, secondi_max=60, quanti=1, solo_complete=True,
                 per_livello=None):
    """Prova le regole dalla piu' semplice e restituisce (trovate, numero di regole verificate).

    Ogni trovata e' un dizionario con la query, il livello della regola e se e' "completa" (riproduce
    la tabella finale, verificata) o solo un filtro (le colonne calcolate mancano). Si ferma dopo
    `quanti` regole. Senza `per_livello` si ferma anche alla fine del primo livello in cui ne ha trovata
    almeno una (le regole piu' complicate sono meno probabili); con `per_livello` invece raccoglie al
    massimo quel numero di regole da ogni livello, per proporre al modello regole di tipo diverso.
    """
    inizio = time.time()
    _, righe_finali = leggi_righe(conn, nome_sql(tabella_finale))
    if not righe_finali:
        return [], 0
    contesti = contesti_possibili(conn, tabelle_di_partenza, righe_finali, solo_complete)
    trovate, condizioni_viste, provate = [], set(), 0
    for livello in range(len(NOMI_DEI_LIVELLI)):
        # Prima le condizioni di tutti i contesti, poi la verifica dalla piu' credibile (peso piu' basso).
        da_provare = []
        for n, contesto in enumerate(contesti):
            for peso, condizione, ordine in contesto.condizioni(livello):
                da_provare.append((peso, n, condizione, ordine, contesto))
                if time.time() - inizio > secondi_max:
                    return trovate, provate
        trovate_nel_livello = 0
        for _, _, condizione, ordine, contesto in sorted(da_provare, key=lambda x: x[:2]):
            if time.time() - inizio > secondi_max:
                return trovate, provate
            if per_livello and trovate_nel_livello >= per_livello:
                break
            # La stessa condizione su un'altra unione di tabelle non e' una regola diversa.
            if (condizione, ordine) in condizioni_viste:
                continue
            sql = contesto.sql(condizione, ordine)
            provate += 1
            if contesto.completo:
                esito = verifica(conn, tabella_finale, sql)
                valida = esito["corretto"] and not esito["copiatura_sospetta"]
            else:
                esito, valida = None, _verifica_parziale(conn, contesto, sql)
            if valida:
                condizioni_viste.add((condizione, ordine))
                trovate_nel_livello += 1
                trovate.append({"sql": sql, "livello": NOMI_DEI_LIVELLI[livello], "completa": contesto.completo,
                                "esito": esito})
                if len(trovate) >= quanti:
                    return trovate, provate
        if trovate and not per_livello:
            break
    return trovate, provate


def cerca_query(conn, tabelle_di_partenza, tabella_finale, secondi_max=120):
    """Il metodo D da solo: la prima query completa e verificata, oppure None."""
    trovate, provate = cerca_filtri(conn, tabelle_di_partenza, tabella_finale, secondi_max, quanti=1, solo_complete=True)
    return (trovate[0] if trovate else None), provate


def main():
    parser = argparse.ArgumentParser(description="Cerca la query provando le regole possibili, senza modelli linguistici.")
    parser.add_argument("--caso", help="file .sqlite di un caso (BIRD o caso dei PC)")
    parser.add_argument("--database", help="un database SQLite qualsiasi")
    parser.add_argument("--partenza", nargs="+", help="le tabelle di partenza (con --database)")
    parser.add_argument("--finale", help="la tabella finale (con --database)")
    parser.add_argument("--secondi-max", type=int, default=120)
    argomenti = parser.parse_args()
    if argomenti.caso:
        conn = apri_database(argomenti.caso)
        partenza, finale = leggi_info_caso(conn)
    elif argomenti.database and argomenti.partenza and argomenti.finale:
        conn = apri_database(argomenti.database)
        partenza, finale = argomenti.partenza, argomenti.finale
    else:
        parser.error("indica --caso oppure --database con --partenza e --finale")

    inizio = time.time()
    trovata, provate = cerca_query(conn, partenza, finale, argomenti.secondi_max)
    secondi = time.time() - inizio
    if trovata:
        print(f"QUERY TROVATA in {secondi:.1f} s ({provate} regole verificate, regola: {trovata['livello']}):\n\n{trovata['sql']}")
    else:
        print(f"Nessuna regola trovata in {secondi:.1f} s ({provate} verificate): forse servono calcoli o dati che non ci sono.")


if __name__ == "__main__":
    main()
