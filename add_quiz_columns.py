"""
One-off script to add the columns needed for the video-gated quiz flow
(mark video watched, score/pass a short quiz, auto-complete the
milestone on a pass). The new `milestone_quizzes` table is created
automatically by db.create_all() in app.py — this script only handles
the ALTER TABLE columns on the existing `roadmap_milestones` table,
which create_all() does NOT add on its own.

Run this once: python add_quiz_columns.py
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
    "ALTER TABLE roadmap_milestones ADD COLUMN video_watched BOOLEAN DEFAULT FALSE",
    "ALTER TABLE roadmap_milestones ADD COLUMN quiz_score INT",
    "ALTER TABLE roadmap_milestones ADD COLUMN quiz_total INT",
    "ALTER TABLE roadmap_milestones ADD COLUMN quiz_attempts INT DEFAULT 0",
    "ALTER TABLE roadmap_milestones ADD COLUMN quiz_passed BOOLEAN DEFAULT FALSE",
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
    print("\nDone. Restart your Flask app now — it will also auto-create the")
    print("new `milestone_quizzes` table via db.create_all() on startup.")
finally:
    conn.close()
