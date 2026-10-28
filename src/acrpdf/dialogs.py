import datetime
import glob
import json
import os
import time
import urllib.request

import pymupdf
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                             QDialogButtonBox, QFileDialog, QFontComboBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                             QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import certstore, i18n, ops, signing
from .i18n import _

DATA_DIR = certstore.DATA_DIR
SIG_DIR = os.path.join(DATA_DIR, "signatures")
DEFAULT_INK = "#000000"
FILE_FILTER_KEYS = ("*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp *.svg *.doc *.docx *.odt *.rtf "
                    "*.txt *.xls *.xlsx *.ods *.csv *.ppt *.pptx *.odp *.html *.htm *.xps *.epub")


def file_filter():
    return (_("All supported files") + f" ({FILE_FILTER_KEYS});;PDF (*.pdf);;" +
            _("Images") + " (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp *.svg);;" +
            _("Office documents") + " (*.doc *.docx *.odt *.rtf *.txt *.xls *.xlsx *.ods *.ppt *.pptx *.odp);;" +
            _("All files") + " (*)")


def image_filter():
    return _("Signature images") + " (*.png *.jpg *.jpeg *.svg *.webp *.bmp)"


def glyph_icon(glyph, bg=None, fg="#ffffff", size=64, radius=14):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if bg:
        p.setBrush(QColor(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), radius, radius)
    elif fg == "#ffffff":
        fg = "#3c3c3c"
    font = QFont("DejaVu Sans", int(size * (0.42 if bg else 0.55)))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor(fg))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


