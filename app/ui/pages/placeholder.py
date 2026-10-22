"""Pantallas que se construyen en fases siguientes."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from ..widgets import Card, Page, badge, muted


class PlaceholderPage(Page):
    def __init__(self, title: str, subtitle: str, phase: int, bullets: list[str]):
        super().__init__(title, subtitle)
        card = Card()
        card.header_row = badge(f"Llega en la Fase {phase}", "warn")
        card.body.addWidget(card.header_row)
        card.body.addWidget(muted("Esta pantalla está reservada. Lo que tendrá:"))
        for b in bullets:
            lbl = QLabel(f"•  {b}")
            lbl.setWordWrap(True)
            card.body.addWidget(lbl)
        self.add(card)
        self.finish()
