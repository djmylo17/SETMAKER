"""PRUEBAS OBLIGATORIAS del motor (sección 7 de la especificación).

- "Carrete juvenil urbano 18–25": 0 temas de rock en español, rock anglo o baladas.
- "Cumpleaños infantil": 0 temas con letra explícita.

Se simula exactamente el error de SetDJ: Los Prisioneros, Soda Stereo y Luis Miguel aparecen
en el top de Chile (Apple/Deezer) junto a reggaetón. Deben quedar fuera.
"""
import copy
from datetime import date

import pytest

from app.ai.gemini import GeminiClassifier
from app.core.models import Classification, Track
from app.core.normalize import track_key
from app.core.store import LearnedRules
from app.core.taxonomy import DEFAULT_GENRES
from app.core.templates import DEFAULT_TEMPLATES
from app.engine.pipeline import SetGenerator

TODAY = date(2026, 10, 22)

# (artista, título, año, explícito Deezer, género real, energía, min_age, tags Last.fm)
CATALOG = [
    # reggaetón actual
    ("Bad Bunny", "DtMF", 2025, False, "reggaeton_actual", 7, 0, ["reggaeton"]),
    ("Bad Bunny", "Baile Inolvidable", 2025, False, "reggaeton_actual", 7, 0, ["reggaeton"]),
    ("Feid", "Luna", 2024, False, "reggaeton_actual", 8, 14, ["reggaeton"]),
    ("Karol G", "Si Antes Te Hubiera Conocido", 2024, False, "reggaeton_actual", 8, 0, ["reggaeton"]),
    ("Ryan Castro", "Monastery", 2025, False, "reggaeton_actual", 8, 0, ["reggaeton"]),
    ("Blessd", "Mírame", 2024, True, "reggaeton_actual", 9, 18, ["reggaeton"]),
    ("Myke Towers", "La Falda", 2024, True, "reggaeton_actual", 8, 18, ["reggaeton"]),
    ("Rauw Alejandro", "Touching The Sky", 2024, False, "reggaeton_actual", 8, 0, ["reggaeton"]),
    ("Young Miko", "Wiggy", 2024, True, "reggaeton_actual", 8, 18, ["reggaeton"]),
    ("Manuel Turizo", "Qué Pecao", 2025, False, "reggaeton_actual", 8, 0, ["reggaeton"]),
    ("Ozuna", "Hey Mor", 2022, False, "reggaeton_actual", 8, 0, ["reggaeton"]),
    ("Jhayco", "Dime Cómo", 2025, False, "reggaeton_actual", 8, 14, ["reggaeton"]),
    # urbano chileno
    ("Pailita", "Ultra Solo", 2023, True, "urbano_chileno", 8, 18, ["chilean"]),
    ("Jere Klein", "Mi Bebé", 2024, False, "urbano_chileno", 8, 14, ["chilean"]),
    ("Cris MJ", "Una Noche en Medellín", 2023, False, "urbano_chileno", 9, 14, ["chilean"]),
    ("Marcianeke", "Dos Botellas", 2024, True, "urbano_chileno", 9, 18, ["chilean"]),
    ("Young Cister", "Plan B", 2025, False, "urbano_chileno", 8, 14, ["chilean"]),
    ("FloyyMenor", "Gata Only", 2024, False, "urbano_chileno", 8, 14, ["chilean", "tiktok"]),
    # guaracha / rkt / dembow
    ("Erick Dj", "Guaracha Sirena", 2025, False, "guaracha", 9, 0, ["guaracha"]),
    ("Pirlo DJ", "Aleteo Total", 2025, False, "guaracha", 10, 0, ["guaracha"]),
    ("L-Gante", "L-Gante RKT", 2023, True, "rkt", 9, 18, ["rkt"]),
    ("La Joaqui", "Butakera", 2024, True, "rkt", 9, 18, ["rkt"]),
    ("El Alfa", "La Mamá de la Mamá", 2023, True, "dembow", 10, 18, ["dembow"]),
    ("Rochy RD", "Ella No Es Tuya", 2024, True, "dembow", 9, 18, ["dembow"]),
    ("Chencho Corleone", "Me Porto Bonito", 2022, True, "perreo", 9, 18, ["perreo"]),
    ("Ñengo Flow", "Perreo Intenso", 2024, True, "perreo", 10, 18, ["perreo"]),
    ("Eladio Carrión", "Sauce Boyz", 2023, True, "trap_latino", 6, 18, ["latin trap"]),
    # clásicos del perreo
    ("Daddy Yankee", "Gasolina", 2004, False, "reggaeton_old", 9, 14, ["reggaeton"]),
    ("Don Omar", "Danza Kuduro", 2010, False, "reggaeton_old", 9, 0, ["reggaeton"]),
    ("Wisin & Yandel", "Rakata", 2005, False, "reggaeton_old", 9, 14, ["reggaeton"]),
    ("Héctor & Tito", "Baila Morena", 2002, False, "reggaeton_old", 8, 0, ["reggaeton"]),
    ("J Balvin", "Ginza", 2015, False, "reggaeton_2013_2019", 8, 0, ["reggaeton"]),
    ("Nicky Jam", "El Perdón", 2015, False, "reggaeton_2013_2019", 7, 0, ["reggaeton"]),
    ("Ozuna", "Taki Taki", 2018, False, "reggaeton_2013_2019", 9, 0, ["reggaeton"]),
    ("Bad Bunny", "Safaera", 2020, True, "perreo", 10, 18, ["reggaeton", "perreo"]),
    # LOS INTRUSOS de SetDJ (aparecen en el top de Chile)
    ("Los Prisioneros", "Tren al Sur", 1990, False, "rock_espanol", 7, 0, ["rock en español", "chilean"]),
    ("Los Prisioneros", "El Baile de los Que Sobran", 1986, False, "rock_espanol", 6, 0, ["rock en español"]),
    ("Soda Stereo", "De Música Ligera", 1990, False, "rock_espanol", 7, 0, ["rock en español"]),
    ("Los Bunkers", "Llueve sobre la Ciudad", 2005, False, "rock_espanol", 5, 0, ["rock en español", "chilean"]),
    ("Queen", "Don't Stop Me Now", 1978, False, "rock_anglo", 8, 0, ["classic rock"]),
    ("Luis Miguel", "La Incondicional", 1989, False, "baladas", 3, 0, ["ballad"]),
    ("Myriam Hernández", "El Hombre Que Yo Amo", 1988, False, "baladas", 2, 0, ["balada"]),
    ("Mon Laferte", "Tu Falta de Querer", 2015, False, "baladas", 3, 0, ["chilean", "balada"]),
    # infantil / pop / viral
    ("31 Minutos", "Mi Muñeca Me Habló", 2004, False, "infantil", 6, 0, ["kids"]),
    ("31 Minutos", "Bailan Sin Cesar", 2003, False, "infantil", 7, 0, ["kids"]),
    ("Cantajuego", "El Baile del Cuerpo", 2012, False, "infantil", 7, 0, ["infantil"]),
    ("Pinkfong", "Baby Shark", 2016, False, "infantil", 6, 0, ["kids"]),
    ("Mazapán", "Mazapán Baila", 2015, False, "infantil", 5, 0, ["infantil"]),
    ("Tikitiklip", "Saltar", 2018, False, "infantil", 6, 0, ["infantil"]),
    ("Cachureos", "El Baile del Cachureo", 2012, False, "infantil", 7, 0, ["infantil"]),
    ("Shakira", "Soltera", 2024, False, "pop_latino", 7, 0, ["latin pop"]),
    ("Emilia", "Bunda", 2024, False, "pop_latino", 8, 10, ["latin pop", "tiktok"]),
    ("TINI", "Me Voy", 2024, False, "pop_latino", 7, 0, ["latin pop"]),
    ("Sebastián Yatra", "Tacones Rojos", 2021, False, "pop_latino", 7, 0, ["latin pop"]),
    ("Morat", "Bajo la Mesa", 2024, False, "pop_latino", 6, 0, ["latin pop"]),
    ("Camilo", "Pegao", 2024, False, "pop_latino", 7, 0, ["latin pop"]),
    ("María Becerra", "Corazón Vacío", 2024, False, "pop_latino", 6, 0, ["latin pop"]),
    ("Sabrina Carpenter", "Espresso", 2024, False, "pop_anglo", 7, 0, ["pop"]),
    ("Dua Lipa", "Houdini", 2024, False, "pop_anglo", 8, 0, ["pop"]),
    ("Bizarrap", "Session Viral", 2025, False, "viral", 8, 0, ["tiktok"]),
    ("Kiko Viral", "Paso del Trend", 2025, False, "viral", 8, 0, ["tiktok"]),
    ("Dance Kids", "Trend del Año", 2025, False, "viral", 8, 0, ["tiktok"]),
    ("Grupo Trend", "Baile TikTok", 2025, None, "viral", 8, 0, ["tiktok"]),   # explícito desconocido
]

