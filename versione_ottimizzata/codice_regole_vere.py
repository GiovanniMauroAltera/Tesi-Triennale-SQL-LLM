"""Il controllo severo: la query usa proprio la stessa regola della query vera?

Il controllo sui dati modificati (togliere a caso il 30% delle righe) scopre le copiature, ma non le regole
che funzionano solo per coincidenza: per esempio round = 21 al posto del nome della gara, o la data di
nascita di un paziente al posto del suo ID. Qui invece, per ogni colonna delle tabelle di partenza, si
mescolano i suoi valori tra le righe: se il risultato della query vera cambia, la query del modello deve
cambiare esattamente allo stesso modo. Una regola vera passa tutte queste prove, una coincidenza no.

E' un controllo severo: anche una regola equivalente solo grazie a un ID (eye_colour_id = 2 al posto di
colour = 'Amber') non passa, perche' la regola vera parla del colore, non del numero 2.

Controlla le query oneste di tutte e due le versioni e scrive grafici/regole_vere.json, che
codice_confronto.py usa per la colonna "stessa regola della query vera". Riparte da dove era rimasto.

Come si usa (dalla cartella principale della repository):
  python versione_ottimizzata/codice_regole_vere.py
"""
import json
import os
import random
import re
import sqlite3
import time

from codice_benchmark_ottimizzato import CASO_PC, SQL_GOLD_PC, firma
from codice_confronto import FILE_REGOLE_VERE, raccogli_prove
from verifica import apri_database, colonne_di, confronta, copia_per_il_modello, esegui, leggi_info_caso, nome_sql

# Queste query cambiano le tabelle: si fanno girare su una copia, per non rovinare le prove successive.
MODIFICA = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|REPLACE)\b", re.IGNORECASE)


def mescola(conn, tabella, colonne, seme):
    """Mescola tra le righe i valori di `colonne` (insieme: ogni riga riceve i valori di un'altra riga)."""
    elenco = []
    assegnazioni = []
    for colonna in colonne:
        elenco.append(nome_sql(colonna))
        assegnazioni.append(f"{nome_sql(colonna)} = ?")
    righe = conn.execute(f"SELECT rowid, {', '.join(elenco)} FROM {nome_sql(tabella)}").fetchall()
    valori = []
    for riga in righe:
        valori.append(riga[1:])
    random.Random(seme).shuffle(valori)
    nuovi = []
    for valori_della_riga, riga in zip(valori, righe):
        nuovi.append(tuple(valori_della_riga) + (riga[0],))
    conn.executemany(f"UPDATE {nome_sql(tabella)} SET {', '.join(assegnazioni)} WHERE rowid = ?", nuovi)


def percorso_del_caso(caso):
    if caso == os.path.basename(CASO_PC)[:-7]:
        return CASO_PC
    for cartella in ("casi_BIRD", "casi_BIRD_nuovi"):
        percorso = os.path.join(cartella, f"{caso}.sqlite")
        if os.path.exists(percorso):
            return percorso
    raise FileNotFoundError(caso)


def prova_la_query(variante, sql, righe_vere):
    """La query da' lo stesso risultato della query vera su questa variante dei dati?"""
    modifica = MODIFICA.search(sql)
    conn = variante
    if modifica:
        conn = sqlite3.connect(":memory:")
        variante.backup(conn)
    try:
        # Si confrontano le righe diverse, senza contare i doppioni: qui interessa la regola
        # (quali righe sceglie), non se c'e' DISTINCT o no.
        colonne, ottenute, totale = esegui(conn, sql)
        return confronta(list(set(ottenute)), list(set(righe_vere)))["corretto"]
    except ValueError:
        return False
    finally:
        if modifica:
            conn.close()
        else:
            # Le tabelle temporanee create dalla query si tolgono, cosi' la variante resta come prima.
            temporanee = conn.execute("SELECT name FROM sqlite_temp_master WHERE type = 'table'").fetchall()
            for riga in temporanee:
                conn.execute(f"DROP TABLE temp.{nome_sql(riga[0])}")


def controlla_caso(caso, query):
    """Per ogni query: True (stessa regola), False (coincidenza) o None (nessuna variante utile)."""
    base = apri_database(percorso_del_caso(caso))
    partenza, finale = leggi_info_caso(base)
    if caso == os.path.basename(CASO_PC)[:-7]:
        query_vera = SQL_GOLD_PC
    else:
        query_vera = base.execute("SELECT sql_gold FROM _bird_info").fetchone()[0].strip().rstrip(";")
    originale = firma(base.execute(query_vera).fetchall())
    esiti = {}
    for sql in query:
        esiti[sql] = None
    for tabella in partenza:
        colonne = colonne_di(base, tabella)
        for colonna in colonne:
            variante = copia_per_il_modello(base, finale)
            try:
                mescola(variante, tabella, [colonna], f"{caso}-{tabella}-{colonna}")
            except sqlite3.Error:
                # Una chiave primaria non si puo' mescolare (a meta' strada ci sarebbero valori doppi): si
                # mescolano tutte le altre colonne della riga insieme, che e' lo stesso (l'ID 30609 passa
                # a un'altra persona).
                variante.close()
                variante = copia_per_il_modello(base, finale)
                altre = []
                for altra in colonne:
                    if altra != colonna:
                        altre.append(altra)
                try:
                    mescola(variante, tabella, altre, f"{caso}-{tabella}-{colonna}")
                except sqlite3.Error:
                    variante.close()
                    continue
            righe_vere = variante.execute(query_vera).fetchall()
            if not righe_vere or firma(righe_vere) == originale:
                variante.close()
                continue  # la query vera non se ne accorge: questa variante non dice niente
            for sql in query:
                if esiti[sql] is not False:
                    esiti[sql] = prova_la_query(variante, sql, righe_vere)
            variante.close()
    return esiti


def main():
    risultati = {}
    if os.path.exists(FILE_REGOLE_VERE):
        with open(FILE_REGOLE_VERE, encoding="utf-8") as f:
            risultati = json.load(f)
    da_controllare = {}  # caso -> le query oneste non ancora controllate
    for prova in raccogli_prove():
        caso = prova["caso"]
        if not prova["onesta"] or not prova["sql"]:
            continue
        if caso in risultati and prova["sql"] in risultati[caso]:
            continue  # gia' controllata in un avvio precedente
        if caso not in da_controllare:
            da_controllare[caso] = set()
        da_controllare[caso].add(prova["sql"])
    print(f"{len(da_controllare)} casi da controllare", flush=True)
    for caso in sorted(da_controllare):
        inizio = time.time()
        esiti = controlla_caso(caso, sorted(da_controllare[caso]))
        if caso not in risultati:
            risultati[caso] = {}
        risultati[caso].update(esiti)
        vere = 0
        coincidenze = 0
        for esito in esiti.values():
            if esito is True:
                vere += 1
            elif esito is False:
                coincidenze += 1
        print(f"{caso}: {vere} con la regola vera, {coincidenze} coincidenze ({time.time() - inizio:.0f} s)", flush=True)
        with open(FILE_REGOLE_VERE, "w", encoding="utf-8") as f:
            json.dump(risultati, f, indent=1, ensure_ascii=False, sort_keys=True)
    print("CONTROLLO FINITO", flush=True)


if __name__ == "__main__":
    main()
