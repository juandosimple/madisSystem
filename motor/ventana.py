# -*- coding: utf-8 -*-
"""
Abre la interfaz como una ventana de aplicacion, no como una pestaña.

Se intentan tres caminos, de mejor a peor:

  1. pywebview, si esta instalado: ventana nativa de verdad. No se incluye en
     los requisitos porque empaquetarlo en Windows arrastra pythonnet y suma
     peso y fragilidad al instalador, que va a una portatil modesta.
  2. El navegador en "modo app" (--app=): ventana sin barra de direcciones ni
     pestanas, con su propio icono en la barra de tareas. Edge viene con
     Windows, asi que en la practica esta siempre. No cuesta nada.
  3. El navegador comun, como ultimo recurso.
"""
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from rutas import SIN_CONSOLA, WINDOWS, carpeta_datos

# Cada navegador con su ejecutable habitual. Se prueba en orden.
CANDIDATOS_WINDOWS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
CANDIDATOS_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


def _navegador():
    candidatos = CANDIDATOS_WINDOWS if WINDOWS else (
        CANDIDATOS_MAC if sys.platform == "darwin" else [])
    for ruta in candidatos:
        if Path(ruta).exists():
            return ruta
    for nombre in ("msedge", "google-chrome", "chromium", "chrome", "brave"):
        encontrado = shutil.which(nombre)
        if encontrado:
            return encontrado
    return None


def _con_pywebview(url):
    try:
        import webview
    except ImportError:
        return False
    webview.create_window("Expedientes GEDO", url, width=1180, height=880,
                          min_size=(900, 640))
    webview.start()
    return True


def _modo_app(url):
    """Ventana del navegador sin barra de direcciones ni pestanas."""
    navegador = _navegador()
    if not navegador:
        return None
    # Un perfil propio consigue dos cosas: que el navegador abra un proceso
    # nuevo (y no delegue en uno ya abierto, devolviendo el control enseguida)
    # y que la app no se mezcle con la navegacion personal del usuario.
    perfil = carpeta_datos() / "ventana"
    perfil.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [navegador, f"--app={url}", f"--user-data-dir={perfil}",
         "--window-size=1180,880", "--no-first-run", "--no-default-browser-check",
         # se apaga todo lo que el navegador hace de fondo y no nos sirve: en
         # una portátil modesta es trabajo regalado, y además ensucia el log
         "--disable-background-networking", "--disable-sync",
         "--disable-extensions", "--no-service-autorun", "--disable-breakpad"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SIN_CONSOLA)


def abrir(url):
    """Muestra la interfaz y vuelve enseguida.

    NO se espera a que el proceso del navegador termine. En Windows el
    navegador delega la ventana en otro proceso suyo y el que lanzamos muere al
    instante, asi que esperarlo daba dos resultados igual de malos: apagar la
    app con la ventana todavia abierta, o dejarla corriendo para siempre. Quien
    marca la vida de la app es el latido que manda la propia pagina.
    """
    if _con_pywebview(url):
        return True
    if _modo_app(url) is not None:
        return True
    webbrowser.open(url)
    return False
