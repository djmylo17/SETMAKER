"""Conexiones a internet con mensajes de error en lenguaje simple."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"SETMAKER/{__version__} (+https://github.com/djmylo17/setmaker)"
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


class SourceError(Exception):
    """Error de una fuente externa, con mensaje listo para mostrar al usuario."""


def friendly_status(status: int) -> str:
    if status in (400, 401, 403):
        return "La clave no es válida o no tiene permiso para este servicio."
    if status == 404:
        return "El servicio no encontró lo pedido (puede que haya cambiado)."
    if status == 429:
        return "Se alcanzó el límite de uso del servicio. Espera un rato y vuelve a intentar."
    if status >= 500:
        return "El servicio está con problemas en este momento. Intenta más tarde."
    return f"El servicio respondió con un error ({status})."


def get_json(url: str, params: dict[str, Any] | None = None, *, timeout=DEFAULT_TIMEOUT,
             headers: dict[str, str] | None = None, client: httpx.Client | None = None) -> Any:
    """GET que devuelve JSON o lanza SourceError con un mensaje entendible."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    own = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        resp = client.get(url, params=params, headers=hdrs)
    except httpx.TimeoutException as exc:
        raise SourceError("El servicio tardó demasiado en responder. Revisa tu internet.") from exc
    except httpx.TransportError as exc:
        raise SourceError("No hay conexión a internet o el servicio no responde.") from exc
    finally:
        if own:
            client.close()
    if resp.status_code >= 400:
        log.info("HTTP %s en %s", resp.status_code, url.split("?")[0])
        raise SourceError(friendly_status(resp.status_code))
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError("El servicio respondió algo inesperado.") from exc
