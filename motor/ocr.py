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
# el cese y el año/división tienen lector propio recortado, más preciso
ESENCIALES = ("carrera", "asignatura", "apellido_nombre")
CACHE = carpeta_datos() / "cache_ocr"
CACHE.mkdir(parents=True, exist_ok=True)


def disponible():
    return bool(ruta_tesseract())


def diagnostico():
    """Comprueba que tesseract se pueda EJECUTAR y tenga español.

    No alcanza con que el archivo exista: empaquetado puede faltarle una DLL y
    fallar al arrancar. Sin esta comprobacion el usuario recibiria la carrera y
    la fecha de cese vacias sin ninguna explicacion.
    """
    ruta = ruta_tesseract()
    if not ruta:
        return False, "No se encontró Tesseract."
    try:
        r = subprocess.run([ruta, "--list-langs"], capture_output=True, text=True,
                           errors="replace", stdin=subprocess.DEVNULL, timeout=30,
                           env=entorno_tesseract(), **SIN_CONSOLA)
    except OSError as e:
        return False, (f"Tesseract está en {ruta} pero no se pudo ejecutar ({e}). "
                       f"Puede faltarle una DLL.")
    except subprocess.TimeoutExpired:
        return False, f"Tesseract ({ruta}) no respondió."
    idiomas = (r.stdout or "").split()
    if "spa" not in idiomas:
        return False, (f"Tesseract funciona pero no tiene el idioma español "
                       f"(tiene: {', '.join(idiomas[1:]) or 'ninguno'}).")
    return True, f"Tesseract listo en {ruta}"


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
        try:
            r = subprocess.run(
                [ruta_tesseract(), str(png), "-", "-l", idioma, "--psm", "6"],
                capture_output=True, text=True, errors="replace",
                stdin=subprocess.DEVNULL,
                env=entorno_tesseract(), **SIN_CONSOLA)
            salida = r.stdout
        except OSError:
            salida = ""
    texto = salida or ""
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
    # el OCR deja basura al inicio del renglón (viñetas, restos del borde del
    # recuadro): exigir que empiece con la etiqueta perdía el campo entero
    "asignatura":      r"(?m)^[^\w\n]{0,6}ASIGNATURA\s*[:.]\s*(.+?)\s*$",
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
                    # algunos patrones capturan dos cosas juntas (año y división)
                    if m.re.groups > 1:
                        partes = tuple(_limpiar(g) for g in m.groups())
                        if all(partes):
                            hallazgos[campo] = partes
                            break
                        continue
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
DPI_UBICAR = 150       # solo para encontrar el rótulo, no para leer el valor


def _tsv(png, psm="6", extra=None):
    """Palabras con su posicion, para poder ubicar un rotulo en la hoja."""
    cmd = ([ruta_tesseract(), str(png), "-", "-l", "spa", "--psm", psm]
           + (extra or []) + ["tsv"])
    if not ruta_tesseract():
        return []
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", stdin=subprocess.DEVNULL,
                           env=entorno_tesseract(), **SIN_CONSOLA)
    except OSError:                       # tesseract ausente o sin permisos
        return []
    palabras = []
    # stdout puede venir vacío o nulo si tesseract falló: no se asume nada
    for linea in (r.stdout or "").splitlines()[1:]:
        p = linea.split("\t")
        if len(p) >= 12 and p[11].strip():
            palabras.append({"t": p[11].strip(), "x": int(p[6]), "y": int(p[7]),
                             "w": int(p[8]), "h": int(p[9])})
    return palabras


def _casilla_a_la_derecha(pagina, patron, ancho=1.0, alto=2.2):
    """Rectangulo con el VALOR que sigue a un rotulo del formulario.

    Se ubica el rotulo por coordenadas y se recorta lo que tiene a la derecha.
    Leer solo esa casilla es mucho mas preciso que leer la hoja entera: el mismo
    campo llegaba a leerse distinto segun la resolucion, y ademas es mas rapido.
    """
    # Ubicar el rótulo no necesita la resolución con la que después se LEE el
    # valor: los rótulos son grandes y se reconocen bien a 150, en la mitad de
    # tiempo. La precisión se juega en el recorte, no acá.
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "hoja.png"
        pix = pagina.get_pixmap(dpi=DPI_UBICAR, colorspace=fitz.csGRAY)
        pix.save(png)
        palabras = _tsv(png)

    rx = re.compile(patron, re.I)
    for i, palabra in enumerate(palabras):
        # el rotulo puede venir partido en varias palabras o pegado a la basura
        tramo = " ".join(w["t"] for w in palabras[i:i + 4])
        if not rx.search(tramo):
            continue
        m = rx.search(tramo)
        # se busca en que palabra termina el rotulo, para recortar despues de esa
        recorrido, ultima = 0, palabras[i]
        for w in palabras[i:i + 4]:
            recorrido += len(w["t"]) + 1
            ultima = w
            if recorrido >= m.end():
                break
        escala = pagina.rect.height / pix.height
        derecha = min(pix.width, ultima["x"] + ultima["w"] * (1 + ancho * 12))
        return fitz.Rect(ultima["x"] * escala,
                         (ultima["y"] - ultima["h"]) * escala,
                         derecha * escala,
                         (ultima["y"] + ultima["h"] * alto) * escala)
    return None


