# -*- coding: utf-8 -*-
"""
Resolucion de rutas: cambia por completo entre desarrollo y app empaquetada.

En desarrollo todo cuelga de la carpeta del proyecto. Empaquetado con
PyInstaller hay que separar dos cosas que en desarrollo son la misma:

  - los archivos DE la app (ui.html, tesseract): van dentro del bundle, en una
    carpeta temporal de solo lectura (sys._MEIPASS);
  - los datos DEL usuario (base, Excel, cache): tienen que ir a una carpeta
    escribible, porque en Windows el instalador deja la app en Archivos de
    programa, que es de solo lectura.
"""
import os
import subprocess
import sys
from pathlib import Path

EMPAQUETADA = getattr(sys, "frozen", False)
WINDOWS = sys.platform == "win32"


def recurso(*partes) -> Path:
    """Un archivo que viaja DENTRO de la app (solo lectura)."""
    if EMPAQUETADA:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).joinpath(*partes)
    return Path(__file__).resolve().parent.joinpath(*partes)


def carpeta_datos() -> Path:
    """Donde se guardan la base, el Excel y el cache. Siempre escribible."""
    if not EMPAQUETADA:
        destino = Path(__file__).resolve().parent.parent / "datos"
    elif WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        destino = Path(base) / "ExpedientesGEDO"
    else:
        destino = Path.home() / ".expedientes-gedo"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def ruta_tesseract() -> str:
    """Tesseract: bundleado con la app, o del sistema si esta instalado."""
    if EMPAQUETADA:
        propio = recurso("tesseract", "tesseract.exe" if WINDOWS else "tesseract")
        if propio.exists():
            return str(propio)
    from shutil import which
    return which("tesseract") or ""


def entorno_tesseract():
    """TESSDATA_PREFIX apunta a los idiomas que viajan con la app."""
    entorno = dict(os.environ)
    if EMPAQUETADA:
        datos = recurso("tesseract", "tessdata")
        if datos.exists():
            entorno["TESSDATA_PREFIX"] = str(datos)
    return entorno


# En Windows, cada subprocess abriria una ventana negra de consola sobre la
# interfaz. Esta bandera la suprime; en macOS y Linux no existe.
SIN_CONSOLA = {"creationflags": 0x08000000} if WINDOWS else {}


def abrir_archivo(ruta):
    """Abre un archivo con el programa que corresponda segun el sistema."""
    ruta = str(ruta)
    if WINDOWS:
        os.startfile(ruta)                                    # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", ruta], check=False)
    else:
        subprocess.run(["xdg-open", ruta], check=False)
