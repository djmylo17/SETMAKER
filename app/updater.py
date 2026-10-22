"""Actualizaciones automáticas desde las Releases de GitHub.

Pasos:
1. check_for_update(): pregunta a GitHub cuál es la última Release y la compara con
   la versión instalada (app.__version__).
2. download_update(): baja SETMAKER-windows.zip a data/_update/ y revisa que sea válido.
3. apply_update_and_restart(): descomprime, escribe un .bat que espera a que SETMAKER
   se cierre, copia los archivos nuevos ENCIMA de la carpeta de la app (sin tocar data/),
   vuelve a abrir SETMAKER.exe y limpia. Después de llamarla, la app debe cerrarse.

La carpeta data/ (eventos, claves, ajustes) NUNCA se toca: robocopy la excluye con /XD.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from . import __version__
from .net import USER_AGENT, SourceError, friendly_status
from .paths import app_base_dir, data_dir

DEFAULT_REPO = "djmylo17/setmaker"
ASSET_NAME = "SETMAKER-windows.zip"
EXE_IN_ZIP = "SETMAKER/SETMAKER.exe"


class UpdateError(Exception):
    """Error de actualización con mensaje listo para mostrar."""


# ---------------------------------------------------------------- versiones
def parse_version(v: str) -> tuple[tuple[int, int, int], bool]:
    """'v1.2.3' -> ((1,2,3), es_prerelease). Acepta '1.2', 'v1.2.3-beta.1'."""
    v = (v or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", v)
    if not m:
        return (0, 0, 0), True
    nums = tuple(int(x or 0) for x in m.group(1, 2, 3))
    rest = m.group(4) or ""
    pre = rest.startswith("-") or bool(re.match(r"^[a-zA-Z]", rest))
    return nums, pre  # type: ignore[return-value]


def is_newer(remote: str, local: str) -> bool:
    """True si 'remote' es más nueva que 'local' (una versión final gana a su pre-release)."""
    (rn, rpre), (ln, lpre) = parse_version(remote), parse_version(local)
    if rn != ln:
        return rn > ln
    return lpre and not rpre


# ---------------------------------------------------------------- 1. buscar
def check_for_update(repo: str = DEFAULT_REPO, current: str = __version__,
                     client: httpx.Client | None = None) -> dict | None:
    """Devuelve {version, notes, zip_url, html_url} si hay una versión más nueva; si no, None."""
    repo = (repo or DEFAULT_REPO).strip().strip("/")
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=True)
    try:
        r = client.get(url, headers=headers)
    except httpx.TransportError as exc:
        raise SourceError("No hay conexión a internet o GitHub no responde.") from exc
    finally:
        if own:
            client.close()
    if r.status_code == 404:
        raise SourceError("Todavía no hay versiones publicadas en GitHub.")
    if r.status_code == 403:
        raise SourceError("GitHub limitó las consultas por un rato. Intenta en una hora.")
    if r.status_code >= 400:
        raise SourceError(friendly_status(r.status_code))
    data = r.json()
    tag = data.get("tag_name") or data.get("name") or ""
    if data.get("draft") or not is_newer(tag, current):
        return None
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset:
        raise SourceError("La versión nueva aún no tiene el archivo para Windows. Intenta en unos minutos.")
    return {
        "version": tag.lstrip("vV"),
        "notes": (data.get("body") or "").strip(),
        "zip_url": asset.get("browser_download_url", ""),
        "html_url": data.get("html_url", ""),
    }


# ---------------------------------------------------------------- 2. descargar
def update_dir() -> Path:
    return data_dir() / "_update"


def verify_zip(path: Path) -> None:
    """Revisa que el zip esté sano y traiga SETMAKER/SETMAKER.exe."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = {n.replace("\\", "/") for n in zf.namelist()}
            if EXE_IN_ZIP not in names:
                raise UpdateError("El archivo descargado no contiene SETMAKER.exe. No se instaló nada.")
            bad = zf.testzip()
            if bad:
                raise UpdateError("El archivo descargado está dañado. Vuelve a intentar.")
            # Seguridad: nada de rutas que se salgan de la carpeta
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts:
                    raise UpdateError("El archivo descargado tiene rutas extrañas. No se instaló nada.")
    except zipfile.BadZipFile as exc:
        raise UpdateError("El archivo descargado no es un .zip válido. Vuelve a intentar.") from exc


