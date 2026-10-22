"""Plantillas de evento de fábrica (editables y duplicables desde la app)."""
from __future__ import annotations

from .models import Block, EventProfile
from .taxonomy import ROCK_BALADA

B = Block


def _t(**kw) -> EventProfile:
    return EventProfile(**kw).enforce_rules()


DEFAULT_TEMPLATES: dict[str, EventProfile] = {
    "Carrete juvenil urbano 18–25": _t(
        name="Carrete juvenil urbano", event_type="carrete_juvenil", age_min=18, age_max=25,
        genre_weights={"reggaeton_actual": 30, "urbano_chileno": 20, "guaracha": 10, "rkt": 10, "dembow": 8,
                       "perreo": 7, "trap_latino": 5, "reggaeton_2013_2019": 6, "reggaeton_old": 4},
        banned_genres=ROCK_BALADA + ["pop_anglo", "pop_retro", "cumbia_ranchera", "infantil"],
        new_pct=70, new_months=12, classic_year_min=2004, classic_year_max=2025, explicit_filter=False,
        blocks=[B("Calentamiento", "22:00", 60, 5, 7),
                B("Peak", "23:00", 120, 7, 10),
                B("Clásicos del perreo", "01:00", 60, 6, 9,
                  ["reggaeton_2013_2019", "reggaeton_old", "perreo"], classics_only=True),
                B("Cierre", "02:00", 30, 7, 10)]),
    "Cumpleaños infantil (6–11)": _t(
        name="Cumpleaños infantil", event_type="cumple_infantil", age_min=6, age_max=11,
        genre_weights={"infantil": 40, "viral": 25, "pop_latino": 20, "reggaeton_actual": 10, "pop_anglo": 5},
        banned_genres=ROCK_BALADA + ["perreo", "trap_latino", "dembow", "rkt", "cumbia_villera", "corridos",
                                     "techengue", "mambo_dominicano"],
        new_pct=60, new_months=18, classic_year_min=2010, classic_year_max=2025, explicit_filter=True,
        blocks=[B("Recepción", "16:00", 30, 3, 6),
                B("Juegos y dinámicas", "16:30", 60, 5, 8, ["infantil", "viral"]),
                B("Baile", "17:30", 45, 6, 9),
                B("Torta y cierre", "18:15", 15, 4, 7)]),
    "Cumpleaños preadolescente (10–13)": _t(
        name="Cumpleaños preadolescente", event_type="cumple_adolescente", age_min=10, age_max=13,
        genre_weights={"viral": 25, "pop_latino": 25, "reggaeton_actual": 25, "urbano_chileno": 10,
                       "guaracha": 10, "pop_anglo": 5},
        banned_genres=ROCK_BALADA + ["perreo", "rkt", "cumbia_villera", "trap_latino", "corridos", "infantil"],
        new_pct=80, new_months=12, classic_year_min=2018, classic_year_max=2025, explicit_filter=True,
        blocks=[B("Llegada", "18:00", 30, 4, 7),
                B("Fiesta", "18:30", 90, 6, 9),
                B("Cierre", "20:00", 30, 7, 10)]),
    "15 años": _t(
        name="Fiesta de 15", event_type="quince", age_min=13, age_max=17,
        genre_weights={"reggaeton_actual": 25, "pop_latino": 15, "urbano_chileno": 10, "guaracha": 10,
                       "reggaeton_2013_2019": 10, "viral": 10, "cumbia_chilena": 5, "bachata": 5,
                       "merengue": 5, "pop_anglo": 5},
        banned_genres=ROCK_BALADA + ["perreo", "rkt", "cumbia_villera", "trap_latino"],
        new_pct=65, new_months=12, classic_year_min=2013, classic_year_max=2025, explicit_filter=True,
        blocks=[B("Recepción", "21:00", 45, 3, 6, ["pop_latino", "bachata", "pop_anglo"]),
                B("Fiesta", "21:45", 120, 6, 9),
                B("Hora loca", "23:45", 30, 8, 10),
                B("Cierre", "00:15", 45, 7, 10)]),
    "Matrimonio": _t(
        name="Matrimonio", event_type="matrimonio", age_min=5, age_max=80,
        genre_weights={"reggaeton_2013_2019": 15, "reggaeton_old": 10, "reggaeton_actual": 10,
                       "cumbia_chilena": 15, "cumbia_peruana": 5, "salsa": 10, "merengue": 5, "bachata": 5,
                       "pop_retro": 15, "pop_latino": 5, "edm": 5},
        banned_genres=["perreo", "rkt", "trap_latino", "cumbia_villera", "dembow", "trova_folclore", "otro"],
        new_pct=25, new_months=12, classic_year_min=1980, classic_year_max=2025, explicit_filter=True,
        blocks=[B("Cóctel", "20:00", 60, 2, 5, ["pop_latino", "bachata", "pop_retro"]),
                B("Cena", "21:00", 60, 2, 4, ["pop_latino", "bachata", "pop_retro", "salsa"]),
                B("Apertura de pista", "22:00", 60, 6, 8),
                B("Fiesta", "23:00", 120, 7, 10),
                B("Hora loca", "01:00", 30, 8, 10),
                B("Cierre", "01:30", 30, 6, 9)]),
    "Fiesta urbana adultos 25–35": _t(
        name="Fiesta urbana adultos", event_type="urbana_adultos", age_min=25, age_max=35,
        genre_weights={"reggaeton_actual": 25, "reggaeton_2013_2019": 20, "reggaeton_old": 15,
                       "urbano_chileno": 10, "perreo": 10, "dembow": 5, "guaracha": 5, "trap_latino": 5, "rkt": 5},
        banned_genres=ROCK_BALADA + ["infantil", "cumbia_ranchera"],
        new_pct=40, new_months=12, classic_year_min=2004, classic_year_max=2025, explicit_filter=False,
        blocks=[B("Calentamiento", "23:00", 60, 5, 7),
                B("Peak", "00:00", 120, 7, 10),
                B("Old school", "02:00", 60, 7, 9, ["reggaeton_old", "reggaeton_2013_2019"], classics_only=True)]),
    "Cumpleaños 30 / 40 / 50+": _t(
        name="Cumpleaños adulto", event_type="cumple_adulto", age_min=30, age_max=60,
        genre_weights={"pop_retro": 25, "cumbia_chilena": 15, "reggaeton_old": 15, "salsa": 10, "merengue": 10,
                       "reggaeton_2013_2019": 10, "rock_espanol": 10, "bachata": 5},
        banned_genres=["perreo", "rkt", "trap_latino", "dembow", "trova_folclore", "otro"],
        new_pct=15, new_months=12, classic_year_min=1980, classic_year_max=2025, explicit_filter=False,
        blocks=[B("Recepción", "21:00", 60, 3, 6),
                B("Fiesta", "22:00", 150, 6, 10),
                B("Cierre", "00:30", 30, 6, 9)]),
    "Fiesta de empresa": _t(
        name="Fiesta de empresa", event_type="empresa", age_min=22, age_max=60,
        genre_weights={"pop_latino": 15, "pop_retro": 20, "reggaeton_2013_2019": 15, "cumbia_chilena": 15,
                       "salsa": 10, "merengue": 5, "edm": 10, "reggaeton_old": 10},
        banned_genres=["perreo", "rkt", "cumbia_villera", "trap_latino", "dembow", "trova_folclore", "otro"],
        new_pct=25, new_months=12, classic_year_min=1980, classic_year_max=2025, explicit_filter=True,
        blocks=[B("Cóctel", "20:00", 60, 2, 5, ["pop_latino", "pop_retro"]),
                B("Fiesta", "21:00", 150, 6, 10),
                B("Cierre", "23:30", 30, 6, 9)]),
    "Bingo / evento familiar": _t(
        name="Bingo familiar", event_type="familiar", age_min=5, age_max=80,
        genre_weights={"cumbia_chilena": 25, "cumbia_ranchera": 15, "cumbia_peruana": 10, "pop_retro": 15,
                       "merengue": 10, "salsa": 10, "reggaeton_old": 5, "viral": 5, "infantil": 5},
        banned_genres=["perreo", "rkt", "trap_latino", "dembow", "cumbia_villera", "otro"],
        new_pct=15, new_months=12, classic_year_min=1970, classic_year_max=2025, explicit_filter=True,
        blocks=[B("Bingo", "19:00", 120, 3, 7), B("Baile", "21:00", 90, 6, 9)]),
    "Despedida": _t(
        name="Despedida", event_type="despedida", age_min=20, age_max=40,
        genre_weights={"reggaeton_actual": 20, "reggaeton_2013_2019": 20, "reggaeton_old": 15, "perreo": 10,
                       "urbano_chileno": 10, "pop_latino": 10, "guaracha": 5, "cumbia_chilena": 10},
        banned_genres=ROCK_BALADA + ["infantil"],
        new_pct=40, new_months=12, classic_year_min=2004, classic_year_max=2025, explicit_filter=False,
        blocks=[B("Previa", "22:00", 60, 5, 8), B("Fiesta", "23:00", 150, 7, 10)]),
}
