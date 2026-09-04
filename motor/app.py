# -*- coding: utf-8 -*-
"""
Servidor local del sistema. Solo libreria estandar: no instala nada.

La UI es HTML+JS a proposito: es exactamente lo que va a renderizar Tauri
cuando envolvamos esto en una app de escritorio. El frontend se reusa entero;
lo unico que cambia es quien responde del otro lado.
"""
import base64
import json
import time
import threading
import uuid
import sys
import tempfile
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extractor import COLUMNAS, GRUPOS, armar_expediente, _norm
from rutas import EMPAQUETADA, abrir_archivo, carpeta_datos, recurso
from version import VERSION
import actualizador
import almacen
import ventana

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

# La ventana avisa cada pocos segundos que sigue abierta. Es el unico modo
# confiable de saberlo: en Windows el navegador delega la ventana en otro
# proceso y el que lanzamos termina enseguida, asi que esperar a que ese
# proceso muera dejaba la app corriendo para siempre sin ventana a la vista.
# Identificador de esta ejecucion. La pagina lo repite en cada latido y en el
# aviso de cierre: asi una ventana vieja, abierta de una ejecucion anterior, no
# puede apagar la instancia nueva al cerrarse.
SESION = uuid.uuid4().hex[:12]

LATIDO = {"ultimo": 0.0, "hubo": False}
SILENCIO_MAXIMO = 20      # segundos sin latido -> se considera cerrada
ESPERA_INICIAL = 90       # margen para que la ventana abra la primera vez
APAGAR = threading.Event()

# La comprobación de versión corre una vez al arrancar, en segundo plano: si no
# hay internet no debe demorar ni molestar.
NOVEDAD = {"buscada": False, "info": None}


def _detalle_error(e):
    """Mensaje con archivo y línea.

    Sin esto un fallo llega como "NoneType no tiene splitlines" y no hay forma
    de saber de dónde salió: el traceback completo queda en el registro, pero
    el usuario solo ve el mensaje y es lo único que puede reenviar.
    """
    import traceback
    traceback.print_exc()
    marco = traceback.extract_tb(e.__traceback__)[-1] if e.__traceback__ else None
    donde = f" [{Path(marco.filename).name}:{marco.lineno}]" if marco else ""
    return f"{type(e).__name__}: {e}{donde}"


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

    def _es_de_esta_sesion(self):
        consulta = urllib.parse.urlparse(self.path).query
        return urllib.parse.parse_qs(consulta).get("s", [""])[0] == SESION

    def _latir(self):
        if not self._es_de_esta_sesion():
            return False
        LATIDO["ultimo"] = time.time()
        LATIDO["hubo"] = True
        return True

    def _leer_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # --------------------------------------------------------------- rutas --
    def do_GET(self):
        if self.path.startswith("/progreso"):
            ident = self.path.partition("=")[2]
            self._json(TRABAJOS.get(ident, {"estado": "desconocido"}))
        elif self.path in ("/", "/index.html"):
            cuerpo = recurso("ui.html").read_text(encoding="utf-8") \
                .replace("__SESION__", SESION).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # Sin esto el navegador puede seguir mostrando la pantalla vieja
            # después de actualizar la app, y no hay forma de darse cuenta.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
        elif self.path == "/vivo":
            self._json({"app": "expedientes-gedo", "version": VERSION})
        elif self.path == "/actualizacion":
            self._json({"version": VERSION, "buscada": NOVEDAD["buscada"],
                        "novedad": NOVEDAD["info"]})
        elif self.path == "/estado":
            import ocr
            ocr_ok, ocr_detalle = ocr.diagnostico()
            self._json({
                "version": VERSION,
                "ocr": {"ok": ocr_ok, "detalle": ocr_detalle},
                "datos": str(almacen.BASE),
                "excel": str(almacen.BASE / "expedientes.xlsx"),
                "expedientes": len(almacen.listar()),
                "buscada": NOVEDAD["buscada"],
                "novedad": NOVEDAD["info"],
            })
        elif self.path.startswith("/latido"):
            self._json({"ok": self._latir()})
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
            elif self.path.startswith("/latido"):
                self._json({"ok": self._latir()})
            elif self.path == "/actualizar":
                self._json(self.actualizar())
            elif self.path.startswith("/cerrar"):
                # la ventana avisa que se está cerrando; se ignora si viene de
                # una ventana de otra ejecución, que si no apagaría esta
                if self._es_de_esta_sesion():
                    APAGAR.set()
                self._json({"ok": True})
            elif self.path == "/eliminar":
                datos = self._leer_json()
                borrados = almacen.eliminar(datos.get("expediente", ""))
                if borrados:
                    almacen.exportar_excel()
                self._json({"ok": bool(borrados),
                            "total": len(almacen.listar())})
            elif self.path == "/abrir-carpeta":
                abrir_archivo(almacen.BASE)
                self._json({"ok": True, "ruta": str(almacen.BASE)})
            elif self.path == "/buscar-actualizacion":
                # comprobación a pedido, para no depender de la del arranque
                NOVEDAD["info"] = actualizador.buscar()
                NOVEDAD["buscada"] = True
                self._json({"novedad": NOVEDAD["info"]})
            elif self.path == "/abrir-excel":
                ruta = almacen.exportar_excel()
                abrir_archivo(ruta)
                self._json({"ok": True, "ruta": str(ruta)})
            else:
                self.send_error(404)
        except Exception as e:  # que un PDF roto no tumbe el servidor
            self._json({"error": _detalle_error(e)}, 500)

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
                TRABAJOS[ident].update(estado="error", error=_detalle_error(e))

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
            "grupos": [{"titulo": t, "claves": c} for t, c in GRUPOS],
            "excel": almacen.contexto_excel(exp.c("expediente").valor),
            "campos": {k: {"valor": exp.c(k).valor, "estado": exp.c(k).estado,
                           "origen": exp.c(k).origen, "nota": exp.c(k).nota,
                           "opciones": exp.c(k).opciones}
                       for k, _ in COLUMNAS},
            "documentos": [{"nombre": d.nombre, "tipo": d.tipo,
                            "paginas": d.paginas,
                            "escaneadas": d.paginas_escaneadas,
                            "firmas": d.firmas_embebidas} for d in exp.documentos],
            "avisos": exp.avisos,
            "carreras_sugeridas": clave_carrera,
            "duplicado": almacen.existe(exp.c("expediente").valor),
        }

    def actualizar(self):
        """Baja el instalador, lo verifica, lo lanza y cierra la app."""
        info = NOVEDAD["info"]
        if not info:
            return {"error": "No hay ninguna actualización disponible."}
        ident = uuid.uuid4().hex[:12]
        TRABAJOS[ident] = {"estado": "trabajando", "paso": "Preparando la descarga…"}

        def tarea():
            try:
                archivo = actualizador.descargar(
                    info, lambda m: TRABAJOS[ident].update(paso=m))
                TRABAJOS[ident]["paso"] = "Iniciando el instalador…"
                actualizador.aplicar(archivo)
                TRABAJOS[ident].update(
                    estado="listo",
                    resultado={"ok": True,
                               "mensaje": actualizador.instruccion_final()})
                # el instalador necesita que la app suelte sus archivos
                threading.Timer(2.0, APAGAR.set).start()
            except Exception as e:
                TRABAJOS[ident].update(estado="error", error=_detalle_error(e))

        threading.Thread(target=tarea, daemon=True).start()
        return {"id": ident}

    def guardar(self, datos):
        valores = datos["valores"]
        expediente = (valores.get("expediente") or "").strip()
        if not expediente:
            return {"error": "El expediente no tiene número. No se puede guardar "
                             "sin identificador: faltaría la carátula del grupo."}
        estado = "observado" if datos.get("observado") else "ok"
        observacion = (datos.get("observacion") or "").strip()
        if estado == "observado" and not observacion:
            return {"error": "Escribí qué hay que corregir antes de marcarlo."}

        # de un expediente observado no se aprende: sus datos están en duda
        if estado == "ok":
            almacen.aprender_carrera(valores.get("instituto"),
                                     valores.get("materia"),
                                     valores.get("carrera"))
        almacen.guardar(expediente, valores, datos.get("archivos", []),
                        estado, observacion)
        ruta = almacen.exportar_excel()
        return {"ok": True, "ruta": str(ruta), "estado": estado,
                "total": len(almacen.listar(solo_ok=True)),
                "observados": len(almacen.listar()) - len(almacen.listar(solo_ok=True))}


