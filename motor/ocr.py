# -*- coding: utf-8 -*-
"""
Lectura de las paginas escaneadas del Formulario T.

Solo se usa OCR donde es inevitable: la fecha de cese es un dato unico de cada
expediente, no se deriva ni se predice, y vive unicamente en el escaneado.

Regla: NADA de lo que sale de aca se da por cierto. Todo vuelve marcado como
"ocr" para que la persona lo verifique contra el PDF antes de exportar.
"""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import fitz

from rutas import SIN_CONSOLA, carpeta_datos, entorno_tesseract, ruta_tesseract

# 200 DPI en escala de grises: mismo resultado que 300 a color, 35% mas rapido
# y 6.8x menos pixeles en memoria (9.5M vs 64.4M). A 150 DPI se pierde la fecha
# de toma de posesion, asi que 200 es el piso. Medido sobre el Formulario T.
DPI = 200
DPI_REINTENTO = 300   # solo si falto algo esencial: cuesta ~50% mas de tiempo
GRIS = True

# si alguno de estos falta tras el primer intento, vale la pena reintentar mas
# fino: en un escaneo flojo la fecha de cese se lee a 300 y no a 200 (ni a 400).
# fecha_cese no está acá: tiene su propio lector recortado, más preciso
ESENCIALES = ("carrera", "asignatura", "apellido_nombre")
CACHE = carpeta_datos() / "cache_ocr"
CACHE.mkdir(parents=True, exist_ok=True)


def disponible():
    return bool(ruta_tesseract())


def _huella(ruta, pagina, dpi):
    h = hashlib.sha1(Path(ruta).read_bytes()).hexdigest()[:16]
    return CACHE / f"{h}_p{pagina}_{dpi}.txt"


def ocr_pagina(ruta_pdf, pagina, idioma="spa", dpi=DPI):
    """OCR de una pagina, cacheado en disco (es lento: ~2-4s por pagina)."""
    cache = _huella(ruta_pdf, pagina, dpi)
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    if not disponible():
        return ""

    doc = fitz.open(ruta_pdf)
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "pag.png"
        pix = doc[pagina].get_pixmap(
            dpi=dpi, colorspace=fitz.csGRAY if GRIS else fitz.csRGB)
        pix.save(png)
        del pix
        doc.close()
        r = subprocess.run(
            [ruta_tesseract(), str(png), "-", "-l", idioma, "--psm", "6"],
            capture_output=True, text=True, env=entorno_tesseract(),
            **SIN_CONSOLA)
    texto = r.stdout or ""
    cache.write_text(texto, encoding="utf-8")
    return texto


# ----------------------------------------------------------------- fechas ---
def normalizar_fecha(bruto):
    """15-02-27 / 15/2/27 -> 15/02/2027"""
    m = re.search(r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{2,4})", bruto or "")
    if not m:
        return ""
    d, mes, a = m.groups()
    if len(a) == 2:
        a = "20" + a
    return f"{int(d):02d}/{int(mes):02d}/{a}"


