"""
One-off script to add the new schema_version column to
`learning_hub_material` (needed so old cached rows generated before
notes/video enrichment existed get treated as stale and regenerated).
Run this once: python add_hub_material_schema_version_column.py
Then delete it — it doesn't need to be part of the app.
"""
import pymysql
from config import Config

conn = pymysql.connect(
    host=Config.MYSQL_HOST,
    user=Config.MYSQL_USER,
    password=Config.MYSQL_PASSWORD,
    database=Config.MYSQL_DB,
)

columns_to_add = [
    "ALTER TABLE learning_hub_material ADD COLUMN schema_version INT DEFAULT 1",
]

try:
    with conn.cursor() as cursor:
        for stmt in columns_to_add:
            try:
                cursor.execute(stmt)
                print(f"OK: {stmt}")
            except pymysql.err.OperationalError as e:
                # 1060 = Duplicate column name -> already added, safe to skip
                if e.args[0] == 1060:
                    print(f"SKIP (already exists): {stmt}")
                else:
                    raise
    conn.commit()
    print("\nDone. Restart your Flask app now.")
finally:
    conn.close()
