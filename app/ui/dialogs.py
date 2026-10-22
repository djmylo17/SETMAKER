"""Diálogos de contraseña maestra."""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout)


class PasswordDialog(QDialog):
    """Pide la contraseña al abrir. Si confirm=True, la pide dos veces (para crearla)."""

    def __init__(self, title: str, message: str, confirm: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        msg = QLabel(message)
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Contraseña")
        lay.addWidget(self.pw)
        self.pw2 = None
        if confirm:
            self.pw2 = QLineEdit()
            self.pw2.setEchoMode(QLineEdit.Password)
            self.pw2.setPlaceholderText("Repite la contraseña")
            lay.addWidget(self.pw2)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #ff5c5c;")
        lay.addWidget(self.error)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Aceptar")
        btns.button(QDialogButtonBox.Cancel).setText("Cancelar")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _accept(self):
        if not self.pw.text():
            self.error.setText("Escribe una contraseña.")
            return
        if self.pw2 is not None:
            if len(self.pw.text()) < 6:
                self.error.setText("Usa al menos 6 caracteres.")
                return
            if self.pw.text() != self.pw2.text():
                self.error.setText("Las contraseñas no coinciden.")
                return
        self.accept()

    def value(self) -> str:
        return self.pw.text()

    def show_error(self, text: str):
        self.error.setText(text)
        self.pw.selectAll()
        self.pw.setFocus()
