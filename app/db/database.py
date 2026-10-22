"""Base de datos SQLite de SETMAKER (data/setmaker.db).

Usa "migraciones" numeradas: cada versión nueva de la app agrega sus tablas
sin borrar lo que ya tienes. La versión del esquema se guarda en PRAGMA user_version.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# (versión, SQL). Nunca modificar una migración ya publicada: solo agregar nuevas al final.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        -- Caché de todo lo consultado a fuentes externas (Deezer, Apple, Last.fm, etc.)
        CREATE TABLE IF NOT EXISTS api_cache (
            source     TEXT NOT NULL,
            key        TEXT NOT NULL,
            payload    TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (source, key)
        );

        -- Eventos / sets que preparas
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            event_type   TEXT,
            event_date   TEXT,
            venue        TEXT,
            profile_json TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
        """,
    ),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Modo de diario clásico (no WAL): más seguro en discos portátiles que se desconectan.
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    # ---------- esquema ----------
    def version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        with self._lock:
            current = self.version()
            for ver, sql in MIGRATIONS:
                if ver > current:
                    log.info("Aplicando migración de base de datos v%s", ver)
                    with self.conn:
                        self.conn.executescript(sql)
                        self.conn.execute(f"PRAGMA user_version = {int(ver)}")

    # ---------- utilidades ----------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock, self.conn:
            return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
            return row[0] if row else None

    # ---------- meta ----------
    def meta_get(self, key: str, default: str | None = None) -> str | None:
        val = self.scalar("SELECT value FROM meta WHERE key = ?", (key,))
        return default if val is None else val

    def meta_set(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ---------- caché de APIs ----------
    def cache_get(self, source: str, key: str, max_age_hours: float | None = None) -> Any | None:
        """Devuelve el dato cacheado o None si no existe o está vencido."""
        row = self.query(
            "SELECT payload, fetched_at FROM api_cache WHERE source = ? AND key = ?",
            (source, key),
        )
        if not row:
            return None
        payload, fetched_at = row[0]["payload"], row[0]["fetched_at"]
        if max_age_hours is not None:
            age = datetime.now() - datetime.fromisoformat(fetched_at)
            if age > timedelta(hours=max_age_hours):
                return None
        return json.loads(payload)

    def cache_put(self, source: str, key: str, payload: Any) -> None:
        self.execute(
            "INSERT INTO api_cache(source, key, payload, fetched_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(source, key) DO UPDATE SET payload = excluded.payload, "
            "fetched_at = excluded.fetched_at",
            (source, key, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )

    def cache_clear(self, source: str | None = None) -> int:
        if source:
            cur = self.execute("DELETE FROM api_cache WHERE source = ?", (source,))
        else:
            cur = self.execute("DELETE FROM api_cache")
        return cur.rowcount

    # ---------- respaldo ----------
    def backup_to(self, dest: Path) -> None:
        """Copia consistente de la base aunque esté abierta (API de respaldo de SQLite)."""
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self.conn.backup(target)
            finally:
                target.close()

    def close(self) -> None:
        with self._lock:
            self.conn.close()
