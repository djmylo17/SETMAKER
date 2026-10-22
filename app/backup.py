"""Respaldo y restauración de data/.

- Respaldo: un .zip en data/backups con la base, la config y las claves (cifradas).
- Restauración: se deja "pendiente" y se aplica al reiniciar, antes de abrir la base,
  para no pisar archivos que la app está usando.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .db.database import Database

log = logging.getLogger(__name__)

# Archivos de data/ que entran al respaldo
BACKUP_FILES = ("config.json", "keys.enc")
DB_NAME = "setmaker.db"


class BackupError(Exception):
    pass


def create_backup(data_dir: Path, db: Database) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = data_dir / "backups" / f"setmaker-respaldo-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / DB_NAME
        db.backup_to(db_copy)
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, DB_NAME)
            for name in BACKUP_FILES:
                f = data_dir / name
                if f.exists():
                    zf.write(f, name)
    log.info("Respaldo creado: %s", dest.name)
    return dest


def validate_backup(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            bad = zf.testzip()
    except zipfile.BadZipFile as exc:
        raise BackupError("El archivo no es un respaldo válido de SETMAKER.") from exc
    if DB_NAME not in names:
        raise BackupError("El archivo no es un respaldo de SETMAKER (no contiene la base de datos).")
    if bad:
        raise BackupError("El respaldo está dañado.")
    for n in names:
        if "/" in n or "\\" in n or n.startswith("."):
            raise BackupError("El respaldo contiene archivos inesperados.")


def schedule_restore(zip_path: Path, pending_path: Path) -> None:
    validate_backup(zip_path)
    shutil.copy2(zip_path, pending_path)


def apply_pending_restore(data_dir: Path, pending_path: Path) -> bool:
    """Se llama al iniciar, ANTES de abrir la base. Devuelve True si restauró algo."""
    if not pending_path.exists():
        return False
    try:
        validate_backup(pending_path)
        with zipfile.ZipFile(pending_path) as zf:
            for name in (DB_NAME, *BACKUP_FILES):
                if name in zf.namelist():
                    (data_dir / name).write_bytes(zf.read(name))
        log.info("Restauración aplicada")
        return True
    finally:
        pending_path.unlink(missing_ok=True)
