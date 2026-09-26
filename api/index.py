from pathlib import Path
import sys

# Add parent directory to sys.path so app and its modules are found on Vercel
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app

# Expose WSGI handler for Vercel Python runtime
handler = app
