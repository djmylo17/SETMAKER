"""Inicio: estado general y mis eventos."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ... import __version__
from ...context import AppContext
from ...core import store
from ...core.models import EVENT_TYPES
from ...security.vault import SERVICES
from ..widgets import Card, Page, muted, styled_button


class StatCard(QFrame):
    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")
        self.hint = muted("")
        lay.addWidget(self.value)
        lay.addWidget(self.label)
        lay.addWidget(self.hint)

    def set(self, value: str, hint: str = "", color: str | None = None):
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color};" if color else "")
        self.hint.setText(hint)


class HomePage(Page):
    go_to = Signal(str)  # nombre de página destino
    open_event = Signal(int)

    def _open_row(self, row: int):
        if 0 <= row < len(self._event_ids):
            self.open_event.emit(self._event_ids[row])

    def _delete(self, event_id: int, name: str):
        if QMessageBox.question(self, "Eliminar evento", f"¿Eliminar «{name}» y su set?") == QMessageBox.Yes:
            store.delete_event(self.ctx.db, event_id)
            self.on_show()

    def __init__(self, ctx: AppContext):
        super().__init__("Inicio")
        self.ctx = ctx

        # ---------- portada ----------
        hero = QFrame()
        hero.setObjectName("Hero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(28, 26, 28, 26)
        txt = QVBoxLayout()
        t = QLabel("Arma el set perfecto antes del evento")
        t.setStyleSheet("font-size: 17pt; font-weight: 700; background: transparent;")
        s = QLabel("Tendencias reales, filtradas por tipo de fiesta y edad del público. "
                   "Te dice qué temas ya tienes y cuáles te faltan.")
        s.setWordWrap(True)
        s.setStyleSheet("color: #b9c1d1; background: transparent;")
        txt.addWidget(t)
        txt.addWidget(s)
        hl.addLayout(txt, 1)
        self.btn_new = styled_button(QPushButton("＋  Nuevo set"), "big")
        self.btn_new.clicked.connect(lambda: self.go_to.emit("nuevo"))
        hl.addWidget(self.btn_new, 0, Qt.AlignVCenter)
        self.add(hero)

        # ---------- estado ----------
        grid = QGridLayout()
        grid.setSpacing(14)
        self.st_keys = StatCard("Claves de API")
        self.st_lib = StatCard("Biblioteca VirtualDJ")
        self.st_events = StatCard("Sets preparados")
        self.st_ver = StatCard("Versión")
        for i, w in enumerate((self.st_keys, self.st_lib, self.st_events, self.st_ver)):
            grid.addWidget(w, 0, i)
        self.layout_.addLayout(grid)

        # ---------- mis eventos ----------
        self.events_card = Card("Mis eventos")
        self.events_empty = muted("Todavía no tienes sets preparados. Crea el primero con «Nuevo set».")
        self.events_card.body.addWidget(self.events_empty)
        self.events = QTableWidget(0, 5)
        self.events.setHorizontalHeaderLabels(["Fecha", "Evento", "Tipo", "Temas", ""])
        self.events.verticalHeader().setVisible(False)
        self.events.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.events.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.events.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.events.setStyleSheet("QTableWidget{background:transparent;border:none;}"
                                  "QHeaderView::section{background:transparent;color:#8a93a6;border:none;padding:4px;}")
        self.events.doubleClicked.connect(lambda idx: self._open_row(idx.row()))
        self.events_card.body.addWidget(self.events)
        self.add(self.events_card)

        # ---------- próximos pasos ----------
        steps = Card("Para dejar SETMAKER listo")
        self.lbl_steps = QLabel()
        self.lbl_steps.setWordWrap(True)
        self.lbl_steps.setTextFormat(Qt.RichText)
        steps.body.addWidget(self.lbl_steps)
        row = QHBoxLayout()
        b1 = styled_button(QPushButton("Ir a Fuentes y claves"), "primary")
        b1.clicked.connect(lambda: self.go_to.emit("claves"))
        b2 = QPushButton("Ir a Ajustes")
        b2.clicked.connect(lambda: self.go_to.emit("ajustes"))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        steps.body.addLayout(row)
        self.add(steps)
        self.finish()
        self.on_show()

    def on_show(self) -> None:
        from ..theme import C
        n = len(self.ctx.vault.configured())
        total = len(SERVICES)
        self.st_keys.set(f"{n} de {total}", "Listas para usar" if n == total else "Faltan claves",
                         C["accent"] if n == total else C["warn"])

        vdj = self.ctx.config.get("virtualdj.database_xml")
        if vdj:
            self.st_lib.set("Configurada", vdj.split("\\")[-2] if "\\" in vdj else "database.xml", C["accent"])
        else:
            self.st_lib.set("Sin ruta", "Configúrala en Ajustes", C["warn"])

        events = store.list_events(self.ctx.db)
        count = len(events)
        self.st_events.set(str(count), "en tu historial")
        self.events_empty.setVisible(count == 0)
        self.events.setVisible(count > 0)
        self._event_ids = [e.id for e in events]
        self.events.setRowCount(count)
        for r, e in enumerate(events):
            date = "-".join(reversed(e.event_date.split("-"))) if e.event_date else "—"
            vals = [date, e.name, EVENT_TYPES.get(e.event_type, e.event_type),
                    str(e.track_count) if e.set_id else "sin generar"]
            for c, v in enumerate(vals):
                self.events.setItem(r, c, QTableWidgetItem(v))
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(4, 2, 4, 2)
            b_open = styled_button(QPushButton("Abrir"), "primary")
            b_open.clicked.connect(lambda _=False, i=e.id: self.open_event.emit(i))
            b_del = QPushButton("Eliminar")
            b_del.clicked.connect(lambda _=False, i=e.id, n=e.name: self._delete(i, n))
            bl.addWidget(b_open)
            bl.addWidget(b_del)
            self.events.setCellWidget(r, 4, box)
            self.events.setRowHeight(r, 44)
        self.events.setMinimumHeight(min(420, 40 + 46 * count))

        self.st_ver.set(__version__, "Lista para usar")

        todo = []
        if n < total:
            todo.append(f"Agregar las claves de API que faltan ({total - n}).")
        if not vdj:
            todo.append("Indicar dónde está tu <b>database.xml</b> de VirtualDJ.")
        if not self.ctx.vault.has_password:
            todo.append("Opcional: proteger tus claves con una contraseña maestra.")
        self.lbl_steps.setText("<br>".join(f"•&nbsp; {t}" for t in todo) if todo
                               else "Todo listo. ✓")
