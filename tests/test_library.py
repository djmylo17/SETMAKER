"""Pruebas de la biblioteca: VirtualDJ, escáner, coincidencias y exportación .vdjfolder."""
import os
import time
import wave
import xml.etree.ElementTree as ET

import pytest

from app.core.models import HAVE, MISSING, OTHER_VERSION, Classification, SetItem, Track
from app.core.normalize import track_key
from app.db.database import Database
from app.library.matcher import LibraryMatcher, match_items
from app.library.scanner import scan_folders
from app.library.vdj_db import INSERT_SQL, build_row, import_vdj_database, spb_to_bpm
from app.library.vdjfolder import export_vdjfolder, safe_filename

VDJ_XML = """<?xml version="1.0" encoding="UTF-8"?>
<VirtualDJ_Database Version="8.5">
 <Song FilePath="E:\\Musica\\Bad Bunny - Titi Me Pregunto (Extended Clean).mp3" FileSize="8123456">
  <Tags Author="Bad Bunny" Title="Titi Me Pregunto (Extended Clean)" Genre="Reggaeton" Year="2022" />
  <Infos SongLength="245.3" Bitrate="320" />
  <Comment>pool</Comment>
  <Scan Version="801" Bpm="0.5" AltBpm="1.0" Volume="1.1" Key="Am" Flag="1" />
  <Poi Pos="1.2" Type="beatgrid" />
 </Song>
 <Song FilePath="E:\\Karaoke\\Shakira - Hips Dont Lie.cdg" FileSize="1000">
  <Tags Author="Shakira" Title="Hips Don't Lie" />
 </Song>
 <Song FilePath="E:\\Karaoke\\Juanes - La Camisa Negra (Karaoke).mp3" FileSize="2000">
  <Tags Author="Juanes" Title="La Camisa Negra (Karaoke)" Genre="Karaoke" />
 </Song>
 <Song FilePath="netsearch://dz12345" FileSize="0">
  <Tags Author="Online" Title="Streaming" />
 </Song>
 <Song FilePath="E:\\Videos\\Daddy Yankee - Gasolina.mp4" FileSize="99999">
  <Tags Author="Daddy Yankee" Title="Gasolina" />
 </Song>
 <Song FilePath="E:\\Musica\\Karol G - Provenza.flac" FileSize="30000000">
  <Tags Author="" Title="" />
  <Scan Bpm="0" Key="" />
 </Song>
</VirtualDJ_Database>
"""


@pytest.fixture
def db(data_dir):
    d = Database(data_dir / "setmaker.db")
    yield d
    d.close()


def _write_wav(path, seconds=0.1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 2 * int(44100 * seconds))


def _add(db, path, artist, title, *, fmt_bitrate=None, karaoke=False, source="scan"):
    row = build_row(path, source, artist, title, bitrate=fmt_bitrate, is_karaoke=karaoke)
    db.execute(INSERT_SQL, row)


def _item(artist, title):
    return SetItem(track=Track(key=track_key(artist, title), title=title, artist=artist),
                   cls=Classification(genres=["reggaeton"]))


# ---------------------------------------------------------------- VirtualDJ
def test_spb_to_bpm():
    assert spb_to_bpm("0.5") == 120.0
    assert spb_to_bpm("0.468750") == 128.0
    assert spb_to_bpm("0") == 0.0
    assert spb_to_bpm("abc") == 0.0


def test_import_vdj(db, tmp_path):
    xml = tmp_path / "database.xml"
    xml.write_text(VDJ_XML, encoding="utf-8")
    seen = []
    stats = import_vdj_database(db, xml, progress=lambda d, t, m: seen.append(m))
    assert stats == {"total": 6, "imported": 4, "karaoke": 2, "skipped": 2}
    assert seen  # al menos un aviso de progreso
    r = db.query("SELECT * FROM library_tracks WHERE path LIKE '%Titi%'")[0]
    assert r["bpm"] == 120.0 and r["musical_key"] == "Am" and r["bitrate"] == 320
    assert r["format"] == "mp3" and r["norm_artist"] == "bad bunny" and r["norm_title"] == "titi me pregunto"
    assert r["duration"] == pytest.approx(245.3) and r["size"] == 8123456 and r["is_karaoke"] == 0
    # título vacío -> desde el nombre del archivo
    k = db.query("SELECT * FROM library_tracks WHERE path LIKE '%Provenza%'")[0]
    assert k["artist"] == "Karol G" and k["title"] == "Provenza" and k["format"] == "flac" and k["bpm"] is None
    assert db.scalar("SELECT COUNT(*) FROM library_tracks WHERE is_karaoke=1") == 2
    assert db.scalar("SELECT COUNT(*) FROM library_tracks WHERE path LIKE 'netsearch%'") == 0
    # reimportar reemplaza (no duplica) y no toca las filas escaneadas
    _add(db, "C:\\otra\\X - Y.mp3", "X", "Y")
    import_vdj_database(db, xml)
    assert db.scalar("SELECT COUNT(*) FROM library_tracks WHERE source='vdj'") == 4
    assert db.scalar("SELECT COUNT(*) FROM library_tracks WHERE source='scan'") == 1


