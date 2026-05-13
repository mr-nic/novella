# migrate_add_posted.py
# Run once from the Novella project root:
#   python migrate_add_posted.py
#
# Safe to run multiple times — skips columns that already exist.

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "novella.db")

MIGRATIONS = [
    ("buyer_email",         "ALTER TABLE books ADD COLUMN buyer_email TEXT DEFAULT ''"),
    ("tracking_reference",  "ALTER TABLE books ADD COLUMN tracking_reference TEXT DEFAULT ''"),
    ("posted_at",           "ALTER TABLE books ADD COLUMN posted_at DATETIME"),
]

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

existing = {row[1] for row in cursor.execute("PRAGMA table_info(books)")}

for col_name, sql in MIGRATIONS:
    if col_name in existing:
        print(f"  skip  {col_name} (already exists)")
    else:
        cursor.execute(sql)
        print(f"  added {col_name}")

conn.commit()
conn.close()
print("Done.")
