# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); el proyecto
sigue [versionado semántico](https://semver.org/lang/es/).

## [2.1.0] - 2026-10-26

### Añadido
- **Proteger DNI / NIE** con marca de agua al estilo de las apps de copias seguras: texto
  diagonal repetido («SOLO PARA {trámite} · {fecha}») con tamaño, grosor, intensidad,
  separación, ángulo y color configurables, franja inferior «DNI para … trámite», opción de
  aplicarla solo sobre las fotos y de fusionar el resultado en imagen para que no se pueda
  quitar. Vista previa en vivo y botones *Guardar como…* / *Aplicar al documento*.
- Vista previa con confirmación antes de aplicar marca de agua, numeración, censura de texto
  y aplanado, y botón *Vista previa* en las herramientas por lotes.
- Las firmas e imágenes colocadas se pueden volver a seleccionar con un clic para moverlas,
  redimensionarlas o borrarlas (también tras guardar y reabrir; los SVG siguen siendo vectoriales).
- Aviso al abrir documentos firmados (válido, identidad no verificada o firma inválida) y
  aviso de campos de firma pendientes, con acceso directo al panel de firmas.
- OCR desde el editor (*Editar PDF → Reconocer texto*): el resultado se abre en una pestaña
  nueva y cualquier palabra reconocida se puede editar (se limpia el fondo escaneado).
  Las páginas que ya tienen texto no se rasterizan.
- Proveedores de IA ChatGPT (OpenAI) y DeepSeek además de Claude y Ollama, con selector de
  modelo y botón *Cargar modelos*.

### Corregido
- *Escanear a PDF* usaba la dirección de la ruta por defecto, que con una VPN activa no es
  accesible desde el móvil. Ahora elige la tarjeta física (Wi-Fi/Ethernet) conectada y permite
  cambiarla.

## [2.0.4] - 2026-10-26

### Corregido
- *Ocultar DNI / NIE* no encontraba números escritos como `61.133.999 - E` (nóminas),
  `012345678Z` (bancos) ni dentro de la zona de lectura mecánica del DNI.
- Ahora también funciona en documentos escaneados y fotos del DNI: cada imagen se lee con
  OCR (Tesseract, varias variantes de contraste para superar el fondo de seguridad) y se
  borran los píxeles. En modo AEPD solo se tapan los caracteres ocultos, de modo que las
  cuatro cifras visibles se conservan en la propia imagen.
- En modo AEPD sobre texto ya no se pinta un recuadro blanco sobre el fondo.

## [2.0.3] - 2026-10-26

### Añadido
- Las imágenes que se colocan (firmas, sellos, fotos) se reducen a 300 ppp para su tamaño
  en la página y se guardan como PNG optimizado (con transparencia) o JPEG.
- Compresión al guardar configurable en *Preferencias* (recomendada 200 ppp por defecto,
  alta calidad, mínima o sin pérdida). Antes de firmar digitalmente se aplica en memoria al
  documento, de modo que la firma cubre ya la versión comprimida.
- La barra de estado muestra el tamaño del archivo guardado.

## [2.0.2] - 2026-10-26

### Corregido
- Los PDF firmados o con texto añadido crecían unos 750 KB por la tipografía incrustada
  completa. Ahora solo se incrustan los caracteres usados y, si el documento aún no tiene
  firmas, se compacta al guardar o firmar (sin revisiones intermedias y con flujos
  comprimidos). Ejemplo: un PDF de 568 KB editado y firmado pasa de ~2 MB a 413 KB.

## [2.0.1] - 2026-10-26

### Corregido
- La aplicación se cerraba al usar como firma un PNG en escala de grises (con o sin
  transparencia), de 1 bit o un JPG CMYK: ahora se convierten a RGB antes de aplicar la tinta.
- Los errores inesperados se muestran en un aviso en lugar de cerrar la aplicación.
- Se silencia el aviso de pyHanko sobre certificados `.p12` codificados en BER (habitual en
  certificados de la FNMT; se leen correctamente).

## [2.0.0] - 2026-10-26

### Añadido
- Nombre definitivo: **ACRPDF Reader** (paquete y comando `acrpdf`).
- Herramientas por lotes al estilo iLovePDF: unir, dividir, eliminar y extraer páginas, rotar,
  comprimir (tres niveles), reparar, OCR, imágenes/Word/PowerPoint/Excel/HTML a PDF,
  PDF a JPG/PNG/Word/PowerPoint/Excel/PDF-A/texto/Markdown, numerar, marca de agua
  (centro, arriba, abajo o mosaico), recortar márgenes, desbloquear, proteger,
  ocultar DNI/NIE y comparar.
- Escanear a PDF con la cámara del móvil (código QR en la red local) o con un escáner SANE.
- Flujos de trabajo: cadenas de herramientas guardadas y reutilizables.
- Firma: imágenes PNG o **SVG vectorial**, vista previa de la apariencia, colocación y
  redimensionado sobre la página antes de firmar, tinta negra por defecto.
- Certificados del almacén de **Firefox/Thunderbird**, almacén propio con la contraseña en el
  llavero del sistema y cadena de certificación completada automáticamente (AIA).
- Ocultación del DNI/NIE en la firma visible y en documentos según la AEPD (`***4567**`).
- Formularios: relleno directamente sobre el lienzo (Tab salta al siguiente campo),
  campos que se mueven y redimensionan con el ratón y detección automática de campos.
- Solicitar firmas por correo electrónico con campos de firma por firmante.
- Asistente IA opcional (resumir y traducir conservando el diseño) con la API de Claude
  o un modelo local de Ollama.
- Interfaz traducida a español, francés y portugués; sigue el idioma del sistema.
- `Makefile`, `pyproject.toml`, tests con pytest y metadatos AppStream.

### Cambiado
- La impresora virtual pasa a llamarse `ACRPDF`; el paquete sustituye a `lumenpdf`.
- Ghostscript ya no autorrota las páginas al comprimir o convertir a PDF/A.

### Eliminado
- El reparador del snap `acrordrdc`.

## [1.0.0] - 2026-10-26

### Añadido
- Primera versión (publicada como «Lumen PDF»): visor con pestañas, anotaciones,
  formularios, firma PAdES con `.p12`, sellos, organización de páginas e impresora virtual.
