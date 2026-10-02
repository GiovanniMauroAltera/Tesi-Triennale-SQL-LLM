# Classifica del benchmark

Casi: 30 esempi BIRD Mini-Dev (simple, max 2 tabelle, niente risultati a singolo valore), 3 prove per caso (8 per Gemma 4 31B e Qwen2.5-Coder 7B; 5 per Llama 3.1 8B). Le percentuali sono calcolate sulle prove di ciascun modello; *casi risolti in tutte le prove* è più severo per chi ha fatto più prove.

- *Risultati corretti*: il risultato della query del modello è identico alla tabella finale (è la Execution Accuracy usata da BIRD).
- *Risultati corretti senza copiature*: il risultato è corretto e supera due controlli (`controllo_copiatura.py`), che escludono chi ha ricopiato i valori della tabella finale (il prompt la mostra per intero quando ha poche righe): resta corretto anche su 3 copie dei dati di partenza con il 30% delle righe tolte, e nel testo della query non compaiono scritti a mano almeno metà dei valori di testo della tabella finale. Il secondo controllo scopre le copiature unite ai dati veri con un JOIN o un filtro IN (...), che togliendo righe passano inosservate.
- *Correttezza parziale*: punteggio F1 sulle righe (media di precisione e richiamo), premia i risultati quasi giusti e penalizza sia le righe mancanti sia quelle in più.

| # | Modello | Prove valutate | Risultati corretti senza copiature | Risultati corretti | Correttezza parziale | Casi risolti almeno una volta | Casi risolti in tutte le prove | Errori di chiamata | Errori SQL | Risposte troncate | Tempo mediano (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Gemma 4 31B (Google) | 240/240 | 35 (14,6%) | 82 (34,2%) | 49,1% | 14/30 | 6/30 | 0 | 0 | 0 | 206 |
| 2 | Nemotron 3 Ultra (OpenRouter) | 90/90 | 13 (14,4%) | 40 (44,4%) | 57,5% | 19/30 | 7/30 | 0 | 2 | 0 | 168 |
| 3 | gpt-oss-120b (Groq) | 90/90 | 6 (6,7%) | 24 (26,7%) | 40,6% | 14/30 | 3/30 | 0 | 4 | 1 | 6 |
| 4 | Qwen2.5-Coder 7B (locale) | 240/240 | 6 (2,5%) | 41 (17,1%) | 26,1% | 14/30 | 3/30 | 0 | 29 | 41 | 40 |
| 5 | Llama 3.1 8B (locale) | 150/150 | 1 (0,7%) | 2 (1,3%) | 3,1% | 2/30 | 0/30 | 0 | 76 | 48 | 141 |

## Caso demo (pc_multivaluta), riportato a parte

Il caso originale della tesi (conversione valute con tassi nascosti da dedurre) non entra nella classifica BIRD.

| Modello | Risultati corretti senza copiature | Risultati corretti | Correttezza parziale |
|---|---|---|---|
| Gemma 4 31B (Google) | 1/8 | 1/8 | 31,2% |
| Nemotron 3 Ultra (OpenRouter) | 0/3 | 0/3 | 11,1% |
| gpt-oss-120b (Groq) | 0/3 | 0/3 | 0,0% |
| Qwen2.5-Coder 7B (locale) | 0/8 | 0/8 | 0,0% |
| Llama 3.1 8B (locale) | 0/5 | 0/5 | 0,0% |
