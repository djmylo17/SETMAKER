"""YouTube Data API v3: tendencias musicales por país y playlists públicas.

Cuota gratis: 10.000 unidades/día. chart y playlistItems cuestan 1 unidad; search cuesta 100
(por eso no se usa search en la generación).
"""
from __future__ import annotations

import re

from ..core.models import Track
from ..core.normalize import track_key
from .http_cache import CachedHTTP

API = "https://www.googleapis.com/youtube/v3"
NOISE = re.compile(r"\s*[\(\[](?:video|official|oficial|lyric|letra|audio|visualizer|en vivo|live)[^\)\]]*[\)\]]", re.I)


def parse_video_title(title: str, channel: str = "") -> tuple[str, str] | None:
    """'Artista - Tema (Video Oficial)' -> (artista, tema). None si no se puede."""
    t = NOISE.sub("", title or "").strip()
    t = t.replace("–", "-").replace("—", "-").replace("|", "-")
    if " - " in t:
        a, s = t.split(" - ", 1)
        return a.strip(), s.split(" - ")[0].strip()
    ch = (channel or "").replace(" - Topic", "").replace("VEVO", "").strip()
    if ch and t:
        return ch, t
    return None


def extract_playlist_id(url: str) -> str:
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else url.strip()


class YouTube:
    def __init__(self, http: CachedHTTP, api_key: str):
        self.http, self.key = http, api_key

    def _items_to_tracks(self, items: list, source: str) -> list[Track]:
        out = []
        for i, it in enumerate(items):
            sn = it.get("snippet", {})
            parsed = parse_video_title(sn.get("title", ""), sn.get("videoOwnerChannelTitle") or sn.get("channelTitle", ""))
            if not parsed:
                continue
            artist, title = parsed
            vid = (sn.get("resourceId") or {}).get("videoId") or it.get("id")
            t = Track(key=track_key(artist, title), title=title, artist=artist,
                      link=f"https://www.youtube.com/watch?v={vid}" if isinstance(vid, str) else "")
            pub = (sn.get("publishedAt") or "")[:4]
            if pub.isdigit() and source == "youtube_chart":
                t.year = int(pub)
            t.sources[source] = {"pos": i + 1}
            out.append(t)
        return out

    def music_chart(self, region: str = "CL", limit: int = 50) -> list[Track]:
        data = self.http.get("youtube", f"{API}/videos", {
            "part": "snippet", "chart": "mostPopular", "regionCode": region, "videoCategoryId": "10",
            "maxResults": min(limit, 50), "key": self.key}, ttl_hours=12)
        return self._items_to_tracks(data.get("items", []), "youtube_chart")

    def playlist_tracks(self, playlist_id: str, limit: int = 100) -> list[Track]:
        items, token = [], None
        while len(items) < limit:
            params = {"part": "snippet", "playlistId": playlist_id, "maxResults": 50, "key": self.key}
            if token:
                params["pageToken"] = token
            data = self.http.get("youtube", f"{API}/playlistItems", params, ttl_hours=24)
            items += data.get("items", [])
            token = data.get("nextPageToken")
            if not token:
                break
        return self._items_to_tracks(items[:limit], "youtube_playlist")
