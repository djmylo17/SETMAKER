"""Apple Music RSS: lo más escuchado por país (solo señal de tendencia)."""
from __future__ import annotations

from ..core.models import Track
from ..core.normalize import track_key
from .http_cache import CachedHTTP

URL = "https://rss.marketingtools.apple.com/api/v2/{country}/music/most-played/{limit}/songs.json"


class AppleMusic:
    def __init__(self, http: CachedHTTP):
        self.http = http

    def most_played(self, country: str, limit: int = 100) -> list[Track]:
        data = self.http.get("apple", URL.format(country=country.lower(), limit=limit), ttl_hours=12)
        out = []
        for i, r in enumerate(data.get("feed", {}).get("results", [])):
            artist, title = r.get("artistName", ""), r.get("name", "")
            rd = r.get("releaseDate", "") or ""
            t = Track(key=track_key(artist, title), title=title, artist=artist,
                      release_date=rd, year=int(rd[:4]) if rd[:4].isdigit() and int(rd[:4]) > 0 else 0, link=r.get("url", ""))
            t.sources[f"apple_{country.upper()}"] = {"pos": i + 1}
            t.source_genres = [g.get("name", "") for g in r.get("genres", []) if g.get("name") not in ("Música", "Music")]
            out.append(t)
        return out
