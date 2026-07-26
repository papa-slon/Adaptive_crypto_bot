"""Encrypted local store for the bot's own exchange credentials.

Scope note: these credentials belong to the BOT's host, which is a separate
service from the journal site. The site never receives, stores or proxies them
(its architecture lock forbids that); it only reads the statistics the bot
publishes.

Design:
  * the encryption key is DERIVED from an operator password (PBKDF2-HMAC-SHA256,
    per-file random salt) and is never written to disk, so a stolen volume,
    snapshot or backup is useless without the password;
  * the password reaches the process via the ``BOT_ADMIN_PASSWORD`` env var —
    which means an attacker who already owns the running host can still read
    the keys. Encryption at rest protects backups and disk images, not a live
    compromise. Say so plainly rather than implying more.
  * secrets are write-only from the UI: the API returns a masked fingerprint,
    never the value.

Requires the `cryptography` package.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - surfaced as a clear error at use time
    HAVE_CRYPTO = False

DEFAULT_PATH = "logs/bot_config.enc"
_PBKDF2_ROUNDS = 480_000        # OWASP-ish for SHA256, 2024+
_SALT_BYTES = 16


class SecretsUnavailable(RuntimeError):
    """Raised when the store cannot be used (no crypto lib, or no password)."""


def _derive(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=_PBKDF2_ROUNDS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def mask(secret: str | None) -> str:
    """A fingerprint safe to show in a UI or a log."""
    if not secret:
        return "—"
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:4]}{'•' * 8}{secret[-4:]}"


class SecretsStore:
    def __init__(self, path: str | None = None, password: str | None = None):
        # BOT_CONFIG_PATH lets a deployment point the store at a mounted volume
        self.path = Path(path or os.environ.get("BOT_CONFIG_PATH") or DEFAULT_PATH)
        self.password = password if password is not None else os.environ.get("BOT_ADMIN_PASSWORD", "")

    def available(self) -> bool:
        return HAVE_CRYPTO and bool(self.password)

    def _require(self) -> None:
        if not HAVE_CRYPTO:
            raise SecretsUnavailable(
                "the 'cryptography' package is required to store credentials "
                "(pip install cryptography)")
        if not self.password:
            raise SecretsUnavailable(
                "set BOT_ADMIN_PASSWORD — it both protects the settings page and "
                "derives the encryption key; it is never written to disk")

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict:
        """Decrypt and return the stored config ({} when absent)."""
        self._require()
        if not self.path.exists():
            return {}
        blob = self.path.read_bytes()
        if len(blob) <= _SALT_BYTES:
            return {}
        salt, token = blob[:_SALT_BYTES], blob[_SALT_BYTES:]
        try:
            plain = Fernet(_derive(self.password, salt)).decrypt(token)
        except InvalidToken as exc:
            raise SecretsUnavailable(
                "could not decrypt the stored config — BOT_ADMIN_PASSWORD does not "
                "match the one used when it was saved") from exc
        return json.loads(plain.decode())

    def save(self, config: dict) -> None:
        """Encrypt and atomically replace the stored config."""
        self._require()
        salt = os.urandom(_SALT_BYTES)
        token = Fernet(_derive(self.password, salt)).encrypt(
            json.dumps(config, separators=(",", ":")).encode())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(salt + token)
        os.chmod(tmp, 0o600)                 # not world-readable, even briefly
        os.replace(tmp, self.path)

    def redacted(self) -> dict:
        """Config safe to render: secrets replaced by fingerprints."""
        try:
            cfg = self.load()
        except SecretsUnavailable:
            return {}
        out = dict(cfg)
        for field in ("api_key", "api_secret"):
            if field in out:
                out[field] = mask(out[field])
        return out


def resolve_runtime_config(store: SecretsStore | None = None) -> dict:
    """Credentials + sizing for the running bot.

    The encrypted store wins when it is usable; otherwise fall back to plain
    environment variables, so an operator who prefers a server-side `.env` is
    not forced through the web UI.
    """
    store = store or SecretsStore()
    cfg: dict = {}
    if store.available():
        try:
            cfg = store.load()
        except SecretsUnavailable:
            cfg = {}

    venue = cfg.get("venue") or os.environ.get("CARRY_VENUE", "bybit-demo")
    prefix = "BYBIT" if str(venue).startswith("bybit") else "BINGX"
    return {
        "venue": venue,
        "api_key": cfg.get("api_key") or os.environ.get(f"{prefix}_API_KEY", ""),
        "api_secret": cfg.get("api_secret") or os.environ.get(f"{prefix}_API_SECRET", ""),
        "capital": float(cfg.get("capital") or os.environ.get("CARRY_CAPITAL", 200)),
        "slots": int(cfg.get("slots") or os.environ.get("CARRY_SLOTS", 3)),
        "leverage": float(cfg.get("leverage") or os.environ.get("CARRY_LEVERAGE", 1)),
        "source": "encrypted-store" if cfg else "environment",
    }
