# Tesi Triennale - versione ottimizzata

Questa è la versione migliorata del progetto della mia tesi ([Tesi-Triennale](https://github.com/GiovanniMauroAltera/Tesi-Triennale)). L'idea resta la stessa: ho le tabelle di partenza di un database e la tabella finale ottenuta con una trasformazione, e voglio ricostruire la query SQL che porta dalle une all'altra.

Nel progetto principale ho misurato quanto sono bravi i modelli linguistici a farlo da soli. Qui ho cercato di trasformarlo in uno strumento che si possa usare davvero: veloce, e che dica chiaramente se la query trovata è affidabile. Ho provato tre strade e le ho confrontate sugli stessi 30 casi di BIRD del benchmark e sul caso dei PC, e poi su 45 casi BIRD nuovi che non avevo mai guardato.

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
| Modelli con gli indizi | gpt-oss | 16,7% | 16,7% | 4 s |
| Modelli con gli indizi | Qwen3 4B | 16,7% | 6,7% | 14 s |
| Senza modelli | - | 86,7% | 60,0% | 0,1 s |
| Misto | Gemma | 86,7% | 63,3% | 69 s |
| Misto | Nemotron | 86,7% | 63,3% | 30 s |
| Misto | gpt-oss | 82,2% | 61,1% | 4 s |
| Misto | Qwen3 4B | 83,3% | 51,7% | 18 s |

Con tutti i modelli insieme (come funziona davvero il programma), il metodo misto risolve onestamente 26 casi su 30 (20 con la stessa regola della query vera) e la prima risposta valida arriva di solito in circa 3 secondi. Con i soli indizi i casi sono 15 (10); nel benchmark originale, mettendo insieme tutti i modelli e tutte le prove ripetute, erano 10 (5).

Il metodo misto è stato ripetuto più volte: 3 prove per caso con gpt-oss e 4 con i modelli sul mio computer. I risultati cambiano pochissimo da una prova all'altra. Gemma con gli indizi è misurata su 27 casi, perché su tre casi i server di Google vanno sempre in errore.

Il caso dei PC (prezzi in valute diverse da convertire in dollari) è quello originale della tesi e richiede di dedurre i tassi di cambio. Il metodo senza modelli non lo risolve, perché servono calcoli. Lo risolvono Gemma con gli indizi, Nemotron con gli indizi e Gemma con il metodo misto, trovando i tassi esatti (1,08, 1,25 e 0,0065). Nel benchmark ci era riuscita solo Gemma, in 1 prova su 8.

### I modelli sul mio computer

Con il metodo misto ho provato anche i modelli locali, con 4 prove per caso ciascuno. "Scritte dal modello" sono le query giuste scritte dal modello stesso (in media per prova), senza contare quelle in cui ha sbagliato ed è rimasta la query del programma.

| Modello | Dimensione | Onesti | Scritte dal modello | Stessa regola della query vera | Tempo mediano |
|---|---|---|---|---|---|
| Qwen3.5 9B | 6,6 GB | 85,0% | 23,8 su 30 | 56,7% | 40 s |
| Qwen3 4B | 2,5 GB | 83,3% | 21,5 su 30 | 51,7% | 18 s |
| Llama 3.1 8B | 4,9 GB | 83,3% | 12,8 su 30 | 55,0% | 29 s |
| Qwen3.5 4B | 3,4 GB | 78,3% | 19,5 su 30 | 55,0% | 25 s |
| Qwen2.5-coder 7B | 4,7 GB | 77,5% | 22,0 su 30 | 54,2% | 26 s |

Nel benchmark Llama aveva lo 0,7% di risposte oneste in 141 secondi e Qwen2.5-coder il 2,5% in 40 secondi. Il migliore in locale è Qwen3.5 9B, che scrive da solo quasi quanto i modelli grandi online ma è più lento; Qwen3 4B è il compromesso migliore tra velocità e risultati. Llama sbaglia spesso perché allarga il filtro che gli propone il programma invece di usarlo com'è. Nessun modello locale risolve il caso dei PC.

### La prova su casi nuovi

Le regole del metodo senza modelli le avevo messe a punto guardando proprio i 30 casi del benchmark, quindi i risultati sopra potevano essere ottimistici. Per controllarlo ho preso 45 casi BIRD mai usati (15 "simple" come i 30 originali e 30 "moderate", più difficili), con gli stessi criteri dell'estrazione originale tranne il limite sulla lunghezza del prompt, e ho lasciato il codice com'era.

| Metodo | Modello | Onesti (45 casi) | Stessa regola della query vera |
|---|---|---|---|
| Modelli senza indizi | Qwen3 4B | 2,2% | 0% |
| Modelli con gli indizi | Gemma | 11,1% | 6,7% |
| Modelli con gli indizi | Qwen3 4B | 8,9% | 0% |
| Senza modelli | - | 26,7% | 15,6% |
| Misto | Gemma | 28,9% | 20,0% |
| Misto | Qwen3 4B | 26,7% | 15,6% |

I risultati sono molto più bassi: i casi nuovi sono più difficili (raggruppamenti, sottoquery, condizioni con OR, calcoli) e i 30 originali erano davvero favorevoli al metodo senza modelli. L'ordine però resta lo stesso: il metodo misto è il migliore, gli indizi aiutano, e i modelli da soli quasi non ci riescono. Gemma senza indizi è misurata solo su 10 casi (nessuno risolto), per gli errori continui dei server di Google.

## Cosa ho capito

- Il problema principale dei modelli non era scrivere l'SQL ma trovare il filtro: senza vedere le righe giuste dovevano indovinarlo. Mostrare gli indizi raddoppia i risultati.
- Sui casi di BIRD, che sono quasi tutti "prendi queste righe con questo filtro", un programma che prova le regole una per una fa già quasi tutto il lavoro. Il modello serve soprattutto quando ci sono calcoli da fare (come nel caso dei PC) e per scegliere tra regole che funzionano tutte sui dati quella che ha senso.
- Quando la tabella finale ha una sola riga quasi ogni colonna di quella riga funziona come filtro, e nessun metodo può sapere quale fosse quella "vera": è il limite che resta.
- Le regole del metodo senza modelli le ho messe a punto sui 30 casi del benchmark: sui casi nuovi passa dall'87% al 27%. Il vantaggio del metodo misto sugli altri metodi però resta anche lì.

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

Con `--modelli` si sceglie quali modelli usare e con `--correzioni` quanti tentativi di correzione dare. Le chiavi dei servizi in cloud vanno salvate come variabili d'ambiente (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GOOGLE_API_KEY`), mai nel codice; per i modelli locali serve [Ollama](https://ollama.com/) con `qwen3:4b-instruct` e `qwen3.5:9b`. I modelli usati di base sono gpt-oss, Nemotron, Gemma, Qwen3 4B e Qwen3.5 9B; gli altri (Llama 3.1, Qwen2.5-coder, Qwen3.5 4B, Qwen3 4B che ragiona) si scelgono con `--modelli`. Tutti i servizi usati sono gratuiti.

I casi di BIRD in `casi_BIRD/` e `casi_BIRD_nuovi/` non sono su GitHub (contengono tabelle reali, alcune grandi): si rigenerano con gli script del progetto principale.
