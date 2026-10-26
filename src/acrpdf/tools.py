import base64
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

import pymupdf

from PyQt6.QtCore import QSettings, QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import dialogs, i18n, ops
from .i18n import N_, _

PDF = "PDF (*.pdf)"


@dataclass
class Tool:
    key: str
    name: str
    description: str
    category: str
    glyph: str
    color: str
    inputs: str = "pdf"
    multiple: bool = True
    output: str = "dir"
    suffix: str = ""
    ext: str = "pdf"
    options: list = field(default_factory=list)
    editor: str = ""


CATEGORIES = [N_("Organize PDF"), N_("Optimize PDF"), N_("Convert to PDF"), N_("Convert from PDF"),
              N_("Edit PDF"), N_("PDF security"), N_("Intelligence"), N_("Workflows")]

TOOLS = [
    Tool("merge", N_("Merge PDF"), N_("Combine PDFs, images and documents in the order you want."),
         "Organize PDF", "⧉", "#e5322d", "any", True, "file", ext="pdf"),
    Tool("split", N_("Split PDF"), N_("Split by page ranges or every N pages."), "Organize PDF", "✂", "#e5322d",
         options=["split"]),
    Tool("remove", N_("Remove pages"), N_("Delete the pages you list."), "Organize PDF", "⌫", "#e5322d",
         suffix="_trimmed", options=["pages"]),
    Tool("extract", N_("Extract pages"), N_("Make a new PDF with selected pages."), "Organize PDF", "⇱",
         "#e5322d", suffix="_extract", options=["pages"]),
    Tool("organize", N_("Organize PDF"), N_("Sort, rotate, duplicate and delete pages visually."),
         "Organize PDF", "▦", "#e5322d", multiple=False, editor="organize"),
    Tool("rotate", N_("Rotate PDF"), N_("Rotate all or some pages."), "Organize PDF", "↻", "#e5322d",
         suffix="_rotated", options=["rotate"]),
    Tool("compress", N_("Compress PDF"), N_("Reduce file size keeping the best possible quality."),
         "Optimize PDF", "⇲", "#3d9b35", suffix="_compressed", options=["compress"]),
    Tool("repair", N_("Repair PDF"), N_("Recover data from damaged PDF files."), "Optimize PDF", "⚒", "#3d9b35",
         suffix="_repaired"),
    Tool("ocr", N_("OCR PDF"), N_("Make scanned PDFs searchable and selectable."), "Optimize PDF", "◎",
         "#3d9b35", suffix="_ocr", options=["ocr"]),
    Tool("images2pdf", N_("Images to PDF"), N_("JPG, PNG, SVG… to a single PDF."), "Convert to PDF", "▧",
         "#e8a317", "images", True, "file", options=["page"]),
    Tool("word2pdf", N_("Word to PDF"), N_("DOC, DOCX, ODT, RTF to PDF."), "Convert to PDF", "W", "#2b5797",
         "office"),
    Tool("ppt2pdf", N_("PowerPoint to PDF"), N_("PPT, PPTX, ODP to PDF."), "Convert to PDF", "P", "#d24726",
         "office"),
    Tool("excel2pdf", N_("Excel to PDF"), N_("Spreadsheets to PDF with columns fitted to the page width."),
         "Convert to PDF", "X", "#1e7145", "office", options=["sheet"]),
    Tool("html2pdf", N_("HTML to PDF"), N_("Web pages (paste the address) or HTML files to PDF."),
         "Convert to PDF", "</>", "#e8a317", "office", options=["url"]),
    Tool("scan", N_("Scan to PDF"), N_("Use your phone camera (QR code) or a scanner."), "Convert to PDF", "⎚",
         "#e8a317", editor="scan"),
    Tool("pdf2jpg", N_("PDF to JPG"), N_("Each page as a JPG image, or extract the images."),
         "Convert from PDF", "J", "#e8a317", options=["images"], ext="jpg"),
    Tool("pdf2png", N_("PDF to PNG"), N_("Each page as a PNG image."), "Convert from PDF", "P", "#e8a317",
         options=["dpi"], ext="png"),
    Tool("pdf2word", N_("PDF to Word"), N_("Editable DOCX keeping the layout."), "Convert from PDF", "W",
         "#2b5797", ext="docx"),
    Tool("pdf2ppt", N_("PDF to PowerPoint"), N_("One slide per page."), "Convert from PDF", "P", "#d24726",
         ext="pptx"),
    Tool("pdf2excel", N_("PDF to Excel"), N_("Tables to XLSX spreadsheets."), "Convert from PDF", "X",
         "#1e7145", ext="xlsx"),
    Tool("pdf2pdfa", N_("PDF to PDF/A"), N_("ISO archival format for long-term preservation."),
         "Convert from PDF", "A", "#2d9d78", suffix="_pdfa", options=["pdfa"]),
    Tool("pdf2txt", N_("PDF to text"), N_("Plain text of every page."), "Convert from PDF", "T", "#2d9d78",
         ext="txt"),
    Tool("pdf2md", N_("PDF to Markdown"), N_("Headings, lists, tables and links as Markdown (ideal for notes and LLMs)."),
         "Convert from PDF", "M↓", "#2d9d78", ext="md"),
    Tool("numbers", N_("Add page numbers"), N_("Position, format and typography of your choice."),
         "Edit PDF", "#", "#7d4bc4", suffix="_numbered", options=["numbers"]),
    Tool("watermark", N_("Add watermark"), N_("Text or image over your pages."), "Edit PDF", "≋", "#7d4bc4",
         suffix="_watermark", options=["watermark"]),
    Tool("crop", N_("Crop PDF"), N_("Trim white margins of every page."), "Edit PDF", "⌗", "#7d4bc4",
         suffix="_cropped", options=["margin"]),
    Tool("edit", N_("Edit PDF"), N_("Add text, images, shapes and change fonts."), "Edit PDF", "✎", "#7d4bc4",
         multiple=False, editor="edit"),
    Tool("forms", N_("PDF forms"), N_("Detect fields automatically, create fillable forms or fill them in."),
         "Edit PDF", "☰", "#7d4bc4", multiple=False, editor="forms"),
    Tool("unlock", N_("Unlock PDF"), N_("Remove the password of PDFs you can open."), "PDF security", "🔓",
         "#2c6fd6", suffix="_unlocked", options=["password"]),
    Tool("protect", N_("Protect PDF"), N_("Encrypt with AES-256 and set permissions."), "PDF security", "🔒",
         "#2c6fd6", suffix="_protected", options=["protect"]),
    Tool("sign", N_("Sign PDF"), N_("Sign yourself (handwritten or certificate) or request signatures by e-mail."), "PDF security",
         "✍", "#2c6fd6", multiple=False, editor="certs"),
    Tool("redact", N_("Redact PDF"), N_("Permanently remove sensitive text or areas."), "PDF security", "▬",
         "#2c6fd6", multiple=False, editor="redact"),
    Tool("hideid", N_("Protect DNI / NIE"),
         N_("Watermark \"DNI for … procedure\" and mask the number (AEPD ***4567**), also on photos."),
         "PDF security", "ID", "#2c6fd6", suffix="_protected", options=["hideid"]),
    Tool("compare", N_("Compare PDF"), N_("Highlight the differences between two versions."), "PDF security",
         "⇄", "#2c6fd6", "pdf", True, "file", ext="pdf"),
    Tool("summarize", N_("Summarize with AI"), N_("Clear, concise summaries with the key points."), "Intelligence",
         "✦", "#6a3fd4", suffix="_summary", ext="md", options=["summary"]),
    Tool("translate", N_("Translate PDF"), N_("Translate with AI keeping fonts, layout and formatting."),
         "Intelligence", "文", "#6a3fd4", suffix="_translated", options=["translate"]),
    Tool("workflow", N_("Create a workflow"), N_("Chain your favourite tools and reuse them any time."),
         "Workflows", "⛓", "#555555", editor="workflow"),
]

