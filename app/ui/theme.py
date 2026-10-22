"""Tema oscuro estilo software DJ."""

COLORS = {
    "bg": "#0d0f14",
    "sidebar": "#11141b",
    "panel": "#171b24",
    "panel_hi": "#1e2330",
    "border": "#262c3a",
    "text": "#e8ebf2",
    "muted": "#8a93a6",
    "accent": "#2fe0a0",      # verde neón
    "accent_dim": "#1a7f5c",
    "accent2": "#ff4f8b",     # magenta
    "warn": "#ffb547",
    "error": "#ff5c5c",
}

C = COLORS

QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: {C['text']};
}}
QMainWindow, QWidget#Root {{ background: {C['bg']}; }}
QWidget#Page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {C['bg']}; }}

/* ---------- barra lateral ---------- */
QWidget#Sidebar {{ background: {C['sidebar']}; border-right: 1px solid {C['border']}; }}
QLabel#Brand {{ font-size: 17pt; font-weight: 800; letter-spacing: 2px; color: {C['text']}; }}
QLabel#BrandSub {{ color: {C['accent']}; font-size: 8pt; letter-spacing: 1px; }}
QListWidget#Nav {{ background: transparent; border: none; outline: none; }}
QListWidget#Nav::item {{
    padding: 9px 12px; margin: 2px 8px; border-radius: 8px; color: {C['muted']};
}}
QListWidget#Nav::item:hover {{ background: {C['panel']}; color: {C['text']}; }}
QListWidget#Nav::item:selected {{
    background: {C['panel_hi']}; color: {C['accent']}; border-left: 3px solid {C['accent']};
}}
QLabel#Version {{ color: {C['muted']}; font-size: 8pt; }}

/* ---------- textos ---------- */
QLabel#PageTitle {{ font-size: 20pt; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {C['muted']}; font-size: 10.5pt; }}
QLabel#CardTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#Muted {{ color: {C['muted']}; }}
QLabel#Help {{
    color: {C['muted']}; background: {C['bg']}; border: 1px solid {C['border']};
    border-radius: 8px; padding: 10px 12px;
}}
QLabel#StatValue {{ font-size: 18pt; font-weight: 700; }}
QLabel#StatLabel {{ color: {C['muted']}; font-size: 9pt; }}

/* ---------- tarjetas ---------- */
QFrame#Card {{
    background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 12px;
}}
QFrame#Hero {{
    border-radius: 14px; border: 1px solid {C['border']};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #13261f, stop:0.55 {C['panel']}, stop:1 #2a1420);
}}

/* ---------- badges ---------- */
QLabel[badge="ok"] {{
    color: {C['accent']}; background: rgba(47,224,160,0.12);
    border: 1px solid rgba(47,224,160,0.35); border-radius: 10px; padding: 2px 10px; font-size: 8.5pt;
}}
QLabel[badge="warn"] {{
    color: {C['warn']}; background: rgba(255,181,71,0.10);
    border: 1px solid rgba(255,181,71,0.35); border-radius: 10px; padding: 2px 10px; font-size: 8.5pt;
}}
QLabel[badge="off"] {{
    color: {C['muted']}; background: transparent;
    border: 1px solid {C['border']}; border-radius: 10px; padding: 2px 10px; font-size: 8.5pt;
}}
QLabel[badge="error"] {{
    color: {C['error']}; background: rgba(255,92,92,0.10);
    border: 1px solid rgba(255,92,92,0.35); border-radius: 10px; padding: 2px 10px; font-size: 8.5pt;
}}

/* ---------- botones ---------- */
QPushButton {{
    background: {C['panel_hi']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {C['accent_dim']}; }}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{ color: #555d6e; border-color: {C['border']}; }}
QPushButton[kind="primary"] {{
    background: {C['accent']}; color: #04140d; border: none; font-weight: 700;
}}
QPushButton[kind="primary"]:hover {{ background: #4cf0b6; }}
QPushButton[kind="primary"]:disabled {{ background: {C['accent_dim']}; color: #0b3326; }}
QPushButton[kind="big"] {{
    background: {C['accent']}; color: #04140d; border: none; font-weight: 800;
    font-size: 12pt; padding: 12px 26px; border-radius: 10px;
}}
QPushButton[kind="big"]:hover {{ background: #4cf0b6; }}
QPushButton[kind="link"] {{
    background: transparent; border: none; color: {C['accent']}; padding: 4px 2px; text-align: left;
}}
QPushButton[kind="link"]:hover {{ text-decoration: underline; }}
QPushButton[kind="danger"] {{ color: {C['error']}; }}

/* ---------- entradas ---------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 7px 10px; selection-background-color: {C['accent_dim']};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {C['panel']}; border: 1px solid {C['border']}; selection-background-color: {C['panel_hi']};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid {C['border']}; background: {C['bg']};
}}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
QListWidget#PathList {{
    background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 4px;
}}

/* ---------- scroll ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4256; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QStatusBar {{ background: {C['sidebar']}; color: {C['muted']}; border-top: 1px solid {C['border']}; }}
QToolTip {{ background: {C['panel_hi']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 6px; }}
QMessageBox, QDialog {{ background: {C['panel']}; }}
"""
