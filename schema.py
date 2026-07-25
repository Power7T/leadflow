import sqlite3
conn = sqlite3.connect('/Users/chandan/leadflow/leadflow.db')
cursor = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table';")
for row in cursor:
    print(f"Table: {row[0]}\n{row[1]}\n")
