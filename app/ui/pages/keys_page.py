"""Fuentes y claves: guardar, probar y explicar cómo conseguir cada clave."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QWidget)

from ...context import AppContext
from ...sources import checks
from ...sources.checks import CheckResult
from ..dialogs import PasswordDialog
from ..widgets import Card, Page, badge, muted, run_in_background, set_badge, styled_button

# Instrucciones paso a paso (HTML simple). Enlaces clicables.
HOWTO = {
    "gemini_api_key": """
<b>Cómo conseguir la clave de Gemini (gratis):</b><br>
1. Abre <a href="https://aistudio.google.com/apikey">aistudio.google.com/apikey</a> e inicia sesión con tu cuenta de Google.<br>
2. Acepta los términos si te los pide.<br>
3. Pulsa <b>Create API key</b> (Crear clave de API). Si pregunta por un proyecto, elige el que ofrece por defecto.<br>
4. Copia la clave (empieza con <i>AIza…</i>), pégala aquí y pulsa <b>Guardar</b> y luego <b>Probar</b>.<br>
<i>SETMAKER solo envía títulos y artistas a Gemini para clasificarlos.</i>""",
    "lastfm_api_key": """
<b>Cómo conseguir la clave de Last.fm (gratis):</b><br>
1. Crea una cuenta en <a href="https://www.last.fm/join">last.fm/join</a> (o inicia sesión) y confirma tu correo.<br>
2. Abre <a href="https://www.last.fm/api/account/create">last.fm/api/account/create</a>.<br>
3. Rellena: <b>Application name:</b> SETMAKER · <b>Description:</b> Uso personal. Deja <b>Callback URL</b> y <b>Homepage</b> vacíos.<br>
4. Pulsa <b>Submit</b> y copia el <b>API key</b> (no el "Shared secret").""",
    "youtube_api_key": """
<b>Cómo conseguir la clave de YouTube (gratis):</b><br>
1. Abre <a href="https://console.cloud.google.com/">console.cloud.google.com</a> con tu cuenta de Google.<br>
2. Arriba, en el selector de proyecto, pulsa <b>Nuevo proyecto</b> → nombre <i>SETMAKER</i> → <b>Crear</b>.<br>
3. Con ese proyecto elegido, abre <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com">la página de YouTube Data API v3</a> y pulsa <b>Habilitar</b>.<br>
4. Ve a <b>APIs y servicios → Credenciales → Crear credenciales → Clave de API</b>.<br>
5. Copia la clave y pégala aquí. <i>Cuota gratis: 10.000 unidades al día (una búsqueda gasta 100).</i>""",
    "spotify_client_id": f"""
