"""Objeto compartido con todo lo que las pantallas necesitan."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .db.database import Database
from .security.vault import KeyVault


@dataclass
class AppContext:
    data_dir: Path
    config: Config
    db: Database
    vault: KeyVault
