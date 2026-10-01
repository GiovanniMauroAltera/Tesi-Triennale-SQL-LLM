"""Fase 5: aggrega i risultati del benchmark in una classifica (tabelle + figure per la tesi).

Legge i JSON in risultati_benchmark/ (non le sottocartelle _scartati_*) e produce in classifica/:
  - classifica_modelli.csv / classifica.md   classifica sui 30 casi BIRD + caso demo a parte
  - dettaglio_casi.csv                       run esatti e F1 medio per ogni coppia caso x modello
  - fig_classifica.png, fig_esiti.png, fig_casi.png, fig_tempi.png

Funziona anche a run in corso: le percentuali sono calcolate sui run gia' valutati.
"""
import csv
import glob
import json
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch, Patch
from matplotlib.path import Path

from codice_benchmark import CARTELLA_RISULTATI, CASO_DEMO, MODELLI, N_RUN, N_RUN_PER_MODELLO, elenco_casi, id_caso, n_run

CARTELLA_USCITA = "classifica"
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


def esito(r):
    if r.get("errore_chiamata"):
        return "errore di chiamata"
    v = r.get("valutazione") or {}
    if v.get("esatto"):
        return "esatto"
    if r.get("risposta_troncata"):
        return "risposta troncata"
    if v.get("errore"):
        return "errore SQL"
    return "risultato sbagliato"


def f1(r):
    return (r.get("valutazione") or {}).get("f1", 0.0)


def esatto_robusto(r):
    """True/False dal controllo su dati modificati (controllo_copiatura.py); None se non ancora calcolato."""
    if esito(r) != "esatto":
        return False
    robusta = r.get("valutazione_robusta")
    return None if robusta is None else robusta["esatto_robusto"]


def non_verificabile(r):
    return esito(r) == "esatto" and (r.get("valutazione_robusta") or {}).get("verificabile") is False


def percentile(valori, q):
    if not valori:
        return None
    ordinati = sorted(valori)
    k = (len(ordinati) - 1) * q
    i, frazione = int(k), k - int(k)
    if i + 1 < len(ordinati):
        return ordinati[i] + (ordinati[i + 1] - ordinati[i]) * frazione
    return ordinati[i]


def statistiche(risultati, casi_bird):
    righe = []
    for modello in MODELLI:
        run = [r for r in risultati if r["modello"] == modello and r["caso"] in casi_bird]
        demo = [r for r in risultati if r["modello"] == modello and r["caso"] == ID_DEMO]
        esiti = [esito(r) for r in run]
        esatti_per_caso = {c: sum(1 for r in run if r["caso"] == c and esito(r) == "esatto") for c in casi_bird}
        run_per_caso = {c: sum(1 for r in run if r["caso"] == c) for c in casi_bird}
        tempi = [r["tempo_secondi"] for r in run]
        n = len(run)
        righe.append({
            "modello": modello,
            "nome": NOMI_MODELLI.get(modello, modello),
            "run_valutati": n,
            "run_previsti": len(casi_bird) * n_run(modello),
            "esatti": esiti.count("esatto"),
            "pct_esatti": 100 * esiti.count("esatto") / n if n else 0.0,
            "esatti_robusti": sum(1 for r in run if esatto_robusto(r)),
            "pct_esatti_robusti": 100 * sum(1 for r in run if esatto_robusto(r)) / n if n else 0.0,
            "robustezza_mancante": sum(1 for r in run if esatto_robusto(r) is None),
            "non_verificabili": sum(1 for r in run if non_verificabile(r)),
            "f1_medio": 100 * statistics.mean(f1(r) for r in run) if n else 0.0,
            "casi_risolti_almeno_una_volta": sum(1 for c in casi_bird if esatti_per_caso[c] > 0),
            "casi_risolti_sempre": sum(1 for c in casi_bird
                                       if run_per_caso[c] == n_run(modello) and esatti_per_caso[c] == run_per_caso[c]),
            "casi_totali": len(casi_bird),
            "esiti": {e: esiti.count(e) for e in ESITI},
            "tempo_mediano_s": percentile(tempi, 0.5),
            "tempo_q1_s": percentile(tempi, 0.25),
            "tempo_q3_s": percentile(tempi, 0.75),
            "demo_esatti": sum(1 for r in demo if esito(r) == "esatto"),
            "demo_esatti_robusti": sum(1 for r in demo if esatto_robusto(r)),
            "demo_run": len(demo),
            "demo_f1_medio": 100 * statistics.mean(f1(r) for r in demo) if demo else 0.0,
        })
    # Metrica piu' severa per prima: un esatto ottenuto copiando i valori del target non regge sui dati modificati.
    righe.sort(key=lambda s: (-s["pct_esatti_robusti"], -s["pct_esatti"], -s["f1_medio"]))
    return righe


