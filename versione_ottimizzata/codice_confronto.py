"""Confronto tra la versione originale e la versione ottimizzata: tabelle e grafici del README.

1. Raccoglie tutte le prove delle due versioni (versione_originale/risultati_benchmark/ e
   versione_ottimizzata/risultati_benchmark/) e le scrive in grafici/prove.csv, una riga per prova.
2. Calcola le tabelle (grafici/confronto.md) e disegna i grafici (grafici/*.png).
I risultati grezzi non sono su GitHub (sono tanti file): se mancano, lo script parte da grafici/prove.csv.

Le misure sono le stesse per le due versioni:
- corretta: la query riproduce la tabella finale;
- onesta: corretta, senza scrivere a mano i valori della tabella finale e regge sui dati modificati
  (3 copie dei dati con il 30% delle righe tolte a caso);
- stessa regola della query vera: onesta, e passa anche il controllo severo di codice_regole_vere.py.

Come si usa (dalla cartella principale della repository, dopo codice_regole_vere.py):
  python versione_ottimizzata/codice_confronto.py
"""
import csv
import glob
import json
import os
import sqlite3
import statistics
import sys

# Dalla versione originale servono due cose: quante prove per modello conta la sua classifica (n_run) e lo
# stile dei grafici (colori, caratteri, barre arrotondate), cosi' i grafici nuovi sono uguali ai vecchi.
CARTELLA_ORIGINALE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "versione_originale")
sys.path.insert(0, CARTELLA_ORIGINALE)
from codice_benchmark import n_run  # noqa: E402
import codice_classifica as stile  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

CARTELLA_GRAFICI = "grafici"
FILE_PROVE = os.path.join(CARTELLA_GRAFICI, "prove.csv")
FILE_REGOLE_VERE = os.path.join(CARTELLA_GRAFICI, "regole_vere.json")
RISULTATI_ORIGINALE = os.path.join("versione_originale", "risultati_benchmark")
RISULTATI_OTTIMIZZATA = os.path.join("versione_ottimizzata", "risultati_benchmark")
CASO_PC = "pc_multivaluta"

# I nomi dei modelli come li scrivo nel README, nell'ordine delle tabelle.
NOMI_MODELLI = {
    "gpt-oss-120b": "gpt-oss-120b",
    "nemotron": "Nemotron 3 Ultra",
    "gemma": "Gemma 4 31B",
    "qwen2.5-coder-7b": "Qwen2.5-Coder 7B",
    "llama3.1": "Llama 3.1 8B",
    "qwen3-4b": "Qwen3 4B",
    "qwen3.5-4b": "Qwen3.5 4B",
    "qwen3.5-9b": "Qwen3.5 9B",
}
# Dove girano: i primi tre su internet (gratis), gli altri sul mio computer.
DOVE = {"gpt-oss-120b": "Groq", "nemotron": "OpenRouter", "gemma": "Google"}
COLONNE = ["versione", "gruppo", "caso", "difficolta", "modello", "prova", "secondi", "corretta", "onesta",
           "regola_vera", "scritta_da", "sql"]
DIFFICOLTA = ["simple", "moderate", "challenging"]


# ---------------------------------------------------------------------------------------------------------
# 1. Raccolta delle prove
# ---------------------------------------------------------------------------------------------------------

def difficolta_del_caso(caso):
    """La difficolta' data da BIRD (simple, moderate, challenging), letta dal file del caso."""
    if caso == CASO_PC:
        return "caso dei PC"
    for cartella in ("casi_BIRD", "casi_BIRD_nuovi"):
        percorso = os.path.join(cartella, f"{caso}.sqlite")
        if os.path.exists(percorso):
            conn = sqlite3.connect(percorso)
            difficolta = conn.execute("SELECT difficulty FROM _bird_info").fetchone()[0]
            conn.close()
            return difficolta
    return ""


