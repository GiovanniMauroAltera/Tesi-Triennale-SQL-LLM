# Casi BIRD

Questa cartella contiene, dopo la generazione, 30 casi di test estratti dal dataset [BIRD Mini-Dev](https://github.com/bird-bench/mini_dev) nello stesso formato `.sqlite` + `_caso_info` usato dal caso demo (`casi/pc_multivaluta.sqlite`).

I file `.sqlite` **non sono versionati in git** (contengono tabelle reali di BIRD, alcune molto grandi) — vengono rigenerati in locale.

## Come rigenerarli

1. Scarica BIRD Mini-Dev:
   - JSON con domande/query gold: https://huggingface.co/datasets/birdsql/bird_mini_dev (file `data/mini_dev_sqlite-00000-of-00001.json`) -> salvalo come `bird-mini-dev/mini_dev_sqlite.json`
   - Database originali: scarica `dev.zip` da https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip, estrai `dev_20240627/dev_databases.zip`, e da questo estrai solo le cartelle degli 11 database elencati sotto in `bird-mini-dev/dev_databases/`
2. Esegui `python estrai_casi_bird.py` dalla root del progetto.

Struttura attesa prima di eseguire lo script:
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

## Criteri di selezione

Il nostro compito e' piu' difficile del text-to-SQL originale di BIRD: il modello non vede la domanda in linguaggio naturale, solo i dati di partenza e il risultato. Per questo si usano solo casi semplici e "deducibili":

- solo esempi con difficolta' **simple** (etichetta originale di BIRD);
- query gold con **al massimo 2 tabelle sorgente**;
- **prompt piccolo** (stima <= 3500 token, ~4 caratteri/token): entra nel contesto dei modelli locali e nei limiti gratuiti di Groq;
- **niente risultati ridotti a un singolo valore** (1 riga x 1 colonna, es. un conteggio): da un solo numero non si puo' risalire al filtro applicato, infinite query danno lo stesso valore. Esclusi anche i risultati vuoti.

Dei 500 esempi di Mini-Dev, 34 soddisfano tutti i criteri (25 con risultato di piu' righe, 9 a una riga ma piu' colonne). Si prendono prima tutti quelli con piu' righe (i piu' deducibili), poi si completa fino a 30 con quelli a una riga, scelti a caso con seed fisso (42). Per la riproducibilita' la stima dei token usa campioni fissi (prime righe) invece che casuali. `_manifest.json` elenca i 30 casi scelti, con tabelle, righe del risultato e token stimati.

## Verifica

`python verifica_estrazione_bird.py` riesegue la query gold di ogni caso estratto e controlla, tramite `valuta_accuratezza`, che il risultato coincida esattamente con la tabella target salvata nel file — conferma che l'estrazione e' fedele all'originale.

## Contenuto di ogni file `.sqlite`

- Le tabelle sorgente effettivamente referenziate dalla query gold (Stato A).
- `RISULTATO_ATTESO`: il risultato della query gold, già calcolato (Stato B).
- `_caso_info`: metadati letti da `carica_caso()` (nomi tabelle sorgente + nome tabella target).
- `_bird_info`: tracciabilità verso il dataset originale (question_id, db_id, difficulty, domanda, evidenza, query gold) — non viene mai passata al modello, serve solo per la documentazione della tesi.