TRUTH = {track_key(a, t): (g, y, ex, en, age, tags) for a, t, y, ex, g, en, age, tags in CATALOG}


def make_track(row, source, pos):
    a, t, y, ex, g, en, age, tags = row
    tr = Track(key=track_key(a, t), title=t, artist=a, year=y, explicit=ex, deezer_id=hash(a + t) % 10**6,
               preview_url="https://cdn/preview.mp3")
    tr.sources[source] = {"pos": pos}
    return tr


class FakeHub:
    """Fuente falsa: por género devuelve temas del catálogo y en tendencias mete a los intrusos."""
    warnings: list = []

    def candidates_for_genre(self, g, profile, progress):
        out = []
        for i, row in enumerate(CATALOG):
            if row[4] == g.slug or (g.slug in ("reggaeton_actual", "urbano_chileno") and row[4] == "rock_espanol"):
                tr = make_track(row, "deezer_playlist", i + 1)
                tr.seed_genres.append(g.slug)   # el buscador se equivocó a propósito
                out.append(tr)
        return out

    def candidates_for_artists(self, artists):
        return []

    def trend_tracks(self, profile, progress):
        # "Top Chile" mezclado: rock, baladas, reggaetón… (el problema de SetDJ)
        return [make_track(row, "apple_CL", i + 1) for i, row in enumerate(CATALOG)]

    def curated_tracks(self, profile, progress):
        return []

    def artist_tags(self, artist):
        tags = []
        for (a, t, y, ex, g, en, age, tg) in CATALOG:
            if a == artist:
                tags += tg
        return list(dict.fromkeys(tags))

    def enrich(self, t):
        return t

    def stats(self):
        return {}


