"""Suite-wide guards.

No test may ever spawn a background UI server or open a browser - the
auto-open feature honors LEADSHOOT_NO_OPEN, so pin it for every test.
Tests that exercise auto-open itself delete the env var and monkeypatch
the process/browser seams instead.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_auto_open(monkeypatch):
    monkeypatch.setenv("LEADSHOOT_NO_OPEN", "1")