def casi_originali():
    """I nomi dei 30 casi BIRD originali (dall'elenco in casi_BIRD/_manifest.json)."""
    with open(os.path.join("casi_BIRD", "_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    nomi = set()
    for caso in manifest["riusciti"]:
        nomi.add(f"{caso['question_id']}_{caso['db_id']}")
    return nomi


def gruppo_del_caso(caso, originali):
    """"originali" per i 30 casi BIRD originali e il caso dei PC, "nuovi" per i 90 casi nuovi."""
    if caso in originali or caso == CASO_PC:
        return "originali"
    return "nuovi"


def prove_della_versione_originale(originali):
    """Le prove del benchmark originale: le stesse che conta la sua classifica."""
    prove = []
    for percorso in sorted(glob.glob(os.path.join(RISULTATI_ORIGINALE, "*.json"))):
        with open(percorso, encoding="utf-8") as f:
            r = json.load(f)
        if r["run"] > n_run(r["modello"]):
            continue
        valutazione = r.get("valutazione")
        if not valutazione:
            valutazione = {}
        corretta = bool(valutazione.get("esatto")) and not r.get("errore_chiamata")
        robusta = r.get("valutazione_robusta")
        if not robusta:
            robusta = {}
        # esatto_robusto e' False anche quando la query copia a mano i valori della tabella finale.
        onesta = corretta and robusta.get("esatto_robusto") is True
        sql = r.get("query_generata")
        if not sql:
            sql = ""
        prove.append({"versione": "originale", "gruppo": gruppo_del_caso(r["caso"], originali), "caso": r["caso"],
                      "modello": r["modello"], "prova": r["run"], "secondi": r["tempo_secondi"],
                      "corretta": corretta, "onesta": onesta, "scritta_da": r["modello"], "sql": sql})
    return prove


def prove_della_versione_ottimizzata(originali):
    prove = []
    for percorso in sorted(glob.glob(os.path.join(RISULTATI_OTTIMIZZATA, "*.json"))):
        with open(percorso, encoding="utf-8") as f:
            r = json.load(f)
        # regge_dati_modificati e' None quando nessuna copia dei dati cambia il risultato vero: non si puo'
        # controllare, e (come nella versione originale) la query conta come onesta.
        onesta = r["corretto"] and not r["copiatura_nel_testo"] and r["regge_dati_modificati"] is not False
        sql = r["sql"]
        if not sql:
            sql = ""
        prove.append({"versione": "ottimizzata", "gruppo": gruppo_del_caso(r["caso"], originali), "caso": r["caso"],
                      "modello": r["modello"], "prova": r["prova"], "secondi": r["secondi"],
                      "corretta": r["corretto"], "onesta": onesta, "scritta_da": r["risolto_da"], "sql": sql})
    return prove


def raccogli_prove():
    """Tutte le prove delle due versioni, dai risultati grezzi (senza la colonna regola_vera)."""
    originali = casi_originali()
    prove = prove_della_versione_originale(originali) + prove_della_versione_ottimizzata(originali)
    difficolta = {}
    for prova in prove:
        if prova["caso"] not in difficolta:
            difficolta[prova["caso"]] = difficolta_del_caso(prova["caso"])
        prova["difficolta"] = difficolta[prova["caso"]]
    return prove


def aggiungi_regole_vere(prove):
    """La colonna regola_vera, dal controllo severo (grafici/regole_vere.json)."""
    regole_vere = {}
    if os.path.exists(FILE_REGOLE_VERE):
        with open(FILE_REGOLE_VERE, encoding="utf-8") as f:
            regole_vere = json.load(f)
    for prova in prove:
        esito = None
        if prova["caso"] in regole_vere:
            esito = regole_vere[prova["caso"]].get(prova["sql"])
        prova["regola_vera"] = bool(prova["onesta"] and esito is True)


def scrivi_prove(prove):
    os.makedirs(CARTELLA_GRAFICI, exist_ok=True)
    with open(FILE_PROVE, "w", newline="", encoding="utf-8") as f:
        scrittore = csv.DictWriter(f, fieldnames=COLONNE)
        scrittore.writeheader()
        for prova in prove:
            scrittore.writerow(prova)


def leggi_prove():
    prove = []
    with open(FILE_PROVE, newline="", encoding="utf-8") as f:
        for riga in csv.DictReader(f):
            riga["prova"] = int(riga["prova"])
            riga["secondi"] = float(riga["secondi"])
            for colonna in ("corretta", "onesta", "regola_vera"):
                riga[colonna] = riga[colonna] == "True"
            prove.append(riga)
    return prove


# ---------------------------------------------------------------------------------------------------------
# 2. Tabelle
# ---------------------------------------------------------------------------------------------------------

def prove_del_modello(prove, versione, gruppo, modello, difficolta):
    """Le prove di un modello in una versione e in un gruppo di casi, senza il caso dei PC (si guarda a
    parte, come nella classifica originale). Con difficolta = None, i casi di tutte le difficolta'."""
    scelte = []
    for prova in prove:
        if prova["versione"] != versione or prova["gruppo"] != gruppo or prova["modello"] != modello:
            continue
        if prova["caso"] == CASO_PC:
            continue
        if difficolta is not None and prova["difficolta"] != difficolta:
            continue
        scelte.append(prova)
    return scelte


def percentuale(prove, colonna):
    if not prove:
        return 0.0
    quante = 0
    for prova in prove:
        if prova[colonna]:
            quante += 1
    return 100 * quante / len(prove)


def riassunto_per_modello(prove, versione, gruppo, difficolta):
    """Per ogni modello: numero di prove, % corrette, % oneste, % con la regola vera, tempo mediano."""
    righe = []
    for modello, nome in NOMI_MODELLI.items():
        sue = prove_del_modello(prove, versione, gruppo, modello, difficolta)
        if not sue:
            continue
        casi = set()
        prove_per_caso = {}
        tempi = []
        dal_modello = 0
        for prova in sue:
            casi.add(prova["caso"])
            prove_per_caso[prova["caso"]] = prove_per_caso.get(prova["caso"], 0) + 1
            tempi.append(prova["secondi"])
            if prova["onesta"] and prova["scritta_da"] == modello:
                dal_modello += 1
        righe.append({"modello": modello, "nome": nome, "prove": len(sue), "casi": len(casi),
                      "prove_per_caso": max(prove_per_caso.values()),
                      "corrette": percentuale(sue, "corretta"), "oneste": percentuale(sue, "onesta"),
                      "regola_vera": percentuale(sue, "regola_vera"),
                      "dal_modello": 100 * dal_modello / len(sue),
                      "tempo_mediano": statistics.median(tempi)})
    return righe


def casi_risolti_insieme(prove, versione, gruppo, colonna):
    """I casi risolti da almeno un modello in almeno una prova (come quando i modelli lavorano insieme)."""
    risolti = set()
    for prova in prove:
        if prova["versione"] != versione or prova["gruppo"] != gruppo:
            continue
        if prova[colonna] and prova["caso"] != CASO_PC:
            risolti.add(prova["caso"])
    return risolti


def numero(valore, decimali=1):
    """Un numero all'italiana: 14,6."""
    return f"{valore:.{decimali}f}".replace(".", ",")


def tabelle_markdown(prove):
    righe = ["# Confronto tra la versione originale e la versione ottimizzata", "",
             "Tabelle generate da `versione_ottimizzata/codice_confronto.py` a partire da `grafici/prove.csv`.", ""]

    righe += ["## I 30 casi originali", "",
              "| Versione | Modello | Prove | Corrette | Oneste | Stessa regola della query vera | Scritte dal modello | Tempo mediano |",
              "|---|---|---|---|---|---|---|---|"]
    for versione in ("originale", "ottimizzata"):
        for r in riassunto_per_modello(prove, versione, "originali", None):
            righe.append(f"| {versione} | {r['nome']} | {r['prove']} ({r['prove_per_caso']} per caso) | "
                         f"{numero(r['corrette'])}% | {numero(r['oneste'])}% | {numero(r['regola_vera'])}% | "
                         f"{numero(r['dal_modello'])}% | {numero(r['tempo_mediano'], 0)} s |")
    righe.append("")
    for versione in ("originale", "ottimizzata"):
        oneste = casi_risolti_insieme(prove, versione, "originali", "onesta")
        vere = casi_risolti_insieme(prove, versione, "originali", "regola_vera")
        righe.append(f"- {versione}, tutti i modelli insieme: {len(oneste)} casi su 30 risolti in modo onesto, "
                     f"{len(vere)} con la stessa regola della query vera.")
    righe.append("")

    righe += ["## Il caso dei PC", "", "| Versione | Modello | Prove | Oneste |", "|---|---|---|---|"]
    for versione in ("originale", "ottimizzata"):
        for modello, nome in NOMI_MODELLI.items():
            sue = []
            oneste = 0
            for prova in prove:
                if prova["versione"] == versione and prova["caso"] == CASO_PC and prova["modello"] == modello:
                    sue.append(prova)
                    if prova["onesta"]:
                        oneste += 1
            if sue:
                righe.append(f"| {versione} | {nome} | {len(sue)} | {oneste} |")
    righe.append("")

    righe += ["## I 90 casi nuovi (solo versione ottimizzata)", "",
              "| Modello | Difficolta' | Prove | Oneste | Stessa regola della query vera | Tempo mediano |",
              "|---|---|---|---|---|---|"]
    for difficolta in DIFFICOLTA + [None]:
        if difficolta is None:
            etichetta = "tutte"
        else:
            etichetta = difficolta
        for r in riassunto_per_modello(prove, "ottimizzata", "nuovi", difficolta):
            righe.append(f"| {r['nome']} | {etichetta} | {r['prove']} | {numero(r['oneste'])}% | "
                         f"{numero(r['regola_vera'])}% | {numero(r['tempo_mediano'], 0)} s |")
    righe.append("")
    return "\n".join(righe)


# ---------------------------------------------------------------------------------------------------------
# 3. Grafici
# ---------------------------------------------------------------------------------------------------------
# Due colori fissi, uno per versione, in tutti i grafici (dalla palette validata della versione originale).
COLORE_ORIGINALE = stile.COLORI_CATEGORICI[1]    # arancione
COLORE_OTTIMIZZATA = stile.COLORI_CATEGORICI[0]  # blu
# Gli stati di un caso: non risolto (grigio chiaro), risolto in modo onesto, con la stessa regola della query vera.
COLORE_ONESTO = stile.RAMPA_ESATTI[0]
COLORE_REGOLA_VERA = stile.RAMPA_ESATTI[2]


def nome_nel_grafico(modello):
    """Es. "Qwen3 4B (locale)" o "Gemma 4 31B (Google)"."""
    if modello in DOVE:
        return f"{NOMI_MODELLI[modello]} ({DOVE[modello]})"
    return f"{NOMI_MODELLI[modello]} (locale)"


def per_modello(righe):
    """Da una lista di riassunti (riassunto_per_modello) a un dizionario modello -> riassunto."""
    dizionario = {}
    for r in righe:
        dizionario[r["modello"]] = r
    return dizionario


def legenda_versioni(fig, y):
    """La legenda con i due colori delle versioni, in alto a sinistra sotto il titolo."""
    voci = [Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORE_ORIGINALE, markeredgecolor="none",
                   markersize=8, label="versione originale"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORE_OTTIMIZZATA, markeredgecolor="none",
                   markersize=8, label="versione ottimizzata")]
    fig.legend(handles=voci, loc="upper left", bbox_to_anchor=(0.015, y), ncol=2, frameon=False, fontsize=9,
               handletextpad=0.3, columnspacing=1.5)


def manubrio(ax, y, prima, dopo, testo_prima, testo_dopo):
    """Due punti uniti da una linea: il valore della versione originale e quello della versione ottimizzata.

    Se uno dei due manca (None) si disegna solo l'altro. Il valore e' scritto sopra ogni punto.
    """
    if prima is not None and dopo is not None:
        ax.plot([prima, dopo], [y, y], color=stile.ASSE, linewidth=2, solid_capstyle="round", zorder=1)
    if prima is not None:
        ax.plot([prima], [y], marker="o", markersize=8, color=COLORE_ORIGINALE, markeredgecolor=stile.SUPERFICIE,
                markeredgewidth=2, zorder=2)
        ax.text(prima, y - 0.3, testo_prima, ha="center", va="bottom", fontsize=8, color=stile.INCHIOSTRO_SECONDARIO)
    if dopo is not None:
        ax.plot([dopo], [y], marker="o", markersize=8, color=COLORE_OTTIMIZZATA, markeredgecolor=stile.SUPERFICIE,
                markeredgewidth=2, zorder=2)
        ax.text(dopo, y - 0.3, testo_dopo, ha="center", va="bottom", fontsize=8, color=stile.INCHIOSTRO_SECONDARIO)


def figura_onesti(prove):
    """Per ogni modello: % di prove oneste e % con la stessa regola della query vera, nelle due versioni."""
    originale = per_modello(riassunto_per_modello(prove, "originale", "originali", None))
    ottimizzata = per_modello(riassunto_per_modello(prove, "ottimizzata", "originali", None))
    modelli = []
    for modello in NOMI_MODELLI:
        if modello in originale or modello in ottimizzata:
            modelli.append(modello)
    y_insieme = len(modelli) + 0.5  # la riga "tutti i modelli insieme", un po' staccata dalle altre
    altezza = 1.6 + 0.5 * (len(modelli) + 1.5)
    fig, assi = plt.subplots(1, 2, figsize=(9.5, altezza), sharey=True)
    fig.subplots_adjust(left=0.215, right=0.985, top=stile.margine_alto(fig, 1.4), bottom=0.3 / altezza, wspace=0.08)
    pannelli = [("onesta", "oneste", "Prove oneste"),
                ("regola_vera", "regola_vera", "Prove con la stessa regola della query vera")]
    for numero_pannello in range(2):
        ax = assi[numero_pannello]
        colonna, chiave, titolo_pannello = pannelli[numero_pannello]
        stile.stile_assi(ax)
        ax.set_xlim(-7, 107)
        ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
        ax.set_ylim(y_insieme + 0.6, -0.9)
        ax.set_title(titolo_pannello, loc="left", fontsize=10, color=stile.INCHIOSTRO, pad=6)
        for i, modello in enumerate(modelli):
            prima = None
            dopo = None
            testo_prima = ""
            testo_dopo = ""
            if modello in originale:
                prima = originale[modello][chiave]
                testo_prima = f"{prima:.0f}%"
            if modello in ottimizzata:
                dopo = ottimizzata[modello][chiave]
                testo_dopo = f"{dopo:.0f}%"
            manubrio(ax, i, prima, dopo, testo_prima, testo_dopo)
        # Tutti i modelli insieme: quanti dei 30 casi sono risolti da almeno un modello in almeno una prova.
        prima = len(casi_risolti_insieme(prove, "originale", "originali", colonna))
        dopo = len(casi_risolti_insieme(prove, "ottimizzata", "originali", colonna))
        manubrio(ax, y_insieme, 100 * prima / 30, 100 * dopo / 30, f"{prima}/30 casi", f"{dopo}/30 casi")
        ax.axhline(y_insieme - 0.75, color=stile.GRIGLIA, linewidth=1)
    etichette = []
    posizioni = []
    for i, modello in enumerate(modelli):
        etichette.append(nome_nel_grafico(modello))
        posizioni.append(i)
    etichette.append("Tutti i modelli insieme\n(casi risolti almeno una volta)")
    posizioni.append(y_insieme)
    assi[0].set_yticks(posizioni, etichette)
    stile.titolo(fig, "Prima e dopo l'ottimizzazione, sui 30 casi originali",
                 "% delle prove di ogni modello · versione originale: 3-8 prove per caso, ottimizzata: 1-4")
    legenda_versioni(fig, stile.margine_alto(fig, 0.72))
    fig.savefig(os.path.join(CARTELLA_GRAFICI, "fig_onesti.png"), dpi=200)
    plt.close(fig)


def figura_tempi(prove):
    """Il tempo mediano per caso di ogni modello, nelle due versioni (scala logaritmica)."""
    originale = per_modello(riassunto_per_modello(prove, "originale", "originali", None))
    ottimizzata = per_modello(riassunto_per_modello(prove, "ottimizzata", "originali", None))
    modelli = []
    for modello in NOMI_MODELLI:
        if modello in originale or modello in ottimizzata:
            modelli.append(modello)
    altezza = 1.45 + 0.5 * len(modelli)
    fig, ax = plt.subplots(figsize=(8, altezza))
    fig.subplots_adjust(left=0.27, right=0.97, top=stile.margine_alto(fig, 1.2), bottom=0.4 / altezza)
    stile.stile_assi(ax)
    ax.set_xscale("log")
    ax.set_xlim(1.5, 600)
    ax.set_ylim(len(modelli) - 0.5, -0.9)
    ax.set_xticks([2, 5, 10, 30, 60, 120, 300], ["2 s", "5 s", "10 s", "30 s", "1 min", "2 min", "5 min"])
    ax.minorticks_off()
    etichette = []
    for i, modello in enumerate(modelli):
        etichette.append(nome_nel_grafico(modello))
        prima = None
        dopo = None
        testo_prima = ""
        testo_dopo = ""
        if modello in originale:
            prima = originale[modello]["tempo_mediano"]
            testo_prima = stile.fmt_durata(prima)
        if modello in ottimizzata:
            dopo = ottimizzata[modello]["tempo_mediano"]
            testo_dopo = stile.fmt_durata(dopo)
        manubrio(ax, i, prima, dopo, testo_prima, testo_dopo)
    ax.set_yticks(range(len(modelli)), etichette)
    stile.titolo(fig, "Tempo mediano per caso",
                 "30 casi originali · versione ottimizzata: ricerca dei filtri + modello + verifica · scala logaritmica")
    legenda_versioni(fig, stile.margine_alto(fig, 0.72))
    fig.savefig(os.path.join(CARTELLA_GRAFICI, "fig_tempi.png"), dpi=200)
    plt.close(fig)


def stato_del_caso(prove, versione, caso):
    """(stato, prove oneste, prove totali) di un caso in una versione, con tutti i modelli insieme.

    Lo stato e' "regola vera" se almeno una prova ha la stessa regola della query vera, "onesto" se almeno
    una prova e' onesta, altrimenti "non risolto".
    """
    totali = 0
    oneste = 0
    vere = 0
    for prova in prove:
        if prova["versione"] == versione and prova["caso"] == caso:
            totali += 1
            if prova["onesta"]:
                oneste += 1
            if prova["regola_vera"]:
                vere += 1
    if vere:
        return "regola vera", oneste, totali
    if oneste:
        return "onesto", oneste, totali
    return "non risolto", oneste, totali


def figura_casi(prove):
    """Una riga per caso: risolto o no da almeno un modello, nella versione originale e in quella ottimizzata."""
    originali = set()
    for prova in prove:
        if prova["gruppo"] == "originali" and prova["caso"] != CASO_PC:
            originali.add(prova["caso"])
    casi = [CASO_PC] + stile.ordine_casi(originali)
    versioni = [("originale", "versione\noriginale"), ("ottimizzata", "versione\nottimizzata")]
    altezza = 1.75 + 0.24 * len(casi)
    fig, ax = plt.subplots(figsize=(5.6, altezza))
    fig.subplots_adjust(left=0.5, right=0.95, top=stile.margine_alto(fig, 1.4), bottom=0.7 / altezza)
    for riga, caso in enumerate(casi):
        if caso == CASO_PC:
            y = riga
        else:
            y = riga + 0.5  # spazio tra il caso dei PC e i casi BIRD
        for colonna in range(len(versioni)):
            versione = versioni[colonna][0]
            stato, oneste, totali = stato_del_caso(prove, versione, caso)
            if stato == "regola vera":
                colore = COLORE_REGOLA_VERA
                inchiostro = stile.SUPERFICIE
            elif stato == "onesto":
                colore = COLORE_ONESTO
                inchiostro = stile.INCHIOSTRO
            else:
                colore = stile.NEUTRO
                inchiostro = stile.TENUE
            ax.add_patch(plt.Rectangle((colonna, y), 1, 1, facecolor=colore, edgecolor=stile.SUPERFICIE, linewidth=2))
            # Nella cella: quante prove (di tutti i modelli) sono oneste, su quante.
            ax.text(colonna + 0.5, y + 0.5, f"{oneste}/{totali}", ha="center", va="center", fontsize=6.5,
                    color=inchiostro)
    ax.set_xlim(0, len(versioni))
    ax.set_ylim(len(casi) + 0.5, 0)
    posizioni_x = []
    nomi_versioni = []
    for colonna in range(len(versioni)):
        posizioni_x.append(colonna + 0.5)
        nomi_versioni.append(versioni[colonna][1])
    ax.set_xticks(posizioni_x, nomi_versioni, fontsize=8.5, color=stile.INCHIOSTRO_SECONDARIO)
    ax.xaxis.tick_top()
    posizioni_y = []
    etichette = []
    for riga, caso in enumerate(casi):
        if caso == CASO_PC:
            posizioni_y.append(riga + 0.5)
            etichette.append("caso dei PC")
        else:
            posizioni_y.append(riga + 1)
            etichette.append(caso.replace("_", " · ", 1))
    ax.set_yticks(posizioni_y, etichette, fontsize=7.5)
    for lato in ax.spines.values():
        lato.set_visible(False)
    ax.tick_params(length=0)
    legenda = [Patch(facecolor=stile.NEUTRO, label="non risolto"),
               Patch(facecolor=COLORE_ONESTO, label="risolto in modo onesto"),
               Patch(facecolor=COLORE_REGOLA_VERA, label="con la stessa regola della query vera")]
    fig.legend(handles=legenda, loc="lower left", bbox_to_anchor=(0.02, 0.005), ncol=2, frameon=False, fontsize=8,
               handlelength=1, handleheight=1)
    stile.titolo(fig, "I casi risolti dai modelli insieme",
                 "in ogni cella: prove oneste su prove fatte,\ncon tutti i modelli")
    fig.savefig(os.path.join(CARTELLA_GRAFICI, "fig_casi.png"), dpi=200)
    plt.close(fig)


def figura_casi_nuovi(prove):
    """La versione ottimizzata sui 90 casi nuovi: % di prove oneste per modello e difficolta'."""
    modelli = []
    for modello in NOMI_MODELLI:
        if prove_del_modello(prove, "ottimizzata", "nuovi", modello, None):
            modelli.append(modello)
    altezza = 1.45 + 0.95 * len(modelli)
    fig, ax = plt.subplots(figsize=(8, altezza))
    fig.subplots_adjust(left=0.24, right=0.97, top=stile.margine_alto(fig, 1.2), bottom=0.35 / altezza)
    stile.stile_assi(ax)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylim(len(modelli) - 0.5, -0.5)
    px = stile.scala_px(ax)
    h = min(0.26, 16 / px[1])
    spazio = 2 / px[1]
    etichette = []
    for i, modello in enumerate(modelli):
        etichette.append(nome_nel_grafico(modello))
        for k in range(len(DIFFICOLTA)):
            difficolta = DIFFICOLTA[k]
            y = i + (k - 1) * (h + spazio)
            sue = prove_del_modello(prove, "ottimizzata", "nuovi", modello, difficolta)
            if not sue:
                ax.text(1, y, "non provato", va="center", fontsize=8, color=stile.TENUE)
                continue
            oneste = 0
            for prova in sue:
                if prova["onesta"]:
                    oneste += 1
            valore = 100 * oneste / len(sue)
            stile.barra(ax, 0, valore, y, h, stile.RAMPA_ESATTI[k], px)
            ax.text(valore + 1.2, y, f"{valore:.0f}% ({oneste}/{len(sue)})", va="center", fontsize=8,
                    color=stile.INCHIOSTRO_SECONDARIO)
    ax.set_yticks(range(len(modelli)), etichette)
    legenda = []
    nomi = {"simple": "facili (simple)", "moderate": "medi (moderate)", "challenging": "difficili (challenging)"}
    for k in range(len(DIFFICOLTA)):
        legenda.append(Patch(color=stile.RAMPA_ESATTI[k], label=nomi[DIFFICOLTA[k]]))
    fig.legend(handles=legenda, loc="upper left", bbox_to_anchor=(0.015, stile.margine_alto(fig, 0.72)), ncol=3,
               frameon=False, fontsize=9, handlelength=1, handleheight=1)
    stile.titolo(fig, "Versione ottimizzata sui 90 casi nuovi",
                 "% di prove oneste per difficolta' BIRD · casi diversi dai 30 su cui ho costruito il metodo")
    fig.savefig(os.path.join(CARTELLA_GRAFICI, "fig_casi_nuovi.png"), dpi=200)
    plt.close(fig)


def disegna_grafici(prove):
    figura_onesti(prove)
    figura_tempi(prove)
    figura_casi(prove)
    figura_casi_nuovi(prove)


def main():
    if os.path.isdir(RISULTATI_ORIGINALE) and os.path.isdir(RISULTATI_OTTIMIZZATA):
        prove = raccogli_prove()
        aggiungi_regole_vere(prove)
        scrivi_prove(prove)
        print(f"{len(prove)} prove raccolte in {FILE_PROVE}")
    else:
        prove = leggi_prove()
        print(f"Risultati grezzi non trovati: uso le {len(prove)} prove di {FILE_PROVE}")
    testo = tabelle_markdown(prove)
    with open(os.path.join(CARTELLA_GRAFICI, "confronto.md"), "w", encoding="utf-8") as f:
        f.write(testo)
    print(testo)
    disegna_grafici(prove)
    print(f"Grafici salvati in {CARTELLA_GRAFICI}/")


if __name__ == "__main__":
    main()
