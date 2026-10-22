"""Ventana principal: barra lateral + pantallas."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..context import AppContext
from .pages.home import HomePage
from .pages.keys_page import KeysPage
from .pages.placeholder import PlaceholderPage
from .pages.settings_page import SettingsPage

# (clave, ícono, texto)
NAV = [
    ("inicio", "⌂", "Inicio"),
    ("nuevo", "＋", "Nuevo set"),
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
        self.setWindowTitle(f"{APP_NAME} · Level Up Producciones")
        self.resize(1280, 820)
        self.setMinimumSize(980, 640)

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
        self.pages = {
            "inicio": self.home,
            "nuevo": PlaceholderPage(
                "Nuevo set", "Asistente paso a paso para crear el perfil del evento.", 2,
                ["Tipo de evento, edad del público y país.",
                 "Géneros permitidos con porcentaje y géneros vetados (nunca entran).",
                 "Temas nuevos vs. clásicos, bloques horarios con energía objetivo.",
                 "Filtro de letras explícitas (obligatorio en eventos infantiles).",
                 "Partir desde una plantilla."]),
            "faltantes": PlaceholderPage(
                "Faltantes", "Lo que te falta para el set, listo para conseguir.", 5,
                ["Botones de búsqueda en YouTube, Spotify, Beatport y tu pool DJ.",
                 "Exportar a Excel, CSV, TXT y playlist de Spotify."]),
            "biblioteca": PlaceholderPage(
                "Biblioteca", "Qué temas tienes en VirtualDJ y en tus carpetas.", 4,
                ["Lectura de database.xml de VirtualDJ (BPM, key, género).",
                 "Escaneo de carpetas con formato y calidad (WAV, FLAC, MP3 320…).",
                 "«La tengo», «Tengo otra versión» o «Me falta», con corrección manual.",
                 "Exportación de crates .vdjfolder."]),
            "plantillas": PlaceholderPage(
                "Plantillas de evento", "Perfiles prearmados por tipo de fiesta.", 2,
                ["Plantillas de fábrica: Carrete juvenil urbano, Cumpleaños infantil, Matrimonio, 15 años…",
                 "Crear, editar y duplicar las tuyas."]),
            "generos": PlaceholderPage(
                "Taxonomía de géneros", "Tus géneros, pensados para Chile/Latam y para DJ.", 2,
                ["Reggaetón por época, urbano chileno, guaracha, RKT, cumbias, dembow…",
                 "Descripción para la IA, artistas semilla, BPM y energía típicos.",
                 "Rock, baladas y trova incluidos para poder vetarlos."]),
            "claves": KeysPage(ctx, self.flash, self.refresh_home),
            "ajustes": SettingsPage(ctx, self.flash, self.refresh_home),
        }
        for key, *_ in NAV:
            self.stack.addWidget(self.pages[key])

        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

    def _on_nav(self, row: int):
        key = NAV[row][0]
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        page.on_show()

    def go(self, key: str):
        for i, (k, *_r) in enumerate(NAV):
            if k == key:
                self.nav.setCurrentRow(i)
                return

    def flash(self, msg: str):
        self.statusBar().showMessage(msg, 4000)

    def refresh_home(self):
        self.home.on_show()