TOOLS_BY_KEY = {t.key: t for t in TOOLS}

IMAGE_PATTERNS = "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp *.svg"
OFFICE_PATTERNS = "*.doc *.docx *.odt *.rtf *.txt *.xls *.xlsx *.ods *.csv *.ppt *.pptx *.odp *.html *.htm"


def input_filter(kind):
    if kind == "pdf":
        return PDF
    if kind == "images":
        return f"{_('Images')} ({IMAGE_PATTERNS})"
    if kind == "office":
        return f"{_('Documents')} ({OFFICE_PATTERNS})"
    return dialogs.file_filter()


class Options(QWidget):

    def __init__(self, tool):
        super().__init__()
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.getters = []
        for name in tool.options:
            getattr(self, "_" + name)()

    def values(self):
        out = {}
        for getter in self.getters:
            out.update(getter())
        return out

    def _pages(self):
        edit = QLineEdit()
        edit.setPlaceholderText(_("e.g. 1-3, 5, 8-"))
        self.form.addRow(_("Pages:"), edit)
        self.getters.append(lambda: {"spec": edit.text()})

    def _split(self):
        mode = QComboBox()
        mode.addItems([_("Every N pages"), _("Custom ranges")])
        every = QSpinBox()
        every.setRange(1, 9999)
        ranges = QLineEdit()
        ranges.setPlaceholderText(_("e.g. 1-3, 4-6, 7-"))
        self.form.addRow(_("Mode:"), mode)
        self.form.addRow(_("Pages per file:"), every)
        self.form.addRow(_("Ranges:"), ranges)
        self.getters.append(lambda: {"every": every.value()} if mode.currentIndex() == 0
                            else {"ranges": ranges.text()})

    def _rotate(self):
        angle = QComboBox()
        for a, label in ((90, _("90° clockwise")), (180, "180°"), (270, _("90° counter-clockwise"))):
            angle.addItem(label, a)
        pages = QLineEdit()
        pages.setPlaceholderText(_("all pages"))
        self.form.addRow(_("Rotation:"), angle)
        self.form.addRow(_("Pages:"), pages)
        self.getters.append(lambda: {"angle": angle.currentData(), "spec": pages.text()})

    def _compress(self):
        level = QComboBox()
        level.addItem(_("Extreme compression (less quality, 72 dpi)"), "extreme")
        level.addItem(_("Recommended compression (good quality, 150 dpi)"), "recommended")
        level.addItem(_("Low compression (high quality, 300 dpi)"), "low")
        level.setCurrentIndex(1)
        self.form.addRow(_("Level:"), level)
        self.getters.append(lambda: {"level": level.currentData()})

    def _ocr(self):
        langs = ops.ocr_languages()
        combo = QComboBox()
        combo.setEditable(True)
        default = "+".join(lang for lang in ("spa", "eng") if lang in langs) or (langs[0] if langs else "eng")
        combo.addItems([default] + [lang for lang in langs if lang != default])
        self.form.addRow(_("Language:"), combo)
        if not langs:
            warn = QLabel(_("Tesseract is not installed: sudo apt install tesseract-ocr tesseract-ocr-spa"))
            warn.setStyleSheet("color:#c62828;")
            self.form.addRow(warn)
        self.getters.append(lambda: {"language": combo.currentText()})

    def _page(self):
        size = QComboBox()
        size.addItem("A4", "a4")
        size.addItem(_("Letter"), "letter")
        size.addItem(_("Same as image"), "fit")
        landscape = QCheckBox(_("Landscape"))
        margin = QSpinBox()
        margin.setRange(0, 100)
        margin.setValue(20)
        margin.setSuffix(" pt")
        self.form.addRow(_("Page size:"), size)
        self.form.addRow(landscape)
        self.form.addRow(_("Margin:"), margin)
        self.getters.append(lambda: {"page_size": size.currentData(), "landscape": landscape.isChecked(),
                                     "margin": margin.value()})

    def _dpi(self):
        dpi = QSpinBox()
        dpi.setRange(36, 600)
        dpi.setValue(150)
        dpi.setSuffix(" dpi")
        self.form.addRow(_("Resolution:"), dpi)
        self.getters.append(lambda: {"dpi": dpi.value()})

    def _images(self):
        mode = QComboBox()
        mode.addItem(_("Convert every page to an image"), "pages")
        mode.addItem(_("Extract the embedded images"), "extract")
        self.form.addRow(_("Mode:"), mode)
        self._dpi()
        self.getters.append(lambda: {"mode": mode.currentData()})

    def _pdfa(self):
        level = QComboBox()
        for v in (2, 1, 3):
            level.addItem(f"PDF/A-{v}b", v)
        self.form.addRow(_("Conformance:"), level)
        self.getters.append(lambda: {"level": level.currentData()})

    def _numbers(self):
        btn = QPushButton(_("Configure…"))
        self._numbers_opts = {}

        def configure():
            d = dialogs.PageNumbersDialog(self)
            if d.exec():
                self._numbers_opts = d.options()
                btn.setText(d.options()["fmt"])
        btn.clicked.connect(configure)
        self.form.addRow(_("Numbering:"), btn)
        self.getters.append(lambda: self._numbers_opts)

    def _watermark(self):
        btn = QPushButton(_("Configure…"))
        self._wm_opts = {"text": _("CONFIDENTIAL")}

        def configure():
            d = dialogs.WatermarkDialog(self)
            if d.exec():
                self._wm_opts = d.options()
                btn.setText(self._wm_opts["text"] if not self._wm_opts["image"] else _("Image"))
        btn.clicked.connect(configure)
        self.form.addRow(_("Watermark:"), btn)
        self.getters.append(lambda: self._wm_opts)

    def _margin(self):
        margin = QSpinBox()
        margin.setRange(0, 200)
        margin.setValue(10)
        margin.setSuffix(" pt")
        self.form.addRow(_("Keep margin:"), margin)
        self.getters.append(lambda: {"margin": margin.value()})

    def _password(self):
        pw = QLineEdit()
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.form.addRow(_("Current password:"), pw)
        self.getters.append(lambda: {"password": pw.text()})

    def _protect(self):
        btn = QPushButton(_("Set password…"))
        self._protect_opts = None

        def configure():
            d = dialogs.ProtectDialog(self)
            if d.exec():
                self._protect_opts = d.options()
                btn.setText("••••••")
        btn.clicked.connect(configure)
        self.form.addRow(_("Password:"), btn)
        self.getters.append(lambda: self._protect_opts or {})

    def _sheet(self):
        landscape = QCheckBox(_("Landscape"))
        fit = QCheckBox(_("Fit all columns to the page width"))
        fit.setChecked(True)
        self.form.addRow(landscape)
        self.form.addRow(fit)
        self.getters.append(lambda: {"landscape": landscape.isChecked(), "fit_width": fit.isChecked()})

    def _url(self):
        url = QLineEdit()
        url.setPlaceholderText("https://…")
        self.form.addRow(_("Web address:"), url)
        self.getters.append(lambda: {"url": url.text().strip()})

    def _target_language(self):
        combo = QComboBox()
        for code, name in (("es", "Español"), ("en", "English"), ("fr", "Français"), ("pt", "Português"),
                           ("de", "Deutsch"), ("it", "Italiano"), ("ca", "Català"), ("gl", "Galego"),
                           ("eu", "Euskara"), ("nl", "Nederlands"), ("pl", "Polski"), ("zh", "中文"),
                           ("ja", "日本語"), ("ar", "العربية")):
            combo.addItem(name, code)
        combo.setCurrentIndex(max(0, combo.findData(i18n.language())))
        return combo

    def _summary(self):
        lang = self._target_language()
        style = QComboBox()
        style.addItem(_("Overview and key points"), "bullets")
        style.addItem(_("One short paragraph"), "short")
        style.addItem(_("Detailed, by sections"), "detailed")
        self.form.addRow(_("Language:"), lang)
        self.form.addRow(_("Style:"), style)
        self._ai_note()
        self.getters.append(lambda: {"language": lang.currentData(), "style": style.currentData()})

    def _translate(self):
        lang = self._target_language()
        self.form.addRow(_("Translate to:"), lang)
        self._ai_note()
        self.getters.append(lambda: {"target": lang.currentData()})

    def _ai_note(self):
        note = QLabel(_("Uses the AI provider chosen in Preferences (Claude, ChatGPT, DeepSeek or a local "
                        "Ollama model). With online providers the document text is sent to that company."))
        note.setWordWrap(True)
        note.setStyleSheet("color:#666;")
        self.form.addRow(note)

    def _hideid(self):
        mode = QComboBox()
        mode.addItem(_("Mask, keeping 4 digits (AEPD): ***4567**"), "mask")
        mode.addItem(_("Black box (remove completely)"), "black")
        purpose = QLineEdit(QSettings().value("idwm/purpose", ""))
        purpose.setPlaceholderText(_("e.g. RENTAL WITH IDEALISTA"))
        watermark = QCheckBox(_("Add watermark with the purpose"))
        watermark.setChecked(True)
        flatten = QCheckBox(_("Merge into an image (the watermark cannot be removed)"))
        flatten.setChecked(True)
        self.form.addRow(_("Mode:"), mode)
        self.form.addRow(_("Procedure / purpose:"), purpose)
        self.form.addRow(watermark)
        self.form.addRow(flatten)
        self.getters.append(lambda: {"mode": mode.currentData(), "purpose": purpose.text().strip(),
                                     "watermark": watermark.isChecked(), "flatten": flatten.isChecked()})


