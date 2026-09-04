# -*- coding: utf-8 -*-
"""
Motor de extraccion de expedientes GEDO (GCABA) -> fila de Excel.

Un expediente = un grupo de PDFs (carátula, declaración jurada, formulario T,
dictamen). Cada campo extraido lleva un ESTADO para que la UI pueda distinguir
un dato leido del documento de uno derivado, de uno que falta.
"""
import re
import unicodedata
from dataclasses import dataclass, field, asdict

from cotejo import (consolidar, VERIFICADO, UNA_FUENTE, DISCREPANCIA,
                    REVISAR_LECTURA, n_fecha)
from pathlib import Path

import fitz  # pymupdf

# ---------------------------------------------------------------- estados ---
EXTRAIDO     = "extraido"      # leido textual del PDF
DERIVADO     = "derivado"      # calculado a partir de otro campo (DNI <- CUIL)
A_CONFIRMAR  = "a_confirmar"   # propuesto por la app, la persona valida
OCR          = "ocr"           # leido de un escaneado: SIEMPRE se verifica
NO_ENCONTRADO = "no_encontrado"


@dataclass
class Campo:
    valor: str = ""
    estado: str = NO_ENCONTRADO
    origen: str = ""   # que documento lo aporto
    nota: str = ""

    def set(self, valor, estado=EXTRAIDO, origen="", nota=""):
        self.valor, self.estado, self.origen, self.nota = valor, estado, origen, nota
        return self