class Servidor(ThreadingHTTPServer):
    """Multihilo a proposito. Con un solo hilo, las conexiones especulativas que
    abre el navegador bloquean el servidor durante ~un minuto, y ademas un OCR
    lento congelaria la interfaz."""
    allow_reuse_address = True   # evita el "Address already in use" al reiniciar
    daemon_threads = True


def _vigilar():
    """Apaga la app cuando la ventana deja de dar señales de vida."""
    inicio = time.time()
    while not APAGAR.is_set():
        APAGAR.wait(3)
        if APAGAR.is_set():
            return
        if LATIDO["hubo"]:
            if time.time() - LATIDO["ultimo"] > SILENCIO_MAXIMO:
                print("La ventana se cerró: apagando.")
                APAGAR.set()
        elif time.time() - inicio > ESPERA_INICIAL:
            # nunca llegó un latido: la ventana no llegó a abrir
            print("No se recibió señal de la ventana: apagando.")
            APAGAR.set()


def _ya_corriendo(url):
    """¿Hay otra instancia NUESTRA en el puerto?"""
    try:
        with urllib.request.urlopen(url + "/vivo", timeout=3) as r:
            return json.loads(r.read()).get("app") == "expedientes-gedo"
    except Exception:
        return False


def main():
    url = f"http://127.0.0.1:{PUERTO}"
    try:
        servidor = Servidor(("127.0.0.1", PUERTO), Handler)
    except OSError:
        # Una sola instancia: en vez de fallar, se le muestra la que ya está.
        if _ya_corriendo(url):
            print("El sistema ya estaba abierto: se muestra esa ventana.")
            ventana.abrir(url)
            return 0
        print(f"\nNo se pudo iniciar: el puerto {PUERTO} está ocupado por otro "
              f"programa.\nCerrá ese programa y volvé a intentar.\n")
        return 1

    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"Sistema de expedientes corriendo en {url}", flush=True)

    # queda asentado al arrancar: si el OCR no funciona en esta máquina, el
    # registro lo dice sin que haya que reproducir el problema
    import ocr
    ok, detalle = ocr.diagnostico()
    print(("OCR: " if ok else "OCR NO DISPONIBLE: ") + detalle, flush=True)
    print(f"Versión {VERSION}", flush=True)

    def _buscar_novedad():
        NOVEDAD["info"] = actualizador.buscar()
        NOVEDAD["buscada"] = True
        if NOVEDAD["info"]:
            print(f"Hay una versión nueva: {NOVEDAD['info']['version']}", flush=True)

    threading.Thread(target=_buscar_novedad, daemon=True).start()
    threading.Thread(target=_vigilar, daemon=True).start()
    try:
        ventana.abrir(url)          # ya no bloquea: la vida la marca el latido
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"No se pudo abrir la ventana ({e}); seguí en {url}", flush=True)

    try:
        while not APAGAR.wait(1):
            pass
    except KeyboardInterrupt:
        pass

    servidor.shutdown()
    print("Sistema detenido.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
