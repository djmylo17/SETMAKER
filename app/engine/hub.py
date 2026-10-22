"""SourceHub: reúne candidatos y señales de tendencia desde todas las fuentes.

El motor solo conoce esta interfaz, así en las pruebas se reemplaza por datos falsos.
Regla clave (lección de SetDJ): las listas de tendencia (charts por país) SOLO aportan
candidatos y puntaje; nunca deciden el género. Todo pasa por la clasificación y los filtros.
"""
from __future__ import annotations

import logging
from typing import Callable

from ..core import store
from ..core.models import EventProfile, Genre, Track
from ..db.database import Database
from ..net import SourceError
from ..sources.apple import AppleMusic
from ..sources.deezer import Deezer, apply_detail, track_from_deezer
from ..sources.http_cache import CachedHTTP
from ..sources.lastfm import COUNTRY_NAMES, LastFM
from ..sources.youtube import YouTube, extract_playlist_id

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


class SourceHub:
    """Implementación real (internet). Errores de una fuente no detienen a las demás."""

    def __init__(self, db: Database, lastfm_key: str = "", youtube_key: str = "", spotify=None):
        self.db = db
        self.spotify = spotify   # SpotifyClient conectado (para leer TUS playlists)
        self.http = CachedHTTP(db)
        self.deezer = Deezer(self.http)
        self.apple = AppleMusic(self.http)
        self.lastfm = LastFM(self.http, lastfm_key) if lastfm_key else None
        self.youtube = YouTube(self.http, youtube_key) if youtube_key else None
        self.warnings: list[str] = []
        self._failed: set[str] = set()
        self._fail_count: dict[str, int] = {}

    def _conn_fail(self, label: str, exc: Exception) -> None:
        """Cuenta fallas de conexión; recién a la 3ª se deja de usar la fuente."""
        if "internet" in str(exc) or "tardó" in str(exc):
            n = self._fail_count.get(label, 0) + 1
            self._fail_count[label] = n
            if n >= 3 and label not in self._failed:
                self._failed.add(label)
                self.warnings.append(f"{label} no respondió varias veces; se siguió con las demás fuentes.")

    def _safe(self, label: str, fn, *a, **k) -> list:
        if label in self._failed:
            return []
        try:
            return fn(*a, **k) or []
        except SourceError as exc:
            log.info("%s: %s", label, exc)
            self._conn_fail(label, exc)
            return []
        except Exception as exc:  # noqa: BLE001
            log.exception("Error en %s", label)
            self.warnings.append(f"{label} falló ({exc.__class__.__name__}); se siguió con las demás.")
            return []

    # ---------------- candidatos por género
    def candidates_for_genre(self, g: Genre, profile: EventProfile, progress: Progress) -> list[Track]:
        out: list[Track] = []
        seeds = list(dict.fromkeys(g.seed_artists[:8]))
        for name in seeds:
            for t in self._safe("Deezer", self.deezer.artist_top, name, 12):
                t.seed_genres.append(g.slug)
                out.append(t)
        country = COUNTRY_NAMES.get(profile.country, "")
        terms = list(g.search_terms[:3])
        if terms and country and g.group in ("Reggaetón", "Urbano", "Electrónica latina", "Especiales"):
            terms.insert(0, f"{terms[0]} {country}")
        for term in terms[:3]:
            for pl in self._safe("Deezer", self.deezer.search_playlists, term, 2):
                for t in self._safe("Deezer", self.deezer.playlist_tracks, pl["id"], 60, pl.get("title", term)):
                    t.seed_genres.append(g.slug)
                    out.append(t)
        if self.lastfm:
            for tag in g.lastfm_tags[:2]:
                for t in self._safe("Last.fm", self.lastfm.tag_top, tag, 50):
                    t.seed_genres.append(g.slug)
                    out.append(t)
        return out

    def candidates_for_artists(self, artists: list[str]) -> list[Track]:
        out = []
        for name in artists:
            for t in self._safe("Deezer", self.deezer.artist_top, name, 15):
                t.sources["artista_semilla"] = {"artista": name}
                out.append(t)
        return out

    # ---------------- tendencias
    def trend_tracks(self, profile: EventProfile, progress: Progress) -> list[Track]:
        out: list[Track] = []
        countries = list(dict.fromkeys([profile.country] + profile.countries))[:4]
        apple_countries = [x for x in dict.fromkeys([profile.country] + profile.countries) if x != "PR"][:4]
        for c in apple_countries:   # Apple no tiene tienda de Puerto Rico
            progress(f"Apple Music: lo más escuchado en {COUNTRY_NAMES.get(c, c)}")
            out += self._safe("Apple Music", self.apple.most_played, c, 100)
        progress("Deezer: chart")
        out += self._safe("Deezer", self.deezer.chart, 100)
        if self.lastfm:
            for c in countries[:2]:
                out += self._safe("Last.fm", self.lastfm.geo_top, c, 100)
        if self.youtube:
            progress("YouTube: tendencias musicales")
            for c in countries[:2]:
                out += self._safe("YouTube", self.youtube.music_chart, c, 50)
        return out

    # ---------------- playlists curadas
    def curated_tracks(self, profile: EventProfile, progress: Progress) -> list[Track]:
        out = []
        for pl in store.list_curated(self.db, enabled_only=True):
            if pl["event_types"] and profile.event_type not in pl["event_types"]:
                continue
            progress(f"Playlist curada: {pl.get('name') or pl['url']}")
            if pl["platform"] == "deezer":
                tracks = self._safe("Deezer", self.deezer.playlist_tracks, pl["playlist_id"], 150, pl.get("name", ""))
            elif pl["platform"] == "youtube" and self.youtube:
                tracks = self._safe("YouTube", self.youtube.playlist_tracks, extract_playlist_id(pl["playlist_id"]), 150)
            elif pl["platform"] == "spotify" and self.spotify:
                tracks = self._safe("Spotify", self._spotify_playlist, pl["playlist_id"])
            else:
                tracks = []
            for t in tracks:
                t.sources["curada"] = {"playlist": pl.get("name") or pl["url"]}
                t.seed_genres += pl["genres"]
            out += tracks
        return out

    def _spotify_playlist(self, playlist_id: str, limit: int = 200) -> list[Track]:
        """Lee una playlist PROPIA de Spotify (desde feb. 2026 la API no entrega playlists ajenas)."""
        import httpx
        from ..core.normalize import track_key
        token = self.spotify._access_token()
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        params = {"limit": 50}
        out: list[Track] = []
        while url and len(out) < limit:
            r = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
            if r.status_code in (401, 403):
                raise SourceError("Spotify no permite leer esa playlist (debe ser tuya o colaborativa contigo).")
            if r.status_code >= 400:
                raise SourceError(f"Spotify respondió {r.status_code}")
            data = r.json()
            for e in data.get("items", []):
                tr = e.get("item") or e.get("track") or {}
                if not tr or tr.get("type", "track") != "track":
                    continue
                artist = ", ".join(a.get("name", "") for a in tr.get("artists", [])[:3])
                title = tr.get("name", "")
                rd = (tr.get("album") or {}).get("release_date", "") or ""
                t = Track(key=track_key(artist, title), title=title, artist=artist, release_date=rd,
                          year=int(rd[:4]) if rd[:4].isdigit() else 0,
                          isrc=(tr.get("external_ids") or {}).get("isrc", ""),
                          explicit=tr.get("explicit"), link=(tr.get("external_urls") or {}).get("spotify", ""))
                t.sources["curada"] = {"pos": len(out) + 1}
                out.append(t)
            url, params = data.get("next"), None
        return out

    # ---------------- enriquecimiento
    def artist_tags(self, artist: str) -> list[str]:
        if not self.lastfm:
            return []
        return self._safe("Last.fm", self.lastfm.artist_tags, artist)

    def enrich(self, t: Track) -> Track:
        """Completa datos de Deezer (id, año, BPM, ISRC, explícito, preview)."""
        if not t.deezer_id:
            d = self._safe_one(self.deezer.find_track, t.artist, t.title)
            if d:
                base = track_from_deezer(d, "deezer")
                t.deezer_id, t.preview_url = base.deezer_id, t.preview_url or base.preview_url
                t.link = t.link or base.link
                t.duration = t.duration or base.duration
                if base.explicit is not None:
                    t.explicit = base.explicit
        if t.deezer_id and (not t.year or not t.bpm or not t.isrc):
            d = self._safe_one(self.deezer.track_detail, t.deezer_id)
            if d:
                year_before = t.year
                apply_detail(t, d)
                # el año de Apple/YouTube suele ser más fiel que el de un recopilatorio en Deezer
                if year_before and t.year and year_before < t.year:
                    t.year = year_before
        return t

    def _safe_one(self, fn, *a):
        if "Deezer" in self._failed:
            return None
        try:
            return fn(*a)
        except SourceError as exc:
            self._conn_fail("Deezer", exc)
            return None
        except Exception:  # noqa: BLE001
            return None

    def stats(self) -> dict:
        return {"llamadas": self.http.calls, "desde_cache": self.http.cache_hits}

    def close(self):
        self.http.close()
