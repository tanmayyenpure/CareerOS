"""
One-off migration for the Career Center "make it dynamic" upgrade.

Adds:
  - jobs.source, jobs.external_id, jobs.apply_url   (live Adzuna sync)
  - skills.created_at                               (skills-growth chart)
  - applications.match_pct_at_apply, applications.last_progressed_at
  - new tables: notifications, interview_coach_sessions, skill_snapshots

Run this once: python migrate_career_center_v2.py
Then restart your Flask app (app.py's `db.create_all()` will create the
brand-new tables; this script only handles ALTER TABLE on existing ones,
same pattern as fix_db.py).
"""
import pymysql
from config import Config

conn = pymysql.connect(
    host=Config.MYSQL_HOST,
    user=Config.MYSQL_USER,
    password=Config.MYSQL_PASSWORD,
    database=Config.MYSQL_DB,
)

alter_statements = [
    "ALTER TABLE jobs ADD COLUMN source VARCHAR(20) DEFAULT 'internal'",
    "ALTER TABLE jobs ADD COLUMN external_id VARCHAR(100)",
    "ALTER TABLE jobs ADD COLUMN apply_url VARCHAR(1000)",
    "ALTER TABLE skills ADD COLUMN created_at DATETIME",
    "ALTER TABLE applications ADD COLUMN match_pct_at_apply INT",
    "ALTER TABLE applications ADD COLUMN last_progressed_at DATETIME",
    "CREATE INDEX idx_jobs_external_id ON jobs (external_id)",
]

# Backfill existing rows with sane defaults so old data doesn't show up
# as NULL/blank in the new dynamic UI.
backfill_statements = [
    "UPDATE jobs SET source = 'internal' WHERE source IS NULL",
    "UPDATE skills SET created_at = NOW() WHERE created_at IS NULL",
    "UPDATE applications SET last_progressed_at = applied_date WHERE last_progressed_at IS NULL",
]

try:
    with conn.cursor() as cursor:
        for stmt in alter_statements:
            try:
                cursor.execute(stmt)
                print(f"OK: {stmt}")
            except pymysql.err.OperationalError as e:
                # 1060 = Duplicate column, 1061 = Duplicate key/index -> already applied
                if e.args[0] in (1060, 1061):
                    print(f"SKIP (already exists): {stmt}")
                else:
                    raise
        for stmt in backfill_statements:
            cursor.execute(stmt)
            print(f"OK (backfill): {stmt}")
    conn.commit()
    print("\nDone. Restart your Flask app now — db.create_all() will add the "
          "new notifications / interview_coach_sessions / skill_snapshots tables.")
finally:
    conn.close()
