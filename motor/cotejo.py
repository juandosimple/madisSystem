# -*- coding: utf-8 -*-
"""
Cotejo de un mismo dato entre documentos distintos.

Cada campo junta candidatos de todas las fuentes donde aparece y recien despues
se decide el valor. Un dato que dice lo mismo en la declaracion jurada, en la
caratula y en el formulario escaneado vale mucho mas que uno leido una sola vez.

Estados que devuelve:
  verificado    dos o mas fuentes independientes coinciden
  una_fuente    aparece en un solo lugar: no se pudo contrastar
  revisar_lectura  el escaneado se leyo casi igual que el texto digital: se
                   toma el digital y se avisa del posible error de OCR
  discrepancia  las fuentes se contradicen: decide la persona
"""
import difflib
import re
import unicodedata

VERIFICADO   = "verificado"
UNA_FUENTE   = "una_fuente"
DISCREPANCIA = "discrepancia"
REVISAR_LECTURA = "revisar_lectura"
NO_ENCONTRADO = "no_encontrado"


def _sin_acentos(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


# --------------------------------------------------------- normalizadores ---
# Comparar en bruto daria falsos negativos: "10/08/2026" y "10-08-26" son la
# misma fecha, y "VERÓNICA" y "VERONICA" el mismo nombre.
def n_texto(v):
    return re.sub(r"\s+", " ", _sin_acentos(v).upper()).strip(" .:-")


def n_fecha(v):
    m = re.search(r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{2,4})", v or "")
    if not m:
        return n_texto(v)
    d, mes, a = m.groups()
    return f"{int(d):02d}/{int(mes):02d}/{'20'+a if len(a)==2 else a}"


def n_digitos(v):
    return re.sub(r"\D", "", v or "")


def n_orden(v):
    """1, 1º, 1°, 01 -> 1"""
    d = re.sub(r"\D", "", v or "")
    return str(int(d)) if d else n_texto(v)


def n_instituto(v):
    """'IFTS Nº28' y 'IFTS 28 EX ANEXO IFTS 22 (297)...' son el mismo instituto.

    Si no es un IFTS (hay institutos con nombre propio, como el Superior de
    Deportes), se compara por palabras significativas para que 'INST. SUPERIOR
    DE DEPORTES' y 'INSTITUTO SUPERIOR DE DEPORTE' no se lean como distintos.
    """
    # ojo: NFKD convierte "º" en "o", asi que "Nº28" llega aca como "No28"
    plano = _sin_acentos(v or "")
    m = re.search(r"\b(?:IFTS|I\.?F\.?T\.?S\.?)\s*N?[°ºo]?\s*(\d+)", plano, re.I)
    if m:
        return f"IFTS {int(m.group(1))}"
    # palabras significativas, sin plurales ni abreviaturas ni domicilio
    vacias = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "NRO", "AV", "AREA",
              "EDUCACION", "SUPERIOR", "INST", "INSTITUTO"}
    palabras = [p.rstrip("S") for p in re.findall(r"[A-ZÑ]{3,}", n_texto(plano))
                if p not in vacias]
    return " ".join(sorted(set(palabras))) or n_texto(v)


def n_nombre(v):
    """Compara nombres como conjunto de palabras.

    Hay que ignorar el orden y la puntuacion: la DJ separa apellido y nombre,
    la caratula los escribe juntos, la firma miBA los invierte y el formulario
    usa 'APELLIDO, NOMBRE'. Sin sacar la coma, 'PEREZ,' no coincide con 'PEREZ'.
    """
    limpio = re.sub(r"[,.;:]+", " ", n_texto(v))
    palabras = [p for p in re.split(r"\s+", limpio) if len(p) > 1]
    return " ".join(sorted(palabras))


NORMALIZADOR = {
    "instituto":    n_instituto,
    "expediente":   n_texto,
    "dni":          n_digitos,
    "anio":         n_orden,
    "comision":     n_orden,
    "fecha_alta":   n_fecha,
    "fecha_cese":   n_fecha,
    "firmas":       n_digitos,
    "_nombre_completo": n_nombre,
}


def normalizar(clave, valor):
    return NORMALIZADOR.get(clave, n_texto)(valor)


