"""Agent-facing surfaces: JSON CLI mode and MCP server shape. No network."""

import json

import pytest
from typer.testing import CliRunner

from leadshoot.cli import app
from leadshoot.store import Store

runner = CliRunner()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "agent.db")
    store = Store(path)
    store.upsert_business({
        "id": "n1", "name": "Test Dental", "category": "dentist",
        "osm_tags": "amenity=dentist", "phone": "+1-503-555-0100",
        "email": None, "address": "1 Main St", "lat": 45.5, "lon": -122.6,
        "osm_website": "https://test.example", "area": "portland, or",
    })
    store.save_check("n1", "broken", 500, None, None, None,
                     ["broken_site"], "verified", 95)
    store.conn.commit()
    store.close()
    return path


def _json_out(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestJsonCLI:
    def test_options_is_json(self, db):
        data = _json_out(runner.invoke(app, ["options", "--db", db]))
        assert "dentist" in data["categories"]
        assert "website_design" in data["services"]
        assert "broken_site" in data["gaps"]

    def test_status_is_json(self, db):
        data = _json_out(runner.invoke(app, ["status", "--db", db]))
        assert data["businesses"] == 1

    def test_leads_json(self, db):
        data = _json_out(runner.invoke(app, ["leads", "--json", "--db", db]))
        assert data["count"] == 1
        assert data["leads"][0]["gap_flags"] == "broken_site"

    def test_mark_json_roundtrip(self, db):
        data = _json_out(runner.invoke(
            app, ["mark", "n1", "--stage", "contacted", "--json", "--db", db]))
        assert data["ok"] is True
        data = _json_out(runner.invoke(
            app, ["leads", "--stage", "contacted", "--json", "--db", db]))
        assert data["count"] == 1

    def test_mark_json_error_shape(self, db):
        result = runner.invoke(
            app, ["mark", "nope", "--stage", "contacted", "--json", "--db", db])
        assert result.exit_code == 1
        assert json.loads(result.output)["ok"] is False

    def test_icp_new_and_list_json(self, db):
        data = _json_out(runner.invoke(app, [
            "icp", "new", "--name", "t", "--area", "Portland, OR",
            "--categories", "dentist,cafe", "--service", "redesign",
            "--json", "--db", db,
        ]))
        assert data["ok"] is True
        assert "not_mobile" in data["icp"]["weights"]
        listed = _json_out(runner.invoke(app, ["icp", "list", "--json",
                                               "--db", db]))
        assert listed[0]["name"] == "t"

    def test_icp_new_invalid_category_json(self, db):
        result = runner.invoke(app, [
            "icp", "new", "--name", "t", "--area", "x",
            "--categories", "spaceport", "--json", "--db", db,
        ])
        assert result.exit_code == 1
        assert json.loads(result.output)["ok"] is False


class TestMCPShape:
    def test_tools_and_http_config(self, db):
        import asyncio

        from leadshoot.mcp_server import build_server

        server = build_server(db, host="127.0.0.1", port=9999)
        tools = {t.name for t in asyncio.run(server.list_tools())}
        assert {"status", "list_options", "save_icp", "list_icps",
                "find_leads", "list_leads", "update_lead", "recheck",
                "export_leads"} <= tools
        assert server.settings.port == 9999
