"""Last.fm: tags de género por artista, top por tag y por país."""
from __future__ import annotations

from ..core.models import Track
from ..core.normalize import track_key
from .http_cache import CachedHTTP

API = "https://ws.audioscrobbler.com/2.0/"

COUNTRY_NAMES = {"CL": "Chile", "AR": "Argentina", "CO": "Colombia", "PR": "Puerto Rico", "PE": "Peru",
                 "MX": "Mexico", "DO": "Dominican Republic", "US": "United States", "ES": "Spain"}


class LastFM:
    def __init__(self, http: CachedHTTP, api_key: str):
        self.http, self.key = http, api_key

    def _get(self, params: dict, ttl: float) -> dict:
        p = dict(params, api_key=self.key, format="json")
        data = self.http.get("lastfm", API, p, ttl_hours=ttl)
        if isinstance(data, dict) and "error" in data:
            return {}
        return data

    def _tracks(self, data: dict, source: str, label: str) -> list[Track]:
        out = []
        items = (data.get("tracks") or {}).get("track", []) or []
        if isinstance(items, dict):
            items = [items]
        for i, d in enumerate(items):
            artist = d.get("artist", {}).get("name", "") if isinstance(d.get("artist"), dict) else str(d.get("artist", ""))
            title = d.get("name", "")
            t = Track(key=track_key(artist, title), title=title, artist=artist)
            t.sources[source] = {"pos": i + 1, "detalle": label}
            out.append(t)
        return out

    def tag_top(self, tag: str, limit: int = 60) -> list[Track]:
        data = self._get({"method": "tag.gettoptracks", "tag": tag, "limit": limit}, ttl=72)
        tracks = self._tracks(data, "lastfm_tag", tag)
        for t in tracks:
            t.source_genres.append(tag)
        return tracks

    def geo_top(self, country_code: str, limit: int = 100) -> list[Track]:
        name = COUNTRY_NAMES.get(country_code.upper())
        if not name:
            return []
        data = self._get({"method": "geo.gettoptracks", "country": name, "limit": limit}, ttl=24)
        return self._tracks(data, f"lastfm_{country_code.upper()}", name)

    def artist_tags(self, artist: str) -> list[str]:
        data = self._get({"method": "artist.gettoptags", "artist": artist, "autocorrect": 1}, ttl=24 * 30)
        tags = (data.get("toptags") or {}).get("tag", []) or []
        if isinstance(tags, dict):
            tags = [tags]
        return [t.get("name", "").lower() for t in tags[:12] if int(t.get("count", 0) or 0) >= 5]
