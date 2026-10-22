"""Exportar un set como carpeta virtual de VirtualDJ 8 (.vdjfolder).

IMPORTANTE: este formato está armado según la documentación/ejemplos conocidos de
VirtualDJ 8. HAY QUE VERIFICARLO contra un .vdjfolder real creado por el VirtualDJ del
usuario (nombres de atributos, convención del bpm en segundos-por-pulso, idx, etc.)
antes de darlo por definitivo.

Ejemplo de salida:
    <?xml version="1.0" encoding="UTF-8"?>
    <VirtualFolder noDuplicates="no">
     <song path="E:\\Musica\\artist - title.mp3" size="123" songlength="201.5" bpm="0.4687"
           key="Am" artist="..." title="..." idx="0" />
    </VirtualFolder>
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from ..core.models import HAVE, SetItem

_INVALID_WIN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# caracteres de control no permitidos en XML 1.0
_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def safe_filename(name: str, default: str = "SETMAKER") -> str:
    """Nombre de archivo válido en Windows (sin < > : \" / \\ | ? *, sin punto/espacio final)."""
    n = _INVALID_WIN.sub(" ", name or "")
    n = re.sub(r"\s+", " ", n).strip().rstrip(". ")
    if not n:
        n = default
    if n.upper().split(".")[0] in _RESERVED:
        n = f"_{n}"
    return n[:120]


def _attr(value) -> str:
    # siempre entre comillas dobles (como VirtualDJ), escapando & < > " y saltos de línea
    return '"' + escape(_XML_BAD.sub("", str(value)),
                        {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}) + '"'


def _fmt_num(v: float, decimals: int) -> str:
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return s or "0"


def _song_line(item: SetItem, idx: int) -> str | None:
    if item.status != HAVE or not item.local_paths:
        return None
    best = item.local_paths[0]
    path = best.get("path") or ""
    if not path:
        return None
    attrs: list[tuple[str, str]] = [("path", path)]
    size = best.get("size")
    if size:
        attrs.append(("size", str(int(size))))
    length = best.get("duration") or (item.track.duration or 0)
    if length:
        attrs.append(("songlength", _fmt_num(float(length), 3)))
    bpm = best.get("bpm") or item.track.bpm or 0
    try:
        bpm = float(bpm)
    except (TypeError, ValueError):
        bpm = 0
    if bpm > 0:
        attrs.append(("bpm", _fmt_num(60.0 / bpm, 6)))   # VirtualDJ: segundos por pulso
    key = best.get("musical_key") or ""
    if key:
        attrs.append(("key", key))
    attrs.append(("artist", best.get("artist") or item.track.artist or ""))
    attrs.append(("title", best.get("title") or item.track.title or ""))
    attrs.append(("idx", str(idx)))
    return " <song " + " ".join(f"{k}={_attr(v)}" for k, v in attrs) + " />"


def export_vdjfolder(items: list[SetItem], dest: Path, name: str) -> Path:
    """Escribe <dest>/<name>.vdjfolder con los temas que tengo (status HAVE). Devuelve la ruta."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<VirtualFolder noDuplicates="no">']
    idx = 0
    for it in items:
        line = _song_line(it, idx)
        if line:
            lines.append(line)
            idx += 1
    lines.append("</VirtualFolder>")
    out = dest / f"{safe_filename(name)}.vdjfolder"
    tmp = out.with_suffix(".vdjfolder.tmp")
    # UTF-8 sin BOM, saltos de línea Windows
    tmp.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    tmp.replace(out)
    return out
