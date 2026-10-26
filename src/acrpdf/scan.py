import html
import http.server
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
from email.parser import BytesParser
from email.policy import default as email_policy

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

from . import ops
from .i18n import _

UPLOAD_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:sans-serif;margin:24px;background:#f4f4f4;color:#222}}
label{{display:block;background:#c8102e;color:#fff;padding:18px;border-radius:12px;text-align:center;
font-size:20px;margin:16px 0}}input{{display:none}}#s{{font-size:16px}}</style></head><body>
<h2>{title}</h2><p>{hint}</p>
<label>{button}<input id="f" type="file" accept="image/*" capture="environment" multiple></label>
<p id="s"></p>
<script>
const f=document.getElementById('f'),s=document.getElementById('s');let n=0;
f.onchange=async()=>{{for(const file of f.files){{const d=new FormData();d.append('image',file);
s.textContent={sending};const r=await fetch(location.pathname,{{method:'POST',body:d}});
if(r.ok){{n++;s.textContent={sent}+' '+n;}}else{{s.textContent='Error '+r.status;}}}}f.value='';}};
</script></body></html>"""


def network_addresses():
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[1] == "lo":
            continue
        name, ip = parts[1], parts[3].split("/")[0]
        sysfs = f"/sys/class/net/{name}"
        physical = os.path.exists(sysfs + "/device")
        wireless = os.path.exists(sysfs + "/wireless")
        try:
            with open(sysfs + "/operstate") as f:
                up = f.read().strip() in ("up", "unknown")
        except OSError:
            up = True
        found.append({"interface": name, "ip": ip, "physical": physical, "wireless": wireless, "up": up})
    found.sort(key=lambda a: (not a["physical"], not a["up"], not a["wireless"]))
    if not found:
        found.append({"interface": "?", "ip": _fallback_address(), "physical": False, "wireless": False, "up": True})
    return found


def _fallback_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def lan_address():
    return network_addresses()[0]["ip"]


class PhoneUploadServer:

    MAX_UPLOAD = 40 * 1024 * 1024

    def __init__(self, folder):
        self.folder = folder
        self.token = secrets.token_urlsafe(12)
        self.received = []
        self.lock = threading.Lock()
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _authorized(self):
                return self.path.rstrip("/") == "/" + server.token

            def do_GET(self):
                if not self._authorized():
                    self.send_error(404)
                    return
                page = UPLOAD_PAGE.format(
                    title=html.escape(_("Scan to PDF")),
                    hint=html.escape(_("Take photos of each page. They appear on your computer instantly.")),
                    button=html.escape(_("📷 Take photo")), sending=json.dumps(_("Sending…")), sent=json.dumps(_("Pages sent:")))
                data = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                if not self._authorized() or not 0 < length <= server.MAX_UPLOAD:
                    self.send_error(403)
                    return
                body = self.rfile.read(length)
                msg = BytesParser(policy=email_policy).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
                saved = 0
                for part in msg.iter_parts():
                    payload = part.get_payload(decode=True)
                    if payload and part.get_content_type().startswith("image/"):
                        server._store(payload, part.get_content_subtype())
                        saved += 1
                self.send_response(200 if saved else 400)
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def _store(self, data, subtype):
        ext = {"jpeg": "jpg", "png": "png", "webp": "webp", "heic": "heic"}.get(subtype, "jpg")
        with self.lock:
            path = os.path.join(self.folder, f"page_{len(self.received) + 1:03d}.{ext}")
            with open(path, "wb") as f:
                f.write(data)
            self.received.append(path)

    def url(self, address=None):
        return f"http://{address or lan_address()}:{self.httpd.server_address[1]}/{self.token}"

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def scanners():
    exe = shutil.which("scanimage")
    if not exe:
        return []
    out = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=60).stdout
    found = []
    for line in out.splitlines():
        if line.startswith("device `"):
            device = line.split("`", 1)[1].split("'", 1)[0]
            found.append((device, line.split(" is a ", 1)[-1]))
    return found


def scan_page(device, out_path, dpi=200, mode="Color"):
    subprocess.run(["scanimage", "-d", device, "--format=png", f"--resolution={dpi}", f"--mode={mode}",
                    "-o", out_path], check=True, capture_output=True, timeout=300)
    return out_path


def enhance_document(path):
    from PIL import Image, ImageOps
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=2)
        out = os.path.splitext(path)[0] + "_doc.png"
        gray.save(out)
    return out


def qr_pixmap(text, size=260):
    import qrcode
    buf = io.BytesIO()
    qrcode.make(text, border=2).save(buf, format="PNG")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue())
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


class ScanDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(_("Scan to PDF"))
        self.folder = tempfile.mkdtemp(prefix="acrpdf-scan-")
        self.server = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        phone = QWidget()
        pl = QHBoxLayout(phone)
        self.qr = QLabel()
        self.qr.setFixedSize(270, 270)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(self.qr)
        info = QVBoxLayout()
        text = QLabel(_("1. Connect the phone to the same Wi-Fi network.\n"
                        "2. Scan the QR code with the camera.\n"
                        "3. Take a photo of each page; they appear here.\n\n"
                        "The link only works while this window is open."))
        text.setWordWrap(True)
        info.addWidget(text)
        info.addWidget(QLabel(_("Network card:")))
        self.address = QComboBox()
        for a in network_addresses():
            kind = _("Wi-Fi") if a["wireless"] else (_("Ethernet") if a["physical"] else _("virtual"))
            self.address.addItem(f"{a['interface']} · {a['ip']} ({kind})", a["ip"])
        self.address.currentIndexChanged.connect(self._update_qr)
        info.addWidget(self.address)
        self.url_label = QLabel()
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.addWidget(self.url_label)
        info.addStretch()
        pl.addLayout(info, 1)
        self.tabs.addTab(phone, _("Phone camera"))

        scanner = QWidget()
        sl = QVBoxLayout(scanner)
        row = QHBoxLayout()
        self.devices = QComboBox()
        refresh = QPushButton(_("Search scanners"))
        refresh.clicked.connect(self._find_scanners)
        row.addWidget(self.devices, 1)
        row.addWidget(refresh)
        sl.addLayout(row)
        row = QHBoxLayout()
        self.dpi = QSpinBox()
        self.dpi.setRange(75, 1200)
        self.dpi.setValue(200)
        self.dpi.setSuffix(" dpi")
        self.mode = QComboBox()
        self.mode.addItem(_("Color"), "Color")
        self.mode.addItem(_("Grayscale"), "Gray")
        self.mode.addItem(_("Black and white"), "Lineart")
        scan = QPushButton(_("Scan page"))
        scan.clicked.connect(self._scan)
        row.addWidget(self.dpi)
        row.addWidget(self.mode)
        row.addWidget(scan)
        sl.addLayout(row)
        sl.addStretch()
        self.tabs.addTab(scanner, _("Scanner"))

        lay.addWidget(QLabel(_("Pages (drag to reorder):")))
        self.pages = QListWidget()
        self.pages.setViewMode(QListWidget.ViewMode.IconMode)
        self.pages.setIconSize(QSize(110, 150))
        self.pages.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.pages.setFixedHeight(190)
        lay.addWidget(self.pages)
        row = QHBoxLayout()
        self.enhance = QCheckBox(_("Document mode (grayscale, more contrast)"))
        self.enhance.setChecked(True)
        remove = QPushButton(_("Remove"))
        remove.clicked.connect(lambda: [self.pages.takeItem(self.pages.row(i)) for i in self.pages.selectedItems()])
        create = QPushButton(_("Create PDF"))
        create.setObjectName("primary")
        create.clicked.connect(self._create)
        row.addWidget(self.enhance)
        row.addStretch()
        row.addWidget(remove)
        row.addWidget(create)
        lay.addLayout(row)
        self._known = 0
        self.timer = QTimer(self, interval=700, timeout=self._poll)
        self._start_server()
        self.resize(640, 620)

    def _start_server(self):
        try:
            self.server = PhoneUploadServer(self.folder)
            self.server.start()
        except OSError as exc:
            self.url_label.setText(str(exc))
            return
        self._update_qr()
        self.timer.start()

    def _update_qr(self, *_args):
        if self.server is None:
            return
        url = self.server.url(self.address.currentData())
        self.qr.setPixmap(qr_pixmap(url))
        self.url_label.setText(url)

    def _add_page(self, path):
        pm = QPixmap(path)
        item = QListWidgetItem(QIcon(pm.scaled(110, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)),
                               str(self.pages.count() + 1))
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.pages.addItem(item)

    def _poll(self):
        with self.server.lock:
            new = self.server.received[self._known:]
            self._known = len(self.server.received)
        for path in new:
            self._add_page(path)

    def _find_scanners(self):
        self.devices.clear()
        found = scanners()
        if not found:
            self.devices.addItem(_("No scanner found (package sane-utils)"), None)
        for device, label in found:
            self.devices.addItem(label, device)

    def _scan(self):
        device = self.devices.currentData()
        if not device:
            self._find_scanners()
            device = self.devices.currentData()
            if not device:
                return
        path = os.path.join(self.folder, f"scan_{self.pages.count() + 1:03d}.png")
        try:
            scan_page(device, path, self.dpi.value(), self.mode.currentData())
        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, _("Scanner"), exc.stderr.decode(errors="replace")[-500:])
            return
        self._add_page(path)

    def _create(self):
        paths = [self.pages.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pages.count())]
        if not paths:
            QMessageBox.warning(self, _("Scan to PDF"), _("There are no pages yet."))
            return
        if self.enhance.isChecked():
            paths = [enhance_document(p) for p in paths]
        out, _f = QFileDialog.getSaveFileName(self, _("Save PDF"), os.path.expanduser("~/Documentos/scan.pdf"),
                                              "PDF (*.pdf)")
        if not out:
            return
        ops.images_to_pdf(paths, out, "a4", margin=0)
        self.main.open_file(out)
        self.accept()

    def done(self, result):
        self.timer.stop()
        if self.server:
            self.server.stop()
        shutil.rmtree(self.folder, ignore_errors=True)
        super().done(result)
