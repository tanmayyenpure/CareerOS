   
import os
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()


class Config:
    # ── DATABASE ──
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")  # no default — must come from .env
    MYSQL_DB = os.getenv("MYSQL_DB", "application")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── FLASK ──
    SECRET_KEY = os.getenv("SECRET_KEY")

    # ── EMAIL (OTP) ──
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")

    # ── AI (renamed to match what app.py actually reads) ──
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
    ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
    # ── YOUTUBE (real video links for roadmap/pathfinder resources) ──
    # Optional: if unset, youtube_helper.py falls back to a YouTube search
    # results link instead of a specific video — app still works fine.
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


REQUIRED_VARS = [
    "MYSQL_PASSWORD", "SECRET_KEY", "MAIL_USERNAME", "MAIL_PASSWORD",
    "OPENROUTER_API_KEY", "GEMINI_API_KEY",
]
# YOUTUBE_API_KEY is intentionally NOT required — see note above.

missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    print(f"WARNING: missing .env values: {', '.join(missing)} — related features will fail.")