"""Nuevo set: asistente paso a paso."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ...context import AppContext
from ...core import store
from ...core.models import EventProfile
from ..profile_editor import ProfileEditor, profile_summary_html
from ..widgets import Card, Page, muted, styled_button

STEP_NAMES = ["Plantilla y datos", "Público", "Géneros", "Nuevos y clásicos", "Bloques", "Filtros", "Resumen"]


class NewSetPage(Page):
    generate_requested = Signal(object, object)   # (EventProfile, event_id | None)

    def __init__(self, ctx: AppContext, status_cb):
        super().__init__("Nuevo set", "Arma el perfil del evento paso a paso. Puedes partir de una plantilla.")
        self.ctx = ctx
        self.status_msg = status_cb
        self.event_id: int | None = None
        self.genres = store.load_genres(ctx.db)
        self.names = {g.slug: g.name for g in self.genres}

        # ---------- indicador de pasos
        self.stepbar = QHBoxLayout()
        self.step_labels = []
        for i, n in enumerate(STEP_NAMES):
            lbl = QLabel(f"{i + 1}. {n}")
            lbl.setObjectName("Muted")
            self.step_labels.append(lbl)
            self.stepbar.addWidget(lbl)
            if i < len(STEP_NAMES) - 1:
                sep = QLabel("›")
                sep.setObjectName("Muted")
                self.stepbar.addWidget(sep)
        self.stepbar.addStretch(1)
        self.layout_.addLayout(self.stepbar)

        # ---------- plantilla
        self.tpl_card = Card()
        row = QHBoxLayout()
        row.addWidget(QLabel("Partir desde plantilla:"))
        self.tpl = QComboBox()
        self.tpl.setMinimumWidth(320)
        row.addWidget(self.tpl)
        b = styled_button(QPushButton("Cargar plantilla"), "primary")
        b.clicked.connect(self.load_template)
        row.addWidget(b)
        row.addStretch(1)
        self.tpl_card.body.addLayout(row)
        self.add(self.tpl_card)

        # ---------- pasos
        self.editor = ProfileEditor(self.genres)
        self.stack = QStackedWidget()
        for s in self.editor.steps:
            c = Card()
            c.body.addWidget(s)
            self.stack.addWidget(c)
        self.summary_card = Card("Resumen")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary_card.body.addWidget(self.summary)
        self.summary_card.body.addWidget(muted(
            "Al generar, SETMAKER busca temas reales en Deezer, Apple Music, Last.fm y YouTube, los clasifica "
            "con IA y aplica tus filtros. La primera vez toma entre 2 y 6 minutos; después usa la caché y es mucho más rápido. Sin clave de Gemini el set sale bastante más corto."))
        self.stack.addWidget(self.summary_card)
        self.add(self.stack)

        # ---------- navegación
        nav = QHBoxLayout()
        self.btn_back = QPushButton("← Atrás")
        self.btn_back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.btn_save_tpl = QPushButton("Guardar como plantilla")
        self.btn_save_tpl.clicked.connect(self.save_as_template)
        self.btn_next = styled_button(QPushButton("Siguiente →"), "primary")
        self.btn_next.clicked.connect(self.next)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_save_tpl)
        nav.addWidget(self.btn_next)
        self.layout_.addLayout(nav)
        self.finish()
        self.reset()

    # ------------------------------------------------------------------
    def refresh_templates(self):
        self.templates = store.load_templates(self.ctx.db)
        cur = self.tpl.currentText()
        self.tpl.clear()
        for t in self.templates:
            self.tpl.addItem(t.name + ("" if t.builtin else "  (mía)"), t.id)
        i = self.tpl.findText(cur)
        if i >= 0:
            self.tpl.setCurrentIndex(i)

    def _rebuild_if_genres_changed(self):
        """Si editaste la taxonomía, rehace los pasos para que aparezcan los géneros nuevos."""
        genres = store.load_genres(self.ctx.db)
        if [(g.slug, g.name) for g in genres] == [(g.slug, g.name) for g in self.genres]:
            return
        self.genres = genres
        self.names = {g.slug: g.name for g in genres}
        while self.stack.count() > 1:   # deja solo el resumen (último)
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.editor = ProfileEditor(genres)
        for i, s in enumerate(self.editor.steps):
            c = Card()
            c.body.addWidget(s)
            self.stack.insertWidget(i, c)

    def reset(self, profile: EventProfile | None = None, event_id: int | None = None):
        """Deja el asistente listo (vacío, desde una plantilla, o editando un evento existente)."""
        self._rebuild_if_genres_changed()
        self.refresh_templates()
        self.event_id = event_id
        if profile is None:
            t = self.templates[0].profile if self.templates else EventProfile()
            profile = copy.deepcopy(t)
            profile.name = ""
        self.editor.load(profile)
        self.go(0)

    def load_template(self):
        tid = self.tpl.currentData()
        for t in self.templates:
            if t.id == tid:
                cur = self.editor.profile()
                p = copy.deepcopy(t.profile)
                # conservar nombre/fecha/lugar ya escritos
                p.name = cur.name if cur.name and cur.name != "Evento sin nombre" else ""
                p.event_date, p.venue = cur.event_date, cur.venue
                self.editor.load(p)
                self.status_msg(f"Plantilla cargada: {t.name}")
                return

    def go(self, i: int):
        i = max(0, min(i, self.stack.count() - 1))
        if i == self.stack.count() - 1:
            self.summary.setText(profile_summary_html(self.editor.profile(), self.names))
        self.stack.setCurrentIndex(i)
        self.tpl_card.setVisible(i == 0)
        self.btn_back.setEnabled(i > 0)
        last = i == self.stack.count() - 1
        self.btn_next.setText("🎛  Generar set" if last else "Siguiente →")
        self.btn_next.setProperty("kind", "big" if last else "primary")
        self.btn_next.style().unpolish(self.btn_next)
        self.btn_next.style().polish(self.btn_next)
        for k, lbl in enumerate(self.step_labels):
            lbl.setStyleSheet("color: #2fe0a0; font-weight: 700;" if k == i else
                              ("color: #e8ebf2;" if k < i else ""))
        self.verticalScrollBar().setValue(0)

    def next(self):
        i = self.stack.currentIndex()
        p = self.editor.profile()
        if i == 2 and not p.allowed_genres():
            self.status_msg("Elige al menos un género con porcentaje mayor a 0")
            return
        if i == 4 and not p.blocks:
            self.status_msg("Agrega al menos un bloque")
            return
        if i == self.stack.count() - 1:
            self.generate_requested.emit(p, self.event_id)
            return
        self.go(i + 1)

    def save_as_template(self):
        p = self.editor.profile()
        name, ok = QInputDialog.getText(self, "Guardar plantilla", "Nombre de la plantilla:",
                                        text=p.name or "Mi plantilla")
        if ok and name.strip():
            tp = copy.deepcopy(p)
            tp.event_date, tp.venue = "", ""
            store.save_template(self.ctx.db, name.strip(), tp)
            self.refresh_templates()
            self.status_msg(f"Plantilla guardada: {name.strip()}")

    def on_show(self):
        before = self.editor
        self._rebuild_if_genres_changed()
        if self.editor is not before:
            self.reset(None, None)
        self.refresh_templates()
