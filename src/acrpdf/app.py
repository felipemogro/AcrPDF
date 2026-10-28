import os
import sys
import tempfile

import pymupdf
from PyQt6.QtCore import (QLibraryInfo, QLocale, QProcess, QRectF, QSettings, QSize, Qt, QThread, QTimer,
                          QTranslator, pyqtSignal)
from PyQt6.QtGui import QAction, QActionGroup, QCursor, QFont, QIcon, QImage, QKeySequence, QPainter
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFontComboBox, QFrame,
                             QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressDialog,
                             QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QToolBar,
                             QToolButton, QVBoxLayout, QWidget)

from . import APP_ID, APP_NAME, __version__, certstore, dialogs, i18n, ops, signing, tools, updater
from .dialogs import glyph_icon, graphic_pixmap, rgb
from .document import DocumentTab
from .i18n import N_, _
from .overlay import TextBoxEditor

RES = os.path.join(os.path.dirname(__file__), "resources")

GROUPS = [
    ("edit", N_("Edit PDF"), "✎", "#d6246e"),
    ("comment", N_("Comment"), "✉", "#e8a317"),
    ("fill", N_("Fill & Sign"), "✍", "#7d4bc4"),
    ("certs", N_("Certificates"), "✔", "#2c6fd6"),
    ("forms", N_("Prepare form"), "☰", "#c43f8a"),
    ("stamp", N_("Stamp"), "◉", "#b8321e"),
    ("organize", N_("Organize pages"), "▦", "#3d9b35"),
    ("protect", N_("Protect"), "🔒", "#5a5a5a"),
    ("redact", N_("Redact"), "▬", "#a5243b"),
    ("ai", N_("AI assistant"), "✦", "#6a3fd4"),
    ("alltools", N_("All PDF tools"), "⋯", "#555555"),
]

CONTEXT = {
    "edit": [("add_text", N_("Add text"), "T"), ("edit_text", N_("Edit text"), "Ꞁ"),
             ("-", "pick_image", N_("Add image")), ("crop", N_("Crop page"), "⌗"),
             ("-", "watermark", N_("Watermark")), ("-", "page_numbers", N_("Page numbers")),
             ("-", "ocr_current", N_("Recognize text (OCR)"))],
    "comment": [("highlight", N_("Highlight"), "▮"), ("underline", N_("Underline"), "U"),
                ("strike", N_("Strikethrough"), "S"), ("note", N_("Note"), "✉"),
                ("freetext", N_("Text box"), "T"), ("rect", N_("Rectangle"), "□"),
                ("ellipse", N_("Ellipse"), "○"), ("line", N_("Line"), "╱"), ("arrow", N_("Arrow"), "➚"),
                ("ink", N_("Draw"), "✎"), ("erase", N_("Delete comment"), "⌫")],
    "fill": [("add_text", N_("Add text"), "Ab"), ("check_mark", N_("Check mark"), "✓"),
             ("cross_mark", N_("Cross"), "✗"), ("-", "sign_menu", N_("Sign ▾")),
             ("-", "digital_sign_tool", N_("Sign with certificate"))],
    "certs": [("digsign", N_("Sign digitally (draw area)"), "✔"), ("-", "invisible_sign", N_("Invisible signature")),
              ("-", "request_signatures", N_("Request signatures…")), ("-", "validate", N_("Validate signatures")),
              ("-", "certificates", N_("Manage certificates"))],
    "forms": [("select_field", N_("Select / resize"), "⬚"), ("field_text", N_("Text field"), "Ⓣ"),
              ("field_check", N_("Check box"), "☑"), ("field_radio", N_("Radio button"), "◉"),
              ("field_combo", N_("Dropdown"), "▾"), ("field_list", N_("List box"), "≣"),
              ("field_signature", N_("Signature field"), "✍"), ("-", "detect_fields", N_("Detect fields")),
              ("-", "flatten", N_("Flatten form"))],
    "stamp": [("-", "stamp_dialog", N_("Choose stamp…"))],
    "organize": [("-", "rotate_left", N_("↺ Rotate left")), ("-", "rotate_right", N_("↻ Rotate right")),
                 ("-", "duplicate_pages", N_("Duplicate")), ("-", "delete_pages", N_("Delete")),
                 ("-", "insert_blank", N_("Insert blank")), ("-", "insert_file", N_("Insert file")),
                 ("-", "extract_pages", N_("Extract")), ("-", "split_current", N_("Split"))],
    "protect": [("-", "encrypt", N_("Encrypt with password")), ("-", "decrypt", N_("Remove password")),
                ("redact", N_("Redact area"), "▬")],
    "ai": [("-", "ai_summarize", N_("Summarize")), ("-", "ai_translate", N_("Translate…"))],
    "redact": [("redact", N_("Redact area"), "▬"), ("-", "redact_search", N_("Redact searched text"))],
}

QSS = """
QMainWindow { background: #f4f4f4; }
QToolBar#main { background: #ffffff; border-bottom: 1px solid #d6d6d6; spacing: 4px; padding: 3px; }
QToolBar#context { background: #fafafa; border-bottom: 1px solid #dcdcdc; spacing: 6px; padding: 2px 6px; }
QToolBar QToolButton { padding: 4px 6px; border-radius: 4px; }
QToolBar QToolButton:hover { background: #e9eef7; }
QToolBar QToolButton:checked { background: #dbe8fb; color: #0d5bd6; }
QTabWidget#docs::pane { border: none; }
QTabBar::tab { background: #e6e6e6; padding: 7px 16px; border: none; margin-right: 1px; }
QTabBar::tab:selected { background: #ffffff; border-top: 3px solid #c8102e; }
QListWidget#groups { background: #ffffff; border: none; border-left: 1px solid #dadada; }
QListWidget#groups::item { padding: 6px; border-radius: 6px; }
QListWidget#groups::item:selected { background: #e9eef7; color: #111; }
QWidget#home { background: #f4f4f4; }
QToolButton#card { background: #ffffff; border: 1px solid #e1e1e1; border-radius: 10px; padding: 8px;
                   text-align: left; }
QToolButton#card:hover { border: 1px solid #c8102e; background: #fff8f8; }
QLabel#h1 { font-size: 20pt; font-weight: 600; color: #2c2c2c; }
QLabel#h2 { font-size: 12pt; font-weight: 600; color: #444; margin-top: 8px; }
QPushButton#primary { background: #c8102e; color: white; border-radius: 14px; padding: 6px 18px;
                      font-weight: 600; border: none; }
QPushButton#primary:hover { background: #a50d26; }
QPushButton#primary:disabled { background: #d9a0a8; }
QWidget#searchBar { background: #fffbe6; border-bottom: 1px solid #e6d690; }
QStatusBar { background: #ffffff; border-top: 1px solid #dddddd; }
"""


def app_icon():
    return QIcon(os.path.join(RES, "acrpdf.svg"))


