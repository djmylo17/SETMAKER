"""Motor de generación de sets (pipeline anti-errores).

1. Candidatos   — por género permitido (artistas semilla, playlists del género, tags) + tendencias + curadas
2. Deduplicar   — misma canción en varias fuentes/versiones = un solo tema
3. Clasificar   — Gemini (caché) o respaldo por tags
4. Filtros duros A — género, vetos, explícito, edad, confianza (NUNCA se saltan)
5. Enriquecer   — Deezer: año, BPM, ISRC, explícito, preview
6. Filtros duros B — años / nuevo-clásico, explícito según Deezer
7. Puntaje      — tendencia, presencia en fuentes, relevancia Chile/Latam, aprendizaje
8. Armado       — por bloques, cuotas de género y nuevo/clásico, energía y artistas alternados
9. Validación   — se revisa el set completo otra vez y se arma el resumen
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ..ai.fallback import TagClassifier, is_new
from ..core.models import Classification, EventProfile, Genre, SetItem, Track
from ..core.normalize import main_artist, split_artists
from ..core.store import LearnedRules
from ..sources.lastfm import COUNTRY_NAMES

log = logging.getLogger(__name__)

JUNK_RE = re.compile(r"\b(karaoke|instrumental|slowed|sped up|speed up|8d|reverb|nightcore|cover|tribute|"
                     r"en vivo|live at|acapella|a capella)\b", re.I)
MAX_CLASSIFY = 700
MIN_CONFIDENCE = 0.35

# peso de cada fuente en la señal de tendencia
SOURCE_WEIGHT = {"deezer_chart": 0.6, "youtube_chart": 0.6, "curada": 0.6, "artista_semilla": 0.5,
                 "deezer_playlist": 0.3, "deezer_artista": 0.3, "lastfm_tag": 0.2, "youtube_playlist": 0.4}


@dataclass
class GenerationResult:
    items: list[SetItem]
    summary: dict
    discarded: list[dict]
    warnings: list[str]
    pool: list[SetItem] = field(default_factory=list)   # aptos no usados (para reemplazos)


class Cancelled(Exception):
    pass


# ======================================================================= filtros duros
def year_of(t: Track, c: Classification) -> int:
    if c.method == "ia" and c.year:
        return c.year
    return t.year or c.year


def hard_filter_a(p: EventProfile, t: Track, c: Classification, rules: LearnedRules | None,
                  banned_artists: set[str]) -> str | None:
    """Devuelve el motivo de descarte o None si pasa."""
    allowed = set(p.allowed_genres())
    banned = set(p.banned_genres)
    if c.primary not in allowed:
        return f"Género {c.primary} no está permitido en este evento"
    hit = [g for g in c.genres if g in banned]
    if hit:
        return f"Género vetado: {', '.join(hit)}"
    if c.confidence < MIN_CONFIDENCE:
        return "La IA no reconoce bien el tema (confianza baja)"
    arts = set(split_artists(t.artist))
    if arts & banned_artists:
        return "Artista vetado"
    if rules:
        if t.key in rules.banned_tracks:
            return "Tema vetado para este tipo de evento"
        if t.key in rules.disliked:
            return "Lo marcaste 👎 en este tipo de evento"
    if p.explicit_filter and (c.explicit or t.explicit is True):
        return "Letra explícita (filtro activado)"
    if p.age_min < 18 and c.min_age > p.age_min:
        return f"No apto para la edad del público (mínimo {c.min_age} años)"
    if p.explicit_filter and c.method == "tags" and t.explicit is None:
        return "Sin IA no se pudo confirmar que la letra sea apta"
    return None


def hard_filter_b(p: EventProfile, t: Track, c: Classification, today: date) -> tuple[str | None, bool]:
    """Filtro de años. Devuelve (motivo, es_nuevo)."""
    y = year_of(t, c)
    rd = t.release_date if (t.release_date[:4].isdigit() and int(t.release_date[:4]) == y) else ""
    new = is_new(y, rd, p.new_months, today)
    if p.explicit_filter and t.explicit is True:
        return "Letra explícita según Deezer", new
    if new:
        return None, True
    if not y:
        return "No se pudo saber el año del tema", False
    if y < p.classic_year_min or y > p.classic_year_max:
        return f"Año {y} fuera del rango de clásicos ({p.classic_year_min}–{p.classic_year_max})", False
    return None, False


def full_check(p: EventProfile, item: SetItem, rules: LearnedRules | None, banned_artists: set[str],
               today: date) -> str | None:
    r = hard_filter_a(p, item.track, item.cls, rules, banned_artists)
    if r:
        return r
    r, _ = hard_filter_b(p, item.track, item.cls, today)
    return r


# ======================================================================= utilidades
def trend_score(t: Track, profile: EventProfile) -> tuple[float, float]:
    """(tendencia 0–1, relevancia local 0–1)."""
    order = list(dict.fromkeys([profile.country] + profile.countries))
    score, local = 0.0, 0.0
    for src, info in t.sources.items():
        pos = (info or {}).get("pos", 50) if isinstance(info, dict) else 50
        if src.startswith(("apple_", "lastfm_")) and src[-2:].isupper() and src not in ("lastfm_tag",):
            cc = src[-2:]
            w = [1.0, 0.7, 0.5, 0.4][order.index(cc)] if cc in order[:4] else 0.3
            base = 0.8 if src.startswith("apple_") else 0.5
            score += base * w * max(0.1, (101 - pos) / 100)
            if cc == profile.country:
                local = max(local, (101 - pos) / 100)
        else:
            w = SOURCE_WEIGHT.get(src, 0.2)
            denom = 15 if src == "deezer_artista" else 100
            score += w * max(0.1, 1 - (pos - 1) / denom)
            if src in ("youtube_chart", "deezer_chart"):
                local = max(local, 0.5 * (101 - pos) / 100)
    return min(1.0, score), local


def source_families(t: Track) -> set[str]:
    fam = set()
    for s in t.sources:
        fam.add(s.split("_")[0] if not s.startswith("artista") else "semilla")
    return fam


def describe_sources(t: Track) -> str:
    parts = []
    for src, info in t.sources.items():
        pos = info.get("pos") if isinstance(info, dict) else None
        if src.startswith("apple_"):
            parts.append(f"Apple {COUNTRY_NAMES.get(src[-2:], src[-2:])} #{pos}")
        elif src.startswith("lastfm_") and src != "lastfm_tag":
            parts.append(f"Last.fm {COUNTRY_NAMES.get(src[-2:], src[-2:])} #{pos}")
        elif src == "deezer_chart":
            parts.append(f"Deezer chart #{pos}")
        elif src == "youtube_chart":
            parts.append(f"YouTube tendencias #{pos}")
        elif src == "deezer_playlist":
            parts.append(f"playlist Deezer «{info.get('playlist', '')}»")
        elif src == "deezer_artista":
            parts.append(f"top de {info.get('artista', '')} en Deezer")
        elif src == "lastfm_tag":
            parts.append(f"top Last.fm «{info.get('detalle', '')}»")
        elif src == "curada":
            parts.append(f"tu playlist «{info.get('playlist', '')}»")
        elif src == "artista_semilla":
            parts.append(f"artista semilla {info.get('artista', '')}")
        elif src == "youtube_playlist":
            parts.append("playlist YouTube")
    return ", ".join(dict.fromkeys(parts))


def merge_track(a: Track, b: Track) -> Track:
    """Une dos apariciones del mismo tema (prefiere datos de Deezer)."""
    base, other = (a, b) if a.deezer_id or not b.deezer_id else (b, a)
    for k, v in other.sources.items():
        base.sources.setdefault(k, v)
    base.source_genres = list(dict.fromkeys(base.source_genres + other.source_genres))
    base.seed_genres = list(dict.fromkeys(base.seed_genres + other.seed_genres))
    if not base.year and other.year:
        base.year = other.year
    elif other.year and base.year and other.year < base.year:
        base.year = other.year
    for attr in ("preview_url", "link", "isrc", "release_date"):
        if not getattr(base, attr) and getattr(other, attr):
            setattr(base, attr, getattr(other, attr))
    if base.explicit is None:
        base.explicit = other.explicit
    elif other.explicit:
        base.explicit = True
    # título más "limpio" (sin versión)
    if len(other.title) < len(base.title) and other.title:
        base.title = other.title
    return base


# ======================================================================= generador
class SetGenerator:
    def __init__(self, genres: list[Genre], hub, classifier=None, rules: LearnedRules | None = None,
                 today: date | None = None):
        self.genres = {g.slug: g for g in genres}
        self.genre_list = genres
        self.hub = hub
        self.ai = classifier
        self.fallback = TagClassifier(genres)
        self.rules = rules
        self.today = today or date.today()

    # ------------------------------------------------------------------ API pública
    def generate(self, p: EventProfile, progress: Callable[[str, float], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> GenerationResult:
        p.enforce_rules()
        prog = progress or (lambda m, f: None)
        stop = cancel or (lambda: False)
        warnings: list[str] = []
        if not p.allowed_genres():
            return GenerationResult([], {"error": "No hay géneros permitidos"}, [],
                                    ["Elige al menos un género permitido con porcentaje mayor a 0."])
        if not p.blocks:
            from ..core.models import Block
            p.blocks = [Block("Set completo", "", 180, 1, 10)]

        banned_artists = {main_artist(a) for a in p.banned_artists if a}
        if self.rules:
            banned_artists |= self.rules.banned_artists

        # 1) candidatos ------------------------------------------------
        raw: list[Track] = []
        allowed = p.allowed_genres()
        for i, slug in enumerate(allowed):
            if stop():
                raise Cancelled()
            g = self.genres.get(slug)
            if not g:
                continue
            prog(f"Buscando temas de {g.name}", 0.02 + 0.30 * i / len(allowed))
            raw += self.hub.candidates_for_genre(g, p, lambda m: prog(m, -1))
        if p.seed_artists:
            prog("Buscando tus artistas semilla", 0.33)
            raw += self.hub.candidates_for_artists(p.seed_artists)
        prog("Revisando tendencias", 0.35)
        raw += self.hub.trend_tracks(p, lambda m: prog(m, -1))
        raw += self.hub.curated_tracks(p, lambda m: prog(m, -1))
        warnings += getattr(self.hub, "warnings", [])
        if not raw:
            return GenerationResult([], {"error": "Sin candidatos"}, [], warnings + [
                "Ninguna fuente entregó temas. Revisa tu conexión a internet."])

        # 2) deduplicar ------------------------------------------------
        prog("Uniendo versiones repetidas", 0.40)
        pool: dict[str, Track] = {}
        discarded: list[dict] = []
        for t in raw:
            if not t.key or not t.title:
                continue
            if JUNK_RE.search(t.title):
                continue
            if set(split_artists(t.artist)) & banned_artists:
                discarded.append(self._disc(t, "Artista vetado"))
                continue
            pool[t.key] = merge_track(pool[t.key], t) if t.key in pool else t
        cands = list(pool.values())
        # prioridad para clasificar: temas buscados por género + tendencia
        cands.sort(key=lambda t: (len(t.seed_genres) > 0, trend_score(t, p)[0]), reverse=True)
        if len(cands) > MAX_CLASSIFY:
            cands = cands[:MAX_CLASSIFY]

        # 3) clasificar ------------------------------------------------
        cls: dict[str, Classification] = {}
        if self.ai:
            prog(f"Clasificando {len(cands)} temas con IA", 0.45)
            cls = self.ai.classify(cands, progress=lambda d, tot: prog(
                f"Clasificando con IA ({d}/{tot})", 0.45 + 0.25 * d / max(tot, 1)), cancel=stop)
            for e in getattr(self.ai, "errors", [])[:2]:
                warnings.append(f"IA: {e}")
        else:
            warnings.append("Sin clave de Gemini: se clasificó por tags. La precisión es menor y el set "
                            "puede quedar más corto.")
        missing = [t for t in cands if t.key not in cls]
        if missing:
            if self.ai:
                warnings.append(f"{len(missing)} temas se clasificaron por tags (la IA no alcanzó).")
            artists = list(dict.fromkeys(main_artist(t.artist) and t.artist.split(" feat")[0] for t in missing))
            tags_by_artist: dict[str, list[str]] = {}
            for i, a in enumerate(artists[:250]):
                if stop():
                    raise Cancelled()
                if i % 10 == 0:
                    prog(f"Leyendo tags de Last.fm ({i}/{min(len(artists), 250)})", 0.70)
                tags_by_artist[a] = self.hub.artist_tags(a)
            for t in missing:
                cls[t.key] = self.fallback.classify(t, tags_by_artist.get(t.artist.split(" feat")[0], []))
        if stop():
            raise Cancelled()

        # 4) filtros duros A ------------------------------------------
        prog("Aplicando filtros del evento", 0.75)
        survivors: list[SetItem] = []
        for t in cands:
            c = cls[t.key]
            reason = hard_filter_a(p, t, c, self.rules, banned_artists)
            if reason:
                discarded.append(self._disc(t, reason, c))
                continue
            survivors.append(SetItem(track=t, cls=c))
        for it in survivors:
            it.score = self._score(p, it)
        survivors.sort(key=lambda it: it.score, reverse=True)

        # 5) enriquecer (solo lo necesario) ---------------------------
        need = p.target_count()
        to_enrich = survivors[: max(need * 3, 60)]
        for i, it in enumerate(to_enrich):
            if stop():
                raise Cancelled()
            if i % 10 == 0:
                prog(f"Completando datos en Deezer ({i}/{len(to_enrich)})", 0.78 + 0.12 * i / max(len(to_enrich), 1))
            self.hub.enrich(it.track)

        # 6) filtros duros B ------------------------------------------
        eligible: list[SetItem] = []
        for it in to_enrich:
            reason, new = hard_filter_b(p, it.track, it.cls, self.today)
            reason = reason or hard_filter_a(p, it.track, it.cls, self.rules, banned_artists)
            if reason:
                discarded.append(self._disc(it.track, reason, it.cls))
                continue
            it.is_new = new
            it.score = self._score(p, it)
            eligible.append(it)

        # 8) armado ----------------------------------------------------
        prog("Armando el set por bloques", 0.92)
        chosen = self._assemble(p, eligible)
        for it in chosen:
            it.reasons = self._reasons(p, it)

        # 9) validación final -----------------------------------------
        prog("Validando el set completo", 0.97)
        final = []
        for it in chosen:
            r = full_check(p, it, self.rules, banned_artists, self.today)
            if r:   # no debería pasar nunca, pero se revisa igual
                discarded.append(self._disc(it.track, f"Validación final: {r}", it.cls))
                continue
            final.append(it)
        used = {it.track.key for it in final}
        rest = [it for it in eligible if it.track.key not in used]
        summary = self.summarize(p, final, discarded)
        summary["fuentes"] = getattr(self.hub, "stats", lambda: {})()
        summary["clasificacion"] = "IA" if self.ai else "tags"
        if len(final) < need:
            warnings.append(f"Se pidieron {need} temas y solo {len(final)} pasaron todos los filtros. "
                            "Es preferible un set más corto que uno con temas fuera de lugar.")
        prog("Listo", 1.0)
        return GenerationResult(final, summary, discarded[:400], list(dict.fromkeys(warnings)), rest)

    # ------------------------------------------------------------------ puntaje
    def _score(self, p: EventProfile, it: SetItem) -> float:
        trend, local = trend_score(it.track, p)
        fam = len(source_families(it.track))
        s = 50 * trend + 4 * min(fam, 5) + 15 * it.cls.confidence + 8 * local
        if set(split_artists(it.track.artist)) & {main_artist(a) for a in p.seed_artists}:
            s += 12
        if self.rules and it.track.key in self.rules.liked:
            s += 10 * min(self.rules.liked[it.track.key], 2)
        if it.track.preview_url:
            s += 1
        return round(s, 2)

    # ------------------------------------------------------------------ armado por bloques
    def _assemble(self, p: EventProfile, eligible: list[SetItem]) -> list[SetItem]:
        n_total = p.target_count()
        weights = {g: w for g, w in p.genre_weights.items() if g in p.allowed_genres()}
        wsum = sum(weights.values()) or 1
        quota = {g: w / wsum * n_total for g, w in weights.items()}
        total_min = sum(b.minutes for b in p.blocks) or 1
        sizes = [max(1, round(n_total * b.minutes / total_min)) for b in p.blocks]
        max_per_artist = 2 if n_total < 40 else 3

        used_keys: set[str] = set()
        genre_count: dict[str, int] = {}
        artist_count: dict[str, int] = {}
        new_count = 0
        placed = 0
        result: list[SetItem] = []

        for bi, (block, size) in enumerate(zip(p.blocks, sizes)):
            block_genres = set(block.genres) & set(weights) if block.genres else set(weights)
            if not block_genres:
                block_genres = set(weights)
            chosen_block: list[SetItem] = []
            for _slot in range(size):
                best, best_val = None, -1e9
                for widen in (0, 1, 2, 10):
                    lo, hi = block.energy_min - widen, block.energy_max + widen
                    for it in eligible:
                        if it.track.key in used_keys:
                            continue
                        if it.cls.primary not in block_genres:
                            continue
                        if block.classics_only and it.is_new:
                            continue
                        if not lo <= it.cls.energy <= hi:
                            continue
                        art = main_artist(it.track.artist)
                        if artist_count.get(art, 0) >= max_per_artist:
                            continue
                        val = it.score
                        q = quota.get(it.cls.primary, 0)
                        deficit = (q - genre_count.get(it.cls.primary, 0)) / max(q, 1)
                        val += 30 * max(-1.0, min(1.0, deficit))
                        if not block.classics_only:
                            want_new = (new_count / max(placed, 1)) < p.new_pct / 100 if placed else p.new_pct >= 50
                            val += 15 if it.is_new == want_new else -5
                        if chosen_block and main_artist(chosen_block[-1].track.artist) == art:
                            val -= 60
                        val -= 6 * widen
                        if val > best_val:
                            best, best_val = it, val
                    if best:
                        break
                if not best:
                    break
                best.block = bi
                used_keys.add(best.track.key)
                genre_count[best.cls.primary] = genre_count.get(best.cls.primary, 0) + 1
                art = main_artist(best.track.artist)
                artist_count[art] = artist_count.get(art, 0) + 1
                new_count += int(best.is_new)
                placed += 1
                chosen_block.append(best)
            result += self._order_block(chosen_block, bi, len(p.blocks))
        return result

    @staticmethod
    def _order_block(items: list[SetItem], bi: int, n_blocks: int) -> list[SetItem]:
        """Curva de energía: sube durante el bloque; BPM agrupado para mezclas suaves."""
        items = sorted(items, key=lambda it: (it.cls.energy, it.track.bpm or 0))
        # evitar mismo artista seguido
        for i in range(1, len(items)):
            if main_artist(items[i].track.artist) == main_artist(items[i - 1].track.artist):
                for j in range(i + 1, len(items)):
                    if main_artist(items[j].track.artist) != main_artist(items[i - 1].track.artist):
                        items[i], items[j] = items[j], items[i]
                        break
        return items

    # ------------------------------------------------------------------ explicaciones
    def _reasons(self, p: EventProfile, it: SetItem) -> list[str]:
        g = self.genres.get(it.cls.primary)
        out = []
        how = "IA" if it.cls.method == "ia" else "tags"
        out.append(f"Género: {g.name if g else it.cls.primary} ({how}, confianza {it.cls.confidence:.0%})")
        src = describe_sources(it.track)
        if src:
            out.append(f"Fuentes: {src}")
        y = year_of(it.track, it.cls)
        out.append(f"{'Nuevo' if it.is_new else 'Clásico'}{f' ({y})' if y else ''}")
        b = p.blocks[it.block] if it.block < len(p.blocks) else None
        if b:
            out.append(f"Energía {it.cls.energy} → bloque «{b.name}» ({b.energy_min}–{b.energy_max})")
        if p.explicit_filter:
            out.append("Letra apta (filtro de explícitos activado)")
        if self.rules and it.track.key in self.rules.liked:
            out.append("Te gustó 👍 en este tipo de evento")
        return out

    @staticmethod
    def _disc(t: Track, reason: str, c: Classification | None = None) -> dict:
        return {"artist": t.artist, "title": t.title, "reason": reason, "genre": c.primary if c else ""}

    # ------------------------------------------------------------------ resumen
    def summarize(self, p: EventProfile, items: list[SetItem], discarded: list[dict]) -> dict:
        n = len(items) or 1
        weights = {g: w for g, w in p.genre_weights.items() if g in p.allowed_genres()}
        wsum = sum(weights.values()) or 1
        real: dict[str, int] = {}
        for it in items:
            real[it.cls.primary] = real.get(it.cls.primary, 0) + 1
        dist = []
        for g in sorted(set(weights) | set(real), key=lambda s: -weights.get(s, 0)):
            dist.append({"genre": g, "name": self.genres[g].name if g in self.genres else g,
                         "requested": round(100 * weights.get(g, 0) / wsum),
                         "actual": round(100 * real.get(g, 0) / n), "count": real.get(g, 0)})
        reasons: dict[str, int] = {}
        for d in discarded:
            key = re.sub(r"\d{4}–\d{4}|\d+", "#", d["reason"])
            reasons[key] = reasons.get(key, 0) + 1
        return {
            "count": len(items), "target": p.target_count(),
            "new_pct_actual": round(100 * sum(it.is_new for it in items) / n),
            "new_pct_requested": p.new_pct,
            "distribution": dist,
            "energy_curve": [it.cls.energy for it in items],
            "discarded_count": len(discarded),
            "discard_reasons": sorted(reasons.items(), key=lambda kv: -kv[1])[:12],
            "explicit_count": sum(1 for it in items if it.cls.explicit or it.track.explicit),
        }

    # ------------------------------------------------------------------ reemplazos
    def replacement(self, p: EventProfile, items: list[SetItem], pool: list[SetItem], index: int,
                    similar: bool = True) -> SetItem | None:
        """Busca un reemplazo para items[index] dentro del pool (mismo bloque, mismo género si se puede)."""
        old = items[index]
        used = {it.track.key for it in items}
        block = p.blocks[old.block] if old.block < len(p.blocks) else None
        banned_artists = {main_artist(a) for a in p.banned_artists}
        if self.rules:
            banned_artists |= self.rules.banned_artists
        best, best_val = None, -1e9
        for it in pool:
            if it.track.key in used:
                continue
            if full_check(p, it, self.rules, banned_artists, self.today):
                continue
            val = it.score
            if similar and it.cls.primary == old.cls.primary:
                val += 40
            val -= 4 * abs(it.cls.energy - old.cls.energy)
            if block:
                if block.genres and it.cls.primary not in block.genres:
                    val -= 50
                if block.classics_only and it.is_new:
                    continue
            if main_artist(it.track.artist) == main_artist(old.track.artist):
                val -= 30
            if val > best_val:
                best, best_val = it, val
        if best:
            best.block = old.block
            best.reasons = self._reasons(p, best)
        return best
