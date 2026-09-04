# -*- coding: utf-8 -*-
"""
Prueba de humo del OCR, para correr en la compilacion.

Comprueba que el Tesseract empaquetado funcione de punta a punta: fabrica un
PDF escaneado (texto rasterizado, sin capa de texto) que imita el Formulario T
y verifica que el motor extraiga los campos. No usa expedientes reales.

    python motor/prueba_humo.py
"""
import sys
import tempfile
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocr  # noqa: E402

TEXTO = """MINISTERIO DE EDUCACION
SOLICITUD DE DESIGNACION DE PERSONAL DOCENTE INTERINO O SUPLENTE
ESTABLECIMIENTO: I.F.T.S Nº 99
CODIGO DEL ESTABLECIMIENTO: 01230000
PLAN DE ESTUDIOS: TECNICATURA SUPERIOR EN PRUEBAS AUTOMATICAS
ASIGNATURA: MATERIA DE PRUEBA
NORMA: Res.123/MEDGC/26
3- DATOS DEL DOCENTE PROPUESTO
FECHA DE LA PROPUESTA: 01-03-26
APELLIDO Y NOMBRE: PEREZ, JUAN CARLOS SEXO: M
4- TOMA DE POSESION 5- CESE
FECHA: 01-03-26 MOTIVO DEL CESE: FIN DE CUATRIMESTRE
FECHA DEL CESE: 31-07-26
"""

ESPERADO = {
    "carrera": "TECNICATURA SUPERIOR EN PRUEBAS AUTOMATICAS",
    "asignatura": "MATERIA DE PRUEBA",
    "apellido_nombre": "PEREZ, JUAN CARLOS",
    "fecha_cese": "31/07/2026",
    "toma_posesion": "01/03/2026",
}


def pdf_escaneado(destino):
    """Un PDF cuya pagina es una imagen: sin capa de texto, como los reales."""
    doc = fitz.open()
    pagina = doc.new_page(width=595, height=842)
    pagina.insert_textbox(fitz.Rect(40, 60, 555, 700), TEXTO,
                          fontname="helv", fontsize=11, lineheight=2.0)
    imagen = pagina.get_pixmap(dpi=200)          # se rasteriza...
    doc.close()

    plano = fitz.open()
    hoja = plano.new_page(width=595, height=842)
    hoja.insert_image(hoja.rect, pixmap=imagen)  # ...y se pega como imagen
    plano.save(destino)
    plano.close()


def main():
    if not ocr.disponible():
        print("FALLA: no se encontró Tesseract")
        return 1
    print(f"Tesseract: {ocr.ruta_tesseract()}")

    with tempfile.TemporaryDirectory() as tmp:
        prueba = Path(tmp) / "formulario.pdf"
        pdf_escaneado(prueba)
        leido, error = ocr.leer_formulario(prueba, [0])

    if error:
        print(f"FALLA: {error}")
        return 1

    # el cese tiene su propio lector: recorta la casilla en la última hoja
    with tempfile.TemporaryDirectory() as tmp:
        prueba = Path(tmp) / "formulario.pdf"
        pdf_escaneado(prueba)
        fecha, lecturas, coinciden = ocr.leer_cese(prueba)
    estado = "ok" if fecha == ESPERADO["fecha_cese"] else "FALLA"
    print(f"  {estado:5s} {'cese (recortado)':18s} {fecha or '(vacío)'} "
          f"{'coincide a varias resoluciones' if coinciden else '(sin acuerdo)'}")

    fallas = []
    if fecha != ESPERADO["fecha_cese"]:
        fallas.append(f"lector de cese: esperaba {ESPERADO['fecha_cese']!r}, "
                      f"obtuvo {fecha!r} (lecturas: {lecturas})")
    for campo, esperado in ESPERADO.items():
        obtenido = leido.get(campo, "")
        estado = "ok" if obtenido == esperado else "FALLA"
        print(f"  {estado:5s} {campo:18s} {obtenido or '(vacío)'}")
        if estado == "FALLA":
            fallas.append(f"{campo}: esperaba {esperado!r}, obtuvo {obtenido!r}")

    if fallas:
        print("\nEl OCR no leyó correctamente:")
        for f in fallas:
            print("  -", f)
        return 1
    print("\nOCR verificado de punta a punta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