def test_import_vdj_broken_keeps_data(db, tmp_path):
    xml = tmp_path / "database.xml"
    xml.write_text(VDJ_XML, encoding="utf-8")
    import_vdj_database(db, xml)
    xml.write_text(VDJ_XML[:400], encoding="utf-8")
    with pytest.raises(ValueError):
        import_vdj_database(db, xml)
    assert db.scalar("SELECT COUNT(*) FROM library_tracks WHERE source='vdj'") == 4


# ---------------------------------------------------------------- escáner
def test_scanner(db, tmp_path):
    music = tmp_path / "musica"
    (music / "sub").mkdir(parents=True)
    _write_wav(music / "Feid - Classy 101.wav")
    _write_wav(music / "sub" / "Young Miko - Riri.wav")
    (music / "sub" / "roto.mp3").write_bytes(b"esto no es un mp3")
    (music / "notas.txt").write_text("hola")

    s = scan_folders(db, [str(music), str(tmp_path / "no_existe")])
    assert s["found"] == 3 and s["new"] == 3 and s["errors"] == 0
    assert s["missing_folders"]
    r = db.query("SELECT * FROM library_tracks WHERE path LIKE '%Classy%'")[0]
    assert r["source"] == "scan" and r["artist"] == "Feid" and r["title"] == "Classy 101"
    assert r["format"] == "wav" and r["bitrate"] == 1411 and r["duration"] == pytest.approx(0.1, abs=0.01)

    # incremental: nada cambió
    s2 = scan_folders(db, [str(music)])
    assert s2["unchanged"] == 3 and s2["new"] == 0

    # un archivo desaparece, otro cambia
    os.remove(music / "sub" / "Young Miko - Riri.wav")
    _write_wav(music / "Feid - Classy 101.wav", seconds=0.2)
    future = time.time() + 10
    os.utime(music / "Feid - Classy 101.wav", (future, future))
    s3 = scan_folders(db, [str(music)])
    assert s3["removed"] == 1 and s3["updated"] == 1
    assert db.scalar("SELECT COUNT(*) FROM library_tracks WHERE source='scan'") == 2


def test_scanner_skips_vdj_paths_and_cancel(db, tmp_path):
    music = tmp_path / "m"
    music.mkdir()
    f = music / "A - B.wav"
    _write_wav(f)
    _add(db, str(f), "A", "B", source="vdj")
    s = scan_folders(db, [str(music)])
    assert s["skipped_vdj"] == 1 and s["new"] == 0
    assert db.query("SELECT source FROM library_tracks")[0]["source"] == "vdj"
    s2 = scan_folders(db, [str(music)], cancel=lambda: True)
    assert s2["cancelled"] and db.scalar("SELECT COUNT(*) FROM library_tracks") == 1


