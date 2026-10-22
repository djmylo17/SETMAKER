"""Clasificación de respaldo sin IA (tags de Last.fm, géneros de Apple y artistas semilla).

Es menos precisa: si no encuentra evidencia clara, el tema queda como "otro" y NO entra al set.
Mejor un set más corto que uno con temas fuera de lugar.
"""
from __future__ import annotations

from datetime import date

from ..core.models import Classification, Genre, Track
from ..core.normalize import _clean, split_artists

# Géneros de Apple Music -> géneros posibles de la taxonomía
APPLE_MAP = {
    "música urbana latina": ["reggaeton_actual"], "urbano latino": ["reggaeton_actual"],
    "latin urban": ["reggaeton_actual"], "reggaeton": ["reggaeton_actual"],
    "pop latino": ["pop_latino"], "latin pop": ["pop_latino"], "pop": ["pop_anglo"],
    "rock y alternativo": ["rock_espanol"], "rock": ["rock_anglo"], "alternativo": ["rock_anglo"],
    "regional mexicano": ["corridos"], "música mexicana": ["corridos"], "tropical": ["cumbia_chilena"],
    "salsa y tropical": ["salsa"], "cumbia": ["cumbia_chilena"], "hip-hop/rap": ["trap_latino"],
    "dance": ["edm"], "electrónica": ["edm"], "infantil": ["infantil"], "música infantil": ["infantil"],
    "children's music": ["infantil"], "baladas y boleros": ["baladas"], "cantautores": ["trova_folclore"],
}

REGGAETON_FAMILY = {"reggaeton_actual", "reggaeton_2013_2019", "reggaeton_old"}


class TagClassifier:
    def __init__(self, genres: list[Genre]):
        self.genres = {g.slug: g for g in genres}
        self.artist_index: dict[str, list[str]] = {}
        for g in genres:
            for a in g.seed_artists:
                self.artist_index.setdefault(_clean(a), []).append(g.slug)
        self.tag_index: dict[str, list[str]] = {}
        for g in genres:
            for t in g.lastfm_tags:
                self.tag_index.setdefault(_clean(t), []).append(g.slug)

    def classify(self, t: Track, artist_tags: list[str] | None = None) -> Classification:
        votes: dict[str, float] = {}

        def vote(slug: str, w: float):
            if slug in self.genres:
                votes[slug] = votes.get(slug, 0) + w

        # 1) artista semilla (señal más fuerte)
        for a in split_artists(t.artist)[:2]:
            for slug in self.artist_index.get(a, []):
                vote(slug, 3.0)
        # 2) tags de Last.fm del artista y de la fuente
        tags = [_clean(x) for x in (artist_tags or []) + (t.source_genres or [])]
        for i, tag in enumerate(tags):
            w = 1.5 if i < 3 else 0.8
            for slug in self.tag_index.get(tag, []):
                vote(slug, w / max(1, len(self.tag_index.get(tag, [])) ** 0.5))
            for name, slugs in APPLE_MAP.items():
                if tag == _clean(name):
                    for slug in slugs:
                        vote(slug, 1.0)
        # 3) género por el que se buscó el candidato (señal débil)
        for slug in t.seed_genres:
            vote(slug, 0.7)

        if not votes or max(votes.values()) < 1.4:
            return Classification(genres=["otro"], year=t.year, energy=5, explicit=bool(t.explicit),
                                  min_age=18 if t.explicit else 0, confidence=0.2,
                                  note="sin evidencia suficiente", method="tags")

        # reggaetón: elegir época por año
        if any(s in REGGAETON_FAMILY for s in votes) and t.year:
            era = ("reggaeton_old" if t.year <= 2012 else
                   "reggaeton_2013_2019" if t.year <= 2019 else
                   "reggaeton_actual" if t.year >= 2022 else None)
            if era:
                total = sum(votes.pop(s, 0) for s in list(votes) if s in REGGAETON_FAMILY)
                votes[era] = total

        ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
        top = ranked[0][1]
        genres = [s for s, v in ranked if v >= top * 0.5][:3]
        g0 = self.genres[genres[0]]
        energy = g0.energy
        conf = min(0.7, 0.35 + top / 10)
        return Classification(genres=genres, year=t.year, energy=energy, explicit=bool(t.explicit),
                              min_age=18 if t.explicit else 0, confidence=conf,
                              note="clasificado por tags", method="tags")


def is_new(year: int, release_date: str, months: int, today: date | None = None) -> bool:
    today = today or date.today()
    if release_date and len(release_date) >= 10:
        try:
            y, m, d = (int(x) for x in release_date[:10].split("-"))
            age_days = (today - date(y, m, d)).days
            return age_days <= months * 30.5
        except ValueError:
            pass
    if year:
        return (today.year - year) * 12 <= months
    return False
