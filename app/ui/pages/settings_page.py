"""Ajustes: rutas, región, exportaciones, respaldo y actualizaciones."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPushButton)

from ... import __version__
from ...backup import BackupError, create_backup, schedule_restore
from ...config import COUNTRIES
from ...context import AppContext
from ...library.vdj_paths import default_folders_dir, find_vdj_databases
from ...paths import pending_restore_path
from ..widgets import Card, Page, muted, styled_button


def path_row(edit: QLineEdit, *buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(edit, 1)
    for b in buttons:
        row.addWidget(b)
    return row


class SettingsPage(Page):
    def __init__(self, ctx: AppContext, status_cb: Callable[[str], None], changed_cb: Callable[[], None]):
        super().__init__("Ajustes", "Los cambios se guardan solos.")
        self.ctx = ctx
        self.status_msg = status_cb
        self.changed = changed_cb
        cfg = ctx.config

        # ---------- VirtualDJ ----------
        vdj = Card("VirtualDJ")
        vdj.body.addWidget(muted("Archivo database.xml de tu VirtualDJ. Si tu música está en el disco "
                                 "portátil, VirtualDJ guarda una base en X:\\VirtualDJ\\database.xml de ese disco."))
        self.ed_vdj = QLineEdit(cfg.get("virtualdj.database_xml"))
        self.ed_vdj.setPlaceholderText("Ej: E:\\VirtualDJ\\database.xml")
        self.ed_vdj.editingFinished.connect(lambda: self._set_path("virtualdj.database_xml", self.ed_vdj))
        b_browse = QPushButton("Examinar…")
        b_browse.clicked.connect(self._browse_vdj)
        b_detect = styled_button(QPushButton("Detectar"), "primary")
        b_detect.clicked.connect(self._detect_vdj)
        vdj.body.addLayout(path_row(self.ed_vdj, b_browse, b_detect))

        vdj.body.addWidget(muted("Carpeta donde se guardarán los crates (.vdjfolder) que exporte SETMAKER:"))
        self.ed_folders = QLineEdit(cfg.get("virtualdj.folders_dir"))
        self.ed_folders.setPlaceholderText("Normalmente …\\VirtualDJ\\Folders")
        self.ed_folders.editingFinished.connect(lambda: self._set_path("virtualdj.folders_dir", self.ed_folders))
        b_f = QPushButton("Examinar…")
        b_f.clicked.connect(lambda: self._browse_dir("virtualdj.folders_dir", self.ed_folders))
        vdj.body.addLayout(path_row(self.ed_folders, b_f))
        self.add(vdj)

        # ---------- carpetas de música ----------
        lib = Card("Carpetas de música")
        lib.body.addWidget(muted("Carpetas extra que SETMAKER revisará para saber qué temas tienes, "
                                 "aunque no estén en VirtualDJ (el escaneo llega en la Fase 4)."))
        self.list_folders = QListWidget()
        self.list_folders.setObjectName("PathList")
        self.list_folders.setMaximumHeight(130)
        self.list_folders.addItems(cfg.get("library.music_folders") or [])
        lib.body.addWidget(self.list_folders)
        row = QHBoxLayout()
        b_add = QPushButton("Agregar carpeta…")
        b_add.clicked.connect(self._add_folder)
        b_rm = QPushButton("Quitar seleccionada")
        b_rm.clicked.connect(self._remove_folder)
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addStretch(1)
        lib.body.addLayout(row)
        self.chk_karaoke = QCheckBox("Ignorar los karaokes al buscar qué temas tengo")
        self.chk_karaoke.setChecked(bool(cfg.get("library.ignore_karaoke")))
        self.chk_karaoke.toggled.connect(lambda v: self._set("library.ignore_karaoke", v))
        lib.body.addWidget(self.chk_karaoke)
        self.add(lib)

        # ---------- región ----------
        reg = Card("Región")
        row = QHBoxLayout()
        row.addWidget(QLabel("País principal:"))
        self.cb_country = QComboBox()
        for code, name in COUNTRIES.items():
            self.cb_country.addItem(name, code)
        idx = self.cb_country.findData(cfg.get("region.country", "CL"))
        self.cb_country.setCurrentIndex(max(idx, 0))
        self.cb_country.currentIndexChanged.connect(
            lambda: self._set("region.country", self.cb_country.currentData()))
        row.addWidget(self.cb_country)
        row.addStretch(1)
        reg.body.addLayout(row)
        prio = " → ".join(COUNTRIES.get(c, c) for c in cfg.get("region.priority", []))
        reg.body.addWidget(muted(f"Prioridad de tendencias: {prio}. Se podrá ajustar por evento en la Fase 2."))
        self.add(reg)

        # ---------- exportaciones ----------
        exp = Card("Exportaciones")
        exp.body.addWidget(muted("Dónde se guardan las listas en Excel, CSV, TXT y el JSON para CrateDJ. "
                                 "Si lo dejas vacío, se usa la carpeta data\\exports de SETMAKER."))
        self.ed_exp = QLineEdit(cfg.get("export.dir"))
        self.ed_exp.setPlaceholderText(str(ctx.data_dir / "exports"))
        self.ed_exp.editingFinished.connect(lambda: self._set_path("export.dir", self.ed_exp))
        b_e = QPushButton("Examinar…")
        b_e.clicked.connect(lambda: self._browse_dir("export.dir", self.ed_exp))
        exp.body.addLayout(path_row(self.ed_exp, b_e))
        self.add(exp)

        # ---------- respaldo ----------
        bk = Card("Respaldo de tus datos")
        bk.body.addWidget(muted("Guarda en un .zip tus eventos, plantillas, ajustes y claves (cifradas). "
                                "Recomendado antes de actualizar."))
        row = QHBoxLayout()
        b1 = styled_button(QPushButton("Crear respaldo ahora"), "primary")
        b1.clicked.connect(self._backup)
        b2 = QPushButton("Restaurar respaldo…")
        b2.clicked.connect(self._restore)
        b3 = QPushButton("Abrir carpeta de datos")
        b3.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ctx.data_dir))))
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        bk.body.addLayout(row)
        self.add(bk)

        # ---------- actualizaciones ----------
        up = Card("Actualizaciones")
        up.body.addWidget(QLabel(f"Versión instalada: <b>{__version__}</b>"))
        up.body.addWidget(muted("El botón «Buscar actualizaciones» se activa en la Fase 6. Descargará la "
                                "versión nueva desde GitHub y la instalará sin tocar tu carpeta data."))
        b_up = QPushButton("Buscar actualizaciones")
        b_up.setEnabled(False)
        up.body.addWidget(b_up)
        self.add(up)
        self.finish()

    # ---------- helpers ----------
    def _set(self, key, value):
        self.ctx.config.set(key, value)
        self.status_msg("Ajustes guardados ✓")
        self.changed()

    def _set_path(self, key: str, edit: QLineEdit):
        value = edit.text().strip().strip('"')
        edit.setText(value)
        if value and not Path(value).exists():
            self.status_msg("Ojo: esa ruta no existe en este PC (puede ser un disco no conectado)")
        if value != self.ctx.config.get(key):
            self._set(key, value)

    def _browse_vdj(self):
        start = self.ed_vdj.text() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Elige database.xml de VirtualDJ", start,
                                              "Base de VirtualDJ (database.xml);;XML (*.xml)")
        if path:
            self._apply_vdj(Path(path))

    def _apply_vdj(self, db: Path):
        self.ed_vdj.setText(str(db))
        self._set("virtualdj.database_xml", str(db))
        if not self.ed_folders.text():
            folders = default_folders_dir(db)
            self.ed_folders.setText(str(folders))
            self._set("virtualdj.folders_dir", str(folders))

    def _detect_vdj(self):
        found = find_vdj_databases()
        if not found:
            QMessageBox.information(self, "Detectar VirtualDJ",
                                    "No encontré ningún database.xml. Conecta tu disco portátil y vuelve a "
                                    "intentar, o usa «Examinar…» para elegirlo a mano.")
            return
        if len(found) == 1:
            self._apply_vdj(found[0])
            self.status_msg(f"Encontrado: {found[0]}")
            return
        from PySide6.QtWidgets import QInputDialog
        items = [str(p) for p in found]
        choice, ok = QInputDialog.getItem(self, "Detectar VirtualDJ",
                                          "Encontré varias bases. ¿Cuál usas para tu música?", items, 0, False)
        if ok and choice:
            self._apply_vdj(Path(choice))

    def _browse_dir(self, key: str, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Elige carpeta", edit.text() or str(Path.home()))
        if path:
            edit.setText(str(Path(path)))
            self._set(key, str(Path(path)))

    def _folders(self) -> list[str]:
        return [self.list_folders.item(i).text() for i in range(self.list_folders.count())]

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Agregar carpeta de música", str(Path.home()))
        if path and str(Path(path)) not in self._folders():
            self.list_folders.addItem(str(Path(path)))
            self._set("library.music_folders", self._folders())

    def _remove_folder(self):
        row = self.list_folders.currentRow()
        if row >= 0:
            self.list_folders.takeItem(row)
            self._set("library.music_folders", self._folders())

    def _backup(self):
        try:
            dest = create_backup(self.ctx.data_dir, self.ctx.db)
        except OSError as exc:
            QMessageBox.warning(self, "Respaldo", f"No se pudo crear el respaldo:\n{exc}")
            return
        QMessageBox.information(self, "Respaldo", f"Respaldo creado:\n{dest.name}\n\nEstá en data\\backups.")

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elige un respaldo", str(self.ctx.data_dir / "backups"),
                                              "Respaldo de SETMAKER (*.zip)")
        if not path:
            return
        ok = QMessageBox.question(
            self, "Restaurar respaldo",
            "Esto reemplazará tus datos actuales por los del respaldo.\n"
            "Se aplicará la próxima vez que abras SETMAKER.\n\n¿Continuar?")
        if ok != QMessageBox.Yes:
            return
        try:
            schedule_restore(Path(path), pending_restore_path())
        except BackupError as exc:
            QMessageBox.warning(self, "Restaurar respaldo", str(exc))
            return
        QMessageBox.information(self, "Restaurar respaldo",
                                "Listo. Cierra SETMAKER y vuelve a abrirlo para aplicar el respaldo.")