def _leer_recorte(pagina, casilla, dpi, permitidos):
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "casilla.png"
        pagina.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=casilla).save(png)
        for psm in ("7", "6", "11"):     # linea suelta, bloque, texto disperso
            extra = ["-c", f"tessedit_char_whitelist={permitidos}"] if permitidos else []
            texto = " ".join(w["t"] for w in _tsv(png, psm, extra))
            if texto.strip():
                yield texto


def leer_casilla(ruta_pdf, patron, permitidos, interpretar,
                 pagina="ultima", clave="casilla"):
    """Lee un campo suelto del formulario a varias resoluciones.

    Devuelve (valor, lecturas, coinciden). Se exige que dos resoluciones digan
    lo mismo: si todas difieren, el dato se informa como dudoso en vez de
    elegir una al azar.
    """
    if not disponible():
        return "", {}, False
    cache = _huella(ruta_pdf, clave, "multi")
    if cache.exists():
        try:
            g = json.loads(cache.read_text(encoding="utf-8"))
            return g["valor"], g["lecturas"], g["coinciden"]
        except (ValueError, KeyError, OSError):
            cache.unlink(missing_ok=True)

    doc = fitz.open(ruta_pdf)
    escaneadas = [i for i, p in enumerate(doc)
                  if len(p.get_text().strip()) < 200 and p.get_images(full=True)]
    if not escaneadas:
        doc.close()
        return "", {}, False

    hoja = doc[escaneadas[-1] if pagina == "ultima" else escaneadas[0]]
    casilla = _casilla_a_la_derecha(hoja, patron)
    if casilla is None:
        doc.close()
        return "", {}, False

    lecturas = {}
    for dpi in DPIS_CESE:
        for texto in _leer_recorte(hoja, casilla, dpi, permitidos):
            valor = interpretar(texto)
            if valor:
                lecturas[dpi] = valor
                break
        vistos = list(lecturas.values())
        if len(vistos) >= 2 and len(set(map(str, vistos))) == 1:
            break
    doc.close()

    if not lecturas:
        return "", {}, False
    conteo = {}
    for v in lecturas.values():
        conteo[str(v)] = conteo.get(str(v), 0) + 1
    ganadora = max(conteo, key=conteo.get)
    valor = next(v for v in lecturas.values() if str(v) == ganadora)
    resultado = (valor, lecturas, conteo[ganadora] >= 2)
    cache.write_text(json.dumps({"valor": resultado[0], "lecturas": lecturas,
                                 "coinciden": resultado[2]}), encoding="utf-8")
    return resultado


def _fecha(texto):
    return normalizar_fecha(texto)


def _anio_division(texto):
    m = re.search(r"(\d)\s*[-/ ]?\s*([A-Z0-9])\b", texto.upper())
    return list(m.groups()) if m else None


def leer_cese(ruta_pdf):
    return leer_casilla(ruta_pdf, r"FECHA\s+DEL\s+CESE", "0123456789/-.",
                        _fecha, pagina="ultima", clave="cese")


def leer_anio_division(ruta_pdf):
    """Año y división van juntos en una casilla de la primera hoja."""
    # el rótulo aparece como "AÑO/DIVISION" y también como "AÑO/DIV.:"
    return leer_casilla(ruta_pdf, r"A[ÑN]O\s*[/.]?\s*DIV",
                        "0123456789ABCDEFGH", _anio_division,
                        pagina="primera", clave="aniodiv")


def paginas_escaneadas_de(doc):
    """Indices de las paginas sin capa de texto util."""
    d = fitz.open(doc.ruta)
    idx = [i for i, p in enumerate(d)
           if len(p.get_text().strip()) < 200 and p.get_images(full=True)]
    d.close()
    return idx