class FakeGemini:
    """Simula la IA devolviendo la clasificación real del catálogo."""
    errors: list = []

    def classify(self, tracks, hints=None, progress=None, cancel=None):
        out = {}
        for t in tracks:
            g, y, ex, en, age, tags = TRUTH[t.key]
            out[t.key] = Classification(genres=[g], year=y, energy=en, explicit=bool(ex) if ex is not None else age >= 18,
                                        min_age=age, confidence=0.9, method="ia")
        return out


ROCK_BALADAS = {"rock_espanol", "rock_anglo", "baladas", "trova_folclore"}
INTRUSOS = {"Los Prisioneros", "Soda Stereo", "Los Bunkers", "Queen", "Luis Miguel", "Myriam Hernández", "Mon Laferte"}


def run(template_name, classifier):
    profile = copy.deepcopy(DEFAULT_TEMPLATES[template_name])
    gen = SetGenerator(DEFAULT_GENRES, FakeHub(), classifier, today=TODAY)
    return profile, gen.generate(profile)


@pytest.mark.parametrize("classifier", [FakeGemini(), None], ids=["con_IA", "sin_IA_tags"])
def test_OBLIGATORIA_carrete_juvenil_sin_rock_ni_baladas(classifier):
    profile, res = run("Carrete juvenil urbano 18–25", classifier)
    assert res.items, "el set no puede quedar vacío"
    for it in res.items:
        real_genre = TRUTH[it.track.key][0]
        assert real_genre not in ROCK_BALADAS, f"Se coló {it.track.artist} - {it.track.title}"
        assert it.track.artist not in INTRUSOS
        assert it.cls.primary not in ROCK_BALADAS
        assert it.reasons, "cada tema debe decir por qué entró"
    # los intrusos aparecen en descartados con motivo
    disc_artists = {d["artist"] for d in res.discarded}
    assert "Los Prisioneros" in disc_artists


