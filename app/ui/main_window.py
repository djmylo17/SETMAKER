"""Ventana principal: barra lateral + pantallas + flujo de generación."""
from __future__ import annotations

import copy
import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..context import AppContext
from ..core import store
from ..core.models import EventProfile
from .pages.genres_page import GenresPage
from .pages.home import HomePage
from .pages.keys_page import KeysPage
from .pages.library_page import LibraryPage
from .pages.missing_page import MissingPage
from .pages.new_set_page import NewSetPage
from .pages.result_page import ResultPage
from .pages.settings_page import SettingsPage
from .pages.templates_page import TemplatesPage

log = logging.getLogger(__name__)

# (clave, ícono, texto)
NAV = [
    ("inicio", "⌂", "Inicio"),
    ("nuevo", "＋", "Nuevo set"),
    ("set", "♪", "Set actual"),
    ("faltantes", "↓", "Faltantes"),
    ("biblioteca", "♫", "Biblioteca"),
    ("plantillas", "▤", "Plantillas"),
    ("generos", "◈", "Géneros"),
    ("claves", "⚿", "Fuentes y claves"),
    ("ajustes", "⚙", "Ajustes"),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        store.ensure_seed(ctx.db)
        self.setWindowTitle(f"{APP_NAME} · Level Up Producciones")
        self.resize(1360, 860)
        self.setMinimumSize(1040, 680)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- barra lateral ----------
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 22, 0, 14)
        sl.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        brand.setContentsMargins(22, 0, 0, 0)
        sub = QLabel("LEVEL UP PRODUCCIONES")
        sub.setObjectName("BrandSub")
        sub.setContentsMargins(23, 0, 0, 18)
        sl.addWidget(brand)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(0, 0))
        self.nav.setFocusPolicy(Qt.NoFocus)
        for key, icon, text in NAV:
            item = QListWidgetItem(f"{icon}    {text}")
            item.setData(Qt.UserRole, key)
            self.nav.addItem(item)
        sl.addWidget(self.nav, 1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("Version")
        ver.setContentsMargins(22, 0, 0, 0)
        sl.addWidget(ver)
        lay.addWidget(side)

        # ---------- pantallas ----------
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setStatusBar(QStatusBar())

        self.home = HomePage(ctx)
        self.home.go_to.connect(self.go)
        self.home.open_event.connect(self.open_event)
        self.new_set = NewSetPage(ctx, self.flash)
        self.new_set.generate_requested.connect(self.generate)
        self.result = ResultPage(ctx, self.flash)
        self.result.go_to.connect(self._result_nav)
        self.result.changed.connect(self._set_changed)
        self.missing = MissingPage(ctx, self.flash)
        self.templates = TemplatesPage(ctx, self.flash)
        self.templates.use_template.connect(self._use_template)
        self.pages = {
            "inicio": self.home,
            "nuevo": self.new_set,
            "set": self.result,
            "faltantes": self.missing,
            "biblioteca": LibraryPage(ctx, self.flash),
            "plantillas": self.templates,
            "generos": GenresPage(ctx, self.flash),
            "claves": KeysPage(ctx, self.flash, self.refresh_home),
            "ajustes": SettingsPage(ctx, self.flash, self.refresh_home),
        }
        for key, *_ in NAV:
            self.stack.addWidget(self.pages[key])
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

    # ------------------------------------------------------------ navegación
    def _on_nav(self, row: int):
        key = NAV[row][0]
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if hasattr(page, "on_show"):
            page.on_show()

    def go(self, key: str):
        for i, (k, *_r) in enumerate(NAV):
            if k == key:
                if self.nav.currentRow() == i:
                    self._on_nav(i)
                self.nav.setCurrentRow(i)
                return

    def flash(self, msg: str):
        self.statusBar().showMessage(msg, 5000)

    def refresh_home(self):
        self.home.on_show()

    def _use_template(self, profile: EventProfile):
        self.new_set.reset(profile)
        self.go("nuevo")

    def _result_nav(self, key: str):
        if key == "editar" and self.result.profile:
            self.new_set.reset(copy.deepcopy(self.result.profile), self.result.event_id)
            self.new_set.go(1)
            self.go("nuevo")
        elif key == "regenerar" and self.result.profile:
            if QMessageBox.question(self, "Regenerar set", "Se armará un set nuevo con el mismo perfil "
                                    "(lo aprendido se respeta). ¿Continuar?") == QMessageBox.Yes:
                self.generate(copy.deepcopy(self.result.profile), self.result.event_id)
        else:
            self.go(key)

    def _set_changed(self):
        self.missing.set_set(self.result.profile, self.result.items, self.result.names)
        self.home.on_show()

    # ------------------------------------------------------------ eventos
    def open_event(self, event_id: int):
        e = store.get_event(self.ctx.db, event_id)
        if not e:
            return
        if not e.set_id:
            self.new_set.reset(e.profile, e.id)
            self.go("nuevo")
            return
        items, summary, discarded = store.load_set(self.ctx.db, e.set_id)
        self.result.load(e.id, e.set_id, e.profile, items, summary, discarded)
        self.missing.set_set(e.profile, items, self.result.names)
        self.go("set")

    # ------------------------------------------------------------ generación
    def generate(self, profile: EventProfile, event_id: int | None):
        from ..ai.gemini import GeminiClassifier
        from ..engine.hub import SourceHub
        from ..engine.pipeline import SetGenerator
        from ..sources.checks import check_gemini
        from .generate_dialog import GenerateDialog

        ctx = self.ctx
        genres = store.load_genres(ctx.db)
        gemini_key = ctx.vault.get("gemini_api_key")
        spotify = None
        if ctx.vault.get("spotify_client_id") and any(p["platform"] == "spotify"
                                                       for p in store.list_curated(ctx.db, enabled_only=True)):
            try:
                from ..sources.spotify import SpotifyClient
                sc = SpotifyClient(ctx.vault, ctx.vault.get("spotify_client_id"))
                spotify = sc if sc.is_connected() else None
            except Exception:  # noqa: BLE001
                spotify = None
        hub = SourceHub(ctx.db, ctx.vault.get("lastfm_api_key"), ctx.vault.get("youtube_api_key"), spotify)
        rules = store.learned_rules(ctx.db, profile.event_type)
        lib_rows = ctx.db.scalar("SELECT COUNT(*) FROM library_tracks") or 0
        ignore_k = bool(ctx.config.get("library.ignore_karaoke"))

        def run(progress, cancel):
            classifier = None
            if gemini_key:
                model = ctx.config.get("gemini.model") or ""
                if not model:
                    progress("Eligiendo modelo de Gemini", 0.01)
                    chk = check_gemini(gemini_key)
                    if chk.ok:
                        model = chk.extra.get("default", "")
                        ctx.config.set("gemini.available_models", chk.extra.get("models", []))
                        ctx.config.set("gemini.model", model)
                if model:
                    classifier = GeminiClassifier(ctx.db, gemini_key, model, genres)
            gen = SetGenerator(genres, hub, classifier, rules)
            res = gen.generate(profile, progress, cancel)
            if lib_rows and res.items:
                progress("Revisando qué temas ya tienes", 0.99)
                from ..library.matcher import LibraryMatcher, match_items
                m = LibraryMatcher(ctx.db, ignore_karaoke=ignore_k)
                match_items(ctx.db, res.items, ignore_karaoke=ignore_k, matcher=m)
                match_items(ctx.db, res.pool[:300], ignore_karaoke=ignore_k, matcher=m)
            return res

        dlg = GenerateDialog(run, self)
        dlg.exec()
        hub.close()
        if dlg.error == "cancelado":
            self.flash("Generación cancelada")
            return
        if dlg.error:
            QMessageBox.warning(self, "No se pudo generar", f"Ocurrió un problema:\n{dlg.error}\n\n"
                                "Revisa tu conexión a internet y vuelve a intentar.")
            return
        res = dlg.result
        if not res or not res.items:
            msg = "\n".join(res.warnings) if res else ""
            QMessageBox.information(self, "Set vacío", "Ningún tema pasó los filtros del evento.\n\n" + msg +
                                    "\n\nPrueba agregando géneros, ampliando los años de clásicos o revisando tus claves.")
            return
        event_id = store.save_event(ctx.db, profile, event_id)
        summary = dict(res.summary)
        summary["pool"] = [it.to_dict() for it in res.pool[:300]]
        summary["warnings"] = res.warnings
        set_id = store.save_set(ctx.db, event_id, res.items, summary, res.discarded)
        self.result.load(event_id, set_id, profile, res.items, summary, res.discarded, res.pool, res.warnings)
        self.missing.set_set(profile, res.items, self.result.names)
        self.home.on_show()
        self.go("set")
        self.flash(f"Set listo: {len(res.items)} temas")