def _out_name(out_dir, path, suffix, ext):
    stem = os.path.splitext(os.path.basename(path))[0]
    candidate = os.path.join(out_dir, f"{stem}{suffix}.{ext}")
    i = 2
    while os.path.exists(candidate):
        candidate = os.path.join(out_dir, f"{stem}{suffix}_{i}.{ext}")
        i += 1
    return candidate


def run_tool(tool, inputs, target, opts):
    k = tool.key
    if k == "merge":
        return ops.merge(inputs, target), ""
    if k == "images2pdf":
        return ops.images_to_pdf(inputs, target, opts.get("page_size", "a4"), opts.get("margin", 20),
                                 opts.get("landscape", False)), ""
    if k == "html2pdf" and opts.get("url"):
        return ops.html_to_pdf(opts["url"], target if target.lower().endswith(".pdf")
                               else os.path.join(target, "web.pdf")), ""
    if k == "workflow":
        return run_workflow(opts["steps"], inputs, target, opts.get("name", "workflow"))
    if k == "compare":
        if len(inputs) != 2:
            raise ops.OperationError(_("Choose exactly two PDF files (original first)."))
        outputs, n = ops.compare(inputs[0], inputs[1], target)
        return outputs, _("%d differences highlighted.") % n
    outputs, notes = [], []
    for path in inputs:
        out = _out_name(target, path, tool.suffix, tool.ext)
        if k == "split":
            outputs += ops.split(path, target, ranges=opts.get("ranges"), every=opts.get("every"))
        elif k == "remove":
            outputs += ops.remove_pages(path, out, opts["spec"])
        elif k == "extract":
            outputs += ops.extract(path, out, opts["spec"])
        elif k == "rotate":
            outputs += ops.rotate_file(path, out, opts["angle"], opts.get("spec", ""))
        elif k == "compress":
            before = os.path.getsize(path)
            outputs += ops.compress(path, out, opts["level"])
            after = os.path.getsize(out)
            notes.append(f"{os.path.basename(path)}: {before / 1024:.0f} KB → {after / 1024:.0f} KB "
                         f"(−{max(0, 100 - after * 100 / max(before, 1)):.0f}%)")
        elif k == "repair":
            outputs += ops.repair(path, out)
        elif k == "ocr":
            outputs += ops.ocr(path, out, opts.get("language", "spa+eng"))
        elif k == "excel2pdf":
            outputs += ops.excel_to_pdf(path, _out_name(target, path, "", "pdf"), opts.get("landscape", False),
                                        opts.get("fit_width", True))
        elif k == "html2pdf":
            outputs += ops.html_to_pdf(path, _out_name(target, path, "", "pdf"))
        elif k == "pdf2md":
            outputs += ops.pdf_to_markdown(path, out)
        elif k == "summarize":
            from . import ai
            text = ai.summarize(ai.provider_from_settings(QSettings()), ops.document_text(path),
                                opts.get("language", "es"), opts.get("style", "bullets"))
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            outputs.append(out)
            notes.append(text)
        elif k == "translate":
            from . import ai
            provider = ai.provider_from_settings(QSettings())
            outputs += ops.translate_pdf(path, out, lambda texts: ai.translate_texts(provider, texts,
                                                                                       opts.get("target", "es")))
        elif k in ("word2pdf", "ppt2pdf"):
            outputs.append(ops.office_to_pdf(path, _out_name(target, path, "", "pdf")))
        elif k == "pdf2jpg":
            outputs += ops.pdf_to_images(path, target, "jpg", opts.get("dpi", 150), opts.get("mode", "pages"))
        elif k == "pdf2png":
            outputs += ops.pdf_to_images(path, target, "png", opts.get("dpi", 150))
        elif k == "pdf2word":
            outputs += ops.pdf_to_word(path, out)
        elif k == "pdf2ppt":
            outputs += ops.pdf_to_powerpoint(path, out)
        elif k == "pdf2excel":
            outputs += ops.pdf_to_excel(path, out)
        elif k == "pdf2pdfa":
            outputs += ops.pdf_to_pdfa(path, out, opts.get("level", 2))
        elif k == "pdf2txt":
            outputs += ops.pdf_to_text(path, out)
        elif k == "numbers":
            outputs += ops.numbers_file(path, out, **opts)
        elif k == "watermark":
            outputs += ops.watermark_file(path, out, **opts)
        elif k == "crop":
            outputs += ops.crop_margins_file(path, out, opts.get("margin", 10))
        elif k == "unlock":
            outputs += ops.unlock(path, out, opts.get("password", ""))
        elif k == "protect":
            if not opts:
                raise ops.OperationError(_("Set a password first."))
            outputs += ops.protect(path, out, **opts)
        elif k == "hideid":
            with open(path, "rb") as f:
                data = f.read()
            hits = ops.scan_ids(pymupdf.open("pdf", data))
            wm = None
            if opts.get("watermark", True):
                s = QSettings()
                wm = ops.IdWatermark(purpose=opts.get("purpose", ""),
                                     text=s.value("idwm/text", _("ONLY FOR {purpose} · {date}")),
                                     footer=s.value("idwm/footer", _("{doc} for {purpose}")),
                                     size=float(s.value("idwm/size", 16)), opacity=float(s.value("idwm/opacity", 35)) / 100)
            with open(out, "wb") as f:
                f.write(ops.protect_identity(data, hits, opts.get("mode", "mask"), wm, opts.get("flatten", True)))
            outputs.append(out)
            notes.append(_("%(file)s: %(n)d ID numbers hidden") % {"file": os.path.basename(path), "n": len(hits)})
    return outputs, "\n".join(notes)


