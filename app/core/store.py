"""Acceso a datos: géneros, plantillas, eventos, sets, feedback y playlists curadas."""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..db.database import Database
from .models import EventProfile, Genre, SetItem
from .taxonomy import DEFAULT_GENRES
from .templates import DEFAULT_TEMPLATES


# ---------------------------------------------------------------- semilla inicial
def ensure_seed(db: Database) -> None:
    """Carga géneros y plantillas de fábrica la primera vez (y agrega las nuevas en actualizaciones)."""
    existing = {r["slug"] for r in db.query("SELECT slug FROM genres")}
    removed = _deleted_genres(db)
    for pos, g in enumerate(DEFAULT_GENRES):
        if g.slug not in existing and g.slug not in removed:
            db.execute("INSERT OR IGNORE INTO genres(slug, position, data) VALUES(?,?,?)",
                       (g.slug, pos, json.dumps(g.to_dict(), ensure_ascii=False)))

    builtin = {r["name"] for r in db.query("SELECT name FROM templates WHERE builtin = 1")}
    removed_t = set(json.loads(db.meta_get("templates_removed", "[]")))
    for name, prof in DEFAULT_TEMPLATES.items():
        if name not in builtin and name not in removed_t:
            db.execute("INSERT INTO templates(name, builtin, profile_json) VALUES(?,1,?)", (name, prof.to_json()))


def _deleted_genres(db: Database) -> set[str]:
    return set(json.loads(db.meta_get("genres_removed", "[]")))


# ---------------------------------------------------------------- géneros
def load_genres(db: Database) -> list[Genre]:
    rows = db.query("SELECT data FROM genres ORDER BY position, slug")
    return [Genre.from_dict(json.loads(r["data"])) for r in rows]


def genre_map(db: Database) -> dict[str, Genre]:
    return {g.slug: g for g in load_genres(db)}


def genre_names(db: Database) -> dict[str, str]:
    return {g.slug: g.name for g in load_genres(db)}


def save_genre(db: Database, g: Genre, position: int | None = None) -> None:
    if position is None:
        position = db.scalar("SELECT position FROM genres WHERE slug = ?", (g.slug,))
        if position is None:
            position = (db.scalar("SELECT MAX(position) FROM genres") or 0) + 1
    db.execute("INSERT INTO genres(slug, position, data) VALUES(?,?,?) "
               "ON CONFLICT(slug) DO UPDATE SET data = excluded.data, position = excluded.position",
               (g.slug, position, json.dumps(g.to_dict(), ensure_ascii=False)))


def delete_genre(db: Database, slug: str) -> None:
    db.execute("DELETE FROM genres WHERE slug = ?", (slug,))
    removed = _deleted_genres(db) | {slug}
    db.meta_set("genres_removed", json.dumps(sorted(removed)))


def reset_genres(db: Database) -> None:
    db.execute("DELETE FROM genres")
    db.meta_set("genres_removed", "[]")
    for pos, g in enumerate(DEFAULT_GENRES):
        save_genre(db, g, pos)


# ---------------------------------------------------------------- plantillas
@dataclass
class TemplateRow:
    id: int
    name: str
    builtin: bool
    profile: EventProfile


def load_templates(db: Database) -> list[TemplateRow]:
    rows = db.query("SELECT id, name, builtin, profile_json FROM templates ORDER BY builtin DESC, name")
    return [TemplateRow(r["id"], r["name"], bool(r["builtin"]), EventProfile.from_json(r["profile_json"]))
            for r in rows]


def save_template(db: Database, name: str, profile: EventProfile, template_id: int | None = None) -> int:
    if template_id:
        db.execute("UPDATE templates SET name = ?, profile_json = ?, updated_at = datetime('now','localtime') "
                   "WHERE id = ?", (name, profile.to_json(), template_id))
        return template_id
    cur = db.execute("INSERT INTO templates(name, builtin, profile_json) VALUES(?,0,?)", (name, profile.to_json()))
    return int(cur.lastrowid)


def delete_template(db: Database, template_id: int) -> None:
    row = db.query("SELECT name, builtin FROM templates WHERE id = ?", (template_id,))
    if row and row[0]["builtin"]:
        removed = set(json.loads(db.meta_get("templates_removed", "[]"))) | {row[0]["name"]}
        db.meta_set("templates_removed", json.dumps(sorted(removed)))
    db.execute("DELETE FROM templates WHERE id = ?", (template_id,))


# ---------------------------------------------------------------- eventos y sets
@dataclass
class EventRow:
    id: int
    name: str
    event_type: str
    event_date: str
    venue: str
    profile: EventProfile
    created_at: str
    set_id: int | None = None
    track_count: int = 0


def save_event(db: Database, profile: EventProfile, event_id: int | None = None) -> int:
    if event_id:
        db.execute("UPDATE events SET name=?, event_type=?, event_date=?, venue=?, profile_json=?, "
                   "updated_at=datetime('now','localtime') WHERE id=?",
                   (profile.name, profile.event_type, profile.event_date, profile.venue, profile.to_json(), event_id))
        return event_id
    cur = db.execute("INSERT INTO events(name, event_type, event_date, venue, profile_json) VALUES(?,?,?,?,?)",
                     (profile.name, profile.event_type, profile.event_date, profile.venue, profile.to_json()))
    return int(cur.lastrowid)


