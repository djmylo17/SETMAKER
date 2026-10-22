"""Me falta: temas del set que no tienes (o tienes en otra versión), con links para conseguirlos,
exportaciones (Excel, CSV, TXT, JSON para CrateDJ) y playlist en Spotify."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QMenu, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QWidget)

from ...context import AppContext
from ...core.models import MISSING, OTHER_VERSION, STATUS_LABELS, EventProfile, SetItem
from ...export import (export_cratedj_json, export_csv, export_txt, export_xlsx, pool_settings,
                       safe_filename, search_links)
from ...export.tables import block_name, genre_display
from ..widgets import Card, Page, badge, muted, run_in_background, set_badge, styled_button

EMPTY_TEXT = "Abre o genera un set para ver lo que te falta."

# formato -> (función, extensión, texto del menú)
FORMATS = {
    "xlsx": (export_xlsx, "xlsx", "Excel (.xlsx)"),
    "csv": (export_csv, "csv", "CSV (para Excel u otras apps)"),
    "txt": (export_txt, "txt", "Texto simple (.txt)"),
}


class _Relay(QObject):
    """Pasa mensajes desde el hilo de fondo a la ventana (Qt exige hacerlo con señales)."""
    message = Signal(str)


class MissingPage(Page):
    def __init__(self, ctx: AppContext, status_cb: Callable[[str], None]):
        super().__init__("Me falta",
                         "Los temas del set que no tienes o que tienes en otra versión, con links para "
                         "conseguirlos. También puedes exportar el set o crear una playlist en Spotify.")
        self.ctx = ctx
        self.status_msg = status_cb
        self.profile: EventProfile | None = None
        self.items: list[SetItem] = []
        self.genre_names: dict = {}
        self._busy = False
        self._relay = _Relay()
        self._relay.message.connect(self.status_msg)

        # ---------- acciones ----------
        top = Card()
        row = QHBoxLayout()
        self.lbl_set = muted(EMPTY_TEXT)
        row.addWidget(self.lbl_set, 1)
        self.counter = badge("")
        row.addWidget(self.counter)
        top.body.addLayout(row)

        btns = QHBoxLayout()
        self.b_missing = styled_button(QPushButton("Exportar faltantes ▾"), "primary")
        m1 = QMenu(self.b_missing)
        for key, (_fn, _ext, label) in FORMATS.items():
            m1.addAction(label, lambda k=key: self.export(k, only_missing=True))
        self.b_missing.setMenu(m1)

        self.b_full = QPushButton("Exportar set completo ▾")
        m2 = QMenu(self.b_full)
        for key, (_fn, _ext, label) in FORMATS.items():
            m2.addAction(label, lambda k=key: self.export(k, only_missing=False))
        m2.addSeparator()
        m2.addAction("JSON para CrateDJ", lambda: self.export("json", only_missing=False))
        self.b_full.setMenu(m2)

        self.b_spotify = QPushButton("Crear playlist en Spotify ▾")
        m3 = QMenu(self.b_spotify)
        m3.addAction("Con el set completo", lambda: self.spotify_playlist(only_missing=False))
        m3.addAction("Solo con los que me faltan", lambda: self.spotify_playlist(only_missing=True))
        self.b_spotify.setMenu(m3)

        for b in (self.b_missing, self.b_full, self.b_spotify):
            btns.addWidget(b)
        btns.addStretch(1)
        top.body.addLayout(btns)
        self.add(top)

        # ---------- tabla ----------
        self.table_card = Card("Temas por conseguir")
        self.empty = muted(EMPTY_TEXT)
        self.table_card.body.addWidget(self.empty)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["#", "Bloque", "Artista", "Título", "Género", "Estado", "Buscar en"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.setMinimumHeight(420)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(4, 130)
        self.table.setColumnWidth(5, 110)
        self.table_card.body.addWidget(self.table)
        self.add(self.table_card)
        self.finish()
        self._refresh()

    # ---------------------------------------------------------------- datos
    def set_set(self, profile: EventProfile | None, items: list[SetItem], genre_names: dict | None = None):
        """La ventana principal llama esto cuando se abre/genera/cierra un set."""
        self.profile = profile
        self.items = list(items or [])
        self.genre_names = dict(genre_names or {})
        self._refresh()

    def on_show(self) -> None:
        # Por si cambió el pool en Ajustes
        self._refresh()

    def missing_items(self) -> list[tuple[int, SetItem]]:
        return [(pos, it) for pos, it in enumerate(self.items, start=1)
                if it.status in (MISSING, OTHER_VERSION)]

    def _refresh(self):
        has_set = self.profile is not None and bool(self.items)
        for b in (self.b_missing, self.b_full, self.b_spotify):
            b.setEnabled(has_set)
        if not has_set:
            self.lbl_set.setText(EMPTY_TEXT)
            set_badge(self.counter, "Sin set", "off")
            self.empty.setText(EMPTY_TEXT)
            self.empty.show()
            self.table.hide()
            self.table.setRowCount(0)
            return

        rows = self.missing_items()
        p = self.profile
        info = " · ".join(x for x in (p.event_date, p.venue) if x)
        self.lbl_set.setText(f"<b>{p.name}</b>" + (f" — {info}" if info else "") +
                             f" · {len(self.items)} temas en el set")
        if rows:
            set_badge(self.counter, f"Te faltan {len(rows)}", "warn")
        else:
            set_badge(self.counter, "Tienes todo", "ok")
        self.b_missing.setEnabled(bool(rows))

        if not rows:
            self.empty.setText("¡Tienes todos los temas de este set! Igual puedes exportarlo o crear la playlist.")
            self.empty.show()
            self.table.hide()
            self.table.setRowCount(0)
            return
        self.empty.hide()
        self.table.show()
        pool_name, pool_tpl = pool_settings(self.ctx.config)
        self.table.setRowCount(len(rows))
        for r, (pos, it) in enumerate(rows):
            values = [str(pos), block_name(p, it.block), it.track.artist, it.track.title,
                      genre_display(it.cls.primary, self.genre_names), STATUS_LABELS.get(it.status, it.status)]
            for c, v in enumerate(values):
                cell = QTableWidgetItem(v)
                if c == 0:
                    cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, cell)
            self.table.setCellWidget(r, 6, self._link_buttons(it, pool_tpl, pool_name))
        self.table.resizeRowsToContents()

    def _link_buttons(self, it: SetItem, pool_tpl: str, pool_name: str) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(4)
        for label, url in search_links(it.track.artist, it.track.title, pool_tpl, pool_name):
            b = QPushButton(label)
            b.setToolTip(f"Buscar «{it.track.artist} - {it.track.title}» en {label}")
            b.setStyleSheet("padding: 3px 8px;")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            lay.addWidget(b)
        return w

    # ---------------------------------------------------------------- exportar
    def export_dir(self) -> Path:
        custom = (self.ctx.config.get("export.dir", "") or "").strip()
        return Path(custom) if custom else self.ctx.data_dir / "exports"

    def file_name(self, suffix: str, ext: str) -> str:
        p = self.profile
        when = (p.event_date if p and p.event_date else date.today().isoformat())
        name = p.name if p else "Set"
        return safe_filename(f"{when} {name} - {suffix}") + "." + ext

    def export(self, fmt: str, only_missing: bool) -> Path | None:
        if not self.profile or not self.items:
            QMessageBox.information(self, "Exportar", EMPTY_TEXT)
            return None
        folder = self.export_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            QMessageBox.warning(self, "Exportar", f"No se puede usar la carpeta:\n{folder}\n\n"
                                "Revisa la carpeta de exportaciones en Ajustes (¿disco desconectado?).")
            return None
        suffix = "faltantes" if only_missing else ("crate CrateDJ" if fmt == "json" else "set")
        try:
            if fmt == "json":
                path = folder / self.file_name(suffix, "json")
                export_cratedj_json(self.items, self.profile, path, genre_names=self.genre_names)
            else:
                fn, ext, _label = FORMATS[fmt]
                path = folder / self.file_name(suffix, ext)
                fn(self.items, self.profile, path, only_missing=only_missing, genre_names=self.genre_names)
        except PermissionError:
            QMessageBox.warning(self, "Exportar", "No se pudo guardar el archivo. Si lo tienes abierto en "
                                "Excel, ciérralo y vuelve a intentar.")
            return None
        except OSError as exc:
            QMessageBox.warning(self, "Exportar", f"No se pudo guardar el archivo:\n{exc}")
            return None
        self.status_msg(f"Guardado: {path.name}")
        self._show_saved(path)
        return path

    def _show_saved(self, path: Path):
        box = QMessageBox(self)
        box.setWindowTitle("Exportar")
        box.setIcon(QMessageBox.Information)
        box.setText(f"Listo, se guardó:\n{path.name}\n\nEn la carpeta:\n{path.parent}")
        b_open = box.addButton("Abrir carpeta", QMessageBox.AcceptRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    # ---------------------------------------------------------------- Spotify
    def spotify_playlist(self, only_missing: bool):
        if self._busy:
            self.status_msg("Espera, ya hay una playlist en proceso…")
            return
        if not self.profile or not self.items:
            QMessageBox.information(self, "Spotify", EMPTY_TEXT)
            return
        if only_missing and not self.missing_items():
            QMessageBox.information(self, "Spotify", "No te falta ningún tema en este set.")
            return
        try:
            client_id = self.ctx.vault.get("spotify_client_id")
        except Exception:  # noqa: BLE001 — bóveda bloqueada
            client_id = ""
        if not client_id:
            QMessageBox.information(self, "Spotify",
                                    "Primero agrega tu Client ID de Spotify en «Fuentes y claves». "
                                    "Ahí están los pasos para crearlo (toma 2 minutos).")
            return
        from ...sources.spotify import SpotifyClient
        client = SpotifyClient(self.ctx.vault, client_id)
        if not client.is_connected():
            ok = QMessageBox.question(self, "Spotify",
                                      "Se abrirá tu navegador para que aceptes que SETMAKER cree playlists "
                                      "en tu cuenta de Spotify. Después vuelve aquí.\n\n¿Continuar?")
            if ok != QMessageBox.Yes:
                return

        p = self.profile
        name = f"{p.name}{' - faltantes' if only_missing else ''}"
        if p.event_date:
            name = f"{p.event_date} {name}"
        desc = f"Creada con SETMAKER para {p.name}" + (f" ({p.venue})" if p.venue else "")
        items = list(self.items)
        relay = self._relay

        def work():
            if not client.is_connected():
                relay.message.emit("Esperando que aceptes los permisos en el navegador…")
                client.connect()
            return client.create_playlist_from_items(
                items, name, desc, only_missing=only_missing,
                progress=lambda n, t: relay.message.emit(f"Buscando en Spotify… {n} de {t}"))

        self._busy = True
        self.b_spotify.setEnabled(False)
        self.status_msg("Creando playlist en Spotify…")
        run_in_background(work, self._spotify_done, self._spotify_failed)

    def _spotify_done(self, res: dict):
        self._busy = False
        self.b_spotify.setEnabled(True)
        self.status_msg(f"Playlist creada con {res.get('added', 0)} temas ✓")
        nf = res.get("not_found") or []
        text = f"Playlist creada con {res.get('added', 0)} temas."
        if nf:
            shown = "\n".join("• " + x for x in nf[:15])
            more = f"\n… y {len(nf) - 15} más" if len(nf) > 15 else ""
            text += f"\n\nNo encontré en Spotify estos {len(nf)}:\n{shown}{more}"
        box = QMessageBox(self)
        box.setWindowTitle("Spotify")
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        b_open = box.addButton("Abrir en Spotify", QMessageBox.AcceptRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open and res.get("url"):
            QDesktopServices.openUrl(QUrl(res["url"]))

    def _spotify_failed(self, msg: str):
        self._busy = False
        self.b_spotify.setEnabled(True)
        self.status_msg("No se pudo crear la playlist")
        QMessageBox.warning(self, "Spotify", msg)
