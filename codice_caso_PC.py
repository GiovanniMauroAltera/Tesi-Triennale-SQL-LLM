import os
import sqlite3

from funzioni_comuni import crea_dataset_demo

CARTELLA_CASI = "caso_PC"
PERCORSO_DB = os.path.join(CARTELLA_CASI, "pc_multivaluta.sqlite")


def genera():
    os.makedirs(CARTELLA_CASI, exist_ok=True)
    if os.path.exists(PERCORSO_DB):
        os.remove(PERCORSO_DB)

    conn = sqlite3.connect(PERCORSO_DB)
    cursor = conn.cursor()

    crea_dataset_demo(cursor)

    cursor.execute("CREATE TABLE _caso_info (tabelle_sorgente TEXT, tabella_target TEXT)")
    cursor.execute("INSERT INTO _caso_info VALUES (?, ?)", ("VENDITE_PC", "TABELLA_FINALE_TARGET"))
    conn.commit()
    conn.close()
    print(f"Caso demo generato: {PERCORSO_DB}")


if __name__ == "__main__":
    genera()
