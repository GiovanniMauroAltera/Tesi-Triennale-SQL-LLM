I file che contengono la parola "python" nel nome sono gli script con il codice vero e proprio, mentre i file e le cartelle nominati "Risultato" contengono le stampe di ciò che esce sulla console (PowerShell) quando faccio eseguire il programma. 

Ho diviso i test in due categorie principali per valutare le prestazioni:

Test in locale: Ho fatto girare i modelli direttamente sul mio computer. Poiché la mia macchina ha una potenza di calcolo limitata, i modelli utilizzati sono più leggeri e faticano parecchio. Di conseguenza, i risultati sono meno accurati, spesso presentano degli errori e tendono a ignorare o non rispettare del tutto le regole logiche che gli impongo nel prompt.

Test in Cloud (tramite OpenRouter): Qui ho potuto testare modelli molto più potenti, nello specifico Nemotron e Gemma, ottenendo un'accuratezza decisamente superiore. Nemotron è estremamente preciso nelle risposte, ma ha il difetto di impiegare tantissimo tempo per elaborare il risultato e molto spesso restituisce un errore perché i server si sovraccaricano. Gemma, invece, è molto più stabile e veloce (ha pochissimi errori di server), ma pecca un po' in precisione e ogni tanto commette qualche sbaglio nei ragionamenti.

Noterà leggendo il codice che i prompt che invio ai modelli sono pieni di clausole e regole molto rigide. Questo perché, utilizzando versioni gratuite delle intelligenze artificiali, c'è un alto rischio di "allucinazioni", quindi bisogna essere estremamente restrittivi per tenerli in carreggiata e guidare i loro ragionamenti.

Infine, noterà una cartella chiamata "progetto alternativo". Qui l'approccio logico è quello simile a BIRD: invece di fornire al modello la Tabella A e la Tabella B e farci restituire cosa è successo nel mezzo, gli fornisco solo la Tabella A (insieme a qualche eventuale tabella intermedia). Dopodiché, gli fornisco la strutturata della Tabella B finale e lascio che sia lui a calcolarsi i dati per costruirla da zero (anche qui ho fatto le stesse cose dei modelli in locale, OpenRouter e Gemini e succede la stessa cosa, quello in locale spesso commette allucinazioni e quelli sul cloud ci mettono tanto a rispondere e danno problemi di collegamento)

## Istruzioni di Utilizzo

Per testare il framework seguire i passaggi sottostanti.

### 1. Prerequisiti di Sistema
*   Assicurarsi di avere **Python 3** installato nel proprio ambiente.
*   Installare la libreria client di OpenAI:
    ```bash
    pip install openai
    ```
*   Il sistema utilizza `sqlite3`, già integrato nativamente in Python. Per utilizzare database relazionali differenti (es. PostgreSQL, MySQL), sarà necessario adattare le librerie di connessione e sostituire le query di sistema specifiche (come `sqlite_master`).

### 2. Configurazione dei Modelli
*   **Esecuzione in Locale (Ollama):** Scaricare [Ollama](https://ollama.com/), avviarlo in background e scaricare il modello desiderato dal terminale (es. `ollama pull qwen2.5` o `ollama pull llama3.1`).
*   **Esecuzione in Cloud (OpenRouter/Groq):** Aprire lo script Python desiderato, individuare il blocco di configurazione del client `OpenAI` e inserire la propria **API Key** personale.

Per analizzare il proprio database:
1.  **Connessione:** Nello script, sostituire la connessione temporanea (es. `sqlite3.connect(':memory:')`) con il percorso al file del proprio database fisico:
    ```python
    conn = sqlite3.connect('percorso/del/proprio/database.db')
    ```
2.  **Selezione delle Tabelle:** Individuare le variabili di input e inserire i nomi esatti delle tabelle su cui si intende eseguire l'analisi:
    ```python
    # Inserire qui le tabelle di partenza per l'estrazione
    NOMI_TABELLE_SORGENTE = ('NOME_TABELLA_A', 'NOME_TABELLA_B') 
    
    # Inserire qui la tabella finale da dedurre o ricostruire
    NOME_TABELLA_TARGET = 'NOME_TABELLA_FINALE' 
    ```
    
### 3. Esecuzione
Lanciare lo script dal terminale o da PowerShell:
```bash
python nome_dello_script.py 
```
