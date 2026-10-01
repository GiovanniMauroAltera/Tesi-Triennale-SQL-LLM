import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from funzioni_comuni import esegui_e_stampa, valuta_accuratezza, stampa_valutazione, carica_caso, estrai_query_sql

PERCORSO_CASO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caso_PC", "pc_multivaluta.sqlite")


def nuovo_caso():
    return carica_caso(PERCORSO_CASO)


print("\n########## CASO 1: Nemotron (main) - atteso 100% ##########")
conn, cursor, nomi_sorgente, nome_target = nuovo_caso()
query_nemotron = """
CREATE TEMP TABLE tassi_cambio AS
SELECT 'EUR' AS Valuta, 1.08 AS Tasso_USD UNION ALL
SELECT 'GBP' AS Valuta, 1.25 AS Tasso_USD UNION ALL
SELECT 'JPY' AS Valuta, 0.0065 AS Tasso_USD;

CREATE TEMP TABLE step_1 AS
SELECT
    VENDITE_PC.Modello,
    VENDITE_PC.Prezzo_Locale * tassi_cambio.Tasso_USD AS Prezzo_USD
FROM VENDITE_PC
JOIN tassi_cambio ON VENDITE_PC.Valuta_Locale = tassi_cambio.Valuta;

CREATE TEMP TABLE step_2 AS
SELECT
    step_1.Modello AS Modello_PC,
    AVG(step_1.Prezzo_USD) AS Prezzo_Medio_USD
FROM step_1
GROUP BY step_1.Modello;
"""
tabelle = esegui_e_stampa(cursor, query_nemotron)
risultato = valuta_accuratezza(cursor, tabelle, nome_target)
stampa_valutazione(risultato)
assert risultato["esatto"] and risultato["f1"] == 1.0, f"Atteso risultato esatto, ottenuto {risultato}"
conn.close()

print("\n########## CASO 2: Gemma (main) - atteso <100% ##########")
conn, cursor, nomi_sorgente, nome_target = nuovo_caso()
query_gemma = """
CREATE TEMP TABLE tasso_cambio AS
SELECT 'EUR' AS Valuta, 1.107 AS Tasso_USD UNION ALL
SELECT 'GBP' AS Valuta, 1.30859375 AS Tasso_USD UNION ALL
SELECT 'JPY' AS Valuta, 0.0046875 AS Tasso_USD;

CREATE TEMP TABLE step_1 AS
SELECT
    VENDITE_PC.Modello,
    VENDITE_PC.Prezzo_Locale * tasso_cambio.Tasso_USD AS Prezzo_USD
FROM VENDITE_PC
JOIN tasso_cambio ON VENDITE_PC.Valuta_Locale = tasso_cambio.Valuta;

CREATE TEMP TABLE step_2 AS
SELECT
    Modello AS Modello_PC,
    AVG(Prezzo_USD) AS Prezzo_Medio_USD
FROM step_1
GROUP BY Modello;
"""
tabelle = esegui_e_stampa(cursor, query_gemma)
risultato = valuta_accuratezza(cursor, tabelle, nome_target)
stampa_valutazione(risultato)
assert not risultato["esatto"] and risultato["f1"] < 1.0, f"Atteso risultato non esatto, ottenuto {risultato}"
conn.close()

print("\n########## CASO 3: Llama3.1 locale - fallimento totale (nessuna tabella) ##########")
conn, cursor, nomi_sorgente, nome_target = nuovo_caso()
query_fallita = """
CREATE TEMP TABLE conversioni_valuta AS
SELECT 'EUR' AS valuta, 1.0 AS conversione_eur_gbp, 0.0086 AS conversione_eur_jpy;

CREATE TEMP TABLE tabella_finale AS
SELECT
  Modello_PC,
  1 AS Prezzo_Medio_USD
FROM tabella_che_non_esiste;
"""
tabelle = esegui_e_stampa(cursor, query_fallita)
risultato = valuta_accuratezza(cursor, tabelle, nome_target)
stampa_valutazione(risultato)
assert not risultato["esatto"] and risultato["f1"] == 0.0 and risultato["errore"] is not None
conn.close()

