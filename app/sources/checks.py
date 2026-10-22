"""Pruebas de conexión para cada fuente (botón "Probar" en Fuentes y claves).

Cada prueba hace UNA consulta mínima y devuelve un CheckResult con un mensaje simple.
Nunca se registran las claves en los logs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..net import SourceError, get_json


@dataclass
class CheckResult:
    ok: bool
    message: str
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- Gemini
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _version_tuple(name: str) -> tuple[int, ...]:
    m = re.search(r"gemini-(\d+(?:\.\d+)*)", name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def choose_default_model(names: list[str]) -> str:
    """Elige el Flash estable más nuevo (sin 'preview', 'exp', 'lite', 'live', 'tts', 'image').

    Si no hay estables, el Flash más nuevo que haya. Si no hay Flash, cadena vacía.
    """
    flash = [n for n in names if "flash" in n]
    banned = ("preview", "exp", "lite", "live", "tts", "image", "audio", "thinking", "8b")
    stable = [n for n in flash if not any(b in n for b in banned)]
    pool = stable or [n for n in flash if not any(b in n for b in ("live", "tts", "image", "audio"))]
    if not pool:
        return ""
    return sorted(pool, key=lambda n: (_version_tuple(n), -len(n)), reverse=True)[0]


def check_gemini(api_key: str) -> CheckResult:
    if not api_key:
        return CheckResult(False, "Falta la clave.")
    try:
        data = get_json(GEMINI_MODELS_URL, {"pageSize": 200}, headers={"x-goog-api-key": api_key})
    except SourceError as exc:
        return CheckResult(False, str(exc))
    names = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(m.get("name", "").removeprefix("models/"))
    flash = sorted((n for n in names if "flash" in n), key=_version_tuple, reverse=True)
    if not flash:
        return CheckResult(False, "La clave funciona, pero no hay modelos Flash disponibles.")
    best = choose_default_model(flash)
    return CheckResult(True, f"Clave válida. Modelo recomendado: {best}", {"models": flash, "default": best})


# ---------------------------------------------------------------- Last.fm
LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"


def check_lastfm(api_key: str) -> CheckResult:
    if not api_key:
        return CheckResult(False, "Falta la clave.")
    try:
        data = get_json(LASTFM_URL, {"method": "tag.gettoptracks", "tag": "reggaeton",
                                     "limit": 1, "api_key": api_key, "format": "json"})
    except SourceError as exc:
        return CheckResult(False, str(exc))
    if isinstance(data, dict) and "error" in data:
        return CheckResult(False, f"Last.fm rechazó la clave: {data.get('message', 'error')}")
    return CheckResult(True, "Clave válida. Last.fm responde correctamente.")


# ---------------------------------------------------------------- YouTube
YOUTUBE_URL = "https://www.googleapis.com/youtube/v3/videos"


def check_youtube(api_key: str) -> CheckResult:
    if not api_key:
        return CheckResult(False, "Falta la clave.")
    try:
        # chart=mostPopular cuesta 1 unidad de cuota (de 10.000 diarias)
        get_json(YOUTUBE_URL, {"part": "id", "chart": "mostPopular", "regionCode": "CL",
                               "videoCategoryId": "10", "maxResults": 1, "key": api_key})
    except SourceError as exc:
        return CheckResult(False, str(exc))
    return CheckResult(True, "Clave válida. YouTube responde correctamente.")


# ---------------------------------------------------------------- Spotify
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8765/callback"


def check_spotify_client_id(client_id: str) -> CheckResult:
    if not client_id:
        return CheckResult(False, "Falta el Client ID.")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", client_id.strip()):
        return CheckResult(False, "El Client ID debe tener 32 caracteres (letras a-f y números).")
    return CheckResult(True, "Formato correcto. La conexión con tu cuenta se activa en la Fase 5.")


# ---------------------------------------------------------------- sin clave
DEEZER_CHART_URL = "https://api.deezer.com/chart/0/tracks"
APPLE_RSS_URL = "https://rss.marketingtools.apple.com/api/v2/{country}/music/most-played/{limit}/songs.json"


def check_deezer() -> CheckResult:
    try:
        data = get_json(DEEZER_CHART_URL, {"limit": 1})
    except SourceError as exc:
        return CheckResult(False, str(exc))
    if isinstance(data, dict) and "error" in data:
        return CheckResult(False, "Deezer respondió con un error. Intenta más tarde.")
    return CheckResult(True, "Deezer responde correctamente.")


def check_apple(country: str = "cl") -> CheckResult:
    try:
        data = get_json(APPLE_RSS_URL.format(country=country.lower(), limit=10))
    except SourceError as exc:
        return CheckResult(False, str(exc))
    n = len(data.get("feed", {}).get("results", []))
    if not n:
        return CheckResult(False, "Apple Music respondió, pero sin canciones para ese país.")
    return CheckResult(True, f"Apple Music responde ({n} canciones en el top de prueba).")
