"""Auto-open live map: `find` shows the session in a browser, hands-free.

One background `leadshoot serve` per database, started on demand and reused
by every later command. The map is reactive (SSE over the change token), so
whoever opened it watches pins land as each check commits - the engine
itself never talks to the UI.

Opt out per call with --no-open, or globally with LEADSHOOT_NO_OPEN=1
(set it in CI and on headless boxes).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import httpx

NO_OPEN_ENV = "LEADSHOOT_NO_OPEN"
PORTS = range(8321, 8332)          # deterministic scan order
_READY_TIMEOUT = 10.0


def resolve_db(db: str | os.PathLike | None) -> str:
    """Absolute path of the database this session works on - the spawned
    server gets it explicitly so cwd never matters."""
    from .store import DEFAULT_DB

    return str(Path(db or os.environ.get("LEADSHOOT_DB", DEFAULT_DB))
               .expanduser().resolve())


def probe(port: int, db_abs: str, timeout: float = 0.5) -> str:
    """'ours' = a LeadShoot server on this port serving db_abs;
    'other' = the port is taken (anything else, including another db);
    'free' = nothing listens."""
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=timeout)
    except httpx.ConnectError:
        return "free"
    except httpx.HTTPError:
        return "other"
    try:
        body = r.json()
    except ValueError:
        return "other"
    if (r.status_code == 200 and isinstance(body, dict)
            and "businesses" in body and body.get("db")
            and str(Path(str(body["db"])).expanduser().resolve()) == db_abs):
        return "ours"
    return "other"


def _pidfile(port: int) -> Path:
    return Path(tempfile.gettempdir()) / f"leadshoot-ui-{port}.pid"


def _logfile(port: int) -> Path:
    return Path(tempfile.gettempdir()) / f"leadshoot-ui-{port}.log"


def _spawn(port: int, db_abs: str) -> bool:
    """Start a detached `leadshoot serve` and wait until it answers."""
    kwargs: dict = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:  # pragma: no cover - windows detach flags
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x8)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    with open(_logfile(port), "ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "leadshoot", "serve",
             "--port", str(port), "--host", "127.0.0.1",
             "--db", db_abs, "--no-open"],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, **kwargs)
    deadline = time.monotonic() + _READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False               # died at startup - see the log
        if probe(port, db_abs) == "ours":
            _pidfile(port).write_text(str(proc.pid))
            return True
        time.sleep(0.25)
    return False


def ensure_ui(db: str | None, *, open_browser: bool = True,
              echo=None) -> str | None:
    """Make sure a live map for this db is up; open the browser at it.

    Returns the URL, or None when skipped (env opt-out, server extras not
    installed, or no port available). Never raises - the pipeline must not
    fail because a browser could not open.
    """
    say = echo or (lambda _msg: None)
    if os.environ.get(NO_OPEN_ENV):
        return None
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        say("live map skipped - install the UI: pip install 'leadshoot[server]'")
        return None
    db_abs = resolve_db(db)
    try:
        for port in PORTS:
            state = probe(port, db_abs)
            if state == "other":
                continue
            if state == "free" and not _spawn(port, db_abs):
                say(f"live map failed to start - log: {_logfile(port)}")
                return None
            url = f"http://127.0.0.1:{port}"
            if open_browser:
                webbrowser.open(url)
            return url
        say("live map skipped - ports 8321-8331 all busy")
        return None
    except Exception as e:  # noqa: BLE001 - UI is best-effort, never fatal
        say(f"live map skipped - {e}")
        return None


def stop_ui(db: str | None, echo=None) -> bool:
    """Stop the background server for this db (the one auto-open started)."""
    import signal

    say = echo or (lambda _msg: None)
    db_abs = resolve_db(db)
    for port in PORTS:
        if probe(port, db_abs) != "ours":
            continue
        pidfile = _pidfile(port)
        if not pidfile.exists():
            say(f"map on :{port} runs in a foreground `leadshoot serve` - "
                "stop it in its own terminal (Ctrl+C)")
            return False
        try:
            os.kill(int(pidfile.read_text().strip()), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass
        pidfile.unlink(missing_ok=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if probe(port, db_abs) == "free":
                break
            time.sleep(0.2)
        say(f"stopped live map on :{port}")
        return True
    say("no live map running for this database")
    return False
