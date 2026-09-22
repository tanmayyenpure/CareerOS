import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

# Load variables from .env
load_dotenv()

# Install PyMySQL as MySQLdb for broad SQLAlchemy MySQL compatibility
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except (ImportError, AttributeError):
    pass


def is_production():
    return (
        os.getenv("VERCEL") == "1"
        or os.getenv("FLASK_ENV") == "production"
        or os.getenv("CAREEROS_ENV") == "production"
    )


def _normalize_database_url(url):
    """Normalize common hosted database URL schemes to SQLAlchemy-compatible drivers."""
    if not url:
        return url
    url = url.strip()
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://"):]
    if url.startswith("mysql2://"):
        return "mysql+pymysql://" + url[len("mysql2://"):]
    if url.startswith("mysql+mysqldb://"):
        return "mysql+pymysql://" + url[len("mysql+mysqldb://"):]
    if url.startswith("mysql+mysqlconnector://"):
        return "mysql+pymysql://" + url[len("mysql+mysqlconnector://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def build_database_uri():
    # 1. Production / cloud database URL (Vercel, PlanetScale, Neon, AWS RDS, etc.)
    url = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL") or os.getenv("POSTGRES_URL")
    if url:
        return _normalize_database_url(url)

    # 2. Local development: MySQL / XAMPP configuration
    mysql_host = os.getenv("MYSQL_HOST", "localhost")
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_password = os.getenv("MYSQL_PASSWORD", "")
    mysql_port = os.getenv("MYSQL_PORT", "3306")
    mysql_db = os.getenv("MYSQL_DB", "application")

    password_part = f":{quote_plus(mysql_password)}" if mysql_password else ""
    return f"mysql+pymysql://{quote_plus(mysql_user)}{password_part}@{mysql_host}:{mysql_port}/{mysql_db}"


def _engine_options():
    options = {"pool_pre_ping": True}
    if is_production() or os.getenv("VERCEL") == "1":
        options["poolclass"] = NullPool
    else:
        options["pool_recycle"] = 300
    options["connect_args"] = {"connect_timeout": 5}
    return options


class Config:
    # ── DATABASE ──
    SQLALCHEMY_DATABASE_URI = build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options()

    # Legacy attributes for scripts that access them directly
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306")) if os.getenv("MYSQL_PORT") else 3306
    MYSQL_DB = os.getenv("MYSQL_DB", "application")

    # ── FLASK ──
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        if is_production():
            SECRET_KEY = None  # Enforced at startup in production
        else:
            SECRET_KEY = "careeros-dev-secret-key-change-in-prod"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = is_production()
    PREFERRED_URL_SCHEME = "https" if is_production() else "http"

    # ── EMAIL (OTP) ──
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER") or MAIL_USERNAME

    # ── AI PROVIDERS ──
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
    ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

    # ── YOUTUBE ──
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

    # ── PAYMENTS (RAZORPAY) ──
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    # ── UPLOAD LIMITS ──
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(8 * 1024 * 1024)))