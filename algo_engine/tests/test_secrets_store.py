"""Tests for the bot's encrypted credential store.

These pin the properties that make it worth having at all: the ciphertext on
disk must not contain the secret, a wrong password must fail loudly rather than
silently returning garbage, and the UI-facing view must never expose the value.
"""
from __future__ import annotations

import pytest

from algo_engine.carry_bot.secrets_store import (
    HAVE_CRYPTO,
    SecretsStore,
    SecretsUnavailable,
    mask,
    resolve_runtime_config,
)

pytestmark = pytest.mark.skipif(not HAVE_CRYPTO, reason="cryptography not installed")

SAMPLE = {"venue": "bingx-demo", "api_key": "MYKEY-1234567890",
          "api_secret": "MYSECRET-abcdefghij", "capital": 200.0,
          "slots": 3, "leverage": 1.0}


def test_round_trip(tmp_path):
    store = SecretsStore(str(tmp_path / "cfg.enc"), password="hunter2")
    store.save(SAMPLE)
    assert store.load() == SAMPLE


def test_ciphertext_does_not_contain_the_secret(tmp_path):
    path = tmp_path / "cfg.enc"
    SecretsStore(str(path), password="hunter2").save(SAMPLE)
    blob = path.read_bytes()
    assert b"MYSECRET-abcdefghij" not in blob
    assert b"MYKEY-1234567890" not in blob


def test_wrong_password_fails_loudly(tmp_path):
    path = tmp_path / "cfg.enc"
    SecretsStore(str(path), password="right").save(SAMPLE)
    with pytest.raises(SecretsUnavailable):
        SecretsStore(str(path), password="wrong").load()


def test_no_password_refuses_instead_of_writing_plaintext(tmp_path):
    store = SecretsStore(str(tmp_path / "cfg.enc"), password="")
    assert not store.available()
    with pytest.raises(SecretsUnavailable):
        store.save(SAMPLE)
    assert not (tmp_path / "cfg.enc").exists()


def test_each_save_uses_a_fresh_salt(tmp_path):
    path = tmp_path / "cfg.enc"
    store = SecretsStore(str(path), password="hunter2")
    store.save(SAMPLE)
    first = path.read_bytes()
    store.save(SAMPLE)
    assert path.read_bytes() != first        # identical plaintext, different bytes


def test_redacted_never_exposes_the_secret(tmp_path):
    store = SecretsStore(str(tmp_path / "cfg.enc"), password="hunter2")
    store.save(SAMPLE)
    view = store.redacted()
    assert view["api_secret"] != SAMPLE["api_secret"]
    assert "MYSECRET" not in str(view)
    assert view["venue"] == "bingx-demo"     # non-secret fields survive


def test_mask_shape():
    assert mask("") == "—"
    assert mask("abcd") == "••••"
    m = mask("ABCD1234567890WXYZ")
    assert m.startswith("ABCD") and m.endswith("WXYZ") and "•" in m


def test_file_permissions_are_owner_only(tmp_path):
    path = tmp_path / "cfg.enc"
    SecretsStore(str(path), password="hunter2").save(SAMPLE)
    assert (path.stat().st_mode & 0o077) == 0, "config readable by other users"


def test_env_fallback_when_store_unusable(tmp_path, monkeypatch):
    """An operator who prefers a server-side .env must still work."""
    monkeypatch.delenv("BOT_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("CARRY_VENUE", "bybit-demo")
    monkeypatch.setenv("BYBIT_API_KEY", "from-env")
    monkeypatch.setenv("BYBIT_API_SECRET", "secret-from-env")
    cfg = resolve_runtime_config(SecretsStore(str(tmp_path / "none.enc"), password=""))
    assert cfg["api_key"] == "from-env"
    assert cfg["source"] == "environment"


def test_store_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BINGX_API_KEY", "from-env")
    store = SecretsStore(str(tmp_path / "cfg.enc"), password="hunter2")
    store.save(SAMPLE)
    cfg = resolve_runtime_config(store)
    assert cfg["api_key"] == SAMPLE["api_key"]
    assert cfg["source"] == "encrypted-store"
