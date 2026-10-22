"""Editor del perfil de evento, dividido en pasos (lo usan el asistente y las plantillas)."""
from __future__ import annotations

import copy
import re

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..config import COUNTRIES
from ..core.models import EVENT_TYPES, Block, EventProfile, Genre
from .widgets import muted, styled_button


def _section(title: str, help_text: str = "") -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("CardTitle")
    lay.addWidget(t)
    if help_text:
        lay.addWidget(muted(help_text))
    return w, lay


def parse_names(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n;]", text or "") if x.strip()]


# ======================================================================= pasos
class StepBasics(QWidget):
    def __init__(self):
        super().__init__()
        w, lay = _section("Datos del evento", "Nombre, fecha, lugar y tipo de fiesta.")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ej: Cumpleaños de Sofía")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd-MM-yyyy")
        self.date.setDate(QDate.currentDate())
        self.no_date = QCheckBox("Sin fecha")
        drow = QHBoxLayout()
        drow.addWidget(self.date)
        drow.addWidget(self.no_date)
        drow.addStretch(1)
        self.venue = QLineEdit()
        self.venue.setPlaceholderText("Ej: Aguas del Monte")
        self.etype = QComboBox()
        for k, v in EVENT_TYPES.items():
            self.etype.addItem(v, k)
        form.addRow("Nombre", self.name)
        form.addRow("Fecha", drow)
        form.addRow("Lugar", self.venue)
        form.addRow("Tipo de evento", self.etype)
        lay.addLayout(form)
        lay.addStretch(1)

    def load(self, p: EventProfile):
        self.name.setText(p.name)
        if p.event_date:
            d = QDate.fromString(p.event_date, "yyyy-MM-dd")
            self.date.setDate(d if d.isValid() else QDate.currentDate())
            self.no_date.setChecked(False)
        else:
            self.no_date.setChecked(False)
        i = self.etype.findData(p.event_type)
        self.etype.setCurrentIndex(max(i, 0))
        self.venue.setText(p.venue)

    def apply(self, p: EventProfile):
        p.name = self.name.text().strip() or "Evento sin nombre"
        p.event_date = "" if self.no_date.isChecked() else self.date.date().toString("yyyy-MM-dd")
        p.venue = self.venue.text().strip()
        p.event_type = self.etype.currentData()


class StepAudience(QWidget):
    def __init__(self):
        super().__init__()
        w, lay = _section("Público", "Edad del público y países que mandan en las tendencias (Chile primero).")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Edad desde"))
        self.age_min = QSpinBox()
        self.age_min.setRange(0, 99)
        row.addWidget(self.age_min)
        row.addWidget(QLabel("hasta"))
        self.age_max = QSpinBox()
        self.age_max.setRange(0, 99)
        row.addWidget(self.age_max)
        row.addStretch(1)
        lay.addLayout(row)
        self.kids_note = muted("")
        lay.addWidget(self.kids_note)
        self.age_min.valueChanged.connect(self._note)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("País principal"))
        self.country = QComboBox()
        for c, n in COUNTRIES.items():
            self.country.addItem(n, c)
        r2.addWidget(self.country)
        r2.addStretch(1)
        lay.addLayout(r2)
        lay.addWidget(muted("Países que también influyen (marca y ordena arrastrando):"))
        self.countries = QListWidget()
        self.countries.setObjectName("PathList")
        self.countries.setDragDropMode(QAbstractItemView.InternalMove)
        self.countries.setMaximumHeight(230)
        lay.addWidget(self.countries)
        lay.addStretch(1)

    def _note(self):
        if self.age_min.value() < 14:
            self.kids_note.setText("Público menor de 14: el filtro de letras explícitas queda activado sí o sí.")
        else:
            self.kid_note_clear()

    def kid_note_clear(self):
        self.kids_note.setText("")

    def load(self, p: EventProfile):
        self.age_min.setValue(p.age_min)
        self.age_max.setValue(p.age_max)
        self.country.setCurrentIndex(max(self.country.findData(p.country), 0))
        self.countries.clear()
        order = list(dict.fromkeys(p.countries + [c for c in COUNTRIES if c not in p.countries]))
        for c in order:
            it = QListWidgetItem(COUNTRIES.get(c, c))
            it.setData(Qt.UserRole, c)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if c in p.countries else Qt.Unchecked)
            self.countries.addItem(it)
        self._note()

    def apply(self, p: EventProfile):
        p.age_min, p.age_max = self.age_min.value(), max(self.age_min.value(), self.age_max.value())
        p.country = self.country.currentData()
        p.countries = [self.countries.item(i).data(Qt.UserRole) for i in range(self.countries.count())
                       if self.countries.item(i).checkState() == Qt.Checked]


