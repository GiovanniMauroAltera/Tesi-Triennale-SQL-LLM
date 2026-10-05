"""Fase 5: aggrega i risultati del benchmark in una classifica (tabelle + figure per la tesi).

Legge i JSON in versione_originale/risultati_benchmark/ (non le sottocartelle _scartati_*) e produce in
versione_originale/classifica/:
  - classifica_modelli.csv / classifica.md   classifica sui 30 casi BIRD + caso demo a parte
  - dettaglio_casi.csv                       run esatti e F1 medio per ogni coppia caso x modello
  - fig_classifica.png, fig_esiti.png, fig_casi.png, fig_tempi.png

Funziona anche a run in corso: le percentuali sono calcolate sui run gia' valutati.

Come si usa (dalla cartella principale della repository):
  python versione_originale/codice_classifica.py
"""
import csv
import glob
import json
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Patch
from matplotlib.path import Path

from codice_benchmark import CARTELLA_RISULTATI, CASO_DEMO, MODELLI, N_RUN, N_RUN_PER_MODELLO, elenco_casi, id_caso, n_run

CARTELLA_USCITA = os.path.join("versione_originale", "classifica")
ID_DEMO = id_caso(CASO_DEMO)

NOMI_MODELLI = {
    "llama3.1": "Llama 3.1 8B (locale)",
    "qwen2.5-coder-7b": "Qwen2.5-Coder 7B (locale)",
    "nemotron": "Nemotron 3 Ultra (OpenRouter)",
    "gemma": "Gemma 4 31B (Google)",
    "gpt-oss-120b": "gpt-oss-120b (Groq)",
}

NOMI_BREVI = {
    "llama3.1": "Llama 3.1\n(locale)",
    "qwen2.5-coder-7b": "Qwen2.5-Coder\n(locale)",
    "nemotron": "Nemotron\n(OpenRouter)",
    "gemma": "Gemma 4\n(Google)",
    "gpt-oss-120b": "gpt-oss-120b\n(Groq)",
}

ESITI = ["esatto", "risultato sbagliato", "errore SQL", "risposta troncata", "errore di chiamata"]
# Come compaiono in tabelle e grafici (nel codice le chiavi restano quelle sopra).
ETICHETTE_ESITI = {"esatto": "risultato corretto"}

# Nomi delle tre misure scelti per la tesi.
MISURA_CORRETTI = "Risultati corretti"
MISURA_SENZA_COPIATURE = "Risultati corretti senza copiature"
MISURA_PARZIALE = "Correttezza parziale"


def etichetta_esito(e):
    return ETICHETTE_ESITI.get(e, e)

# Palette validata con validate_palette.py (skill dataviz), tema chiaro:
# categorica slot 1-5 in ordine fisso, rampa ordinale blu per 1-3 run esatti.
COLORI_CATEGORICI = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
RAMPA_ESATTI = ["#86b6ef", "#3987e5", "#184f95"]
SUPERFICIE = "#fcfcfb"
INCHIOSTRO = "#0b0b0b"
INCHIOSTRO_SECONDARIO = "#52514e"
TENUE = "#898781"
GRIGLIA = "#e1e0d9"
ASSE = "#c3c2b7"
NEUTRO = "#f0efec"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    "font.size": 10,
    "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE,
    "savefig.facecolor": SUPERFICIE,
    "text.color": INCHIOSTRO,
    "axes.labelcolor": INCHIOSTRO_SECONDARIO,
    "xtick.color": TENUE,
    "ytick.color": INCHIOSTRO_SECONDARIO,
})


# -- lettura e classificazione ----------------------------------------------------

def carica_risultati():
    risultati = []
    for percorso in glob.glob(os.path.join(CARTELLA_RISULTATI, "*.json")):
        with open(percorso, encoding="utf-8") as f:
            risultati.append(json.load(f))
    return risultati


def valutazione_di(r):
    """La valutazione della prova; un dizionario vuoto se non c'e' (per esempio dopo un errore di chiamata)."""
    v = r.get("valutazione")
    if not v:
        return {}
    return v