@pytest.mark.parametrize("classifier", [FakeGemini(), None], ids=["con_IA", "sin_IA_tags"])
def test_OBLIGATORIA_cumple_infantil_sin_explicitos(classifier):
    profile, res = run("Cumpleaños infantil (6–11)", classifier)
    assert profile.explicit_filter is True
    assert res.items
    for it in res.items:
        g, y, ex, en, age, tags = TRUTH[it.track.key]
        assert ex is not True, f"Tema explícito: {it.track.artist} - {it.track.title}"
        if classifier is not None:   # la edad mínima solo la sabe la IA
            assert age <= profile.age_min, f"No apto para niños: {it.track.title}"
        assert not it.cls.explicit
    assert res.summary["explicit_count"] == 0


def test_no_hay_artista_seguido_y_respeta_bloques():
    profile, res = run("Carrete juvenil urbano 18–25", FakeGemini())
    for a, b in zip(res.items, res.items[1:]):
        if a.block == b.block:
            assert a.track.artist != b.track.artist or len(res.items) < 6
    clasicos = [it for it in res.items if profile.blocks[it.block].classics_only]
    assert all(not it.is_new for it in clasicos)
    assert all(it.cls.primary in profile.blocks[it.block].genres for it in clasicos)


def test_feedback_aprendido_veta_artista_solo_en_su_tipo():
    rules = LearnedRules(banned_artists={"bad bunny"}, banned_tracks=set(), disliked={}, liked={})
    profile = copy.deepcopy(DEFAULT_TEMPLATES["Carrete juvenil urbano 18–25"])
    res = SetGenerator(DEFAULT_GENRES, FakeHub(), FakeGemini(), rules=rules, today=TODAY).generate(profile)
    assert all("Bad Bunny" not in it.track.artist for it in res.items)
    # sin reglas, Bad Bunny sí puede aparecer
    res2 = SetGenerator(DEFAULT_GENRES, FakeHub(), FakeGemini(), today=TODAY).generate(copy.deepcopy(profile))
    assert any("Bad Bunny" in it.track.artist for it in res2.items + res2.pool)


def test_reemplazo_respeta_filtros():
    profile, res = run("Carrete juvenil urbano 18–25", FakeGemini())
    gen = SetGenerator(DEFAULT_GENRES, FakeHub(), FakeGemini(), today=TODAY)
    rep = gen.replacement(profile, res.items, res.pool, 0)
    if rep:
        assert TRUTH[rep.track.key][0] not in ROCK_BALADAS
        assert rep.track.key not in {it.track.key for it in res.items}


def test_resumen_tiene_distribucion():
    profile, res = run("Carrete juvenil urbano 18–25", FakeGemini())
    s = res.summary
    assert s["count"] == len(res.items)
    assert any(d["genre"] == "reggaeton_actual" for d in s["distribution"])
    assert s["discarded_count"] > 0


def test_gemini_classifier_parsea_y_cachea(data_dir):
    from app.db.database import Database
    db = Database(data_dir / "setmaker.db")
    calls = []

    def fake_post(body):
        calls.append(body)
        text = '{"items": [{"id": 0, "genres": ["rock_espanol"], "year": 1990, "energy": 7, ' \
               '"explicit": false, "min_age": 0, "confidence": 0.95}, {"id": 1, "genres": ["inventado", ' \
               '"reggaeton_actual"], "year": 2025, "energy": 8, "explicit": true, "min_age": 18, "confidence": 0.9}]}'
        return 200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    clf = GeminiClassifier(db, "k", "gemini-x-flash", DEFAULT_GENRES, post=fake_post)
    tracks = [Track(key=track_key("Los Prisioneros", "Tren al Sur"), title="Tren al Sur", artist="Los Prisioneros"),
              Track(key=track_key("Bad Bunny", "DtMF"), title="DtMF", artist="Bad Bunny")]
    res = clf.classify(tracks)
    assert res[tracks[0].key].primary == "rock_espanol"
    assert res[tracks[1].key].genres == ["reggaeton_actual"]   # género inventado descartado
    assert len(calls) == 1
    # segunda vez: desde caché, sin llamar a la IA
    clf.classify(tracks)
    assert len(calls) == 1
    db.close()


def test_gemini_sin_cuota_no_rompe(data_dir):
    from app.db.database import Database
    db = Database(data_dir / "setmaker.db")
    clf = GeminiClassifier(db, "k", "m", DEFAULT_GENRES,
                           post=lambda b: (429, {"error": {"message": "Quota exceeded GenerateRequestsPerDay"}}))
    res = clf.classify([Track(key="a|b", title="b", artist="a")])
    assert res == {}
    assert clf.errors
    db.close()
