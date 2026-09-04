# -*- mode: python ; coding: utf-8 -*-
"""
Empaquetado con PyInstaller. Se corre SOBRE Windows (no cross-compila).

    pyinstaller motor/app.spec --noconfirm

Espera que tesseract ya este copiado en motor/tesseract/ (lo hace el workflow).
"""
from pathlib import Path

RAIZ = Path(SPECPATH)

# la interfaz y el motor de OCR viajan dentro del ejecutable
datos = [(str(RAIZ / "ui.html"), ".")]
carpeta_tess = RAIZ / "tesseract"
if carpeta_tess.exists():
    for archivo in carpeta_tess.rglob("*"):
        if archivo.is_file():
            destino = Path("tesseract") / archivo.relative_to(carpeta_tess).parent
            datos.append((str(archivo), str(destino)))

a = Analysis(
    [str(RAIZ / "app.py")],
    pathex=[str(RAIZ)],
    datas=datos,
    hiddenimports=["extractor", "almacen", "ocr", "cotejo", "rutas"],
    # PyMuPDF y openpyxl arrastran extras que no usamos y pesan
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ExpedientesGEDO",
    console=False,          # sin ventana negra: es una app, no un script
    icon=None,
)
COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,   # UPX rompe algunas DLL de tesseract
    name="ExpedientesGEDO",
)
