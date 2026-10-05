# Prova veloce

In questa cartella ci sono tre casi piccoli presi da BIRD e lo script `quick_start.py`, per vedere il progetto in funzione senza scaricare niente. Lo script usa anche il caso dei PC (`caso_PC/pc_multivaluta.sqlite`).

| Caso | Domanda di BIRD (non viene mai mostrata al programma né ai modelli) | Che regola serve |
|---|---|---|
| `781_superhero` | Provide the heights of the heroes whose eye colours are amber. | un filtro su una tabella collegata (il colore degli occhi) |
| `978_formula_1` | How many times the circuits were held in Austria? Please give their location and coordinates. | un filtro semplice (il paese) |
| `1035_european_football_2` | Give the team_fifa_api_id of teams with more than 50 but less than 60 build-up play speed. | un intervallo di numeri |
| caso dei PC | Qual è il prezzo medio in dollari di ogni modello di PC? | un calcolo con i tassi di cambio, che vanno dedotti dai dati |

Dalla cartella principale della repository:

```bash
python prova_veloce/quick_start.py
python prova_veloce/quick_start.py --caso 781_superhero --modelli qwen3-4b
```

Senza `--modelli` lavora solo il programma che cerca i filtri: risolve i tre casi di BIRD in pochi secondi, ma non il caso dei PC, perché lì servono dei calcoli. Con `--modelli` lavora la versione ottimizzata completa (le istruzioni sono nel [README principale](../README.md#prova-veloce)).

## Da dove vengono i casi

I tre casi sono estratti da [BIRD Mini-Dev](https://github.com/bird-bench/mini_dev) (Li et al., "Can LLM Already Serve as A Database Interface? A BIg Bench for Large-Scale Database Grounded Text-to-SQLs", NeurIPS 2023), che è distribuito con licenza [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Ogni file contiene solo le tabelle che servono alla query, la tabella finale ottenuta con la query vera di BIRD e le informazioni originali di BIRD (domanda, suggerimento e query vera). Come richiede la licenza, questi tre file sono distribuiti con la stessa licenza CC BY-SA 4.0.
