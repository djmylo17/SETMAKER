"""Links de búsqueda para conseguir un tema que falta (YouTube, Spotify, Beatport, pool DJ)."""
from __future__ import annotations

from urllib.parse import quote, quote_plus

POOL_URL_KEY = "links.pool_url"
POOL_NAME_KEY = "links.pool_name"
DEFAULT_POOL_NAME = "Mi pool"


def pool_settings(config) -> tuple[str, str]:
    """(nombre, plantilla) del pool configurado en Ajustes."""
    name = (config.get(POOL_NAME_KEY, "") or "").strip() or DEFAULT_POOL_NAME
    url = (config.get(POOL_URL_KEY, "") or "").strip()
    return name, url


def pool_link(artist: str, title: str, template: str) -> str:
    """Rellena {artista}, {titulo} y {query} de la plantilla. Vacío si no hay marcadores."""
    template = (template or "").strip()
    if not template or not any(k in template for k in ("{artista}", "{titulo}", "{query}")):
        return ""
    query = f"{artist} {title}".strip()
    # Si va en la parte "?q=..." se usa quote_plus (espacios como +); si va en la ruta, quote (%20)
    in_query = "?" in template and template.index("?") < min(
        (template.index(k) for k in ("{artista}", "{titulo}", "{query}") if k in template))
    enc = quote_plus if in_query else (lambda s: quote(s, safe=""))
    return (template.replace("{artista}", enc(artist or ""))
            .replace("{titulo}", enc(title or ""))
            .replace("{query}", enc(query)))


def search_links(artist: str, title: str, pool_template: str = "",
                 pool_name: str = DEFAULT_POOL_NAME) -> list[tuple[str, str]]:
    """Lista de (etiqueta, url) para buscar el tema."""
    q = f"{artist} {title}".strip()
    links = [
        ("YouTube", "https://www.youtube.com/results?search_query=" + quote_plus(q)),
        ("Spotify", "https://open.spotify.com/search/" + quote(q, safe="")),
        ("Beatport", "https://www.beatport.com/search?q=" + quote_plus(q)),
    ]
    pool = pool_link(artist, title, pool_template)
    if pool:
        links.append((pool_name or DEFAULT_POOL_NAME, pool))
    return links
