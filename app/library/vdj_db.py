"""Lectura de la base de VirtualDJ 8 (database.xml) hacia la tabla library_tracks.

Formato (resumido):
    <VirtualDJ_Database Version="8.x">
      <Song FilePath="E:\\Musica\\Artista - Tema.mp3" FileSize="1234">
        <Tags Author="..." Title="..." Genre="..." Album="..." Year="..." Remix="..."/>
        <Infos SongLength="201.5" Bitrate="320" .../>
        <Comment>texto</Comment>
        <Scan Version="801" Bpm="0.468750" AltBpm="..." Volume="..." Key="Am" Flag="..."/>
        <Poi .../>
      </Song>
    </VirtualDJ_Database>

OJO: en <Scan>, Bpm está en SEGUNDOS POR PULSO (bpm real = 60 / valor).
La base puede tener 11.000+ temas (~30 MB): se lee en streaming (iterparse) limpiando
cada <Song> apenas se procesa, para no llenar la memoria.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from typing import Callable

from ..core.normalize import is_karaoke_text, main_artist, normalize_title

log = logging.getLogger(__name__)

Progress = Callable[[int, "int | None", str], None]

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".aac", ".ogg", ".wma", ".alac", ".opus"}
LOSSLESS_EXTS = {".wav", ".flac", ".aiff", ".aif", ".alac"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".mpg", ".mpeg", ".webm", ".m4v", ".vob"}
# Formatos de karaoke (solo se aceptan si hay contexto de karaoke, salvo .cdg/.kar que siempre lo son)
KARAOKE_ONLY_EXTS = {".cdg", ".kar"}
KARAOKE_CONTAINER_EXTS = {".zip"} | VIDEO_EXTS

ONLINE_PREFIXES = ("netsearch:", "td:", "http:", "https:", "ftp:", "spotify:", "deezer:",
                   "tidal:", "beatport:", "beatsource:", "soundcloud:", "itunes:", "vdjcache:")

_FILENAME_RE = re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+?)\s*$")


# ---------------------------------------------------------------- utilidades compartidas
def file_ext(path: str) -> str:
    """Extensión en minúsculas, funciona con rutas Windows aunque corra en otro sistema."""
    return PureWindowsPath(path).suffix.lower() if "\\" in path else Path(path).suffix.lower()


def file_stem(path: str) -> str:
    return PureWindowsPath(path).stem if "\\" in path else Path(path).stem


def format_from_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return {"aif": "aiff"}.get(ext, ext)


def parse_filename(path: str) -> tuple[str, str]:
    """'Artista - Título.mp3' -> ('Artista', 'Título'). Sin guion: ('', nombre)."""
    stem = file_stem(path).replace("_", " ").strip()
    # quitar numeración típica "01 - " o "01. "
    stem = re.sub(r"^\d{1,3}\s*[.\-_)]\s*", "", stem)
    m = _FILENAME_RE.match(stem)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", stem


def spb_to_bpm(value: str | float | None) -> float:
    """Convierte segundos-por-pulso de VirtualDJ a BPM. 0 = desconocido/ inválido."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    bpm = round(60.0 / v, 1)
    return bpm if 30.0 <= bpm <= 300.0 else 0.0


def _to_float(value) -> float | None:
    try:
        f = float(value)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        i = int(float(value))
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _is_online(path: str) -> bool:
    p = path.strip().lower()
    return p.startswith(ONLINE_PREFIXES) or "://" in p


def build_row(path: str, source: str, artist: str, title: str, *, genre: str = "", comment: str = "",
              bpm: float = 0.0, key: str = "", duration: float | None = None, bitrate: int | None = None,
              size: int | None = None, mtime: float | None = None, is_karaoke: bool = False) -> tuple:
    """Tupla en el orden de ROW_COLUMNS (compartido con el escáner)."""
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not title:
        fa, ft = parse_filename(path)
        title = ft
        if not artist:
            artist = fa
    elif not artist:
        fa, ft = parse_filename(path)
        if fa and normalize_title(ft) == normalize_title(title):
            artist = fa
    ext = file_ext(path)
    return (
        path, source, artist, title, genre or "", comment or "", bpm or None, key or "",
        duration, format_from_ext(ext), bitrate, size, mtime,
        main_artist(artist), normalize_title(title), normalize_title(title, keep_remix=True),
        1 if is_karaoke else 0,
    )


ROW_COLUMNS = ("path", "source", "artist", "title", "genre", "comment", "bpm", "musical_key",
               "duration", "format", "bitrate", "size", "mtime", "norm_artist", "norm_title",
               "title_remix", "is_karaoke")

