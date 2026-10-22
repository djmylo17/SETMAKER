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

    def __init__(self, db: Database, lastfm_key: str = "", youtube_key: str = ""):
        self.db = db
        self.http = CachedHTTP(db)
        self.deezer = Deezer(self.http)
        self.apple = AppleMusic(self.http)
        self.lastfm = LastFM(self.http, lastfm_key) if lastfm_key else None
        self.youtube = YouTube(self.http, youtube_key) if youtube_key else None
        self.warnings: list[str] = []
        self._failed: set[str] = set()

    def _safe(self, label: str, fn, *a, **k) -> list:
        if label in self._failed:
            return []
        try:
            return fn(*a, **k) or []
        except SourceError as exc:
            msg = f"{label}: {exc}"
            log.info(msg)
            if "internet" in str(exc) or "tardó" in str(exc):
                self._failed.add(label)
                self.warnings.append(f"{label} no respondió; se siguió con las demás fuentes.")
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
        for c in countries:
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
            else:
                tracks = []
            for t in tracks:
                t.sources["curada"] = {"playlist": pl.get("name") or pl["url"]}
                t.seed_genres += pl["genres"]
            out += tracks
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
            if "internet" in str(exc):
                self._failed.add("Deezer")
                self.warnings.append("Deezer no respondió; se siguió con las demás fuentes.")
            return None
        except Exception:  # noqa: BLE001
            return None

    def stats(self) -> dict:
        return {"llamadas": self.http.calls, "desde_cache": self.http.cache_hits}

    def close(self):
        self.http.close()
