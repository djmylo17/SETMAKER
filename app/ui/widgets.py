"""Piezas de interfaz reutilizables."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)


# ---------------------------------------------------------------- trabajo en segundo plano
class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 — se muestra en la UI
            traceback.print_exc()
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.done.emit(result)


_active: set[_Task] = set()


def run_in_background(fn: Callable[[], Any], on_done: Callable[[Any], None],
                      on_error: Callable[[str], None] | None = None) -> None:
    """Ejecuta fn sin congelar la ventana y avisa al terminar."""
    task = _Task(fn)
    _active.add(task)

    def _finish_ok(res):
        _active.discard(task)
        on_done(res)

    def _finish_err(msg):
        _active.discard(task)
        (on_error or (lambda m: None))(msg)

    task.signals.done.connect(_finish_ok)
    task.signals.failed.connect(_finish_err)
    QThreadPool.globalInstance().start(task)


# ---------------------------------------------------------------- layout
class Card(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(10)
        if title:
            self.header = QHBoxLayout()
            lbl = QLabel(title)
            lbl.setObjectName("CardTitle")
            self.header.addWidget(lbl)
            self.header.addStretch(1)
            self.body.addLayout(self.header)


def badge(text: str, kind: str = "off") -> QLabel:
    lbl = QLabel(text)
    set_badge(lbl, text, kind)
    lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lbl


def set_badge(lbl: QLabel, text: str, kind: str) -> None:
    lbl.setText(text)
    lbl.setProperty("badge", kind)
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)


def muted(text: str, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(wrap)
    return lbl


def styled_button(btn, kind: str):
    btn.setProperty("kind", kind)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class Page(QScrollArea):
    """Página con scroll, título y subtítulo."""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        self.setWidget(inner)
        self.layout_ = QVBoxLayout(inner)
        self.layout_.setContentsMargins(36, 30, 36, 30)
        self.layout_.setSpacing(16)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        self.layout_.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("PageSubtitle")
            s.setWordWrap(True)
            self.layout_.addWidget(s)
        self.layout_.addSpacing(4)

    def add(self, w: QWidget) -> QWidget:
        self.layout_.addWidget(w)
        return w

    def finish(self) -> None:
        self.layout_.addStretch(1)

    def on_show(self) -> None:
        """Se llama cada vez que se muestra la página (para refrescar datos)."""