class ColorButton(QPushButton):
    def __init__(self, color="#000000", on_change=None):
        super().__init__()
        self.setFixedSize(28, 24)
        self.on_change = on_change
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color):
        self.color = QColor(color).name()
        self.setStyleSheet(f"background:{self.color};border:1px solid #888;border-radius:3px;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, _("Choose color"))
        if c.isValid():
            self.set_color(c.name())
            if self.on_change:
                self.on_change(self.color)


def rgb(color):
    c = QColor(color)
    return (c.redF(), c.greenF(), c.blueF())


def qimage_to_png(img):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def trim_image(img):
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if img.pixelColor(x, y).alpha() > 10:
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    if x1 < 0:
        return img
    m = 6
    left, top = max(0, x0 - m), max(0, y0 - m)
    return img.copy(left, top, min(w, x1 + m) - left, min(h, y1 + m) - top)


def remove_background(img, threshold=225):
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.red() > threshold and c.green() > threshold and c.blue() > threshold:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
    return img


def graphic_pixmap(data, max_w=600, max_h=300):
    if ops.is_svg(data):
        renderer = QSvgRenderer(QByteArray(data))
        size = renderer.defaultSize()
        if size.isEmpty():
            size = QSize(300, 100)
        size.scale(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio)
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        renderer.render(p)
        p.end()
        return pm
    pm = QPixmap()
    pm.loadFromData(data)
    if pm.width() > max_w or pm.height() > max_h:
        pm = pm.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return pm


def apply_ink(data, mode, custom="#000000"):
    if mode == "original":
        return data
    color = {"black": "#000000", "blue": "#0b2a8a"}.get(mode, custom)
    if ops.is_svg(data):
        return ops.recolor_svg(data, color)
    return ops.recolor_png(data, rgb(color))


def saved_signatures():
    os.makedirs(SIG_DIR, exist_ok=True)
    files = glob.glob(os.path.join(SIG_DIR, "*.png")) + glob.glob(os.path.join(SIG_DIR, "*.svg"))
    return sorted(files, key=os.path.getmtime, reverse=True)


def save_signature(data):
    os.makedirs(SIG_DIR, exist_ok=True)
    ext = "svg" if ops.is_svg(data) else "png"
    path = os.path.join(SIG_DIR, f"signature_{int(time.time() * 1000)}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def checkerboard_label(min_h=150):
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setMinimumHeight(min_h)
    lbl.setStyleSheet("background:#ffffff;border:1px solid #d0d0d0;border-radius:4px;")
    return lbl


def buttons(dialog, ok_text=None, ok=None):
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    if ok_text:
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancel"))
    bb.accepted.connect(ok or dialog.accept)
    bb.rejected.connect(dialog.reject)
    return bb


class DrawPad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 190)
        self.strokes = []
        self.ink = QColor(DEFAULT_INK)
        self.pen_width = 3.0
        self.on_change = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def clear(self):
        self.strokes = []
        self.update()
        if self.on_change:
            self.on_change()

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])

    def mouseMoveEvent(self, e):
        if self.strokes:
            self.strokes[-1].append(e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        if self.on_change:
            self.on_change()

    def _paint_strokes(self, p, scale=1.0):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.ink, self.pen_width * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        for stroke in self.strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0] * scale)
            for i in range(1, len(stroke) - 1):
                path.quadTo(stroke[i] * scale, (stroke[i] + stroke[i + 1]) / 2 * scale)
            path.lineTo(stroke[-1] * scale)
            p.drawPath(path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c8c8c8"), 1, Qt.PenStyle.DashLine))
        y = int(self.height() * 0.75)
        p.drawLine(20, y, self.width() - 20, y)
        p.drawText(22, y + 16, _("Sign above the line"))
        self._paint_strokes(p)

    def image(self):
        scale = 3.0
        img = QImage(int(self.width() * scale), int(self.height() * scale), QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        self._paint_strokes(p, scale)
        p.end()
        return trim_image(img)


class SignatureDialog(QDialog):

    HAND_FONTS = ("Z003", "URW Chancery L", "Dancing Script", "Great Vibes", "Pacifico", "Caveat",
                  "Satisfy", "Allura", "Sacramento", "Purisa", "DejaVu Serif")

    def __init__(self, parent=None, initials=False):
        super().__init__(parent)
        self.setWindowTitle(_("Create initials") if initials else _("Create signature"))
        self.result_data = None
        self.uploaded = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        w = QWidget()
        f = QVBoxLayout(w)
        self.name = QLineEdit(QSettings().value("signature/name", os.environ.get("USER", "").title()))
        self.name.setPlaceholderText(_("Type your name"))
        f.addWidget(self.name)
        self.styles = QListWidget()
        self.styles.setIconSize(QSize(420, 64))
        f.addWidget(self.styles)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Other font:")))
        self.font = QFontComboBox()
        row.addWidget(self.font, 1)
        f.addLayout(row)
        self.name.textChanged.connect(self._fill_styles)
        self.font.currentFontChanged.connect(self._fill_styles)
        self.styles.currentRowChanged.connect(lambda _r: self._update_preview())
        self.tabs.addTab(w, _("Type"))

        w = QWidget()
        f = QVBoxLayout(w)
        self.pad = DrawPad()
        self.pad.on_change = self._update_preview
        f.addWidget(self.pad)
        row = QHBoxLayout()
        thick = QSpinBox()
        thick.setRange(1, 10)
        thick.setValue(3)
        thick.valueChanged.connect(lambda v: (setattr(self.pad, "pen_width", float(v)), self.pad.update()))
        clear = QPushButton(_("Clear"))
        clear.clicked.connect(self.pad.clear)
        row.addWidget(QLabel(_("Thickness:")))
        row.addWidget(thick)
        row.addStretch()
        row.addWidget(clear)
        f.addLayout(row)
        self.tabs.addTab(w, _("Draw"))

        w = QWidget()
        f = QVBoxLayout(w)
        f.addWidget(QLabel(_("PNG or JPG (a transparent background is best) or SVG (vector, "
                             "always sharp — the format used by professional signature pads).")))
        self.upload_label = checkerboard_label(170)
        self.upload_label.setText(_("No image selected"))
        f.addWidget(self.upload_label)
        row = QHBoxLayout()
        b = QPushButton(_("Choose PNG / SVG…"))
        b.clicked.connect(self._pick_image)
        self.remove_bg = QCheckBox(_("Remove white background"))
        self.remove_bg.setChecked(True)
        self.remove_bg.toggled.connect(lambda _c: self._update_preview())
        row.addWidget(b)
        row.addWidget(self.remove_bg)
        row.addStretch()
        f.addLayout(row)
        self.tabs.addTab(w, _("Upload"))
        self.tabs.currentChanged.connect(lambda _i: self._update_preview())

        g = QGroupBox(_("Preview"))
        gl = QVBoxLayout(g)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Ink:")))
        self.ink_group = QButtonGroup(self)
        for key, label in (("black", _("Black")), ("blue", _("Blue")), ("original", _("Original")),
                           ("custom", _("Custom"))):
            rb = QRadioButton(label)
            rb.setProperty("ink", key)
            self.ink_group.addButton(rb)
            row.addWidget(rb)
            if key == "black":
                rb.setChecked(True)
        self.custom_ink = ColorButton("#5a1a8c", lambda _c: self._update_preview())
        row.addWidget(self.custom_ink)
        row.addStretch()
        self.ink_group.buttonToggled.connect(lambda *_a: self._update_preview())
        gl.addLayout(row)
        prev = QHBoxLayout()
        self.preview = checkerboard_label(110)
        self.box_preview = checkerboard_label(110)
        self.box_preview.setToolTip(_("How it looks inside a digital signature"))
        prev.addWidget(self.preview, 1)
        prev.addWidget(self.box_preview, 1)
        gl.addLayout(prev)
        lay.addWidget(g)

        self.save = QCheckBox(_("Save this signature to reuse it"))
        self.save.setChecked(True)
        lay.addWidget(self.save)
        lay.addWidget(buttons(self, _("Use signature"), self._accept))
        self._fill_styles()
        self.resize(640, 640)

    def _families(self):
        installed = set(QFontDatabase.families())
        families = [f for f in self.HAND_FONTS if f in installed]
        families += sorted(f for f in installed
                           if any(k in f.lower() for k in ("script", "hand", "chancery", "brush", "signature")))
        out = []
        for f in [self.font.currentFont().family()] + families:
            if f not in out:
                out.append(f)
        return out[:10]

    def _render_text(self, family, text):
        font = QFont(family, 72)
        fm = QFontMetrics(font)
        w, h = max(40, fm.horizontalAdvance(text) + 40), fm.height() + 30
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font)
        p.setPen(QColor(DEFAULT_INK))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return trim_image(img)

    def _fill_styles(self, *_args):
        self.styles.blockSignals(True)
        self.styles.clear()
        text = self.name.text().strip() or _("Signature")
        for family in self._families():
            pm = QPixmap.fromImage(self._render_text(family, text))
            it = QListWidgetItem(QIcon(pm.scaled(420, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)), "")
            it.setData(Qt.ItemDataRole.UserRole, family)
            it.setToolTip(family)
            self.styles.addItem(it)
        self.styles.setCurrentRow(0)
        self.styles.blockSignals(False)
        self._update_preview()

    def _pick_image(self):
        path, _f = QFileDialog.getOpenFileName(self, _("Signature image"), os.path.expanduser("~"), image_filter())
        if path:
            self.uploaded = read_file(path)
            self.remove_bg.setEnabled(not ops.is_svg(self.uploaded))
            self.upload_label.setPixmap(graphic_pixmap(self.uploaded, 480, 160))
            self._update_preview()

    def _raw(self):
        tab = self.tabs.currentIndex()
        if tab == 0:
            it = self.styles.currentItem()
            if it and self.name.text().strip():
                return qimage_to_png(self._render_text(it.data(Qt.ItemDataRole.UserRole), self.name.text().strip()))
        elif tab == 1:
            if self.pad.strokes:
                return qimage_to_png(self.pad.image())
        elif self.uploaded:
            if ops.is_svg(self.uploaded):
                return self.uploaded
            img = QImage.fromData(self.uploaded)
            if img.width() > 1600:
                img = img.scaledToWidth(1600, Qt.TransformationMode.SmoothTransformation)
            if self.remove_bg.isChecked():
                img = remove_background(img)
            return qimage_to_png(trim_image(img))
        return None

    def ink_mode(self):
        b = self.ink_group.checkedButton()
        return b.property("ink") if b else "black"

    def current(self):
        raw = self._raw()
        return apply_ink(raw, self.ink_mode(), self.custom_ink.color) if raw else None

    def _update_preview(self):
        if not hasattr(self, "preview"):
            return
        data = self.current()
        if not data:
            self.preview.setText(_("Empty"))
            self.box_preview.clear()
            return
        self.preview.setPixmap(graphic_pixmap(data, 280, 100))
        lines = signing.detail_lines(_("Name Surname") + " - 12345678Z")
        png = signing.appearance_preview(220, 70, signing.Appearance(graphic=data), lines, zoom=1.3)
        self.box_preview.setPixmap(graphic_pixmap(png, 300, 100))

    def _accept(self):
        data = self.current()
        if not data:
            QMessageBox.warning(self, _("Signature"), _("The signature is empty."))
            return
        self.result_data = data
        QSettings().setValue("signature/name", self.name.text())
        if self.save.isChecked():
            save_signature(data)
        self.accept()


class StampDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Stamps"))
        self.result = None
        settings = QSettings()
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        w = QWidget()
        f = QVBoxLayout(w)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(190, 62))
        self.list.setGridSize(QSize(210, 78))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        f.addWidget(self.list)
        form = QFormLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText(_("Custom text (optional)"))
        form.addRow(_("Text:"), self.custom)
        self.sub_mode = QComboBox()
        self.sub_mode.addItems([_("Name and date"), _("Date only"), _("No subtitle"), _("Custom subtitle")])
        form.addRow(_("Subtitle:"), self.sub_mode)
        self.sub_text = QLineEdit(settings.value("stamp/name", os.environ.get("USER", "").title()))
        form.addRow(_("Name / subtitle:"), self.sub_text)
        row = QHBoxLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(settings.value("stamp/font", "DejaVu Sans")))
        self.color = ColorButton("#1a8c33")
        self.use_color = QCheckBox(_("Use this color"))
        row.addWidget(self.font, 1)
        row.addWidget(self.color)
        row.addWidget(self.use_color)
        form.addRow(_("Font:"), row)
        f.addLayout(form)
        self.tabs.addTab(w, _("Text stamps (vector)"))
        for name, color in ops.STAMP_PRESETS:
            title = _(name)
            png = ops.stamp_png(title, color, "DejaVu Sans", _("Name · date"))
            it = QListWidgetItem(QIcon(graphic_pixmap(png, 190, 62)), "")
            it.setData(Qt.ItemDataRole.UserRole, (title, color))
            it.setToolTip(title)
            self.list.addItem(it)
        self.list.setCurrentRow(0)

        w = QWidget()
        f = QVBoxLayout(w)
        f.addWidget(QLabel(_("Company seal or rubber stamp image (PNG with transparency or SVG).")))
        self.img_label = checkerboard_label(200)
        f.addWidget(self.img_label)
        row = QHBoxLayout()
        b = QPushButton(_("Choose image…"))
        b.clicked.connect(self._pick)
        self.white = QCheckBox(_("Remove white background"))
        self.white.setChecked(True)
        row.addWidget(b)
        row.addWidget(self.white)
        row.addStretch()
        f.addLayout(row)
        self.tabs.addTab(w, _("Image stamp"))
        self.image = None
        lay.addWidget(buttons(self, _("Place stamp"), self._accept))
        self.resize(720, 520)

    def _pick(self):
        path, _f = QFileDialog.getOpenFileName(self, _("Stamp image"), os.path.expanduser("~"), image_filter())
        if path:
            self.image = read_file(path)
            self.img_label.setPixmap(graphic_pixmap(self.image, 420, 200))

    def _accept(self):
        settings = QSettings()
        if self.tabs.currentIndex() == 0:
            it = self.list.currentItem()
            title, color = it.data(Qt.ItemDataRole.UserRole)
            title = self.custom.text().strip() or title
            if self.use_color.isChecked():
                color = rgb(self.color.color)
            now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
            sub = {0: f"{self.sub_text.text().strip()} · {now}", 1: now, 2: None,
                   3: self.sub_text.text().strip()}[self.sub_mode.currentIndex()]
            family = self.font.currentFont().family()
            settings.setValue("stamp/name", self.sub_text.text())
            settings.setValue("stamp/font", family)
            self.result = {"kind": "vector", "title": title, "sub": sub, "color": color, "family": family}
        else:
            if not self.image:
                QMessageBox.warning(self, _("Stamp"), _("Choose an image."))
                return
            data = self.image
            if not ops.is_svg(data) and self.white.isChecked():
                data = qimage_to_png(trim_image(remove_background(QImage.fromData(data))))
            self.result = {"kind": "image", "data": data}
        self.accept()


