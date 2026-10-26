from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidget,
                             QPlainTextEdit, QToolButton, QVBoxLayout)

from .i18n import _


class _Editor:
    def __init__(self, view, widget, scene_pos):
        self.view = view
        self.widget = widget
        self.proxy = view.scene().addWidget(widget)
        self.proxy.setZValue(40)
        self.proxy.setPos(scene_pos)
        self._done = False
        view.show_editor(self)

    def contains_scene(self, sp):
        return self.proxy.sceneBoundingRect().adjusted(-2, -2, 2, 2).contains(sp)

    def _close(self):
        self._done = True
        if self.view.editor is self:
            self.view.editor = None
        scene = self.proxy.scene()
        if scene is not None:
            scene.removeItem(self.proxy)
        self.widget.deleteLater()

    def commit(self):
        if not self._done:
            self._close()
            self.on_commit()

    def cancel(self):
        if not self._done:
            self._close()

    def on_commit(self):
        raise NotImplementedError


class TextBoxEditor(_Editor):

    def __init__(self, view, scene_pos, callback, family="DejaVu Sans", size=12.0, color="#000000",
                 text="", note=False):
        self.view = view
        self.callback = callback
        self.family = family
        self.size = float(size)
        self.color = QColor(color)
        self.note = note
        frame = QFrame()
        frame.setObjectName("inlineText")
        frame.setStyleSheet(
            "#inlineText{background:transparent;}"
            "QToolButton{background:#ffffff;border:1px solid #c9d6ea;border-radius:3px;padding:0 4px;}"
            "QToolButton:hover{background:#e9eef7;}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        for text_, tip, slot in (("A−", _("Smaller text"), lambda: self._resize_font(-1)),
                                 ("A+", _("Larger text"), lambda: self._resize_font(1)),
                                 ("✓", _("Apply (Ctrl+Enter)"), self.commit),
                                 ("🗑", _("Discard (Esc)"), self.cancel)):
            b = QToolButton(text=text_)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.edit = QPlainTextEdit()
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bg = "#fff8c4" if note else "rgba(255,255,255,0.55)"
        self.edit.setStyleSheet(f"QPlainTextEdit{{background:{bg};border:1px dashed #1473e6;"
                                f"color:{self.color.name()};padding:0px;}}")
        self.edit.document().setDocumentMargin(1)
        self.edit.setPlainText(text)
        self.edit.textChanged.connect(self._fit)
        self._filter = _KeyFilter(self)
        self.edit.installEventFilter(self._filter)
        lay.addWidget(self.edit)
        self.frame = frame
        self._apply_font()
        super().__init__(view, frame, QPointF(scene_pos.x() - 2, scene_pos.y() - 26))
        self.edit.setFocus()
        self.edit.moveCursor(self.edit.textCursor().MoveOperation.End)

    def _apply_font(self):
        font = QFont(self.family)
        font.setPixelSize(max(4, round(self.size * self.view_scale())))
        self.edit.setFont(font)
        self._fit()

    def view_scale(self):
        return self.view.scale()

    def _resize_font(self, delta):
        self.size = max(4.0, self.size + delta)
        self._apply_font()

    def _fit(self):
        fm = QFontMetricsF(self.edit.font())
        lines = self.edit.toPlainText().split("\n") or [""]
        width = max(fm.horizontalAdvance(line) for line in lines) + fm.averageCharWidth() * 3 + 8
        height = fm.lineSpacing() * len(lines) + 8
        width = max(width, 160 if self.note else 60)
        self.edit.setFixedSize(int(width), int(max(height, 60 if self.note else height)))
        self.frame.adjustSize()

    def on_commit(self):
        text = self.edit.toPlainText().rstrip()
        if text:
            self.callback(text, self.size)


class _KeyFilter(QObject):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key, mods = event.key(), event.modifiers()
            if key == Qt.Key.Key_Escape:
                self.editor.cancel()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & Qt.KeyboardModifier.ControlModifier:
                self.editor.commit()
                return True
            if isinstance(self.editor, FieldEditor) and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self.editor.next_field = -1 if key == Qt.Key.Key_Backtab else 1
                self.editor.commit()
                return True
            if (isinstance(self.editor, FieldEditor) and not self.editor.multiline
                    and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
                self.editor.commit()
                return True
        return False


class FieldEditor(_Editor):

    def __init__(self, view, scene_rect, value, callback, multiline=False, font_size=0):
        self.callback = callback
        self.multiline = multiline
        self.next_field = 0
        self.original = value or ""
        widget = QPlainTextEdit() if multiline else QLineEdit()
        if multiline:
            widget.setPlainText(self.original)
        else:
            widget.setText(self.original)
        widget.setStyleSheet("background:#fffbe6;border:2px solid #1473e6;padding:0 2px;")
        size_px = (font_size or max(7.0, min(scene_rect.height() / view.scale() * 0.65, 14))) * view.scale()
        font = QFont("DejaVu Sans")
        font.setPixelSize(max(6, round(size_px)))
        widget.setFont(font)
        widget.setFixedSize(int(max(30, scene_rect.width())), int(max(16, scene_rect.height())))
        self._filter = _KeyFilter(self)
        widget.installEventFilter(self._filter)
        self.input = widget
        super().__init__(view, widget, scene_rect.topLeft())
        widget.setFocus()
        if not multiline:
            widget.selectAll()

    def value(self):
        return self.input.toPlainText() if self.multiline else self.input.text()

    def on_commit(self):
        self.callback(self.value(), self.next_field)


class ChoiceEditor(_Editor):

    def __init__(self, view, scene_rect, choices, current, callback, listbox=False):
        self.callback = callback
        self.choices = choices
        if listbox:
            widget = QListWidget()
            widget.addItems(choices)
            widget.setFixedSize(int(max(80, scene_rect.width())), int(max(60, scene_rect.height())))
            if current in choices:
                widget.setCurrentRow(choices.index(current))
            widget.itemClicked.connect(lambda _it: self.commit())
            self.current = lambda: widget.currentItem().text() if widget.currentItem() else None
        else:
            widget = QComboBox()
            widget.addItems(choices)
            widget.setFixedSize(int(max(80, scene_rect.width())), int(max(20, scene_rect.height())))
            if current in choices:
                widget.setCurrentIndex(choices.index(current))
            widget.activated.connect(lambda _i: self.commit())
            self.current = widget.currentText
        widget.setStyleSheet("background:#fffbe6;")
        super().__init__(view, widget, scene_rect.topLeft())
        widget.setFocus()
        if not listbox:
            widget.showPopup()

    def on_commit(self):
        value = self.current()
        if value is not None:
            self.callback(value)