def prove_di(risultati, modello, caso):
    """Le prove di un modello su un caso."""
    prove = []
    for r in risultati:
        if r["modello"] == modello and r["caso"] == caso:
            prove.append(r)
    return prove


def esito(r):
    if r.get("errore_chiamata"):
        return "errore di chiamata"
    v = valutazione_di(r)
    if v.get("esatto"):
        return "esatto"
    if r.get("risposta_troncata"):
        return "risposta troncata"
    if v.get("errore"):
        return "errore SQL"
    return "risultato sbagliato"


def f1(r):
    return valutazione_di(r).get("f1", 0.0)


def esatto_robusto(r):
    """True/False dal controllo su dati modificati (controllo_copiatura.py); None se non ancora calcolato."""
    if esito(r) != "esatto":
        return False
    robusta = r.get("valutazione_robusta")
    if robusta is None:
        return None
    return robusta["esatto_robusto"]


def non_verificabile(r):
    """Esatto in un caso dove i dati modificati non distinguono una copiatura, e senza copiature nel testo."""
    robusta = r.get("valutazione_robusta")
    if not robusta:
        robusta = {}
    return esito(r) == "esatto" and robusta.get("verificabile") is False and not robusta.get("copiatura_nel_testo")


def percentile(valori, q):
    if not valori:
        return None
    ordinati = sorted(valori)
    k = (len(ordinati) - 1) * q
    i = int(k)
    frazione = k - int(k)
    if i + 1 < len(ordinati):
        return ordinati[i] + (ordinati[i + 1] - ordinati[i]) * frazione
    return ordinati[i]


def statistiche(risultati, casi_bird):
    righe = []
    for modello in MODELLI:
        run = []   # le prove del modello sui casi BIRD
        demo = []  # le prove del modello sul caso dei PC
        for r in risultati:
            if r["modello"] == modello and r["caso"] in casi_bird:
                run.append(r)
            if r["modello"] == modello and r["caso"] == ID_DEMO:
                demo.append(r)
        n = len(run)

        esiti = []
        tempi = []
        valori_f1 = []
        esatti_robusti = 0
        robustezza_mancante = 0
        non_verificabili = 0
        for r in run:
            esiti.append(esito(r))
            tempi.append(r["tempo_secondi"])
            valori_f1.append(f1(r))
            if esatto_robusto(r):
                esatti_robusti += 1
            if esatto_robusto(r) is None:
                robustezza_mancante += 1
            if non_verificabile(r):
                non_verificabili += 1

        # Per ogni caso: quante prove e quante con risultato esatto.
        esatti_per_caso = {}
        run_per_caso = {}
        for c in casi_bird:
            esatti_per_caso[c] = 0
            run_per_caso[c] = 0
        for r in run:
            run_per_caso[r["caso"]] += 1
            if esito(r) == "esatto":
                esatti_per_caso[r["caso"]] += 1
        casi_risolti_almeno_una_volta = 0
        casi_risolti_sempre = 0
        for c in casi_bird:
            if esatti_per_caso[c] > 0:
                casi_risolti_almeno_una_volta += 1
            if run_per_caso[c] == n_run(modello) and esatti_per_caso[c] == run_per_caso[c]:
                casi_risolti_sempre += 1

        conteggio_esiti = {}
        for e in ESITI:
            conteggio_esiti[e] = esiti.count(e)

        demo_esatti = 0
        demo_esatti_robusti = 0
        demo_f1 = []
        for r in demo:
            if esito(r) == "esatto":
                demo_esatti += 1
            if esatto_robusto(r):
                demo_esatti_robusti += 1
            demo_f1.append(f1(r))

        if n:
            pct_esatti = 100 * esiti.count("esatto") / n
            pct_esatti_robusti = 100 * esatti_robusti / n
            f1_medio = 100 * statistics.mean(valori_f1)
        else:
            pct_esatti = 0.0
            pct_esatti_robusti = 0.0
            f1_medio = 0.0
        if demo:
            demo_f1_medio = 100 * statistics.mean(demo_f1)
        else:
            demo_f1_medio = 0.0

        righe.append({
            "modello": modello,
            "nome": NOMI_MODELLI.get(modello, modello),
            "run_valutati": n,
            "run_previsti": len(casi_bird) * n_run(modello),
            "esatti": esiti.count("esatto"),
            "pct_esatti": pct_esatti,
            "esatti_robusti": esatti_robusti,
            "pct_esatti_robusti": pct_esatti_robusti,
            "robustezza_mancante": robustezza_mancante,
            "non_verificabili": non_verificabili,
            "f1_medio": f1_medio,
            "casi_risolti_almeno_una_volta": casi_risolti_almeno_una_volta,
            "casi_risolti_sempre": casi_risolti_sempre,
            "casi_totali": len(casi_bird),
            "esiti": conteggio_esiti,
            "tempo_mediano_s": percentile(tempi, 0.5),
            "tempo_q1_s": percentile(tempi, 0.25),
            "tempo_q3_s": percentile(tempi, 0.75),
            "demo_esatti": demo_esatti,
            "demo_esatti_robusti": demo_esatti_robusti,
            "demo_run": len(demo),
            "demo_f1_medio": demo_f1_medio,
        })
    return ordina_classifica(righe)


