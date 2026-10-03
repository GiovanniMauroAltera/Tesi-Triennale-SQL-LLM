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
    "qwen2.5-coder-7b": {"fornitore": "ollama", "nome": "qwen2.5-coder:7b"},
    # Al posto di Llama 3.1 (01/10), due versioni di Qwen3 4B (2,5 GB): "instruct" risponde subito,
    # quella base ragiona sempre prima di rispondere (non si puo' spegnere) e le serve un tetto di token piu' alto.
    "qwen3-4b": {"fornitore": "ollama", "nome": "qwen3:4b-instruct"},
    "qwen3-4b-ragiona": {"fornitore": "ollama", "nome": "qwen3:4b", "pensa": True, "max_token": 4096},
    # Il modello locale del benchmark, per confrontarlo con il metodo misto (03/10): non e' tra quelli di base
    # perche' sul PC della tesi e' lento (4,9 GB, non sta nella memoria della scheda video).
    "llama3.1": {"fornitore": "ollama", "nome": "llama3.1:latest", "di_base": False},
    # Qwen3.5 (03/10, scelti dall'utente per provare i modelli locali piu' nuovi): il ragionamento si puo' spegnere.
    "qwen3.5-4b": {"fornitore": "ollama", "nome": "qwen3.5:4b", "pensa": False, "di_base": False},
    "qwen3.5-9b": {"fornitore": "ollama", "nome": "qwen3.5:9b", "pensa": False, "di_base": False},
}
# I modelli interrogati quando non se ne sceglie nessuno con --modelli.
MODELLI_DI_BASE = [nome for nome, config in MODELLI.items() if config.get("di_base", True)]


MAX_ATTESE_LIMITE_AL_MINUTO = 6


class ModelloNonDisponibile(Exception):
    """Quota giornaliera finita o chiave mancante: inutile riprovare oggi."""


def _attesa_suggerita(messaggio):
    """Secondi da aspettare indicati nel messaggio d'errore (es. Groq: 'Please try again in 1m2.5s')."""
    trovato = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", messaggio)
    if not trovato:
        return None
    return int(trovato.group(1) or 0) * 60 + float(trovato.group(2))


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


def _contesto_necessario(messaggi, max_token):
    """Il contesto piu' piccolo che basta: con meno contesto il modello sta tutto nella scheda video ed e' piu' veloce.

    Stima prudente di 2 caratteri per token (il prompt piu' lungo dei casi BIRD: 8499 caratteri = 4242 token).
    """
    token_prompt = sum(len(m["content"]) for m in messaggi) / 2
    return max(CONTESTO_MINIMO_LOCALI, math.ceil((token_prompt + max_token + 256) / 1024) * 1024)


def _chiama_ollama(config, messaggi):
    max_token = config.get("max_token", MAX_TOKEN_LOCALI)
    richiesta = {"model": config["nome"], "messages": messaggi, "stream": False,
                 "options": {"temperature": 0, "num_ctx": _contesto_necessario(messaggi, max_token),
                             "num_predict": max_token}}
    if "pensa" in config:
        richiesta["think"] = config["pensa"]  # il ragionamento torna a parte, non nel testo della risposta
    risposta = httpx.post(OLLAMA, timeout=FORNITORI["ollama"][2], json=richiesta)
    risposta.raise_for_status()
    dati = risposta.json()
    return dati["message"]["content"], dati.get("done_reason") == "length"


def chiama(modello, messaggi):
    """Manda la conversazione al modello e restituisce (testo della risposta, True se e' stata tagliata)."""
    config = MODELLI[modello]
    if config["fornitore"] == "ollama":
        return _chiama_ollama(config, messaggi)

    indirizzo, variabile, secondi = FORNITORI[config["fornitore"]]
    client = OpenAI(base_url=indirizzo, api_key=leggi_chiave(variabile), timeout=secondi, max_retries=0)
    for _ in range(MAX_ATTESE_LIMITE_AL_MINUTO):
        try:
            risposta = client.chat.completions.create(model=config["nome"], messages=messaggi, temperature=0.0,
                                                      **config.get("parametri", {}))
            break
        except Exception as errore:
            testo = str(errore)
            if "429" in testo and ("per day" in testo.lower() or "per-day" in testo.lower()):
                raise ModelloNonDisponibile(f"quota giornaliera gratuita finita: {errore}")
            attesa = _attesa_suggerita(testo)
            if "429" not in testo or attesa is None or attesa > 120:
                raise
            time.sleep(attesa + 1)  # limite al minuto: il fornitore dice quanto aspettare
    else:
        raise RuntimeError("limite di richieste al minuto: troppe attese di fila")
    if not risposta.choices:
        # OpenRouter a volte risponde "200 OK" ma con l'errore del fornitore al posto della risposta.
        raise RuntimeError(f"risposta vuota dal fornitore: {(risposta.model_extra or {}).get('error')}")
    scelta = risposta.choices[0]
    return scelta.message.content or "", scelta.finish_reason == "length"