def _cert_line(cert):
    when = ""
    if cert.valid_to:
        v = cert.valid_to
        when = (v if isinstance(v, str) else v.strftime("%Y-%m-%d"))[:10]
    return f"{cert.label}" + (f"  —  {cert.issuer}" if cert.issuer else "") + (f"  —  {_('until')} {when}" if when else "")


class CertificateManager(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Certificates"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("Certificates imported into AcrPDF are copied to %s (only your user can "
                               "read them). Certificates from Firefox/Thunderbird are used directly from "
                               "their store.") % certstore.CERT_DIR))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Certificate"), _("Issuer"), _("Valid until"), _("Source")])
        self.tree.setRootIsDecorated(False)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        for text, slot in ((_("Import .p12/.pfx…"), self._import), (_("Remove"), self._remove),
                           (_("Forget saved password"), self._forget)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        if not certstore.keyring_available():
            lay.addWidget(QLabel(_("No system keyring found: passwords cannot be remembered.")))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.button(QDialogButtonBox.StandardButton.Close).setText(_("Close"))
        lay.addWidget(close)
        self.resize(820, 380)
        self._load()

    def _load(self):
        self.tree.clear()
        self.certs = certstore.all_certificates()
        names = {"store": "AcrPDF", "mozilla": "Firefox / Thunderbird", "file": _("File")}
        for c in self.certs:
            v = c.valid_to
            when = (v if isinstance(v, str) else v.strftime("%Y-%m-%d"))[:10] if v else ""
            QTreeWidgetItem(self.tree, [c.label, c.issuer, when, names[c.source]])
        for i in range(4):
            self.tree.resizeColumnToContents(i)

    def _selected(self):
        i = self.tree.indexOfTopLevelItem(self.tree.currentItem()) if self.tree.currentItem() else -1
        return self.certs[i] if i >= 0 else None

    def _import(self):
        imported = import_certificate_interactive(self)
        if imported:
            self._load()

    def _remove(self):
        c = self._selected()
        if not c or c.source != "store":
            QMessageBox.information(self, _("Certificates"), _("Only certificates imported into AcrPDF can be removed here."))
            return
        if QMessageBox.question(self, _("Certificates"), _("Remove «%s» from AcrPDF?") % c.label) == QMessageBox.StandardButton.Yes:
            certstore.remove_from_store(c)
            self._load()

    def _forget(self):
        c = self._selected()
        if c:
            certstore.forget_password(c)
            QMessageBox.information(self, _("Certificates"), _("Saved password removed."))


def import_certificate_interactive(parent):
    path, _f = QFileDialog.getOpenFileName(parent, _("Import certificate"), os.path.expanduser("~/Documentos"),
                                           _("Certificates") + " (*.p12 *.pfx)")
    if not path:
        return None
    dlg = QDialog(parent)
    dlg.setWindowTitle(_("Import certificate"))
    form = QFormLayout(dlg)
    pw = QLineEdit()
    pw.setEchoMode(QLineEdit.EchoMode.Password)
    remember = QCheckBox(_("Remember the password in the system keyring"))
    remember.setChecked(certstore.keyring_available())
    remember.setEnabled(certstore.keyring_available())
    form.addRow(_("File:"), QLabel(os.path.basename(path)))
    form.addRow(_("Password:"), pw)
    form.addRow(remember)
    form.addRow(buttons(dlg, _("Import")))
    if not dlg.exec():
        return None
    try:
        cert = certstore.import_p12(path, pw.text())
    except signing.SignError as exc:
        QMessageBox.critical(parent, _("Import certificate"), str(exc))
        return None
    if remember.isChecked():
        certstore.remember_password(cert, pw.text())
    QMessageBox.information(parent, _("Import certificate"), _("Certificate «%s» imported.") % cert.label)
    return cert


class DigitalSignDialog(QDialog):

    def __init__(self, parent=None, default_out="", visible=True, field=None, box_size=(220, 70)):
        super().__init__(parent)
        self.setWindowTitle(_("Sign with a digital certificate"))
        self.box_size = box_size
        self.signer_name = None
        settings = QSettings()
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        lay.addLayout(left, 3)

        g = QGroupBox(_("Certificate"))
        form = QFormLayout(g)
        row = QHBoxLayout()
        self.cert_combo = QComboBox()
        self.cert_combo.setMinimumWidth(360)
        row.addWidget(self.cert_combo, 1)
        b = QPushButton(_("Import…"))
        b.setToolTip(_("Import a .p12/.pfx into AcrPDF"))
        b.clicked.connect(self._import)
        row.addWidget(b)
        b = QPushButton(_("File…"))
        b.setToolTip(_("Use a .p12/.pfx file without importing it"))
        b.clicked.connect(self._browse)
        row.addWidget(b)
        form.addRow(row)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_label = QLabel(_("Password:"))
        form.addRow(self.pw_label, self.pw)
        self.remember = QCheckBox(_("Remember the password in the system keyring"))
        self.remember.setEnabled(certstore.keyring_available())
        form.addRow(self.remember)
        self.cert_status = QLabel("")
        self.cert_status.setWordWrap(True)
        form.addRow(self.cert_status)
        left.addWidget(g)

        g = QGroupBox(_("Appearance") + (f" — {_('field')} «{field}»" if field else ""))
        g.setEnabled(visible)
        form = QFormLayout(g)
        row = QHBoxLayout()
        self.img_combo = QComboBox()
        self.img_combo.setIconSize(QSize(110, 34))
        row.addWidget(self.img_combo, 1)
        b = QPushButton(_("Upload PNG/SVG…"))
        b.clicked.connect(self._upload)
        row.addWidget(b)
        b = QPushButton(_("Create…"))
        b.clicked.connect(self._create)
        row.addWidget(b)
        form.addRow(_("Signature image:"), row)
        self.ink = QComboBox()
        for key, label in (("black", _("Black")), ("blue", _("Blue")), ("original", _("Original colors"))):
            self.ink.addItem(label, key)
        self.ink.setCurrentIndex(self.ink.findData(settings.value("sign/ink", "black")))
        form.addRow(_("Ink:"), self.ink)
        self.layout_combo = QComboBox()
        for key, label in (("side", _("Image left, details right")), ("stack", _("Image above, details below")),
                           ("image", _("Image only")), ("text", _("Details only"))):
            self.layout_combo.addItem(label, key)
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(settings.value("sign/layout", "side"))))
        form.addRow(_("Layout:"), self.layout_combo)
        self.show_details = QCheckBox(_("Show name, date and reason"))
        self.show_details.setChecked(True)
        form.addRow(self.show_details)
        self.hide_id = QCheckBox(_("Hide the DNI/NIE in the visible name (***4567**, AEPD)"))
        self.hide_id.setChecked(settings.value("sign/hide_id", "true") == "true")
        form.addRow(self.hide_id)
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(settings.value("sign/font", "DejaVu Sans")))
        form.addRow(_("Font:"), self.font)
        left.addWidget(g)

        g = QGroupBox(_("Details"))
        form = QFormLayout(g)
        self.reason = QLineEdit(settings.value("sign/reason", _("I am the author of this document")))
        self.location = QLineEdit(settings.value("sign/location", ""))
        self.contact = QLineEdit(settings.value("sign/contact", ""))
        form.addRow(_("Reason:"), self.reason)
        form.addRow(_("Location:"), self.location)
        form.addRow(_("Contact:"), self.contact)
        self.certify = QCheckBox(_("Certify document (author signature, DocMDP)"))
        self.lock = QCheckBox(_("Lock the document after signing"))
        self.tsa = QCheckBox(_("Add a trusted timestamp (TSA, needs Internet)"))
        self.tsa_url = QLineEdit(settings.value("sign/tsa", "http://timestamp.digicert.com"))
        form.addRow(self.certify)
        form.addRow(self.lock)
        row = QHBoxLayout()
        row.addWidget(self.tsa)
        row.addWidget(self.tsa_url, 1)
        form.addRow(row)
        row = QHBoxLayout()
        self.out = QLineEdit(default_out)
        b = QPushButton("…")
        b.clicked.connect(self._browse_out)
        row.addWidget(self.out, 1)
        row.addWidget(b)
        form.addRow(_("Save as:"), row)
        left.addWidget(g)
        left.addWidget(buttons(self, _("Continue"), self._accept))

        right = QVBoxLayout()
        right.addWidget(QLabel("<b>" + _("Preview") + "</b>"))
        self.preview = checkerboard_label(160)
        self.preview.setMinimumWidth(330)
        right.addWidget(self.preview)
        hint = QLabel(_("After Continue you can move and resize the signature on the page before signing."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        right.addWidget(hint)
        right.addStretch()
        lay.addLayout(right, 2)

        self._fill_certs()
        self._fill_images()
        self._timer = QTimer(self, singleShot=True, interval=150, timeout=self._update_preview)
        for sig in (self.img_combo.currentIndexChanged, self.ink.currentIndexChanged,
                    self.layout_combo.currentIndexChanged, self.show_details.toggled, self.hide_id.toggled,
                    self.font.currentFontChanged, self.reason.textChanged, self.location.textChanged):
            sig.connect(lambda *_a: self._timer.start())
        self.cert_combo.currentIndexChanged.connect(self._cert_changed)
        self.pw.editingFinished.connect(self._check)
        self._cert_changed()
        self.resize(1040, 680)

    def _fill_certs(self, select=None):
        self.cert_combo.blockSignals(True)
        self.cert_combo.clear()
        self.certs = certstore.all_certificates()
        last_file = QSettings().value("sign/p12_file", "")
        if last_file and os.path.exists(last_file):
            self.certs.append(certstore.Certificate("file", os.path.basename(last_file), path=last_file,
                                                    key_id="file:" + last_file))
        for c in self.certs:
            self.cert_combo.addItem(_cert_line(c))
        if not self.certs:
            self.cert_combo.addItem(_("No certificates: import a .p12/.pfx"))
        last = QSettings().value("sign/cert", "")
        index = next((i for i, c in enumerate(self.certs) if (c.path + c.nickname) == (select or last)), 0)
        self.cert_combo.setCurrentIndex(index)
        self.cert_combo.blockSignals(False)

    def cert(self):
        i = self.cert_combo.currentIndex()
        return self.certs[i] if 0 <= i < len(self.certs) else None

    def _cert_changed(self, *_a):
        c = self.cert()
        self.signer_name = None
        self.cert_status.setText("")
        if c is None:
            return
        needs = c.needs_password
        self.pw_label.setText(_("Password:") if needs else _("Firefox primary password:"))
        self.pw.setPlaceholderText("" if needs else _("Leave empty if Firefox has no primary password"))
        saved = certstore.saved_password(c) if needs else None
        self.pw.setText(saved or "")
        self.remember.setChecked(bool(saved))
        self.remember.setVisible(needs)
        if c.source == "mozilla":
            self.signer_name = c.label.rsplit("  (", 1)[0]
        if saved or c.source == "mozilla":
            self._check()
        self._timer.start()

    def _import(self):
        cert = import_certificate_interactive(self)
        if cert:
            self._fill_certs(select=cert.path)
            self._cert_changed()

    def _browse(self):
        path, _f = QFileDialog.getOpenFileName(self, _("Certificate"), os.path.expanduser("~/Documentos"),
                                               _("Certificates") + " (*.p12 *.pfx)")
        if path:
            QSettings().setValue("sign/p12_file", path)
            self._fill_certs(select=path)
            self._cert_changed()

    def _check(self):
        c = self.cert()
        if c is None:
            return False
        try:
            with certstore.exported_p12(c, self.pw.text()) as (p12, pw):
                signer = signing.load_signer(p12, pw if pw is not None else self.pw.text())
            info = signing.describe_cert(signer.signing_cert)
        except signing.SignError as exc:
            self.cert_status.setText(str(exc))
            self.cert_status.setStyleSheet("color:#c62828;")
            return False
        self.signer_name = info["name"]
        self.cert_status.setText(f"<b>{info['name']}</b><br>{_('Issuer')}: {info['issuer']}<br>"
                                 f"{_('Valid until')}: {info['valid_to']:%d/%m/%Y}")
        self.cert_status.setStyleSheet("color:#1a7f37;")
        self._timer.start()
        return True

    def _fill_images(self, select=None):
        self.img_combo.blockSignals(True)
        self.img_combo.clear()
        self.img_combo.addItem(_("No image"), None)
        for path in saved_signatures():
            self.img_combo.addItem(QIcon(graphic_pixmap(read_file(path), 110, 34)),
                                   "SVG" if path.endswith(".svg") else "PNG", path)
        idx = self.img_combo.findData(select) if select else (1 if self.img_combo.count() > 1 else 0)
        self.img_combo.setCurrentIndex(max(0, idx))
        self.img_combo.blockSignals(False)

    def _upload(self):
        path, _f = QFileDialog.getOpenFileName(self, _("Signature image"), os.path.expanduser("~"), image_filter())
        if path:
            self._fill_images(select=save_signature(read_file(path)))
            self._timer.start()

    def _create(self):
        d = SignatureDialog(self)
        if d.exec() and d.result_data:
            path = saved_signatures()[0] if d.save.isChecked() else save_signature(d.result_data)
            self._fill_images(select=path)
            self._timer.start()

    def appearance(self):
        path = self.img_combo.currentData()
        graphic = apply_ink(read_file(path), self.ink.currentData()) if path else None
        layout = self.layout_combo.currentData()
        if not graphic and layout != "text":
            layout = "text"
        return signing.Appearance(graphic=graphic, layout=layout, show_details=self.show_details.isChecked(),
                                  family=self.font.currentFont().family(), hide_id=self.hide_id.isChecked())

    def detail_lines(self):
        name = self.signer_name or (_("Name Surname") + " - 12345678Z")
        return signing.detail_lines(name, self.reason.text(), self.location.text(),
                                    hide_id=self.hide_id.isChecked())

    def _update_preview(self):
        w, h = self.box_size
        png = signing.appearance_preview(w, h, self.appearance(), self.detail_lines(), zoom=2.0)
        self.preview.setPixmap(graphic_pixmap(png, 420, 220))

    def preview_png(self, width, height, zoom=3.0):
        return signing.appearance_preview(width, height, self.appearance(), self.detail_lines(), zoom=zoom)

    def _browse_out(self):
        path, _f = QFileDialog.getSaveFileName(self, _("Save signed PDF"), self.out.text(), "PDF (*.pdf)")
        if path:
            self.out.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    def _accept(self):
        if self.cert() is None:
            QMessageBox.warning(self, _("Signature"), _("Import or choose a certificate first."))
            return
        if not self._check():
            return
        if not self.out.text():
            self._browse_out()
            if not self.out.text():
                return
        c = self.cert()
        if self.remember.isChecked() and c.needs_password:
            certstore.remember_password(c, self.pw.text())
        settings = QSettings()
        settings.setValue("sign/cert", c.path + c.nickname)
        for key, value in (("reason", self.reason.text()), ("location", self.location.text()),
                           ("contact", self.contact.text()), ("tsa", self.tsa_url.text()),
                           ("layout", self.layout_combo.currentData()), ("ink", self.ink.currentData()),
                           ("font", self.font.currentFont().family()),
                           ("hide_id", "true" if self.hide_id.isChecked() else "false")):
            settings.setValue(f"sign/{key}", value)
        self.accept()

    def options(self):
        return dict(appearance=self.appearance(), reason=self.reason.text(), location=self.location.text(),
                    contact=self.contact.text(), certify=self.certify.isChecked(),
                    lock_document=self.lock.isChecked(),
                    tsa_url=self.tsa_url.text() if self.tsa.isChecked() else None)


class PagePreview(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea{background:#e4e4e4;border:none;}")
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background:#e4e4e4;")
        self.scroll.setWidget(self.label)
        lay.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        self.prev = QPushButton("◀")
        self.next = QPushButton("▶")
        self.info = QLabel()
        self.prev.clicked.connect(lambda: self.show_page(self.page - 1))
        self.next.clicked.connect(lambda: self.show_page(self.page + 1))
        row.addStretch()
        row.addWidget(self.prev)
        row.addWidget(self.info)
        row.addWidget(self.next)
        row.addStretch()
        lay.addLayout(row)
        self.doc = None
        self.page = 0
        self.on_page_changed = None

    def set_pdf(self, data, page=None):
        self.doc = pymupdf.open("pdf", data)
        self.show_page(self.page if page is None else page)

    def show_page(self, index):
        if self.doc is None or not self.doc.page_count:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        changed = index != self.page
        self.page = index
        width = max(300, self.scroll.viewport().width() - 20)
        page = self.doc[index]
        zoom = width / page.rect.width * self.devicePixelRatioF()
        pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(img)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self.label.setPixmap(pixmap)
        self.info.setText(_("Page %(n)d of %(total)d") % {"n": index + 1, "total": self.doc.page_count})
        self.prev.setEnabled(index > 0)
        self.next.setEnabled(index < self.doc.page_count - 1)
        if changed and self.on_page_changed:
            self.on_page_changed(index)


class PreviewDialog(QDialog):

    def __init__(self, parent, title, result, default_path, on_apply=None):
        super().__init__(parent)
        self.setWindowTitle(_("Preview: %s") % title)
        self.result = result
        self.default_path = default_path
        self.on_apply = on_apply
        self.saved_path = None
        lay = QVBoxLayout(self)
        note = QLabel(_("Check the result. Nothing has been changed yet."))
        note.setStyleSheet("color:#555;")
        lay.addWidget(note)
        self.preview = PagePreview()
        lay.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Size: %d KB") % (len(result) // 1024)))
        row.addStretch()
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        if on_apply:
            apply_btn = QPushButton(_("Apply to document"))
            apply_btn.clicked.connect(self._apply)
            row.addWidget(apply_btn)
        save = QPushButton(_("Save as…"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        lay.addLayout(row)
        self.resize(760, 860)
        QTimer.singleShot(0, lambda: self.preview.set_pdf(result, 0))

    def _apply(self):
        self.on_apply(self.result)
        self.accept()

    def _save(self):
        path, _f = QFileDialog.getSaveFileName(self, _("Save as"), self.default_path, "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            with open(path, "wb") as f:
                f.write(self.result)
            self.saved_path = path
            self.accept()


class FieldDialog(QDialog):
    def __init__(self, parent, kind, name, options=None):
        super().__init__(parent)
        self.setWindowTitle(_("Field properties"))
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        form.addRow(_("Name:"), self.name)
        self.tooltip = QLineEdit()
        form.addRow(_("Tooltip:"), self.tooltip)
        self.options = QPlainTextEdit("\n".join(options or []))
        self.options.setMaximumHeight(110)
        if kind in ("combo", "list"):
            form.addRow(_("Options (one per line):"), self.options)
        self.size = QSpinBox()
        self.size.setRange(0, 72)
        self.size.setSpecialValueText(_("Auto"))
        if kind in ("text", "combo", "list"):
            form.addRow(_("Font size:"), self.size)
        self.multiline = QCheckBox(_("Multi-line"))
        if kind == "text":
            form.addRow(self.multiline)
        self.required = QCheckBox(_("Required"))
        form.addRow(self.required)
        form.addRow(buttons(self))

    def values(self):
        return dict(name=self.name.text().strip(),
                    options=[o.strip() for o in self.options.toPlainText().splitlines() if o.strip()],
                    fontsize=self.size.value(), multiline=self.multiline.isChecked(),
                    required=self.required.isChecked(), tooltip=self.tooltip.text())


class ProtectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Protect with password"))
        form = QFormLayout(self)
        self.user, self.user2, self.owner = QLineEdit(), QLineEdit(), QLineEdit()
        for w in (self.user, self.user2, self.owner):
            w.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Password to open:"), self.user)
        form.addRow(_("Repeat password:"), self.user2)
        form.addRow(_("Permissions password:"), self.owner)
        self.p_print = QCheckBox(_("Allow printing"))
        self.p_print.setChecked(True)
        self.p_copy = QCheckBox(_("Allow copying text"))
        self.p_edit = QCheckBox(_("Allow editing, filling and commenting"))
        for c in (self.p_print, self.p_copy, self.p_edit):
            form.addRow(c)
        form.addRow(QLabel(_("Encryption: AES-256")))
        form.addRow(buttons(self, ok=self._ok))

    def _ok(self):
        if self.user.text() != self.user2.text():
            QMessageBox.warning(self, _("Protect"), _("The passwords do not match."))
            return
        if not self.user.text() and not self.owner.text():
            QMessageBox.warning(self, _("Protect"), _("Enter at least one password."))
            return
        self.accept()

    def options(self):
        return dict(user_pw=self.user.text(), owner_pw=self.owner.text(), allow_print=self.p_print.isChecked(),
                    allow_copy=self.p_copy.isChecked(), allow_edit=self.p_edit.isChecked())


class WatermarkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Watermark"))
        form = QFormLayout(self)
        self.text = QLineEdit(_("CONFIDENTIAL"))
        self.image = None
        img_row = QHBoxLayout()
        self.image_label = QLabel(_("(text watermark)"))
        b = QPushButton(_("Use an image…"))
        b.clicked.connect(self._pick)
        img_row.addWidget(self.image_label, 1)
        img_row.addWidget(b)
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont("DejaVu Sans"))
        self.size = QSpinBox()
        self.size.setRange(8, 200)
        self.size.setValue(64)
        self.color = ColorButton("#9a9a9a")
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setValue(30)
        self.opacity.setSuffix(" %")
        self.angle = QSpinBox()
        self.angle.setRange(-90, 90)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        self.position = QComboBox()
        for key, label in (("center", _("Center")), ("top", _("Top")), ("bottom", _("Bottom")),
                           ("tile", _("Mosaic (repeated)"))):
            self.position.addItem(label, key)
        form.addRow(_("Text:"), self.text)
        form.addRow(_("Image:"), img_row)
        form.addRow(_("Font:"), self.font)
        form.addRow(_("Size:"), self.size)
        form.addRow(_("Color:"), self.color)
        form.addRow(_("Opacity:"), self.opacity)
        form.addRow(_("Angle:"), self.angle)
        form.addRow(_("Position:"), self.position)
        form.addRow(buttons(self))

    def _pick(self):
        path, _f = QFileDialog.getOpenFileName(self, _("Watermark image"), os.path.expanduser("~"), image_filter())
        if path:
            self.image = read_file(path)
            self.image_label.setText(os.path.basename(path))

    def options(self):
        return dict(text=self.text.text(), image=self.image, size=self.size.value(), color=rgb(self.color.color),
                    opacity=self.opacity.value() / 100, family=self.font.currentFont().family(),
                    angle=self.angle.value(), position=self.position.currentData())


class PageNumbersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Page numbers"))
        form = QFormLayout(self)
        self.position = QComboBox()
        labels = {"bottom-center": _("Bottom center"), "bottom-right": _("Bottom right"),
                  "bottom-left": _("Bottom left"), "top-center": _("Top center"),
                  "top-right": _("Top right"), "top-left": _("Top left")}
        for key in ops.PAGE_NUMBER_POSITIONS:
            self.position.addItem(labels[key], key)
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        self.fmt.addItems(["{n}", _("Page {n}"), _("Page {n} of {total}"), "{n} / {total}", "- {n} -"])
        self.start = QSpinBox()
        self.start.setRange(0, 99999)
        self.start.setValue(1)
        self.first = QSpinBox()
        self.first.setRange(1, 99999)
        self.first.setValue(1)
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont("DejaVu Sans"))
        self.size = QSpinBox()
        self.size.setRange(5, 40)
        self.size.setValue(10)
        form.addRow(_("Position:"), self.position)
        form.addRow(_("Format:"), self.fmt)
        form.addRow(QLabel(_("Variables: {n} page, {total} total, {date} today")))
        form.addRow(_("First number:"), self.start)
        form.addRow(_("Start on page:"), self.first)
        form.addRow(_("Font:"), self.font)
        form.addRow(_("Size:"), self.size)
        form.addRow(buttons(self))

    def options(self):
        return dict(fmt=self.fmt.currentText(), position=self.position.currentData(), start=self.start.value(),
                    first_page=self.first.value(), size=self.size.value(), family=self.font.currentFont().family())


class FileListDialog(QDialog):

    def __init__(self, parent=None, title="", ok_text=None, files=(), filter_=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.filter = filter_ or file_filter()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("Add files and drag them to change the order.")))
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in ((_("Add files…"), self._add), (_("Remove"), self._remove),
                           (_("Up"), lambda: self._move(-1)), (_("Down"), lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(buttons(self, ok_text))
        for f in files:
            self.list.addItem(f)
        self.resize(560, 420)

    def _add(self):
        paths, _f = QFileDialog.getOpenFileNames(self, _("Add files"), os.path.expanduser("~"), self.filter)
        for p in paths:
            self.list.addItem(p)

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _move(self, delta):
        r = self.list.currentRow()
        if 0 <= r + delta < self.list.count():
            it = self.list.takeItem(r)
            self.list.insertItem(r + delta, it)
            self.list.setCurrentRow(r + delta)

    def files(self):
        return [self.list.item(i).text() for i in range(self.list.count())]


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Preferences"))
        settings = QSettings()
        form = QFormLayout(self)
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(_(name) if not code else name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.value("language", ""))))
        form.addRow(_("Language:"), self.language)
        form.addRow(QLabel(_("The language change applies after restarting AcrPDF.")))
        self.author = QLineEdit(settings.value("author", os.environ.get("USER", "")))
        form.addRow(_("Author name for comments:"), self.author)
        self.compression = QComboBox()
        for key, label in (("recommended", _("Recommended (images at 200 dpi)")),
                           ("high", _("High quality (images at 300 dpi)")),
                           ("small", _("Smallest file (images at 150 dpi)")),
                           ("lossless", _("Lossless (fonts and structure only)"))):
            self.compression.addItem(label, key)
        self.compression.setCurrentIndex(max(0, self.compression.findData(
            settings.value("save/compression", "recommended"))))
        self.compression.setToolTip(_("Applied when saving and, before signing, to the document that gets signed. "
                                      "Documents that are already signed are never recompressed."))
        form.addRow(_("Compress when saving:"), self.compression)
        self.auto_update = QCheckBox(_("Check for updates automatically (GitHub)"))
        self.auto_update.setChecked(settings.value("updates/auto", "true") == "true")
        form.addRow(self.auto_update)

        from . import ai
        self.ai = ai
        box = QGroupBox(_("AI (summaries and translations)"))
        ai_form = QFormLayout(box)
        self.provider = QComboBox()
        for key, (label, *_rest) in ai.PROVIDERS.items():
            self.provider.addItem(label + (" — " + _("local, offline") if key == "ollama" else ""), key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(settings.value("ai/provider", "claude"))))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.load_models = QPushButton(_("Load models"))
        self.load_models.clicked.connect(self._load_models)
        row.addWidget(self.model, 1)
        row.addWidget(self.load_models)
        self.ollama_url = QLineEdit(settings.value("ai/ollama_url", ai.DEFAULT_OLLAMA_URL))
        self.privacy = QLabel()
        self.privacy.setWordWrap(True)
        self.privacy.setStyleSheet("color:#666;")
        ai_form.addRow(_("Provider:"), self.provider)
        self.key_label = QLabel(_("API key:"))
        ai_form.addRow(self.key_label, self.api_key)
        ai_form.addRow(_("Model:"), row)
        self.url_label = QLabel(_("Ollama URL:"))
        ai_form.addRow(self.url_label, self.ollama_url)
        ai_form.addRow(self.privacy)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()
        form.addRow(box)
        form.addRow(buttons(self))

    def _provider_changed(self, *_args):
        key = self.provider.currentData()
        settings = QSettings()
        local = key == "ollama"
        self.key_label.setVisible(not local)
        self.api_key.setVisible(not local)
        self.url_label.setVisible(local)
        self.ollama_url.setVisible(local)
        self.api_key.clear()
        self.api_key.setPlaceholderText(_("saved in the system keyring") if self.ai.get_api_key(key)
                                        else {"claude": "sk-ant-…", "openai": "sk-…", "deepseek": "sk-…"}.get(key, ""))
        default = self.ai.PROVIDERS[key][3]
        current = settings.value(f"ai/{key}_model", "") if key != "ollama" else \
            settings.value("ai/ollama_model", self.ai.DEFAULT_OLLAMA_MODEL)
        self.model.clear()
        if key == "openai":
            self.model.addItem(_("Automatic (cheapest available)"), "")
        if default:
            self.model.addItem(default, default)
        if current and self.model.findData(current) < 0:
            self.model.addItem(current, current)
        self.model.setCurrentIndex(max(0, self.model.findData(current or default)))
        self.model.setEnabled(key != "claude")
        self.load_models.setEnabled(key != "claude")
        company = {"claude": "Anthropic", "openai": "OpenAI", "deepseek": "DeepSeek"}.get(key)
        self.privacy.setText(_("Runs on this computer: the document never leaves it.") if local else
                             _("When you summarize or translate, the document text is sent to %s.") % company)

    def _load_models(self):
        key = self.provider.currentData()
        try:
            if key == "ollama":
                with urllib.request.urlopen(self.ollama_url.text().rstrip("/") + "/api/tags", timeout=10) as r:
                    names = [m["name"] for m in json.loads(r.read())["models"]]
            else:
                provider = self.ai.OpenAICompatibleProvider(key, model="-", api_key=self.api_key.text().strip() or None)
                names = [m for m in provider.models() if key != "openai" or m.startswith(("gpt-", "o"))]
        except Exception as exc:
            QMessageBox.warning(self, _("Load models"), str(exc))
            return
        current = self.model.currentData()
        for name in names:
            if self.model.findData(name) < 0:
                self.model.addItem(name, name)
        self.model.setCurrentIndex(max(0, self.model.findData(current)))
        self.model.showPopup()

    def save(self):
        settings = QSettings()
        settings.setValue("language", self.language.currentData())
        settings.setValue("author", self.author.text())
        settings.setValue("save/compression", self.compression.currentData())
        settings.setValue("updates/auto", "true" if self.auto_update.isChecked() else "false")
        key = self.provider.currentData()
        settings.setValue("ai/provider", key)
        model = self.model.currentData() if self.model.currentText() == self.model.itemText(self.model.currentIndex()) \
            else self.model.currentText().strip()
        if key == "ollama":
            settings.setValue("ai/ollama_url", self.ollama_url.text().strip())
            settings.setValue("ai/ollama_model", model or self.ai.DEFAULT_OLLAMA_MODEL)
        elif key != "claude":
            settings.setValue(f"ai/{key}_model", model or "")
        if self.api_key.text().strip():
            self.ai.set_api_key(self.api_key.text().strip(), key)


class TextResultDialog(QDialog):

    def __init__(self, parent, title, text, default_path):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.default_path = default_path
        self.saved_path = None
        lay = QVBoxLayout(self)
        note = QLabel(_("Review and correct the recognized text, then save it as a .txt file."))
        note.setStyleSheet("color:#555;")
        lay.addWidget(note)
        self.edit = QPlainTextEdit(text)
        self.edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        copy = QPushButton(_("Copy"))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.edit.toPlainText()))
        close = QPushButton(_("Close"))
        close.clicked.connect(self.reject)
        save = QPushButton(_("Save as .txt…"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(copy)
        row.addStretch()
        row.addWidget(close)
        row.addWidget(save)
        lay.addLayout(row)
        self.resize(820, 760)

    def _save(self):
        path, _f = QFileDialog.getSaveFileName(self, _("Save as"), self.default_path, _("Text") + " (*.txt)")
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.edit.toPlainText())
        self.saved_path = path
        self.accept()


class MarkdownDialog(QDialog):

    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.text = text
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setMarkdown(text)
        lay.addWidget(view)
        row = QHBoxLayout()
        copy = QPushButton(_("Copy"))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        save = QPushButton(_("Save as…"))
        save.clicked.connect(self._save)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.accept)
        row.addWidget(copy)
        row.addWidget(save)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.resize(720, 560)

    def _save(self):
        path, _f = QFileDialog.getSaveFileName(self, _("Save as"), os.path.expanduser("~/Documentos/summary.md"),
                                               "Markdown (*.md);;" + _("Text") + " (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text)

