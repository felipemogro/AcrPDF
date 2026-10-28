#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/src/acrpdf/__init__.py")
ARCH=$(dpkg --print-architecture)
PKG="acrpdf_${VERSION}_${ARCH}"
STAGE="$ROOT/build/$PKG"
PYTHON=/usr/bin/python3
PY=$($PYTHON -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PYNEXT=$($PYTHON -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1] + 1))')
UV=${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

[ -x "$UV" ] || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
ls "$ROOT"/src/acrpdf/locale/*/LC_MESSAGES/acrpdf.mo >/dev/null 2>&1 \
    || { echo "Translations are not compiled: run 'make mo' first." >&2; exit 1; }

log "AcrPDF $VERSION ($ARCH, Python $PY)"
rm -rf "$STAGE"
install -d "$STAGE/DEBIAN" "$STAGE/opt/acrpdf" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/metainfo" "$STAGE/usr/share/doc/acrpdf" "$STAGE/usr/lib/cups/backend" \
    "$STAGE/usr/share/ppd/acrpdf" "$STAGE/usr/share/icons/hicolor/scalable/apps"

log "Python environment"
"$UV" venv --quiet --relocatable --python "$PYTHON" "$STAGE/opt/acrpdf/venv"
"$UV" pip install --quiet --python "$STAGE/opt/acrpdf/venv/bin/python" "$ROOT"

log "Removing unused Qt modules"
SITE=$(echo "$STAGE"/opt/acrpdf/venv/lib/python*/site-packages)
QT="$SITE/PyQt6/Qt6"
rm -rf "$QT/qml" "$QT"/plugins/{multimedia,qmltooling,sensors,position,texttospeech,canbus,sqldrivers,renderers,designer}
find "$QT/translations" -type f ! -name 'qtbase_es.qm' ! -name 'qtbase_fr.qm' ! -name 'qtbase_pt*.qm' -delete
for module in Quick Qml Designer Multimedia Bluetooth Nfc Sensors Positioning RemoteObjects WebChannel \
              WebSockets SerialPort Labs Test TextToSpeech SpatialAudio ShaderTools StateMachine Help Pdf \
              Sql Concurrent Quick3D; do
    rm -f "$QT"/lib/libQt6${module}* "$SITE"/PyQt6/Qt${module}*
done
rm -f "$QT"/lib/libQt6FFmpeg* "$QT"/lib/libav* "$QT"/lib/libsw*
find "$SITE" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$SITE"/pip "$SITE"/pip-* "$STAGE"/opt/acrpdf/venv/bin/activate*

log "Checking the reduced environment"
QT_QPA_PLATFORM=offscreen "$STAGE/opt/acrpdf/venv/bin/python" -c \
    "import acrpdf.app, acrpdf.signing, acrpdf.tools, acrpdf.scan, acrpdf.ai; \
     from PyQt6.QtPrintSupport import QPrinter; from PyQt6.QtSvg import QSvgRenderer"
find "$STAGE/opt/acrpdf" -name '__pycache__' -type d -prune -exec rm -rf {} +

log "Desktop integration, printer and docs"
install -m 755 "$ROOT/packaging/acrpdf.sh" "$STAGE/usr/bin/acrpdf"
install -m 644 "$ROOT/data/acrpdf.desktop" "$STAGE/usr/share/applications/acrpdf.desktop"
install -m 644 "$ROOT/data/acrpdf.metainfo.xml" "$STAGE/usr/share/metainfo/acrpdf.metainfo.xml"
install -m 644 "$ROOT/src/acrpdf/resources/acrpdf.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/acrpdf.svg"
for size in 48 128 256; do
    install -d "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps"
    QT_QPA_PLATFORM=offscreen "$STAGE/opt/acrpdf/venv/bin/python" -c "
import sys
from PyQt6.QtGui import QGuiApplication, QIcon
app = QGuiApplication(sys.argv)
QIcon(sys.argv[1]).pixmap($size, $size).save(sys.argv[2])" \
        "$ROOT/src/acrpdf/resources/acrpdf.svg" "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/acrpdf.png"
done
install -m 700 "$ROOT/printer/acrpdf" "$STAGE/usr/lib/cups/backend/acrpdf"
install -m 644 "$ROOT/printer/ACRPDF.ppd" "$STAGE/usr/share/ppd/acrpdf/ACRPDF.ppd"
install -m 644 "$ROOT/README.md" "$ROOT/CHANGELOG.md" "$STAGE/usr/share/doc/acrpdf/"
install -m 644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/acrpdf/copyright"

log "Package metadata"
SIZE=$(du -sk "$STAGE" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" -e "s/@SIZE@/$SIZE/" -e "s/@PY@/$PY/" \
    -e "s/@PYNEXT@/$PYNEXT/" "$ROOT/packaging/debian/control.in" > "$STAGE/DEBIAN/control"
install -m 755 "$ROOT"/packaging/debian/{postinst,prerm,postrm} "$STAGE/DEBIAN/"

log "Building"
mkdir -p "$ROOT/releases"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$ROOT/releases/$PKG.deb" >/dev/null
(cd "$ROOT/releases" && sha256sum "$PKG.deb" > "$PKG.deb.sha256")
log "releases/$PKG.deb ($(du -h "$ROOT/releases/$PKG.deb" | cut -f1))"
