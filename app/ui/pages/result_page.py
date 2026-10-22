"""Resultado del set: la pantalla principal de trabajo."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from ...context import AppContext
from ...core import store
from ...core.models import (EVENT_TYPES, HAVE, MISSING, OTHER_VERSION, STATUS_LABELS, EventProfile,
                            SetItem)
from ...engine.pipeline import SetGenerator, describe_sources, trend_score, year_of
from ..charts import EnergyCurve, GenreBars
from ..widgets import Card, muted, run_in_background, styled_button

log = logging.getLogger(__name__)

COLS = ["#", "Bloque", "Tema", "Artista", "Género", "Año", "BPM", "Energía", "Tendencia", "Fuentes",
        "Estado", "Por qué entró"]
STATUS_COLORS = {HAVE: "#2fe0a0", OTHER_VERSION: "#ffb547", MISSING: "#ff5c5c"}


class DragTable(QTableWidget):
    moved = Signal(int, int)

    def __init__(self, rows, cols):
        super().__init__(rows, cols)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)

    def dropEvent(self, event):
        src = self.currentRow()
        dst = self.rowAt(int(event.position().y()))
        if dst < 0:
            dst = self.rowCount() - 1
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        if src >= 0 and dst != src:
            self.moved.emit(src, dst)


class ResultPage(QWidget):
    changed = Signal()            # el set cambió (para Faltantes / Inicio)
    go_to = Signal(str)

    def __init__(self, ctx: AppContext, status_cb):
        super().__init__()
        self.setObjectName("Page")
        self.ctx = ctx
        self.status_msg = status_cb
        self.profile: EventProfile | None = None
        self.items: list[SetItem] = []
        self.pool: list[SetItem] = []
        self.summary: dict = {}
        self.discarded: list[dict] = []
        self.warnings: list[str] = []
        self.event_id: int | None = None
        self.set_id: int | None = None
        self.player = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(12)

        # ---------- encabezado
        head = QHBoxLayout()
        tl = QVBoxLayout()
        self.title = QLabel("Set")
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("PageSubtitle")
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        head.addLayout(tl, 1)
        self.btn_lib = QPushButton("Revisar mi biblioteca")
        self.btn_lib.clicked.connect(self.check_library)
        self.btn_vdj = styled_button(QPushButton("Crate VirtualDJ"), "primary")
        self.btn_vdj.clicked.connect(self.export_vdj)
        self.btn_missing = QPushButton("Faltantes y exportar →")
        self.btn_missing.clicked.connect(lambda: self.go_to.emit("faltantes"))
        self.btn_edit = QPushButton("Editar perfil")
        self.btn_edit.clicked.connect(lambda: self.go_to.emit("editar"))
        self.btn_regen = QPushButton("Regenerar")
        self.btn_regen.clicked.connect(lambda: self.go_to.emit("regenerar"))
        for b in (self.btn_edit, self.btn_regen, self.btn_lib, self.btn_missing, self.btn_vdj):
            head.addWidget(b)
        root.addLayout(head)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color:#ffb547; background: rgba(255,181,71,0.08); border:1px solid "
                                "rgba(255,181,71,0.3); border-radius:8px; padding:8px 12px;")
        self.warn.setVisible(False)
        root.addWidget(self.warn)

        # ---------- filtros y acciones
        bar = QHBoxLayout()
        self.f_block = QComboBox()
        self.f_genre = QComboBox()
        self.f_missing = QCheckBox("Solo faltantes")
        for w in (self.f_block, self.f_genre):
            w.currentIndexChanged.connect(self.apply_filters)
        self.f_missing.toggled.connect(self.apply_filters)
        bar.addWidget(QLabel("Filtrar:"))
        bar.addWidget(self.f_block)
        bar.addWidget(self.f_genre)
        bar.addWidget(self.f_missing)
        bar.addStretch(1)
        self.btn_play = QPushButton("▶ Preview")
        self.btn_play.clicked.connect(self.toggle_preview)
        bar.addWidget(self.btn_play)
        for text, tip, fn in (("👍", "Me gusta (sube su prioridad en este tipo de evento)", self.like),
                              ("👎", "Sacar y reemplazar (no vuelve en este tipo de evento)", self.dislike),
                              ("↻ Similar", "Reemplazar por uno parecido", self.similar)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        more = QToolButton()
        more.setText("Más ▾")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Vetar este artista en este tipo de evento", self.ban_artist)
        menu.addAction("Vetar este tema en este tipo de evento", self.ban_track)
        self.move_menu = menu.addMenu("Mover a bloque")
        menu.addAction("Subir", lambda: self.shift(-1))
        menu.addAction("Bajar", lambda: self.shift(1))
        menu.addSeparator()
        menu.addAction("Marcar «la tengo»: elegir archivo…", self.pick_local)
        menu.addAction("Marcar «me falta»", self.force_missing)
        menu.addAction("Abrir en Deezer / YouTube", self.open_link)
        menu.addSeparator()
        menu.addAction("Ver temas descartados y por qué", self.show_discarded)
        more.setMenu(menu)
        more.setStyleSheet("QToolButton{background:#1e2330;border:1px solid #262c3a;border-radius:8px;padding:7px 12px;}"
                           "QToolButton::menu-indicator{image:none;}")
        bar.addWidget(more)
        root.addLayout(bar)

        # ---------- tabla + resumen
        split = QSplitter(Qt.Horizontal)
        self.table = DragTable(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget{background:#11141b; alternate-background-color:#141823;"
                                 "border:1px solid #262c3a; border-radius:10px; gridline-color:#1c2130;}"
                                 "QTableWidget::item:selected{background:#1f3a31; color:#e8ebf2;}"
                                 "QHeaderView::section{background:#171b24; color:#8a93a6; border:none;"
                                 "border-bottom:1px solid #262c3a; padding:6px;}")
        hh = self.table.horizontalHeader()
        for c in range(len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for col, wdt in ((1, 120), (3, 150), (4, 170), (11, 260)):
            hh.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, wdt)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setWordWrap(False)
        self.table.moved.connect(self._moved)
        self.table.doubleClicked.connect(lambda _i: self.toggle_preview())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(lambda pos: menu.exec(self.table.viewport().mapToGlobal(pos)))
        self.table.currentCellChanged.connect(lambda *_: self._show_detail())
        split.addWidget(self.table)

        from PySide6.QtWidgets import QScrollArea
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setMinimumWidth(320)
        side_scroll.setMaximumWidth(400)
        side = QWidget()
        side.setObjectName("Page")
        side_scroll.setWidget(side)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 0, 0, 0)
        sl.setSpacing(10)
        c1 = Card("Resumen")
        self.lbl_stats = QLabel("")
        self.lbl_stats.setWordWrap(True)
        self.lbl_stats.setTextFormat(Qt.RichText)
        c1.body.addWidget(self.lbl_stats)
        sl.addWidget(c1)
        c2 = Card("Géneros: real vs. pedido")
        self.bars = GenreBars()
        c2.body.addWidget(self.bars)
        c2.body.addWidget(muted("Barra verde = real · línea rosada = lo que pediste"))
        sl.addWidget(c2)
        c3 = Card("Curva de energía")
        self.curve = EnergyCurve()
        c3.body.addWidget(self.curve)
        sl.addWidget(c3)
        c4 = Card("Por qué entró")
        self.detail = QLabel("Selecciona un tema.")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.RichText)
        c4.body.addWidget(self.detail)
        sl.addWidget(c4)
        sl.addStretch(1)
        split.addWidget(side_scroll)
        split.setStretchFactor(0, 1)
        root.addWidget(split, 1)

        self.empty = muted("Todavía no hay un set abierto. Crea uno en «Nuevo set» o ábrelo desde Inicio.")
        root.addWidget(self.empty)

    # ================================================================ carga
    def load(self, event_id: int, set_id: int, profile: EventProfile, items: list[SetItem], summary: dict,
             discarded: list[dict], pool: list[SetItem] | None = None, warnings: list[str] | None = None):
        self.event_id, self.set_id, self.profile = event_id, set_id, profile
        self.items, self.summary, self.discarded = items, summary, discarded
        self.pool = pool if pool is not None else [SetItem.from_dict(d) for d in summary.get("pool", [])]
        self.warnings = warnings if warnings is not None else summary.get("warnings", [])
        self.genres = store.genre_map(self.ctx.db)
        self.names = {k: g.name for k, g in self.genres.items()}
        self.f_block.blockSignals(True)
        self.f_genre.blockSignals(True)
        self.f_block.clear()
        self.f_block.addItem("Todos los bloques", -1)
        for i, b in enumerate(profile.blocks):
            self.f_block.addItem(b.name, i)
        self.f_genre.clear()
        self.f_genre.addItem("Todos los géneros", "")
        for g in sorted({it.cls.primary for it in items}):
            self.f_genre.addItem(self.names.get(g, g), g)
        self.f_block.blockSignals(False)
        self.f_genre.blockSignals(False)
        self.move_menu.clear()
        for i, b in enumerate(profile.blocks):
            self.move_menu.addAction(b.name, lambda bi=i: self.move_to_block(bi))
        self.refresh()

    def has_set(self) -> bool:
        return self.profile is not None

    # ================================================================ pintar
    def refresh(self):
        has = self.profile is not None
        self.empty.setVisible(not has)
        for w in (self.table, self.btn_lib, self.btn_vdj, self.btn_missing, self.btn_edit, self.btn_regen):
            w.setEnabled(has)
        if not has:
            return
        p = self.profile
        self.title.setText(p.name)
        self.subtitle.setText(f"{EVENT_TYPES.get(p.event_type, '')} · {p.event_date or 'sin fecha'}"
                              f"{' · ' + p.venue if p.venue else ''} · público {p.age_min}–{p.age_max} años")
        self.warn.setText("⚠  " + "<br>⚠  ".join(self.warnings) if self.warnings else "")
        self.warn.setTextFormat(Qt.RichText)
        self.warn.setVisible(bool(self.warnings))

        sel = self.table.currentRow()
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            t, c = it.track, it.cls
            trend, _ = trend_score(t, p)
            block = p.blocks[it.block].name if it.block < len(p.blocks) else "—"
            vals = [str(r + 1), block, t.title, t.artist, self.names.get(c.primary, c.primary),
                    str(year_of(t, c) or "—"), f"{t.bpm:.0f}" if t.bpm else "—", str(c.energy),
                    "●" * max(1, round(trend * 5)) + "○" * (5 - max(1, round(trend * 5))),
                    str(len(t.sources)), STATUS_LABELS.get(it.status, "—"), " · ".join(it.reasons[:2])]
            for col, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setData(Qt.UserRole, r)
                if col == 10 and it.status in STATUS_COLORS:
                    cell.setForeground(QColor(STATUS_COLORS[it.status]))
                if col == 9:
                    cell.setToolTip(describe_sources(t))
                if col == 11:
                    cell.setToolTip("\n".join(it.reasons))
                if col == 2 and it.is_new:
                    cell.setText("✦ " + v)
                    cell.setToolTip("Tema nuevo")
                if col in (2, 3, 4):
                    cell.setToolTip(cell.toolTip() or v)
                self.table.setItem(r, col, cell)
        if 0 <= sel < len(self.items):
            self.table.selectRow(sel)
        self.apply_filters()
        self._summary()

    def _summary(self):
        p = self.profile
        n = len(self.items)
        have = sum(it.status == HAVE for it in self.items)
        other = sum(it.status == OTHER_VERSION for it in self.items)
        miss = sum(it.status == MISSING for it in self.items)
        new = sum(it.is_new for it in self.items)
        checked = any(it.status in (HAVE, OTHER_VERSION, MISSING) for it in self.items)
        lib = (f"<span style='color:#2fe0a0'>{have} la tengo</span> · <span style='color:#ffb547'>{other} otra "
               f"versión</span> · <span style='color:#ff5c5c'>{miss} me faltan</span>" if checked
               else "<i>Biblioteca sin revisar</i>")
        mins = round(n * p.avg_track_minutes)
        self.lbl_stats.setText(
            f"<b>{n}</b> temas (pedidos {p.target_count()}) · ~{mins // 60} h {mins % 60:02d} min<br>"
            f"Nuevos: <b>{round(100 * new / max(n, 1))}%</b> (pedido {p.new_pct}%)<br>{lib}<br>"
            f"Descartados: {self.summary.get('discarded_count', len(self.discarded))} "
            f"· clasificación: {self.summary.get('clasificacion', '—')}")
        # distribución recalculada en vivo
        real: dict[str, int] = {}
        for it in self.items:
            real[it.cls.primary] = real.get(it.cls.primary, 0) + 1
        weights = {g: w for g, w in p.genre_weights.items() if g in p.allowed_genres()}
        ws = sum(weights.values()) or 1
        rows = [{"name": self.names.get(g, g), "requested": round(100 * weights.get(g, 0) / ws),
                 "actual": round(100 * real.get(g, 0) / max(n, 1))}
                for g in sorted(set(weights) | set(real), key=lambda s: -weights.get(s, 0))]
        self.bars.set_data(rows)
        self.curve.set_data([it.cls.energy for it in self.items], [it.block for it in self.items])

    def apply_filters(self):
        b = self.f_block.currentData()
        g = self.f_genre.currentData()
        only = self.f_missing.isChecked()
        for r, it in enumerate(self.items):
            hide = (b not in (None, -1) and it.block != b) or (g and it.cls.primary != g) or \
                   (only and it.status not in (MISSING, OTHER_VERSION))
            self.table.setRowHidden(r, bool(hide))

    def _show_detail(self):
        it = self._current()
        if not it:
            return
        paths = "".join(f"<br>&nbsp;&nbsp;📁 {Path(d['path']).name} <span style='color:#8a93a6'>"
                        f"({d.get('quality_label') or d.get('format', '')})</span>" for d in it.local_paths[:4])
        note = f"<br><i>IA: {it.cls.note}</i>" if it.cls.note else ""
        self.detail.setText(f"<b>{it.track.artist} – {it.track.title}</b><br>" +
                            "<br>".join(f"• {r}" for r in it.reasons) + note +
                            (f"<br><b>{STATUS_LABELS.get(it.status)}</b>{paths}" if it.status in STATUS_COLORS else ""))

    # ================================================================ selección
    def _current_index(self) -> int:
        r = self.table.currentRow()
        if r < 0 or r >= len(self.items) or self.table.isRowHidden(r):
            return -1
        return r

    def _current(self) -> SetItem | None:
        i = self._current_index()
        return self.items[i] if i >= 0 else None

    def _need(self) -> int:
        i = self._current_index()
        if i < 0:
            self.status_msg("Selecciona un tema de la tabla primero")
        return i

    # ================================================================ guardar
    def persist(self):
        if not self.event_id:
            return
        self.summary["pool"] = [it.to_dict() for it in self.pool[:300]]
        self.summary["warnings"] = self.warnings
        self.set_id = store.save_set(self.ctx.db, self.event_id, self.items, self.summary, self.discarded, self.set_id)
        self.changed.emit()

    def _generator(self) -> SetGenerator:
        rules = store.learned_rules(self.ctx.db, self.profile.event_type)
        return SetGenerator(list(self.genres.values()), hub=None, rules=rules)

    def _replace(self, i: int, similar: bool) -> bool:
        gen = self._generator()
        rep = gen.replacement(self.profile, self.items, self.pool, i, similar=similar)
        old = self.items[i]
        if rep:
            self.pool = [p for p in self.pool if p.track.key != rep.track.key]
            if similar:   # el tema reemplazado sigue siendo apto: vuelve al pool
                self.pool.append(old)
            self._match_one(rep)
            self.items[i] = rep
            self.status_msg(f"Reemplazado por {rep.track.artist} – {rep.track.title}")
            return True
        self.items.pop(i)
        self.status_msg("No hay más temas aptos para reemplazar; se sacó del set")
        return False

    def _match_one(self, it: SetItem):
        try:
            from ...library.matcher import match_items
            if self.ctx.db.scalar("SELECT COUNT(*) FROM library_tracks"):
                match_items(self.ctx.db, [it], ignore_karaoke=bool(self.ctx.config.get("library.ignore_karaoke")))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo revisar la biblioteca")

    # ================================================================ acciones
    def like(self):
        i = self._need()
        if i < 0:
            return
        it = self.items[i]
        store.add_feedback(self.ctx.db, self.profile.event_type, "like", it.track.key, it.track.artist,
                           f"{it.track.artist} – {it.track.title}")
        if "Te gustó 👍 en este tipo de evento" not in it.reasons:
            it.reasons.append("Te gustó 👍 en este tipo de evento")
        self.status_msg("👍 Guardado: tendrá más prioridad en este tipo de evento")
        self.persist()
        self.refresh()

    def dislike(self):
        i = self._need()
        if i < 0:
            return
        it = self.items[i]
        store.add_feedback(self.ctx.db, self.profile.event_type, "dislike", it.track.key, it.track.artist,
                           f"{it.track.artist} – {it.track.title}")
        self._replace(i, similar=False)
        self.persist()
        self.refresh()

    def similar(self):
        i = self._need()
        if i < 0:
            return
        self._replace(i, similar=True)
        self.persist()
        self.refresh()

    def ban_artist(self):
        i = self._need()
        if i < 0:
            return
        from ...core.normalize import main_artist
        art = main_artist(self.items[i].track.artist)
        name = self.items[i].track.artist.split(" feat")[0]
        if QMessageBox.question(self, "Vetar artista",
                                f"¿Vetar a {name} en «{EVENT_TYPES.get(self.profile.event_type)}»?\n"
                                "Se sacan sus temas de este set y no volverá en este tipo de evento.") != QMessageBox.Yes:
            return
        store.add_feedback(self.ctx.db, self.profile.event_type, "ban_artist", "", name, name)
        idxs = [k for k, it in enumerate(self.items) if main_artist(it.track.artist) == art]
        for k in reversed(idxs):
            self._replace(k, similar=True)
        self.pool = [p for p in self.pool if main_artist(p.track.artist) != art]
        self.persist()
        self.refresh()

    def ban_track(self):
        i = self._need()
        if i < 0:
            return
        it = self.items[i]
        store.add_feedback(self.ctx.db, self.profile.event_type, "ban_track", it.track.key, it.track.artist,
                           f"{it.track.artist} – {it.track.title}")
        self._replace(i, similar=True)
        self.persist()
        self.refresh()

    def move_to_block(self, bi: int):
        i = self._need()
        if i < 0:
            return
        it = self.items.pop(i)
        it.block = bi
        # insertar al final de ese bloque
        pos = max([k for k, x in enumerate(self.items) if x.block <= bi], default=-1) + 1
        self.items.insert(pos, it)
        self.persist()
        self.refresh()
        self.table.selectRow(pos)

    def shift(self, d: int):
        i = self._need()
        if i < 0:
            return
        self._moved(i, max(0, min(len(self.items) - 1, i + d)))

    def _moved(self, src: int, dst: int):
        if src == dst or not (0 <= src < len(self.items)):
            return
        it = self.items.pop(src)
        dst = max(0, min(dst, len(self.items)))
        neighbor = self.items[dst - 1] if dst > 0 else (self.items[0] if self.items else None)
        if neighbor is not None:
            it.block = neighbor.block
        self.items.insert(dst, it)
        self.persist()
        self.refresh()
        self.table.selectRow(dst)

    def pick_local(self):
        i = self._need()
        if i < 0:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Elige el archivo de este tema", "",
                                              "Audio (*.mp3 *.wav *.flac *.m4a *.aiff *.aif *.ogg *.wma);;Todos (*)")
        if not path:
            return
        from ...library.matcher import LibraryMatcher
        LibraryMatcher(self.ctx.db).set_override(self.items[i].track.key, path)
        self._match_one(self.items[i]) if self.ctx.db.scalar("SELECT COUNT(*) FROM library_tracks") else None
        it = self.items[i]
        if it.status != HAVE:
            it.status = HAVE
            it.local_paths = [{"path": path, "format": Path(path).suffix.lstrip(".").upper(), "quality_label": ""}]
        self.persist()
        self.refresh()

    def force_missing(self):
        i = self._need()
        if i < 0:
            return
        from ...library.matcher import LibraryMatcher
        LibraryMatcher(self.ctx.db).set_override(self.items[i].track.key, "")
        self.items[i].status, self.items[i].local_paths = MISSING, []
        self.persist()
        self.refresh()

    def open_link(self):
        it = self._current()
        if it and it.track.link:
            QDesktopServices.openUrl(QUrl(it.track.link))

    def check_library(self):
        if not self.ctx.db.scalar("SELECT COUNT(*) FROM library_tracks"):
            QMessageBox.information(self, "Biblioteca", "Primero importa tu VirtualDJ o escanea tus carpetas en la "
                                                        "pantalla «Biblioteca».")
            self.go_to.emit("biblioteca")
            return
        from ...library.matcher import match_items
        self.btn_lib.setEnabled(False)
        self.btn_lib.setText("Revisando…")

        def done(counts):
            self.btn_lib.setEnabled(True)
            self.btn_lib.setText("Revisar mi biblioteca")
            self.persist()
            self.refresh()
            self.status_msg(f"Biblioteca: {counts.get(HAVE, 0)} la tengo · {counts.get(OTHER_VERSION, 0)} otra "
                            f"versión · {counts.get(MISSING, 0)} me faltan")

        run_in_background(lambda: match_items(self.ctx.db, self.items,
                                              ignore_karaoke=bool(self.ctx.config.get("library.ignore_karaoke"))),
                          done, lambda m: (done({}), self.status_msg(f"Error: {m}")))

    def export_vdj(self):
        if not self.items:
            return
        if not any(it.status == HAVE for it in self.items):
            QMessageBox.information(self, "Crate VirtualDJ", "El crate solo lleva los temas que ya tienes. Pulsa "
                                                             "«Revisar mi biblioteca» primero.")
            return
        dest = self.ctx.config.get("virtualdj.folders_dir") or ""
        if not dest or not Path(dest).exists():
            dest = QFileDialog.getExistingDirectory(self, "¿Dónde guardo el crate (.vdjfolder)?",
                                                    dest or str(Path.home()))
            if not dest:
                return
        from ...library.vdjfolder import export_vdjfolder
        name = f"{self.profile.event_date} {self.profile.name}".strip()
        try:
            path = export_vdjfolder(self.items, Path(dest), name)
        except OSError as exc:
            QMessageBox.warning(self, "Crate VirtualDJ", f"No se pudo guardar:\n{exc}")
            return
        n = sum(it.status == HAVE for it in self.items)
        box = QMessageBox(self)
        box.setWindowTitle("Crate VirtualDJ")
        box.setText(f"Crate guardado con {n} temas:\n{path}\n\nEn VirtualDJ aparece en la carpeta «Folders» "
                    "(si no se ve, reinicia VirtualDJ).")
        open_btn = box.addButton("Abrir carpeta", QMessageBox.ActionRole)
        box.addButton("OK", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def show_discarded(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Temas descartados")
        dlg.resize(820, 560)
        lay = QVBoxLayout(dlg)
        reasons = self.summary.get("discard_reasons", [])
        if reasons:
            lay.addWidget(muted("Motivos más comunes: " + " · ".join(f"{r} ({n})" for r, n in reasons[:6])))
        t = QTableWidget(len(self.discarded), 3)
        t.setHorizontalHeaderLabels(["Artista", "Tema", "Motivo"])
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, d in enumerate(self.discarded):
            for c, k in enumerate(("artist", "title", "reason")):
                t.setItem(r, c, QTableWidgetItem(d.get(k, "")))
        lay.addWidget(t)
        dlg.exec()

    # ================================================================ preview
    def toggle_preview(self):
        it = self._current()
        if not it:
            self.status_msg("Selecciona un tema para escuchar el preview")
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            self.status_msg("El reproductor no está disponible en este equipo")
            return
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.8)
            self.player.setAudioOutput(self.audio)
            self.player.errorOccurred.connect(lambda *_: self.status_msg("No se pudo reproducir el preview"))
            self._playing_key = None
        if self.player.playbackState() == QMediaPlayer.PlayingState and self._playing_key == it.track.key:
            self.player.stop()
            self.btn_play.setText("▶ Preview")
            return
        self.btn_play.setText("… cargando")

        def fresh_url():
            # los links de preview de Deezer vencen: se pide uno nuevo sin caché
            if it.track.deezer_id:
                from ...net import get_json
                d = get_json(f"https://api.deezer.com/track/{it.track.deezer_id}")
                return d.get("preview") or it.track.preview_url
            return it.track.preview_url

        def play(url):
            if not url:
                self.btn_play.setText("▶ Preview")
                self.status_msg("Este tema no tiene preview disponible")
                return
            self._playing_key = it.track.key
            self.player.setSource(QUrl(url))
            self.player.play()
            self.btn_play.setText("■ Detener")
            self.status_msg(f"▶ {it.track.artist} – {it.track.title} (30 s)")

        run_in_background(fresh_url, play, lambda m: play(it.track.preview_url))

    def stop_preview(self):
        if self.player:
            self.player.stop()
            self.btn_play.setText("▶ Preview")
