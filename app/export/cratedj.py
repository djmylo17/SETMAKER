"""JSON de intercambio para CrateDJ (formato "setmaker-crate", versión 1).

CrateDJ es otra app (sin código compartido). El contrato está documentado en
docs/formato-intercambio.md: si cambias algo aquí, actualiza ese documento y,
si el cambio rompe compatibilidad, sube FORMAT_VERSION.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..core.models import EVENT_TYPES, HAVE, MISSING, OTHER_VERSION, EventProfile, SetItem
from .tables import all_local_paths, genre_display, item_year

FORMAT_NAME = "setmaker-crate"
FORMAT_VERSION = 1


def _status(s: str) -> str:
    # Solo tres valores posibles en el archivo; "sin revisar" se informa como "falta"
    return s if s in (HAVE, OTHER_VERSION, MISSING) else MISSING


def build_cratedj_payload(items: list[SetItem], profile: EventProfile | None,
                          genre_names: dict | None = None) -> dict:
    p = profile or EventProfile(name="Set")
    blocks = [{"index": i, "name": b.name, "start": b.start, "minutes": b.minutes}
              for i, b in enumerate(p.blocks)]
    tracks = []
    for pos, it in enumerate(items, start=1):
        t = it.track
        paths = all_local_paths(it)
        slug = it.cls.primary
        tracks.append({
            "position": pos,
            "block_index": it.block,
            "artist": t.artist,
            "title": t.title,
            "genre_slug": slug,
            "genre_name": genre_display(slug, genre_names),
            "year": item_year(it) or None,
            "bpm": round(t.bpm, 1) if t.bpm else None,
            "energy": it.cls.energy if it.cls.energy else None,
            "status": _status(it.status),
            "local_path": paths[0] if paths else None,
            "all_local_paths": paths,
            "isrc": t.isrc or None,
            "deezer_id": t.deezer_id or None,
            "preview_url": t.preview_url or None,
            "link": t.link or None,
            "sources": [str(k) for k in (t.sources or {}).keys()],
            "reasons": list(it.reasons or []),
        })
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "app_version": __version__,
        "event": {
            "name": p.name,
            "date": p.event_date,
            "venue": p.venue,
            "event_type": p.event_type,
            "event_type_label": EVENT_TYPES.get(p.event_type, p.event_type),
        },
        "blocks": blocks,
        "tracks": tracks,
    }


def export_cratedj_json(items: list[SetItem], profile: EventProfile | None, path,
                        genre_names: dict | None = None) -> Path:
    """Escribe el JSON (UTF-8 sin BOM, legible) de forma atómica."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build_cratedj_payload(list(items), profile, genre_names)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path