# ------------------------------------------------------------- extraccion ---
# Cada patron esta anclado en su etiqueta COMPLETA. En la seccion inferior del
# formulario las columnas "4- TOMA DE POSESION" y "5- CESE" quedan en el mismo
# renglon de OCR, asi que buscar "FECHA" suelto traeria el dato equivocado.
PATRONES = {
    "carrera":       r"PLAN\s+DE\s+ESTUDIOS\s*[:.]?\s*(.+?)\s*$",
    # entre la etiqueta y el valor el OCR mete los bordes del recuadro como
    # "[", "|" o "_": hay que saltearlos para llegar a la fecha.
    "fecha_cese":    r"FECHA\s+DEL\s+CESE\s*[:.]?[\s|\[\]_]*([\d\s\-/.]{6,12})",
    "motivo_cese":   r"MOTIVO\s+DEL\s+CESE\s*[:.]?\s*(.+?)(?:\s+FECHA|\s*$)",
    # el rótulo "4- TOMA DE POSESION" y su FECHA caen en renglones distintos:
    # hay que cruzar el salto de línea, pero acotado para no irse de sección.
    "toma_posesion": r"TOMA\s+DE\s+POSESI[OÓ]N[\s\S]{0,60}?FECHA\s*[:.]?[\s|\[\]_]*([\d\s\-/.]{6,12})",
    "norma":         r"NORMA\s*[:.]?\s*(Res\.?\s*[\w/.\-]+)",
    # segundas fuentes: sirven para cotejar contra la capa de texto
    # OJO: "APELLIDO Y NOMBRE" aparece 4 veces en el formulario. Tres son de
    # CAMPO A/B/C (el docente al que se REEMPLAZA) y en un expediente de baja
    # vienen llenas con OTRA persona. La que sirve es la de la seccion 3.
    "apellido_nombre": r"DOCENTE\s+PROPUESTO[\s\S]{0,400}?APELLIDO\s+Y\s+NOMBRE"
                       r"\s*[:.]?\s*(.+?)\s+SEXO",
    "asignatura":      r"(?m)^\s*ASIGNATURA\s*[:.]\s*(.+?)\s*$",
    "fecha_propuesta": r"FECHA\s+DE\s+LA\s+PROPUESTA\s*[:.]?[\s|\[\]_]*([\d\s\-/.]{6,12})",
    "codigo_estab":  r"CODIGO\s+DEL\s+ESTABLECIMIENTO\s*[:.]?\s*(\d{4,10})",
}
CAMPOS_FECHA = {"fecha_cese", "toma_posesion", "fecha_propuesta"}


def _limpiar(v):
    v = re.sub(r"[|_]+", " ", v or "")
    v = re.sub(r"\s+", " ", v).strip(" .:-\u2013\u2014")
    # El OCR deja una letra suelta al final de las lineas de formulario (los
    # bordes de los recuadros se leen como caracteres). Cubre acentuadas y Ñ.
    return re.sub(r"\s+[^\W\d_]$", "", v).strip()


def leer_formulario(ruta_pdf, paginas_escaneadas, progreso=None):
    """Devuelve {campo: valor} de lo que se pudo leer del formulario escaneado."""
    if not disponible():
        return {}, "Tesseract no está instalado: no se pueden leer las páginas escaneadas."

    # Se procesa pagina por pagina y se corta apenas estan todos los campos:
    # en una portatil modesta cada pagina de mas cuesta ~2 segundos.
    def barrer(dpi, etiqueta):
        hallazgos, texto = {}, ""
        for i, numero in enumerate(paginas_escaneadas, start=1):
            if progreso:
                progreso(f"Reconociendo texto del formulario escaneado{etiqueta} "
                         f"(página {i} de {len(paginas_escaneadas)})…")
            texto += "\n" + ocr_pagina(ruta_pdf, numero, dpi=dpi)
            for campo, patron in PATRONES.items():
                if campo in hallazgos:
                    continue
                # se recorren TODAS las coincidencias y se toma la primera con
                # contenido: los formularios repiten rotulos con casillas vacias.
                for m in re.finditer(patron, texto, re.I | re.M):
                    valor = _limpiar(m.group(1))
                    if campo in CAMPOS_FECHA:
                        valor = normalizar_fecha(valor)
                    if valor:
                        hallazgos[campo] = valor
                        break
            if len(hallazgos) == len(PATRONES):
                break
        return hallazgos

    hallazgos = barrer(DPI, "")
    if any(c not in hallazgos for c in ESENCIALES):
        # segundo intento mas fino, solo por lo que falta
        for campo, valor in barrer(DPI_REINTENTO, " con más detalle").items():
            hallazgos.setdefault(campo, valor)
    return hallazgos, ""


# ---------------------------------------------------------- fecha de cese ---
# El cese esta siempre en la ultima pagina del formulario "Solicitud de
# personal docente". Leerlo con el resto de la pagina lo vuelve poco confiable:
# a pagina completa el mismo campo se leyo "15/2/2026" a 200 DPI y "15/2/2028"
# a 300. Recortando solo la casilla el resultado es estable y ademas mas rapido.
DPIS_CESE = (200, 300, 400)


