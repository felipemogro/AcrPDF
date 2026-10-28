import os
import tempfile

from PyQt6.QtCore import QMarginsF, QSettings, QSize, Qt, QUrl
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QFont, QImage, QKeySequence, QPageLayout, QPageSize,
                         QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextDocumentWriter,
                         QTextFormat, QTextFrameFormat, QTextImageFormat, QTextLength, QTextListFormat,
                         QTextTableFormat)
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QFontComboBox, QHBoxLayout, QInputDialog,
                             QMainWindow, QMessageBox, QPushButton, QSizePolicy, QTextEdit, QToolBar, QWidget)

from . import APP_NAME
from .dialogs import glyph_icon
from .i18n import _

PAGE_WIDTH = 794  # A4 at 96 dpi
PAGE_MARGIN = 72  # 2 cm at 96 dpi
SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72)
STYLES = ((0, "Normal"), (1, "Heading 1"), (2, "Heading 2"), (3, "Heading 3"))
HEADING_SIZES = {1: 20, 2: 16, 3: 13}
OPEN_FILTER = "*.odt *.html *.htm *.md *.txt"


class WriterWindow(QMainWindow):
    """A small word processor: what you type becomes a PDF opened in AcrPDF."""

    def __init__(self, main):
        super().__init__(main, Qt.WindowType.Window)
        self.main = main
        self.path = None
        self.resize(1100, 860)
        self.setWindowIcon(main.windowIcon())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        self.edit.setFixedWidth(PAGE_WIDTH)
        self.edit.setStyleSheet("QTextEdit { background: #ffffff; border: 1px solid #cfcfcf; }")
        doc = self.edit.document()
        doc.setDocumentMargin(PAGE_MARGIN)
        doc.setDefaultFont(QFont("Liberation Serif", 12))
        self.edit.setFontPointSize(12)
        page = QWidget()
        page.setStyleSheet("background: #e8e8e8;")
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 16, 0, 0)
        lay.addStretch()
        lay.addWidget(self.edit)
        lay.addStretch()
        self.setCentralWidget(page)

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self.edit.currentCharFormatChanged.connect(self._char_format_changed)
        self.edit.cursorPositionChanged.connect(self._cursor_moved)
        doc.modificationChanged.connect(lambda _m: self._update_title())
        self._char_format_changed(self.edit.currentCharFormat())
        self._cursor_moved()
        self._update_title()
        self.edit.setFocus()

    # ---------------------------------------------------------------- UI
    def _act(self, text, slot, shortcut=None, glyph=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if glyph:
            a.setIcon(glyph_icon(glyph, None, "#3c3c3c", 48))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        e = self.edit
        self.a_new = self._act(_("New"), self.new_document, "Ctrl+N", "🗋")
        self.a_open = self._act(_("Open…"), self.open_document, "Ctrl+O", "📂")
        self.a_save = self._act(_("Save"), self.save, "Ctrl+S", "💾")
        self.a_save_as = self._act(_("Save as…"), self.save_as, "Ctrl+Shift+S")
        self.a_export = self._act(_("Export to PDF…"), self.export_pdf, "Ctrl+E")
        self.a_create = self._act(_("Create PDF"), self.create_pdf, "Ctrl+Shift+P")
        self.a_undo = self._act(_("Undo"), e.undo, "Ctrl+Z", "↶")
        self.a_redo = self._act(_("Redo"), e.redo, "Ctrl+Y", "↷")
        e.undoAvailable.connect(self.a_undo.setEnabled)
        e.redoAvailable.connect(self.a_redo.setEnabled)
        self.a_undo.setEnabled(False)
        self.a_redo.setEnabled(False)
        self.a_bold = self._act(_("Bold"), self._bold, "Ctrl+B", "B", True)
        self.a_italic = self._act(_("Italic"), lambda on: self._merge(italic=on), "Ctrl+I", "I", True)
        self.a_underline = self._act(_("Underline"), lambda on: self._merge(underline=on), "Ctrl+U", "U", True)
        self.a_strike = self._act(_("Strikethrough"), lambda on: self._merge(strike=on), None, "S", True)
        f = self.a_italic.font()
        f.setItalic(True)
        self.a_italic.setFont(f)
        self.a_color = self._act(_("Text color"), self._text_color, None, "A")
        self.a_highlight = self._act(_("Highlight"), self._highlight, None, "▮")
        self.align_group = QActionGroup(self)
        self.a_align = {}
        for flag, text, key, glyph in ((Qt.AlignmentFlag.AlignLeft, _("Align left"), "Ctrl+L", "⇤"),
                                       (Qt.AlignmentFlag.AlignHCenter, _("Align center"), "Ctrl+Shift+E", "↔"),
                                       (Qt.AlignmentFlag.AlignRight, _("Align right"), "Ctrl+R", "⇥"),
                                       (Qt.AlignmentFlag.AlignJustify, _("Justify"), "Ctrl+J", "☰")):
            a = self._act(text, lambda _c, fl=flag: self.edit.setAlignment(fl), key, glyph, True)
            self.align_group.addAction(a)
            self.a_align[flag] = a
        self.a_bullets = self._act(_("Bulleted list"), lambda: self._list(QTextListFormat.Style.ListDisc),
                                   None, "•")
        self.a_numbers = self._act(_("Numbered list"), lambda: self._list(QTextListFormat.Style.ListDecimal),
                                   None, "1.")
        self.a_indent = self._act(_("Increase indent"), lambda: self._indent(1), "Ctrl+]", "→")
        self.a_outdent = self._act(_("Decrease indent"), lambda: self._indent(-1), "Ctrl+[", "←")
        self.a_image = self._act(_("Image…"), self.insert_image, None, "▣")
        self.a_table = self._act(_("Table…"), self.insert_table, None, "▦")
        self.a_break = self._act(_("Page break"), self.insert_page_break, "Ctrl+Return", "⤓")
        self.a_rule = self._act(_("Horizontal line"), lambda: self.edit.insertHtml("<hr/>"), None, "―")

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(_("&File"))
        for a in (self.a_new, self.a_open, None, self.a_save, self.a_save_as, None, self.a_create, self.a_export,
                  None):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction(self._act(_("Close"), self.close, "Ctrl+W"))
        m = mb.addMenu(_("&Edit"))
        for a in (self.a_undo, self.a_redo):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self._act(_("Cut"), self.edit.cut, "Ctrl+X"))
        m.addAction(self._act(_("Copy"), self.edit.copy, "Ctrl+C"))
        m.addAction(self._act(_("Paste"), self.edit.paste, "Ctrl+V"))
        m.addAction(self._act(_("Select all"), self.edit.selectAll, "Ctrl+A"))
        m = mb.addMenu(_("&Insert"))
        for a in (self.a_image, self.a_table, self.a_rule, self.a_break):
            m.addAction(a)
        m = mb.addMenu(_("F&ormat"))
        for a in (self.a_bold, self.a_italic, self.a_underline, self.a_strike, None, self.a_color,
                  self.a_highlight, None, *self.a_align.values(), None, self.a_bullets, self.a_numbers,
                  self.a_indent, self.a_outdent):
            m.addSeparator() if a is None else m.addAction(a)

    def _build_toolbars(self):
        tb = QToolBar(_("File"))
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        self.addToolBar(tb)
        for a in (self.a_new, self.a_open, self.a_save, None, self.a_undo, self.a_redo):
            tb.addSeparator() if a is None else tb.addAction(a)
        tb.addSeparator()
        self.style_combo = QComboBox()
        for level, name in STYLES:
            self.style_combo.addItem(_(name), level)
        self.style_combo.activated.connect(lambda i: self._apply_style(self.style_combo.itemData(i)))
        tb.addWidget(self.style_combo)
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(lambda f: self._merge(family=f.family()))
        tb.addWidget(self.font_combo)
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        for s in SIZES:
            self.size_combo.addItem(str(s))
        self.size_combo.textActivated.connect(self._size)
        tb.addWidget(self.size_combo)
        stretch = QWidget()
        stretch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(stretch)
        create = QPushButton(_("Create PDF"))
        create.setStyleSheet("QPushButton { background: #c8102e; color: white; border-radius: 14px; "
                             "padding: 6px 18px; font-weight: 600; border: none; }"
                             "QPushButton:hover { background: #a50d26; }")
        create.setToolTip(_("Convert this document into a PDF and open it in %s") % APP_NAME)
        create.clicked.connect(self.create_pdf)
        tb.addWidget(create)

        self.addToolBarBreak()
        fmt = QToolBar(_("Format"))
        fmt.setIconSize(QSize(20, 20))
        fmt.setMovable(False)
        self.addToolBar(fmt)
        for a in (self.a_bold, self.a_italic, self.a_underline, self.a_strike, None, self.a_color,
                  self.a_highlight, None, *self.a_align.values(), None, self.a_bullets, self.a_numbers,
                  self.a_outdent, self.a_indent, None, self.a_image, self.a_table, self.a_rule, self.a_break):
            fmt.addSeparator() if a is None else fmt.addAction(a)

    # ------------------------------------------------------ formatting
    def _merge(self, family=None, size=None, italic=None, underline=None, strike=None, weight=None,
               color=None, background=None):
        f = QTextCharFormat()
        if family is not None:
            f.setFontFamilies([family])
        if size is not None:
            f.setFontPointSize(size)
        if italic is not None:
            f.setFontItalic(italic)
        if underline is not None:
            f.setFontUnderline(underline)
        if strike is not None:
            f.setFontStrikeOut(strike)
        if weight is not None:
            f.setFontWeight(weight)
        if color is not None:
            f.setForeground(color)
        if background is not None:
            f.setBackground(background)
        cursor = self.edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(f)
        self.edit.mergeCurrentCharFormat(f)
        self.edit.setFocus()

    def _bold(self, on):
        self._merge(weight=QFont.Weight.Bold if on else QFont.Weight.Normal)

    def _size(self, text):
        try:
            size = float(text.replace(",", "."))
        except ValueError:
            return
        if 1 <= size <= 400:
            self._merge(size=size)

    def _text_color(self):
        c = QColorDialog.getColor(self.edit.textColor(), self, _("Text color"))
        if c.isValid():
            self._merge(color=c)

    def _highlight(self):
        c = QColorDialog.getColor(QColor("#fff176"), self, _("Highlight"))
        if c.isValid():
            self._merge(background=c)

    def _list(self, style):
        cursor = self.edit.textCursor()
        current = cursor.currentList()
        cursor.beginEditBlock()
        if current and current.format().style() == style:
            for i in reversed(range(current.count())):
                current.remove(current.item(i))
            block = cursor.blockFormat()
            block.setIndent(0)
            cursor.setBlockFormat(block)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            fmt.setIndent(max(1, cursor.blockFormat().indent()))
            cursor.createList(fmt)
        cursor.endEditBlock()

    def _indent(self, delta):
        cursor = self.edit.textCursor()
        lst = cursor.currentList()
        if lst:
            fmt = lst.format()
            fmt.setIndent(max(1, fmt.indent() + delta))
            lst.setFormat(fmt)
            return
        block = cursor.blockFormat()
        block.setIndent(max(0, block.indent() + delta))
        cursor.setBlockFormat(block)

    def _apply_style(self, level):
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        block = cursor.blockFormat()
        block.setHeadingLevel(level)
        cursor.setBlockFormat(block)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        f = QTextCharFormat()
        f.setFontWeight(QFont.Weight.Bold if level else QFont.Weight.Normal)
        f.setFontPointSize(HEADING_SIZES.get(level, 12))
        cursor.mergeCharFormat(f)
        self.edit.mergeCurrentCharFormat(f)
        cursor.endEditBlock()
        self.edit.setFocus()

    def _char_format_changed(self, f):
        for widget in (self.font_combo, self.size_combo):
            widget.blockSignals(True)
        families = f.fontFamilies() or [self.edit.document().defaultFont().family()]
        self.font_combo.setCurrentFont(QFont(families[0]))
        size = f.fontPointSize() or self.edit.document().defaultFont().pointSizeF()
        self.size_combo.setEditText(f"{size:g}")
        for widget in (self.font_combo, self.size_combo):
            widget.blockSignals(False)
        self.a_bold.setChecked(f.fontWeight() >= QFont.Weight.Bold)
        self.a_italic.setChecked(f.fontItalic())
        self.a_underline.setChecked(f.fontUnderline())
        self.a_strike.setChecked(f.fontStrikeOut())

    def _cursor_moved(self):
        align = self.edit.alignment()
        for flag, a in self.a_align.items():
            if align & flag:
                a.setChecked(True)
                break
        level = self.edit.textCursor().blockFormat().headingLevel()
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(level)))

    # ---------------------------------------------------------- insert
    def insert_image(self):
        last = QSettings().value("last_dir", os.path.expanduser("~"))
        path, _f = QFileDialog.getOpenFileName(self, _("Insert image"), last,
                                               _("Images") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, APP_NAME, _("Could not open the file:\n%s") % path)
            return
        url = QUrl.fromLocalFile(path).toString()
        self.edit.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        fmt = QTextImageFormat()
        fmt.setName(url)
        usable = PAGE_WIDTH - 2 * PAGE_MARGIN - 4
        width = min(image.width(), usable)
        fmt.setWidth(width)
        fmt.setHeight(image.height() * width / max(1, image.width()))
        self.edit.textCursor().insertImage(fmt)

    def insert_table(self):
        rows, ok = QInputDialog.getInt(self, _("Insert table"), _("Rows:"), 3, 1, 200)
        if not ok:
            return
        cols, ok = QInputDialog.getInt(self, _("Insert table"), _("Columns:"), 3, 1, 30)
        if not ok:
            return
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderBrush(QColor("#666666"))
        fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        fmt.setCellPadding(4)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        self.edit.textCursor().insertTable(rows, cols, fmt)

    def insert_page_break(self):
        cursor = self.edit.textCursor()
        block = QTextBlockFormat()
        block.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        cursor.insertBlock(block)
        self.edit.setTextCursor(cursor)

    # ----------------------------------------------------------- files
    def _update_title(self):
        name = os.path.basename(self.path) if self.path else _("Untitled document")
        mark = "*" if self.edit.document().isModified() else ""
        self.setWindowTitle(f"{mark}{name} — {APP_NAME}")

    def _confirm_discard(self):
        if not self.edit.document().isModified() or not self.edit.document().toPlainText().strip():
            return True
        answer = QMessageBox.question(
            self, APP_NAME, _("The document has unsaved changes. Save them?"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_document(self):
        if self._confirm_discard():
            self.edit.clear()
            self.path = None
            self.edit.document().setModified(False)
            self._update_title()

    def open_document(self):
        if not self._confirm_discard():
            return
        last = QSettings().value("last_dir", os.path.expanduser("~"))
        path, _f = QFileDialog.getOpenFileName(self, _("Open"), last, _("Documents") + f" ({OPEN_FILTER})")
        if path:
            self.load(path)

    def load(self, path):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".odt":
                html = _odt_to_html(path)
                self.edit.setHtml(html)
            else:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if ext in (".html", ".htm"):
                    self.edit.setHtml(text)
                elif ext == ".md":
                    self.edit.setMarkdown(text)
                else:
                    self.edit.setPlainText(text)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, _("Could not open the file:\n%s") % exc)
            return
        self.path = path if ext in (".odt", ".html", ".htm") else None
        self.edit.document().setModified(False)
        self._update_title()

    def save(self):
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self):
        last = QSettings().value("last_dir", os.path.expanduser("~"))
        start = self.path or os.path.join(last, _("Document") + ".odt")
        path, chosen = QFileDialog.getSaveFileName(
            self, _("Save as"), start,
            "OpenDocument (*.odt);;HTML (*.html);;Markdown (*.md);;" + _("Plain text") + " (*.txt)")
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += "." + chosen.split("*.")[1].rstrip(")") if "*." in chosen else ".odt"
        return self._write(path)

    def _write(self, path):
        ext = os.path.splitext(path)[1].lower()
        doc = self.edit.document()
        try:
            if ext == ".odt":
                writer = QTextDocumentWriter(path, b"odf")
                if not writer.write(doc):
                    raise OSError(writer.device().errorString() if writer.device() else path)
            else:
                text = {".md": doc.toMarkdown, ".txt": doc.toPlainText}.get(ext, doc.toHtml)()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, _("Could not save:\n%s") % exc)
            return False
        if ext in (".odt", ".html", ".htm"):
            self.path = path
            doc.setModified(False)
        QSettings().setValue("last_dir", os.path.dirname(path))
        self._update_title()
        return True

    def _print_pdf(self, path):
        doc = self.edit.document().clone(self)
        doc.setDocumentMargin(0)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                          QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter))
        printer.setCreator(APP_NAME)
        printer.setDocName(os.path.splitext(os.path.basename(self.path or _("Document")))[0])
        doc.print(printer)
        doc.deleteLater()

    def export_pdf(self):
        last = QSettings().value("last_dir", os.path.expanduser("~"))
        stem = os.path.splitext(os.path.basename(self.path))[0] if self.path else _("Document")
        path, _f = QFileDialog.getSaveFileName(self, _("Export to PDF"), os.path.join(last, stem + ".pdf"),
                                               "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._print_pdf(path)
        self.main.open_file(path)
        self.main.raise_()

    def create_pdf(self):
        import pymupdf
        fd, tmp = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            self._print_pdf(tmp)
            with open(tmp, "rb") as f:
                doc = pymupdf.open("pdf", f.read())
        finally:
            os.unlink(tmp)
        stem = os.path.splitext(os.path.basename(self.path))[0] if self.path else _("Document")
        self.main._new_tab(doc, stem + ".pdf")
        self.main.raise_()
        self.main.activateWindow()

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def _odt_to_html(path):
    """Qt can write ODT but not read it: convert with LibreOffice when available."""
    import shutil
    import subprocess
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError(_("LibreOffice is needed to open .odt files."))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "html", "--outdir", tmp, path],
                       check=True, capture_output=True, timeout=120)
        out = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + ".html")
        with open(out, encoding="utf-8", errors="replace") as f:
            return f.read()