def ordina_classifica(righe):
    """Metrica piu' severa per prima: un esatto ottenuto copiando i valori del target non regge sui dati modificati.

    A pari merito conta la percentuale di risultati corretti, poi la correttezza parziale, poi l'ordine di MODELLI.
    I valori hanno il segno meno perche' l'ordinamento va dal piu' piccolo al piu' grande.
    """
    chiavi = []
    for posizione, s in enumerate(righe):
        chiavi.append((-s["pct_esatti_robusti"], -s["pct_esatti"], -s["f1_medio"], posizione))
    chiavi.sort()
    ordinate = []
    for chiave in chiavi:
        ordinate.append(righe[chiave[3]])
    return ordinate


# -- tabelle ----------------------------------------------------------------------

def fmt_tempo(s):
    if s is None:
        return "n.d."
    return f"{s:.0f}"


def pct(x):
    return f"{x:.1f}%".replace(".", ",")


def descrizione_run():
    """Es. "3 prove per caso (8 per Gemma 4 31B e Qwen2.5-Coder 7B)"."""
    per_numero = {}  # numero di prove -> i modelli che ne hanno fatte tante
    for modello, k in N_RUN_PER_MODELLO.items():
        if k not in per_numero:
            per_numero[k] = []
        per_numero[k].append(NOMI_MODELLI.get(modello, modello).split(" (")[0])
    pezzi = []
    for k, nomi in per_numero.items():
        pezzi.append(f"{k} per {' e '.join(nomi)}")
    eccezioni = "; ".join(pezzi)
    if eccezioni:
        return f"{N_RUN} prove per caso ({eccezioni})"
    return f"{N_RUN} prove per caso"


