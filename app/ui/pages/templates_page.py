"""Plantillas de evento + lo aprendido con tu feedback."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...context import AppContext
from ...core import store
from ...core.models import EVENT_TYPES
from ..profile_editor import ProfileEditor
from ..widgets import Card, Page, muted, styled_button

KIND_LABELS = {"like": "👍 Me gustó", "dislike": "👎 No me gustó", "ban_artist": "⛔ Artista vetado",
               "ban_track": "⛔ Tema vetado"}


class TemplatesPage(Page):
    use_template = Signal(object)   # EventProfile

    def __init__(self, ctx: AppContext, status_cb):
        super().__init__("Plantillas y aprendizaje",
                         "Perfiles prearmados por tipo de fiesta, y todo lo que SETMAKER aprendió de tus 👍/👎 y vetos.")
        self.ctx = ctx
        self.status_msg = status_cb
        self.current_id: int | None = None
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane{border:none;} QTabBar::tab{padding:8px 18px; background:#171b24;"
                           "border:1px solid #262c3a; border-bottom:none; border-top-left-radius:8px;"
                           "border-top-right-radius:8px; margin-right:4px; color:#8a93a6;}"
                           "QTabBar::tab:selected{color:#2fe0a0; background:#1e2330;}")
        tabs.addTab(self._build_templates(), "Plantillas")
        tabs.addTab(self._build_learned(), "Lo aprendido")
        self.add(tabs)
        self.finish()

    # =========================================================== plantillas
    def _build_templates(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(16)
        left = Card("Tus plantillas")
        self.list = QListWidget()
        self.list.setObjectName("PathList")
        self.list.setMinimumWidth(260)
        self.list.currentItemChanged.connect(self._select)
        left.body.addWidget(self.list)
        for text, fn in (("Nueva", self.new), ("Duplicar", self.duplicate), ("Eliminar", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            left.body.addWidget(b)
        lay.addWidget(left, 0)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        genres = store.load_genres(self.ctx.db)
        self.editor = ProfileEditor(genres)
        for s in self.editor.steps[1:]:   # sin "datos del evento" salvo el tipo
            c = Card()
            c.body.addWidget(s)
            rl.addWidget(c)
        top = Card()
        r = QHBoxLayout()
        r.addWidget(QLabel("Tipo de evento:"))
        self.etype = QComboBox()
        for k, v in EVENT_TYPES.items():
            self.etype.addItem(v, k)
        r.addWidget(self.etype)
        r.addStretch(1)
        b_save = styled_button(QPushButton("Guardar cambios"), "primary")
        b_save.clicked.connect(self.save)
        b_use = QPushButton("Usar para un nuevo set →")
        b_use.clicked.connect(self._use)
        r.addWidget(b_save)
        r.addWidget(b_use)
        top.body.addLayout(r)
        rl.insertWidget(0, top)
        lay.addWidget(right, 1)
        return w

    def refresh(self):
        self.templates = store.load_templates(self.ctx.db)
        keep = self.current_id
        self.list.blockSignals(True)
        self.list.clear()
        for t in self.templates:
            it = QListWidgetItem(("★ " if t.builtin else "• ") + t.name)
            it.setData(Qt.UserRole, t.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        idx = next((i for i, t in enumerate(self.templates) if t.id == keep), 0)
        if self.templates:
            self.list.setCurrentRow(idx)

    def _row(self):
        return next((t for t in self.templates if t.id == self.current_id), None)

    def _select(self, cur, _prev):
        if not cur:
            return
        self.current_id = cur.data(Qt.UserRole)
        t = self._row()
        if t:
            self.editor.load(copy.deepcopy(t.profile))
            self.etype.setCurrentIndex(max(self.etype.findData(t.profile.event_type), 0))

    def _collect(self):
        p = self.editor.profile()
        p.event_type = self.etype.currentData()
        p.event_date, p.venue = "", ""
        return p.enforce_rules()

    def save(self):
        t = self._row()
        if not t:
            return
        store.save_template(self.ctx.db, t.name, self._collect(), t.id)
        self.status_msg(f"Plantilla guardada: {t.name}")
        self.refresh()

    def new(self):
        name, ok = QInputDialog.getText(self, "Nueva plantilla", "Nombre:")
        if ok and name.strip():
            base = self.templates[0].profile if self.templates else None
            from ...core.models import EventProfile
            p = copy.deepcopy(base) if base else EventProfile()
            p.name = name.strip()
            self.current_id = store.save_template(self.ctx.db, name.strip(), p)
            self.refresh()

    def duplicate(self):
        t = self._row()
        if not t:
            return
        name, ok = QInputDialog.getText(self, "Duplicar plantilla", "Nombre de la copia:", text=f"{t.name} (copia)")
        if ok and name.strip():
            self.current_id = store.save_template(self.ctx.db, name.strip(), self._collect())
            self.refresh()

    def delete(self):
        t = self._row()
        if not t:
            return
        if QMessageBox.question(self, "Eliminar plantilla", f"¿Eliminar «{t.name}»?") == QMessageBox.Yes:
            store.delete_template(self.ctx.db, t.id)
            self.current_id = None
            self.refresh()

    def _use(self):
        p = self._collect()
        p.name = ""
        self.use_template.emit(p)

    # =========================================================== aprendizaje
    def _build_learned(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        card = Card("Lo que SETMAKER aprendió")
        card.body.addWidget(muted("Cada 👍, 👎 y veto se guarda por tipo de evento: si vetaste un artista en "
                                  "«Carrete juvenil», no vuelve ahí, pero sí podría salir en un matrimonio. "
                                  "Selecciona filas y pulsa «Deshacer» para olvidarlas."))
        r = QHBoxLayout()
        r.addWidget(QLabel("Tipo de evento:"))
        self.l_type = QComboBox()
        self.l_type.addItem("Todos", "")
        for k, v in EVENT_TYPES.items():
            self.l_type.addItem(v, k)
        self.l_type.currentIndexChanged.connect(self.refresh_learned)
        r.addWidget(self.l_type)
        r.addStretch(1)
        b = QPushButton("Deshacer seleccionados")
        b.clicked.connect(self.undo)
        r.addWidget(b)
        card.body.addLayout(r)
        self.l_table = QTableWidget(0, 4)
        self.l_table.setHorizontalHeaderLabels(["Tipo de evento", "Qué", "Tema / artista", "Fecha"])
        self.l_table.verticalHeader().setVisible(False)
        self.l_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.l_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.l_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.l_table.setMinimumHeight(380)
        card.body.addWidget(self.l_table)
        lay.addWidget(card)
        return w

    def refresh_learned(self):
        rows = store.list_feedback(self.ctx.db, self.l_type.currentData() or None)
        self.l_table.setRowCount(len(rows))
        for i, f in enumerate(rows):
            vals = [EVENT_TYPES.get(f["event_type"], f["event_type"]), KIND_LABELS.get(f["kind"], f["kind"]),
                    f["label"] or f["artist"] or f["track_key"], f["created_at"][:16]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, f["id"])
                self.l_table.setItem(i, c, it)

    def undo(self):
        ids = {self.l_table.item(r.row(), 0).data(Qt.UserRole) for r in self.l_table.selectionModel().selectedRows()}
        for fid in ids:
            store.delete_feedback(self.ctx.db, fid)
        if ids:
            self.status_msg(f"Se olvidaron {len(ids)} registros")
        self.refresh_learned()

    def on_show(self):
        self.refresh()
        self.refresh_learned()
