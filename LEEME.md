# Sistema de expedientes GEDO → Excel

## Cómo se usa
Doble clic en **Iniciar sistema.command** (macOS) o `python3 motor/app.py`.
Se abre el navegador solo. Para cerrarlo, cerrá la ventana de la terminal.

Flujo: soltás los PDFs de UN expediente → revisás la fila → "Extraer datos a Excel".

## Qué hay acá
    motor/extractor.py   lee los PDFs, detecta el tipo y extrae los campos
    motor/ocr.py         lee las paginas escaneadas del Formulario T (cacheado)
    motor/cotejo.py      compara un mismo dato entre documentos distintos
    motor/almacen.py     SQLite (fuente de verdad) + exportación a Excel
    motor/app.py         servidor local
    motor/ui.html        la pantalla (se reusa tal cual en Tauri)
    datos/               la base y el Excel generado
    ejemplos/            PDFs de prueba

## Historial y archivo por mes

Cada expediente guardado queda en el historial, agrupado por **mes de
importación** (cuándo se cargó, no la fecha del trámite). Desde el botón
*Ver historial* se puede abrir uno para corregirlo o quitarlo.

El Excel tiene una hoja **Todos** con el historial completo y una columna
*Importado*, más **una hoja por mes**, de la más reciente a la más vieja.

Corregir un expediente NO cambia su mes: sigue archivado donde se cargó.

## Decisiones de diseño
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

## Compilar el instalador de Windows

No se puede compilar desde macOS: PyInstaller no cross-compila (empaqueta el
intérprete y las librerías nativas del sistema donde corre). Hay que hacerlo en
Windows, y la forma más simple es que lo haga GitHub gratis:

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

El workflow instala Tesseract, lo empaqueta junto con la app (solo los idiomas
español, inglés y OSD: el pack completo son ~700 MB), compila, **arranca el
ejecutable y verifica que responda** antes de publicar nada, y arma el
instalador con Inno Setup.

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