class Task(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        except Exception as exc:
            self.failed.emit(str(exc))


def stretch():
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w


class MainWindow(QMainWindow):
    def __init__(self, files=()):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.settings = QSettings()
        self.current_group = None
        self.opts = {"color": "#000000", "family": "DejaVu Sans", "size": 12.0, "width": 2,
                     "highlight": "#ffe600"}
        self.resize(1380, 900)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_central()
        self.statusBar().showMessage(_("Ready"))
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        for f in files:
            self.open_file(f)
        QTimer.singleShot(5000, lambda: self.check_updates(manual=False))

    def _act(self, text, slot, shortcut=None, glyph=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if glyph:
            a.setIcon(glyph_icon(glyph, None, "#3c3c3c", 48))
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        self.a_open = self._act(_("Open…"), self.open_dialog, "Ctrl+O", "📂")
        self.a_save = self._act(_("Save"), self.save, "Ctrl+S", "💾")
        self.a_save_as = self._act(_("Save as…"), self.save_as, "Ctrl+Shift+S")
        self.a_print = self._act(_("Print…"), self.print_doc, "Ctrl+P", "⎙")
        self.a_close = self._act(_("Close"), lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.a_undo = self._act(_("Undo"), lambda: self._doc_call("undo"), "Ctrl+Z", "↶")
        self.a_redo = self._act(_("Redo"), lambda: self._doc_call("redo"), "Ctrl+Y", "↷")
        self.a_find = self._act(_("Find…"), lambda: self._doc_call("show_search"), "Ctrl+F", "🔍")
        self.a_zoom_in = self._act(_("Zoom in"), lambda: self._view_call("zoom_in"), "Ctrl++", "+")
        self.a_zoom_out = self._act(_("Zoom out"), lambda: self._view_call("zoom_out"), "Ctrl+-", "−")
        self.a_fit_w = self._act(_("Fit width"), lambda: self._fit("width"), "Ctrl+2")
        self.a_fit_p = self._act(_("Fit page"), lambda: self._fit("page"), "Ctrl+0")
        self.a_hand = self._act(_("Hand / fill forms"), lambda: self.set_tool("hand"), "H", "✋")
        self.a_select = self._act(_("Select text"), lambda: self.set_tool("select_text"), "V", "𝙸")
        for a in (self.a_hand, self.a_select):
            a.setCheckable(True)
        self.a_hand.setData("hand")
        self.a_select.setData("select_text")
        self.a_rotate = self._act(_("Rotate page"), lambda: self.rotate(90), "Ctrl+Shift+R", "↻")

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(_("&File"))
        m.addAction(self.a_open)
        self.recent_menu = m.addMenu(_("Open recent"))
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addAction(self._act(_("Create PDF from files…"), self.create_pdf, "Ctrl+N"))
        m.addAction(self._act(_("Blank PDF"), self.create_blank))
        m.addSeparator()
        m.addAction(self.a_save)
        m.addAction(self.a_save_as)
        export = m.addMenu(_("Export to"))
        for key in ("pdf2word", "pdf2excel", "pdf2ppt", "pdf2jpg", "pdf2png", "pdf2pdfa", "pdf2txt"):
            export.addAction(_(tools.TOOLS_BY_KEY[key].name), lambda k=key: self.run_on_current(k))
        m.addAction(self._act(_("Compress…"), lambda: self.run_on_current("compress")))
        m.addSeparator()
        m.addAction(self.a_print)
        m.addAction(self._act(_("Document properties…"), self.properties, "Ctrl+D"))
        m.addSeparator()
        m.addAction(self.a_close)
        m.addAction(self._act(_("Quit"), self.close, "Ctrl+Q"))
        m = mb.addMenu(_("&Edit"))
        m.addAction(self.a_undo)
        m.addAction(self.a_redo)
        m.addSeparator()
        m.addAction(self.a_find)
        m.addAction(self._act(_("Copy all text"), self.copy_all_text))
        m.addSeparator()
        m.addAction(self._act(_("Preferences…"), self.preferences))
        m = mb.addMenu(_("&View"))
        for a in (self.a_zoom_in, self.a_zoom_out, self.a_fit_w, self.a_fit_p, self.a_rotate):
            m.addAction(a)
        m.addAction(self._act(_("Full screen"), self.toggle_full_screen, "F11"))
        m.addAction(self._act(_("Show/hide side panel"), self._toggle_sidebar, "F4"))
        m.addAction(self._act(_("Show/hide tools pane"),
                              lambda: self.groups.setVisible(not self.groups.isVisible()), "Shift+F4"))
        m = mb.addMenu(_("&Tools"))
        for key, name, glyph, color in GROUPS:
            m.addAction(glyph_icon(glyph, color), _(name), lambda k=key: self.select_group(k))
        m.addSeparator()
        for cat in tools.CATEGORIES:
            sub = m.addMenu(_(cat))
            for t in tools.TOOLS:
                if t.category == cat:
                    sub.addAction(glyph_icon(t.glyph, t.color), _(t.name), lambda k=t.key: self.open_tool(k))
        m.addSeparator()
        m.addAction(self._act(_("Certificates…"), self.certificates))
        m.addAction(self._act(_("PDF printer…"), self.printer_info))
        m = mb.addMenu(_("&Help"))
        m.addAction(self._act(_("Check for updates…"), lambda: self.check_updates(manual=True)))
        m.addAction(self._act(_("About AcrPDF"), self.about))

    def _build_toolbars(self):
        tb = QToolBar(_("Main"))
        tb.setObjectName("main")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        self.addToolBar(tb)
        for a in (self.a_open, self.a_save, self.a_print):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        tb.addAction(self.a_hand)
        tb.addAction(self.a_select)
        tb.addSeparator()
        tb.addWidget(QLabel(" " + _("Page") + " "))
        self.page_edit = QLineEdit("0")
        self.page_edit.setFixedWidth(46)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.returnPressed.connect(self._go_page)
        tb.addWidget(self.page_edit)
        self.page_total = QLabel(" / 0 ")
        tb.addWidget(self.page_total)
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems([_("Fit width"), _("Fit page"), "50%", "75%", "100%", "125%", "150%",
                                  "200%", "300%", "400%"])
        self.zoom_combo.setFixedWidth(130)
        self.zoom_combo.activated.connect(self._zoom_combo)
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_combo)
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.a_zoom_in)
        tb.addSeparator()
        tb.addAction(self.a_rotate)
        tb.addAction(self.a_find)
        tb.addWidget(stretch())
        sign = QPushButton("  " + _("Sign") + "  ")
        sign.setObjectName("primary")
        sign.clicked.connect(lambda: self.select_group("fill"))
        tb.addWidget(sign)

        self.addToolBarBreak()
        self.ctx = QToolBar(_("Tool"))
        self.ctx.setObjectName("context")
        self.ctx.setMovable(False)
        self.ctx.setIconSize(QSize(18, 18))
        self.ctx.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(self.ctx)
        self.ctx.hide()
        self.tool_group = QActionGroup(self)
        self.tool_group.addAction(self.a_hand)
        self.tool_group.addAction(self.a_select)
        self.a_hand.setChecked(True)

    def _build_central(self):
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("docs")
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.addTab(self._build_home(), _("Home"))
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        lay.addWidget(self.tabs, 1)
        self.groups = QListWidget()
        self.groups.setObjectName("groups")
        self.groups.setIconSize(QSize(26, 26))
        self.groups.setFixedWidth(220)
        for key, name, glyph, color in GROUPS:
            it = QListWidgetItem(glyph_icon(glyph, color), _(name))
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.groups.addItem(it)
        self.groups.itemClicked.connect(lambda it: self.select_group(it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.groups)
        self.setCentralWidget(central)

    def _build_home(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        home = QWidget()
        home.setObjectName("home")
        outer = QVBoxLayout(home)
        outer.setContentsMargins(36, 24, 36, 24)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(64, 64))
        head.addWidget(logo)
        text = QVBoxLayout()
        h1 = QLabel(APP_NAME)
        h1.setObjectName("h1")
        text.addWidget(h1)
        text.addWidget(QLabel(_("View, edit, fill, sign and certify PDF documents.")))
        head.addLayout(text)
        head.addStretch()
        b = QPushButton("  " + _("Open file") + "  ")
        b.setObjectName("primary")
        b.clicked.connect(self.open_dialog)
        head.addWidget(b)
        outer.addLayout(head)

        body = QHBoxLayout()
        left = QVBoxLayout()
        for cat in tools.CATEGORIES:
            h2 = QLabel(_(cat))
            h2.setObjectName("h2")
            left.addWidget(h2)
            grid = QGridLayout()
            grid.setSpacing(10)
            grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
            items = [t for t in tools.TOOLS if t.category == cat]
            for i, t in enumerate(items):
                card = QToolButton()
                card.setObjectName("card")
                card.setIcon(glyph_icon(t.glyph, t.color))
                card.setIconSize(QSize(34, 34))
                card.setText(_(t.name))
                card.setToolTip(_(t.description))
                card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                card.setFixedSize(188, 54)
                card.clicked.connect(lambda _c, k=t.key: self.open_tool(k))
                grid.addWidget(card, i // 4, i % 4)
            left.addLayout(grid)
        left.addStretch()
        body.addLayout(left, 3)
        right = QVBoxLayout()
        h2 = QLabel(_("Recent files"))
        h2.setObjectName("h2")
        right.addWidget(h2)
        self.recent_list = QListWidget()
        self.recent_list.setMinimumWidth(240)
        self.recent_list.itemActivated.connect(lambda it: self.open_file(it.data(Qt.ItemDataRole.UserRole)))
        self.recent_list.itemClicked.connect(lambda it: self.open_file(it.data(Qt.ItemDataRole.UserRole)))
        right.addWidget(self.recent_list, 1)
        body.addLayout(right, 1)
        outer.addLayout(body, 1)
        self._fill_recent_list()
        scroll.setWidget(home)
        return scroll

    def doc_tab(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def require_doc(self):
        t = self.doc_tab()
        if t is None and self.tabs.count() > 1:
            self.tabs.setCurrentIndex(self._last_doc_index())
            t = self.doc_tab()
        if t is None:
            self.open_dialog()
            t = self.doc_tab()
        return t

    def _last_doc_index(self):
        last = getattr(self, "_last_doc_tab", None)
        for i in range(1, self.tabs.count()):
            if self.tabs.widget(i) is last:
                return i
        return self.tabs.count() - 1

    def _doc_call(self, name):
        t = self.doc_tab()
        if t:
            getattr(t, name)()

    def _view_call(self, name):
        t = self.doc_tab()
        if t:
            getattr(t.view, name)()

    def _toggle_sidebar(self):
        t = self.doc_tab()
        if t:
            t.sidebar.setVisible(not t.sidebar.isVisible())

    def _fit(self, mode):
        t = self.doc_tab()
        if t:
            t.view.set_zoom(t.view.zoom, fit=mode)

    def _zoom_combo(self, *_args):
        t = self.doc_tab()
        if not t:
            return
        text = self.zoom_combo.currentText()
        if text == _("Fit width"):
            return self._fit("width")
        if text == _("Fit page"):
            return self._fit("page")
        try:
            t.view.set_zoom(float(text.strip(" %")) / 100)
        except ValueError:
            pass

    def _go_page(self):
        t = self.doc_tab()
        if t:
            try:
                t.view.go_to(int(self.page_edit.text()) - 1)
            except ValueError:
                pass

    def page_changed(self, tab, index):
        if tab is self.doc_tab():
            self.page_edit.setText(str(index + 1))

    def zoom_changed(self, tab, zoom):
        if tab is self.doc_tab():
            self.zoom_combo.setEditText(f"{zoom * 100:.0f}%")

    def _tab_changed(self, _index):
        t = self.doc_tab()
        if t:
            self._last_doc_tab = t
            self.page_edit.setText(str(t.view.current_page() + 1))
            self.zoom_changed(t, t.view.zoom)
            t.view.set_tool(self.current_tool())
        self._update_title()

    def _update_title(self):
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            self.tabs.setTabText(i, ("● " if w.modified else "") + w.title)
        t = self.doc_tab()
        self.setWindowTitle(f"{t.title}{' *' if t.modified else ''} — {APP_NAME}" if t else APP_NAME)
        if t:
            self.page_total.setText(f" / {t.doc.page_count} ")

    def current_tool(self):
        a = self.tool_group.checkedAction()
        return a.data() if a and a.data() else "hand"

    def set_tool(self, tool):
        for a in self.tool_group.actions():
            if a.data() == tool:
                a.setChecked(True)
        t = self.doc_tab()
        if t:
            t.view.set_tool(tool)
            t.view.setProperty("inkColor", self.opts["color"])
        hints = {"add_text": _("Click where you want to type."),
                 "edit_text": _("Click on a text to edit it."),
                 "digsign": _("Draw the rectangle where the signature will appear."),
                 "select_field": _("Click a field to move or resize it. Del deletes it."),
                 "crop": _("Draw the area to keep.")}
        if tool.startswith("field_"):
            self.statusBar().showMessage(_("Click or drag on the page to create the field; then resize it."))
        else:
            self.statusBar().showMessage(hints.get(tool, ""))

    def select_group(self, key):
        if key == "alltools":
            self.tabs.setCurrentIndex(0)
            return
        t = self.require_doc()
        if not t:
            return
        self.current_group = key
        self.ctx.clear()
        for a in list(self.tool_group.actions()):
            if a not in (self.a_hand, self.a_select):
                self.tool_group.removeAction(a)
        name = next(n for k, n, _g, _c in GROUPS if k == key)
        self.ctx.addWidget(QLabel(f"  <b>{_(name)}</b>  "))
        self.ctx.addSeparator()
        for entry in CONTEXT.get(key, []):
            if entry[0] == "-":
                a = QAction(_(entry[2]), self)
                a.triggered.connect(getattr(self, entry[1]))
            else:
                tool, label, glyph = entry
                a = QAction(glyph_icon(glyph, None, "#333333", 40), _(label), self)
                a.setCheckable(True)
                a.setData(tool)
                a.triggered.connect(lambda _c, tl=tool: self.set_tool(tl))
                self.tool_group.addAction(a)
            self.ctx.addAction(a)
        self.ctx.addSeparator()
        self._add_options(key)
        self.ctx.addWidget(stretch())
        close = QAction("✕ " + _("Close"), self)
        close.triggered.connect(self.close_context)
        self.ctx.addAction(close)
        self.ctx.show()
        t.set_organize(key == "organize")
        if key == "stamp":
            self.stamp_dialog()
        elif key == "forms":
            self.set_tool("select_field")
        elif key == "fill":
            self.set_tool("hand")
            self.statusBar().showMessage(_("Click the fields to fill them in place, or use «Sign ▾» to add your signature."))

    def close_context(self):
        self.ctx.hide()
        t = self.doc_tab()
        if t:
            t.set_organize(False)
        self.set_tool("hand")

    def _add_options(self, key):
        if key not in ("edit", "comment", "fill", "forms"):
            return
        color = dialogs.ColorButton(self.opts["color"], lambda c: (self.opts.__setitem__("color", c),
                                                                    self.set_tool(self.current_tool())))
        color.setToolTip(_("Color"))
        self.ctx.addWidget(QLabel(_("Color") + " "))
        self.ctx.addWidget(color)
        if key in ("edit", "fill", "comment"):
            fonts = QFontComboBox()
            fonts.setCurrentFont(QFont(self.opts["family"]))
            fonts.setMaximumWidth(210)
            fonts.setToolTip(_("Font (embedded in the PDF)"))
            fonts.currentFontChanged.connect(lambda f: self.opts.__setitem__("family", f.family()))
            self.ctx.addWidget(QLabel(" " + _("Font") + " "))
            self.ctx.addWidget(fonts)
        size = QDoubleSpinBox()
        size.setRange(4, 144)
        size.setValue(self.opts["size"])
        size.valueChanged.connect(lambda v: self.opts.__setitem__("size", v))
        self.ctx.addWidget(QLabel(" " + _("Size") + " "))
        self.ctx.addWidget(size)
        if key == "comment":
            width = QSpinBox()
            width.setRange(1, 20)
            width.setValue(self.opts["width"])
            width.valueChanged.connect(lambda v: self.opts.__setitem__("width", v))
            self.ctx.addWidget(QLabel(" " + _("Width") + " "))
            self.ctx.addWidget(width)
            hl = dialogs.ColorButton(self.opts["highlight"], lambda c: self.opts.__setitem__("highlight", c))
            self.ctx.addWidget(QLabel(" " + _("Highlight") + " "))
            self.ctx.addWidget(hl)

    def tool_finished(self, tool, idx, payload):
        t = self.doc_tab()
        if not t:
            return
        o = self.opts
        color = rgb(o["color"])
        view = t.view
        pages = [idx]
        is_rect = isinstance(payload, pymupdf.Rect)

        def at(point):
            return view.page_rect_to_scene(idx, pymupdf.Rect(point, point)).topLeft()

        if tool in ("highlight", "underline", "strike", "squiggly"):
            c = rgb(o["highlight"]) if tool == "highlight" else color
            if payload.is_empty or t.modify(lambda d: ops.markup(d[idx], payload, tool, c), pages, sidebar=True) is None:
                self.statusBar().showMessage(_("There is no text in the selected area."), 4000)
        elif tool in ("rect", "ellipse") and not payload.is_empty:
            t.modify(lambda d: ops.shape_annot(d[idx], tool, rect=payload, color=color, width=o["width"]),
                     pages, sidebar=True)
        elif tool in ("line", "arrow"):
            t.modify(lambda d: ops.shape_annot(d[idx], tool, p1=payload[0], p2=payload[1], color=color,
                                               width=o["width"]), pages, sidebar=True)
        elif tool == "ink":
            t.modify(lambda d: ops.ink_annot(d[idx], payload, color=color, width=o["width"]), pages, sidebar=True)
        elif tool == "add_text":
            family, hexcolor = o["family"], o["color"]
            TextBoxEditor(view, at(payload), lambda text, size: t.modify(
                lambda d: ops.insert_text_block(d[idx], pymupdf.Rect(payload, payload), text, family, size,
                                                rgb(hexcolor)), pages), family, o["size"], hexcolor)
        elif tool == "freetext":
            def add_text_box(text, size):
                lines = text.split("\n")
                width = max(60, max(len(line) for line in lines) * size * 0.55)
                rect = pymupdf.Rect(payload.x, payload.y, payload.x + width,
                                    payload.y + size * 1.35 * len(lines) + 4)
                t.modify(lambda d: ops.freetext_annot(d[idx], rect, text, size, color), pages, sidebar=True)
            TextBoxEditor(view, at(payload), add_text_box, "Helvetica", o["size"], o["color"])
        elif tool == "note":
            author = self.settings.value("author", os.environ.get("USER", ""))
            TextBoxEditor(view, at(payload), lambda text, _s: t.modify(
                lambda d: ops.note_annot(d[idx], payload, text, author), pages, sidebar=True),
                          "DejaVu Sans", 10, "#000000", note=True)
        elif tool == "edit_text":
            self._edit_text(t, idx, payload)
        elif tool in ("check_mark", "cross_mark"):
            s = max(o["size"], 10)
            glyph = "✓" if tool == "check_mark" else "✗"
            r = pymupdf.Rect(payload.x - s * 0.4, payload.y - s * 0.7, payload.x + s, payload.y + s)
            t.modify(lambda d: ops.insert_text_block(d[idx], r, glyph, "DejaVu Sans", s, color), pages)
        elif tool == "erase":
            annot = ops.annot_at(t.doc[idx], payload)
            if annot:
                x = annot.xref
                t.modify(lambda d: d[idx].delete_annot(d[idx].load_annot(x)), pages, sidebar=True)
        elif tool == "select_text":
            text = " ".join(w[4] for w in ops.words_in_rect(t.doc[idx], payload))
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage(_("Copied: %s") % text[:80] if text else _("No text"), 5000)
        elif tool == "redact" and not payload.is_empty:
            view.begin_placement(idx, payload, lambda i, r: t.modify(lambda d: ops.redact(d[i], r), [i]),
                                 commit_text=_("Redact permanently"))
        elif tool == "crop" and not payload.is_empty:
            def crop_all():
                rect = view.placement_rect()
                view.cancel_placement()
                t.modify(lambda d: ops.crop_pages(d, rect), relayout=True)
                self.set_tool("hand")
            view.begin_placement(idx, payload, lambda i, r: (t.modify(lambda d: ops.crop_page(d[i], r), relayout=True),
                                                             self.set_tool("hand")),
                                 commit_text=_("Crop this page"),
                                 extra_buttons=[("⧉", _("Crop all pages"), crop_all)])
        elif tool.startswith("field_") and is_rect:
            self._add_field(t, idx, tool[6:], payload)
        elif tool == "digsign" and is_rect:
            box = payload if payload.width > 20 else pymupdf.Rect(payload.x0, payload.y0, payload.x0 + 220, payload.y0 + 70)
            self.set_tool("hand")
            self.digital_sign(page=idx, box=box)

    def _edit_text(self, t, idx, point):
        page = t.doc[idx]
        span = ops.find_span(page, point)
        if not span:
            self.statusBar().showMessage(_("No text found at that point."), 4000)
            return
        bbox = ops.to_visible(page, span["bbox"])
        family = self.opts["family"]
        scene_pos = t.view.page_rect_to_scene(idx, bbox).topLeft()
        hexcolor = "#%06x" % span["color"]

        def done(text, size):
            if text != span["text"] or size != span["size"]:
                t.modify(lambda d: ops.replace_span(d[idx], span, text, family=family, size=size), [idx])
        TextBoxEditor(t.view, scene_pos, done, family, span["size"], hexcolor, text=span["text"])

    def _add_field(self, t, idx, kind, rect):
        defaults = {"text": (180, 22), "check": (16, 16), "radio": (16, 16), "combo": (160, 22),
                    "list": (160, 70), "signature": (200, 60)}
        if rect.width < 6 or rect.height < 6:
            w, h = defaults[kind]
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + w, rect.y0 + h)
        base = {"text": _("Text"), "check": _("Check"), "radio": _("Group"), "combo": _("Dropdown"),
                "list": _("List"), "signature": _("Signature")}[kind]
        name = ops.unique_field_name(t.doc, base)
        if kind == "signature":
            try:
                t.replace_document(signing.add_signature_field(t.bytes(), idx, rect, name))
            except Exception as exc:
                QMessageBox.critical(self, _("Signature field"), str(exc))
            return
        options = [_("Option %d") % i for i in (1, 2, 3)] if kind in ("combo", "list") else None
        t.modify(lambda d: ops.add_field(d[idx], kind, rect, name, options), [idx], sidebar=True)
        widget = next((w for w in t.doc[idx].widgets() if w.field_name == name), None)
        if widget is not None:
            self.set_tool("select_field")
            t.select_field(idx, widget.xref)

    def _default_box(self, t, width, height):
        idx = t.view.current_page()
        page_rect = t.doc[idx].rect
        center = t.view.mapToScene(t.view.viewport().rect().center())
        _i, pt = t.view.scene_to_page(center)
        if pt is None or _i != idx:
            pt = pymupdf.Point(page_rect.width / 2, page_rect.height / 2)
        x0 = max(10, min(pt.x - width / 2, page_rect.width - width - 10))
        y0 = max(10, min(pt.y - height / 2, page_rect.height - height - 10))
        return idx, pymupdf.Rect(x0, y0, x0 + width, y0 + height)

    def place_graphic(self, data, width=160):
        t = self.require_doc()
        if not t:
            return
        gw, gh = ops.graphic_size(data)
        height = width * gh / max(gw, 1)
        idx, box = self._default_box(t, width, height)
        pixmap = graphic_pixmap(ops.render_graphic_png(data, 900), 900, 900)
        t.view.begin_placement(idx, box, lambda i, r: t.modify(lambda d: ops.insert_graphic(d[i], r, data), [i]),
                               pixmap=pixmap, keep_aspect=True, commit_text=_("Place"))
        self.statusBar().showMessage(_("Drag to move, use the handles to resize, then press Place or Enter."))

    def sign_menu(self):
        m = QMenu(self)
        m.setStyleSheet("QMenu { icon-size: 140px; } QMenu::item { padding: 6px 12px; }")
        saved = dialogs.saved_signatures()[:12]
        for path in saved:
            a = m.addAction(QIcon(graphic_pixmap(dialogs.read_file(path), 280, 80)), "")
            a.triggered.connect(lambda _c, p=path: self.place_graphic(dialogs.read_file(p)))
        if saved:
            m.addSeparator()
            delete = m.addMenu(_("Delete saved signature"))
            for path in saved:
                delete.addAction(QIcon(graphic_pixmap(dialogs.read_file(path), 140, 40)), os.path.basename(path),
                                 lambda p=path: os.unlink(p))
        m.addAction(_("Add signature (draw, type or upload PNG/SVG)…"), lambda: self._new_signature(False))
        m.addAction(_("Add initials…"), lambda: self._new_signature(True))
        m.addSeparator()
        m.addAction(_("Sign with a digital certificate…"), self.digital_sign_tool)
        m.exec(QCursor.pos())

    def _new_signature(self, initials):
        d = dialogs.SignatureDialog(self, initials)
        if d.exec() and d.result_data:
            self.place_graphic(d.result_data, 70 if initials else 160)

    def pick_image(self):
        if not self.require_doc():
            return
        path, _f = QFileDialog.getOpenFileName(self, _("Insert image"), os.path.expanduser("~"),
                                               _("Images") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.svg)")
        if path:
            self.place_graphic(dialogs.read_file(path), 240)

    def stamp_dialog(self):
        t = self.require_doc()
        d = dialogs.StampDialog(self)
        if not (t and d.exec() and d.result):
            return
        st = d.result
        if st["kind"] == "image":
            return self.place_graphic(st["data"], 120)
        idx, box = self._default_box(t, 190, 62)
        png = ops.stamp_png(st["title"], st["color"], st["family"], st["sub"], zoom=4)
        t.view.begin_placement(
            idx, box, lambda i, r: t.modify(lambda doc: ops.draw_stamp(doc[i], r, st["title"], st["color"],
                                                                       st["family"], st["sub"]), [i]),
            pixmap=graphic_pixmap(png, 900, 400), keep_aspect=True, commit_text=_("Stamp"))

    def digital_sign_tool(self):
        if self.require_doc():
            self.select_group("certs")
            self.set_tool("digsign")

    def invisible_sign(self):
        self.digital_sign(visible=False)

    def digital_sign(self, field=None, page=0, box=None, visible=True):
        t = self.require_doc()
        if not t:
            return
        t.view.finish_editing()
        base = t.path or os.path.join(os.path.expanduser("~/Documentos"), t.title)
        stem = os.path.splitext(base)[0]
        out = stem + ("" if stem.endswith(_("_signed")) else _("_signed")) + ".pdf"
        if field:
            for p in t.doc:
                for w in p.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
                    if w.field_name == field:
                        page, box = p.number, ops.to_visible(p, w.rect)
        size = (box.width, box.height) if box else (220, 70)
        d = dialogs.DigitalSignDialog(self, out, visible=visible, field=field, box_size=size)
        if not d.exec():
            return
        if not visible or field:
            return self._sign(t, d, field, page, box if visible else None)
        if box is None:
            page, box = self._default_box(t, 220, 70)
        preview = graphic_pixmap(d.preview_png(box.width, box.height, 4), 1200, 600)
        self._sign_dialog = d
        t.view.begin_placement(page, box, lambda i, r: self._sign(t, d, None, i, r), pixmap=preview,
                               commit_text=_("Sign"), label=_("Signature"))
        self.statusBar().showMessage(_("Adjust the position and size of the signature, then press Sign."))

    def _sign(self, t, dialog, field, page, box):
        cert = dialog.cert()
        out = dialog.out.text()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with certstore.exported_p12(cert, dialog.pw.text()) as (p12, p12_password):
                info = signing.sign_pdf(t.export_bytes(), out, p12,
                                        p12_password if p12_password is not None else dialog.pw.text(),
                                        field_name=field, page_index=page, box=box, **dialog.options())
        except signing.SignError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _("Digital signature"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        with open(out, "rb") as f:
            t.replace_document(f.read())
        t.path, t.title = out, os.path.basename(out)
        t.set_modified(False)
        t.warned_signed = False
        self.add_recent(out)
        t.sidebar.setCurrentWidget(t.sigs)
        self._update_title()
        QMessageBox.information(self, _("Digital signature"),
                                _("Signed by <b>%(name)s</b>.<br><br>Saved to:<br>%(path)s")
                                % {"name": signing.display_name(info["name"], dialog.hide_id.isChecked()),
                                   "path": out})

    def validate(self):
        t = self.require_doc()
        if t:
            t.refresh_signatures()
            t.sidebar.show()
            t.sidebar.setCurrentWidget(t.sigs)

    def certificates(self):
        dialogs.CertificateManager(self).exec()

    def open_dialog(self):
        last = self.settings.value("last_dir", os.path.expanduser("~/Documentos"))
        paths, _f = QFileDialog.getOpenFileNames(self, _("Open"), last, dialogs.file_filter())
        for p in paths:
            self.open_file(p)

    def open_file(self, path):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, _("File not found:\n%s") % path)
            return
        for i in range(1, self.tabs.count()):
            if self.tabs.widget(i).path == path:
                self.tabs.setCurrentIndex(i)
                return
        self.settings.setValue("last_dir", os.path.dirname(path))
        try:
            if not path.lower().endswith(".pdf"):
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    doc = ops.open_any(path)
                finally:
                    QApplication.restoreOverrideCursor()
                tab = DocumentTab(self, None, doc=doc, title=os.path.splitext(os.path.basename(path))[0] + ".pdf")
            else:
                password = None
                with pymupdf.open(path) as probe:
                    while probe.needs_pass:
                        password, ok = QInputDialog.getText(self, _("Protected document"),
                                                            _("Password for %s:") % os.path.basename(path),
                                                            QLineEdit.EchoMode.Password)
                        if not ok:
                            return
                        if probe.authenticate(password):
                            break
                tab = DocumentTab(self, path, password=password)
                self.add_recent(path)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, _("Could not open the file:\n%s") % exc)
            return
        tab.changed.connect(self._update_title)
        i = self.tabs.addTab(tab, tab.title)
        self.tabs.setTabToolTip(i, path)
        self.tabs.setCurrentIndex(i)
        if ops.has_signatures(tab.doc):
            tab.sidebar.setCurrentWidget(tab.sigs)

    def save(self):
        t = self.doc_tab()
        if not t:
            return
        if not t.path:
            return self.save_as()
        t.save()
        self._update_title()
        self.statusBar().showMessage(_("Saved: %(path)s (%(size)d KB)") % {"path": t.path, "size": t.saved_size // 1024},
                                     6000)

    def save_as(self):
        t = self.doc_tab()
        if not t:
            return
        start = t.path or os.path.join(self.settings.value("last_dir", os.path.expanduser("~/Documentos")), t.title)
        path, _f = QFileDialog.getSaveFileName(self, _("Save as"), start, "PDF (*.pdf)")
        if path:
            t.save(path if path.lower().endswith(".pdf") else path + ".pdf")
            self._update_title()

    def close_tab(self, index):
        if index <= 0:
            return True
        t = self.tabs.widget(index)
        t.view.finish_editing()
        if t.modified:
            self.tabs.setCurrentIndex(index)
            answer = QMessageBox.question(self, _("Close"), _("Save changes to «%s»?") % t.title,
                                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                          | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                self.save()
                if t.modified:
                    return False
        self.tabs.removeTab(index)
        t.close_doc()
        t.deleteLater()
        return True

    def closeEvent(self, e):
        for i in range(self.tabs.count() - 1, 0, -1):
            if self.close_tab(i) is False:
                e.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()

    def add_recent(self, path):
        recent = [p for p in (self.settings.value("recent", []) or []) if p != path]
        self.settings.setValue("recent", [path] + recent[:19])
        self._fill_recent_list()

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        for p in self.settings.value("recent", []) or []:
            self.recent_menu.addAction(p, lambda p=p: self.open_file(p))

    def _fill_recent_list(self):
        if not hasattr(self, "recent_list"):
            return
        self.recent_list.clear()
        icon = glyph_icon("PDF", "#c8102e", size=48)
        for p in self.settings.value("recent", []) or []:
            if os.path.exists(p):
                it = QListWidgetItem(icon, os.path.basename(p))
                it.setToolTip(p)
                it.setData(Qt.ItemDataRole.UserRole, p)
                self.recent_list.addItem(it)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.open_file(url.toLocalFile())

    def open_tool(self, key):
        tool = tools.TOOLS_BY_KEY[key]
        if tool.editor == "scan":
            from .scan import ScanDialog
            return ScanDialog(self).exec()
        if tool.editor == "workflow":
            return tools.WorkflowDialog(self).exec()
        if tool.editor:
            if self.require_doc() is not None:
                self.select_group(tool.editor)
            return
        tools.ToolDialog(tool, self).exec()

    def run_on_current(self, key):
        t = self.require_doc()
        if not t:
            return
        tmp = os.path.join(tempfile.mkdtemp(prefix="acrpdf-"), t.title if t.title.lower().endswith(".pdf")
                           else t.title + ".pdf")
        with open(tmp, "wb") as f:
            f.write(t.export_bytes())
        dialog = tools.ToolDialog(tools.TOOLS_BY_KEY[key], self, files=[tmp])
        out_dir = os.path.dirname(t.path) if t.path else os.path.expanduser("~/Documentos")
        tool = tools.TOOLS_BY_KEY[key]
        dialog.out.setText(tools._out_name(out_dir, tmp, "_" + key, tool.ext) if tool.output == "file" else out_dir)
        dialog.exec()

    def _build_from_dialog(self, title, label):
        d = dialogs.FileListDialog(self, title, _("Create"))
        if not d.exec() or not d.files():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            doc = ops.create_from_files(d.files())
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, title, str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._new_tab(doc, label)

    def _new_tab(self, doc, title):
        tab = DocumentTab(self, None, doc=doc, title=title)
        tab.changed.connect(self._update_title)
        self.tabs.setCurrentIndex(self.tabs.addTab(tab, title))

    def create_pdf(self):
        self._build_from_dialog(_("Create PDF"), _("New document.pdf"))

    def create_blank(self):
        from .writer import WriterWindow
        w = WriterWindow(self)
        w.show()

    def watermark(self):
        t = self.require_doc()
        d = dialogs.WatermarkDialog(self)
        if t and d.exec():
            opts = d.options()
            self.preview_change(_("Watermark"), lambda doc: ops.watermark(doc, **opts), _("_watermark"))

    def page_numbers(self):
        t = self.require_doc()
        d = dialogs.PageNumbersDialog(self)
        if t and d.exec():
            opts = d.options()
            self.preview_change(_("Page numbers"), lambda doc: ops.page_numbers(doc, **opts), _("_numbered"))

    def flatten(self):
        t = self.require_doc()
        if t:
            self.preview_change(_("Flatten form"), ops.flatten, _("_flattened"))

    def redact_search(self):
        t = self.require_doc()
        if not t:
            return
        text, ok = QInputDialog.getText(self, _("Redact text"), _("Text to remove from the whole document:"))
        if ok and text:
            self.preview_change(_("Redact text"), lambda d: ops.redact_text(d, text), _("_redacted"))

    def _derived_path(self, t, suffix):
        base = t.path or os.path.join(self.settings.value("last_dir", os.path.expanduser("~/Documentos")), t.title)
        return os.path.splitext(base)[0] + suffix + ".pdf"

    def preview_change(self, title, fn, suffix):
        t = self.require_doc()
        if not t:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            copy = pymupdf.open("pdf", t.bytes())
            fn(copy)
            result = copy.tobytes(garbage=1, deflate=True)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, title, _("The operation could not be completed:\n%s") % exc)
            return
        QApplication.restoreOverrideCursor()
        d = dialogs.PreviewDialog(self, title, result, self._derived_path(t, suffix),
                                  on_apply=lambda data: t.confirm_change() and t.replace_document(data))
        if d.exec() and d.saved_path:
            self.open_file(d.saved_path)

    def ocr_current(self):
        t = self.require_doc()
        if not t:
            return
        if not ops.ocr_languages():
            QMessageBox.warning(self, _("OCR PDF"), _("Tesseract OCR is not installed. Install the packages "
                                                      "tesseract-ocr and tesseract-ocr-spa."))
            return
        folder = tempfile.mkdtemp(prefix="acrpdf-ocr-")
        src = os.path.join(folder, "in.pdf")
        with open(src, "wb") as f:
            f.write(t.bytes())
        languages = "+".join(lang for lang in ("spa", "eng") if lang in ops.ocr_languages()) or "eng"
        progress = QProgressDialog(_("Recognizing text…"), None, 0, t.doc.page_count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def step(done, total):
            progress.setValue(done)
            QApplication.processEvents()
        try:
            text = ops.ocr_text(src, languages, progress=step)
        except ops.OperationError as exc:
            QMessageBox.critical(self, _("OCR PDF"), str(exc))
            return
        finally:
            progress.close()
        dialogs.TextResultDialog(self, _("Recognized text: %s") % t.title, text,
                                 os.path.splitext(self._derived_path(t, "_ocr"))[0] + ".txt").exec()

    def detect_fields(self):
        t = self.require_doc()
        if not t:
            return
        found = ops.detect_fields(t.doc)
        if not found:
            QMessageBox.information(self, _("Detect fields"), _("No new fields were detected."))
            return
        n = t.modify(lambda d: ops.add_detected_fields(d, found), relayout=True)
        self.set_tool("select_field")
        self.statusBar().showMessage(_("%d fields created. Click one to adjust it.") % (n or 0), 8000)

    def request_signatures(self):
        t = self.require_doc()
        if not t:
            return
        emails, ok = QInputDialog.getText(self, _("Request signatures"),
                                          _("Signers' e-mail addresses (separated by commas):"))
        emails = [e.strip() for e in emails.split(",") if "@" in e] if ok else []
        if not emails:
            return
        empty = [w for p in t.doc for w in p.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]) if not w.is_signed]
        if not empty and QMessageBox.question(
                self, _("Request signatures"),
                _("The document has no empty signature fields. Add one for each signer on the last page?")) \
                == QMessageBox.StandardButton.Yes:
            last = t.doc.page_count - 1
            r = t.doc[last].rect
            data = t.bytes()
            for i, email in enumerate(emails):
                x0 = 40 + (i % 2) * (r.width / 2)
                y0 = r.height - 110 - (i // 2) * 80
                name = email.split("@")[0]
                data = signing.add_signature_field(data, last, pymupdf.Rect(x0, y0, x0 + 220, y0 + 64),
                                                   _("Signature") + "_" + name)
            t.replace_document(data)
        folder = tempfile.mkdtemp(prefix="acrpdf-mail-")
        attachment = os.path.join(folder, t.title if t.title.lower().endswith(".pdf") else t.title + ".pdf")
        with open(attachment, "wb") as f:
            f.write(t.bytes())
        body = _("Hello,\n\nPlease sign the attached document with your digital certificate (for example with "
                 "AcrPDF, Adobe Acrobat Reader or AutoFirma) and send it back.\n\nThank you.")
        import subprocess
        try:
            subprocess.Popen(["xdg-email", "--subject", _("Signature request: %s") % t.title, "--body", body,
                              "--attach", attachment] + emails)
        except OSError as exc:
            QMessageBox.critical(self, _("Request signatures"), str(exc))
            return
        self.statusBar().showMessage(_("E-mail prepared in your mail client."), 6000)

    def ai_summarize(self):
        t = self.require_doc()
        if not t:
            return
        from . import ai
        language = i18n.language()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = ai.summarize(ai.provider_from_settings(self.settings), ops.document_text(t.doc), language)
        except ai.AIError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _("Summarize with AI"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        dialogs.MarkdownDialog(self, _("Summary of %s") % t.title, text).exec()

    def ai_translate(self):
        self.run_on_current("translate")

    def rotate(self, angle):
        t = self.doc_tab()
        if t:
            pages = t.selected_pages()
            t.modify(lambda d: ops.rotate_pages(d, pages, angle), relayout=True)

    def rotate_left(self):
        self.rotate(-90)

    def rotate_right(self):
        self.rotate(90)

    def duplicate_pages(self):
        t = self.doc_tab()
        if t:
            pages = t.selected_pages()
            t.modify(lambda d: ops.duplicate_pages(d, pages), relayout=True)

    def delete_pages(self):
        t = self.doc_tab()
        if not t:
            return
        pages = t.selected_pages()
        if len(pages) >= t.doc.page_count:
            QMessageBox.warning(self, _("Delete"), _("Cannot remove every page."))
            return
        if QMessageBox.question(self, _("Delete"), i18n.ngettext("Delete %d page?", "Delete %d pages?",
                                                                 len(pages)) % len(pages)) == QMessageBox.StandardButton.Yes:
            t.modify(lambda d: ops.delete_pages(d, pages), relayout=True)

    def insert_blank(self):
        t = self.doc_tab()
        if t:
            after = t.selected_pages()[-1]
            t.modify(lambda d: ops.insert_blank(d, after), relayout=True)

    def insert_file(self):
        t = self.doc_tab()
        if not t:
            return
        paths, _f = QFileDialog.getOpenFileNames(self, _("Insert files"), os.path.expanduser("~"), dialogs.file_filter())
        if paths:
            at = t.selected_pages()[-1] + 1
            t.modify(lambda d: ops.insert_files(d, paths, at), relayout=True)

    def extract_pages(self):
        t = self.doc_tab()
        if not t:
            return
        pages = t.selected_pages()
        stem = os.path.splitext(t.path or os.path.join(os.path.expanduser("~/Documentos"), t.title))[0]
        path, _f = QFileDialog.getSaveFileName(self, _("Extract pages"), stem + _("_pages") + ".pdf", "PDF (*.pdf)")
        if path:
            ops.extract_pages(t.doc, pages, path)
            self.statusBar().showMessage(_("Pages extracted to %s") % path, 6000)

    def split_current(self):
        self.run_on_current("split")

    def encrypt(self):
        t = self.require_doc()
        d = dialogs.ProtectDialog(self)
        if not (t and d.exec()):
            return
        stem = os.path.splitext(t.path or os.path.join(os.path.expanduser("~/Documentos"), t.title))[0]
        path, _f = QFileDialog.getSaveFileName(self, _("Save protected PDF"), stem + _("_protected") + ".pdf", "PDF (*.pdf)")
        if path:
            tmp = os.path.join(tempfile.mkdtemp(prefix="acrpdf-"), "in.pdf")
            with open(tmp, "wb") as f:
                f.write(t.bytes())
            ops.protect(tmp, path, password=t.password, **d.options())
            QMessageBox.information(self, _("Protect"), _("Encrypted with AES-256:\n%s") % path)

    def decrypt(self):
        t = self.require_doc()
        if not t:
            return
        if not t.doc.is_encrypted and not t.password:
            QMessageBox.information(self, _("Remove password"), _("The document is not protected."))
            return
        stem = os.path.splitext(t.path or t.title)[0]
        path, _f = QFileDialog.getSaveFileName(self, _("Save without password"), stem + _("_unlocked") + ".pdf", "PDF (*.pdf)")
        if path:
            t.flush()
            t.doc.save(path, encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=1)
            QMessageBox.information(self, _("Remove password"), _("Saved without password:\n%s") % path)

    def print_doc(self):
        t = self.doc_tab()
        if not t:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, t.doc.page_count)
        dlg.setFromTo(1, t.doc.page_count)
        if not dlg.exec():
            return
        first, last = printer.fromPage(), printer.toPage()
        if first == 0:
            first, last = 1, t.doc.page_count
        dpi = min(printer.resolution(), 300)
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, _("Print"), _("Printing could not be started."))
            return
        progress = QProgressDialog(_("Printing…"), _("Cancel"), first - 1, last, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        for i in range(first - 1, last):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            if i > first - 1:
                printer.newPage()
            pm = t.doc[i].get_pixmap(dpi=dpi, annots=True)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888)
            area = painter.viewport()
            size = img.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawImage(QRectF((area.width() - size.width()) / 2, (area.height() - size.height()) / 2,
                                     size.width(), size.height()), img)
        progress.setValue(last)
        painter.end()

    def printer_info(self):
        installed = os.path.exists("/usr/lib/cups/backend/acrpdf")
        QMessageBox.information(
            self, _("PDF printer"),
            (_("✔ The virtual printer <b>AcrPDF</b> is installed.") if installed
             else _("✖ The virtual printer is not installed (install the .deb package).")) + "<br><br>" +
            _("Print from any program (LibreOffice, Firefox, Chrome…) to the <b>AcrPDF</b> printer and the PDF "
              "is saved in your <b>~/PDF</b> folder."))

    def properties(self):
        t = self.doc_tab()
        if not t:
            return
        meta = "\n".join(f"{k}: {v}" for k, v in (t.doc.metadata or {}).items() if v)
        QMessageBox.information(self, _("Properties"),
                                _("File: %(file)s\nPages: %(pages)d\nSize: %(size).1f KB\nEncrypted: %(enc)s\nForm: %(form)s")
                                % {"file": t.path or _("(not saved)"), "pages": t.doc.page_count,
                                   "size": os.path.getsize(t.work) / 1024, "enc": t.doc.is_encrypted,
                                   "form": bool(t.doc.is_form_pdf)} + "\n\n" + meta)

    def copy_all_text(self):
        t = self.doc_tab()
        if t:
            QApplication.clipboard().setText("\n".join(p.get_text() for p in t.doc))
            self.statusBar().showMessage(_("Text copied"), 3000)

    def preferences(self):
        d = dialogs.PreferencesDialog(self)
        if d.exec():
            d.save()

    def toggle_full_screen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def check_updates(self, manual=False):
        if getattr(self, "_update_task", None) is not None and self._update_task.isRunning():
            return
        task = Task(updater.check, manual, self.settings)
        task.done.connect(lambda release: self._update_found(release, manual))
        task.failed.connect(lambda msg: manual and QMessageBox.information(self, _("Updates"), msg))
        self._update_task = task
        task.start()

    def _update_found(self, release, manual):
        if release is None:
            if manual:
                QMessageBox.information(self, _("Updates"),
                                        _("You have the latest version (%s).") % __version__)
            return
        box = QMessageBox(self)
        box.setWindowTitle(_("Update available"))
        box.setText(_("AcrPDF %(new)s is available (you have %(old)s).")
                    % {"new": release.version, "old": __version__})
        box.setDetailedText(release.notes)
        install = box.addButton(_("Install now"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not install:
            return
        if not updater.installed_from_package():
            QMessageBox.information(self, _("Updates"),
                                    _("This copy runs from the source code. Update it with:\n\n"
                                      "git pull && make deb && make install"))
            return
        progress = QProgressDialog(_("Downloading %s…") % release.version, None, 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        task = Task(lambda: updater.download(release, lambda d, t: task.progress.emit(d, t)))
        task.progress.connect(lambda d, t: progress.setValue(int(d * 100 / t) if t else 0))
        task.done.connect(lambda path: (progress.close(), self._install_update(path, release)))
        task.failed.connect(lambda msg: (progress.close(), QMessageBox.critical(self, _("Updates"), msg)))
        self._update_task = task
        task.start()

    def _install_update(self, path, release):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            updater.install(path)
        except updater.UpdateError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _("Updates"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        answer = QMessageBox.question(self, _("Updates"),
                                      _("Version %s is installed. Restart AcrPDF now?") % release.version)
        if answer == QMessageBox.StandardButton.Yes and self.close():
            QProcess.startDetached("/usr/bin/acrpdf", [])

    def about(self):
        QMessageBox.about(self, _("About AcrPDF"),
                          f"<h3>{APP_NAME} {__version__}</h3>"
                          + _("PDF viewer, editor and digital signing tool for Linux.") + "<br>"
                          + _("Built with PyMuPDF, pyHanko and Qt 6.") + "<br><br>"
                          + _("License: AGPL-3.0-or-later"))


def _install_qt_translations(app, language):
    locale = QLocale(language) if language else QLocale.system()
    translator = QTranslator(app)
    if translator.load(locale, "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)


def _install_excepthook():
    import traceback

    def hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        if QApplication.instance() is not None:
            QMessageBox.critical(None, APP_NAME, _("Unexpected error:") + f"\n{exc_type.__name__}: {exc}")
    sys.excepthook = hook


def main():
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ID)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    language = QSettings().value("language", "") or None
    i18n.setup(language)
    _install_qt_translations(app, language)
    window = MainWindow([a for a in sys.argv[1:] if not a.startswith("-")])
    window.show()
    sys.exit(app.exec())
