# I casi presi da BIRD

In questa cartella ci sono i 30 casi che ho usato per il benchmark, presi dal dataset [BIRD Mini-Dev](https://github.com/bird-bench/mini_dev). Ogni caso è un piccolo file `.sqlite` che contiene tutto quello che serve: le tabelle di partenza (lo Stato A), la tabella finale (lo Stato B) e qualche informazione in più. Il formato è lo stesso che uso per il caso dei PC (`caso_PC/pc_multivaluta.sqlite`).

I file `.sqlite` non li ho caricati su GitHub, perché contengono tabelle reali di BIRD e alcune sono piuttosto grandi: si ricreano sul proprio computer seguendo i passaggi qui sotto. Su GitHub c'è solo `_manifest.json`, che è l'elenco dei 30 casi scelti.

## Come ho scelto i casi

Rispetto a BIRD il mio compito è più difficile. In BIRD il modello riceve una domanda scritta a parole (per esempio "quali gare si sono corse a settembre 2005?") e deve scrivere la query; io invece gli do solo i dati di partenza e il risultato finale, e deve capire da solo cosa è stato fatto. Per questo ho tenuto solo i casi che si possono ragionevolmente dedurre guardando i dati:

- solo esempi che BIRD considera **semplici** (quelli con l'etichetta "simple");
- query che usano **al massimo 2 tabelle** di partenza;
- prompt **non troppo lungo** (al massimo circa 3500 token), così entra nella memoria dei modelli che girano sul mio computer e nei limiti gratuiti dei servizi in cloud;
- **niente risultati fatti da un solo numero**, come un conteggio: da un numero da solo è impossibile capire quale filtro è stato applicato, perché tantissime query diverse danno lo stesso valore. Ho escluso anche i risultati vuoti.

Dei 500 esempi di BIRD Mini-Dev solo 34 rispettano tutte queste regole: 25 hanno un risultato con più righe e 9 un risultato con una sola riga ma più colonne. Ho preso prima tutti quelli con più righe, che sono i più facili da dedurre, e poi ho completato fino a 30 con quelli a una riga, scelti a caso ma sempre allo stesso modo (con il seme 42), così chiunque rifaccia l'estrazione ottiene esattamente gli stessi casi.

## Come ricreare i casi

1. Scaricare BIRD Mini-Dev:
   - il file con le domande e le query vere: da https://huggingface.co/datasets/birdsql/bird_mini_dev scaricare `data/mini_dev_sqlite-00000-of-00001.json` e salvarlo come `bird-mini-dev/mini_dev_sqlite.json`;
   - i database: scaricare `dev.zip` da https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip, aprire al suo interno `dev_20240627/dev_databases.zip` ed estrarre in `bird-mini-dev/dev_databases/` solo le cartelle degli 11 database elencati qui sotto.
2. Dalla cartella principale del progetto lanciare:
    ```bash
    python estrazione_casi_BIRD.py
    ```

Prima di lanciarlo, la cartella `bird-mini-dev/` deve essere fatta così:
```
bird-mini-dev/
  mini_dev_sqlite.json
  dev_databases/
    california_schools/california_schools.sqlite
    card_games/card_games.sqlite
    codebase_community/codebase_community.sqlite
    debit_card_specializing/debit_card_specializing.sqlite
    european_football_2/european_football_2.sqlite
    financial/financial.sqlite
    formula_1/formula_1.sqlite
    student_club/student_club.sqlite
    superhero/superhero.sqlite
    thrombosis_prediction/thrombosis_prediction.sqlite
    toxicology/toxicology.sqlite
```

## Il controllo dei casi

Per essere sicuro che i casi siano identici all'originale ho scritto `codice_verifica_casi_BIRD.py`: riesegue la query vera di BIRD su ogni caso e controlla che il risultato sia uguale alla tabella finale salvata nel file. Sui 30 casi il controllo passa sempre.

```bash
python codice_verifica_casi_BIRD.py
```

## Cosa c'è dentro ogni file

- Le tabelle di partenza che servono alla query (lo Stato A).
- `RISULTATO_ATTESO`, cioè la tabella finale già calcolata (lo Stato B).
- `_caso_info`, con i nomi delle tabelle di partenza e di quella finale, che il programma usa per caricare il caso.
- `_bird_info`, con i dati originali di BIRD: numero della domanda, database, difficoltà, domanda scritta a parole, suggerimento e query vera. Queste informazioni **non vengono mai mostrate ai modelli**: servono solo a me per documentare i casi nella tesi.
