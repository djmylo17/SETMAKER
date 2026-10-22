"""Gráficos simples dibujados a mano (sin dependencias extra)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .theme import C


class GenreBars(QWidget):
    """Distribución de géneros: barra real vs. marca de lo pedido."""

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self.setMinimumHeight(60)

    def set_data(self, rows: list[dict]):
        self.rows = [r for r in rows if r.get("requested") or r.get("actual")][:12]
        self.setMinimumHeight(28 * len(self.rows) + 10)
        self.setFixedHeight(28 * len(self.rows) + 10)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        label_w = min(170, int(w * 0.45))
        bar_w = w - label_w - 50
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        for i, r in enumerate(self.rows):
            y = 6 + i * 28
            p.setPen(QColor(C["muted"]))
            name = p.fontMetrics().elidedText(r["name"], Qt.ElideRight, label_w - 10)
            p.drawText(QRectF(0, y, label_w - 8, 20), Qt.AlignVCenter | Qt.AlignRight, name)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["panel_hi"]))
            p.drawRoundedRect(QRectF(label_w, y + 4, bar_w, 12), 4, 4)
            p.setBrush(QColor(C["accent"]))
            p.drawRoundedRect(QRectF(label_w, y + 4, bar_w * min(r["actual"], 100) / 100, 12), 4, 4)
            # marca de lo pedido
            x = label_w + bar_w * min(r["requested"], 100) / 100
            p.setPen(QPen(QColor(C["accent2"]), 2))
            p.drawLine(QPointF(x, y + 1), QPointF(x, y + 19))
            p.setPen(QColor(C["text"]))
            p.drawText(QRectF(label_w + bar_w + 6, y, 44, 20), Qt.AlignVCenter, f"{r['actual']}%")
        p.end()


class EnergyCurve(QWidget):
    def __init__(self):
        super().__init__()
        self.values: list[int] = []
        self.blocks: list[int] = []
        self.setMinimumHeight(120)

    def set_data(self, values: list[int], block_index: list[int] | None = None):
        self.values = values
        self.blocks = block_index or []
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 10
        p.setPen(QPen(QColor(C["border"]), 1, Qt.DashLine))
        for lvl in (2, 5, 8):
            y = h - pad - (h - 2 * pad) * lvl / 10
            p.drawLine(QPointF(pad, y), QPointF(w - pad, y))
        if len(self.values) < 2:
            p.end()
            return
        step = (w - 2 * pad) / (len(self.values) - 1)
        # separadores de bloque
        p.setPen(QPen(QColor(C["panel_hi"]), 1))
        for i in range(1, len(self.blocks)):
            if self.blocks[i] != self.blocks[i - 1]:
                x = pad + i * step - step / 2
                p.drawLine(QPointF(x, pad), QPointF(x, h - pad))
        path = QPainterPath()
        for i, v in enumerate(self.values):
            pt = QPointF(pad + i * step, h - pad - (h - 2 * pad) * v / 10)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor(C["accent"]), 2.2))
        p.drawPath(path)
        p.end()