# -- tabelle ----------------------------------------------------------------------

def fmt_tempo(s):
    return "n.d." if s is None else f"{s:.0f}"


def pct(x):
    return f"{x:.1f}%".replace(".", ",")


def descrizione_run():
    """Es. "3 prove per caso (8 per Gemma 4 31B e Qwen2.5-Coder 7B)"."""
    per_numero = {}
    for modello, k in N_RUN_PER_MODELLO.items():
        per_numero.setdefault(k, []).append(NOMI_MODELLI.get(modello, modello).split(" (")[0])
    eccezioni = "; ".join(f"{k} per {' e '.join(nomi)}" for k, nomi in per_numero.items())
    return f"{N_RUN} prove per caso" + (f" ({eccezioni})" if eccezioni else "")


def scrivi_tabelle(stats, risultati, casi_bird):
    with open(os.path.join(CARTELLA_USCITA, "classifica_modelli.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["posizione", "modello", "prove_valutate", "prove_previste",
                    "corretti_senza_copiature", "pct_corretti_senza_copiature",
                    "risultati_corretti", "pct_risultati_corretti", "correttezza_parziale",
                    "corretti_non_verificabili", "controllo_copiatura_mancante",
                    "casi_risolti_almeno_una_volta", "casi_risolti_in_tutte_le_prove", "casi_totali",
                    *[f"n_{etichetta_esito(e).replace(' ', '_')}" for e in ESITI],
                    "tempo_mediano_s", "tempo_q1_s", "tempo_q3_s",
                    "demo_corretti_senza_copiature", "demo_risultati_corretti", "demo_prove", "demo_correttezza_parziale"])
        for i, s in enumerate(stats, 1):
            w.writerow([i, s["nome"], s["run_valutati"], s["run_previsti"], s["esatti_robusti"], f"{s['pct_esatti_robusti']:.1f}",
                        s["esatti"], f"{s['pct_esatti']:.1f}", f"{s['f1_medio']:.1f}", s["non_verificabili"], s["robustezza_mancante"],
                        s["casi_risolti_almeno_una_volta"], s["casi_risolti_sempre"], s["casi_totali"],
                        *[s["esiti"][e] for e in ESITI],
                        fmt_tempo(s["tempo_mediano_s"]), fmt_tempo(s["tempo_q1_s"]), fmt_tempo(s["tempo_q3_s"]),
                        s["demo_esatti_robusti"], s["demo_esatti"], s["demo_run"], f"{s['demo_f1_medio']:.1f}"])

    with open(os.path.join(CARTELLA_USCITA, "dettaglio_casi.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["caso", "modello", "prove", "risultati_corretti", "corretti_senza_copiature", "correttezza_parziale"])
        for caso in [ID_DEMO] + ordine_casi(casi_bird):
            for modello in MODELLI:
                run = [r for r in risultati if r["modello"] == modello and r["caso"] == caso]
                if run:
                    w.writerow([caso, NOMI_MODELLI.get(modello, modello), len(run),
                                sum(1 for r in run if esito(r) == "esatto"), sum(1 for r in run if esatto_robusto(r)),
                                f"{100 * statistics.mean(f1(r) for r in run):.1f}"])

    righe = [
        "# Classifica del benchmark",
        "",
        f"Casi: {len(casi_bird)} esempi BIRD Mini-Dev (simple, max 2 tabelle, niente risultati a singolo valore), "
        f"{descrizione_run()}. Le percentuali sono calcolate sulle prove di ciascun modello; *casi risolti in tutte "
        "le prove* è più severo per chi ha fatto più prove.",
        "",
        f"- *{MISURA_CORRETTI}*: il risultato della query del modello è identico alla tabella finale "
        "(è la Execution Accuracy usata da BIRD).",
        f"- *{MISURA_SENZA_COPIATURE}*: il risultato resta corretto anche su 3 copie dei dati di partenza con il 30% "
        "delle righe tolte (`controllo_copiatura.py`). Esclude chi ha ricopiato i valori della tabella finale, che il "
        "prompt mostra per intero quando ha poche righe. In 4 casi (ricerche di un singolo elemento) la copiatura non "
        "si può scoprire: lì un risultato corretto viene tenuto valido.",
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
    mancanti = sum(s["robustezza_mancante"] for s in stats)
    if mancanti:
        righe += ["", f"**Attenzione**: {mancanti} prove con risultato corretto non hanno ancora il controllo sulle "
                      "copiature (eseguire `python controllo_copiatura.py`): nel frattempo non contano come corrette "
                      "senza copiature."]
    with open(os.path.join(CARTELLA_USCITA, "classifica.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(righe) + "\n")


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
    rx = min(raggio_px / px[0], x1 - x0) if arrotonda else 0
    ry = min(raggio_px / px[1], altezza / 2) if arrotonda else 0
    basso, alto = y - altezza / 2, y + altezza / 2
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
    return f"{s:.0f} s" if s < 120 else f"{s / 60:.1f} min".replace(".", ",")


def sottotitolo_copertura(stats):
    valutati = sum(s["run_valutati"] for s in stats)
    previsti = sum(s["run_previsti"] for s in stats)
    parziale = "" if valutati >= previsti else f" · DATI PARZIALI: {valutati}/{previsti} prove"
    return f"{stats[0]['casi_totali']} casi BIRD, {descrizione_run()}{parziale}"


# -- figure -----------------------------------------------------------------------------

def figura_classifica(stats):
    n = len(stats)
    fig, ax = plt.subplots(figsize=(8, 1.5 + 0.85 * n))
    fig.subplots_adjust(left=0.30, right=0.93, top=margine_alto(fig, 1.05), bottom=0.35 / fig.get_figheight())
    stile_assi(ax)
    ax.set_xlim(0, 100)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), [s["nome"] for s in stats])
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    px = scala_px(ax)
    h = min(0.26, 18 / px[1])
    gap = 2 / px[1]
    # Palette validata in quest'ordine visivo (adiacenze blu-verde acqua, verde acqua-arancio).
    serie = [(MISURA_CORRETTI, "pct_esatti", COLORI_CATEGORICI[0]),
             (MISURA_SENZA_COPIATURE, "pct_esatti_robusti", COLORI_CATEGORICI[2]),
             (MISURA_PARZIALE, "f1_medio", COLORI_CATEGORICI[1])]
    for i, s in enumerate(stats):
        for k, (_, chiave, colore) in enumerate(serie):
            y = i + (k - (len(serie) - 1) / 2) * (h + gap)
            barra(ax, 0, s[chiave], y, h, colore, px)
            ax.text(s[chiave] + 1.2, y, f"{s[chiave]:.0f}%", va="center", fontsize=8.5, color=INCHIOSTRO_SECONDARIO)
    ax.legend(handles=[Patch(color=c, label=l) for l, _, c in serie], loc="lower left", bbox_to_anchor=(0, 1.0),
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
    ax.set_yticks(range(n), [s["nome"] for s in stats])
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    px = scala_px(ax)
    h = min(0.6, 24 / px[1])
    gap = 2 / px[0]
    for i, s in enumerate(stats):
        totale = s["run_valutati"]
        if not totale:
            continue
        quote = [(e, 100 * s["esiti"][e] / totale) for e in ESITI if s["esiti"][e]]
        inizio = 0.0
        for j, (e, quota) in enumerate(quote):
            ultimo = j == len(quote) - 1
            fine = inizio + quota
            barra(ax, inizio, fine if ultimo else fine - gap, i, h, COLORI_CATEGORICI[ESITI.index(e)], px, arrotonda=ultimo)
            inizio = fine
    ax.legend(handles=[Patch(color=c, label=etichetta_esito(e)) for e, c in zip(ESITI, COLORI_CATEGORICI)], loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=9, handlelength=1, handleheight=1)
    titolo(fig, "Esito delle prove per modello", sottotitolo_copertura(stats) + "\nquota sul totale delle prove valutate")
    fig.savefig(os.path.join(CARTELLA_USCITA, "fig_esiti.png"), dpi=200)
    plt.close(fig)


def ordine_casi(casi_bird):
    # Raggruppati per database, poi per id numerico della domanda BIRD.
    def chiave(caso):
        qid, db = caso.split("_", 1)
        return db, int(qid)
    return sorted(casi_bird, key=chiave)


def gradino_esatti(esatti, run):
    """Indice nella rampa per la quota di run esatti: fino a 1/3, fino a 2/3, oltre (con 3 run: 1, 2, 3 esatti)."""
    quota = esatti / run
    return 0 if quota <= 1 / 3 + 1e-9 else 1 if quota <= 2 / 3 + 1e-9 else 2


def figura_casi(stats, risultati, casi_bird):
    casi = [ID_DEMO] + ordine_casi(casi_bird)
    modelli = [s["modello"] for s in stats]
    fig, ax = plt.subplots(figsize=(7.2, 1.7 + 0.24 * len(casi)))
    fig.subplots_adjust(left=0.36, right=0.97, top=margine_alto(fig, 1.05), bottom=0.45 / fig.get_figheight())
    for riga, caso in enumerate(casi):
        y = riga + (0 if caso == ID_DEMO else 0.5)  # spazio tra il demo e i casi BIRD
        for col, modello in enumerate(modelli):
            run = [r for r in risultati if r["modello"] == modello and r["caso"] == caso]
            if not run:
                ax.add_patch(plt.Rectangle((col, y), 1, 1, facecolor=SUPERFICIE, edgecolor=SUPERFICIE, linewidth=2,
                                           hatch="////", hatchcolor=GRIGLIA))
                continue
            esatti = sum(1 for r in run if esito(r) == "esatto")
            gradino = None if esatti == 0 else gradino_esatti(esatti, len(run))
            colore = NEUTRO if gradino is None else RAMPA_ESATTI[gradino]
            ax.add_patch(plt.Rectangle((col, y), 1, 1, facecolor=colore, edgecolor=SUPERFICIE, linewidth=2))
            # Il conteggio in ogni cella: il colore da solo non distingue 2/3 da 5/8.
            inchiostro = SUPERFICIE if gradino == 2 else (TENUE if gradino is None else INCHIOSTRO)
            ax.text(col + 0.5, y + 0.5, f"{esatti}/{len(run)}", ha="center", va="center", fontsize=6.5, color=inchiostro)
    ax.set_xlim(0, len(modelli))
    ax.set_ylim(len(casi) + 0.5, 0)
    ax.set_xticks([c + 0.5 for c in range(len(modelli))], [NOMI_BREVI.get(m, m) for m in modelli], fontsize=8,
                  color=INCHIOSTRO_SECONDARIO)
    ax.xaxis.tick_top()
    etichette = [("demo · " + ID_DEMO) if c == ID_DEMO else c.replace("_", " · ", 1) for c in casi]
    ax.set_yticks([r + 0.5 + (0 if c == ID_DEMO else 0.5) for r, c in enumerate(casi)], etichette, fontsize=7.5)
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
    validi = [s for s in stats if s["tempo_mediano_s"]]
    n = len(validi)
    fig, ax = plt.subplots(figsize=(8, 1.4 + 0.55 * n))
    fig.subplots_adjust(left=0.30, right=0.93, top=margine_alto(fig, 1.05), bottom=0.40 / fig.get_figheight())
    stile_assi(ax)
    ax.set_xscale("log")
    minimo = min(s["tempo_q1_s"] for s in validi)
    massimo = max(s["tempo_q3_s"] for s in validi)
    ax.set_xlim(max(0.5, minimo / 2), massimo * 4)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), [s["nome"] for s in validi])
    etichette_tick = {1: "1 s", 10: "10 s", 60: "1 min", 600: "10 min", 3600: "1 ora"}
    tick = [t for t in etichette_tick if ax.get_xlim()[0] <= t <= ax.get_xlim()[1]]
    ax.set_xticks(tick, [etichette_tick[t] for t in tick])
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
    casi_bird = [id_caso(p) for p in elenco_casi() if id_caso(p) != ID_DEMO]
    # Solo i run previsti per ciascun modello: eventuali run in piu' non sbilanciano i casi.
    risultati = [r for r in carica_risultati() if r["modello"] in MODELLI and r["run"] <= n_run(r["modello"])]
    stats = statistiche(risultati, casi_bird)
    scrivi_tabelle(stats, risultati, casi_bird)
    figura_classifica(stats)
    figura_esiti(stats)
    figura_casi(stats, risultati, casi_bird)
    figura_tempi(stats)
    for i, s in enumerate(stats, 1):
        print(f"{i}. {s['nome']}: {s['esatti_robusti']} corretti senza copiature, {s['esatti']} corretti "
              f"su {s['run_valutati']} prove, correttezza parziale {s['f1_medio']:.1f}%")
    mancanti = sum(s["robustezza_mancante"] for s in stats)
    if mancanti:
        print(f"ATTENZIONE: {mancanti} prove corrette senza controllo sulle copiature: eseguire python controllo_copiatura.py")
    print(f"Tabelle e figure salvate in {CARTELLA_USCITA}/")


if __name__ == "__main__":
    main()