print("\n########## CASO 4: righe in ordine diverso - deve comunque valere 100% ##########")
conn, cursor, nomi_sorgente, nome_target = nuovo_caso()
query_ordine_diverso = """
CREATE TEMP TABLE step_2 AS
SELECT 'PC_Zeta' AS Modello_PC, 1356.875 AS Prezzo_Medio_USD UNION ALL
SELECT 'PC_Epsilon', 703.125 UNION ALL
SELECT 'PC_Delta', 2214.0 UNION ALL
SELECT 'PC_Gamma', 975.0 UNION ALL
SELECT 'PC_Beta', 1046.875 UNION ALL
SELECT 'PC_Alfa', 1188.0;
"""
tabelle = esegui_e_stampa(cursor, query_ordine_diverso)
risultato = valuta_accuratezza(cursor, tabelle, nome_target)
stampa_valutazione(risultato)
assert risultato["esatto"] and risultato["f1"] == 1.0, f"L'ordine delle righe non dovrebbe contare, ottenuto {risultato}"
conn.close()

print("\n########## CASO 4b: superinsieme del target (righe in piu') - NON deve risultare esatto ##########")
conn, cursor, nomi_sorgente, nome_target = nuovo_caso()
query_superinsieme = """
CREATE TEMP TABLE risultato AS
SELECT 'PC_Alfa' AS Modello_PC, 1188.0 AS Prezzo_Medio_USD UNION ALL
SELECT 'PC_Beta', 1046.875 UNION ALL
SELECT 'PC_Gamma', 975.0 UNION ALL
SELECT 'PC_Delta', 2214.0 UNION ALL
SELECT 'PC_Epsilon', 703.125 UNION ALL
SELECT 'PC_Zeta', 1356.875 UNION ALL
SELECT 'PC_Extra_1', 1.0 UNION ALL
SELECT 'PC_Extra_2', 2.0 UNION ALL
SELECT 'PC_Extra_3', 3.0 UNION ALL
SELECT 'PC_Extra_4', 4.0 UNION ALL
SELECT 'PC_Extra_5', 5.0 UNION ALL
SELECT 'PC_Extra_6', 6.0;
"""
tabelle = esegui_e_stampa(cursor, query_superinsieme)
risultato = valuta_accuratezza(cursor, tabelle, nome_target)
stampa_valutazione(risultato)
assert not risultato["esatto"], "Un superinsieme del target non deve contare come esatto"
assert risultato["richiamo"] == 1.0 and risultato["precisione"] == 0.5, f"Attesi richiamo 100% e precisione 50%, ottenuto {risultato}"
conn.close()

print("\n########## CASO 5: nomi tabelle/target letti dal caso, non hardcoded ##########")
conn, cursor, nomi_sorgente, nome_target = nuovo_caso()
assert nomi_sorgente == ["VENDITE_PC"], f"nomi_sorgente inatteso: {nomi_sorgente}"
assert nome_target == "TABELLA_FINALE_TARGET", f"nome_target inatteso: {nome_target}"
conn.close()

print("\n########## CASO 6: ragionamento <thought>/<think> con bozze SQL - va ignorato ##########")
for tag in ("thought", "think"):
    risposta = (
        f"<{tag}>Provo prima questo:\n```sql\nCREATE TEMP TABLE bozza AS SELECT 1;\n```\nNo, meglio altro.</{tag}>"
        "Ecco la soluzione:\n```sql\nCREATE TEMP TABLE finale AS SELECT 2;\n```"
    )
    estratta = estrai_query_sql(risposta)
    assert "bozza" not in estratta and "finale" in estratta, f"<{tag}>: estratto anche il ragionamento: {estratta!r}"

print("\nTUTTI I TEST SONO PASSATI.")
