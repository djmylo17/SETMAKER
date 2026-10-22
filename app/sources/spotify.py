"""Crear playlists en la cuenta de Spotify del DJ.

Cómo funciona la conexión (Authorization Code + PKCE, sin "client secret"):
1. Se abre el navegador en la página de Spotify para que el DJ acepte los permisos.
2. Spotify vuelve a http://127.0.0.1:8765/callback; SETMAKER levanta un mini servidor
   local de un solo uso para recibir ese "code".
3. El code se cambia por un access token (dura ~1 hora) y un refresh token, que se guarda
   cifrado en la bóveda (clave 'spotify_refresh_token'). Spotify puede entregar un refresh
   token nuevo cada vez que se renueva: siempre se guarda el último.

Endpoints vigentes desde la migración de febrero 2026 (apps en "Development Mode"):
- Crear playlist:   POST /v1/me/playlists          (ya no /users/{id}/playlists)
- Agregar temas:    POST /v1/playlists/{id}/items  (antes /tracks), máx. 100 uris por llamada
- Buscar:           GET  /v1/search?type=track     (limit máximo 10)
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import logging
import secrets
import threading
import time
import webbrowser
from difflib import SequenceMatcher
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from ..core.models import MISSING, OTHER_VERSION, SetItem
from ..core.normalize import normalize_title, split_artists
from ..net import USER_AGENT, SourceError
from .checks import SPOTIFY_REDIRECT_URI

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-private playlist-modify-public"
REFRESH_KEY = "spotify_refresh_token"
CALLBACK_HOST, CALLBACK_PORT = "127.0.0.1", 8765
SEARCH_LIMIT = 5          # el máximo permitido ahora es 10
ADD_CHUNK = 100           # máximo de uris por llamada al agregar
MAX_RETRY_WAIT = 30       # segundos máximos que esperamos si Spotify pide pausa (429)

_DONE_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>SETMAKER</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;background:#0d0f14;color:#e8ebf2;
text-align:center;padding-top:15vh">
<h1 style="color:#2fe0a0">Listo, ya puedes volver a SETMAKER</h1>
<p>{msg}</p><p style="color:#8a93a6">Puedes cerrar esta pestaña.</p></body></html>"""


# ---------------------------------------------------------------- elegir el mejor resultado
def _title_score(wanted: str, found: str) -> float:
    a, b = normalize_title(wanted), normalize_title(found)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def _artist_score(wanted: str, found_artists: list[str]) -> float:
    want = split_artists(wanted)
    got: list[str] = []
    for name in found_artists:
        got.extend(split_artists(name))
    if not want or not got:
        return 0.0
    if want[0] in got:
        return 1.0
    if any(w in got for w in want):
        return 0.8
    return max(SequenceMatcher(None, w, g).ratio() for w in want for g in got)


def match_score(artist: str, title: str, candidate: dict) -> float:
    """Puntaje 0–1 de qué tanto un resultado de Spotify coincide con el tema buscado."""
    names = [a.get("name", "") for a in candidate.get("artists", []) or []]
    t = _title_score(title, candidate.get("name", ""))
    a = _artist_score(artist, names)
    if t < 0.6 or a < 0.6:
        return 0.0
    score = 0.6 * t + 0.4 * a
    # Leve castigo si el resultado es un remix/en vivo y lo buscado no
    found_full = (candidate.get("name") or "").lower()
    if any(w in found_full for w in ("remix", "live", "en vivo", "karaoke", "instrumental")) and \
            not any(w in title.lower() for w in ("remix", "live", "en vivo", "karaoke", "instrumental")):
        score -= 0.15
    return max(score, 0.0)


def pick_best_match(artist: str, title: str, candidates: list[dict],
                    min_score: float = 0.7) -> dict | None:
    """Devuelve el resultado con mejor puntaje (o None si ninguno se parece lo suficiente)."""
    best, best_score = None, 0.0
    for c in candidates or []:
        if not c or not c.get("uri"):
            continue
        s = match_score(artist, title, c)
        if s > best_score:
            best, best_score = c, s
    return best if best_score >= min_score else None


# ---------------------------------------------------------------- PKCE
def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge.decode("ascii").rstrip("=")


# ---------------------------------------------------------------- mini servidor local
class _CallbackServer(http.server.HTTPServer):
    allow_reuse_address = True
    result: dict | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — nombre exigido por http.server
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.server.result = params  # type: ignore[attr-defined]
        msg = ("SETMAKER quedó conectado a tu Spotify." if "code" in params
               else "No se completó la conexión. Vuelve a SETMAKER para ver el detalle.")
        body = _DONE_HTML.format(msg=msg).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # sin ruido en la consola (y sin registrar el code)
        pass