<b>Cómo crear tu app de Spotify (necesitas tu cuenta Premium):</b><br>
1. Abre <a href="https://developer.spotify.com/dashboard">developer.spotify.com/dashboard</a> e inicia sesión.<br>
2. Pulsa <b>Create app</b>. <b>App name:</b> SETMAKER · <b>App description:</b> Uso personal.<br>
3. En <b>Redirect URIs</b> pega exactamente: <b>{checks.SPOTIFY_REDIRECT_URI}</b> y pulsa <b>Add</b>.<br>
4. En <b>Which API/SDKs</b> marca <b>Web API</b>. Acepta los términos y pulsa <b>Save</b>.<br>
5. Entra a la app → <b>Settings</b> y copia el <b>Client ID</b>. <i>No necesitas el Client secret.</i>""",
}

DESCRIPTIONS = {
    "gemini_api_key": ("Gemini (Google)", "Clasifica cada tema según tu taxonomía de géneros, energía, edad y "
                       "contenido explícito. Es el filtro principal anti-errores."),
    "lastfm_api_key": ("Last.fm", "Tags de género por tema y artista (guaracha, rkt, dembow…). "
                       "Segunda opinión para confirmar géneros."),
    "youtube_api_key": ("YouTube", "Lo viral y lo muy nuevo. También tus playlists curadas de YouTube."),
    "spotify_client_id": ("Spotify", "Crear playlists en tu cuenta con el set o los faltantes. "
                          "Spotify ya no permite leer playlists ajenas."),
}

CHECKERS: dict[str, Callable[[str], CheckResult]] = {
    "gemini_api_key": checks.check_gemini,
    "lastfm_api_key": checks.check_lastfm,
    "youtube_api_key": checks.check_youtube,
    "spotify_client_id": checks.check_spotify_client_id,
}


class KeyCard(Card):
    def __init__(self, page: "KeysPage", name: str):
        title, desc = DESCRIPTIONS[name]
        super().__init__(title)
        self.page, self.name = page, name
        self.status = badge("")
        self.header.addWidget(self.status)
        self.body.addWidget(muted(desc))

        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("Pega aquí tu clave" if name != "spotify_client_id" else "Pega aquí tu Client ID")
        self.edit.setText(page.ctx.vault.get(name))
        self.btn_eye = QPushButton("👁")
        self.btn_eye.setFixedWidth(42)
        self.btn_eye.setToolTip("Mostrar u ocultar")
        self.btn_eye.setCheckable(True)
        self.btn_eye.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.btn_save = styled_button(QPushButton("Guardar"), "primary")
        self.btn_save.clicked.connect(self.save)
        self.btn_test = QPushButton("Probar")
        self.btn_test.clicked.connect(self.test)
        row.addWidget(self.edit, 1)
        row.addWidget(self.btn_eye)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_test)
        self.body.addLayout(row)

        self.result = muted("")
        self.result.setVisible(False)
        self.body.addWidget(self.result)

        if name == "spotify_client_id":
            r = QHBoxLayout()
            r.addWidget(muted(f"Redirect URI para tu app de Spotify:  {checks.SPOTIFY_REDIRECT_URI}", wrap=False))
            cp = QPushButton("Copiar")
            cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(checks.SPOTIFY_REDIRECT_URI),
                                        page.status_msg("Redirect URI copiado")))
            r.addWidget(cp)
            r.addStretch(1)
            self.body.addLayout(r)

        if name == "gemini_api_key":
            r = QHBoxLayout()
            r.addWidget(QLabel("Modelo:"))
            self.model = QComboBox()
            self.model.setMinimumWidth(260)
            self.model.currentTextChanged.connect(self._model_changed)
            r.addWidget(self.model)
            r.addWidget(muted("La lista se llena al pulsar «Probar» (se pregunta a Google qué modelos hay hoy).", wrap=True), 1)
            self.body.addLayout(r)
            self._fill_models()

        self.btn_help = styled_button(QPushButton("¿Cómo la consigo?  ▸"), "link")
        self.btn_help.clicked.connect(self.toggle_help)
        self.body.addWidget(self.btn_help, 0, Qt.AlignLeft)
        self.help = QLabel(HOWTO[name].replace("<a href", '<a style="color:#2fe0a0;" href'))
        self.help.setObjectName("Help")
        self.help.setWordWrap(True)
        self.help.setTextFormat(Qt.RichText)
        self.help.setOpenExternalLinks(True)
        self.help.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.help.setVisible(False)
        self.body.addWidget(self.help)
        self.refresh_status()

    # ----- Gemini: modelos
    def _fill_models(self):
        cfg = self.page.ctx.config
        models = cfg.get("gemini.available_models") or []
        current = cfg.get("gemini.model") or ""
        self.model.blockSignals(True)
        self.model.clear()
        if not models:
            self.model.addItem("(prueba la clave para ver modelos)")
            self.model.setEnabled(False)
        else:
            self.model.setEnabled(True)
            self.model.addItems(models)
            if current in models:
                self.model.setCurrentText(current)
        self.model.blockSignals(False)

    def _model_changed(self, text: str):
        if text and not text.startswith("("):
            self.page.ctx.config.set("gemini.model", text)
            self.page.status_msg(f"Modelo de Gemini: {text}")

    # ----- acciones
    def toggle_help(self):
        vis = not self.help.isVisible()
        self.help.setVisible(vis)
        self.btn_help.setText("¿Cómo la consigo?  ▾" if vis else "¿Cómo la consigo?  ▸")

    def refresh_status(self):
        if self.page.ctx.vault.get(self.name):
            set_badge(self.status, "✓ Guardada", "ok")
        else:
            set_badge(self.status, "Falta", "warn")

    def save(self):
        self.page.ctx.vault.set(self.name, self.edit.text())
        self.refresh_status()
        self.page.status_msg(f"{DESCRIPTIONS[self.name][0]}: guardado")
        self.page.changed()

    def test(self):
        value = self.edit.text().strip()
        if value != self.page.ctx.vault.get(self.name):
            self.save()
        self.btn_test.setEnabled(False)
        self.btn_test.setText("Probando…")
        checker = CHECKERS[self.name]
        run_in_background(lambda: checker(value), self._show_result,
                          lambda msg: self._show_result(CheckResult(False, f"Error inesperado: {msg}")))

    def _show_result(self, res: CheckResult):
        self.btn_test.setEnabled(True)
        self.btn_test.setText("Probar")
        color = "#2fe0a0" if res.ok else "#ff5c5c"
        self.result.setText(("✓  " if res.ok else "✗  ") + res.message)
        self.result.setStyleSheet(f"color: {color};")
        self.result.setVisible(True)
        if res.ok:
            set_badge(self.status, "✓ Funciona", "ok")
        elif self.page.ctx.vault.get(self.name):
            set_badge(self.status, "Revisar", "error")
        if self.name == "gemini_api_key" and res.ok:
            cfg = self.page.ctx.config
            cfg.set("gemini.available_models", res.extra.get("models", []))
            if not cfg.get("gemini.model") or cfg.get("gemini.model") not in res.extra.get("models", []):
                cfg.set("gemini.model", res.extra.get("default", ""))
            self._fill_models()


def parse_playlist_url(url: str) -> tuple[str, str] | None:
    """Detecta plataforma e ID de una playlist pegada. None si no se reconoce."""
    import re
    u = url.strip()
    m = re.search(r"deezer\.com/(?:[a-z]{2}/)?playlist/(\d+)", u)
    if m:
        return "deezer", m.group(1)
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", u)
    if m and ("youtube" in u or "youtu.be" in u):
        return "youtube", m.group(1)
    m = re.search(r"open\.spotify\.com/(?:intl-[a-z]+/)?playlist/([A-Za-z0-9]+)", u)
    if m:
        return "spotify", m.group(1)
    return None


class CuratedCard(Card):
    """Playlists curadas que agregas como fuente para ciertos géneros o tipos de evento."""

    def __init__(self, ctx: AppContext, status_cb):
        super().__init__("Playlists curadas (tus fuentes)")
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem
        from ...core import store
        from ...core.models import EVENT_TYPES
        self.ctx, self.status_msg = ctx, status_cb
        self._store, self._types = store, EVENT_TYPES
        self._QTI = QTableWidgetItem
        self.body.addWidget(muted(
            "Pega el link de una playlist de Deezer o YouTube que te guste (de un curador, de un pool, tuya). "
            "Sus temas entran como candidatos, pero igual pasan por la clasificación y los filtros: nunca se cuela "
            "algo que no calce. Spotify: solo funcionan playlists TUYAS (Spotify bloqueó leer playlists ajenas desde "
            "2026; copia la playlist a una tuya en la app de Spotify y pega ese link)."))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://www.deezer.com/playlist/…  o  https://www.youtube.com/playlist?list=…")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nombre (ej: Perreo pool)")
        self.name.setMaximumWidth(200)
        self.etype = QComboBox()
        self.etype.addItem("Todos los eventos", "")
        for k, v in EVENT_TYPES.items():
            self.etype.addItem(v, k)
        add = styled_button(QPushButton("Agregar"), "primary")
        add.clicked.connect(self.add_playlist)
        row.addWidget(self.url, 1)
        row.addWidget(self.name)
        row.addWidget(self.etype)
        row.addWidget(add)
        self.body.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Plataforma", "Nombre", "Para", "Link"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMaximumHeight(170)
        self.body.addWidget(self.table)
        rm = QPushButton("Quitar seleccionada")
        rm.clicked.connect(self.remove)
        self.body.addWidget(rm, 0, Qt.AlignLeft)
        self.refresh()

    def refresh(self):
        rows = self._store.list_curated(self.ctx.db)
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            for c, v in enumerate([d["platform"].capitalize(), d.get("name") or "",
                                   ", ".join(self._types.get(t, t) for t in d["event_types"]) or "Todos", d["url"]]):
                it = self._QTI(v)
                it.setData(Qt.UserRole, d["id"])
                self.table.setItem(r, c, it)

    def add_playlist(self):
        parsed = parse_playlist_url(self.url.text())
        if not parsed:
            QMessageBox.warning(self, "Playlist", "No reconocí el link. Debe ser una playlist de Deezer, YouTube o "
                                                  "Spotify (copia el link desde «Compartir»).")
            return
        platform, pid = parsed
        et = [self.etype.currentData()] if self.etype.currentData() else []
        self._store.add_curated(self.ctx.db, platform, self.url.text().strip(), pid,
                                self.name.text().strip() or f"Playlist {platform}", [], et)
        self.url.clear()
        self.name.clear()
        self.refresh()
        self.status_msg("Playlist agregada como fuente")

    def remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self._store.delete_curated(self.ctx.db, self.table.item(r, 0).data(Qt.UserRole))
            self.refresh()


class KeysPage(Page):
    def __init__(self, ctx: AppContext, status_cb: Callable[[str], None], changed_cb: Callable[[], None]):
        super().__init__("Fuentes y claves",
                         "Las claves se guardan cifradas en la carpeta data/ de SETMAKER, en tu disco. "
                         "Nunca se suben a internet ni a GitHub.")
        self.ctx = ctx
        self.status_msg = status_cb
        self.changed = changed_cb

        self.cards = {name: KeyCard(self, name) for name in DESCRIPTIONS}
        for c in self.cards.values():
            self.add(c)

        # ---------- fuentes sin clave ----------
        free = Card("Fuentes que no necesitan clave")
        free.body.addWidget(muted("Deezer: charts, búsqueda, género, ISRC y preview de 30 s. "
                                  "Apple Music: top más escuchado por país (solo como señal de tendencia)."))
        for label, fn in (("Deezer", checks.check_deezer),
                          ("Apple Music", lambda: checks.check_apple(ctx.config.get("region.country", "CL")))):
            row = QHBoxLayout()
            name = QLabel(label)
            name.setMinimumWidth(110)
            res = muted("Sin probar", wrap=True)
            btn = QPushButton("Probar")
            btn.clicked.connect(lambda _=False, f=fn, r=res, b=btn: self._test_free(f, r, b))
            row.addWidget(name)
            row.addWidget(btn)
            row.addWidget(res, 1)
            free.body.addLayout(row)
        self.add(free)

        # ---------- playlists curadas ----------
        self.add(CuratedCard(ctx, status_cb))

        # ---------- contraseña maestra ----------
        pw = Card("Contraseña maestra")
        self.pw_status = badge("")
        pw.header.addWidget(self.pw_status)
        pw.body.addWidget(muted(
            "Opcional. Sin contraseña, tus claves igual quedan cifradas, pero cualquiera que abra "
            "SETMAKER desde tu disco podría usarlas. Con contraseña, SETMAKER te la pedirá al abrir. "
            "Si la olvidas, tendrás que volver a pegar las claves (no se puede recuperar)."))
        row = QHBoxLayout()
        self.btn_pw_set = styled_button(QPushButton(), "primary")
        self.btn_pw_set.clicked.connect(self._set_password)
        self.btn_pw_off = styled_button(QPushButton("Quitar contraseña"), "danger")
        self.btn_pw_off.clicked.connect(self._remove_password)
        row.addWidget(self.btn_pw_set)
        row.addWidget(self.btn_pw_off)
        row.addStretch(1)
        pw.body.addLayout(row)
        self.add(pw)
        self._refresh_pw()
        self.finish()

    def _test_free(self, fn, res_lbl: QLabel, btn: QPushButton):
        btn.setEnabled(False)
        res_lbl.setText("Probando…")
        res_lbl.setStyleSheet("")

        def done(r: CheckResult):
            btn.setEnabled(True)
            res_lbl.setText(("✓  " if r.ok else "✗  ") + r.message)
            res_lbl.setStyleSheet(f"color: {'#2fe0a0' if r.ok else '#ff5c5c'};")

        run_in_background(fn, done, lambda m: done(CheckResult(False, m)))

    def _refresh_pw(self):
        on = self.ctx.vault.has_password
        set_badge(self.pw_status, "Activada" if on else "Desactivada", "ok" if on else "off")
        self.btn_pw_set.setText("Cambiar contraseña" if on else "Activar contraseña")
        self.btn_pw_off.setVisible(on)

    def _set_password(self):
        if self.ctx.vault.has_password and not self._ask_current():
            return
        dlg = PasswordDialog("Contraseña maestra", "Elige una contraseña para proteger tus claves.",
                             confirm=True, parent=self)
        if dlg.exec():
            self.ctx.vault.set_password(dlg.value())
            self._refresh_pw()
            self.status_msg("Contraseña maestra activada")
            self.changed()

    def _remove_password(self):
        if not self._ask_current():
            return
        self.ctx.vault.set_password(None)
        self._refresh_pw()
        self.status_msg("Contraseña maestra quitada")
        self.changed()

    def _ask_current(self) -> bool:
        dlg = PasswordDialog("Confirmar", "Escribe tu contraseña maestra actual.", parent=self)
        while dlg.exec():
            if self.ctx.vault.check_password(dlg.value()):
                return True
            dlg.show_error("Contraseña incorrecta.")
        return False

    def on_show(self) -> None:
        for c in self.cards.values():
            c.refresh_status()
