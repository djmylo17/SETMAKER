"""¿Ya tengo este tema? Compara los temas del set con la biblioteca local.

La biblioteca se carga una sola vez en memoria con dos índices:
- por artista (todos los artistas de cada archivo, incluidos los feat.)
- por palabras del título normalizado
así comparar 100 temas contra 11.000+ archivos toma una fracción de segundo.

Reglas:
- título casi igual (>= 90) + artista coincide            -> HAVE ("la tengo")
- igual pero solo existe como remix/mashup (o al revés)   -> OTHER_VERSION
- mismo artista con título parecido (80–90)               -> OTHER_VERSION
- si no                                                   -> MISSING
- las correcciones manuales (match_overrides) mandan: path '' = "me falta", ruta = "la tengo".
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from pathlib import Path, PureWindowsPath

from rapidfuzz import fuzz, process

from ..core.models import HAVE, MISSING, OTHER_VERSION, SetItem
from ..core.normalize import _clean, is_remix_tag, normalize_title, split_artists, track_key

log = logging.getLogger(__name__)

LOSSLESS = {"wav", "flac", "aiff", "aif", "alac"}
HAVE_MIN = 90
VERSION_MIN = 80
ARTIST_FUZZY_MIN = 90
COMMON_TOKEN_MAX = 2500     # palabras muy comunes ("la", "de") no sirven para buscar candidatos

_COLS = ("path, source, artist, title, genre, bpm, musical_key, duration, format, bitrate, size, "
         "norm_artist, norm_title, title_remix, is_karaoke")


def quality_rank(fmt: str, bitrate: int | None) -> int:
    fmt = (fmt or "").lower()
    if fmt in LOSSLESS:
        return 10000
    return int(bitrate or 0)


def quality_label(fmt: str, bitrate: int | None) -> str:
    fmt = (fmt or "").lower()
    name = fmt.upper() or "?"
    if fmt in LOSSLESS:
        return f"{name} (sin pérdida)"
    if bitrate:
        return f"{name} {int(bitrate)}"
    return name


def _stem(path: str) -> str:
    p = PureWindowsPath(path) if "\\" in path else Path(path)
    return _clean(p.stem)


def _has_remix(title_remix: str, norm_title: str) -> bool:
    """El título conserva info de remix/mashup que el normalizado quitó."""
    return bool(title_remix) and title_remix != norm_title and is_remix_tag(title_remix)


def title_similarity(a: str, b: str) -> float:
    """Parecido de títulos normalizados (0–100).

    token_set_ratio solo cuenta completo si los títulos tienen largo parecido; así
    "party" no es igual a "party in the usa".
    """
    if not a or not b:
        return 0.0
    base = max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
    ts = fuzz.token_set_ratio(a, b)
    if ts > base:
        la, lb = len(a.split()), len(b.split())
        if min(la, lb) / max(la, lb) >= 0.6:
            base = max(base, ts)
        else:
            base = max(base, min(ts, 85.0))  # contenido dentro de otro: "parecido"
    return float(base)


class LibraryMatcher:
    def __init__(self, db, ignore_karaoke: bool = True):
        self.db = db
        self.ignore_karaoke = ignore_karaoke
        self.rows: list[dict] = []
        self.by_path: dict[str, dict] = {}
        self.by_artist: dict[str, list[int]] = defaultdict(list)
        self.by_token: dict[str, list[int]] = defaultdict(list)
        self.overrides: dict[str, str] = {}
        self.reload()

    # ---------------------------------------------------------------- carga
    def reload(self) -> None:
        self.rows.clear()
        self.by_path.clear()
        self.by_artist.clear()
        self.by_token.clear()
        for r in self.db.query(f"SELECT {_COLS} FROM library_tracks"):
            d = dict(r)
            d["is_karaoke"] = bool(d.get("is_karaoke"))
            self.by_path[os.path.normcase(d["path"])] = d
            if self.ignore_karaoke and d["is_karaoke"]:
                continue
            d["norm_title"] = d.get("norm_title") or ""
            d["title_remix"] = d.get("title_remix") or d["norm_title"]
            d["artists"] = split_artists(d.get("artist") or "") or ([d["norm_artist"]] if d.get("norm_artist") else [])
            d["stem"] = _stem(d["path"])
            d["remix"] = _has_remix(d["title_remix"], d["norm_title"])
            idx = len(self.rows)
            self.rows.append(d)
            for a in d["artists"]:
                self.by_artist[a].append(idx)
            for tok in set(d["norm_title"].split()):
                self.by_token[tok].append(idx)
        self.artist_names = list(self.by_artist.keys())
        self.overrides = {r["track_key"]: r["path"] for r in
                          self.db.query("SELECT track_key, path FROM match_overrides")}

    # ---------------------------------------------------------------- correcciones
    def set_override(self, key: str, path: str) -> None:
        """path '' = forzar "me falta"; una ruta = "la tengo" con ese archivo."""
        self.db.execute(
            "INSERT INTO match_overrides(track_key, path) VALUES(?, ?) "
            "ON CONFLICT(track_key) DO UPDATE SET path = excluded.path, "
            "created_at = datetime('now','localtime')", (key, path or ""))
        self.overrides[key] = path or ""

    def clear_override(self, key: str) -> None:
        self.db.execute("DELETE FROM match_overrides WHERE track_key = ?", (key,))
        self.overrides.pop(key, None)

    # ---------------------------------------------------------------- salida
    @staticmethod
    def to_result(d: dict) -> dict:
        return {
            "path": d["path"], "artist": d.get("artist") or "", "title": d.get("title") or "",
            "format": d.get("format") or "", "bitrate": d.get("bitrate"),
            "quality_label": quality_label(d.get("format") or "", d.get("bitrate")),
            "source": d.get("source") or "", "bpm": d.get("bpm"), "musical_key": d.get("musical_key") or "",
            "duration": d.get("duration"), "size": d.get("size"),
        }

    @staticmethod
    def _sort(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda d: (-quality_rank(d.get("format") or "", d.get("bitrate")),
                                           d.get("source") != "vdj", d["path"]))

    def _override_result(self, path: str) -> dict:
        d = self.by_path.get(os.path.normcase(path))
        if d is None:
            ext = (PureWindowsPath(path) if "\\" in path else Path(path)).suffix.lower().lstrip(".")
            d = {"path": path, "artist": "", "title": "", "format": ext, "bitrate": None, "source": "manual"}
        return self.to_result(d)

    # ---------------------------------------------------------------- búsqueda
    def _artist_candidates(self, q_artists: list[str]) -> set[int]:
        out: set[int] = set()
        for a in q_artists:
            if a in self.by_artist:
                out.update(self.by_artist[a])
            elif self.artist_names and len(a) >= 4:
                for name, score, _ in process.extract(a, self.artist_names, scorer=fuzz.ratio,
                                                      limit=3, score_cutoff=ARTIST_FUZZY_MIN):
                    out.update(self.by_artist[name])
        return out

    def _title_candidates(self, q_title: str) -> set[int]:
        out: set[int] = set()
        toks = [t for t in set(q_title.split()) if t in self.by_token]
        useful = [t for t in toks if len(self.by_token[t]) <= COMMON_TOKEN_MAX] or toks
        for t in useful:
            out.update(self.by_token[t])
        return out

    def _artist_ok(self, d: dict, q_artists: list[str]) -> bool:
        if not q_artists:
            return False
        for a in q_artists:
            for ra in d["artists"]:
                if ra == a or (len(a) >= 4 and fuzz.ratio(ra, a) >= ARTIST_FUZZY_MIN):
                    return True
        main = q_artists[0]
        # archivo sin artista en tags pero con el nombre en el título o el nombre de archivo
        if len(main) >= 3 and (f" {main} " in f" {d['norm_title']} " or f" {main} " in f" {d['stem']} "):
            return True
        return False

    def match(self, artist: str, title: str, key: str | None = None) -> tuple[str, list[dict]]:
        key = key or track_key(artist, title)
        if key in self.overrides:
            path = self.overrides[key]
            if not path:
                return MISSING, []
            return HAVE, [self._override_result(path)]

        q_title = normalize_title(title)
        if not q_title:
            return MISSING, []
        q_remix = _has_remix(normalize_title(title, keep_remix=True), q_title)
        q_artists = split_artists(artist)

        by_artist = self._artist_candidates(q_artists)
        cands = by_artist | self._title_candidates(q_title)

        have: list[dict] = []
        version: list[dict] = []
        for i in cands:
            d = self.rows[i]
            if i not in by_artist and not self._artist_ok(d, q_artists):
                continue
            score = title_similarity(q_title, d["norm_title"])
            if score >= HAVE_MIN:
                (have if d["remix"] == q_remix else version).append(d)
            elif score >= VERSION_MIN:
                version.append(d)
        if have:
            return HAVE, [self.to_result(d) for d in self._sort(have)]
        if version:
            return OTHER_VERSION, [self.to_result(d) for d in self._sort(version)]
        return MISSING, []

    def search(self, text: str, limit: int = 200, include_karaoke: bool = False) -> list[dict]:
        """Búsqueda simple para la pantalla Biblioteca (todas las palabras deben aparecer)."""
        toks = _clean(text or "").split()
        out = []
        pool = [d for d in self.by_path.values() if include_karaoke or not d.get("is_karaoke")]
        if not toks:
            pool.sort(key=lambda d: ((d.get("artist") or "").lower(), (d.get("title") or "").lower()))
            return [self.to_result(d) for d in pool[:limit]]
        for d in pool:
            hay = " ".join((d.get("norm_artist") or "", _clean(d.get("artist") or ""),
                            d.get("title_remix") or "", _stem(d["path"]), (d.get("genre") or "").lower()))
            if all(t in hay for t in toks):
                out.append(d)
                if len(out) >= limit:
                    break
        out.sort(key=lambda d: ((d.get("artist") or "").lower(), (d.get("title") or "").lower()))
        return [self.to_result(d) for d in out]


def match_items(db, items: list[SetItem], ignore_karaoke: bool = True,
                matcher: LibraryMatcher | None = None) -> dict:
    """Llena item.status e item.local_paths en el lugar. Devuelve conteos por estado."""
    m = matcher or LibraryMatcher(db, ignore_karaoke=ignore_karaoke)
    counts = {HAVE: 0, OTHER_VERSION: 0, MISSING: 0}
    for it in items:
        status, paths = m.match(it.track.artist, it.track.title, it.track.key or None)
        it.status = status
        it.local_paths = paths
        counts[status] = counts.get(status, 0) + 1
    return counts
