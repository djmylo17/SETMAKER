"""Normalización de títulos y artistas.

Se usa en dos lugares (por eso es compartido):
- el motor, para deduplicar versiones del mismo tema entre fuentes;
- la biblioteca, para saber si un tema del set ya lo tienes.

Ejemplos:
    "Tití Me Preguntó (Extended Clean)"  -> "titi me pregunto"
    "Bad Bunny feat. Bomba Estéreo"      -> artistas ["bad bunny", "bomba estereo"]
"""
from __future__ import annotations

import re
import unicodedata

# Palabras de "versión" que no cambian el tema (se quitan para comparar)
VERSION_WORDS = [
    "extended", "extended mix", "extended version", "original mix", "radio edit", "radio version",
    "clean", "dirty", "explicit", "intro", "outro", "intro outro", "short edit", "edit",
    "quick hit", "quickhitter", "hype intro", "dj intro", "acapella intro", "transition",
    "remaster", "remastered", "official video", "official audio", "video oficial", "audio oficial",
    "lyric video", "letra", "lyrics", "hd", "hq", "4k", "videoclip", "official music video",
]

# Nombres típicos de pools DJ que aparecen en títulos/archivos
POOL_WORDS = [
    "bpm supreme", "dj city", "djcity", "crooklyn clan", "club killers", "mp3 pool", "zipdj",
    "latin throwback", "dmc", "promo only", "x-mix", "xmix", "heavy hits", "beatfreakz",
    "remix planet", "latino remixes", "dj tools", "acapella", "redrum",
]

FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|con|with|x|&|y|,|vs\.?)\s+", re.I)
BRACKETS_RE = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
NON_ALNUM_RE = re.compile(r"[^a-z0-9ñ ]+")
SPACES_RE = re.compile(r"\s+")
BPM_KEY_RE = re.compile(r"\b\d{2,3}\s?bpm\b|\b\d{1,2}[ab]\b|\b[a-g][#b]?m?\s?-\s?\d{2,3}\b", re.I)


def strip_accents(s: str) -> str:
    # conserva la ñ (no es tilde) pero quita á é í ó ú ü
    s = s.replace("ñ", "\u0000").replace("Ñ", "\u0001")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.replace("\u0000", "ñ").replace("\u0001", "Ñ")


def _clean(s: str) -> str:
    s = strip_accents(s.lower())
    s = s.replace("’", "'").replace("'", "")
    s = NON_ALNUM_RE.sub(" ", s)
    return SPACES_RE.sub(" ", s).strip()


def is_remix_tag(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in ("remix", "rmx", "mashup", "bootleg", "rework", "flip", "cover", "en vivo", "live"))


def normalize_title(title: str, keep_remix: bool = False) -> str:
    """Título limpio para comparar. Quita paréntesis de versión, feats y ruido de pools.

    keep_remix=True deja la info de remix (para distinguir "otra versión").
    """
    if not title:
        return ""
    t = title
    # quitar "feat. X" del título
    t = re.split(r"\s[\(\[]?(?:feat\.?|ft\.?|featuring)\s", t, maxsplit=1, flags=re.I)[0]

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        if keep_remix and is_remix_tag(inner):
            return " " + inner + " "
        return " "

    t = BRACKETS_RE.sub(repl, t)
    # " - Extended Mix" al final
    parts = re.split(r"\s+-\s+", t)
    if len(parts) > 1:
        tail = _clean(parts[-1])
        if any(tail == w or tail.startswith(w) for w in VERSION_WORDS + POOL_WORDS) or (
                not keep_remix and is_remix_tag(tail)):
            t = " - ".join(parts[:-1])
    t = BPM_KEY_RE.sub(" ", t)
    t = _clean(t)
    for w in sorted(VERSION_WORDS + POOL_WORDS, key=len, reverse=True):
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    return SPACES_RE.sub(" ", t).strip()


def split_artists(artist: str) -> list[str]:
    if not artist:
        return []
    parts = FEAT_RE.split(artist)
    out = []
    for p in parts:
        c = _clean(p)
        if c and c not in out:
            out.append(c)
    return out


def main_artist(artist: str) -> str:
    a = split_artists(artist)
    return a[0] if a else ""


def track_key(artist: str, title: str) -> str:
    """Clave estable de un tema (independiente de versión, mayúsculas, tildes y feats)."""
    return f"{main_artist(artist)}|{normalize_title(title)}"


def is_karaoke_text(*texts: str) -> bool:
    return any(t and "karaoke" in t.lower() for t in texts)
