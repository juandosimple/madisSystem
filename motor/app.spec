# -*- mode: python ; coding: utf-8 -*-
"""
Empaquetado con PyInstaller. Se corre SOBRE Windows (no cross-compila).

    pyinstaller motor/app.spec --noconfirm

Espera que tesseract ya este copiado en motor/tesseract/ (lo hace el workflow).
"""
import re
import sys
from pathlib import Path

RAIZ = Path(SPECPATH)

# la version que sella el workflow, para que el .app la muestre en Finder
try:
    VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"',
                        (RAIZ / "version.py").read_text()).group(1)
except Exception:
    VERSION = "0.0.0"

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
    hiddenimports=["extractor", "almacen", "ocr", "cotejo", "rutas",
                   "ventana", "actualizador", "version"],
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
coleccion = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,   # UPX rompe algunas DLL de tesseract
    name="ExpedientesGEDO",
)

# En macOS el resultado tiene que ser un .app, no una carpeta suelta: es lo
# unico que el Finder abre con doble clic y lo que espera un .dmg.
if sys.platform == "darwin":
    app = BUNDLE(
        coleccion,
        name="Expedientes GEDO.app",
        icon=None,
        bundle_identifier="ar.gob.buenosaires.expedientes-gedo",
        info_plist={
            "CFBundleName": "Expedientes GEDO",
            "CFBundleDisplayName": "Expedientes GEDO",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            # no aparece en el Dock como app de fondo; abre su ventana normal
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
