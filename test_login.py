# dump_db.py
import sqlite3
import csv

DB = "instance/safichain.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = [r[0] for r in cur.fetchall()]

for t in tables:
    print("\n==== TABLE:", t, "====")
    cur.execute(f"PRAGMA table_info('{t}')")
    cols = [c[1] for c in cur.fetchall()]
    print("COLUMNS:", cols)
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print("ROWS:", cur.fetchone()[0])

    cur.execute(f"SELECT * FROM {t} LIMIT 20")
    rows = cur.fetchall()
    if rows:
        print("Sample rows:")
        for r in rows:
            print(r)
    else:
        print("No rows.")
conn.close()









