# Sistema de expedientes GEDO → Excel

## Cómo se usa
Doble clic en **Iniciar sistema.command** (macOS), **Iniciar sistema.bat**
(Windows) o `python3 motor/app.py`. Se abre como una ventana de aplicación:
sin barra de direcciones ni pestañas, con su ícono propio. **Cerrando esa
ventana se cierra el sistema.**

Flujo: soltás los PDFs de UN expediente → revisás la fila → "Extraer datos a Excel".

## Qué hay acá
    motor/extractor.py   lee los PDFs, detecta el tipo y extrae los campos
    motor/ocr.py         lee las paginas escaneadas del Formulario T (cacheado)
    motor/cotejo.py      compara un mismo dato entre documentos distintos
    motor/almacen.py     SQLite (fuente de verdad) + exportación a Excel
    motor/app.py         servidor local
    motor/ui.html        la pantalla (se reusa tal cual en Tauri)
    motor/ventana.py     abre la interfaz como ventana de app, no como pestaña
    datos/               la base y el Excel generado
    ejemplos/            PDFs de prueba

## Actualización remota

Al abrir, la app consulta el último release de GitHub en segundo plano. Si hay
una versión más nueva, aparece un punto amarillo sobre el engranaje; la
actualización se hace desde **Ajustes**, con un botón. Nada se descarga ni se
instala sin que la persona lo pida, y sin internet no pasa nada.

En Ajustes también se ve la versión, si el OCR está funcionando y dónde se
guardan los datos, con accesos para abrir esa carpeta y el Excel.

Al aceptar, se baja el instalador, se comprueba **tamaño, sha256 y que sea
realmente un ejecutable de Windows**, se lanza en modo silencioso y la app se
cierra sola para liberar sus archivos. Los expedientes cargados y el Excel
viven en otra carpeta y no se tocan.

Requiere que **el repositorio sea público**: los releases de un repositorio
privado no se pueden descargar sin credenciales, y meter un token dentro de la
app lo dejaría al alcance de cualquiera que la tenga.

La versión no se escribe a mano: el workflow la sella en `motor/version.py` al
compilar, con el mismo número del release. Así lo que muestra la app y lo que
se publicó no pueden separarse.

## Historial y archivo por mes

Cada expediente guardado queda en el historial, agrupado por **mes de
importación** (cuándo se cargó, no la fecha del trámite). Desde el botón
*Ver historial* se puede abrir uno para corregirlo o quitarlo.

El Excel tiene una hoja **Todos** con el historial completo y una columna
*Importado*, más **una hoja por mes**, de la más reciente a la más vieja.

Corregir un expediente NO cambia su mes: sigue archivado donde se cargó.

## Decisiones de diseño
- **La ventana avisa que sigue viva, y eso decide cuándo apagar.** La página
  manda un latido cada 5 segundos y un aviso al cerrarse. Vigilar el proceso
  del navegador no sirve: en Windows delega la ventana en otro proceso suyo y
  el que se lanzó muere al instante, así que o se apagaba la app con la ventana
  abierta o quedaba corriendo para siempre sin ventana (un proceso fantasma en
  el Administrador de tareas). Cierre normal: se apaga al instante. Si el
  navegador se cuelga: a los 20 segundos sin latido.
- **Una sola instancia.** Si el puerto ya está tomado por el sistema, no se
  levanta un segundo servidor: se abre una ventana contra el que ya corre.
- **Ventana de aplicación sin dependencias nuevas.** Se usa el modo `--app` del
  navegador (Edge viene con Windows), que da una ventana sin barra de
  direcciones ni pestañas y con su ícono en la barra de tareas. pywebview daría
  una ventana nativa de verdad, pero empaquetarlo en Windows arrastra pythonnet
  y suma peso y fragilidad al instalador; si está instalado se usa, y si no
  se cae al modo `--app`. El navegador corre con un perfil propio, aislado de
  la navegación personal y con la actividad de fondo apagada.
- **SQLite manda, el Excel se regenera entero.** Nunca se le agregan filas al
  .xlsx. Así los duplicados, las correcciones, el borrado y las hojas por mes
  salen gratis.
- **Las fechas se guardan en hora local, no UTC.** CURRENT_TIMESTAMP de SQLite
  devuelve UTC: con el huso argentino, un expediente cargado el día 30 a las
  22:00 quedaría archivado en el mes siguiente.
- **Cada dato se coteja entre documentos.** No se lee una vez: se junta de todas
  las fuentes donde aparece y recién después se decide. El estado resultante es
  `verificado` (2+ fuentes coinciden), `una_fuente` (no se pudo contrastar) o
  `discrepancia` (los documentos se contradicen: decide la persona).
  Sobre el expediente de ejemplo, 12 de 13 campos quedan verificados.
- El único dato sin segunda fuente es la **fecha de cese**: existe solo en la
  sección 5 del formulario escaneado. Se informa como tal, no se disimula.
- **La fecha de cese se lee aparte.** Está siempre en la última hoja del
  formulario "Solicitud de personal docente". En vez de OCRear la página
  entera, se ubica el rótulo "FECHA DEL CESE" por coordenadas, se recorta solo
  su casilla y se la lee a 200, 300 y 400 DPI hasta que dos coincidan. A página
  completa el mismo campo daba "15/2/2026" a 200 DPI y "15/2/2028" a 300; con
  el recorte da estable, y encima tarda menos. Si ninguna resolución coincide
  con otra, el campo se marca en rojo con las lecturas obtenidas.
