"""Prueba de humo: la ventana abre y todas las pantallas se pueden mostrar."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from app.ui.theme import QSS
    app.setStyleSheet(QSS)
    return app


def test_main_window_opens_all_pages(qapp, data_dir):
    from app.main import build_context
    from app.ui.main_window import NAV, MainWindow

    ctx = build_context()
    ctx.vault.unlock()
    win = MainWindow(ctx)
    win.show()
    for i, (key, *_r) in enumerate(NAV):
        win.nav.setCurrentRow(i)
        qapp.processEvents()
        assert win.stack.currentWidget() is win.pages[key]
    win.close()
    ctx.db.close()


def test_saving_key_updates_home(qapp, data_dir):
    from app.main import build_context
    from app.ui.main_window import MainWindow

    ctx = build_context()
    ctx.vault.unlock()
    win = MainWindow(ctx)
    card = win.pages["claves"].cards["lastfm_api_key"]
    card.edit.setText("clave-de-prueba")
    card.save()
    assert ctx.vault.get("lastfm_api_key") == "clave-de-prueba"
    assert win.home.st_keys.value.text() == "1 de 4"
    win.close()
    ctx.db.close()
