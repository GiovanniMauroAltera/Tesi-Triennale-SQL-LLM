"""I modelli disponibili (tutti gratuiti) e il codice che li chiama."""
import math
import os
import re
import sys
import time

import httpx
from openai import OpenAI

# Le risposte giuste dei modelli locali nel benchmark stavano tutte sotto i 500 token:
# oltre i 1024 e' quasi sempre un ciclo di ripetizioni, che prima durava fino a 15 minuti.
MAX_TOKEN_LOCALI = 1024
CONTESTO_MINIMO_LOCALI = 4096
OLLAMA = "http://localhost:11434/api/chat"

FORNITORI = {
    # nome: (indirizzo, variabile con la chiave, secondi massimi di attesa per una risposta)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", 120),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", 600),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_API_KEY", 600),
    "ollama": (OLLAMA, None, 600),
}

MODELLI = {
    "gpt-oss-120b": {"fornitore": "groq", "nome": "openai/gpt-oss-120b"},
    "nemotron": {"fornitore": "openrouter", "nome": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    "gemma": {"fornitore": "google", "nome": "gemma-4-31b-it"},
    # Sostituito da Qwen3.5 9B tra quelli di base (03/10): con il metodo misto 24 query giuste su 30 contro 22.
    "qwen2.5-coder-7b": {"fornitore": "ollama", "nome": "qwen2.5-coder:7b", "di_base": False},
    # Al posto di Llama 3.1 (01/10), due versioni di Qwen3 4B (2,5 GB): "instruct" risponde subito,
    # quella base ragiona sempre prima di rispondere (non si puo' spegnere) e le serve un tetto di token piu' alto.
    "qwen3-4b": {"fornitore": "ollama", "nome": "qwen3:4b-instruct"},
    # Non tra quelli di base (03/10): sul PC della tesi impiega 6-15 minuti a caso e rallenta gli altri modelli locali.
    "qwen3-4b-ragiona": {"fornitore": "ollama", "nome": "qwen3:4b", "pensa": True, "max_token": 4096, "di_base": False},
    # Il modello locale del benchmark, per confrontarlo con il metodo misto (03/10): non e' tra quelli di base
    # perche' sul PC della tesi e' lento (4,9 GB, non sta nella memoria della scheda video).
    "llama3.1": {"fornitore": "ollama", "nome": "llama3.1:latest", "di_base": False},
    # Qwen3.5 (03/10, scelti dall'utente per provare i modelli locali piu' nuovi): il ragionamento si puo' spegnere.
    "qwen3.5-4b": {"fornitore": "ollama", "nome": "qwen3.5:4b", "pensa": False, "di_base": False},
    "qwen3.5-9b": {"fornitore": "ollama", "nome": "qwen3.5:9b", "pensa": False},
}

# I modelli interrogati quando non se ne sceglie nessuno con --modelli.
MODELLI_DI_BASE = []
for nome, configurazione in MODELLI.items():
    if configurazione.get("di_base", True):
        MODELLI_DI_BASE.append(nome)

MAX_ATTESE_LIMITE_AL_MINUTO = 6


class ModelloNonDisponibile(Exception):
    """Quota giornaliera finita o chiave mancante: inutile riprovare oggi."""


def attesa_suggerita(messaggio):
    """Secondi da aspettare indicati nel messaggio d'errore (es. Groq: 'Please try again in 1m2.5s')."""
    trovato = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", messaggio)
    if not trovato:
        return None
    minuti = int(trovato.group(1) or 0)
    secondi = float(trovato.group(2))
    return minuti * 60 + secondi


def leggi_chiave(variabile):
    chiave = os.environ.get(variabile)
    if not chiave and sys.platform == "win32":
        # Una chiave salvata con setx finisce nel registro di Windows ma non nei terminali gia' aperti.
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registro:
                chiave = winreg.QueryValueEx(registro, variabile)[0]
        except OSError:
            chiave = None
    if not chiave:
        raise ModelloNonDisponibile(f"manca la chiave {variabile} (impostala con: setx {variabile} \"...\")")
    return chiave


def contesto_necessario(messaggi, max_token):
    """Il contesto piu' piccolo che basta: con meno contesto il modello sta tutto nella scheda video ed e' piu' veloce.

    Stima prudente di 2 caratteri per token (il prompt piu' lungo dei casi BIRD: 8499 caratteri = 4242 token).
    Il risultato e' arrotondato a un multiplo di 1024.
    """
    caratteri = 0
    for messaggio in messaggi:
        caratteri += len(messaggio["content"])
    token_prompt = caratteri / 2
    contesto = math.ceil((token_prompt + max_token + 256) / 1024) * 1024
    return max(CONTESTO_MINIMO_LOCALI, contesto)


def chiama_ollama(configurazione, messaggi):
    """Un modello sul computer, con Ollama."""
    max_token = configurazione.get("max_token", MAX_TOKEN_LOCALI)
    richiesta = {"model": configurazione["nome"], "messages": messaggi, "stream": False,
                 "options": {"temperature": 0, "num_ctx": contesto_necessario(messaggi, max_token),
                             "num_predict": max_token}}
    if "pensa" in configurazione:
        richiesta["think"] = configurazione["pensa"]  # il ragionamento torna a parte, non nel testo della risposta
    risposta = httpx.post(OLLAMA, timeout=FORNITORI["ollama"][2], json=richiesta)
    risposta.raise_for_status()
    dati = risposta.json()
    tagliata = dati.get("done_reason") == "length"
    return dati["message"]["content"], tagliata


def chiama(modello, messaggi):
    """Manda la conversazione al modello e restituisce (testo della risposta, True se e' stata tagliata)."""
    configurazione = MODELLI[modello]
    if configurazione["fornitore"] == "ollama":
        return chiama_ollama(configurazione, messaggi)

    indirizzo, variabile, secondi = FORNITORI[configurazione["fornitore"]]
    client = OpenAI(base_url=indirizzo, api_key=leggi_chiave(variabile), timeout=secondi, max_retries=0)
    risposta = None
    for _ in range(MAX_ATTESE_LIMITE_AL_MINUTO):
        try:
            risposta = client.chat.completions.create(model=configurazione["nome"], messages=messaggi,
                                                      temperature=0.0)
            break
        except Exception as errore:
            testo = str(errore)
            # 429 = troppe richieste. Se e' il limite del giorno non serve aspettare.
            if "429" in testo and ("per day" in testo.lower() or "per-day" in testo.lower()):
                raise ModelloNonDisponibile(f"quota giornaliera gratuita finita: {errore}")
            attesa = attesa_suggerita(testo)
            if "429" not in testo or attesa is None or attesa > 120:
                raise
            time.sleep(attesa + 1)  # limite al minuto: il fornitore dice quanto aspettare
    if risposta is None:
        raise RuntimeError("limite di richieste al minuto: troppe attese di fila")
    if not risposta.choices:
        # OpenRouter a volte risponde "200 OK" ma con l'errore del fornitore al posto della risposta.
        errore = None
        if risposta.model_extra:
            errore = risposta.model_extra.get("error")
        raise RuntimeError(f"risposta vuota dal fornitore: {errore}")
    scelta = risposta.choices[0]
    tagliata = scelta.finish_reason == "length"
    return scelta.message.content or "", tagliata