def download_update(info: dict, progress: Callable[[int, int], None] | None = None,
                    client: httpx.Client | None = None) -> Path:
    """Descarga el zip (progress(bytes_bajados, bytes_totales)); devuelve la ruta."""
    url = info.get("zip_url")
    if not url:
        raise UpdateError("No hay link de descarga para esta versión.")
    folder = update_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / ASSET_NAME
    part = folder / (ASSET_NAME + ".part")
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True)
    try:
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as r:
            if r.status_code >= 400:
                raise SourceError(friendly_status(r.status_code))
            total = int(r.headers.get("Content-Length", 0) or 0)
            done = 0
            with open(part, "wb") as fh:
                for chunk in r.iter_bytes(64 * 1024):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except httpx.TransportError as exc:
        part.unlink(missing_ok=True)
        raise SourceError("Se cortó la descarga. Revisa tu internet y vuelve a intentar.") from exc
    finally:
        if own:
            client.close()
    os.replace(part, dest)
    try:
        verify_zip(dest)
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    return dest


# ---------------------------------------------------------------- 3. instalar
def build_update_script(pid: int, new_app_dir: Path, app_dir: Path, exe_name: str,
                        work_dir: Path) -> str:
    """Contenido del .bat que reemplaza los archivos cuando SETMAKER ya se cerró."""
    # Nota: en un .bat el % se escribe %% dentro de FOR; aquí no usamos FOR.
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        "title Actualizando SETMAKER...",
        "echo Actualizando SETMAKER, no cierres esta ventana...",
        # 1) Esperar a que el proceso actual termine (revisa cada 1 segundo)
        ":esperar",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto esperar",
        ")",
        # Pequeño margen para que Windows suelte los archivos
        "timeout /t 1 /nobreak >nul",
        # 2) Copiar lo nuevo encima, SIN tocar la carpeta data (/XD data).
        #    /E = subcarpetas, /R:3 /W:2 = reintentos si un archivo está ocupado.
        f'robocopy "{new_app_dir}" "{app_dir}" /E /XD data "{app_dir / "data"}" '
        "/R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul",
        # robocopy: códigos 0–7 = bien, 8 o más = error
        "if errorlevel 8 (",
        "  echo No se pudo copiar la actualización. Tu versión anterior sigue funcionando.",
        "  pause",
        ")",
        # 3) Volver a abrir SETMAKER
        f'start "" "{app_dir / exe_name}"',
        # 4) Limpiar la carpeta temporal (el .bat se borra a sí mismo al final)
        f'rmdir /s /q "{work_dir / "new"}" 2>nul',
        f'del /q "{work_dir / ASSET_NAME}" 2>nul',
        '(goto) 2>nul & del "%~f0"',
        "",
    ])


def apply_update_and_restart(zip_path: Path) -> None:
    """Prepara la instalación y lanza el .bat. Luego el que llama debe cerrar la app."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("Solo disponible en la versión empaquetada (SETMAKER.exe).")
    if os.name != "nt":
        raise UpdateError("La actualización automática solo funciona en Windows.")
    zip_path = Path(zip_path)
    verify_zip(zip_path)
    work = update_dir()
    new_root = work / "new"
    if new_root.exists():
        shutil.rmtree(new_root, ignore_errors=True)
    new_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(new_root)
    new_app = new_root / "SETMAKER"
    if not (new_app / "SETMAKER.exe").exists():
        raise UpdateError("La actualización descargada está incompleta. No se instaló nada.")
    # Por si alguien empaquetó una carpeta data dentro del zip: se descarta.
    shutil.rmtree(new_app / "data", ignore_errors=True)

    app_dir = app_base_dir()
    exe_name = Path(sys.executable).name or "SETMAKER.exe"
    bat = work / "actualizar_setmaker.bat"
    bat.write_text(build_update_script(os.getpid(), new_app, app_dir, exe_name, work),
                   encoding="utf-8")
    # Lanzar el .bat en una consola propia (minimizada) que sigue viva cuando SETMAKER se cierra.
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    try:
        # Se pasa como texto (no lista) para que las comillas vacías de "start" lleguen tal cual.
        subprocess.Popen(f'cmd /c start "" /min "{bat}"', creationflags=flags,
                         close_fds=True, cwd=str(work))
    except OSError as exc:
        raise UpdateError(f"No se pudo iniciar el instalador: {exc}") from exc
