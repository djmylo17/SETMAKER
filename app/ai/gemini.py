"""Clasificación de temas con Gemini (tier gratuito).

- Envía lotes de temas y pide JSON estructurado con géneros de TU taxonomía (lista cerrada).
- Cachea cada resultado por tema en ai_classification: nunca reclasifica lo ya clasificado.
- Si se acaba la cuota o falla, devuelve lo que alcanzó y el motor usa el respaldo por tags.

La clasificación NO depende del evento: describe el tema (género, año, energía, explícito,
edad mínima). El "encaja o no" lo decide el motor con los filtros duros del perfil, así un tema
clasificado sirve para todos tus eventos futuros sin gastar más cuota.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable

import httpx

from ..core.models import Classification, Genre, Track
from ..db.database import Database

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
BATCH = 40

PROMPT = """Eres un DJ profesional de Chile experto en música latina, urbana y de fiestas.
Clasifica cada tema de la lista usando SOLO estos géneros (usa el código entre corchetes):

{genres}

Reglas:
- "genres": 1 a 3 códigos, el PRINCIPAL primero. Si ninguno calza bien, usa ["otro"]. Nunca fuerces un género:
  un tema de rock, balada o trova debe ir en su género (rock_espanol, rock_anglo, baladas, trova_folclore)
  aunque sea muy popular. Los Prisioneros o Soda Stereo son rock_espanol, nunca reggaetón.
- Reggaetón: separa por época del tema ORIGINAL (actual = 2022+, 2013–2019, old school = 2004–2012).
- "viral" solo si el tema fue tendencia en TikTok/redes en los últimos ~2 años; ponlo como género secundario.
- "year": año de lanzamiento ORIGINAL del tema (no de recopilatorios ni remasters).
- "energy": 1 a 10, qué tan arriba pone la pista de baile (balada = 1–2, perreo/guaracha en peak = 9–10).
- "explicit": true si la letra tiene contenido sexual explícito, garabatos fuertes, drogas o violencia.
- "min_age": edad mínima recomendada para el público: 0 (apto niños), 10, 14 o 18.
- "confidence": 0 a 1, qué tan seguro estás de conocer el tema. Si no lo conoces, confidence baja (< 0.4).
- "note": máximo 8 palabras en español.
Devuelve un objeto JSON con "items": una entrada por tema, con el mismo "id".

