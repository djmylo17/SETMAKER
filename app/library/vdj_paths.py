"""Detección de dónde está VirtualDJ (la lectura completa llega en la Fase 4)."""
from __future__ import annotations

import os
import string
from pathlib import Path


def candidate_vdj_dirs() -> list[Path]:
    """Lugares habituales de la carpeta VirtualDJ en Windows.

    - Documentos\\VirtualDJ (instalación normal)
    - X:\\VirtualDJ en cada disco (VirtualDJ crea una base por disco externo)
    """
    out: list[Path] = []
    home = Path.home()
    for docs in (home / "Documents", home / "Documentos", home / "OneDrive" / "Documents",
                 home / "OneDrive" / "Documentos"):
        out.append(docs / "VirtualDJ")
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            try:
                if root.exists():
                    out.append(root / "VirtualDJ")
            except OSError:
                continue
    return out


def find_vdj_databases() -> list[Path]:
    found = []
    for d in candidate_vdj_dirs():
        db = d / "database.xml"
        try:
            if db.is_file():
                found.append(db)
        except OSError:
            continue
    return found


def default_folders_dir(database_xml: Path) -> Path:
    """Carpeta de crates de VirtualDJ junto a una base dada."""
    return Path(database_xml).parent / "Folders"