def scrivi_tabelle(stats, risultati, casi_bird):
    with open(os.path.join(CARTELLA_USCITA, "classifica_modelli.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        intestazione = ["posizione", "modello", "prove_valutate", "prove_previste",
                        "corretti_senza_copiature", "pct_corretti_senza_copiature",
                        "risultati_corretti", "pct_risultati_corretti", "correttezza_parziale",
                        "corretti_non_verificabili", "controllo_copiatura_mancante",
                        "casi_risolti_almeno_una_volta", "casi_risolti_in_tutte_le_prove", "casi_totali"]
        for e in ESITI:
            intestazione.append(f"n_{etichetta_esito(e).replace(' ', '_')}")
        intestazione += ["tempo_mediano_s", "tempo_q1_s", "tempo_q3_s",
                         "demo_corretti_senza_copiature", "demo_risultati_corretti", "demo_prove", "demo_correttezza_parziale"]
        w.writerow(intestazione)
        for i, s in enumerate(stats, 1):
            riga = [i, s["nome"], s["run_valutati"], s["run_previsti"], s["esatti_robusti"], f"{s['pct_esatti_robusti']:.1f}",
                    s["esatti"], f"{s['pct_esatti']:.1f}", f"{s['f1_medio']:.1f}", s["non_verificabili"], s["robustezza_mancante"],
                    s["casi_risolti_almeno_una_volta"], s["casi_risolti_sempre"], s["casi_totali"]]
            for e in ESITI:
                riga.append(s["esiti"][e])
            riga += [fmt_tempo(s["tempo_mediano_s"]), fmt_tempo(s["tempo_q1_s"]), fmt_tempo(s["tempo_q3_s"]),
                     s["demo_esatti_robusti"], s["demo_esatti"], s["demo_run"], f"{s['demo_f1_medio']:.1f}"]
            w.writerow(riga)

    with open(os.path.join(CARTELLA_USCITA, "dettaglio_casi.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["caso", "modello", "prove", "risultati_corretti", "corretti_senza_copiature", "correttezza_parziale"])
        for caso in [ID_DEMO] + ordine_casi(casi_bird):
            for modello in MODELLI:
                run = prove_di(risultati, modello, caso)
                if run:
                    esatti = 0
                    robusti = 0
                    valori_f1 = []
                    for r in run:
                        if esito(r) == "esatto":
                            esatti += 1
                        if esatto_robusto(r):
                            robusti += 1
                        valori_f1.append(f1(r))
                    w.writerow([caso, NOMI_MODELLI.get(modello, modello), len(run), esatti, robusti,
                                f"{100 * statistics.mean(valori_f1):.1f}"])

    righe = [
        "# Classifica del benchmark",
        "",
        f"Casi: {len(casi_bird)} esempi BIRD Mini-Dev (simple, max 2 tabelle, niente risultati a singolo valore), "
        f"{descrizione_run()}. Le percentuali sono calcolate sulle prove di ciascun modello; *casi risolti in tutte "
        "le prove* è più severo per chi ha fatto più prove.",
        "",
        f"- *{MISURA_CORRETTI}*: il risultato della query del modello è identico alla tabella finale "
        "(è la Execution Accuracy usata da BIRD).",
        f"- *{MISURA_SENZA_COPIATURE}*: il risultato è corretto e supera due controlli (`controllo_copiatura.py`), "
        "che escludono chi ha ricopiato i valori della tabella finale (il prompt la mostra per intero quando ha poche "
        "righe): resta corretto anche su 3 copie dei dati di partenza con il 30% delle righe tolte, e nel testo della "
        "query non compaiono scritti a mano almeno metà dei valori di testo della tabella finale. Il secondo controllo "
        "scopre le copiature unite ai dati veri con un JOIN o un filtro IN (...), che togliendo righe passano inosservate.",
        f"- *{MISURA_PARZIALE}*: punteggio F1 sulle righe (media di precisione e richiamo), premia i risultati quasi "
        "giusti e penalizza sia le righe mancanti sia quelle in più.",
        "",
        f"| # | Modello | Prove valutate | {MISURA_SENZA_COPIATURE} | {MISURA_CORRETTI} | {MISURA_PARZIALE} | "
        "Casi risolti almeno una volta | Casi risolti in tutte le prove | Errori di chiamata | Errori SQL | "
        "Risposte troncate | Tempo mediano (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(stats, 1):
        righe.append(
            f"| {i} | {s['nome']} | {s['run_valutati']}/{s['run_previsti']} | "
            f"{s['esatti_robusti']} ({pct(s['pct_esatti_robusti'])}) | {s['esatti']} ({pct(s['pct_esatti'])}) | "
            f"{pct(s['f1_medio'])} | {s['casi_risolti_almeno_una_volta']}/{s['casi_totali']} | "
            f"{s['casi_risolti_sempre']}/{s['casi_totali']} | {s['esiti']['errore di chiamata']} | {s['esiti']['errore SQL']} | "
            f"{s['esiti']['risposta troncata']} | {fmt_tempo(s['tempo_mediano_s'])} |"
        )
    righe += [
        "",
        f"## Caso demo ({ID_DEMO}), riportato a parte",
        "",
        "Il caso originale della tesi (conversione valute con tassi nascosti da dedurre) non entra nella classifica BIRD.",
        "",
        f"| Modello | {MISURA_SENZA_COPIATURE} | {MISURA_CORRETTI} | {MISURA_PARZIALE} |",
        "|---|---|---|---|",
    ]
    for s in stats:
        righe.append(f"| {s['nome']} | {s['demo_esatti_robusti']}/{s['demo_run']} | {s['demo_esatti']}/{s['demo_run']} | "
                     f"{pct(s['demo_f1_medio'])} |")
    mancanti = prove_senza_controllo(stats)
    if mancanti:
        righe += ["", f"**Attenzione**: {mancanti} prove con risultato corretto non hanno ancora il controllo sulle "
                      "copiature (eseguire `python versione_originale/controllo_copiatura.py`): nel frattempo non "
                      "contano come corrette senza copiature."]
    with open(os.path.join(CARTELLA_USCITA, "classifica.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(righe) + "\n")


def prove_senza_controllo(stats):
    """Quante prove corrette non hanno ancora il controllo sulle copiature."""
    mancanti = 0
    for s in stats:
        mancanti += s["robustezza_mancante"]
    return mancanti


# -- primitive grafiche -------------------------------------------------------------

def stile_assi(ax):
    for lato in ("top", "right", "left"):
        ax.spines[lato].set_visible(False)
    ax.spines["bottom"].set_color(ASSE)
    ax.spines["bottom"].set_linewidth(1)
    ax.tick_params(axis="both", length=0)
    ax.grid(axis="x", color=GRIGLIA, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)


def scala_px(ax):
    """Pixel per unita' di dati sugli assi x e y (serve per raggi e spessori in pixel)."""
    ax.figure.canvas.draw()
    box = ax.get_window_extent()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    return box.width / (x1 - x0), box.height / abs(y1 - y0)


def barra(ax, x0, x1, y, altezza, colore, px, arrotonda=True, raggio_px=4):
    """Barra orizzontale: estremo dei dati arrotondato di 4px, base squadrata."""
    if x1 - x0 <= 0:
        return
    if arrotonda:
        rx = min(raggio_px / px[0], x1 - x0)
        ry = min(raggio_px / px[1], altezza / 2)
    else:
        rx = 0
        ry = 0
    basso = y - altezza / 2
    alto = y + altezza / 2
    vertici = [(x0, basso), (x1 - rx, basso), (x1, basso), (x1, basso + ry),
               (x1, alto - ry), (x1, alto), (x1 - rx, alto), (x0, alto), (x0, basso)]
    codici = [Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3,
              Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(vertici, codici), facecolor=colore, edgecolor="none"))


def titolo(fig, testo, sottotitolo=None):
    # Posizioni in pollici dal bordo alto: restano uguali qualunque sia l'altezza della figura.
    h = fig.get_figheight()
    fig.text(0.02, 1 - 0.12 / h, testo, fontsize=13, fontweight="semibold", color=INCHIOSTRO, va="top")
    if sottotitolo:
        fig.text(0.02, 1 - 0.40 / h, sottotitolo, fontsize=9.5, color=INCHIOSTRO_SECONDARIO, va="top")


def margine_alto(fig, pollici):
    return 1 - pollici / fig.get_figheight()


def fmt_durata(s):
    if s < 120:
        return f"{s:.0f} s"
    return f"{s / 60:.1f} min".replace(".", ",")


def sottotitolo_copertura(stats):
    valutati = 0
    previsti = 0
    for s in stats:
        valutati += s["run_valutati"]
        previsti += s["run_previsti"]
    parziale = ""
    if valutati < previsti:
        parziale = f" · DATI PARZIALI: {valutati}/{previsti} prove"
    return f"{stats[0]['casi_totali']} casi BIRD, {descrizione_run()}{parziale}"


def nomi_dei_modelli(stats):
    nomi = []
    for s in stats:
        nomi.append(s["nome"])
    return nomi


# -- figure -----------------------------------------------------------------------------

def figura_classifica(stats):
    n = len(stats)
    fig, ax = plt.subplots(figsize=(8, 1.5 + 0.85 * n))
    fig.subplots_adjust(left=0.30, right=0.93, top=margine_alto(fig, 1.05), bottom=0.35 / fig.get_figheight())
    stile_assi(ax)
    ax.set_xlim(0, 100)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), nomi_dei_modelli(stats))
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    px = scala_px(ax)
    h = min(0.26, 18 / px[1])
    gap = 2 / px[1]
    # Palette validata in quest'ordine visivo (adiacenze blu-verde acqua, verde acqua-arancio).
    serie = [(MISURA_CORRETTI, "pct_esatti", COLORI_CATEGORICI[0]),
             (MISURA_SENZA_COPIATURE, "pct_esatti_robusti", COLORI_CATEGORICI[2]),
             (MISURA_PARZIALE, "f1_medio", COLORI_CATEGORICI[1])]
    for i, s in enumerate(stats):
        for k in range(len(serie)):
            etichetta, chiave, colore = serie[k]
            y = i + (k - (len(serie) - 1) / 2) * (h + gap)
            barra(ax, 0, s[chiave], y, h, colore, px)
            ax.text(s[chiave] + 1.2, y, f"{s[chiave]:.0f}%", va="center", fontsize=8.5, color=INCHIOSTRO_SECONDARIO)
    legenda = []
    for etichetta, chiave, colore in serie:
        legenda.append(Patch(color=colore, label=etichetta))
    ax.legend(handles=legenda, loc="lower left", bbox_to_anchor=(0, 1.0),
              ncol=3, frameon=False, fontsize=9, handlelength=1, handleheight=1)
    titolo(fig, "Classifica dei modelli", sottotitolo_copertura(stats))
    fig.savefig(os.path.join(CARTELLA_USCITA, "fig_classifica.png"), dpi=200)
    plt.close(fig)


def figura_esiti(stats):
    n = len(stats)
    fig, ax = plt.subplots(figsize=(8, 1.8 + 0.5 * n))
    fig.subplots_adjust(left=0.30, right=0.97, top=margine_alto(fig, 1.50), bottom=0.35 / fig.get_figheight())
    stile_assi(ax)
    ax.set_xlim(0, 100)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), nomi_dei_modelli(stats))
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    px = scala_px(ax)
    h = min(0.6, 24 / px[1])
    gap = 2 / px[0]
    for i, s in enumerate(stats):
        totale = s["run_valutati"]
        if not totale:
            continue
        # Le quote degli esiti presenti, una dopo l'altra sulla stessa barra.
        quote = []
        for e in ESITI:
            if s["esiti"][e]:
                quote.append((e, 100 * s["esiti"][e] / totale))
        inizio = 0.0
        for j in range(len(quote)):
            e, quota = quote[j]
            ultimo = j == len(quote) - 1
            fine = inizio + quota
            if ultimo:
                fine_disegnata = fine
            else:
                fine_disegnata = fine - gap  # 2px di spazio tra un pezzo e il successivo
            barra(ax, inizio, fine_disegnata, i, h, COLORI_CATEGORICI[ESITI.index(e)], px, arrotonda=ultimo)
            inizio = fine
    legenda = []
    for numero, e in enumerate(ESITI):
        legenda.append(Patch(color=COLORI_CATEGORICI[numero], label=etichetta_esito(e)))
    ax.legend(handles=legenda, loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=9, handlelength=1, handleheight=1)
    titolo(fig, "Esito delle prove per modello", sottotitolo_copertura(stats) + "\nquota sul totale delle prove valutate")
    fig.savefig(os.path.join(CARTELLA_USCITA, "fig_esiti.png"), dpi=200)
    plt.close(fig)


def ordine_casi(casi_bird):
    # Raggruppati per database, poi per id numerico della domanda BIRD (es. "1334_student_club").
    chiavi = []
    for caso in casi_bird:
        qid, db = caso.split("_", 1)
        chiavi.append((db, int(qid), caso))
    chiavi.sort()
    ordinati = []
    for db, qid, caso in chiavi:
        ordinati.append(caso)
    return ordinati


def gradino_esatti(esatti, run):
    """Indice nella rampa per la quota di run esatti: fino a 1/3, fino a 2/3, oltre (con 3 run: 1, 2, 3 esatti)."""
    quota = esatti / run
    if quota <= 1 / 3 + 1e-9:
        return 0
    if quota <= 2 / 3 + 1e-9:
        return 1
    return 2


def figura_casi(stats, risultati, casi_bird):
    casi = [ID_DEMO] + ordine_casi(casi_bird)
    modelli = []
    for s in stats:
        modelli.append(s["modello"])
    fig, ax = plt.subplots(figsize=(7.2, 1.7 + 0.24 * len(casi)))
    fig.subplots_adjust(left=0.36, right=0.97, top=margine_alto(fig, 1.05), bottom=0.45 / fig.get_figheight())
    for riga, caso in enumerate(casi):
        if caso == ID_DEMO:
            y = riga
        else:
            y = riga + 0.5  # spazio tra il demo e i casi BIRD
        for col, modello in enumerate(modelli):
            run = prove_di(risultati, modello, caso)
            if not run:
                ax.add_patch(plt.Rectangle((col, y), 1, 1, facecolor=SUPERFICIE, edgecolor=SUPERFICIE, linewidth=2,
                                           hatch="////", hatchcolor=GRIGLIA))
                continue
            esatti = 0
            for r in run:
                if esito(r) == "esatto":
                    esatti += 1
            if esatti == 0:
                gradino = None
                colore = NEUTRO
            else:
                gradino = gradino_esatti(esatti, len(run))
                colore = RAMPA_ESATTI[gradino]
            ax.add_patch(plt.Rectangle((col, y), 1, 1, facecolor=colore, edgecolor=SUPERFICIE, linewidth=2))
            # Il conteggio in ogni cella: il colore da solo non distingue 2/3 da 5/8.
            if gradino == 2:
                inchiostro = SUPERFICIE
            elif gradino is None:
                inchiostro = TENUE
            else:
                inchiostro = INCHIOSTRO
            ax.text(col + 0.5, y + 0.5, f"{esatti}/{len(run)}", ha="center", va="center", fontsize=6.5, color=inchiostro)
    ax.set_xlim(0, len(modelli))
    ax.set_ylim(len(casi) + 0.5, 0)
    posizioni_x = []
    nomi_brevi = []
    for c in range(len(modelli)):
        posizioni_x.append(c + 0.5)
        nomi_brevi.append(NOMI_BREVI.get(modelli[c], modelli[c]))
    ax.set_xticks(posizioni_x, nomi_brevi, fontsize=8, color=INCHIOSTRO_SECONDARIO)
    ax.xaxis.tick_top()
    posizioni_y = []
    etichette = []
    for r, c in enumerate(casi):
        if c == ID_DEMO:
            posizioni_y.append(r + 0.5)
            etichette.append("demo · " + ID_DEMO)
        else:
            posizioni_y.append(r + 0.5 + 0.5)
            etichette.append(c.replace("_", " · ", 1))
    ax.set_yticks(posizioni_y, etichette, fontsize=7.5)
    for lato in ax.spines.values():
        lato.set_visible(False)
    ax.tick_params(length=0)
    legenda = [Patch(facecolor=NEUTRO, label="nessun risultato corretto"),
               Patch(facecolor=RAMPA_ESATTI[0], label="fino a 1/3 delle prove"),
               Patch(facecolor=RAMPA_ESATTI[1], label="fino a 2/3"),
               Patch(facecolor=RAMPA_ESATTI[2], label="oltre 2/3"),
               Patch(facecolor=SUPERFICIE, edgecolor=SUPERFICIE, hatch="////", hatchcolor=TENUE, label="non ancora eseguito")]
    fig.legend(handles=legenda, loc="lower left", bbox_to_anchor=(0.02, 0.005), ncol=5, frameon=False, fontsize=8,
               handlelength=1, handleheight=1)
    titolo(fig, "Risultati corretti per caso e modello", sottotitolo_copertura(stats))
    fig.savefig(os.path.join(CARTELLA_USCITA, "fig_casi.png"), dpi=200)
    plt.close(fig)


def figura_tempi(stats):
    validi = []
    for s in stats:
        if s["tempo_mediano_s"]:
            validi.append(s)
    n = len(validi)
    fig, ax = plt.subplots(figsize=(8, 1.4 + 0.55 * n))
    fig.subplots_adjust(left=0.30, right=0.93, top=margine_alto(fig, 1.05), bottom=0.40 / fig.get_figheight())
    stile_assi(ax)
    ax.set_xscale("log")
    primi_quartili = []
    terzi_quartili = []
    for s in validi:
        primi_quartili.append(s["tempo_q1_s"])
        terzi_quartili.append(s["tempo_q3_s"])
    minimo = min(primi_quartili)
    massimo = max(terzi_quartili)
    ax.set_xlim(max(0.5, minimo / 2), massimo * 4)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), nomi_dei_modelli(validi))
    etichette_tick = {1: "1 s", 10: "10 s", 60: "1 min", 600: "10 min", 3600: "1 ora"}
    limite_sinistro, limite_destro = ax.get_xlim()
    tick = []
    etichette = []
    for t in etichette_tick:
        if t >= limite_sinistro and t <= limite_destro:
            tick.append(t)
            etichette.append(etichette_tick[t])
    ax.set_xticks(tick, etichette)
    ax.minorticks_off()
    for i, s in enumerate(validi):
        ax.plot([s["tempo_q1_s"], s["tempo_q3_s"]], [i, i], color=COLORI_CATEGORICI[0], linewidth=2,
                solid_capstyle="round")
        ax.plot([s["tempo_mediano_s"]], [i], marker="o", markersize=7, color=COLORI_CATEGORICI[0],
                markeredgecolor=SUPERFICIE, markeredgewidth=2)
        ax.text(s["tempo_q3_s"] * 1.15, i, f"mediana {fmt_durata(s['tempo_mediano_s'])}", va="center", fontsize=8.5,
                color=INCHIOSTRO_SECONDARIO)
    titolo(fig, "Tempo per chiamata",
           sottotitolo_copertura(stats) + "\npunto = mediana, linea = 25°-75° percentile · scala logaritmica")
    fig.savefig(os.path.join(CARTELLA_USCITA, "fig_tempi.png"), dpi=200)
    plt.close(fig)


