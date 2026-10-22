"""Taxonomía de géneros editable."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QInputDialog, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ...context import AppContext
from ...core import store
from ...core.models import Genre
from ...core.normalize import strip_accents
from ..profile_editor import parse_names
from ..widgets import Card, Page, muted, styled_button


class GenresPage(Page):
    def __init__(self, ctx: AppContext, status_cb):
        super().__init__("Taxonomía de géneros",
                         "Tus géneros, pensados para Chile/Latam. La IA clasifica cada tema usando SOLO esta lista; "
                         "la descripción le explica qué es cada uno.")
        self.ctx = ctx
        self.status_msg = status_cb
        self.current: str | None = None
        row = QHBoxLayout()
        row.setSpacing(16)
        left = Card("Géneros")
        self.list = QListWidget()
        self.list.setObjectName("PathList")
        self.list.setMinimumWidth(280)
        self.list.setMinimumHeight(520)
        self.list.currentItemChanged.connect(self._select)
        left.body.addWidget(self.list)
        for text, fn in (("Nuevo género", self.new), ("Eliminar", self.delete),
                         ("Restaurar géneros de fábrica", self.reset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            left.body.addWidget(b)
        row.addWidget(left, 0)

        right = Card("Detalle")
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.slug = QLineEdit()
        self.slug.setReadOnly(True)
        self.name = QLineEdit()
        self.group = QLineEdit()
        self.desc = QPlainTextEdit()
        self.desc.setMaximumHeight(90)
        self.seeds = QPlainTextEdit()
        self.seeds.setMaximumHeight(90)
        self.tags = QLineEdit()
        self.terms = QLineEdit()
        bpm = QHBoxLayout()
        self.bpm_min, self.bpm_max = QSpinBox(), QSpinBox()
        for s in (self.bpm_min, self.bpm_max):
            s.setRange(0, 220)
        bpm.addWidget(self.bpm_min)
        bpm.addWidget(muted("a", False))
        bpm.addWidget(self.bpm_max)
        bpm.addStretch(1)
        self.energy = QSpinBox()
        self.energy.setRange(1, 10)
        era = QHBoxLayout()
        self.era_from, self.era_to = QSpinBox(), QSpinBox()
        for s in (self.era_from, self.era_to):
            s.setRange(0, 2100)
            s.setSpecialValueText("—")
        era.addWidget(self.era_from)
        era.addWidget(muted("a", False))
        era.addWidget(self.era_to)
        era.addStretch(1)
        form.addRow("Código", self.slug)
        form.addRow("Nombre", self.name)
        form.addRow("Grupo", self.group)
        form.addRow("Descripción para la IA", self.desc)
        form.addRow("Artistas semilla", self.seeds)
        form.addRow("Tags de Last.fm", self.tags)
        form.addRow("Búsquedas de playlists", self.terms)
        form.addRow("BPM típico", bpm)
        form.addRow("Energía típica (1–10)", self.energy)
        form.addRow("Años típicos", era)
        right.body.addLayout(form)
        right.body.addWidget(muted("Artistas, tags y búsquedas separados por coma. Los artistas semilla se usan "
                                   "para buscar candidatos y para clasificar cuando no hay IA."))
        b = styled_button(QPushButton("Guardar género"), "primary")
        b.clicked.connect(self.save)
        right.body.addWidget(b, 0, Qt.AlignLeft)
        row.addWidget(right, 1)
        self.layout_.addLayout(row)
        self.finish()

    def refresh(self):
        self.genres = store.load_genres(self.ctx.db)
        self.list.blockSignals(True)
        self.list.clear()
        group = None
        for g in self.genres:
            if g.group != group:
                group = g.group
                h = QListWidgetItem(f"— {group or 'Sin grupo'} —")
                h.setFlags(Qt.NoItemFlags)
                h.setForeground(Qt.gray)
                self.list.addItem(h)
            it = QListWidgetItem("   " + g.name)
            it.setData(Qt.UserRole, g.slug)
            self.list.addItem(it)
        self.list.blockSignals(False)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == (self.current or (self.genres[0].slug if self.genres else None)):
                self.list.setCurrentRow(i)
                break

    def _g(self) -> Genre | None:
        return next((g for g in self.genres if g.slug == self.current), None)

    def _select(self, cur, _prev):
        if not cur or not cur.data(Qt.UserRole):
            return
        self.current = cur.data(Qt.UserRole)
        g = self._g()
        if not g:
            return
        self.slug.setText(g.slug)
        self.name.setText(g.name)
        self.group.setText(g.group)
        self.desc.setPlainText(g.description)
        self.seeds.setPlainText(", ".join(g.seed_artists))
        self.tags.setText(", ".join(g.lastfm_tags))
        self.terms.setText(", ".join(g.search_terms))
        self.bpm_min.setValue(g.bpm_min)
        self.bpm_max.setValue(g.bpm_max)
        self.energy.setValue(g.energy)
        self.era_from.setValue(g.era_from)
        self.era_to.setValue(g.era_to)

    def save(self):
        g = self._g()
        if not g:
            return
        g.name = self.name.text().strip() or g.name
        g.group = self.group.text().strip()
        g.description = self.desc.toPlainText().strip()
        g.seed_artists = parse_names(self.seeds.toPlainText())
        g.lastfm_tags = [t.lower() for t in parse_names(self.tags.text())]
        g.search_terms = parse_names(self.terms.text())
        g.bpm_min, g.bpm_max = self.bpm_min.value(), self.bpm_max.value()
        g.energy = self.energy.value()
        g.era_from, g.era_to = self.era_from.value(), self.era_to.value()
        store.save_genre(self.ctx.db, g)
        self.status_msg(f"Género guardado: {g.name}")
        self.refresh()

    def new(self):
        name, ok = QInputDialog.getText(self, "Nuevo género", "Nombre del género:")
        if not ok or not name.strip():
            return
        slug = re.sub(r"[^a-z0-9]+", "_", strip_accents(name.lower())).strip("_") or "genero"
        base = slug
        n = 2
        while any(g.slug == slug for g in self.genres):
            slug = f"{base}_{n}"
            n += 1
        store.save_genre(self.ctx.db, Genre(slug, name.strip(), "Míos", f"{name.strip()}."))
        self.current = slug
        self.refresh()

    def delete(self):
        g = self._g()
        if not g or g.slug == "otro":
            return
        if QMessageBox.question(self, "Eliminar género",
                                f"¿Eliminar «{g.name}»? Las plantillas que lo usen lo ignorarán.") == QMessageBox.Yes:
            store.delete_genre(self.ctx.db, g.slug)
            self.current = None
            self.refresh()

    def reset(self):
        if QMessageBox.question(self, "Restaurar géneros",
                                "Se perderán tus cambios en los géneros. ¿Continuar?") == QMessageBox.Yes:
            store.reset_genres(self.ctx.db)
            self.current = None
            self.refresh()

    def on_show(self):
        self.refresh()
