# Tesi Triennale - versione ottimizzata

Questa è la versione migliorata del progetto della mia tesi ([Tesi-Triennale](https://github.com/GiovanniMauroAltera/Tesi-Triennale)). L'idea resta la stessa: ho le tabelle di partenza di un database e la tabella finale ottenuta con una trasformazione, e voglio ricostruire la query SQL che porta dalle une all'altra.

Nel progetto principale ho misurato quanto sono bravi i modelli linguistici a farlo da soli. Qui ho cercato di trasformarlo in uno strumento che si possa usare davvero: veloce, e che dica chiaramente se la query trovata è affidabile. Ho provato tre strade e le ho confrontate sugli stessi 30 casi di BIRD del benchmark e sul caso dei PC.

## I tre metodi

**1. Modelli con gli indizi** (`codice_principale.py`). Il programma prepara la descrizione delle tabelle e cerca da solo nei dati le righe di partenza da cui nasce la tabella finale, mostrandole al modello come "indizi". Analizzando gli errori del benchmark avevo visto che quasi sempre il modello sbagliava il filtro perché non vedeva le righe giuste: vedeva solo le prime 5 righe di ogni tabella. Poi manda la stessa richiesta a più modelli insieme e tiene la prima query che funziona.

**2. Ricerca delle regole senza modelli** (`codice_ricerca_noLLM.py`). Un programma normale, senza intelligenza artificiale, che prova le regole possibili dalla più semplice alla più complicata (colonna = valore, anno o mese di una data, intervalli di numeri, due condizioni insieme, i primi N in ordine) su ogni tabella e sulle tabelle unite, e tiene la prima che riproduce la tabella finale. È velocissimo, ma ha due limiti: non sa fare calcoli (somme, medie, conversioni) e a volte trova una regola che funziona per coincidenza (per esempio un intervallo di CAP al posto dello stato).

**3. Metodo misto** (`codice_misto.py`). Prima il programma del metodo 2 cerca le regole possibili, poi il modello le riceve insieme agli indizi, sceglie quella che ha senso e scrive la query completa, aggiungendo i calcoli se servono. Se il modello non ci riesce resta la query del programma.

In tutti e tre i casi la query viene eseguita su una copia del database (senza la tabella finale, così non si può leggere la soluzione) e confrontata con la tabella finale. Se è sbagliata il modello riceve una spiegazione di cosa non va e può correggerla.

## Risultati

Ho usato le stesse misure del benchmark. Una query è "onesta" se riproduce la tabella finale, non scrive a mano i suoi valori e funziona ancora quando tolgo a caso il 30% delle righe. In più ho fatto un controllo più severo, "stessa regola della query vera": mescolo i valori di una colonna alla volta e guardo se la query cambia risultato esattamente come quella vera. Così si scoprono le regole che funzionano solo per coincidenza.

Percentuali sui 30 casi BIRD:

| Metodo | Modello | Onesti | Stessa regola della query vera | Tempo mediano |
|---|---|---|---|---|
| Originale (benchmark) | Gemma | 14,6% | 5,4% | 206 s |
| Originale (benchmark) | Nemotron | 14,4% | 2,2% | 168 s |
| Originale (benchmark) | gpt-oss | 6,7% | 0% | 6 s |
| Modelli con gli indizi | Gemma | 37,0% | 29,6% | 120 s |
| Modelli con gli indizi | Nemotron | 36,7% | 26,7% | 219 s |
| Modelli con gli indizi | gpt-oss | 20,0% | 20,0% | 4 s |
| Modelli con gli indizi | Qwen3 4B | 16,7% | 6,7% | 14 s |
| Senza modelli | - | 86,7% | 60,0% | 0,1 s |
| Misto | Gemma | 86,7% | 63,3% | 69 s |
| Misto | Nemotron | 86,7% | 63,3% | 30 s |
| Misto | gpt-oss | 83,3% | 60,0% | 3 s |
| Misto | Qwen3 4B | 83,3% | 53,3% | 20 s |

Con tutti i modelli insieme (come funziona davvero il programma), il metodo misto risolve onestamente 26 casi su 30 (20 con la stessa regola della query vera) e la prima risposta valida arriva di solito in circa 3 secondi. Con i soli indizi i casi sono 15 (10); nel benchmark originale, mettendo insieme tutti i modelli e tutte le prove ripetute, erano 10 (5).

Due misure non sono complete perché i servizi gratuiti non hanno risposto in tempo: gpt-oss con gli indizi è misurato su 25 casi (limite giornaliero di Groq) e Gemma con gli indizi su 27 (tre casi su cui i server di Google vanno sempre in errore); le loro percentuali sono sui casi misurati.

Il caso dei PC (prezzi in valute diverse da convertire in dollari) è quello originale della tesi e richiede di dedurre i tassi di cambio. Il metodo senza modelli non lo risolve, perché servono calcoli. Lo risolvono Gemma con gli indizi, Nemotron con gli indizi e Gemma con il metodo misto, trovando i tassi esatti (1,08, 1,25 e 0,0065). Nel benchmark ci era riuscita solo Gemma, in 1 prova su 8.

## Cosa ho capito

- Il problema principale dei modelli non era scrivere l'SQL ma trovare il filtro: senza vedere le righe giuste dovevano indovinarlo. Mostrare gli indizi raddoppia i risultati.
- Sui casi di BIRD, che sono quasi tutti "prendi queste righe con questo filtro", un programma che prova le regole una per una fa già quasi tutto il lavoro. Il modello serve soprattutto quando ci sono calcoli da fare (come nel caso dei PC) e per scegliere tra regole che funzionano tutte sui dati quella che ha senso.
- Quando la tabella finale ha una sola riga quasi ogni colonna di quella riga funziona come filtro, e nessun metodo può sapere quale fosse quella "vera": è il limite che resta.
- Attenzione: le regole del metodo senza modelli le ho messe a punto guardando proprio questi 30 casi, quindi i suoi risultati sono probabilmente un po' ottimistici. Per esserne sicuri andrebbero provati su casi nuovi.

## I file

- `codice_principale.py`: modelli con gli indizi, tutti insieme, con le correzioni.
- `codice_ricerca_noLLM.py`: la ricerca delle regole senza modelli.
- `codice_misto.py`: il metodo misto (quello consigliato).
- `modelli.py`: l'elenco dei modelli e il codice che li chiama.
- `prompt.py`: prepara cosa mandare ai modelli, compresi gli indizi e i messaggi di correzione.
- `verifica.py`: esegue la query e la confronta con la tabella finale.

## Come si usa

```bash
pip install -r requirements.txt
python codice_misto.py --caso casi_BIRD/1334_student_club.sqlite
python codice_misto.py --database miei_dati.sqlite --partenza TABELLA_A TABELLA_B --finale TABELLA_FINALE
python codice_ricerca_noLLM.py --caso casi_BIRD/1334_student_club.sqlite
```

Con `--modelli` si sceglie quali modelli usare e con `--correzioni` quanti tentativi di correzione dare. Le chiavi dei servizi in cloud vanno salvate come variabili d'ambiente (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GOOGLE_API_KEY`), mai nel codice; per il modello locale serve [Ollama](https://ollama.com/) con `qwen3:4b-instruct`. Tutti i servizi usati sono gratuiti.

I 30 casi di BIRD in `casi_BIRD/` non sono su GitHub (contengono tabelle reali, alcune grandi): si rigenerano con gli script del progetto principale.