INSERT_SQL = (f"INSERT OR REPLACE INTO library_tracks({', '.join(ROW_COLUMNS)}) "
              f"VALUES({', '.join('?' for _ in ROW_COLUMNS)})")


# ---------------------------------------------------------------- lectura
def _song_to_row(song: ET.Element) -> tuple[tuple | None, bool]:
    """Devuelve (fila, es_karaoke) o (None, False) si hay que saltarla."""
    path = (song.get("FilePath") or "").strip()
    if not path or _is_online(path):
        return None, False
    ext = file_ext(path)
    tags = song.find("Tags")
    infos = song.find("Infos")
    scan = song.find("Scan")
    comment_el = song.find("Comment")
    g = (lambda el, k: (el.get(k) or "").strip() if el is not None else "")
    artist, title, genre = g(tags, "Author"), g(tags, "Title"), g(tags, "Genre")
    remix = g(tags, "Remix")
    comment = (comment_el.text or "").strip() if comment_el is not None else ""
    if remix and title and remix.lower() not in title.lower():
        title = f"{title} ({remix})"

    karaoke = is_karaoke_text(path, title, genre, comment, g(tags, "Album"))
    if ext in KARAOKE_ONLY_EXTS:
        karaoke = True
    elif ext in AUDIO_EXTS:
        pass
    elif ext in KARAOKE_CONTAINER_EXTS and karaoke:
        pass  # video/zip de karaoke: se conserva marcado
    else:
        return None, False  # video normal, imagen u otro tipo

    bitrate = _to_int(g(infos, "Bitrate"))
    if bitrate and bitrate > 10000:  # algunas versiones lo guardan en bps
        bitrate //= 1000
    row = build_row(
        path, "vdj", artist, title, genre=genre, comment=comment,
        bpm=spb_to_bpm(g(scan, "Bpm")), key=g(scan, "Key"),
        duration=_to_float(g(infos, "SongLength")), bitrate=bitrate,
        size=_to_int(song.get("FileSize")), is_karaoke=karaoke,
    )
    return row, karaoke


def iter_vdj_songs(xml_path: Path, stats: dict, progress: Progress | None = None):
    """Recorre database.xml en streaming y entrega filas listas para insertar."""
    context = ET.iterparse(str(xml_path), events=("start", "end"))
    root = None
    for event, el in context:
        if event == "start":
            if root is None:
                root = el
            continue
        if el.tag != "Song":
            continue
        stats["total"] += 1
        try:
            row, karaoke = _song_to_row(el)
        except Exception:  # noqa: BLE001 — un tema raro no debe botar la importación
            log.exception("Tema ilegible en database.xml")
            row, karaoke = None, False
        if row is None:
            stats["skipped"] += 1
        else:
            if karaoke:
                stats["karaoke"] += 1
            yield row
        # liberar memoria: el <Song> ya procesado y su referencia desde la raíz
        el.clear()
        if root is not None:
            try:
                root.remove(el)
            except ValueError:
                pass
        if progress and stats["total"] % 500 == 0:
            progress(stats["total"], None, f"Leyendo VirtualDJ… {stats['total']:,} temas".replace(",", "."))


def import_vdj_database(db, xml_path, progress: Progress | None = None) -> dict:
    """Importa database.xml de VirtualDJ. Reemplaza todas las filas source='vdj' en una transacción.

    Devuelve {"total", "imported", "karaoke", "skipped"}.
    """
    xml_path = Path(xml_path)
    if not xml_path.is_file():
        raise FileNotFoundError(f"No encuentro el archivo de VirtualDJ: {xml_path}")
    stats = {"total": 0, "imported": 0, "karaoke": 0, "skipped": 0}
    try:
        # Primero se lee todo (si el XML está dañado, la base actual queda intacta)
        rows = list(iter_vdj_songs(xml_path, stats, progress))
    except ET.ParseError as exc:
        raise ValueError(f"El archivo database.xml parece dañado o incompleto ({exc}). "
                         "Cierra VirtualDJ y vuelve a intentar.") from exc
    # rutas repetidas: la última gana (igual que INSERT OR REPLACE)
    stats["imported"] = len({r[0] for r in rows})
    if progress:
        progress(stats["total"], stats["total"], "Guardando en la base de SETMAKER…")
    with db._lock, db.conn:
        db.conn.execute("DELETE FROM library_tracks WHERE source = 'vdj'")
        for i in range(0, len(rows), 2000):
            db.conn.executemany(INSERT_SQL, rows[i:i + 2000])
    if progress:
        progress(stats["total"], stats["total"], "Listo")
    log.info("VirtualDJ importado: %s", stats)
    return stats
