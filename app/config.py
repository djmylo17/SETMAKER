"""Ajustes de la app en data/config.json (texto legible, sin claves de API)."""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Países disponibles para la prioridad geográfica (código ISO → nombre).
COUNTRIES = {
    "CL": "Chile",
    "AR": "Argentina",
    "CO": "Colombia",
    "PR": "Puerto Rico",
    "PE": "Perú",
    "MX": "México",
    "DO": "República Dominicana",
    "US": "Estados Unidos",
    "ES": "España",
}

DEFAULTS: dict[str, Any] = {
    "config_version": 1,
    "ui": {"theme": "oscuro"},
    "virtualdj": {
        "database_xml": "",   # ruta a database.xml de VirtualDJ
        "folders_dir": "",    # carpeta donde se guardan los .vdjfolder
    },
    "library": {
        "music_folders": [],  # carpetas extra a escanear
        "ignore_karaoke": True,
    },
    "export": {"dir": ""},    # vacío = data/exports
    "region": {
        "country": "CL",
        "priority": ["CL", "AR", "CO", "PR", "PE", "MX", "DO"],
    },
    "gemini": {
        "model": "",               # vacío = elegir automáticamente
        "available_models": [],    # se llena al probar la clave
    },
    "updates": {
        "repo": "",                # usuario/setmaker en GitHub
        "check_on_start": False,
    },
}


def _deep_merge(base: dict, extra: dict) -> dict:
    """Mezcla 'extra' sobre 'base' sin perder claves nuevas de DEFAULTS."""
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.data = _deep_merge(DEFAULTS, raw)
        except (OSError, json.JSONDecodeError) as exc:
            # Archivo dañado: se respalda y se parte con valores por defecto.
            log.warning("config.json dañado (%s); se usan valores por defecto", exc)
            try:
                self.path.replace(self.path.with_suffix(".json.danado"))
            except OSError:
                pass
            self.data = copy.deepcopy(DEFAULTS)
            self.save()

    def save(self) -> None:
        # Escritura atómica: si se corta la luz no queda un archivo a medias.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        if save:
            self.save()
