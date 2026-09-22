import os
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
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


def _get_raw_database_url():
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("POSTGRES_PRISMA_URL")
        or os.getenv("MYSQL_URL")
        or ""
    ).strip()


def _normalize_database_url(url):
    """Normalize common hosted database URL schemes to SQLAlchemy-compatible drivers."""
    if not url:
        return url
    url = url.strip()
    if url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    elif url.startswith("mysql2://"):
        url = "mysql+pymysql://" + url[len("mysql2://"):]
    elif url.startswith("mysql+mysqldb://"):
        url = "mysql+pymysql://" + url[len("mysql+mysqldb://"):]
    elif url.startswith("mysql+mysqlconnector://"):
        url = "mysql+pymysql://" + url[len("mysql+mysqlconnector://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]

    # For PyMySQL connections, strip unsupported SSL query parameters from the URL.
    # PyMySQL does not accept 'ssl_mode', 'ssl-mode', 'sslmode', or 'ssl=true' as kwargs
    # from SQLAlchemy's URL query string parser (causes TypeError or AttributeError).
    # SSL for PyMySQL is configured cleanly via SQLAlchemy connect_args instead.
    if url.startswith(("mysql+pymysql://", "mysql://")):
        try:
            parts = urlsplit(url)
            if parts.query:
                unsupported_keys = {
                    "ssl-mode", "ssl_mode", "sslmode",
                    "ssl",
                    "ssl-ca", "ssl_ca", "ca", "sslrootcert",
                    "ssl-cert", "ssl_cert", "sslcert",
                    "ssl-key", "ssl_key", "sslkey",
                    "ssl-cipher", "ssl_cipher",
                }
                qsl = parse_qsl(parts.query, keep_blank_values=True)
                filtered_qsl = [(k, v) for k, v in qsl if k.lower() not in unsupported_keys]
                url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered_qsl), parts.fragment))
        except Exception:
            pass

    return url


def _get_mysql_ssl_config(raw_url=None):
    """
    Determine whether SSL/TLS should be enabled for PyMySQL, and construct
    the exact SSL dictionary accepted by PyMySQL.
    Does NOT pass unsupported keywords (like ssl_mode) to PyMySQL.
    """
    if raw_url is None:
        raw_url = _get_raw_database_url()

    host = ""
    query_params = {}

    if raw_url:
        try:
            parts = urlsplit(raw_url)
            host = (parts.hostname or "").lower()
            if parts.query:
                for k, v in parse_qsl(parts.query, keep_blank_values=True):
                    query_params[k.lower()] = v
        except Exception:
            pass

    if not host:
        host = (os.getenv("MYSQL_HOST") or "").strip().lower()

    # Determine requested SSL mode / flag
    ssl_mode_val = (
        query_params.get("ssl-mode")
        or query_params.get("ssl_mode")
        or query_params.get("sslmode")
        or os.getenv("MYSQL_SSL_MODE")
        or ""
    ).strip().lower()

    ssl_val = query_params.get("ssl") or os.getenv("MYSQL_SSL") or ""
    ssl_val = str(ssl_val).strip().lower()

    # Explicitly disabled
    if (
        ssl_mode_val in ("disabled", "disable", "none", "0", "false", "off")
        or ssl_val in ("disabled", "disable", "none", "0", "false", "off")
    ):
        return None

    is_localhost = host in ("localhost", "127.0.0.1", "::1", "")
    is_aiven = "aivencloud.com" in host or "aiven" in host
    explicit_ssl = bool(
        ssl_mode_val in (
            "required", "require",
            "verify_ca", "verify-ca",
            "verify_identity", "verify-identity", "verify-full",
            "preferred", "prefer",
            "1", "true", "yes",
        )
        or ssl_val in ("required", "require", "1", "true", "yes")
    )

    # Local development: do NOT enable SSL unless explicitly requested
    if is_localhost and not explicit_ssl:
        return None

    # Enable SSL if explicitly requested, or if hosted on Aiven, or on Vercel with remote MySQL
    should_use_ssl = explicit_ssl or is_aiven or (os.getenv("VERCEL") == "1" and not is_localhost)
    if not should_use_ssl:
        return None

    # Default SSL configuration for PyMySQL (equivalent to MySQL ssl-mode=REQUIRED):
    # Enforces TLS encryption without rejecting internal/cloud CAs.
    ssl_dict = {
        "check_hostname": False,
        "verify_mode": "none",
    }

    # If CA certificate is provided, resolve and configure it
    ca_path = (
        query_params.get("ssl_ca")
        or query_params.get("ssl-ca")
        or query_params.get("ca")
        or os.getenv("MYSQL_SSL_CA")
        or os.getenv("AIVEN_CA_CERT")
        or os.getenv("CA_CERT")
    )

    # Check for inline CA certificate text
    ca_content = (
        os.getenv("AIVEN_CA_CERT_DATA")
        or os.getenv("MYSQL_SSL_CA_DATA")
        or os.getenv("MYSQL_SSL_CA_CONTENT")
    )
    if not ca_path and ca_content and "-----BEGIN CERTIFICATE-----" in ca_content:
        target_dir = "/tmp" if os.name != "nt" else os.getenv("TEMP", ".")
        temp_ca_path = os.path.join(target_dir, "careeros-aiven-ca.pem")
        try:
            with open(temp_ca_path, "w", encoding="utf-8") as f:
                f.write(ca_content.strip())
            ca_path = temp_ca_path
        except Exception:
            pass

    # Check for root ca.pem or aiven-ca.pem in project root
    if not ca_path:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        for candidate in ("ca.pem", "aiven-ca.pem"):
            candidate_path = os.path.join(root_dir, candidate)
            if os.path.isfile(candidate_path):
                ca_path = candidate_path
                break

    if ca_path and os.path.isfile(ca_path):
        ssl_dict["ca"] = ca_path
        if ssl_mode_val in ("verify_identity", "verify-identity", "verify-full"):
            ssl_dict["check_hostname"] = True
            ssl_dict["verify_mode"] = "required"
        elif ssl_mode_val in ("verify_ca", "verify-ca"):
            ssl_dict["check_hostname"] = False
            ssl_dict["verify_mode"] = "required"

    return ssl_dict


def build_database_uri():
    # 1. Production / cloud database URL (Vercel, PlanetScale, Neon, AWS RDS, etc.)
    raw_url = _get_raw_database_url()
    if raw_url:
        return _normalize_database_url(raw_url)

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

    uri = build_database_uri()
    connect_args = options.setdefault("connect_args", {})
    connect_args.setdefault("connect_timeout", 10)

    if uri.startswith(("mysql+pymysql", "mysql:")):
        ssl_config = _get_mysql_ssl_config()
        if ssl_config is not None:
            connect_args["ssl"] = ssl_config

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