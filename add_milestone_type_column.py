"""
One-off script to add the new milestone_type column to
`roadmap_milestones` (needed for the revision-vs-new-learning roadmap
split). Run this once: python add_milestone_type_column.py
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
    "ALTER TABLE roadmap_milestones ADD COLUMN milestone_type VARCHAR(20) DEFAULT 'new'",
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
