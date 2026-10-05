# Confronto tra la versione originale e la versione ottimizzata

Tabelle generate da `versione_ottimizzata/codice_confronto.py` a partire da `grafici/prove.csv`.

## I 30 casi originali

| Versione | Modello | Prove | Corrette | Oneste | Stessa regola della query vera | Scritte dal modello | Tempo mediano |
|---|---|---|---|---|---|---|---|
| originale | gpt-oss-120b | 90 (3 per caso) | 26,7% | 6,7% | 0,0% | 6,7% | 6 s |
| originale | Nemotron 3 Ultra | 90 (3 per caso) | 44,4% | 14,4% | 2,2% | 14,4% | 168 s |
| originale | Gemma 4 31B | 240 (8 per caso) | 34,2% | 14,6% | 5,4% | 14,6% | 206 s |
| originale | Qwen2.5-Coder 7B | 240 (8 per caso) | 17,1% | 2,5% | 0,0% | 2,5% | 40 s |
| originale | Llama 3.1 8B | 150 (5 per caso) | 1,3% | 0,7% | 0,0% | 0,7% | 141 s |
| ottimizzata | gpt-oss-120b | 90 (3 per caso) | 100,0% | 82,2% | 61,1% | 80,0% | 4 s |
| ottimizzata | Nemotron 3 Ultra | 30 (1 per caso) | 100,0% | 86,7% | 63,3% | 83,3% | 30 s |
| ottimizzata | Gemma 4 31B | 30 (1 per caso) | 100,0% | 86,7% | 63,3% | 70,0% | 69 s |
| ottimizzata | Qwen2.5-Coder 7B | 120 (4 per caso) | 100,0% | 77,5% | 54,2% | 73,3% | 26 s |
| ottimizzata | Llama 3.1 8B | 120 (4 per caso) | 100,0% | 83,3% | 55,0% | 42,5% | 29 s |
| ottimizzata | Qwen3 4B | 120 (4 per caso) | 100,0% | 83,3% | 51,7% | 71,7% | 18 s |
| ottimizzata | Qwen3.5 4B | 120 (4 per caso) | 96,7% | 78,3% | 55,0% | 65,0% | 25 s |
| ottimizzata | Qwen3.5 9B | 120 (4 per caso) | 100,0% | 85,0% | 56,7% | 79,2% | 40 s |

- originale, tutti i modelli insieme: 10 casi su 30 risolti in modo onesto, 5 con la stessa regola della query vera.
- ottimizzata, tutti i modelli insieme: 26 casi su 30 risolti in modo onesto, 20 con la stessa regola della query vera.

## Il caso dei PC

| Versione | Modello | Prove | Oneste |
|---|---|---|---|
| originale | gpt-oss-120b | 3 | 0 |
| originale | Nemotron 3 Ultra | 3 | 0 |
| originale | Gemma 4 31B | 8 | 1 |
| originale | Qwen2.5-Coder 7B | 8 | 0 |
| originale | Llama 3.1 8B | 5 | 0 |
| ottimizzata | gpt-oss-120b | 3 | 0 |
| ottimizzata | Nemotron 3 Ultra | 1 | 0 |
| ottimizzata | Gemma 4 31B | 1 | 1 |
| ottimizzata | Qwen2.5-Coder 7B | 4 | 0 |
| ottimizzata | Llama 3.1 8B | 4 | 0 |
| ottimizzata | Qwen3 4B | 4 | 0 |
| ottimizzata | Qwen3.5 4B | 4 | 0 |
| ottimizzata | Qwen3.5 9B | 4 | 0 |

## I 90 casi nuovi (solo versione ottimizzata)

| Modello | Difficolta' | Prove | Oneste | Stessa regola della query vera | Tempo mediano |
|---|---|---|---|---|---|
| Gemma 4 31B | simple | 15 | 40,0% | 20,0% | 136 s |
| Qwen3 4B | simple | 15 | 40,0% | 26,7% | 64 s |
| Qwen3.5 4B | simple | 15 | 40,0% | 20,0% | 66 s |
| Qwen3.5 9B | simple | 15 | 40,0% | 20,0% | 80 s |
| Gemma 4 31B | moderate | 30 | 23,3% | 20,0% | 176 s |
| Qwen3 4B | moderate | 60 | 23,3% | 8,3% | 25 s |
| Qwen3.5 4B | moderate | 60 | 21,7% | 13,3% | 37 s |
| Qwen3.5 9B | moderate | 60 | 23,3% | 15,0% | 54 s |
| Qwen3 4B | challenging | 15 | 20,0% | 6,7% | 31 s |
| Qwen3.5 4B | challenging | 15 | 26,7% | 13,3% | 61 s |
| Qwen3.5 9B | challenging | 15 | 26,7% | 13,3% | 56 s |
| Gemma 4 31B | tutte | 45 | 28,9% | 20,0% | 171 s |
| Qwen3 4B | tutte | 90 | 25,6% | 11,1% | 34 s |
| Qwen3.5 4B | tutte | 90 | 25,6% | 14,4% | 47 s |
| Qwen3.5 9B | tutte | 90 | 26,7% | 15,6% | 57 s |
