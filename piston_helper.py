"""
Piston code-execution helper (https://github.com/engineer-man/piston).

Uses the free public instance at emkc.org — no API key needed, but it's a
shared, rate-limited service (roughly 5 requests/sec across everyone using
it), so this is fine for a hobby app but don't hammer it in a tight loop.
If you outgrow it later, self-host Piston (docker-compose one-liner in
their repo) and just change PISTON_BASE below — nothing else in app.py
needs to change.

Drop this file next to app.py (same folder as youtube_helper.py) and:
    from piston_helper import run_code, list_supported_languages, PistonError
"""

import requests

PISTON_BASE = "https://emkc.org/api/v2/piston"

# Fallback map used only if the /runtimes call fails (e.g. no network at
# startup). Keys are the language names this app offers in the dropdown.
_FALLBACK_VERSIONS = {
    "python": "3.10.0",
    "javascript": "18.15.0",
    "typescript": "5.0.3",
    "cpp": "10.2.0",
    "c": "10.2.0",
    "java": "15.0.2",
    "csharp": "6.12.0",
    "go": "1.16.2",
    "ruby": "3.0.1",
    "php": "8.2.3",
    "rust": "1.68.2",
    "kotlin": "1.8.20",
    "swift": "5.3.3",
    "sql": "3.36.0",  # Piston runs this via 'sqlite3'
}

# Piston needs a filename per language; for Java the public class in the
# starter code MUST be named "Main" to match Main.java.
_FILE_NAMES = {
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "cpp": "main.cpp",
    "c": "main.c",
    "java": "Main.java",
    "csharp": "main.cs",
    "go": "main.go",
    "ruby": "main.rb",
    "php": "main.php",
    "rust": "main.rs",
    "kotlin": "main.kt",
    "swift": "main.swift",
    "sql": "main.sql",
}

# "sql" isn't a real Piston language key — it exposes sqlite3 under this name.
_LANGUAGE_ALIASES = {
    "sql": "sqlite3",
}

_runtime_cache = None  # lazily populated {language_key: version}


class PistonError(Exception):
    """Raised when the Piston service itself can't be reached — not raised
    just because the user's code fails to compile or errors out; that's a
    normal graded result, not an exception."""
    pass


def _load_runtimes():
    global _runtime_cache
    if _runtime_cache is not None:
        return _runtime_cache

    table = {}
    try:
        resp = requests.get(f"{PISTON_BASE}/runtimes", timeout=10)
        resp.raise_for_status()
        for rt in resp.json():
            lang = rt.get("language")
            version = rt.get("version")
            if lang and version:
                table[lang] = version
            for alias in rt.get("aliases", []) or []:
                table.setdefault(alias, version)
        # map our friendly "sql" key onto whatever version sqlite3 reported
        if "sqlite3" in table:
            table.setdefault("sql", table["sqlite3"])
    except Exception as e:
        print("Piston /runtimes fetch failed, using fallback version list:", e)
        table = dict(_FALLBACK_VERSIONS)

    _runtime_cache = table
    return table


def list_supported_languages():
    """
    Returns an ordered list of language keys to show in the frontend
    dropdown: known/curated languages first (only if Piston actually
    supports them right now), then anything else Piston offers.
    """
    runtimes = _load_runtimes()
    known = [l for l in _FALLBACK_VERSIONS if l in runtimes]
    extra = sorted(l for l in runtimes if l not in _FALLBACK_VERSIONS and l != "sqlite3")
    return known + extra


def run_code(language, code, stdin="", timeout=10):
    """
    Executes `code` under Piston with `stdin` fed to it.

    Returns:
        {
          "stdout": str, "stderr": str,
          "exit_code": int | None,
          "compile_error": bool,
        }

    Raises:
        PistonError if the Piston service itself is unreachable or errors
        (network failure, bad response, unsupported language) — NOT raised
        for the user's own code failing; that comes back as a normal
        non-zero exit_code / non-empty stderr for the caller to interpret.
    """
    runtimes = _load_runtimes()
    version = runtimes.get(language)
    if not version:
        raise PistonError(f"Unsupported language: {language}")

    piston_language = _LANGUAGE_ALIASES.get(language, language)
    filename = _FILE_NAMES.get(language, "main.txt")

    payload = {
        "language": piston_language,
        "version": version,
        "files": [{"name": filename, "content": code}],
        "stdin": stdin,
        "run_timeout": timeout * 1000,
    }

    try:
        resp = requests.post(f"{PISTON_BASE}/execute", json=payload, timeout=timeout + 5)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        raise PistonError(f"Piston request failed: {e}")

    compile_step = data.get("compile") or {}
    run_step = data.get("run") or {}
    compile_code = compile_step.get("code")

    return {
        "stdout": run_step.get("stdout", "") or "",
        "stderr": (run_step.get("stderr") or compile_step.get("stderr") or ""),
        "exit_code": run_step.get("code"),
        "compile_error": compile_code not in (None, 0),
    }
