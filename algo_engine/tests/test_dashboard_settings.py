"""End-to-end tests for the bot's settings web UI (real HTTP, localhost).

What must hold: the page is closed without the admin password, a saved secret
is never echoed back to the browser, a blank field keeps the stored value, and
the single-slot configuration that backtested negative is rejected.
"""
from __future__ import annotations

import base64
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from algo_engine.carry_bot import dashboard
from algo_engine.carry_bot.secrets_store import HAVE_CRYPTO, SecretsStore

pytestmark = pytest.mark.skipif(not HAVE_CRYPTO, reason="cryptography not installed")

PASSWORD = "test-admin-password"
PORT = 8477


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_ADMIN_PASSWORD", PASSWORD)
    store_path = str(tmp_path / "cfg.enc")
    monkeypatch.setattr(dashboard, "SecretsStore",
                        lambda *a, **kw: SecretsStore(store_path, password=PASSWORD))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), dashboard.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    yield f"http://127.0.0.1:{PORT}", store_path
    srv.shutdown()


def _auth_header(password: str = PASSWORD) -> dict:
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=5)


def _post(url: str, fields: dict, headers: dict | None = None):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    return urllib.request.urlopen(req, timeout=5)


def test_settings_closed_without_password(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/settings")
    assert exc.value.code == 401


def test_settings_rejects_wrong_password(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/settings", _auth_header("not-the-password"))
    assert exc.value.code == 401


def test_settings_opens_with_password(server):
    base, _ = server
    resp = _get(f"{base}/settings", _auth_header())
    assert resp.status == 200
    assert b"API key" in resp.read()


def test_save_then_secret_is_never_echoed(server):
    base, store_path = server
    _post(f"{base}/settings", {
        "venue": "bingx-demo", "api_key": "LIVE-KEY-ABCDEFGH",
        "api_secret": "LIVE-SECRET-ZYXWVUT",
        "capital": "250", "slots": "3", "leverage": "1",
    }, _auth_header())

    stored = SecretsStore(store_path, password=PASSWORD).load()
    assert stored["api_secret"] == "LIVE-SECRET-ZYXWVUT"      # it really saved

    body = _get(f"{base}/settings", _auth_header()).read().decode()
    assert "LIVE-SECRET-ZYXWVUT" not in body                  # but never comes back
    assert "LIVE-KEY-ABCDEFGH" not in body


def test_blank_field_keeps_the_stored_secret(server):
    base, store_path = server
    _post(f"{base}/settings", {
        "venue": "bingx-demo", "api_key": "K1", "api_secret": "S1",
        "capital": "200", "slots": "2", "leverage": "1",
    }, _auth_header())
    _post(f"{base}/settings", {
        "venue": "bingx-demo", "api_key": "", "api_secret": "",
        "capital": "500", "slots": "2", "leverage": "1",
    }, _auth_header())

    stored = SecretsStore(store_path, password=PASSWORD).load()
    assert stored["api_secret"] == "S1"      # kept
    assert stored["capital"] == 500.0        # non-secret field updated


def test_single_slot_is_rejected(server):
    base, store_path = server
    resp = _post(f"{base}/settings", {
        "venue": "bybit-demo", "api_key": "K", "api_secret": "S",
        "capital": "200", "slots": "1", "leverage": "1",
    }, _auth_header())
    assert b"slots must be 2 or more" in resp.read()
    assert not SecretsStore(store_path, password=PASSWORD).exists()


def test_dashboard_itself_stays_open(server):
    """Read-only monitoring must not require the admin password."""
    base, _ = server
    assert _get(f"{base}/").status == 200
    assert _get(f"{base}/api/state").status == 200