def list_events(db: Database) -> list[EventRow]:
    rows = db.query("""
        SELECT e.*, (SELECT s.id FROM sets s WHERE s.event_id = e.id ORDER BY s.id DESC LIMIT 1) AS set_id
        FROM events e ORDER BY COALESCE(NULLIF(e.event_date,''), e.created_at) DESC, e.id DESC""")
    out = []
    for r in rows:
        count = 0
        if r["set_id"]:
            items = db.scalar("SELECT items_json FROM sets WHERE id = ?", (r["set_id"],))
            count = len(json.loads(items or "[]"))
        out.append(EventRow(r["id"], r["name"], r["event_type"] or "otro", r["event_date"] or "", r["venue"] or "",
                            EventProfile.from_json(r["profile_json"] or "{}"), r["created_at"], r["set_id"], count))
    return out


def get_event(db: Database, event_id: int) -> EventRow | None:
    for e in list_events(db):
        if e.id == event_id:
            return e
    return None


def delete_event(db: Database, event_id: int) -> None:
    db.execute("DELETE FROM sets WHERE event_id = ?", (event_id,))
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))


def save_set(db: Database, event_id: int, items: list[SetItem], summary: dict | None = None,
             discarded: list[dict] | None = None, set_id: int | None = None) -> int:
    items_json = json.dumps([i.to_dict() for i in items], ensure_ascii=False)
    s_json = json.dumps(summary or {}, ensure_ascii=False)
    d_json = json.dumps(discarded or [], ensure_ascii=False)
    if set_id:
        db.execute("UPDATE sets SET items_json=?, summary_json=?, discarded_json=?, "
                   "updated_at=datetime('now','localtime') WHERE id=?", (items_json, s_json, d_json, set_id))
        return set_id
    cur = db.execute("INSERT INTO sets(event_id, items_json, summary_json, discarded_json) VALUES(?,?,?,?)",
                     (event_id, items_json, s_json, d_json))
    return int(cur.lastrowid)


def load_set(db: Database, set_id: int) -> tuple[list[SetItem], dict, list[dict]]:
    r = db.query("SELECT items_json, summary_json, discarded_json FROM sets WHERE id = ?", (set_id,))
    if not r:
        return [], {}, []
    return ([SetItem.from_dict(d) for d in json.loads(r[0]["items_json"])],
            json.loads(r[0]["summary_json"] or "{}"), json.loads(r[0]["discarded_json"] or "[]"))


# ---------------------------------------------------------------- aprendizaje
def add_feedback(db: Database, event_type: str, kind: str, track_key: str = "", artist: str = "",
                 label: str = "") -> None:
    db.execute("INSERT INTO feedback(event_type, kind, track_key, artist, label) VALUES(?,?,?,?,?)",
               (event_type, kind, track_key, artist, label))


def list_feedback(db: Database, event_type: str | None = None) -> list[dict]:
    if event_type:
        rows = db.query("SELECT * FROM feedback WHERE event_type = ? ORDER BY id DESC", (event_type,))
    else:
        rows = db.query("SELECT * FROM feedback ORDER BY id DESC")
    return [dict(r) for r in rows]


def delete_feedback(db: Database, feedback_id: int) -> None:
    db.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))


@dataclass
class LearnedRules:
    banned_artists: set[str]
    banned_tracks: set[str]
    disliked: dict[str, int]        # track_key -> veces
    liked: dict[str, int]


def learned_rules(db: Database, event_type: str) -> LearnedRules:
    from .normalize import main_artist
    r = LearnedRules(set(), set(), {}, {})
    for f in list_feedback(db, event_type):
        if f["kind"] == "ban_artist" and f["artist"]:
            r.banned_artists.add(main_artist(f["artist"]))
        elif f["kind"] == "ban_track" and f["track_key"]:
            r.banned_tracks.add(f["track_key"])
        elif f["kind"] == "dislike" and f["track_key"]:
            r.disliked[f["track_key"]] = r.disliked.get(f["track_key"], 0) + 1
        elif f["kind"] == "like" and f["track_key"]:
            r.liked[f["track_key"]] = r.liked.get(f["track_key"], 0) + 1
    return r


# ---------------------------------------------------------------- playlists curadas
def list_curated(db: Database, enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM curated_playlists" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY id"
    out = []
    for r in db.query(sql):
        d = dict(r)
        d["genres"] = json.loads(d.get("genres") or "[]")
        d["event_types"] = json.loads(d.get("event_types") or "[]")
        out.append(d)
    return out


def add_curated(db: Database, platform: str, url: str, playlist_id: str, name: str,
                genres: list[str], event_types: list[str]) -> int:
    cur = db.execute("INSERT INTO curated_playlists(platform, url, playlist_id, name, genres, event_types) "
                     "VALUES(?,?,?,?,?,?)", (platform, url, playlist_id, name, json.dumps(genres),
                                             json.dumps(event_types)))
    return int(cur.lastrowid)


def delete_curated(db: Database, cid: int) -> None:
    db.execute("DELETE FROM curated_playlists WHERE id = ?", (cid,))
