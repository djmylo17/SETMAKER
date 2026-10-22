"""Tarjetas para Ajustes: «Salidas» (pool DJ + Spotify) y «Actualizaciones»."""
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton)

from ... import __version__
from ...context import AppContext
from ...export.links import DEFAULT_POOL_NAME, POOL_NAME_KEY, POOL_URL_KEY, pool_link
from ..widgets import Card, badge, muted, run_in_background, set_badge, styled_button

POOL_EXAMPLE = "https://mipool.com/search?q={artista} {titulo}"


class OutputsCard(Card):
    """Pool DJ para el botón de búsqueda y conexión con Spotify."""

    def __init__(self, ctx: AppContext, status_cb: Callable[[str], None]):
        super().__init__("Salidas")
        self.ctx = ctx
        self.status_msg = status_cb
        cfg = ctx.config

        # ---------- pool DJ ----------
        self.body.addWidget(muted("Tu pool DJ (opcional): en «Me falta» aparecerá un botón para buscar "
                                  "cada tema directo en tu pool."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre:"))
        self.ed_pool_name = QLineEdit(cfg.get(POOL_NAME_KEY, "") or "")
        self.ed_pool_name.setPlaceholderText(DEFAULT_POOL_NAME)
        self.ed_pool_name.setMaximumWidth(200)
        self.ed_pool_name.editingFinished.connect(self._save_pool)
        row.addWidget(self.ed_pool_name)
        row.addWidget(QLabel("Link de búsqueda:"))
        self.ed_pool_url = QLineEdit(cfg.get(POOL_URL_KEY, "") or "")
        self.ed_pool_url.setPlaceholderText(POOL_EXAMPLE)
        self.ed_pool_url.editingFinished.connect(self._save_pool)
        row.addWidget(self.ed_pool_url, 1)
        b_test = QPushButton("Probar")
        b_test.clicked.connect(self._test_pool)
        row.addWidget(b_test)
        self.body.addLayout(row)
        help_lbl = QLabel(
            "Cómo sacarlo: busca cualquier tema en la página de tu pool y copia el link de la barra del "
            "navegador. Cambia lo que buscaste por <b>{artista}</b> y <b>{titulo}</b> (o <b>{query}</b> "
            f"para ambos juntos).<br>Ejemplo: <i>{POOL_EXAMPLE}</i>")
        help_lbl.setObjectName("Help")
        help_lbl.setWordWrap(True)
        help_lbl.setTextFormat(Qt.RichText)
        self.body.addWidget(help_lbl)

        # ---------- Spotify ----------
        self.body.addSpacing(6)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("<b>Spotify</b>"))
        self.sp_badge = badge("")
        srow.addWidget(self.sp_badge)
        srow.addStretch(1)
        self.b_sp = styled_button(QPushButton("Conectar Spotify"), "primary")
        self.b_sp.clicked.connect(self._toggle_spotify)
        srow.addWidget(self.b_sp)
        self.body.addLayout(srow)
        self.body.addWidget(muted("Permite crear playlists privadas en tu cuenta con el set o con los temas que "
                                  "te faltan. Necesitas el Client ID guardado en «Fuentes y claves»."))
        self._busy = False
        self.refresh_spotify()

    # ---------- pool ----------
    def _save_pool(self):
        name = self.ed_pool_name.text().strip()
        url = self.ed_pool_url.text().strip().strip('"')
        self.ed_pool_url.setText(url)
        changed = False
        if name != (self.ctx.config.get(POOL_NAME_KEY, "") or ""):
            self.ctx.config.set(POOL_NAME_KEY, name)
            changed = True
        if url != (self.ctx.config.get(POOL_URL_KEY, "") or ""):
            self.ctx.config.set(POOL_URL_KEY, url)
            changed = True
            if url and not any(k in url for k in ("{artista}", "{titulo}", "{query}")):
                self.status_msg("Ojo: el link del pool necesita {artista}, {titulo} o {query}")
                return
        if changed:
            self.status_msg("Ajustes guardados ✓")

    def _test_pool(self):
        self._save_pool()
        url = pool_link("Bad Bunny", "Tití Me Preguntó", self.ed_pool_url.text())
        if not url:
            QMessageBox.information(self, "Pool DJ", "Escribe primero el link con {artista} y {titulo}. "
                                    f"Ejemplo:\n{POOL_EXAMPLE}")
            return
        QDesktopServices.openUrl(QUrl(url))

    # ---------- Spotify ----------
    def _client_id(self) -> str:
        try:
            return self.ctx.vault.get("spotify_client_id")
        except Exception:  # noqa: BLE001
            return ""

    def _client(self):
        from ...sources.spotify import SpotifyClient
        return SpotifyClient(self.ctx.vault, self._client_id())

    def refresh_spotify(self):
        if self._busy:
            return
        if not self._client_id():
            set_badge(self.sp_badge, "Falta Client ID", "off")
            self.b_sp.setText("Conectar Spotify")
            self.b_sp.setEnabled(False)
            self.b_sp.setToolTip("Agrega tu Client ID en «Fuentes y claves»")
            return
        self.b_sp.setEnabled(True)
        self.b_sp.setToolTip("")
        if self._client().is_connected():
            set_badge(self.sp_badge, "Conectado", "ok")
            self.b_sp.setText("Desconectar")
            self.b_sp.setProperty("kind", "")
        else:
            set_badge(self.sp_badge, "No conectado", "warn")
            self.b_sp.setText("Conectar Spotify")
            self.b_sp.setProperty("kind", "primary")
        self.b_sp.style().unpolish(self.b_sp)
        self.b_sp.style().polish(self.b_sp)

    def showEvent(self, event):  # noqa: N802 — refrescar si cambió la clave en otra pantalla
        super().showEvent(event)
        self.refresh_spotify()

    def _toggle_spotify(self):
        client = self._client()
        if client.is_connected():
            if QMessageBox.question(self, "Spotify", "¿Desconectar SETMAKER de tu cuenta de Spotify?") \
                    == QMessageBox.Yes:
                client.disconnect()
                self.status_msg("Spotify desconectado")
                self.refresh_spotify()
            return
        QMessageBox.information(self, "Spotify",
                                "Se abrirá tu navegador. Inicia sesión en Spotify, pulsa «Aceptar» y "
                                "vuelve a SETMAKER (tienes 3 minutos).")
        self._busy = True
        self.b_sp.setEnabled(False)
        set_badge(self.sp_badge, "Esperando al navegador…", "warn")
        run_in_background(client.connect, self._connected, self._connect_failed)

    def _connected(self, _res):
        self._busy = False
        self.status_msg("Spotify conectado ✓")
        self.refresh_spotify()

    def _connect_failed(self, msg: str):
        self._busy = False
        self.refresh_spotify()
        QMessageBox.warning(self, "Spotify", msg)


class _Progress(QObject):
    changed = Signal(int, int)


class UpdatesCard(Card):
    """Buscar, descargar e instalar versiones nuevas desde GitHub."""

    def __init__(self, ctx: AppContext, status_cb: Callable[[str], None]):
        super().__init__("Actualizaciones")
        self.ctx = ctx
        self.status_msg = status_cb
        self.info: dict | None = None
        self.body.addWidget(QLabel(f"Versión instalada: <b>{__version__}</b>"))
        self.body.addWidget(muted("SETMAKER descarga la versión nueva desde GitHub y la instala sin tocar tu "
                                  "carpeta data (eventos, ajustes y claves). Igual se recomienda crear un "
                                  "respaldo antes."))
        row = QHBoxLayout()
        self.b_check = styled_button(QPushButton("Buscar actualizaciones"), "primary")
        self.b_check.clicked.connect(self.check)
        row.addWidget(self.b_check)
        self.b_install = QPushButton("Descargar e instalar")
        self.b_install.clicked.connect(self.install)
        self.b_install.hide()
        row.addWidget(self.b_install)
        row.addStretch(1)
        self.body.addLayout(row)
        self.lbl = muted("")
        self.lbl.setTextFormat(Qt.RichText)
        self.lbl.setOpenExternalLinks(True)
        self.lbl.hide()
        self.body.addWidget(self.lbl)
        self.bar = QProgressBar()
        self.bar.hide()
        self.body.addWidget(self.bar)
        self._prog = _Progress()
        self._prog.changed.connect(self._on_progress)

    def _repo(self) -> str:
        from ...updater import DEFAULT_REPO
        return (self.ctx.config.get("updates.repo", "") or "").strip() or DEFAULT_REPO

    def check(self):
        from ...updater import check_for_update
        self.b_check.setEnabled(False)
        self.b_install.hide()
        self.lbl.setText("Buscando…")
        self.lbl.show()
        run_in_background(lambda: check_for_update(self._repo()), self._checked, self._failed)

    def _checked(self, info):
        self.b_check.setEnabled(True)
        self.info = info
        if not info:
            self.lbl.setText("Ya tienes la versión más nueva ✓")
            self.status_msg("SETMAKER está al día")
            return
        notes = (info.get("notes") or "Sin notas.").replace("&", "&amp;").replace("<", "&lt;")
        if len(notes) > 1200:
            notes = notes[:1200] + "…"
        link = f' · <a href="{info["html_url"]}">ver en GitHub</a>' if info.get("html_url") else ""
        self.lbl.setText(f"<b>Hay una versión nueva: {info['version']}</b>{link}<br>"
                         f"<span style='white-space:pre-wrap'>{notes}</span>")
        self.b_install.show()
        if not getattr(sys, "frozen", False):
            self.b_install.setEnabled(False)
            self.b_install.setToolTip("Solo disponible en la versión empaquetada (SETMAKER.exe)")
            self.lbl.setText(self.lbl.text() + "<br><i>Estás usando la versión de desarrollo: la instalación "
                             "automática solo funciona en SETMAKER.exe.</i>")
        else:
            self.b_install.setEnabled(True)

    def _failed(self, msg: str):
        self.b_check.setEnabled(True)
        self.b_install.setEnabled(True)
        self.bar.hide()
        self.lbl.setText(msg)
        self.lbl.show()
        self.status_msg("No se pudo actualizar")

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.bar.setFormat(f"{done / 1e6:.1f} de {total / 1e6:.1f} MB")
        else:
            self.bar.setRange(0, 0)

    def install(self):
        if not self.info:
            return
        if not getattr(sys, "frozen", False):
            QMessageBox.information(self, "Actualizaciones",
                                    "Solo disponible en la versión empaquetada (SETMAKER.exe).")
            return
        from ...updater import download_update
        self.b_install.setEnabled(False)
        self.b_check.setEnabled(False)
        self.bar.setValue(0)
        self.bar.show()
        self.status_msg("Descargando actualización…")
        info, prog = self.info, self._prog
        run_in_background(lambda: download_update(info, progress=lambda d, t: prog.changed.emit(d, t)),
                          self._downloaded, self._failed)

    def _downloaded(self, zip_path):
        from ...updater import UpdateError, apply_update_and_restart
        self.bar.hide()
        self.b_check.setEnabled(True)
        ok = QMessageBox.question(self, "Actualizaciones",
                                  f"Se descargó la versión {self.info['version']}.\n\n"
                                  "SETMAKER se cerrará y volverá a abrir solo en unos segundos. "
                                  "Tus datos no se tocan.\n\n¿Instalar ahora?")
        if ok != QMessageBox.Yes:
            self.b_install.setEnabled(True)
            self.status_msg("Actualización descargada; puedes instalarla después")
            return
        try:
            apply_update_and_restart(zip_path)
        except (UpdateError, OSError) as exc:
            self._failed(str(exc))
            return
        QApplication.quit()