# ---------------------------------------------------------------- cliente
class SpotifyClient:
    def __init__(self, vault, client_id: str, http: httpx.Client | None = None):
        self.vault = vault
        self.client_id = (client_id or "").strip()
        self._http = http
        self._token = ""
        self._token_exp = 0.0

    # ---------- estado ----------
    def is_connected(self) -> bool:
        try:
            return bool(self.vault.get(REFRESH_KEY))
        except Exception:  # noqa: BLE001 — bóveda bloqueada = no conectado
            return False

    def disconnect(self) -> None:
        self.vault.set(REFRESH_KEY, "")
        self._token, self._token_exp = "", 0.0

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0),
                                      headers={"User-Agent": USER_AGENT})
        return self._http

    # ---------- conectar ----------
    def build_auth_url(self, state: str, challenge: str) -> str:
        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id, "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT_URI, "scope": SCOPES, "state": state,
            "code_challenge_method": "S256", "code_challenge": challenge,
        })

    def connect(self, timeout: int = 180) -> bool:
        """Abre el navegador y espera la respuesta de Spotify. Bloquea: llamar en segundo plano."""
        if not self.client_id:
            raise SourceError("Falta el Client ID de Spotify. Agrégalo en «Fuentes y claves».")
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        try:
            server = _CallbackServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
        except OSError as exc:
            raise SourceError("No se pudo abrir el puerto 8765 en este PC. Cierra otras ventanas de "
                              "conexión de SETMAKER y vuelve a intentar.") from exc
        server.timeout = 1.0
        server.result = None

        # El servidor atiende en su propio hilo; este hilo espera con un límite de tiempo.
        stop = threading.Event()

        def serve():
            while not stop.is_set() and server.result is None:
                server.handle_request()

        th = threading.Thread(target=serve, name="spotify-callback", daemon=True)
        th.start()
        try:
            webbrowser.open(self.build_auth_url(state, challenge))
            deadline = time.monotonic() + timeout
            while server.result is None and time.monotonic() < deadline:
                time.sleep(0.2)
        finally:
            stop.set()
            th.join(timeout=2)
            server.server_close()

        res = server.result
        if res is None:
            raise SourceError("Se acabó el tiempo de espera. Vuelve a intentar y acepta los permisos "
                              "en la ventana de Spotify.")
        if res.get("state") != state:
            raise SourceError("La respuesta de Spotify no coincide con la solicitud (por seguridad se "
                              "canceló). Vuelve a intentar.")
        if "error" in res:
            if res["error"] == "access_denied":
                raise SourceError("Cancelaste los permisos en Spotify. No se conectó.")
            raise SourceError(f"Spotify no permitió la conexión ({res['error']}). Revisa que en tu app "
                              f"de Spotify esté la Redirect URI {SPOTIFY_REDIRECT_URI}")
        code = res.get("code")
        if not code:
            raise SourceError("Spotify no envió el código de conexión. Vuelve a intentar.")
        data = self._token_request({
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": SPOTIFY_REDIRECT_URI, "client_id": self.client_id,
            "code_verifier": verifier,
        })
        self._store_tokens(data)
        return True

    # ---------- tokens ----------
    def _token_request(self, form: dict) -> dict:
        try:
            r = self._client().post(TOKEN_URL, data=form,
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        except httpx.TransportError as exc:
            raise SourceError("No hay conexión a internet o Spotify no responde.") from exc
        if r.status_code >= 400:
            err = ""
            try:
                err = r.json().get("error", "")
            except ValueError:
                pass
            if err == "invalid_grant":
                # refresh token vencido o revocado: hay que conectar de nuevo
                try:
                    self.vault.set(REFRESH_KEY, "")
                except Exception:  # noqa: BLE001
                    pass
                raise SourceError("La conexión con Spotify venció. Vuelve a conectar tu cuenta en Ajustes.")
            if err == "invalid_client":
                raise SourceError("El Client ID de Spotify no es válido. Revísalo en «Fuentes y claves».")
            raise SourceError(f"Spotify rechazó la conexión ({r.status_code}). Intenta conectar de nuevo.")
        return r.json()

    def _store_tokens(self, data: dict) -> None:
        self._token = data.get("access_token", "")
        self._token_exp = time.time() + int(data.get("expires_in", 3600)) - 60
        new_refresh = data.get("refresh_token")
        if new_refresh:          # Spotify puede rotarlo: siempre guardar el último
            self.vault.set(REFRESH_KEY, new_refresh)

    def _access_token(self, force: bool = False) -> str:
        if self._token and not force and time.time() < self._token_exp:
            return self._token
        refresh = self.vault.get(REFRESH_KEY)
        if not refresh:
            raise SourceError("Spotify no está conectado. Conéctalo en Ajustes → Salidas.")
        data = self._token_request({"grant_type": "refresh_token", "refresh_token": refresh,
                                    "client_id": self.client_id})
        self._store_tokens(data)
        return self._token

    # ---------- llamadas a la API ----------
    def _api(self, method: str, path: str, *, params: dict | None = None,
             json: Any = None) -> Any:
        url = path if path.startswith("http") else API + path
        refreshed = False
        for _attempt in range(4):
            headers = {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json"}
            try:
                r = self._client().request(method, url, params=params, json=json, headers=headers)
            except httpx.TimeoutException as exc:
                raise SourceError("Spotify tardó demasiado en responder. Revisa tu internet.") from exc
            except httpx.TransportError as exc:
                raise SourceError("No hay conexión a internet o Spotify no responde.") from exc
            if r.status_code == 401 and not refreshed:
                refreshed = True
                self._access_token(force=True)
                continue
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "5") or 5)
                if wait > MAX_RETRY_WAIT:
                    raise SourceError(f"Spotify pidió esperar {wait // 60 + 1} minutos por exceso de uso. "
                                      "Intenta más tarde.")
                time.sleep(max(wait, 1))
                continue
            if r.status_code == 401:
                raise SourceError("Spotify rechazó la conexión. Desconecta y vuelve a conectar tu cuenta.")
            if r.status_code == 403:
                raise SourceError("Spotify no dio permiso. Revisa que tu cuenta esté agregada en "
                                  "«User Management» de tu app en developer.spotify.com y vuelve a conectar.")
            if r.status_code >= 500:
                raise SourceError("Spotify está con problemas en este momento. Intenta más tarde.")
            if r.status_code >= 400:
                raise SourceError(f"Spotify respondió con un error ({r.status_code}).")
            if not r.content:
                return {}
            try:
                return r.json()
            except ValueError:
                return {}
        raise SourceError("Spotify está muy ocupado. Intenta de nuevo en unos minutos.")

    def search_track(self, artist: str, title: str, isrc: str = "") -> dict | None:
        """Busca un tema y devuelve el mejor resultado (dict de Spotify) o None."""
        queries = []
        if isrc:
            queries.append(f"isrc:{isrc}")
        clean_title = title.replace('"', "")
        clean_artist = artist.replace('"', "")
        queries.append(f'track:"{clean_title}" artist:"{clean_artist}"')
        queries.append(f"{clean_artist} {clean_title}")
        for q in queries:
            data = self._api("GET", "/search", params={"q": q, "type": "track", "limit": SEARCH_LIMIT})
            items = ((data or {}).get("tracks") or {}).get("items") or []
            best = pick_best_match(artist, title, items, min_score=0.6 if q.startswith("isrc:") else 0.7)
            if best:
                return best
        return None

    def create_playlist_from_items(self, items: list[SetItem], name: str, description: str = "",
                                   only_missing: bool = False,
                                   progress: Callable[[int, int], None] | None = None) -> dict:
        """Busca cada tema en Spotify y crea una playlist privada con los encontrados.

        progress(hechos, total) se llama después de cada búsqueda.
        Devuelve {"url", "added", "not_found": ["artista - título", ...]}.
        """
        chosen = [i for i in items if not only_missing or i.status in (MISSING, OTHER_VERSION)]
        if not chosen:
            raise SourceError("No hay temas para la playlist.")
        uris: list[str] = []
        not_found: list[str] = []
        total = len(chosen)
        for n, it in enumerate(chosen, start=1):
            t = it.track
            hit = self.search_track(t.artist, t.title, t.isrc)
            if hit and hit["uri"] not in uris:
                uris.append(hit["uri"])
            elif not hit:
                not_found.append(f"{t.artist} - {t.title}")
            if progress:
                progress(n, total)
        if not uris:
            raise SourceError("No se encontró ninguno de los temas en Spotify.")

        pl = self._api("POST", "/me/playlists", json={
            "name": name[:100] or "SETMAKER", "description": (description or "")[:300], "public": False,
        })
        pid = pl.get("id")
        if not pid:
            raise SourceError("Spotify no devolvió la playlist creada.")
        for i in range(0, len(uris), ADD_CHUNK):
            self._api("POST", f"/playlists/{pid}/items", json={"uris": uris[i:i + ADD_CHUNK]})
        url = (pl.get("external_urls") or {}).get("spotify") or f"https://open.spotify.com/playlist/{pid}"
        return {"url": url, "added": len(uris), "not_found": not_found}
