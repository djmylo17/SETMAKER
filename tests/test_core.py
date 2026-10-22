import json

import pytest

from app.backup import BackupError, apply_pending_restore, create_backup, schedule_restore
from app.config import Config
from app.db.database import SCHEMA_VERSION, Database
from app.security.vault import KeyVault, VaultLocked, WrongPassword
from app.sources import checks
from app.sources.checks import choose_default_model


# ---------------------------------------------------------------- rutas / config
def test_data_dir_creates_subfolders(data_dir):
    for sub in ("backups", "exports", "logs"):
        assert (data_dir / sub).is_dir()


def test_config_defaults_and_persistence(data_dir):
    cfg = Config(data_dir / "config.json")
    assert cfg.get("region.country") == "CL"
    cfg.set("virtualdj.database_xml", r"E:\VirtualDJ\database.xml")
    again = Config(data_dir / "config.json")
    assert again.get("virtualdj.database_xml") == r"E:\VirtualDJ\database.xml"
    assert again.get("library.ignore_karaoke") is True  # clave por defecto se conserva


def test_config_survives_corruption(data_dir):
    p = data_dir / "config.json"
    p.write_text("{esto no es json", encoding="utf-8")
    cfg = Config(p)
    assert cfg.get("region.country") == "CL"
    assert (data_dir / "config.json.danado").exists()


# ---------------------------------------------------------------- base de datos
def test_database_migrates_and_caches(data_dir):
    db = Database(data_dir / "setmaker.db")
    assert db.version() == SCHEMA_VERSION
    db.cache_put("deezer", "chart:CL", {"tracks": [1, 2, 3]})
    assert db.cache_get("deezer", "chart:CL") == {"tracks": [1, 2, 3]}
    assert db.cache_get("deezer", "chart:CL", max_age_hours=1) is not None
    assert db.cache_get("deezer", "otra") is None
    db.close()
    # Reabrir no vuelve a migrar ni pierde datos
    db2 = Database(data_dir / "setmaker.db")
    assert db2.cache_get("deezer", "chart:CL") == {"tracks": [1, 2, 3]}
    db2.close()


# ---------------------------------------------------------------- bóveda
def test_vault_without_password(data_dir):
    v = KeyVault(data_dir / "keys.enc")
    v.unlock()
    v.set("gemini_api_key", "AIzaPRUEBA123")
    raw = (data_dir / "keys.enc").read_text()
    assert "AIzaPRUEBA123" not in raw          # no queda en texto plano
    v2 = KeyVault(data_dir / "keys.enc")
    assert not v2.is_protected()
    v2.unlock()
    assert v2.get("gemini_api_key") == "AIzaPRUEBA123"


def test_vault_with_password(data_dir):
    v = KeyVault(data_dir / "keys.enc")
    v.unlock()
    v.set("lastfm_api_key", "abc")
    v.set_password("milo2026")
    v2 = KeyVault(data_dir / "keys.enc")
    assert v2.is_protected()
    with pytest.raises(VaultLocked):
        v2.unlock()
    with pytest.raises(WrongPassword):
        v2.unlock("otra")
    v2.unlock("milo2026")
    assert v2.get("lastfm_api_key") == "abc"
    v2.set_password(None)
    v3 = KeyVault(data_dir / "keys.enc")
    v3.unlock()
    assert v3.get("lastfm_api_key") == "abc"


def test_vault_empty_value_removes_key(data_dir):
    v = KeyVault(data_dir / "keys.enc")
    v.unlock()
    v.set("youtube_api_key", "x")
    v.set("youtube_api_key", "  ")
    assert v.configured() == []


# ---------------------------------------------------------------- respaldo
def test_backup_and_restore_roundtrip(data_dir):
    db = Database(data_dir / "setmaker.db")
    cfg = Config(data_dir / "config.json")
    db.execute("INSERT INTO events(name, event_type) VALUES ('Cumple Sofía', 'cumple_infantil')")
    cfg.set("region.country", "AR")
    zip_path = create_backup(data_dir, db)

    db.execute("DELETE FROM events")
    cfg.set("region.country", "MX")
    db.close()

    pending = data_dir / "_restauracion_pendiente.zip"
    schedule_restore(zip_path, pending)
    assert apply_pending_restore(data_dir, pending)
    assert not pending.exists()

    db2 = Database(data_dir / "setmaker.db")
    assert db2.scalar("SELECT name FROM events") == "Cumple Sofía"
    assert Config(data_dir / "config.json").get("region.country") == "AR"
    db2.close()


def test_restore_rejects_foreign_zip(data_dir, tmp_path):
    import zipfile
    bad = tmp_path / "otro.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("hola.txt", "x")
    with pytest.raises(BackupError):
        schedule_restore(bad, data_dir / "_p.zip")


# ---------------------------------------------------------------- Gemini: elección de modelo
def test_choose_default_model_prefers_newest_stable_flash():
    names = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.7-flash", "gemini-3.6-flash",
             "gemini-3.5-flash-lite", "gemini-3.7-flash-live", "gemini-3.1-pro-preview"]
    assert choose_default_model(names) == "gemini-3.7-flash"


def test_choose_default_model_falls_back_to_preview():
    assert choose_default_model(["gemini-4-flash-preview", "gemini-pro"]) == "gemini-4-flash-preview"
    assert choose_default_model(["gemini-pro"]) == ""


# ---------------------------------------------------------------- pruebas de conexión (simuladas)
def test_check_gemini_parses_models(monkeypatch):
    fake = {"models": [
        {"name": "models/gemini-3.7-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    ]}
    monkeypatch.setattr(checks, "get_json", lambda *a, **k: fake)
    r = checks.check_gemini("AIzaX")
    assert r.ok and r.extra["default"] == "gemini-3.7-flash"
    assert "text-embedding-004" not in r.extra["models"]


def test_check_lastfm_detects_invalid_key(monkeypatch):
    monkeypatch.setattr(checks, "get_json", lambda *a, **k: {"error": 10, "message": "Invalid API key"})
    r = checks.check_lastfm("mala")
    assert not r.ok and "Invalid" in r.message


def test_check_source_error_is_friendly(monkeypatch):
    from app.net import SourceError

    def boom(*a, **k):
        raise SourceError("No hay conexión a internet o el servicio no responde.")
    monkeypatch.setattr(checks, "get_json", boom)
    r = checks.check_deezer()
    assert not r.ok and "internet" in r.message


def test_check_apple_counts(monkeypatch):
    monkeypatch.setattr(checks, "get_json", lambda *a, **k: {"feed": {"results": [{}] * 10}})
    assert checks.check_apple("CL").ok


def test_spotify_client_id_format():
    assert checks.check_spotify_client_id("a" * 32).ok
    assert not checks.check_spotify_client_id("abc").ok


def test_friendly_status_messages():
    from app.net import friendly_status
    assert "límite" in friendly_status(429)
    assert "clave" in friendly_status(403)
