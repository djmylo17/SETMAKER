"""Modelos de datos compartidos por toda la app (contratos entre módulos)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------- tipos de evento
EVENT_TYPES = {
    "cumple_infantil": "Cumpleaños infantil",
    "cumple_adolescente": "Cumpleaños preadolescente / adolescente",
    "quince": "15 años",
    "carrete_juvenil": "Carrete juvenil",
    "urbana_adultos": "Fiesta urbana adultos",
    "matrimonio": "Matrimonio",
    "cumple_adulto": "Cumpleaños 30 / 40 / 50+",
    "empresa": "Fiesta de empresa",
    "familiar": "Bingo / evento familiar",
    "despedida": "Despedida",
    "otro": "Otro",
}


# ---------------------------------------------------------------- géneros
@dataclass
class Genre:
    slug: str
    name: str
    group: str = ""
    description: str = ""            # descripción para la IA
    seed_artists: list[str] = field(default_factory=list)
    lastfm_tags: list[str] = field(default_factory=list)  # tags que indican este género
    search_terms: list[str] = field(default_factory=list)  # para buscar playlists en Deezer/YouTube
    bpm_min: int = 0
    bpm_max: int = 0
    energy: int = 5                  # 1–10 típico
    era_from: int = 0                # años típicos (0 = sin límite)
    era_to: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Genre":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------- perfil de evento
@dataclass
class Block:
    name: str
    start: str = ""                  # "20:00"
    minutes: int = 60
    energy_min: int = 1
    energy_max: int = 10
    genres: list[str] = field(default_factory=list)  # vacío = todos los permitidos
    classics_only: bool = False      # bloque de clásicos


@dataclass
class EventProfile:
    name: str = "Nuevo evento"
    event_date: str = ""
    venue: str = ""
    event_type: str = "otro"
    age_min: int = 18
    age_max: int = 35
    country: str = "CL"
    countries: list[str] = field(default_factory=lambda: ["CL", "AR", "CO", "PR", "PE", "MX", "DO"])
    genre_weights: dict[str, int] = field(default_factory=dict)   # slug -> %
    banned_genres: list[str] = field(default_factory=list)
    banned_artists: list[str] = field(default_factory=list)
    seed_artists: list[str] = field(default_factory=list)         # obligatorios / semilla
    new_pct: int = 60                 # % de temas nuevos
    new_months: int = 12              # "nuevo" = lanzado en los últimos N meses
    classic_year_min: int = 2004
    classic_year_max: int = 2025
    explicit_filter: bool = False     # True = sacar letras explícitas
    blocks: list[Block] = field(default_factory=list)
    track_count: int = 0              # 0 = calcular por duración
    avg_track_minutes: float = 3.0

    @property
    def is_kids(self) -> bool:
        return self.event_type in ("cumple_infantil", "cumple_adolescente") or self.age_min < 14

    def total_minutes(self) -> int:
        return sum(b.minutes for b in self.blocks) or 180

    def target_count(self) -> int:
        if self.track_count > 0:
            return self.track_count
        return max(10, round(self.total_minutes() / max(self.avg_track_minutes, 1.5)))

    def allowed_genres(self) -> list[str]:
        return [g for g, w in self.genre_weights.items() if w > 0 and g not in self.banned_genres]

    def enforce_rules(self) -> "EventProfile":
        """Reglas que no se pueden saltar (ej. infantil = sin explícitos)."""
        if self.is_kids:
            self.explicit_filter = True
        return self

    # ---- serialización
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "EventProfile":
        known = set(cls.__dataclass_fields__)
        data = {k: v for k, v in d.items() if k in known}
        data["blocks"] = [Block(**{k: v for k, v in b.items() if k in Block.__dataclass_fields__})
                          for b in d.get("blocks", [])]
        return cls(**data)

    @classmethod
    def from_json(cls, s: str) -> "EventProfile":
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------- temas
@dataclass
class Track:
    """Un tema candidato reunido desde las fuentes."""
    key: str                          # normalize.track_key(artist, title)
    title: str
    artist: str
    year: int = 0
    release_date: str = ""
    duration: int = 0                 # segundos
    isrc: str = ""
    deezer_id: int = 0
    preview_url: str = ""
    link: str = ""
    bpm: float = 0.0
    explicit: bool | None = None      # según Deezer (None = desconocido)
    sources: dict[str, Any] = field(default_factory=dict)   # fuente -> detalle (rank, playlist…)
    source_genres: list[str] = field(default_factory=list)  # géneros/tags crudos de las fuentes
    trend: float = 0.0                # 0–1 señal de tendencia combinada
    seed_genres: list[str] = field(default_factory=list)    # géneros por los que se buscó

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Classification:
    """Lo que la IA (o el respaldo por tags) dice de un tema. No depende del evento."""
    genres: list[str]                 # slugs de MI taxonomía, el primero es el principal
    year: int = 0
    energy: int = 5
    explicit: bool = False
    min_age: int = 0                  # edad mínima recomendada (0, 10, 14, 18)
    confidence: float = 0.5
    note: str = ""
    method: str = "ia"                # "ia" | "tags"

    @property
    def primary(self) -> str:
        return self.genres[0] if self.genres else "otro"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Classification":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# Estado frente a mi biblioteca
HAVE = "tengo"
OTHER_VERSION = "otra_version"
MISSING = "falta"
UNKNOWN = "sin_revisar"

STATUS_LABELS = {HAVE: "La tengo", OTHER_VERSION: "Otra versión", MISSING: "Me falta", UNKNOWN: "—"}


@dataclass
class SetItem:
    track: Track
    cls: Classification
    block: int = 0
    score: float = 0.0
    is_new: bool = False
    reasons: list[str] = field(default_factory=list)
    status: str = UNKNOWN
    local_paths: list[dict] = field(default_factory=list)   # [{path, format, bitrate, title}]

    def to_dict(self) -> dict:
        return {
            "track": self.track.to_dict(), "cls": self.cls.to_dict(), "block": self.block,
            "score": self.score, "is_new": self.is_new, "reasons": self.reasons,
            "status": self.status, "local_paths": self.local_paths,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SetItem":
        return cls(track=Track.from_dict(d["track"]), cls=Classification.from_dict(d["cls"]),
                   block=d.get("block", 0), score=d.get("score", 0.0), is_new=d.get("is_new", False),
                   reasons=d.get("reasons", []), status=d.get("status", UNKNOWN),
                   local_paths=d.get("local_paths", []))
