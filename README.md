# Tesi Triennale - versione ottimizzata

Questa è la versione migliorata del progetto della mia tesi ([Tesi-Triennale](https://github.com/GiovanniMauroAltera/Tesi-Triennale)). L'idea resta la stessa: do a un modello linguistico le tabelle di partenza di un database e la tabella finale ottenuta con una trasformazione, e gli chiedo di ricostruire la query SQL che porta dalle une all'altra.

Nel progetto principale ho misurato quanto sono bravi i modelli a farlo. Qui invece ho cercato di trasformarlo in uno strumento che si possa usare davvero: veloce, e che dica chiaramente se la query trovata è affidabile.

## Come funziona

1. Il programma prepara la descrizione delle tabelle per i modelli. Oltre a qualche riga di esempio, cerca da solo nei dati le righe di partenza da cui nasce la tabella finale e le mostra come "indizi": senza di queste, nella maggior parte dei casi il modello dovrebbe indovinare la regola senza vederne le prove.
2. Manda la stessa richiesta a più modelli contemporaneamente (gpt-oss, Nemotron, Gemma e Qwen3 sul mio computer).
3. Quando arriva una risposta, esegue la query su una copia del database (senza la tabella finale, così il modello non può leggerla) e confronta il risultato con la tabella finale.
4. Controlla che il modello non abbia copiato i valori della tabella finale invece di capire la trasformazione.
5. Se la query è sbagliata, spiega al modello cosa non va e gli dà altri due tentativi.
6. Si ferma alla prima query che riproduce la tabella finale senza copiare.

## I file

- `codice_principale.py`: quello da lanciare, coordina tutto.
- `modelli.py`: l'elenco dei modelli e il codice che li chiama.
- `prompt.py`: prepara cosa mandare ai modelli, compresi gli indizi e i messaggi di correzione.
- `verifica.py`: esegue la query del modello e la confronta con la tabella finale.

## Come si usa

```bash
pip install -r requirements.txt
python codice_principale.py --caso casi_BIRD/1334_student_club.sqlite
python codice_principale.py --database miei_dati.sqlite --partenza TABELLA_A TABELLA_B --finale TABELLA_FINALE
```

Con `--modelli` si sceglie quali modelli usare e con `--correzioni` quanti tentativi di correzione dare. Le chiavi dei servizi in cloud vanno salvate come variabili d'ambiente (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GOOGLE_API_KEY`), mai nel codice; per il modello locale serve [Ollama](https://ollama.com/) con `qwen3:4b-instruct`.

I 30 casi di BIRD in `casi_BIRD/` non sono su GitHub (contengono tabelle reali, alcune grandi): si rigenerano con gli script del progetto principale.
