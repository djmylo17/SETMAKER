"""Escaneo de carpetas de música (además de lo que ya conoce VirtualDJ).

Es incremental: si un archivo no cambió (mismo tamaño y fecha) no se vuelve a leer.
Los archivos que ya vienen desde VirtualDJ (source='vdj') no se duplican.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from ..core.normalize import is_karaoke_text
from .vdj_db import INSERT_SQL, LOSSLESS_EXTS, build_row, file_ext

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".aac", ".ogg", ".wma"}
BATCH = 500


def _walk(folder: str, cancel: Callable[[], bool] | None):
    """Recorre carpetas recursivamente con os.scandir, tolerando errores de permisos."""
    stack = [folder]
    while stack:
        if cancel and cancel():
            return
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not entry.name.startswith(("$", ".")):  # $RECYCLE.BIN, .Trash…
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if os.path.splitext(entry.name)[1].lower() in AUDIO_EXTS:
                                st = entry.stat()
                                yield entry.path, st.st_size, st.st_mtime
                    except OSError as exc:
                        log.warning("No se pudo revisar %s: %s", entry.path, exc)
        except OSError as exc:
            log.warning("No se pudo abrir la carpeta %s: %s", current, exc)


def _first(tags, key: str) -> str:
    try:
        v = tags.get(key) if tags is not None else None
    except Exception:  # noqa: BLE001
        return ""
    if not v:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip()


def read_tags(path: str) -> dict:
    """Lee tags y datos técnicos con mutagen. Nunca lanza excepción."""
    out = {"artist": "", "title": "", "genre": "", "comment": "", "bpm": 0.0, "key": "",
           "duration": None, "bitrate": None}
    try:
        import mutagen
        mf = mutagen.File(path, easy=True)
    except Exception as exc:  # noqa: BLE001 — archivo dañado o formato raro
        log.warning("No pude leer los tags de %s: %s", path, exc)
        return out
    if mf is None:
        return out
    tags = getattr(mf, "tags", None)
    out["artist"] = _first(tags, "artist") or _first(tags, "albumartist")
    out["title"] = _first(tags, "title")
    out["genre"] = _first(tags, "genre")
    out["comment"] = _first(tags, "comment")
    out["key"] = _first(tags, "initialkey")
    try:
        bpm = float(_first(tags, "bpm") or 0)
        out["bpm"] = round(bpm, 1) if 30 <= bpm <= 300 else 0.0
    except ValueError:
        pass
    info = getattr(mf, "info", None)
    if info is not None:
        length = getattr(info, "length", None)
        if length:
            out["duration"] = round(float(length), 2)
        br = getattr(info, "bitrate", None)
        if br:
            out["bitrate"] = int(br) // 1000 if br > 10000 else int(br)
        elif length:
            # WAV/AIFF sin bitrate: calcularlo con frecuencia × bits × canales
            sr = getattr(info, "sample_rate", 0) or 0
            bits = getattr(info, "bits_per_sample", 0) or 0
            ch = getattr(info, "channels", 0) or 0
            if sr and bits and ch:
                out["bitrate"] = int(sr * bits * ch / 1000)
    return out


def _under(path: str, roots: list[str]) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    for r in roots:
        if p == r or p.startswith(r.rstrip("\\/") + os.sep):
            return True
    return False


def scan_folders(db, folders, progress: Callable | None = None,
                 cancel: Callable[[], bool] | None = None) -> dict:
    """Escanea carpetas y actualiza library_tracks (source='scan').

    Devuelve {"folders", "found", "new", "updated", "unchanged", "removed", "errors",
    "skipped_vdj", "missing_folders", "cancelled"}.
    """
    stats = {"folders": 0, "found": 0, "new": 0, "updated": 0, "unchanged": 0, "removed": 0,
             "errors": 0, "skipped_vdj": 0, "missing_folders": [], "cancelled": False}
    roots: list[str] = []
    for f in folders or []:
        f = str(f).strip().strip('"')
        if not f:
            continue
        if os.path.isdir(f):
            roots.append(os.path.normcase(os.path.abspath(f)))
        else:
            stats["missing_folders"].append(f)
    stats["folders"] = len(roots)

    # Estado actual en memoria: path -> (source, size, mtime)
    existing: dict[str, tuple] = {}
    for r in db.query("SELECT path, source, size, mtime FROM library_tracks"):
        existing[os.path.normcase(r["path"])] = (r["path"], r["source"], r["size"], r["mtime"])

    seen: set[str] = set()
    batch: list[tuple] = []

    def flush():
        if batch:
            with db._lock, db.conn:
                db.conn.executemany(INSERT_SQL, batch)
            batch.clear()

    for root in roots:
        if cancel and cancel():
            stats["cancelled"] = True
            break
        for path, size, mtime in _walk(root, cancel):
            if cancel and cancel():
                stats["cancelled"] = True
                break
            stats["found"] += 1
            nk = os.path.normcase(path)
            seen.add(nk)
            prev = existing.get(nk)
            if prev is not None:
                if prev[1] == "vdj":
                    stats["skipped_vdj"] += 1
                    continue
                if prev[2] == size and prev[3] is not None and abs(float(prev[3]) - mtime) < 1.0:
                    stats["unchanged"] += 1
                    continue
            try:
                t = read_tags(path)
                ext = file_ext(path)
                karaoke = is_karaoke_text(path, t["title"], t["genre"], t["comment"])
                bitrate = t["bitrate"]
                if bitrate is None and ext in LOSSLESS_EXTS:
                    bitrate = 1411
                row = build_row(path, "scan", t["artist"], t["title"], genre=t["genre"],
                                comment=t["comment"], bpm=t["bpm"], key=t["key"], duration=t["duration"],
                                bitrate=bitrate, size=size, mtime=mtime, is_karaoke=karaoke)
                batch.append(row)
                stats["updated" if prev else "new"] += 1
            except Exception as exc:  # noqa: BLE001 — un archivo raro no detiene el escaneo
                stats["errors"] += 1
                log.warning("Error leyendo %s: %s", path, exc)
            if len(batch) >= BATCH:
                flush()
            if progress and stats["found"] % 200 == 0:
                progress(stats["found"], None, f"Escaneando… {stats['found']} archivos")
        if cancel and cancel():
            stats["cancelled"] = True
        if stats["cancelled"]:
            break
    flush()

    # Borrar los que desaparecieron (solo si el escaneo terminó completo)
    if not stats["cancelled"] and roots:
        gone = [orig for nk, (orig, src, _s, _m) in existing.items()
                if src == "scan" and nk not in seen and _under(orig, roots)]
        if gone:
            with db._lock, db.conn:
                db.conn.executemany("DELETE FROM library_tracks WHERE path = ?", [(g,) for g in gone])
        stats["removed"] = len(gone)
    if progress:
        progress(stats["found"], stats["found"], "Listo")
    log.info("Escaneo de carpetas: %s", stats)
    return stats
