"""
One-off script to add the new resource_title / resource_channel columns
to `roadmap_milestones` (needed after wiring up real YouTube video links).
Run this once: python add_video_columns.py
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
    "ALTER TABLE roadmap_milestones ADD COLUMN resource_title VARCHAR(255)",
    "ALTER TABLE roadmap_milestones ADD COLUMN resource_channel VARCHAR(255)",
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