Temas:
{tracks}
"""


def _schema(slugs: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "items": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "INTEGER"},
                        "genres": {"type": "ARRAY", "items": {"type": "STRING", "enum": slugs}},
                        "year": {"type": "INTEGER"},
                        "energy": {"type": "INTEGER"},
                        "explicit": {"type": "BOOLEAN"},
                        "min_age": {"type": "INTEGER"},
                        "confidence": {"type": "NUMBER"},
                        "note": {"type": "STRING"},
                    },
                    "required": ["id", "genres", "year", "energy", "explicit", "min_age", "confidence"],
                },
            }
        },
        "required": ["items"],
    }


class QuotaExhausted(Exception):
    pass


class GeminiClassifier:
    def __init__(self, db: Database, api_key: str, model: str, genres: list[Genre],
                 post: Callable | None = None):
        self.db, self.key, self.model = db, api_key, model
        self.genres = genres
        self.slugs = [g.slug for g in genres]
        self._post = post            # inyectable en pruebas
        self.used_schema = True
        self.errors: list[str] = []

    # ---------- caché
    def cached(self, keys: list[str]) -> dict[str, Classification]:
        out = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = ",".join("?" * len(chunk))
            for r in self.db.query(f"SELECT track_key, data FROM ai_classification WHERE track_key IN ({q})", tuple(chunk)):
                c = Classification.from_dict(json.loads(r["data"]))
                # descartar slugs que ya no existen en la taxonomía
                c.genres = [g for g in c.genres if g in self.slugs] or ["otro"]
                out[r["track_key"]] = c
        return out

    def _store(self, key: str, c: Classification) -> None:
        self.db.execute("INSERT INTO ai_classification(track_key, model, data) VALUES(?,?,?) "
                        "ON CONFLICT(track_key) DO UPDATE SET model=excluded.model, data=excluded.data, "
                        "created_at=datetime('now','localtime')",
                        (key, self.model, json.dumps(c.to_dict(), ensure_ascii=False)))

    def forget(self, key: str) -> None:
        self.db.execute("DELETE FROM ai_classification WHERE track_key = ?", (key,))

    # ---------- clasificación
    def classify(self, tracks: list[Track], hints: dict[str, list[str]] | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> dict[str, Classification]:
        hints = hints or {}
        result = self.cached([t.key for t in tracks])
        pending = [t for t in tracks if t.key not in result]
        total = len(pending)
        done = 0
        for i in range(0, total, BATCH):
            if cancel and cancel():
                break
            batch = pending[i:i + BATCH]
            try:
                got = self._classify_batch(batch, hints)
            except QuotaExhausted as exc:
                self.errors.append(str(exc))
                log.warning("Gemini sin cuota: %s", exc)
                break
            except Exception as exc:  # noqa: BLE001
                self.errors.append(str(exc))
                log.warning("Gemini falló en un lote: %s", exc)
                continue
            for key, c in got.items():
                self._store(key, c)
                result[key] = c
            done += len(batch)
            if progress:
                progress(done, total)
        return result

    def _genre_lines(self) -> str:
        return "\n".join(f"[{g.slug}] {g.name}: {g.description}" for g in self.genres)

    def _classify_batch(self, batch: list[Track], hints: dict[str, list[str]]) -> dict[str, Classification]:
        lines = []
        for idx, t in enumerate(batch):
            extra = []
            if t.year:
                extra.append(f"año fuente {t.year}")
            tags = (t.source_genres or []) + hints.get(t.key, [])
            if tags:
                extra.append("tags: " + ", ".join(dict.fromkeys(tags))[:120])
            lines.append(f"{idx} | {t.artist} - {t.title}" + (f" ({'; '.join(extra)})" if extra else ""))
        prompt = PROMPT.format(genres=self._genre_lines(), tracks="\n".join(lines))
        data = self._call(prompt)
        items = data.get("items", []) if isinstance(data, dict) else data
        out: dict[str, Classification] = {}
        for it in items or []:
            try:
                idx = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(batch):
                continue
            genres = [g for g in it.get("genres") or [] if g in self.slugs][:3] or ["otro"]
            out[batch[idx].key] = Classification(
                genres=genres,
                year=int(it.get("year") or 0),
                energy=max(1, min(10, int(it.get("energy") or 5))),
                explicit=bool(it.get("explicit")),
                min_age=int(it.get("min_age") or 0),
                confidence=max(0.0, min(1.0, float(it.get("confidence") or 0.5))),
                note=str(it.get("note") or "")[:80],
                method="ia",
            )
        return out

    def _call(self, prompt: str) -> dict:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        if self.used_schema:
            body["generationConfig"]["responseSchema"] = _schema(self.slugs)
        for attempt in range(5):
            status, payload = self._send(body)
            if status == 200:
                return self._parse(payload)
            text = json.dumps(payload)[:500] if not isinstance(payload, str) else payload[:500]
            if status == 400 and self.used_schema and "schema" in text.lower():
                # el modelo no acepta el esquema: seguir solo con JSON + instrucciones
                self.used_schema = False
                body["generationConfig"].pop("responseSchema", None)
                continue
            if status == 429:
                if "PerDay" in text or "per day" in text.lower() or "daily" in text.lower():
                    raise QuotaExhausted("Se acabó la cuota diaria gratis de Gemini. Mañana se renueva.")
                wait = 20 * (attempt + 1)
                m = re.search(r'"retryDelay":\s*"(\d+)s"', text)
                if m:
                    wait = int(m.group(1)) + 1
                time.sleep(min(wait, 65))
                continue
            if status in (500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            if status in (401, 403):
                raise QuotaExhausted("Gemini rechazó la clave. Revísala en Fuentes y claves.")
            if status == 404:
                raise QuotaExhausted(f"El modelo {self.model} ya no existe. Elige otro en Fuentes y claves.")
            raise RuntimeError(f"Gemini respondió {status}")
        raise QuotaExhausted("Gemini está saturado o sin cuota en este momento.")

    def _send(self, body: dict) -> tuple[int, dict | str]:
        if self._post:
            return self._post(body)
        url = API.format(model=self.model)
        try:
            r = httpx.post(url, json=body, headers={"x-goog-api-key": self.key}, timeout=90)
        except httpx.HTTPError:
            return 503, "sin conexión"
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    @staticmethod
    def _parse(payload: dict) -> dict:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            return {"items": []}
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0)) if m else {"items": []}