- **La declaración jurada lista TODOS los cargos del docente**, no solo el de
  este expediente (se vio un caso con seis). Hay que elegir el bloque cuya
  asignatura coincide con la del formulario de designación. Tomar el primero
  trae la materia, el año y la fecha de otro cargo.
- **OCR con reintento adaptativo**: primero 200 DPI; si falta algo esencial, se
  reintenta a 300 solo para lo que falta. El reintento nunca pisa un valor ya
  leído, porque a veces la lectura fina es la equivocada (se vio 300 DPI
  inventando un año que a 200 salía bien).
- **Controles de coherencia**: el cese no puede ser anterior al alta, y la toma
  de posesión debería coincidir con la fecha de alta. Ambos avisan.
- **OCR solo donde es inevitable.** 11 columnas salen de la capa de texto. La
  fecha de cese y la carrera viven unicamente en el Formulario T escaneado, asi
  que se leen con Tesseract y vuelven marcadas como "verificá": nunca se dan por
  ciertas. Se OCRea solo el Formulario T, no el dictamen.
- **Control cruzado de fechas.** La toma de posesion del formulario deberia
  coincidir con la fecha de alta de la declaracion jurada. Si no, avisa.
- **Las firmas se verifican de verdad**: campos /Sig reales del PDF, más el
  firmante GEDO y la autenticación miBA del docente.

## Rendimiento (pensado para portátil Windows modesta)
Medido sobre un expediente completo de 4 PDFs con 6 páginas escaneadas:

    primera vez   2.1 s        RAM pico   118 MB
    ya cacheado   0.0 s

- OCR a **200 DPI en escala de grises**. Da los mismos campos que 300 DPI a
  color, 35% más rápido y con 6.8x menos píxeles en memoria (9.5M vs 64.4M).
  A 150 DPI se pierde la fecha de toma de posesión, así que 200 es el piso.
- Se OCRea **solo el Formulario T**, no el dictamen, y se corta apenas están
  todos los campos.
- El resultado del OCR queda **cacheado en disco** por huella del archivo:
  reprocesar el mismo expediente es instantáneo.
- Al empaquetar para Windows alcanza con `tesseract.exe` + `spa.traineddata`
  (2.2 MB). NO hace falta el pack completo de idiomas (685 MB).

## Requisitos
- Python 3.11+ con `pymupdf` y `openpyxl`
- **Tesseract** con el idioma español (`brew install tesseract tesseract-lang`).
  Sin Tesseract el sistema igual funciona, pero deja la fecha de cese y la
  carrera sin completar, y lo avisa.

## Compilar (Windows y macOS)

PyInstaller no cross-compila: empaqueta el intérprete y las librerías nativas
del sistema donde corre, así que cada plataforma se compila en la suya. GitHub
lo hace gratis en paralelo:

    git init
    git add -A
    git commit -m "Sistema de expedientes GEDO"
    git remote add origin https://github.com/USUARIO/REPO.git
    git push -u origin main

Después, en la pestaña **Actions** del repositorio → *Instalador Windows* →
**Run workflow**. El campo *Versión* viene con `1.0.0` por defecto, así que
ejecutarlo sin tocar nada ya publica un **Release** con el instalador y el .zip
portable adjuntos.

Si se vacía ese campo, solo quedan *artifacts*: están al pie de la página de la
corrida, caducan a los 90 días y NO aparecen en la solapa Releases. El resumen
de cada corrida dice cuál de las dos cosas pasó.

El release se publica ANTES de subir los artifacts, y los artifacts no pueden
voltear la corrida: el servicio de artifacts de GitHub falla por timeout cada
tanto, y una falla de red ahí no tiene por qué costar el entregable.

Volver a ejecutar con una versión ya publicada reemplaza los archivos de ese
release en lugar de fallar.

También se dispara empujando una etiqueta:

    git tag v1.0.0 && git push --tags

Son tres trabajos: uno compila en Windows, otro en macOS y el tercero publica
el release con los dos resultados. Cada uno empaqueta Tesseract dentro de la
app (solo español, inglés y OSD), corre la prueba de OCR **contra el Tesseract
empaquetado**, arranca el ejecutable y verifica que responda antes de publicar.

En macOS hay un paso extra: el binario de Homebrew apunta a sus bibliotecas por
ruta absoluta, que en otra máquina no existen. `motor/empaquetar_tesseract.py`
copia el árbol de dependencias y reescribe cada referencia a `@loader_path`,
dejándolo autocontenido. Verificado corriendo con un entorno vacío, sin
Homebrew en el camino.

**Ninguno de los dos está firmado.** En Windows aparece la advertencia de
SmartScreen; en macOS, Gatekeeper exige abrirla la primera vez con clic derecho
→ *Abrir*. Firmar requiere un certificado de código en Windows y una cuenta de
desarrollador de Apple (paga) en macOS.

Archivos involucrados:

    .github/workflows/windows.yml   el que compila en GitHub
    motor/app.spec                  qué entra en el ejecutable
    instalador.iss                  el instalador (Inno Setup)
    motor/rutas.py                  rutas en desarrollo vs empaquetado

Los datos del usuario NO van junto a la app: en Windows se guardan en
`%LOCALAPPDATA%\ExpedientesGEDO`, porque Archivos de programa es de solo
lectura. Ahí queda también `registro.txt`, útil si la app no arranca.

## Pendiente
- Probar con un expediente de **cese** y uno de **suplente** (no los vi todavía).
  Son los que llenan CAMPO A y CAMPO B del formulario, las secciones con datos
  del docente al que se reemplaza.
- Empaquetar para Windows: ni Tauri ni PyInstaller cross-compilan desde macOS.
  Hace falta una máquina Windows o GitHub Actions. Tesseract hay que bundlearlo.
