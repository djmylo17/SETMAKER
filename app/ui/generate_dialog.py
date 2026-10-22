"""Ventana "Generando…": progreso por etapa en lenguaje simple."""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QProgressBar, QPushButton,
                               QVBoxLayout)

from ..engine.pipeline import Cancelled


class GenerateDialog(QDialog):
    def __init__(self, run_fn, parent=None):
        """run_fn(progress_cb, cancel_cb) -> resultado. Se ejecuta en un hilo aparte."""
        super().__init__(parent)
        self.setWindowTitle("Generando set")
        self.setMinimumSize(560, 420)
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        title = QLabel("Armando tu set…")
        title.setStyleSheet("font-size: 15pt; font-weight: 700;")
        lay.addWidget(title)
        self.stage = QLabel("Preparando")
        self.stage.setWordWrap(True)
        lay.addWidget(self.stage)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet("QProgressBar{background:#0d0f14;border:1px solid #262c3a;border-radius:6px;height:12px;}"
                               "QProgressBar::chunk{background:#2fe0a0;border-radius:6px;}")
        lay.addWidget(self.bar)
        self.log = QListWidget()
        self.log.setObjectName("PathList")
        lay.addWidget(self.log, 1)
        self.elapsed = QLabel("")
        self.elapsed.setObjectName("Muted")
        row = QHBoxLayout()
        row.addWidget(self.elapsed)
        row.addStretch(1)
        self.btn = QPushButton("Cancelar")
        self.btn.clicked.connect(self._cancel)
        row.addWidget(self.btn)
        lay.addLayout(row)

        self.result = None
        self.error: str | None = None
        self._state = {"msg": "Preparando", "frac": 0.0, "log": [], "done": False}
        self._cancel_flag = False
        self._t0 = time.monotonic()
        self._lock = threading.Lock()
        self._seen = 0

        def progress(msg: str, frac: float):
            with self._lock:
                self._state["msg"] = msg
                if frac >= 0:
                    self._state["frac"] = frac
                if not self._state["log"] or self._state["log"][-1] != msg:
                    self._state["log"].append(msg)

        def worker():
            try:
                self.result = run_fn(progress, lambda: self._cancel_flag)
            except Cancelled:
                self.error = "cancelado"
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).exception("Error generando set")
                self.error = str(exc) or exc.__class__.__name__
            finally:
                self._state["done"] = True

        self._thread = threading.Thread(target=worker, daemon=True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)
        self._thread.start()

    def _tick(self):
        with self._lock:
            st = dict(self._state)
            new_logs = self._state["log"][self._seen:]
            self._seen = len(self._state["log"])
        self.stage.setText(st["msg"])
        self.bar.setValue(int(st["frac"] * 100))
        for m in new_logs:
            self.log.addItem("• " + m)
        if new_logs:
            self.log.scrollToBottom()
        self.elapsed.setText(f"{int(time.monotonic() - self._t0)} s")
        if st["done"]:
            self._timer.stop()
            self.accept() if self.result is not None else self.reject()

    def _cancel(self):
        self._cancel_flag = True
        self.btn.setEnabled(False)
        self.btn.setText("Cancelando…")

    def reject(self):
        if not self._state["done"]:
            self._cancel()
            return
        super().reject()