class StepGenres(QWidget):
    changed = Signal()

    def __init__(self, genres: list[Genre]):
        super().__init__()
        self.genres = genres
        w, lay = _section("Géneros", "Pon un % a los géneros que quieres. Marca «Vetado» en los que NUNCA "
                                     "deben entrar (filtro duro). Los que quedan en 0 % y sin vetar tampoco entran.")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w)
        self.table = QTableWidget(len(genres), 4)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setHorizontalHeaderLabels(["Género", "Grupo", "%", "Vetado"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 80)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(420)
        self.spins: dict[str, QSpinBox] = {}
        self.bans: dict[str, QCheckBox] = {}
        for r, g in enumerate(genres):
            it = QTableWidgetItem(g.name)
            it.setToolTip(g.description)
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            gi = QTableWidgetItem(g.group)
            gi.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 1, gi)
            sp = QSpinBox()
            sp.setRange(0, 100)
            sp.setSuffix(" %")
            sp.valueChanged.connect(self._update_total)
            self.table.setCellWidget(r, 2, sp)
            cb = QCheckBox()
            cb.toggled.connect(lambda on, s=sp: (s.setValue(0) if on else None, s.setEnabled(not on)))
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(18, 0, 0, 0)
            bl.addWidget(cb)
            self.table.setCellWidget(r, 3, box)
            self.spins[g.slug], self.bans[g.slug] = sp, cb
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.total = QLabel()
        row.addWidget(self.total)
        row.addStretch(1)
        b = QPushButton("Ajustar a 100 %")
        b.clicked.connect(self.normalize)
        row.addWidget(b)
        lay.addLayout(row)

    def _update_total(self):
        t = sum(s.value() for s in self.spins.values())
        color = "#2fe0a0" if t == 100 else "#ffb547"
        self.total.setText(f"<span style='color:{color}'>Total: {t} %</span>"
                           + ("" if t == 100 else "  (se ajusta solo al generar)"))
        self.changed.emit()

    def normalize(self):
        vals = {k: s.value() for k, s in self.spins.items() if s.value() > 0}
        tot = sum(vals.values())
        if not tot:
            return
        acc = 0
        keys = list(vals)
        for i, k in enumerate(keys):
            v = 100 - acc if i == len(keys) - 1 else round(vals[k] * 100 / tot)
            acc += v
            self.spins[k].setValue(max(0, v))

    def load(self, p: EventProfile):
        for slug, sp in self.spins.items():
            self.bans[slug].setChecked(slug in p.banned_genres)
            sp.setValue(0 if slug in p.banned_genres else p.genre_weights.get(slug, 0))
        self._update_total()

    def apply(self, p: EventProfile):
        p.genre_weights = {k: s.value() for k, s in self.spins.items() if s.value() > 0}
        p.banned_genres = [k for k, c in self.bans.items() if c.isChecked()]


class StepNewClassic(QWidget):
    def __init__(self):
        super().__init__()
        w, lay = _section("Nuevos vs. clásicos", "Cuántos temas recientes quieres y qué años cuentan como clásicos.")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setSingleStep(5)
        self.lbl = QLabel()
        self.lbl.setMinimumWidth(240)
        self.slider.valueChanged.connect(lambda v: self.lbl.setText(f"<b>{v} %</b> nuevos · {100 - v} % clásicos"))
        row.addWidget(self.slider, 1)
        row.addWidget(self.lbl)
        lay.addLayout(row)
        form = QFormLayout()
        self.months = QSpinBox()
        self.months.setRange(1, 60)
        self.months.setSuffix(" meses")
        form.addRow("«Nuevo» = lanzado en los últimos", self.months)
        yr = QHBoxLayout()
        self.ymin = QSpinBox()
        self.ymin.setRange(1950, 2100)
        self.ymax = QSpinBox()
        self.ymax.setRange(1950, 2100)
        yr.addWidget(self.ymin)
        yr.addWidget(QLabel("a"))
        yr.addWidget(self.ymax)
        yr.addStretch(1)
        form.addRow("Clásicos permitidos de", yr)
        lay.addLayout(form)
        lay.addStretch(1)

    def load(self, p: EventProfile):
        self.slider.setValue(p.new_pct)
        self.slider.valueChanged.emit(p.new_pct)
        self.months.setValue(p.new_months)
        self.ymin.setValue(p.classic_year_min)
        self.ymax.setValue(p.classic_year_max)

    def apply(self, p: EventProfile):
        p.new_pct, p.new_months = self.slider.value(), self.months.value()
        p.classic_year_min, p.classic_year_max = sorted((self.ymin.value(), self.ymax.value()))


