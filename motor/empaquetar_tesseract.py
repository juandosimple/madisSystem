# -*- coding: utf-8 -*-
"""
Deja una copia autocontenida de Tesseract en motor/tesseract/.

En macOS el binario de Homebrew apunta a sus bibliotecas por ruta absoluta
(/opt/homebrew/...), que en otra maquina no existen. Hay que copiar el arbol de
dependencias y reescribir cada referencia a @loader_path, para que se busquen
entre ellas dentro de la carpeta.

En Windows no hace falta: los DLL se resuelven por directorio y alcanza con
copiarlos al lado del .exe (de eso se ocupa el workflow).

    python3 motor/empaquetar_tesseract.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent / "tesseract"
IDIOMAS = ("spa", "eng", "osd")
PREFIJOS = ("/opt/homebrew", "/usr/local/")   # lo de Homebrew viaja; lo del sistema no


def _dependencias(binario, vistas=None):
    """Arbol completo de bibliotecas propias, sin las del sistema."""
    vistas = vistas if vistas is not None else set()
    binario = os.path.realpath(binario)
    if binario in vistas or not os.path.exists(binario):
        return vistas
    vistas.add(binario)
    salida = subprocess.run(["otool", "-L", binario],
                            capture_output=True, text=True).stdout
    for linea in salida.splitlines()[1:]:
        ruta = linea.strip().split(" ")[0]
        if ruta.startswith(PREFIJOS):
            _dependencias(ruta, vistas)
    return vistas


def _reescribir(archivo, nombres):
    """Cambia cada ruta absoluta por @loader_path/<nombre>."""
    salida = subprocess.run(["otool", "-L", str(archivo)],
                            capture_output=True, text=True).stdout
    for linea in salida.splitlines()[1:]:
        ruta = linea.strip().split(" ")[0]
        base = os.path.basename(ruta)
        if ruta.startswith(PREFIJOS) and base in nombres:
            subprocess.run(["install_name_tool", "-change", ruta,
                            f"@loader_path/{base}", str(archivo)],
                           capture_output=True)
    if archivo.suffix == ".dylib":
        subprocess.run(["install_name_tool", "-id",
                        f"@loader_path/{archivo.name}", str(archivo)],
                       capture_output=True)
    # la firma anterior deja de valer al reescribir: se vuelve a firmar local
    subprocess.run(["codesign", "--force", "--sign", "-", str(archivo)],
                   capture_output=True)


def main():
    if sys.platform != "darwin":
        print("Este script es para macOS.")
        return 1
    origen = shutil.which("tesseract")
    if not origen:
        print("No se encontró Tesseract. Instalalo con:")
        print("  brew install tesseract tesseract-lang")
        return 1

    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    (DESTINO / "tessdata").mkdir(parents=True)

    archivos = _dependencias(origen)
    nombres = {os.path.basename(a) for a in archivos}
    for archivo in archivos:
        shutil.copy2(archivo, DESTINO / os.path.basename(archivo))

    binario = DESTINO / "tesseract"
    (DESTINO / os.path.basename(os.path.realpath(origen))).rename(binario)
    nombres.discard(os.path.basename(os.path.realpath(origen)))
    for archivo in DESTINO.glob("*"):
        if archivo.is_file():
            archivo.chmod(0o755)
            _reescribir(archivo, nombres)

    # los idiomas: solo los que se usan, no el pack entero
    tessdata = Path(subprocess.run(
        ["brew", "--prefix"], capture_output=True, text=True).stdout.strip()) / "share/tessdata"
    copiados = []
    for idioma in IDIOMAS:
        archivo = tessdata / f"{idioma}.traineddata"
        if archivo.exists():
            shutil.copy2(os.path.realpath(archivo), DESTINO / "tessdata" / archivo.name)
            copiados.append(idioma)
    # tesseract necesita estas subcarpetas para arrancar
    for sub in ("configs", "tessconfigs"):
        if (tessdata / sub).exists():
            shutil.copytree(tessdata / sub, DESTINO / "tessdata" / sub,
                            dirs_exist_ok=True)

    peso = sum(f.stat().st_size for f in DESTINO.rglob("*") if f.is_file())
    print(f"{len(archivos)} binarios + idiomas {', '.join(copiados)} "
          f"-> {DESTINO} ({peso/1e6:.1f} MB)")
    return 0 if "spa" in copiados else 1


if __name__ == "__main__":
    raise SystemExit(main())