# ---------------------------------------------------------------- coincidencias
def test_matcher(db):
    _add(db, "E:\\M\\Bad Bunny - Titi Me Pregunto (Extended Clean).mp3", "Bad Bunny",
         "Titi Me Pregunto (Extended Clean)", fmt_bitrate=320)
    _add(db, "E:\\M\\Bad Bunny - Titi Me Pregunto.mp3", "Bad Bunny", "Titi Me Pregunto", fmt_bitrate=128)
    _add(db, "E:\\M\\Bad Bunny - Titi Me Pregunto.wav", "", "Bad Bunny - Titi Me Pregunto")
    _add(db, "E:\\M\\Karol G - Provenza (Remix).mp3", "Karol G", "Provenza (Remix)", fmt_bitrate=320)
    _add(db, "E:\\K\\Juanes - La Camisa Negra (Karaoke).mp3", "Juanes", "La Camisa Negra", karaoke=True)
    for i in range(300):  # relleno para que haya volumen
        _add(db, f"E:\\R\\Artista {i} - Tema {i}.mp3", f"Artista {i}", f"Tema numero {i}", fmt_bitrate=192)

    m = LibraryMatcher(db, ignore_karaoke=True)
    st, paths = m.match("Bad Bunny", "Tití Me Preguntó")
    assert st == HAVE
    assert paths[0]["format"] == "wav"                    # mejor calidad primero
    assert [p["bitrate"] for p in paths[1:]] == [320, 128]
    assert "sin pérdida" in paths[0]["quality_label"] and paths[1]["quality_label"] == "MP3 320"

    st, paths = m.match("Karol G", "Provenza")
    assert st == OTHER_VERSION and "Remix" in paths[0]["title"]

    assert m.match("Bad Bunny", "Monaco")[0] == MISSING
    assert m.match("Peso Pluma", "Ella Baila Sola")[0] == MISSING

    # karaoke ignorado / incluido
    assert m.match("Juanes", "La Camisa Negra")[0] == MISSING
    assert LibraryMatcher(db, ignore_karaoke=False).match("Juanes", "La Camisa Negra")[0] == HAVE

    # correcciones manuales
    k = track_key("Bad Bunny", "Tití Me Preguntó")
    m.set_override(k, "")
    assert m.match("Bad Bunny", "Tití Me Preguntó", k) == (MISSING, [])
    m.set_override(track_key("Peso Pluma", "Ella Baila Sola"), "E:\\M\\Bad Bunny - Titi Me Pregunto.mp3")
    st, paths = LibraryMatcher(db).match("Peso Pluma", "Ella Baila Sola")  # persistido en la base
    assert st == HAVE and paths[0]["bitrate"] == 128
    m.clear_override(k)
    assert m.match("Bad Bunny", "Tití Me Preguntó")[0] == HAVE

    # search
    assert any("Provenza" in r["title"] for r in m.search("provenza"))
    assert len(m.search("", limit=50)) == 50


def test_match_items_and_speed(db):
    rows = [build_row(f"E:\\R\\Artista {i} - Tema {i}.mp3", "vdj", f"Artista {i}", f"Cancion {i} de prueba",
                      bitrate=320) for i in range(11000)]
    with db.conn:
        db.conn.executemany(INSERT_SQL, rows)
    _add(db, "E:\\M\\Feid - Classy 101.mp3", "Feid feat. Young Miko", "Classy 101", fmt_bitrate=320)
    items = [_item("Feid", "Classy 101"), _item("Nadie", "Nada que ver")] + \
            [_item(f"Otro {i}", f"Tema raro {i}") for i in range(98)]
    t0 = time.perf_counter()
    m = LibraryMatcher(db)
    counts = match_items(db, items, matcher=m)
    elapsed = time.perf_counter() - t0
    assert items[0].status == HAVE and items[0].local_paths[0]["path"].endswith("Classy 101.mp3")
    assert items[1].status == MISSING and items[1].local_paths == []
    assert counts[HAVE] == 1 and counts[MISSING] == 99
    assert elapsed < 3.0, elapsed  # carga + 100 temas (en máquina normal < 1 s)


# ---------------------------------------------------------------- .vdjfolder
def test_export_vdjfolder(tmp_path):
    a = _item("Bad Bunny & Ñengo Flow", 'Tema "Uno" & Más')
    a.status = HAVE
    a.local_paths = [{"path": "E:\\Música\\Bad Bunny & Ñengo - Tema \"Uno\".mp3", "artist": "Bad Bunny & Ñengo Flow",
                      "title": 'Tema "Uno" & Más', "bpm": 120.0, "musical_key": "Am", "duration": 201.5,
                      "size": 123}]
    b = _item("X", "Falta")
    b.status = MISSING
    c = _item("Y", "Otra")
    c.status = OTHER_VERSION
    c.local_paths = [{"path": "E:\\otra.mp3"}]
    out = export_vdjfolder([a, b, c], tmp_path / "Folders", 'Matri: "Ana" <2026>?')
    assert out.exists() and out.suffix == ".vdjfolder"
    assert not any(ch in out.name for ch in '<>:"?')
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    text = raw.decode("utf-8")
    assert "&amp;" in text and "&quot;" in text and "Ñengo" in text
    root = ET.fromstring(raw)
    assert root.tag == "VirtualFolder"
    songs = root.findall("song")
    assert len(songs) == 1
    s = songs[0]
    assert s.get("title") == 'Tema "Uno" & Más' and s.get("path").startswith("E:\\Música")
    assert float(s.get("bpm")) == pytest.approx(0.5) and s.get("key") == "Am"
    assert s.get("songlength") == "201.5" and s.get("size") == "123" and s.get("idx") == "0"


def test_safe_filename():
    assert safe_filename("CON") == "_CON"
    assert safe_filename('  a/b\\c:d*e?  .') == "a b c d e"
    assert safe_filename("") == "SETMAKER"
