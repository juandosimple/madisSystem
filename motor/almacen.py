# -*- coding: utf-8 -*-
"""
Almacen local del sistema.

Principio de diseño: SQLite es la fuente de verdad, el Excel es una EXPORTACION
que se regenera completa cada vez. Nunca se le agregan filas al .xlsx a mano.
Esto evita duplicados, permite corregir un expediente viejo y elimina toda una
clase de errores de corrupcion del archivo.
"""
import json
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from extractor import COLUMNAS, _norm
from rutas import carpeta_datos

BASE = carpeta_datos()
DB = BASE / "expedientes.db"


def conectar():
    cx = sqlite3.connect(DB)
    cx.execute("""CREATE TABLE IF NOT EXISTS expedientes (
        expediente TEXT PRIMARY KEY,
        datos      TEXT NOT NULL,
        archivos   TEXT NOT NULL,
        creado     TEXT DEFAULT CURRENT_TIMESTAMP,
        editado    TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cx.execute("""CREATE TABLE IF NOT EXISTS carreras (
        clave   TEXT NOT NULL,
        carrera TEXT NOT NULL,
        PRIMARY KEY (clave, carrera))""")
    return cx


# ------------------------------------------------------ tabla de carreras ---
def tabla_carreras():
    """{ 'instituto|materia' : [carreras...] } — la clave incluye el instituto
    porque una misma materia puede dictarse en varios institutos."""
    cx = conectar()
    tabla = {}
    for clave, carrera in cx.execute("SELECT clave, carrera FROM carreras"):
        tabla.setdefault(clave, []).append(carrera)
    cx.close()
    return tabla


def aprender_carrera(instituto, materia, carrera):
    if not (instituto and materia and carrera):
        return
    cx = conectar()
    cx.execute("INSERT OR IGNORE INTO carreras VALUES (?,?)",
               (_norm(f"{instituto}|{materia}"), carrera.strip()))
    cx.commit(); cx.close()


# ---------------------------------------------------------- expedientes -----
def existe(expediente):
    cx = conectar()
    r = cx.execute("SELECT 1 FROM expedientes WHERE expediente=?",
                   (expediente,)).fetchone()
    cx.close()
    return r is not None


def guardar(expediente, valores, archivos):
    cx = conectar()
    cx.execute("""INSERT INTO expedientes (expediente, datos, archivos) VALUES (?,?,?)
                  ON CONFLICT(expediente) DO UPDATE SET
                    datos=excluded.datos, archivos=excluded.archivos,
                    editado=CURRENT_TIMESTAMP""",
               (expediente, json.dumps(valores, ensure_ascii=False),
                json.dumps(archivos, ensure_ascii=False)))
    cx.commit(); cx.close()


def listar():
    cx = conectar()
    filas = [(e, json.loads(d), json.loads(a), c)
             for e, d, a, c in cx.execute(
                 "SELECT expediente, datos, archivos, creado "
                 "FROM expedientes ORDER BY creado")]
    cx.close()
    return filas


# ------------------------------------------------------- exportar Excel -----
ENCABEZADO = PatternFill("solid", fgColor="1F3864")
REVISAR    = PatternFill("solid", fgColor="FFF2CC")   # celda vacia / sin dato


def exportar_excel(destino=None):
    """Regenera el Excel completo desde SQLite."""
    destino = Path(destino or BASE / "expedientes.xlsx")
    wb = Workbook(); ws = wb.active; ws.title = "Expedientes"

    # Los nombres de archivo se siguen guardando en SQLite para trazabilidad,
    # pero no se exportan: en el Excel no aportan.
    etiquetas = [etiqueta for _, etiqueta in COLUMNAS]
    ws.append(etiquetas)
    for i in range(1, len(etiquetas) + 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = ENCABEZADO
        c.alignment = Alignment(vertical="center", wrap_text=True)

    for _expediente, valores, _archivos, _ in listar():
        fila = [valores.get(k, "") for k, _ in COLUMNAS]
        ws.append(fila)
        r = ws.max_row
        for i, (clave, _) in enumerate(COLUMNAS, start=1):
            if not str(valores.get(clave, "")).strip():
                ws.cell(row=r, column=i).fill = REVISAR   # resaltar lo que falta

    anchos = {"Instituto": 18, "N° de expediente": 34, "Descripción": 40,
              "Materia": 42, "Carrera": 38, "Cantidad de firmas": 18}
    for i, etiqueta in enumerate(etiquetas, start=1):
        ws.column_dimensions[get_column_letter(i)].width = anchos.get(etiqueta, 16)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(destino)
    return destino
