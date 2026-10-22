"""Deezer API pública (sin clave): búsqueda, charts, playlists, detalle y preview de 30 s."""
from __future__ import annotations

import logging

from ..core.models import Track
from ..core.normalize import main_artist, normalize_title, track_key
from .http_cache import CachedHTTP

log = logging.getLogger(__name__)
API = "https://api.deezer.com"


def track_from_deezer(d: dict, source: str, detail: dict | None = None) -> Track:
    artist = (d.get("artist") or {}).get("name", "")
    contributors = [c.get("name", "") for c in (detail or d).get("contributors", []) or []]
    if len(contributors) > 1:
        extra = [c for c in contributors if c and main_artist(c) != main_artist(artist)]
        if extra:
            artist = artist + " feat. " + ", ".join(extra[:3])
    title = d.get("title") or d.get("title_short") or ""
    t = Track(
        key=track_key(artist, title), title=title, artist=artist,
        duration=int(d.get("duration") or 0), deezer_id=int(d.get("id") or 0),
        preview_url=d.get("preview") or "", link=d.get("link") or "",
        explicit=bool(d["explicit_lyrics"]) if "explicit_lyrics" in d else None,
    )
    if detail:
        apply_detail(t, detail)
    return t


def apply_detail(t: Track, detail: dict) -> None:
    rd = detail.get("release_date") or ""
    if rd and rd[:4].isdigit() and int(rd[:4]) > 0:
        t.release_date = rd
        t.year = int(rd[:4])
    if detail.get("bpm"):
        t.bpm = float(detail["bpm"])
    t.isrc = detail.get("isrc") or t.isrc
    if "explicit_lyrics" in detail:
        t.explicit = bool(detail["explicit_lyrics"])
    t.preview_url = detail.get("preview") or t.preview_url
    t.link = detail.get("link") or t.link
    t.duration = int(detail.get("duration") or t.duration)


class Deezer:
    def __init__(self, http: CachedHTTP):
        self.http = http

    def _get(self, path: str, params: dict | None = None, ttl: float = 24) -> dict:
        return self.http.get("deezer", API + path, params, ttl_hours=ttl)

    def search_artist_id(self, name: str) -> int | None:
        data = self._get("/search/artist", {"q": name, "limit": 5}, ttl=24 * 30)
        target = main_artist(name)
        for a in data.get("data", []):
            if main_artist(a.get("name", "")) == target:
                return int(a["id"])
        items = data.get("data", [])
        return int(items[0]["id"]) if items else None

    def artist_top(self, name: str, limit: int = 15) -> list[Track]:
        aid = self.search_artist_id(name)
        if not aid:
            return []
        data = self._get(f"/artist/{aid}/top", {"limit": limit}, ttl=72)
        out = []
        for i, d in enumerate(data.get("data", [])):
            t = track_from_deezer(d, "deezer")
            t.sources["deezer_artista"] = {"artista": name, "pos": i + 1, "rank": d.get("rank", 0)}
            out.append(t)
        return out

    def search_playlists(self, query: str, limit: int = 3) -> list[dict]:
        data = self._get("/search/playlist", {"q": query, "limit": limit * 2}, ttl=72)
        pls = [p for p in data.get("data", []) if (p.get("nb_tracks") or 0) >= 15]
        return pls[:limit]

    def playlist_tracks(self, playlist_id: int | str, limit: int = 80, label: str = "") -> list[Track]:
        data = self._get(f"/playlist/{playlist_id}/tracks", {"limit": limit}, ttl=24)
        out = []
        for i, d in enumerate(data.get("data", [])):
            if not d.get("readable", True):
                continue
            t = track_from_deezer(d, "deezer")
            t.sources["deezer_playlist"] = {"playlist": label or str(playlist_id), "pos": i + 1}
            out.append(t)
        return out

    def chart(self, limit: int = 100) -> list[Track]:
        data = self._get("/chart/0/tracks", {"limit": limit}, ttl=12)
        out = []
        for i, d in enumerate(data.get("data", [])):
            t = track_from_deezer(d, "deezer")
            t.sources["deezer_chart"] = {"pos": i + 1}
            out.append(t)
        return out

    def track_detail(self, deezer_id: int) -> dict:
        return self._get(f"/track/{deezer_id}", ttl=24 * 30)

    def find_track(self, artist: str, title: str) -> dict | None:
        """Busca un tema por artista+título (para temas que llegan de Apple/Last.fm/YouTube)."""
        q = f'artist:"{main_artist(artist)}" track:"{normalize_title(title)}"'
        data = self._get("/search/track", {"q": q, "limit": 5}, ttl=24 * 30)
        items = data.get("data", [])
        if not items:
            data = self._get("/search/track", {"q": f"{artist} {title}", "limit": 5}, ttl=24 * 30)
            items = data.get("data", [])
        want = track_key(artist, title)
        for d in items:
            if track_key((d.get("artist") or {}).get("name", ""), d.get("title", "")) == want:
                return d
        # aceptar coincidencia de título exacto con artista contenido
        nt = normalize_title(title)
        for d in items:
            if normalize_title(d.get("title", "")) == nt:
                return d
        return None
