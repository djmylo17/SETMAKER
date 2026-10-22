"""Punto de entrada de SETMAKER."""
from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__
from .backup import apply_pending_restore
from .config import Config
from .context import AppContext
from .db.database import Database
from .paths import (config_path, data_dir, db_path, is_writable, pending_restore_path,
                    resource_dir, vault_path)
from .security.vault import KeyVault, VaultLocked, WrongPassword
from .ui.dialogs import PasswordDialog
from .ui.theme import QSS

log = logging.getLogger("setmaker")


def setup_logging(folder) -> None:
    handler = RotatingFileHandler(folder / "logs" / "setmaker.log", maxBytes=1_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # httpx registra URLs completas (podrían incluir claves): se silencia.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def install_error_handler() -> None:
    def handler(exc_type, exc, tb):
        log.error("Error no controlado:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            QMessageBox.critical(None, APP_NAME,
                                 "Ocurrió un error inesperado. SETMAKER sigue funcionando, pero si se "
                                 "repite, envía el archivo data\\logs\\setmaker.log.\n\n"
                                 f"Detalle: {exc}")
        except Exception:  # noqa: BLE001
            pass
    sys.excepthook = handler


def unlock_vault(vault: KeyVault) -> bool:
    """Abre la bóveda; si tiene contraseña, la pide. False si el usuario cancela."""
    try:
        vault.unlock()
        return True
    except VaultLocked:
        pass
    except WrongPassword as exc:
        QMessageBox.warning(None, APP_NAME, f"{exc}\nSe creará un archivo de claves nuevo.")
        vault.path.replace(vault.path.with_suffix(".enc.danado"))
        vault.unlock()
        return True
    dlg = PasswordDialog(APP_NAME, "Escribe tu contraseña maestra para abrir tus claves.")
    while dlg.exec():
        try:
            vault.unlock(dlg.value())
            return True
        except WrongPassword:
            dlg.show_error("Contraseña incorrecta.")
    return False


def build_context() -> AppContext:
    d = data_dir()
    restored = apply_pending_restore(d, pending_restore_path())
    ctx = AppContext(data_dir=d, config=Config(config_path()), db=Database(db_path()),
                     vault=KeyVault(vault_path()))
    if restored:
        log.info("Se aplicó un respaldo al iniciar")
    return ctx


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    icon = resource_dir() / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    d = data_dir()
    if not is_writable(d):
        QMessageBox.critical(None, APP_NAME,
                             f"No puedo guardar datos en:\n{d}\n\nRevisa que el disco no esté protegido "
                             "contra escritura y que la carpeta no esté en modo solo lectura.")
        return 1
    setup_logging(d)
    install_error_handler()
    log.info("Iniciando %s %s", APP_NAME, __version__)

    ctx = build_context()
    if not unlock_vault(ctx.vault):
        return 0

    from .ui.main_window import MainWindow
    win = MainWindow(ctx)
    win.show()
    code = app.exec()
    ctx.db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
