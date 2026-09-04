# -*- coding: utf-8 -*-
"""
Servidor local del sistema. Solo libreria estandar: no instala nada.

La UI es HTML+JS a proposito: es exactamente lo que va a renderizar Tauri
cuando envolvamos esto en una app de escritorio. El frontend se reusa entero;
lo unico que cambia es quien responde del otro lado.
"""
import base64
import json
import threading
import uuid
import sys
import tempfile
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extractor import COLUMNAS, armar_expediente, _norm
from rutas import EMPAQUETADA, abrir_archivo, carpeta_datos, recurso
import almacen

# Empaquetada la app corre sin consola: sin esto, un error queda invisible y
# no hay forma de saber por que no arranco.
if EMPAQUETADA:
    _log = open(carpeta_datos() / "registro.txt", "a", encoding="utf-8",
                buffering=1)
    sys.stdout = sys.stderr = _log

RAIZ = Path(__file__).resolve().parent
PUERTO = 8765

# analisis en curso: {id: {estado, paso, resultado, error}}
TRABAJOS = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # silenciar el log de acceso

    # ---------------------------------------------------------- respuestas --
    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # --------------------------------------------------------------- rutas --
    def do_GET(self):
        if self.path.startswith("/progreso"):
            ident = self.path.partition("=")[2]
            self._json(TRABAJOS.get(ident, {"estado": "desconocido"}))
        elif self.path in ("/", "/index.html"):
            cuerpo = recurso("ui.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
        elif self.path == "/historial":
            # se mandan las columnas junto al historial: si el usuario abre un
            # expediente guardado sin haber analizado nada todavía, el
            # formulario necesita saber qué campos dibujar.
            self._json({
                "columnas": [{"clave": k, "etiqueta": e} for k, e in COLUMNAS],
                "meses": [{**mes, "titulo": almacen.nombre_hoja(mes["mes"])}
                          for mes in almacen.historial()]})
        elif self.path.startswith("/expediente"):
            consulta = urllib.parse.urlparse(self.path).query
            ident = urllib.parse.parse_qs(consulta).get("id", [""])[0]
            guardado = almacen.obtener(ident)
            self._json(guardado or {"error": "No se encontró ese expediente."})
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            if self.path == "/analizar":
                self._json(self.arrancar(self._leer_json()))
            elif self.path == "/guardar":
                self._json(self.guardar(self._leer_json()))
            elif self.path == "/eliminar":
                datos = self._leer_json()
                borrados = almacen.eliminar(datos.get("expediente", ""))
                if borrados:
                    almacen.exportar_excel()
                self._json({"ok": bool(borrados),
                            "total": len(almacen.listar())})
            elif self.path == "/abrir-excel":
                ruta = almacen.exportar_excel()
                abrir_archivo(ruta)
                self._json({"ok": True, "ruta": str(ruta)})
            else:
                self.send_error(404)
        except Exception as e:  # que un PDF roto no tumbe el servidor
            import traceback; traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ------------------------------------------------------------ acciones --
    def arrancar(self, datos):
        """Lanza el analisis en segundo plano y devuelve un identificador.

        El analisis puede tardar varios segundos (el OCR sobre todo, y mas en
        una portatil modesta). Contestar enseguida y dejar que la UI consulte
        el progreso evita que la pantalla parezca colgada.
        """
        ident = uuid.uuid4().hex[:12]
        TRABAJOS[ident] = {"estado": "trabajando", "paso": "Preparando…"}

        def tarea():
            try:
                TRABAJOS[ident]["resultado"] = self.analizar(
                    datos, lambda m: TRABAJOS[ident].update(paso=m))
                TRABAJOS[ident]["estado"] = "listo"
            except Exception as e:
                import traceback; traceback.print_exc()
                TRABAJOS[ident].update(estado="error",
                                       error=f"{type(e).__name__}: {e}")

        threading.Thread(target=tarea, daemon=True).start()
        return {"id": ident}

    def analizar(self, datos, progreso=None):
        """Recibe los PDFs del grupo y devuelve la fila propuesta."""
        tmp = Path(tempfile.mkdtemp(prefix="expediente_"))
        rutas = []
        for archivo in datos.get("archivos", []):
            destino = tmp / archivo["nombre"]
            destino.write_bytes(base64.b64decode(archivo["contenido"]))
            rutas.append(destino)

        exp = armar_expediente(rutas, almacen.tabla_carreras(),
                               progreso=progreso)
        clave = _norm(f"{exp.c('instituto').valor}|{exp.c('materia').valor}")
        clave_carrera = almacen.tabla_carreras().get(clave, [])

        return {
            "columnas": [{"clave": k, "etiqueta": e} for k, e in COLUMNAS],
            "campos": {k: {"valor": exp.c(k).valor, "estado": exp.c(k).estado,
                           "origen": exp.c(k).origen, "nota": exp.c(k).nota}
                       for k, _ in COLUMNAS},
            "documentos": [{"nombre": d.nombre, "tipo": d.tipo,
                            "paginas": d.paginas,
                            "escaneadas": d.paginas_escaneadas,
                            "firmas": d.firmas_embebidas} for d in exp.documentos],
            "avisos": exp.avisos,
            "carreras_sugeridas": clave_carrera,
            "duplicado": almacen.existe(exp.c("expediente").valor),
        }

    def guardar(self, datos):
        valores = datos["valores"]
        expediente = (valores.get("expediente") or "").strip()
        if not expediente:
            return {"error": "El expediente no tiene número. No se puede guardar "
                             "sin identificador: faltaría la carátula del grupo."}
        almacen.aprender_carrera(valores.get("instituto"), valores.get("materia"),
                                 valores.get("carrera"))
        almacen.guardar(expediente, valores, datos.get("archivos", []))
        ruta = almacen.exportar_excel()
        return {"ok": True, "ruta": str(ruta), "total": len(almacen.listar())}


class Servidor(ThreadingHTTPServer):
    """Multihilo a proposito. Con un solo hilo, las conexiones especulativas que
    abre el navegador bloquean el servidor durante ~un minuto, y ademas un OCR
    lento congelaria la interfaz."""
    allow_reuse_address = True   # evita el "Address already in use" al reiniciar
    daemon_threads = True


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PUERTO}"
    try:
        servidor = Servidor(("127.0.0.1", PUERTO), Handler)
    except OSError as e:
        # le puede pasar a cualquiera que abra la app dos veces
        print(f"\nNo se pudo iniciar: el puerto {PUERTO} ya está en uso.")
        print("Probablemente el sistema ya esté abierto en otra ventana.")
        print(f"Abrí {url} en el navegador, o cerrá la otra ventana y reintentá.\n")
        raise SystemExit(1)
    print(f"Sistema de expedientes corriendo en {url}")
    print("Cerrá esta ventana o Ctrl+C para detenerlo.")
    webbrowser.open(url)
    servidor.serve_forever()