WORKFLOW_STEPS = ("unlock", "repair", "rotate", "remove", "extract", "numbers", "watermark", "crop", "hideid",
                  "ocr", "compress", "pdf2pdfa", "translate", "protect")


def _encode(value):
    if isinstance(value, bytes):
        return {"__b64__": base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {"__b64__"}:
            return base64.b64decode(value["__b64__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def load_workflows():
    try:
        return _decode(json.loads(QSettings().value("workflows", "[]")))
    except (TypeError, ValueError):
        return []


def save_workflows(workflows):
    QSettings().setValue("workflows", json.dumps(_encode(workflows)))


def run_workflow(steps, inputs, out_dir, name):
    if not steps:
        raise ops.OperationError(_("The workflow has no steps."))
    outputs = []
    for path in inputs:
        work = tempfile.mkdtemp(prefix="acrpdf-wf-")
        current = path
        for key, opts in steps:
            produced, _msg = run_tool(TOOLS_BY_KEY[key], [current], work, dict(opts))
            current = produced[0]
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        final = _out_name(out_dir, path, "_" + safe, "pdf")
        shutil.copyfile(current, final)
        shutil.rmtree(work, ignore_errors=True)
        outputs.append(final)
    return outputs, ""


class StepDialog(QDialog):
    def __init__(self, parent, key):
        super().__init__(parent)
        tool = TOOLS_BY_KEY[key]
        self.setWindowTitle(_(tool.name))
        lay = QVBoxLayout(self)
        self.options = Options(tool)
        lay.addWidget(self.options if tool.options else QLabel(_("This step has no options.")))
        lay.addWidget(dialogs.buttons(self))


class WorkflowDialog(QDialog):

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(_("Workflows"))
        self.workflows = load_workflows()
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>" + _("Saved workflows") + "</b>"))
        self.saved = QListWidget()
        self.saved.currentRowChanged.connect(self._load)
        left.addWidget(self.saved)
        row = QHBoxLayout()
        new = QPushButton(_("New"))
        new.clicked.connect(self._new)
        delete = QPushButton(_("Delete"))
        delete.clicked.connect(self._delete)
        row.addWidget(new)
        row.addWidget(delete)
        left.addLayout(row)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        form.addRow(_("Name:"), self.name)
        right.addLayout(form)
        right.addWidget(QLabel(_("Steps (run from top to bottom):")))
        self.steps = QListWidget()
        self.steps.itemDoubleClicked.connect(self._configure)
        right.addWidget(self.steps)
        row = QHBoxLayout()
        self.step_combo = QComboBox()
        for key in WORKFLOW_STEPS:
            t = TOOLS_BY_KEY[key]
            self.step_combo.addItem(dialogs.glyph_icon(t.glyph, t.color), _(t.name), key)
        add = QPushButton(_("Add step"))
        add.clicked.connect(self._add_step)
        row.addWidget(self.step_combo, 1)
        row.addWidget(add)
        right.addLayout(row)
        row = QHBoxLayout()
        for text, slot in ((_("Options…"), lambda: self._configure(self.steps.currentItem())),
                           (_("Up"), lambda: self._move(-1)), (_("Down"), lambda: self._move(1)),
                           (_("Remove"), self._remove_step)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        right.addLayout(row)
        row = QHBoxLayout()
        save = QPushButton(_("Save"))
        save.clicked.connect(self._save)
        run = QPushButton(_("Run on files…"))
        run.setObjectName("primary")
        run.clicked.connect(self._run)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(close)
        row.addWidget(save)
        row.addWidget(run)
        right.addLayout(row)
        lay.addLayout(right, 2)
        self.current = []
        for wf in self.workflows:
            self.saved.addItem(wf["name"])
        if self.workflows:
            self.saved.setCurrentRow(0)
        else:
            self._new()
        self.resize(760, 480)

    def _refresh_steps(self):
        self.steps.clear()
        for i, (key, opts) in enumerate(self.current, 1):
            t = TOOLS_BY_KEY[key]
            summary = ", ".join(f"{k}={v}" for k, v in opts.items() if not isinstance(v, (bytes, dict)) and v not in ("", None))
            self.steps.addItem(QListWidgetItem(dialogs.glyph_icon(t.glyph, t.color),
                                               f"{i}. {_(t.name)}" + (f"  ({summary[:60]})" if summary else "")))

    def _load(self, row):
        if 0 <= row < len(self.workflows):
            wf = self.workflows[row]
            self.name.setText(wf["name"])
            self.current = [tuple(step) for step in wf["steps"]]
            self._refresh_steps()

    def _new(self):
        self.saved.clearSelection()
        self.name.setText(_("My workflow"))
        self.current = []
        self._refresh_steps()

    def _delete(self):
        row = self.saved.currentRow()
        if 0 <= row < len(self.workflows):
            del self.workflows[row]
            self.saved.takeItem(row)
            save_workflows(self.workflows)

    def _add_step(self):
        key = self.step_combo.currentData()
        opts = {}
        if TOOLS_BY_KEY[key].options:
            d = StepDialog(self, key)
            if not d.exec():
                return
            opts = d.options.values()
        self.current.append((key, opts))
        self._refresh_steps()

    def _configure(self, item):
        if item is None:
            return
        row = self.steps.row(item)
        key = self.current[row][0]
        d = StepDialog(self, key)
        if d.exec():
            self.current[row] = (key, d.options.values())
            self._refresh_steps()

    def _move(self, delta):
        r = self.steps.currentRow()
        if 0 <= r + delta < len(self.current) and r >= 0:
            self.current[r], self.current[r + delta] = self.current[r + delta], self.current[r]
            self._refresh_steps()
            self.steps.setCurrentRow(r + delta)

    def _remove_step(self):
        r = self.steps.currentRow()
        if r >= 0:
            del self.current[r]
            self._refresh_steps()

    def _save(self):
        name = self.name.text().strip() or _("My workflow")
        wf = {"name": name, "steps": [list(s) for s in self.current]}
        names = [w["name"] for w in self.workflows]
        if name in names:
            self.workflows[names.index(name)] = wf
        else:
            self.workflows.append(wf)
            self.saved.addItem(name)
        save_workflows(self.workflows)
        return wf

    def _run(self):
        wf = self._save()
        tool = Tool("workflow", wf["name"], _("Workflow: %s") % " → ".join(_(TOOLS_BY_KEY[k].name) for k, _o in wf["steps"]),
                    "Workflows", "⛓", "#555555", suffix="_" + wf["name"])
        dialog = ToolDialog(tool, self.main, preset={"steps": wf["steps"], "name": wf["name"]})
        dialog.exec()


class Worker(QThread):
    finished_ok = pyqtSignal(list, str)
    failed = pyqtSignal(str)

    def __init__(self, tool, inputs, target, opts):
        super().__init__()
        self.args = (tool, inputs, target, opts)

    def run(self):
        try:
            outputs, message = run_tool(*self.args)
        except ops.OperationError as exc:
            self.failed.emit(str(exc))
        except subprocess.CalledProcessError as exc:
            self.failed.emit((exc.stderr or b"").decode("utf-8", "replace")[-800:] or str(exc))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished_ok.emit(outputs, message)


class DropList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.source() is self:
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                if url.isLocalFile():
                    self.addItem(url.toLocalFile())
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class ToolDialog(QDialog):
    def __init__(self, tool, parent=None, files=(), preset=None):
        super().__init__(parent)
        self.tool = tool
        self.preset = preset or {}
        self.main = parent
        self.setWindowTitle(_(tool.name))
        lay = QVBoxLayout(self)
        head = QLabel(f"<h2 style='margin:0'>{_(tool.name)}</h2><p style='color:#555'>{_(tool.description)}</p>")
        lay.addWidget(head)
        lay.addWidget(QLabel(_("Files (drag and drop here; the order matters for merging):")))
        self.list = DropList()
        for f in files:
            self.list.addItem(f)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, slot in ((_("Add files…"), self._add), (_("Remove"), self._remove), (_("Clear"), self.list.clear)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.options = Options(tool)
        if tool.options:
            lay.addWidget(self.options)
        out_row = QHBoxLayout()
        self.out = QLineEdit()
        b = QPushButton("…")
        b.clicked.connect(self._choose_out)
        out_row.addWidget(QLabel(_("Save to:") if tool.output == "file" else _("Output folder:")))
        out_row.addWidget(self.out, 1)
        out_row.addWidget(b)
        lay.addLayout(out_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        lay.addWidget(self.progress)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(110)
        self.result.hide()
        lay.addWidget(self.result)
        row = QHBoxLayout()
        self.open_dir = QPushButton(_("Open folder"))
        self.open_dir.hide()
        self.open_doc = QPushButton(_("Open in ACRPDF"))
        self.open_doc.hide()
        self.preview_btn = QPushButton(_("Preview"))
        self.preview_btn.setToolTip(_("Process the first file and show the result before saving anything"))
        self.preview_btn.clicked.connect(self._preview)
        self.preview_btn.setVisible(tool.ext == "pdf")
        self.run_btn = QPushButton(_(tool.name))
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.reject)
        row.addWidget(self.open_dir)
        row.addWidget(self.open_doc)
        row.addStretch()
        row.addWidget(close)
        row.addWidget(self.preview_btn)
        row.addWidget(self.run_btn)
        lay.addLayout(row)
        self.outputs = []
        self.resize(640, 560)
        if not files:
            self._add()

    def _add(self):
        paths, _f = QFileDialog.getOpenFileNames(self, _("Add files"), os.path.expanduser("~/Documentos"),
                                                 input_filter(self.tool.inputs))
        for p in paths:
            self.list.addItem(p)
        if paths and not self.out.text():
            first = paths[0]
            if self.tool.output == "file":
                self.out.setText(_out_name(os.path.dirname(first), first, "_" + self.tool.key, self.tool.ext))
            else:
                self.out.setText(os.path.dirname(first))

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _choose_out(self):
        if self.tool.output == "file":
            p, _f = QFileDialog.getSaveFileName(self, _("Save as"), self.out.text(), f"*.{self.tool.ext}")
        else:
            p = QFileDialog.getExistingDirectory(self, _("Output folder"), self.out.text())
        if p:
            self.out.setText(p)

    def files(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _run(self):
        files = self.files()
        if not files and not (self.tool.key == "html2pdf" and self.options.values().get("url")):
            QMessageBox.warning(self, _(self.tool.name), _("Add at least one file."))
            return
        target = self.out.text().strip()
        if not target:
            self._choose_out()
            target = self.out.text().strip()
            if not target:
                return
        if self.tool.output == "dir":
            os.makedirs(target, exist_ok=True)
        self.run_btn.setEnabled(False)
        self.progress.show()
        self.result.hide()
        opts = dict(self.options.values(), **self.preset)
        self.worker = Worker(self.tool, files, target, opts)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _preview(self):
        files = self.files()
        if not files:
            QMessageBox.warning(self, _(self.tool.name), _("Add at least one file."))
            return
        self._preview_dir = tempfile.mkdtemp(prefix="acrpdf-preview-")
        inputs = files if self.tool.output == "file" else files[:1]
        target = os.path.join(self._preview_dir, "preview.pdf") if self.tool.output == "file" else self._preview_dir
        self.preview_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.progress.show()
        self.worker = Worker(self.tool, inputs, target, dict(self.options.values(), **self.preset))
        self.worker.finished_ok.connect(self._show_preview)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _show_preview(self, outputs, _message):
        self.progress.hide()
        self.preview_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        pdfs = [o for o in outputs if o.lower().endswith(".pdf")]
        if not pdfs:
            return
        with open(pdfs[0], "rb") as f:
            data = f.read()
        first = self.files()[0]
        default = self.out.text() if self.tool.output == "file" else \
            _out_name(self.out.text() or os.path.dirname(first), first, self.tool.suffix, "pdf")
        d = dialogs.PreviewDialog(self, _(self.tool.name), data, default)
        if d.exec() and d.saved_path and self.main is not None:
            self.main.open_file(d.saved_path)
        shutil.rmtree(self._preview_dir, ignore_errors=True)

    def _done(self, outputs, message):
        self.progress.hide()
        self.run_btn.setEnabled(True)
        self.outputs = outputs
        if self.tool.key == "ocr" and outputs and self.main is not None:
            for path in outputs[1:]:
                self.main.open_file(path)
            self.accept()
            self.main.open_ocr_result(outputs[0], temporary=False)
            return
        text = _("Done: %d file(s) created.") % len(outputs) + "\n" + "\n".join(outputs[:20])
        if message:
            text = message + "\n\n" + text
        self.result.setPlainText(text)
        self.result.show()
        if outputs:
            folder = os.path.dirname(outputs[0])
            self.open_dir.show()
            self.open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
            pdfs = [o for o in outputs if o.lower().endswith(".pdf")]
            if pdfs and self.main is not None:
                self.open_doc.show()
                self.open_doc.clicked.connect(lambda: [self.main.open_file(p) for p in pdfs[:10]])

    def _failed(self, message):
        self.progress.hide()
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, _(self.tool.name), message)
