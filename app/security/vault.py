"""Bóveda de claves de API (data/keys.enc).

- Sin contraseña maestra: las claves quedan cifradas con una llave interna de la app.
  Evita que alguien las lea abriendo el archivo con el Bloc de notas, pero NO es
  protección fuerte (cualquiera con SETMAKER puede abrirlas).
- Con contraseña maestra: cifrado real (scrypt + Fernet/AES). Sin la contraseña
  no se pueden leer. Funciona en cualquier PC porque no depende de Windows.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT_VERSION = 1
_INTERNAL_SECRET = b"SETMAKER::llave-interna::v1"

# Claves que maneja la app
SERVICES = {
    "gemini_api_key": "Gemini",
    "lastfm_api_key": "Last.fm",
    "youtube_api_key": "YouTube",
    "spotify_client_id": "Spotify",
}


class VaultLocked(Exception):
    """La bóveda tiene contraseña y no se entregó."""


class WrongPassword(Exception):
    """Contraseña incorrecta o archivo dañado."""


def _derive(secret: bytes, salt: bytes) -> Fernet:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret)))


class KeyVault:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, str] = {}
        self._password: str | None = None
        self._unlocked = False

    # ---------- estado ----------
    def exists(self) -> bool:
        return self.path.exists()

    def is_protected(self) -> bool:
        """True si el archivo existente pide contraseña maestra."""
        if not self.exists():
            return False
        try:
            return bool(json.loads(self.path.read_text(encoding="utf-8")).get("protected"))
        except (OSError, json.JSONDecodeError):
            return False

    @property
    def unlocked(self) -> bool:
        return self._unlocked

    @property
    def has_password(self) -> bool:
        return self._password is not None

    # ---------- abrir / guardar ----------
    def unlock(self, password: str | None = None) -> None:
        if not self.exists():
            self._data, self._password, self._unlocked = {}, password or None, True
            return
        try:
            header = json.loads(self.path.read_text(encoding="utf-8"))
            salt = base64.b64decode(header["salt"])
            token = header["token"].encode("ascii")
            protected = bool(header.get("protected"))
        except (OSError, KeyError, ValueError) as exc:
            raise WrongPassword("El archivo de claves está dañado.") from exc

        if protected and not password:
            raise VaultLocked()
        secret = password.encode("utf-8") if protected else _INTERNAL_SECRET
        try:
            plain = _derive(secret, salt).decrypt(token)
        except InvalidToken as exc:
            raise WrongPassword("Contraseña incorrecta.") from exc
        self._data = json.loads(plain.decode("utf-8"))
        self._password = password if protected else None
        self._unlocked = True

    def save(self) -> None:
        self._require_unlocked()
        salt = os.urandom(16)
        secret = self._password.encode("utf-8") if self._password else _INTERNAL_SECRET
        token = _derive(secret, salt).encrypt(json.dumps(self._data).encode("utf-8"))
        payload = {
            "format": FORMAT_VERSION,
            "protected": self._password is not None,
            "salt": base64.b64encode(salt).decode("ascii"),
            "token": token.decode("ascii"),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---------- claves ----------
    def get(self, name: str) -> str:
        self._require_unlocked()
        return self._data.get(name, "")

    def set(self, name: str, value: str) -> None:
        self._require_unlocked()
        value = (value or "").strip()
        if value:
            self._data[name] = value
        else:
            self._data.pop(name, None)
        self.save()

    def configured(self) -> list[str]:
        self._require_unlocked()
        return [k for k in SERVICES if self._data.get(k)]

    # ---------- contraseña maestra ----------
    def set_password(self, new_password: str | None) -> None:
        """Activa, cambia o quita (None) la contraseña maestra."""
        self._require_unlocked()
        self._password = new_password or None
        self.save()

    def check_password(self, password: str) -> bool:
        return self._password is not None and password == self._password

    def _require_unlocked(self) -> None:
        if not self._unlocked:
            raise VaultLocked()
