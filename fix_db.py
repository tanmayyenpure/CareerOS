"""
One-off script to add the missing columns to the `users` table.
Run this once: python fix_db.py
Then delete it — it doesn't need to be part of the app.
"""
import pymysql
from config import Config

conn = pymysql.connect(
    host=Config.MYSQL_HOST,
    user=Config.MYSQL_USER,
    password=Config.MYSQL_PASSWORD,   # now pulled from .env, same as app.py
    database=Config.MYSQL_DB,
)

# Each column is added individually and wrapped so that if a column
# already exists (e.g. you re-run this script), it won't crash the rest.
columns_to_add = [
    "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN is_pro BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN created_at DATETIME",
    "ALTER TABLE users ADD COLUMN chat_count_today INT DEFAULT 0",
    "ALTER TABLE users ADD COLUMN chat_count_date DATE",
    "ALTER TABLE users ADD COLUMN pro_expires_at DATETIME",
    "ALTER TABLE users ADD COLUMN phone VARCHAR(30)",
    "ALTER TABLE users ADD COLUMN location VARCHAR(120)",
    "ALTER TABLE users ADD COLUMN linkedin VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN github VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN resume_filename VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN resume_score INT",
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
    
    columns_to_add = [
    "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN is_pro BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN created_at DATETIME",
    "ALTER TABLE users ADD COLUMN chat_count_today INT DEFAULT 0",
    "ALTER TABLE users ADD COLUMN chat_count_date DATE",
    "ALTER TABLE users ADD COLUMN pro_expires_at DATETIME",
    "ALTER TABLE users ADD COLUMN phone VARCHAR(30)",
    "ALTER TABLE users ADD COLUMN location VARCHAR(120)",
    "ALTER TABLE users ADD COLUMN linkedin VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN github VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN resume_filename VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN resume_score INT",
]