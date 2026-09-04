# -*- coding: utf-8 -*-
"""
Actualizacion desde los releases de GitHub.

Solo avisa: nada se descarga ni se instala sin que la persona lo pida. La
comprobacion corre en segundo plano y si falla no molesta a nadie, porque estas
maquinas pueden estar sin internet.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from rutas import SIN_CONSOLA, WINDOWS, carpeta_datos

MAC = sys.platform == "darwin"
from version import VERSION

REPO = "juandosimple/madisSystem"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ESPERA = 15

# De donde se acepta descargar. Sin esto, un release manipulado podria apuntar
# el instalador a cualquier servidor.
HOSTS_VALIDOS = ("github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com")


def _numeros(v):
    """'v1.2.3' -> (1, 2, 3). Lo que no sea numero se ignora."""
    return tuple(int(n) for n in re.findall(r"\d+", v or "")[:4]) or (0,)


def hay_novedad(remota, local=VERSION):
    a, b = _numeros(remota), _numeros(local)
    largo = max(len(a), len(b))
    return a + (0,) * (largo - len(a)) > b + (0,) * (largo - len(b))


def buscar():
    """Devuelve los datos de la version nueva, o None si no hay o falla."""
    try:
        pedido = urllib.request.Request(
            API, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "ExpedientesGEDO"})
        with urllib.request.urlopen(pedido, timeout=ESPERA) as r:
            datos = json.loads(r.read())
    except Exception:
        return None            # sin internet o sin releases: no es un error

    etiqueta = datos.get("tag_name", "")
    if not hay_novedad(etiqueta):
        return None

    # El archivo tiene que ser el de ESTE sistema. Sin este filtro, una Mac
    # descargaría el instalador de Windows y lo intentaría ejecutar.
    def es_mio(nombre):
        nombre = nombre.lower()
        if WINDOWS:
            return nombre.endswith(".exe") and "instalador" in nombre
        if MAC:
            return nombre.endswith(".dmg")
        return False

    instalador = next((a for a in datos.get("assets", [])
                       if es_mio(a.get("name", ""))), None)
    if not instalador:
        return None

    url = instalador.get("browser_download_url", "")
    if not url.startswith("https://") or \
            urllib.parse.urlparse(url).hostname not in HOSTS_VALIDOS:
        return None

    return {
        "version": etiqueta.lstrip("vV"),
        "actual": VERSION,
        "archivo": instalador["name"],
        "url": url,
        "tamano": instalador.get("size", 0),
        "sha256": (instalador.get("digest") or "").replace("sha256:", ""),
        "notas": (datos.get("body") or "").strip()[:600],
    }


def descargar(info, progreso=None):
    """Baja el instalador y comprueba que sea lo que dice ser."""
    destino = Path(tempfile.mkdtemp(prefix="actualizacion_")) / info["archivo"]
    resumen = hashlib.sha256()
    bajado = 0
    pedido = urllib.request.Request(
        info["url"], headers={"User-Agent": "ExpedientesGEDO"})
    with urllib.request.urlopen(pedido, timeout=60) as r, open(destino, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("tamano") or 0)
        while True:
            trozo = r.read(65536)
            if not trozo:
                break
            f.write(trozo)
            resumen.update(trozo)
            bajado += len(trozo)
            if progreso and total:
                progreso(f"Descargando la actualización… {bajado * 100 // total}%")

    if info.get("tamano") and bajado != info["tamano"]:
        raise ValueError(f"La descarga quedó incompleta ({bajado} de "
                         f"{info['tamano']} bytes).")
    if info.get("sha256") and resumen.hexdigest() != info["sha256"]:
        raise ValueError("El archivo descargado no coincide con el publicado.")
    cabecera = destino.read_bytes()[:8]
    if WINDOWS and cabecera[:2] != b"MZ":     # ejecutable de Windows
        raise ValueError("Lo descargado no es un instalador de Windows.")
    if MAC and not (cabecera[:4] in (b"koly", b"\x78\x01\x73\x0d")
                    or b"\x00" in cabecera):
        raise ValueError("Lo descargado no parece una imagen de disco de macOS.")
    return destino


def aplicar(instalador):
    """Pone en marcha la actualizacion. La app debe cerrarse enseguida para
    liberar sus archivos; de eso se encarga quien llama.

    En Windows el instalador hace todo solo. En macOS no: reemplazar un .app en
    ejecucion desde el propio .app es fragil, asi que se abre la imagen de
    disco y la persona arrastra la version nueva, que es el gesto habitual del
    sistema.
    """
    if WINDOWS:
        subprocess.Popen([str(instalador), "/SILENT", "/NORESTART"], **SIN_CONSOLA)
    elif MAC:
        subprocess.Popen(["open", str(instalador)])
    else:
        raise RuntimeError("La actualización automática no está disponible en "
                           "este sistema.")


def instruccion_final():
    """Que decirle a la persona despues de lanzar la actualizacion."""
    if MAC:
        return ("Se abrió la imagen de disco: arrastrá la aplicación nueva a "
                "Aplicaciones, reemplazando la anterior. Esta ventana se cierra.")
    return "Instalando: la aplicación se va a cerrar."
