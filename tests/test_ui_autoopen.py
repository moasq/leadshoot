"""Auto-open live map: `find` must show the session in a browser by itself.

Covers the three probe states (free / other / ours), ensure_ui's safety
rails (env opt-out, reuse over respawn, port skipping), and the CLI wiring
(--no-open, the `ui` command). All sockets are localhost; nothing here
spawns a real server or browser.
"""

from __future__ import annotations

import http.server
import json
import socket
import subprocess
import sys
import threading

import pytest
from typer.testing import CliRunner

from leadshoot import ui as ui_mod
from leadshoot.cli import app
from leadshoot.store import Store

runner = CliRunner()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _http(handler) -> tuple[http.server.HTTPServer, int]:
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _status_handler(db_path: str):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"db": db_path, "businesses": 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return H


class _PlainHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"not leadshoot")

    def log_message(self, *a):
        pass


class TestProbe:
    def test_free_port(self, tmp_path):
        assert ui_mod.probe(_free_port(), str(tmp_path / "x.db")) == "free"

    def test_foreign_server_is_other(self, tmp_path):
        srv, port = _http(_PlainHandler)
        try:
            assert ui_mod.probe(port, str(tmp_path / "x.db")) == "other"
        finally:
            srv.shutdown()

    def test_matching_leadshoot_is_ours(self, tmp_path):
        db = str((tmp_path / "x.db").resolve())
        srv, port = _http(_status_handler(db))
        try:
            assert ui_mod.probe(port, db) == "ours"
        finally:
            srv.shutdown()

    def test_other_database_is_other(self, tmp_path):
        srv, port = _http(_status_handler(str(tmp_path / "a.db")))
        try:
            assert ui_mod.probe(port, str(tmp_path / "b.db")) == "other"
        finally:
            srv.shutdown()


class TestEnsureUi:
    def test_env_opt_out_touches_nothing(self, monkeypatch, tmp_path):
        # conftest sets LEADSHOOT_NO_OPEN=1 - probe/spawn must never run
        monkeypatch.setattr(ui_mod, "probe",
                            lambda *a, **k: pytest.fail("probed"))
        monkeypatch.setattr(ui_mod, "_spawn",
                            lambda *a, **k: pytest.fail("spawned"))
        assert ui_mod.ensure_ui(str(tmp_path / "x.db")) is None

    def test_reuses_running_server_no_respawn(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LEADSHOOT_NO_OPEN")
        opened = []
        monkeypatch.setattr(ui_mod, "probe", lambda p, d, **k: "ours")
        monkeypatch.setattr(ui_mod, "_spawn",
                            lambda *a, **k: pytest.fail("respawned"))
        monkeypatch.setattr(ui_mod.webbrowser, "open", opened.append)
        url = ui_mod.ensure_ui(str(tmp_path / "x.db"))
        assert url == "http://127.0.0.1:8321"
        assert opened == [url]

    def test_skips_busy_ports_deterministically(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LEADSHOOT_NO_OPEN")
        monkeypatch.setattr(
            ui_mod, "probe",
            lambda p, d, **k: "other" if p == 8321 else "ours")
        monkeypatch.setattr(ui_mod.webbrowser, "open", lambda u: True)
        assert ui_mod.ensure_ui(str(tmp_path / "x.db")) \
            == "http://127.0.0.1:8322"

    def test_spawn_failure_is_none_not_crash(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LEADSHOOT_NO_OPEN")
        monkeypatch.setattr(ui_mod, "probe", lambda p, d, **k: "free")
        monkeypatch.setattr(ui_mod, "_spawn", lambda *a, **k: False)
        notes = []
        assert ui_mod.ensure_ui(str(tmp_path / "x.db"),
                                echo=notes.append) is None
        assert notes  # the reason was surfaced, not swallowed

    def test_can_open_without_browser(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LEADSHOOT_NO_OPEN")
        monkeypatch.setattr(ui_mod, "probe", lambda p, d, **k: "ours")
        monkeypatch.setattr(ui_mod.webbrowser, "open",
                            lambda u: pytest.fail("browser opened"))
        assert ui_mod.ensure_ui(str(tmp_path / "x.db"),
                                open_browser=False) is not None


def _seed_icp(db: str) -> None:
    s = Store(db)
    s.save_icp("t", {"name": "t", "area": "Testville",
                     "categories": ["cafe"], "service": "website_design"})
    s.conn.commit()
    s.close()


class TestCliWiring:
    def test_find_calls_ensure_ui_by_default(self, monkeypatch, tmp_path):
        db = str(tmp_path / "w.db")
        _seed_icp(db)
        calls = []
        monkeypatch.setattr(ui_mod, "ensure_ui",
                            lambda *a, **k: calls.append(a) or "http://u")
        monkeypatch.setattr("leadshoot.cli.run_find", lambda *a, **k: [])
        out = runner.invoke(app, ["find", "--icp", "t", "--json", "--db", db])
        assert out.exit_code == 0
        assert len(calls) == 1
        # runners may interleave stderr notes; the JSON payload starts at {
        payload = json.loads(out.stdout[out.stdout.index("{"):])
        assert payload["live_map"] == "http://u"

    def test_find_no_open_skips_ui(self, monkeypatch, tmp_path):
        db = str(tmp_path / "w.db")
        _seed_icp(db)
        monkeypatch.setattr(ui_mod, "ensure_ui",
                            lambda *a, **k: pytest.fail("ui opened"))
        monkeypatch.setattr("leadshoot.cli.run_find", lambda *a, **k: [])
        out = runner.invoke(app, ["find", "--icp", "t", "--no-open",
                                  "--json", "--db", db])
        assert out.exit_code == 0
        payload = json.loads(out.stdout[out.stdout.index("{"):])
        assert payload["live_map"] is None

    def test_ui_command_opens(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ui_mod, "ensure_ui", lambda *a, **k: "http://m")
        out = runner.invoke(app, ["ui", "--db", str(tmp_path / "w.db")])
        assert out.exit_code == 0
        assert "http://m" in out.stdout

    def test_ui_stop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ui_mod, "stop_ui", lambda *a, **k: True)
        out = runner.invoke(app, ["ui", "--stop",
                                  "--db", str(tmp_path / "w.db")])
        assert out.exit_code == 0

    def test_serve_has_no_open_flag(self):
        assert "--no-open" in runner.invoke(app, ["serve", "--help"]).stdout

    def test_python_dash_m_entry(self):
        # the spawned server runs `sys.executable -m leadshoot serve ...`
        out = subprocess.run([sys.executable, "-m", "leadshoot", "version"],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0
        assert "leadshoot" in out.stdout
