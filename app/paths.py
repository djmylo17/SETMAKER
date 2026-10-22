"""Rutas portables.

SETMAKER guarda TODO dentro de su propia carpeta (data/ al lado del .exe),
así funciona igual si conectas el disco portátil en otro PC.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Carpeta donde vive la app.

    - Empaquetada (.exe): la carpeta del ejecutable.
    - En desarrollo: la raíz del proyecto.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Carpeta de recursos internos (íconos, plantillas de fábrica)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", app_base_dir()))
    return app_base_dir()


def data_dir() -> Path:
    """Carpeta de datos del usuario (se conserva al actualizar).

    La variable de entorno SETMAKER_DATA_DIR permite cambiarla (se usa en pruebas).
    """
    override = os.environ.get("SETMAKER_DATA_DIR")
    base = Path(override) if override else app_base_dir() / "data"
    for sub in ("", "backups", "exports", "logs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "setmaker.db"


def config_path() -> Path:
    return data_dir() / "config.json"


def vault_path() -> Path:
    return data_dir() / "keys.enc"


def pending_restore_path() -> Path:
    return data_dir() / "_restauracion_pendiente.zip"


def is_writable(folder: Path) -> bool:
    """True si se puede escribir en la carpeta (un disco protegido contra escritura daría False)."""
    probe = folder / ".prueba_escritura"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
