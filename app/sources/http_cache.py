"""Cliente HTTP con caché en SQLite y control de velocidad por fuente.

Todo lo consultado se guarda en api_cache, así no se repiten llamadas ni se gasta cuota.
Las claves de API nunca forman parte de la clave de caché ni de los logs.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

import httpx

from ..db.database import Database
from ..net import DEFAULT_TIMEOUT, SourceError, get_json

SECRET_PARAMS = {"key", "api_key", "apikey", "token", "access_token"}

# segundos mínimos entre llamadas reales por fuente (Deezer: 50 req / 5 s)
MIN_INTERVAL = {"deezer": 0.12, "lastfm": 0.21, "apple": 0.3, "youtube": 0.1, "gemini": 0.0}


class CachedHTTP:
    def __init__(self, db: Database):
        self.db = db
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self.calls = 0          # llamadas reales (para mostrar en el resumen)
        self.cache_hits = 0

    def _cache_key(self, url: str, params: dict | None) -> str:
        safe = {k: v for k, v in (params or {}).items() if k.lower() not in SECRET_PARAMS}
        raw = url + "?" + json.dumps(safe, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get(self, source: str, url: str, params: dict | None = None, ttl_hours: float = 24,
            headers: dict | None = None) -> Any:
        key = self._cache_key(url, params)
        cached = self.db.cache_get(source, key, max_age_hours=ttl_hours)
        if cached is not None:
            self.cache_hits += 1
            return cached
        with self._lock:
            wait = MIN_INTERVAL.get(source, 0.1) - (time.monotonic() - self._last.get(source, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[source] = time.monotonic()
        data = None
        for attempt in range(3):
            try:
                data = get_json(url, params, headers=headers, client=self.client)
                break
            except SourceError as exc:
                # límite de uso: esperar y reintentar
                if "límite" in str(exc) and attempt < 2:
                    time.sleep(2 + attempt * 3)
                    continue
                raise
        self.calls += 1
        # Deezer devuelve errores con HTTP 200: {"error": {...}}
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            code = data["error"].get("code")
            if code == 4:  # quota
                time.sleep(5)
                return self.get(source, url, params, ttl_hours, headers)
            raise SourceError(f"{source}: {data['error'].get('message', 'error')}")
        if isinstance(data, dict) and "error" in data and not isinstance(data.get("error"), dict):
            return data   # error de Last.fm (ej. clave mala): no se guarda en caché
        self.db.cache_put(source, key, data)
        return data

    def close(self):
        self.client.close()