def main():
    os.makedirs(CARTELLA_USCITA, exist_ok=True)
    casi_bird = []
    for percorso in elenco_casi():
        if id_caso(percorso) != ID_DEMO:
            casi_bird.append(id_caso(percorso))
    # Solo i run previsti per ciascun modello: eventuali run in piu' non sbilanciano i casi.
    risultati = []
    for r in carica_risultati():
        if r["modello"] in MODELLI and r["run"] <= n_run(r["modello"]):
            risultati.append(r)
    stats = statistiche(risultati, casi_bird)
    scrivi_tabelle(stats, risultati, casi_bird)
    figura_classifica(stats)
    figura_esiti(stats)
    figura_casi(stats, risultati, casi_bird)
    figura_tempi(stats)
    for i, s in enumerate(stats, 1):
        print(f"{i}. {s['nome']}: {s['esatti_robusti']} corretti senza copiature, {s['esatti']} corretti "
              f"su {s['run_valutati']} prove, correttezza parziale {s['f1_medio']:.1f}%")
    mancanti = prove_senza_controllo(stats)
    if mancanti:
        print(f"ATTENZIONE: {mancanti} prove corrette senza controllo sulle copiature: "
              f"eseguire python versione_originale/controllo_copiatura.py")
    print(f"Tabelle e figure salvate in {CARTELLA_USCITA}/")


if __name__ == "__main__":
    main()