# ------------------------------------------------------------ consolidar ----
# Los nombres se comparan por subconjunto: la declaracion jurada suele omitir
# el segundo nombre ("CRISTIAN") mientras el formulario y la firma lo traen
# ("CRISTIAN PABLO"). Uno mas corto no contradice a uno mas largo; gana el mas
# completo. Un apellido distinto si es una contradiccion real y se marca.
def _consolidar_nombre(fuentes):
    conjuntos = [(set(n_nombre(v).split()), v, d) for v, d in fuentes]
    completo = max(conjuntos, key=lambda c: len(c[0]))
    compatibles = [c for c in conjuntos if c[0] <= completo[0]]
    incompatibles = [c for c in conjuntos if c not in compatibles]

    if incompatibles:
        otras = "; ".join(f"{v!r} según {d}" for _, v, d in incompatibles)
        return completo[1], DISCREPANCIA, (
            f"NO COINCIDEN — {completo[1]!r} según "
            f"{', '.join(d for _, _, d in compatibles)}; {otras}. "
            f"Revisá los PDFs y dejá el correcto.")

    donde = [d for _, _, d in compatibles]
    parciales = [d for c, _, d in compatibles if c < completo[0]]
    nota = "coincide en " + ", ".join(donde)
    if parciales:
        nota += f" (en {', '.join(parciales)} figura sin el nombre completo)"
    return (completo[1], VERIFICADO if len(compatibles) >= 2 else UNA_FUENTE, nota)


def opciones_de(clave, fuentes):
    """Los valores distintos en juego, con quien dice cada uno.

    La persona tiene que poder elegir cual va al Excel: la app no debe decidir
    por ella cuando dos documentos se contradicen.
    """
    fuentes = [(v, d) for v, d in fuentes if str(v).strip()]
    grupos = {}
    for valor, de_donde in fuentes:
        grupos.setdefault(normalizar(clave, valor), []).append((valor, de_donde))
    return [{"valor": g[0][0], "fuentes": [d for _, d in g]}
            for _, g in sorted(grupos.items(), key=lambda kv: -len(kv[1]))]


def consolidar(clave, fuentes):
    """fuentes: [(valor, de_donde)] -> (valor, estado, nota)"""
    fuentes = [(v, d) for v, d in fuentes if str(v).strip()]
    if not fuentes:
        return "", NO_ENCONTRADO, ""
    if clave == "_nombre_completo":
        return _consolidar_nombre(fuentes)

    grupos = {}
    for valor, de_donde in fuentes:
        grupos.setdefault(normalizar(clave, valor), []).append((valor, de_donde))

    # el valor que gana es el mas repetido; ante empate, el primero que llego
    orden = sorted(grupos.items(), key=lambda kv: -len(kv[1]))
    (_, principal), *resto = orden
    valor = principal[0][0]
    donde = [d for _, d in principal]

    if resto:
        otras = "; ".join(f"{g[0][0]!r} según {', '.join(d for _, d in g)}"
                          for _, g in resto)
        # Si la unica fuente que difiere es el OCR y ademas dice casi lo mismo,
        # es un error de lectura del escaneado, no una contradiccion entre
        # documentos. Reservar el rojo para lo segundo evita que la persona se
        # acostumbre a ignorar la alarma.
        solo_ocr = all("OCR" in d for _, g in resto for _, d in g)
        digital  = all("OCR" not in d for d in donde)
        parecido = all(difflib.SequenceMatcher(
                        None, normalizar(clave, valor), k).ratio() >= 0.80
                       for k, _ in resto)
        if solo_ocr and digital and parecido:
            return valor, REVISAR_LECTURA, (
                f"El escaneado se leyó distinto ({otras}). Se tomó {valor!r} de "
                f"{', '.join(donde)}, que es texto digital. Verificá cuál va.")
        return valor, DISCREPANCIA, (
            f"NO COINCIDEN — {valor!r} según {', '.join(donde)}; {otras}. "
            f"Revisá los PDFs y dejá el correcto.")

    if len(principal) >= 2:
        return valor, VERIFICADO, "coincide en " + ", ".join(donde)
    return valor, UNA_FUENTE, "único origen: " + donde[0] + " (no se pudo contrastar)"