# ------------------------------------------------------------- utilidades ---
def _norm(s: str) -> str:
    """minusculas sin acentos, para comparar etiquetas de forma robusta."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _limpiar(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


FECHA = r"(\d{1,2}/\d{1,2}/\d{2,4})"


def _buscar(texto, patron, grupo=1, flags=re.I):
    m = re.search(patron, texto, flags)
    return _limpiar(m.group(grupo)) if m else ""


# --------------------------------------------------- tipos de documento -----
# El titulo bajo "Hoja Adicional de Firmas" identifica el tipo sin ambiguedad.
TIPOS = [
    ("caratula",     r"Car[aá]tula Expediente"),
    ("declaracion",  r"Declaraci[oó]n jurada docente"),
    ("formulario_t", r"Form\.\s*Desig/Cese Docente"),
    ("dictamen",     r"Informe gr[aá]fico"),
]


def detectar_tipo(texto: str, nombre_archivo: str) -> str:
    for tipo, patron in TIPOS:
        if re.search(patron, texto, re.I):
            return tipo
    # respaldo por prefijo de nombre de archivo GEDO
    pref = nombre_archivo.split("-")[0].upper()
    return {"PV": "caratula", "DOCPE": "declaracion"}.get(pref, "desconocido")


# ------------------------------------------------------------- documento ----
@dataclass
class Documento:
    ruta: str
    nombre: str
    tipo: str
    texto: str
    paginas: int
    paginas_escaneadas: int
    firmas_embebidas: int
    firmante: str = ""
    firmante_cargo: str = ""
    firma_docente: str = ""
    firma_docente_fecha: str = ""
    organismo: str = ""


def leer_documento(ruta) -> Documento:
    ruta = Path(ruta)
    doc = fitz.open(ruta)
    partes, escaneadas, firmas = [], 0, 0
    for pag in doc:
        t = pag.get_text()
        partes.append(t)
        # pagina sin capa de texto util pero con una imagen que la cubre entera
        if len(t.strip()) < 200 and pag.get_images(full=True):
            escaneadas += 1
        firmas += sum(1 for w in pag.widgets() if w.field_type == 6)
    texto = "\n".join(partes)
    doc.close()

    d = Documento(
        ruta=str(ruta), nombre=ruta.name,
        tipo=detectar_tipo(texto, ruta.name),
        texto=texto, paginas=len(partes),
        paginas_escaneadas=escaneadas, firmas_embebidas=firmas,
    )

    # firmante GEDO: nombre en una linea, cargo en la siguiente
    m = re.search(
        r"(?m)^([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+){1,3})\s*\n"
        r"(Secretari[oa] de Escuela|Director[a]?(?: de \w+)?|Supervisor[a]?|Rector[a]?|"
        r"Asistente administrativ[oa]|Coordinador[a]?(?: de \w+)?)",
        texto)
    if m:
        d.firmante, d.firmante_cargo = _limpiar(m.group(1)), _limpiar(m.group(2))

    # El organismo es la linea justo antes de "MINISTERIO DE EDUCACION" en el
    # bloque de firma de GEDO. Es el ancla mas confiable: aparece igual en todos
    # los documentos del expediente, sea "IFTS Nº28" o "INST. SUPERIOR DE DEPORTES".
    m = re.search(r"(?m)^(.+)\n\s*MINISTERIO DE EDUCACION", texto)
    if m:
        d.organismo = _limpiar(m.group(1))

    # firma del docente: autenticacion miBA en la declaracion jurada
    m = re.search(r"autenticada en miBA por\s+(.+?)\s+el d[ií]a\s+" + FECHA, texto, re.I)
    if m:
        d.firma_docente, d.firma_docente_fecha = _limpiar(m.group(1)), m.group(2)
    return d


# ------------------------------------------------------- prestaciones DJ ----
# La declaracion jurada lista TODOS los cargos del docente, no solo el de este
# expediente: en un caso real aparecieron seis. Tomar el primero traia la
# materia equivocada. Hay que elegir el bloque cuya asignatura coincide con la
# del formulario de designacion.
def prestaciones_declaradas(texto_dj):
    """Divide la DJ en bloques y devuelve [{asignatura, curso, division, alta}]."""
    bloques = re.split(r"Establecimiento/Proyecto:", texto_dj)[1:]
    salida = []
    for b in bloques:
        salida.append({
            "establecimiento": _buscar(b, r"^\s*([^\n]+)"),
            "asignatura": _buscar(b, r"Asignatura:\s*([^\n]+)"),
            # ojo: si "Curso:" viene vacio, \S+ se comeria la linea siguiente
            "curso":      _buscar(b, r"(?m)^Curso:[ \t]*(\S+)[ \t]*$"),
            "division":   _buscar(b, r"(?m)^Divisi[oó]n:[ \t]*(\S+)[ \t]*$"),
            "alta":       _buscar(b, r"Fecha de Alta:\s*" + FECHA),
        })
    return salida


def elegir_prestacion(bloques, asignatura_buscada):
    """El bloque que corresponde a este expediente, por asignatura."""
    if not bloques:
        return {}
    if not asignatura_buscada:
        return bloques[0] if len(bloques) == 1 else {}
    objetivo = _norm(asignatura_buscada)
    for b in bloques:                      # coincidencia exacta normalizada
        if _norm(b["asignatura"]) == objetivo:
            return b
    for b in bloques:                      # una contiene a la otra
        a = _norm(b["asignatura"])
        if a and (a in objetivo or objetivo in a):
            return b
    return {}


# ------------------------------------------------------------ expediente ----
COLUMNAS = [
    ("instituto",   "Instituto"),
    ("expediente",  "N° de expediente"),
    ("descripcion", "Descripción"),
    ("apellido",    "Apellido"),
    ("nombre",      "Nombre"),
    ("dni",         "DNI"),
    ("materia",     "Materia"),
    ("carrera",     "Carrera"),
    ("anio",        "Año"),
    ("comision",    "Comisión"),
    ("fecha_alta",  "Fecha de alta"),
    ("fecha_cese",  "Fecha de cese/baja"),
    ("firmas",      "Cantidad de firmas"),
]


@dataclass
class Expediente:
    campos: dict = field(default_factory=lambda: {k: Campo() for k, _ in COLUMNAS})
    documentos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    def c(self, clave) -> Campo:
        return self.campos[clave]


# El cese puede llamarse distinto segun el formulario. Se busca por varias
# etiquetas y SIEMPRE se exige una fecha real al lado, para no confundirlo con
# los encabezados "Desde/Hasta" de la grilla de horarios de la DJ.
ETIQUETAS_CESE = [
    r"fecha\s+de\s+cese",
    r"toma\s+de\s+posesi[oó]n\s+y\s+cese",
    r"\bcese\b",
    r"fecha\s+de\s+baja",
    r"\bbaja\b",
    r"hasta",
]


def _buscar_cese(texto):
    for etiqueta in ETIQUETAS_CESE:
        m = re.search(etiqueta + r"[^\n\d]{0,40}" + FECHA, texto, re.I)
        if m:
            return m.group(1), _limpiar(m.group(0))
    return "", ""


def _dni_desde_cuil(cuil):
    """CUIL 20-12345678-3 -> DNI 12.345.678"""
    d = re.sub(r"\D", "", cuil or "")
    if len(d) != 11:
        return ""
    n = d[2:10].lstrip("0")
    return f"{int(n):,}".replace(",", ".") if n else ""


def armar_expediente(rutas, tabla_carreras=None, usar_ocr=True,
                     progreso=None) -> Expediente:
    tabla_carreras = tabla_carreras or {}
    avisar = progreso or (lambda *_: None)
    exp = Expediente()
    docs = []
    for i, r in enumerate(rutas, start=1):
        avisar(f"Leyendo los documentos ({i} de {len(rutas)})…")
        docs.append(leer_documento(r))
    exp.documentos = docs
    por_tipo = {}
    for d in docs:
        por_tipo.setdefault(d.tipo, []).append(d)

    dj   = (por_tipo.get("declaracion") or [None])[0]
    cara = (por_tipo.get("caratula")    or [None])[0]
    todo = "\n".join(d.texto for d in docs)

    # Cada dato se junta de TODAS las fuentes donde aparece; el valor se decide
    # despues, en cotejo.consolidar(). Un campo que dice lo mismo en tres
    # documentos distintos vale mucho mas que uno leido una sola vez.
    aportes = {}

    def aportar(clave, valor, fuente):
        if valor and str(valor).strip():
            aportes.setdefault(clave, []).append((str(valor).strip(), fuente))

    # ---------------------------------------------------- OCR del formulario
    cese_ocr = None
    leido = {}
    if usar_ocr:
        import ocr as _ocr
        formularios = por_tipo.get("formulario_t", [])
        if formularios:
            # no alcanza con que el archivo exista: hay que poder EJECUTARLO.
            # Si no, la carrera y el cese quedarían vacíos sin explicación.
            ok, detalle = _ocr.diagnostico()
            if not ok:
                exp.avisos.append(
                    f"No se pueden leer las páginas escaneadas: {detalle} "
                    f"La fecha de cese y la carrera quedan sin completar; "
                    f"cargalas a mano.")
                formularios = []
        for d in formularios:
            paginas = _ocr.paginas_escaneadas_de(d)
            if not paginas:
                continue
            hallado, error = _ocr.leer_formulario(d.ruta, paginas, avisar)
            if error:
                exp.avisos.append(error)
            for k, v in hallado.items():
                leido.setdefault(k, v)

            # El cese va aparte: se recorta su casilla en la última hoja del
            # formulario y se lee a varias resoluciones. A página completa el
            # mismo campo daba resultados distintos según el DPI.
            avisar("Leyendo las casillas del formulario…")
            fecha, lecturas, coinciden = _ocr.leer_cese(d.ruta)
            if fecha:
                cese_ocr = (fecha, lecturas, coinciden)
            # el año y la división viven en una casilla de la primera hoja y
            # con frecuencia están vacíos: leerlos recortados evita reprocesar
            # la página entera a alta resolución solo por si acaso
            par, _lect, coincide_par = _ocr.leer_anio_division(d.ruta)
            # Solo se acepta si dos resoluciones dijeron lo mismo. Una casilla
            # vacía (con un guion de "no corresponde") hace que el OCR lea los
            # bordes del recuadro como caracteres: en un caso real devolvió
            # "2/D" a 200 DPI y nada a 300 y 400. Un valor inventado es peor
            # que uno faltante.
            if par and coincide_par:
                leido.setdefault("anio_division", par)

    OCR_F = "formulario escaneado (OCR)"
    avisar("Cotejando los datos entre documentos…")

    # ------------------------------------------------------------- instituto
    # se aporta el organismo de cada documento: si los 4 dicen lo mismo, queda
    # verificado por 4 fuentes independientes.
    for d in docs:
        aportar("instituto", d.organismo, f"firma de {d.tipo}")

    # ------------------------------------------------------------ expediente
    if cara:
        aportar("expediente", _buscar(cara.texto,
                r"Expediente:\s*(EX-[\d\-\s]*-?GCABA-[A-Z0-9]+)"), "carátula")
        aportar("expediente", _buscar(cara.texto,
                r"Referencia:.*?(EX-[\d\-\s]*-?GCABA-[A-Z0-9]+)"),
                "carátula (referencia)")
        # El código de trámite es la clasificación oficial y viene siempre igual.
        # La "Descripción" libre cambia de formato entre escuelas ("ALTA DOCENTE
        # INTERINO - ..." vs "ALTA 4HS SIT3 POLITICAS ..."), así que no sirve
        # para cotejar: se guarda como contexto, no como valor.
        aportar("descripcion", _buscar(cara.texto,
                r"C[oó]digo Tr[aá]mite:\s*[A-Z0-9]+\s*-\s*([^\n]+)"), "código de trámite")

    # --------------------------------------------------- persona: nombre y DNI
    # El nombre se coteja completo porque el orden cambia entre documentos:
    # la DJ lo separa, la caratula lo escribe junto y la firma lo invierte.
    apellido_dj = nombre_dj = ""
    if dj:
        apellido_dj = _buscar(dj.texto, r"(?m)^Apellido:\s*(.+?)\s*$")
        nombre_dj   = _buscar(dj.texto, r"(?m)^Nombre:\s*(.+?)\s*$")
        if apellido_dj or nombre_dj:
            aportar("_nombre_completo", f"{apellido_dj} {nombre_dj}",
                    "declaración jurada")
        aportar("dni", _buscar(dj.texto, r"CUIL:\s*(\d{2}-\d{7,8}-\d)"),
                "declaración jurada")
    if cara:
        aportar("_nombre_completo", _buscar(cara.texto,
                r"(?:Descripci[oó]n|Motivo de Solicitud[^:]*):\s*[A-ZÁÉÍÓÚÑ ]+?-\s*"
                r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]+?)\s*-\s*CUIL"), "carátula")
        aportar("dni", _buscar(cara.texto, r"CUIL\s*(\d{2}-\d{7,8}-\d)"), "carátula")
    for d in docs:
        if d.firma_docente:
            aportar("_nombre_completo", d.firma_docente, "firma del docente (miBA)")
    aportar("_nombre_completo", leido.get("apellido_nombre"), OCR_F)

    # -------------------------------------------------------- cargo y cursada
    # La asignatura de ESTE expediente sale del formulario de designación; la
    # declaración jurada solo sirve para ubicar el bloque que le corresponde.
    aportar("materia", leido.get("asignatura"), OCR_F)
    if cara:
        aportar("materia", _buscar(cara.texto, r"Asignatura:\s*([^\n]+?)\s*(?:A[ñn]o:|$)"),
                "carátula")

    objetivo = (aportes.get("materia") or [("", "")])[0][0]
    bloques = prestaciones_declaradas(dj.texto) if dj else []
    elegida = elegir_prestacion(bloques, objetivo)
    if dj and len(bloques) > 1 and not elegida:
        exp.avisos.append(
            f"La declaración jurada declara {len(bloques)} cargos y no se pudo "
            f"determinar cuál corresponde a este expediente. Revisá materia, "
            f"año, comisión y fecha de alta a mano.")
    if elegida:
        aportar("materia", elegida["asignatura"], "declaración jurada")
        aportar("anio", elegida["curso"], "declaración jurada")
        aportar("comision", elegida["division"], "declaración jurada")
        aportar("fecha_alta", elegida["alta"], "declaración jurada")

    if leido.get("anio_division"):
        anio_ocr, division_ocr = leido["anio_division"]
        aportar("anio", anio_ocr, OCR_F)
        aportar("comision", division_ocr, OCR_F)

    if cara:
        # formato con etiquetas: "Asignatura: X Año: 1 División: A Hs: 6.00"
        aportar("anio", _buscar(cara.texto, r"A[ñn]o:\s*(\S+?)\s*(?:Divisi|$)"), "carátula")
        aportar("comision", _buscar(cara.texto, r"Divisi[oó]n:\s*(\S+?)\s*(?:Hs|Turno|$)"),
                "carátula")
        # formato condensado: "DPPL 1º 1º 6HC - 10/08/26"
        m = re.search(r"(\d{1,2})\s*[°º]\s*(\d{1,2})\s*[°º]\s*\d*\s*HC\b", cara.texto, re.I)
        if m:
            aportar("anio", m.group(1), "carátula")
            aportar("comision", m.group(2), "carátula")
        aportar("fecha_alta", _buscar(cara.texto, r"HC?\s*-\s*" + FECHA), "carátula")
    aportar("fecha_alta", leido.get("toma_posesion"), OCR_F + ", toma de posesión")
    aportar("fecha_alta", leido.get("fecha_propuesta"), OCR_F + ", fecha de propuesta")

    # ------------------------------------------------------------------ cese
    fecha_cese, contexto = _buscar_cese(todo)
    if fecha_cese:
        aportar("fecha_cese", fecha_cese, f"capa de texto ({contexto})")
    if cese_ocr:
        aportar("fecha_cese", cese_ocr[0], OCR_F + ", casilla del cese")
    else:
        aportar("fecha_cese", leido.get("fecha_cese"), OCR_F)

    # --------------------------------------------------------------- carrera
    if cara:
        # el nombre del plan suele partirse en dos renglones, hay que cruzarlos
        aportar("carrera", _buscar(cara.texto,
                r"Plan:\s*([\s\S]{3,90}?)\s*(?:-\s*Resoluci|Asignatura:|Cod |$)"),
                "carátula")
    aportar("carrera", leido.get("carrera"), OCR_F)
    inst_probable = (aportes.get("instituto") or [("", "")])[0][0]
    mat_probable  = (aportes.get("materia")   or [("", "")])[0][0]
    for opcion in tabla_carreras.get(_norm(f"{inst_probable}|{mat_probable}"), []):
        aportar("carrera", opcion, "cargado en expedientes anteriores")

    # ---------------------------------------------------------------- firmas
    # dos verificaciones independientes: los campos /Sig reales del PDF y las
    # marcas de firma que GEDO deja en el texto.
    aportar("firmas", str(sum(d.firmas_embebidas for d in docs)),
            "campos de firma del PDF")
    aportar("firmas", str(len(re.findall(r"Digitally signed by", todo))),
            "marcas de firma en el texto")

    # ============================================================ consolidar
    for clave, etiqueta in COLUMNAS:
        valor, estado, nota = consolidar(clave, aportes.get(clave, []))
        if clave == "expediente":
            valor = re.sub(r"-\s+-", "-", valor)   # el sector vacío queda como "- -"
        exp.c(clave).set(valor, estado, "", nota)

    # el nombre se validó completo; apellido y nombre heredan esa confianza
    nom_val, nom_estado, nom_nota = consolidar("_nombre_completo",
                                               aportes.get("_nombre_completo", []))
    if not apellido_dj and nom_val:
        # el formulario escribe "APELLIDO, NOMBRE"; sin coma, se asume que el
        # apellido va primero, que es la convencion de estos documentos.
        if "," in nom_val:
            izq, _, der = nom_val.partition(",")
            apellido_dj, nombre_dj = _limpiar(izq), _limpiar(der)
        else:
            partes = nom_val.split()
            apellido_dj, nombre_dj = partes[0], " ".join(partes[1:])
    for clave, valor in (("apellido", apellido_dj), ("nombre", nombre_dj)):
        if valor:
            exp.c(clave).set(valor, nom_estado, "",
                             "nombre completo " + nom_nota)

    # el DNI sale del CUIL cotejado
    cuil = exp.c("dni").valor
    dni = _dni_desde_cuil(cuil)
    if dni:
        exp.c("dni").set(dni, exp.c("dni").estado, "",
                         f"derivado del CUIL {cuil} · " + exp.c("dni").nota)

    c = exp.c("fecha_cese")
    if cese_ocr:
        _fecha, lecturas, coinciden = cese_ocr
        detalle = ", ".join(f"{dpi} DPI: {v}" for dpi, v in sorted(lecturas.items()))
        if coinciden:
            c.nota = (c.nota + f" · leído igual a dos resoluciones ({detalle})").strip(" ·")
        else:
            # no sabemos cuál es: eso no es "una sola fuente", es un conflicto
            c.estado = DISCREPANCIA
            c.nota = (c.nota + f" · LECTURA DUDOSA, cada resolución dio distinto "
                               f"({detalle})").strip(" ·")
            exp.avisos.append(
                f"La fecha de cese se leyó distinto según la resolución ({detalle}). "
                f"El escaneo no es claro: verificala contra el PDF y corregila.")
    if leido.get("motivo_cese"):
        c.nota = (c.nota + " · motivo: " + leido["motivo_cese"]).strip(" ·")

    # ================================================================ avisos
    for clave, etiqueta in COLUMNAS:
        c = exp.c(clave)
        if c.estado == DISCREPANCIA:
            exp.avisos.append(f"{etiqueta}: {c.nota}")
        elif c.estado == NO_ENCONTRADO and clave != "fecha_cese":
            exp.avisos.append(f"No se pudo extraer: {etiqueta}")
    if exp.c("fecha_cese").estado == NO_ENCONTRADO:
        exp.avisos.append(
            "No se encontró fecha de cese en ningún documento. Si el formulario "
            "tiene la sección 5- CESE vacía esto es lo esperado; si no, revisá "
            "la calidad del escaneo y cargala a mano.")
    # coherencia de fechas: apareció un expediente real con el cese anterior al
    # alta (error del formulario, no del OCR). Conviene que salte.
    alta_f, cese_f = exp.c("fecha_alta").valor, exp.c("fecha_cese").valor
    if alta_f and cese_f:
        def _clave(f):
            d, m, a = n_fecha(f).split("/")
            return (a, m, d)
        try:
            if _clave(cese_f) <= _clave(alta_f):
                exp.avisos.append(
                    f"La fecha de cese ({cese_f}) es anterior o igual a la de alta "
                    f"({alta_f}). Puede ser un error del formulario o una mala "
                    f"lectura del escaneado: verificá contra el PDF.")
        except ValueError:
            pass

    if exp.c("firmas").valor and int(exp.c("firmas").valor or 0) < 2 * len(docs):
        flojos = [d.nombre for d in docs if d.firmas_embebidas < 2]
        if flojos:
            exp.avisos.append("Documentos con menos de 2 firmas: " + ", ".join(flojos))

    avisar("Listo")
    return exp