def _tsv(png, psm="6", extra=None):
    """Palabras con su posicion, para poder ubicar un rotulo en la hoja."""
    cmd = ([ruta_tesseract(), str(png), "-", "-l", "spa", "--psm", psm]
           + (extra or []) + ["tsv"])
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=entorno_tesseract(), **SIN_CONSOLA)
    palabras = []
    for linea in r.stdout.splitlines()[1:]:
        p = linea.split("\t")
        if len(p) >= 12 and p[11].strip():
            palabras.append({"t": p[11].strip(), "x": int(p[6]), "y": int(p[7]),
                             "w": int(p[8]), "h": int(p[9])})
    return palabras


def _casilla_del_cese(pagina):
    """El rectangulo a la derecha de 'FECHA DEL CESE:', donde va el valor."""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "hoja.png"
        pix = pagina.get_pixmap(dpi=300, colorspace=fitz.csGRAY)
        pix.save(png)
        palabras = _tsv(png)
    for i in range(len(palabras) - 2):
        if (palabras[i]["t"].upper().startswith("FECHA")
                and palabras[i + 1]["t"].upper().startswith("DEL")
                and palabras[i + 2]["t"].upper().startswith("CESE")):
            a = palabras[i + 2]
            escala = pagina.rect.height / pix.height
            return fitz.Rect(a["x"] * escala, (a["y"] - a["h"]) * escala,
                             pix.width * escala, (a["y"] + a["h"] * 2.2) * escala)
    return None


def _fecha_en_casilla(pagina, casilla, dpi):
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "casilla.png"
        pagina.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=casilla).save(png)
        for psm in ("7", "6", "11"):     # linea suelta, bloque, texto disperso
            texto = " ".join(w["t"] for w in _tsv(
                png, psm, ["-c", "tessedit_char_whitelist=0123456789/-."]))
            fecha = normalizar_fecha(texto)
            if fecha:
                return fecha
    return ""


def leer_cese(ruta_pdf):
    """Devuelve (fecha, lecturas, coinciden).

    Se lee la misma casilla a varias resoluciones y se exige acuerdo: si dos
    resoluciones distintas dicen lo mismo, el dato es confiable; si todas
    difieren, se avisa en vez de elegir una al azar.
    """
    cache = _huella(ruta_pdf, "cese", "multi")
    if cache.exists():
        guardado = json.loads(cache.read_text(encoding="utf-8"))
        return guardado["fecha"], guardado["lecturas"], guardado["coinciden"]

    doc = fitz.open(ruta_pdf)
    escaneadas = [i for i, p in enumerate(doc)
                  if len(p.get_text().strip()) < 200 and p.get_images(full=True)]
    if not escaneadas:
        doc.close()
        return "", {}, False

    pagina = doc[escaneadas[-1]]          # el cese va en la última hoja
    casilla = _casilla_del_cese(pagina)
    if casilla is None:
        doc.close()
        return "", {}, False

    lecturas = {}
    for dpi in DPIS_CESE:
        fecha = _fecha_en_casilla(pagina, casilla, dpi)
        if fecha:
            lecturas[dpi] = fecha
        # con dos resoluciones de acuerdo alcanza: no se sigue gastando tiempo
        valores = list(lecturas.values())
        if len(valores) >= 2 and len(set(valores)) == 1:
            break
    doc.close()

    if not lecturas:
        return "", {}, False
    conteo = {}
    for fecha in lecturas.values():
        conteo[fecha] = conteo.get(fecha, 0) + 1
    ganadora = max(conteo, key=conteo.get)
    resultado = (ganadora, lecturas, conteo[ganadora] >= 2)
    cache.write_text(json.dumps({"fecha": resultado[0], "lecturas": lecturas,
                                 "coinciden": resultado[2]}), encoding="utf-8")
    return resultado


def paginas_escaneadas_de(doc):
    """Indices de las paginas sin capa de texto util."""
    d = fitz.open(doc.ruta)
    idx = [i for i, p in enumerate(d)
           if len(p.get_text().strip()) < 200 and p.get_images(full=True)]
    d.close()
    return idx
