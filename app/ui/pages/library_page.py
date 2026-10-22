"""Biblioteca: importar VirtualDJ, escanear carpetas y buscar qué temas tengo."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem)

from ...context import AppContext
from ..widgets import Card, Page, badge, muted, run_in_background, set_badge, styled_button

ORIGIN = {"vdj": "VirtualDJ", "scan": "Carpeta", "manual": "Manual"}
COLUMNS = ["Artista", "Título", "Formato", "Calidad", "Origen", "Ruta"]


def _n(v: int) -> str:
    return f"{int(v or 0):,}".replace(",", ".")


class LibraryPage(Page):
    def __init__(self, ctx: AppContext, status_cb: Callable[[str], None]):
        super().__init__("Mi biblioteca", "SETMAKER mira tu VirtualDJ y tus carpetas para saber qué temas "
                                          "ya tienes y en qué calidad.")
        self.ctx = ctx
        self.status_msg = status_cb
        self._busy = False
        self._progress: dict = {"text": ""}
        self._matcher = None          # se crea al buscar (y se invalida tras importar/escanear)

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_progress)

        # ---------- VirtualDJ ----------
        vdj = Card("VirtualDJ")
        self.vdj_badge = badge("—")
        vdj.header.addWidget(self.vdj_badge)
        self.lbl_vdj_path = muted("")
        self.lbl_vdj_count = QLabel("")
        vdj.body.addWidget(self.lbl_vdj_path)
        vdj.body.addWidget(self.lbl_vdj_count)
        row = QHBoxLayout()
        self.btn_vdj = styled_button(QPushButton("Importar / reimportar VirtualDJ"), "primary")
        self.btn_vdj.clicked.connect(self._import_vdj)
        row.addWidget(self.btn_vdj)
        row.addStretch(1)
        vdj.body.addLayout(row)
        self.add(vdj)

        # ---------- carpetas ----------
        sc = Card("Carpetas de música")
        self.scan_badge = badge("—")
        sc.header.addWidget(self.scan_badge)
        self.lbl_scan = QLabel("")
        self.lbl_scan.setWordWrap(True)
        sc.body.addWidget(self.lbl_scan)
        row = QHBoxLayout()
        self.btn_scan = styled_button(QPushButton("Escanear carpetas"), "primary")
        self.btn_scan.clicked.connect(self._scan)
        row.addWidget(self.btn_scan)
        row.addStretch(1)
        sc.body.addLayout(row)
        self.add(sc)

        self.lbl_progress = muted("")
        self.add(self.lbl_progress)

        # ---------- búsqueda ----------
        se = Card("Buscar en mi música")
        row = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Artista o título… (Enter para buscar)")
        self.ed_search.returnPressed.connect(self._search)
        b = QPushButton("Buscar")
        b.clicked.connect(self._search)
        row.addWidget(self.ed_search, 1)
        row.addWidget(b)
        se.body.addLayout(row)
        self.lbl_results = muted("Escribe algo y pulsa Buscar. Se muestran hasta 200 resultados.")
        se.body.addWidget(self.lbl_results)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(360)
        hh = self.table.horizontalHeader()
        for i in range(len(COLUMNS) - 1):
            hh.setSectionResizeMode(i, QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 90)
        se.body.addWidget(self.table)
        self.add(se)
        self.finish()

    # ---------------------------------------------------------------- estado
    def on_show(self) -> None:
        self._refresh_status()

    def _count(self, sql: str) -> int:
        try:
            return int(self.ctx.db.scalar(sql) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def _refresh_status(self) -> None:
        cfg = self.ctx.config
        xml = (cfg.get("virtualdj.database_xml") or "").strip()
        n_vdj = self._count("SELECT COUNT(*) FROM library_tracks WHERE source='vdj'")
        n_kar = self._count("SELECT COUNT(*) FROM library_tracks WHERE source='vdj' AND is_karaoke=1")
        last = self.ctx.db.meta_get("library.vdj_imported_at", "")
        if not xml:
            self.lbl_vdj_path.setText("Todavía no eliges tu database.xml. Hazlo en Ajustes → VirtualDJ.")
            set_badge(self.vdj_badge, "Sin configurar", "off")
        else:
            exists = Path(xml).is_file()
            self.lbl_vdj_path.setText(f"Archivo: {xml}" + ("" if exists else "  (no lo encuentro: ¿disco desconectado?)"))
            if n_vdj:
                set_badge(self.vdj_badge, "Importado", "ok")
            else:
                set_badge(self.vdj_badge, "Sin importar" if exists else "No encontrado", "warn" if exists else "error")
        txt = f"<b>{_n(n_vdj)}</b> temas de VirtualDJ · {_n(n_kar)} karaokes"
        if last:
            txt += f" · última importación: {last}"
        self.lbl_vdj_count.setText(txt)

        folders = cfg.get("library.music_folders") or []
        n_scan = self._count("SELECT COUNT(*) FROM library_tracks WHERE source='scan'")
        if not folders:
            self.lbl_scan.setText("No tienes carpetas agregadas. Agrégalas en Ajustes → Carpetas de música.")
            set_badge(self.scan_badge, "Sin carpetas", "off")
        else:
            self.lbl_scan.setText(f"{len(folders)} carpeta(s) configurada(s) · <b>{_n(n_scan)}</b> archivos escaneados "
                                  "que no están en VirtualDJ.")
            set_badge(self.scan_badge, "Escaneado" if n_scan else "Sin escanear", "ok" if n_scan else "warn")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_vdj.setEnabled(not busy)
        self.btn_scan.setEnabled(not busy)
        if busy:
            self._timer.start()
        else:
            self._timer.stop()

    def _poll_progress(self) -> None:
        text = self._progress.get("text")
        if text:
            self.lbl_progress.setText(text)

    def _progress_cb(self, done: int, total, message: str) -> None:
        # se llama desde el hilo de trabajo: solo escribe en el dict (el QTimer lo muestra)
        self._progress["text"] = message

    # ---------------------------------------------------------------- acciones
    def _import_vdj(self) -> None:
        if self._busy:
            return
        xml = (self.ctx.config.get("virtualdj.database_xml") or "").strip()
        if not xml:
            self.lbl_progress.setText("Primero elige tu database.xml en Ajustes → VirtualDJ.")
            return
        if not Path(xml).is_file():
            self.lbl_progress.setText(f"No encuentro {xml}. Conecta el disco donde está VirtualDJ y vuelve a intentar.")
            return
        from ...library.vdj_db import import_vdj_database
        self._set_busy(True)
        self._progress["text"] = "Leyendo la base de VirtualDJ…"
        self.lbl_progress.setText(self._progress["text"])
        run_in_background(lambda: import_vdj_database(self.ctx.db, xml, self._progress_cb),
                          self._vdj_done, self._failed)

    def _vdj_done(self, stats: dict) -> None:
        from datetime import datetime
        self._set_busy(False)
        self._matcher = None
        self.ctx.db.meta_set("library.vdj_imported_at", datetime.now().strftime("%d-%m-%Y %H:%M"))
        msg = (f"VirtualDJ importado ✓ — {_n(stats.get('imported'))} temas "
               f"({_n(stats.get('karaoke'))} karaokes, {_n(stats.get('skipped'))} saltados: videos o en línea).")
        self.lbl_progress.setText(msg)
        self.status_msg("VirtualDJ importado ✓")
        self._refresh_status()

    def _scan(self) -> None:
        if self._busy:
            return
        folders = self.ctx.config.get("library.music_folders") or []
        if not folders:
            self.lbl_progress.setText("No tienes carpetas para escanear. Agrégalas en Ajustes → Carpetas de música.")
            return
        from ...library.scanner import scan_folders
        self._set_busy(True)
        self._progress["text"] = "Escaneando carpetas…"
        self.lbl_progress.setText(self._progress["text"])
        run_in_background(lambda: scan_folders(self.ctx.db, list(folders), self._progress_cb),
                          self._scan_done, self._failed)

    def _scan_done(self, s: dict) -> None:
        self._set_busy(False)
        self._matcher = None
        msg = (f"Escaneo listo ✓ — {_n(s.get('found'))} archivos: {_n(s.get('new'))} nuevos, "
               f"{_n(s.get('updated'))} actualizados, {_n(s.get('removed'))} ya no estaban")
        if s.get("skipped_vdj"):
            msg += f", {_n(s['skipped_vdj'])} ya venían de VirtualDJ"
        msg += "."
        if s.get("errors"):
            msg += f" {_n(s['errors'])} archivos no se pudieron leer."
        if s.get("missing_folders"):
            msg += " No encontré: " + ", ".join(s["missing_folders"]) + "."
        self.lbl_progress.setText(msg)
        self.status_msg("Escaneo de carpetas listo ✓")
        self._refresh_status()

    def _failed(self, err: str) -> None:
        self._set_busy(False)
        self.lbl_progress.setText(f"Algo falló: {err}")
        self.status_msg("No se pudo completar la operación")

    def _search(self) -> None:
        from ...library.matcher import LibraryMatcher
        if self._matcher is None:
            self._matcher = LibraryMatcher(self.ctx.db, ignore_karaoke=False)
        results = self._matcher.search(self.ed_search.text(), limit=200)
        self.table.setRowCount(0)
        self.table.setRowCount(len(results))
        for r, d in enumerate(results):
            vals = [d["artist"], d["title"], (d["format"] or "").upper(), d["quality_label"],
                    ORIGIN.get(d["source"], d["source"]), d["path"]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v or ""))
                if c == len(vals) - 1:
                    item.setToolTip(str(v))
                self.table.setItem(r, c, item)
        if not self._matcher.by_path:
            self.lbl_results.setText("Tu biblioteca está vacía: importa VirtualDJ o escanea tus carpetas.")
        elif not results:
            self.lbl_results.setText("No encontré nada con eso.")
        else:
            extra = " (mostrando los primeros 200)" if len(results) >= 200 else ""
            self.lbl_results.setText(f"{_n(len(results))} resultado(s){extra}.")