class GenrePicker(QDialog):
    def __init__(self, genres: list[Genre], selected: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Géneros del bloque")
        self.setMinimumSize(360, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(muted("Si no marcas ninguno, el bloque usa todos los géneros permitidos del evento."))
        self.list = QListWidget()
        self.list.setObjectName("PathList")
        for g in genres:
            it = QListWidgetItem(g.name)
            it.setData(Qt.UserRole, g.slug)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if g.slug in selected else Qt.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def selected(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class StepBlocks(QWidget):
    COLS = ["Bloque", "Inicio", "Minutos", "Energía mín", "Energía máx", "Géneros", "Solo clásicos"]

    def __init__(self, genres: list[Genre]):
        super().__init__()
        self.genres = genres
        self.names = {g.slug: g.name for g in genres}
        w, lay = _section("Bloques horarios", "Divide la noche en bloques con su energía objetivo (1 = suave, "
                                              "10 = peak). Puedes limitar los géneros de cada bloque.")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setMinimumHeight(260)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in (("Agregar bloque", self.add_row), ("Quitar", self.remove_row),
                         ("Subir", lambda: self.move(-1)), ("Bajar", lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.total = muted("", wrap=False)
        row.addWidget(self.total)
        lay.addLayout(row)
        self._block_genres: list[list[str]] = []

    def _spin(self, lo, hi, val, suffix=""):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        if suffix:
            s.setSuffix(suffix)
        s.valueChanged.connect(self._update_total)
        return s

    def add_row(self, b: Block | None = None):
        b = b or Block("Nuevo bloque", "", 60, 5, 8)
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(b.name))
        self.table.setItem(r, 1, QTableWidgetItem(b.start))
        self.table.setCellWidget(r, 2, self._spin(5, 600, b.minutes, " min"))
        self.table.setCellWidget(r, 3, self._spin(1, 10, b.energy_min))
        self.table.setCellWidget(r, 4, self._spin(1, 10, b.energy_max))
        self._block_genres.insert(r, list(b.genres))
        btn = QPushButton(self._genres_text(b.genres))
        btn.clicked.connect(lambda _=False, bt=btn: self._pick(bt))
        self.table.setCellWidget(r, 5, btn)
        cb = QCheckBox()
        cb.setChecked(b.classics_only)
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(30, 0, 0, 0)
        bl.addWidget(cb)
        self.table.setCellWidget(r, 6, box)
        self._update_total()

    def _genres_text(self, slugs):
        return "Todos los permitidos" if not slugs else ", ".join(self.names.get(s, s) for s in slugs)[:60]

    def _row_of(self, widget) -> int:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 5) is widget:
                return r
        return -1

    def _pick(self, btn):
        r = self._row_of(btn)
        dlg = GenrePicker(self.genres, self._block_genres[r], self)
        if dlg.exec():
            self._block_genres[r] = dlg.selected()
            btn.setText(self._genres_text(self._block_genres[r]))

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._block_genres.pop(r)
            self._update_total()

    def move(self, d: int):
        r = self.table.currentRow()
        blocks = self.blocks()
        t = r + d
        if r < 0 or not 0 <= t < len(blocks):
            return
        blocks[r], blocks[t] = blocks[t], blocks[r]
        self._fill(blocks)
        self.table.selectRow(t)

    def _fill(self, blocks: list[Block]):
        self.table.setRowCount(0)
        self._block_genres = []
        for b in blocks:
            self.add_row(b)

    def _update_total(self):
        mins = sum(self.table.cellWidget(r, 2).value() for r in range(self.table.rowCount())
                   if self.table.cellWidget(r, 2))
        self.total.setText(f"Duración total: {mins // 60} h {mins % 60:02d} min  ·  ~{max(10, round(mins / 3))} temas")

    def blocks(self) -> list[Block]:
        out = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip() or f"Bloque {r + 1}"
            start = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            lo, hi = self.table.cellWidget(r, 3).value(), self.table.cellWidget(r, 4).value()
            cb = self.table.cellWidget(r, 6).findChild(QCheckBox)
            out.append(Block(name, start, self.table.cellWidget(r, 2).value(), min(lo, hi), max(lo, hi),
                             list(self._block_genres[r]), bool(cb and cb.isChecked())))
        return out

    def load(self, p: EventProfile):
        self._fill(copy.deepcopy(p.blocks))

    def apply(self, p: EventProfile):
        p.blocks = self.blocks()


class StepFilters(QWidget):
    def __init__(self):
        super().__init__()
        w, lay = _section("Filtros y cantidad", "Letras explícitas, artistas vetados u obligatorios y largo del set.")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w)
        self.explicit = QCheckBox("Sacar temas con letra explícita o subida de tono")
        lay.addWidget(self.explicit)
        self.explicit_note = muted("")
        lay.addWidget(self.explicit_note)
        lay.addWidget(QLabel("Artistas vetados (nunca entran) — uno por línea o separados por coma:"))
        self.banned = QPlainTextEdit()
        self.banned.setMaximumHeight(90)
        self.banned.setPlaceholderText("Ej: Los Prisioneros, Soda Stereo")
        lay.addWidget(self.banned)
        lay.addWidget(QLabel("Artistas obligatorios / semilla (se buscan sí o sí y suben de prioridad):"))
        self.seeds = QPlainTextEdit()
        self.seeds.setMaximumHeight(90)
        self.seeds.setPlaceholderText("Ej: Pailita, Bad Bunny")
        lay.addWidget(self.seeds)
        row = QHBoxLayout()
        row.addWidget(QLabel("Cantidad de temas"))
        self.count = QSpinBox()
        self.count.setRange(0, 400)
        self.count.setSpecialValueText("Automática (según duración)")
        self.count.setMinimumWidth(240)
        row.addWidget(self.count)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

    def set_kids(self, kids: bool):
        if kids:
            self.explicit.setChecked(True)
        self.explicit.setEnabled(not kids)
        self.explicit_note.setText("Obligatorio para público infantil o preadolescente." if kids else "")

    def load(self, p: EventProfile):
        self.explicit.setChecked(p.explicit_filter)
        self.banned.setPlainText(", ".join(p.banned_artists))
        self.seeds.setPlainText(", ".join(p.seed_artists))
        self.count.setValue(p.track_count)
        self.set_kids(p.is_kids)

    def apply(self, p: EventProfile):
        p.explicit_filter = self.explicit.isChecked()
        p.banned_artists = parse_names(self.banned.toPlainText())
        p.seed_artists = parse_names(self.seeds.toPlainText())
        p.track_count = self.count.value()


def profile_summary_html(p: EventProfile, names: dict[str, str]) -> str:
    gw = sorted(p.genre_weights.items(), key=lambda kv: -kv[1])
    genres = ", ".join(f"{names.get(g, g)} {w}%" for g, w in gw if w > 0) or "—"
    banned = ", ".join(names.get(g, g) for g in p.banned_genres) or "—"
    blocks = "<br>".join(f"&nbsp;&nbsp;• {b.start or ''} <b>{b.name}</b> · {b.minutes} min · energía "
                         f"{b.energy_min}–{b.energy_max}" + (" · solo clásicos" if b.classics_only else "")
                         for b in p.blocks) or "—"
    return (f"<b>{p.name}</b> · {EVENT_TYPES.get(p.event_type, p.event_type)}<br>"
            f"Fecha: {p.event_date or '—'} · Lugar: {p.venue or '—'}<br>"
            f"Público: {p.age_min}–{p.age_max} años · País: {COUNTRIES.get(p.country, p.country)}<br><br>"
            f"<b>Géneros:</b> {genres}<br><b>Vetados:</b> {banned}<br><br>"
            f"<b>Nuevos:</b> {p.new_pct}% (últimos {p.new_months} meses) · clásicos {p.classic_year_min}–{p.classic_year_max}<br>"
            f"<b>Letras explícitas:</b> {'se sacan' if p.explicit_filter else 'permitidas'}<br>"
            f"<b>Artistas vetados:</b> {', '.join(p.banned_artists) or '—'}<br>"
            f"<b>Artistas semilla:</b> {', '.join(p.seed_artists) or '—'}<br><br>"
            f"<b>Bloques</b> (~{p.target_count()} temas):<br>{blocks}")


class ProfileEditor:
    """Agrupa los pasos. load(profile) / profile()."""

    def __init__(self, genres: list[Genre]):
        self.basics = StepBasics()
        self.audience = StepAudience()
        self.genres = StepGenres(genres)
        self.newclassic = StepNewClassic()
        self.blocks = StepBlocks(genres)
        self.filters = StepFilters()
        self.steps = [self.basics, self.audience, self.genres, self.newclassic, self.blocks, self.filters]
        self.audience.age_min.valueChanged.connect(self._sync_kids)
        self.basics.etype.currentIndexChanged.connect(self._sync_kids)
        self._base = EventProfile()

    def _sync_kids(self):
        p = EventProfile(event_type=self.basics.etype.currentData() or "otro", age_min=self.audience.age_min.value())
        self.filters.set_kids(p.is_kids)

    def load(self, p: EventProfile):
        self._base = copy.deepcopy(p)
        for s in self.steps:
            s.load(p)
        self._sync_kids()

    def profile(self) -> EventProfile:
        p = copy.deepcopy(self._base)
        for s in self.steps:
            s.apply(p)
        return p.enforce_rules()
