import os
import shutil
import tempfile

import pymupdf
from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                             QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import ops
from .i18n import _
from .overlay import ChoiceEditor, FieldEditor
from .viewer import PageView

WORK_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "acrpdf", "work")
MAX_UNDO = 40


def page_pixmap(page, zoom):
    pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(img)


class OrganizeView(QListWidget):
    orderChanged = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(150, 200))
        self.setGridSize(QSize(180, 240))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setSpacing(8)
        self.setStyleSheet("QListWidget{background:#e4e4e4;} QListWidget::item:selected{background:#cfe0fb;"
                           "border:2px solid #1473e6;border-radius:6px;}")

    def fill(self, doc):
        self.clear()
        for page in doc:
            it = QListWidgetItem(QIcon(page_pixmap(page, 0.3)), str(page.number + 1))
            it.setData(Qt.ItemDataRole.UserRole, page.number)
            self.addItem(it)

    def dropEvent(self, e):
        super().dropEvent(e)
        order = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
        if order != sorted(order):
            self.orderChanged.emit(order)

    def selected_pages(self):
        return sorted(self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())
                      if self.item(i).isSelected())


class DocumentTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, main, path=None, doc=None, title=None, password=None):
        super().__init__()
        self.main = main
        self.path = path
        self.password = password
        self.modified = False
        self.undo_stack, self.redo_stack = [], []
        self.search_hits, self.search_pos, self._last_search = [], -1, None
        self.warned_signed = False
        self.saved_size = 0
        os.makedirs(WORK_DIR, exist_ok=True)
        fd, self.work = tempfile.mkstemp(suffix=".pdf", dir=WORK_DIR)
        os.close(fd)
        if doc is None:
            shutil.copyfile(path, self.work)
        else:
            doc.save(self.work, garbage=1, deflate=True)
            doc.close()
            self.modified = True
        self.title = title or (os.path.basename(path) if path else _("Untitled.pdf"))
        self.doc = self._open_work()
        self._build_ui()
        self.reload_view()

    def _open_work(self):
        doc = pymupdf.open(self.work)
        if doc.needs_pass and not (self.password and doc.authenticate(self.password)):
            raise PermissionError("password")
        return doc

    def _reopen(self):
        self.doc = self._open_work()
        if hasattr(self, "view"):
            self.view.doc = self.doc

    def flush(self):
        if not self.doc.is_dirty:
            return
        try:
            self.doc.save(self.work, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        except (RuntimeError, ValueError):
            self._replace_bytes(self.doc.tobytes(garbage=1, deflate=True))
            return
        self.doc.close()
        self._reopen()

    def bytes(self):
        self.flush()
        with open(self.work, "rb") as f:
            return f.read()

    def _replace_bytes(self, data):
        self.doc.close()
        with open(self.work, "wb") as f:
            f.write(data)
        self._reopen()

    def checkpoint(self):
        self.undo_stack.append(self.bytes())
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()

    def confirm_change(self):
        if self.warned_signed or not ops.has_signatures(self.doc):
            return True
        answer = QMessageBox.question(
            self, _("Signed document"),
            _("This document has digital signatures.\n\nChanges are saved as an incremental "
              "revision: the signatures stay valid for the signed version, but readers will "
              "report that the document was changed afterwards.\n\nContinue?"))
        self.warned_signed = answer == QMessageBox.StandardButton.Yes
        return self.warned_signed

    def modify(self, fn, pages=None, relayout=False, sidebar=False):
        self.view.finish_editing()
        if not self.confirm_change():
            return None
        self.checkpoint()
        try:
            result = fn(self.doc)
        except Exception as exc:
            self._replace_bytes(self.undo_stack.pop())
            QMessageBox.critical(self, _("Error"), _("The operation could not be completed:\n%s") % exc)
            return None
        self.set_modified()
        if relayout:
            self.reload_view(keep=True)
        else:
            self.view.refresh(pages)
            if sidebar:
                self.refresh_sidebar()
            else:
                self.refresh_thumbs(pages)
        return result

    def replace_document(self, data, keep=True):
        self.checkpoint()
        self._replace_bytes(data)
        self.set_modified()
        self.reload_view(keep=keep)

    def undo(self):
        self.view.finish_editing()
        if self.undo_stack:
            self.redo_stack.append(self.bytes())
            self._replace_bytes(self.undo_stack.pop())
            self.set_modified()
            self.reload_view(keep=True)

    def redo(self):
        self.view.finish_editing()
        if self.redo_stack:
            self.undo_stack.append(self.bytes())
            self._replace_bytes(self.redo_stack.pop())
            self.set_modified()
            self.reload_view(keep=True)

    def set_modified(self, value=True):
        self.modified = value
        self.changed.emit()

    def export_bytes(self):
        from PyQt6.QtCore import QSettings
        return ops.compact_bytes(self.bytes(), QSettings().value("save/compression", "recommended"))

    def save(self, path=None):
        self.view.finish_editing()
        path = path or self.path
        data = self.export_bytes()
        with open(path, "wb") as f:
            f.write(data)
        self.saved_size = len(data)
        self.path = path
        self.title = os.path.basename(path)
        self.set_modified(False)
        self.main.add_recent(path)

    def close_doc(self):
        try:
            self.doc.close()
        except (ValueError, RuntimeError):
            pass
        if os.path.exists(self.work):
            os.unlink(self.work)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.search_bar = QWidget()
        self.search_bar.setObjectName("searchBar")
        bar = QHBoxLayout(self.search_bar)
        bar.setContentsMargins(8, 4, 8, 4)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_("Find in document…"))
        self.search_edit.returnPressed.connect(lambda: self.find_next(1))
        self.search_info = QLabel("")
        prev_b, next_b, close_b = QPushButton("◀"), QPushButton("▶"), QPushButton("✕")
        prev_b.clicked.connect(lambda: self.find_next(-1))
        next_b.clicked.connect(lambda: self.find_next(1))
        close_b.clicked.connect(self.hide_search)
        for w in (QLabel(_("Find:")), self.search_edit, prev_b, next_b, self.search_info):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(close_b)
        self.search_bar.hide()
        lay.addWidget(self.search_bar)

        split = QSplitter()
        lay.addWidget(split, 1)
        self.sidebar = QTabWidget()
        self.sidebar.setTabPosition(QTabWidget.TabPosition.West)
        self.sidebar.setMinimumWidth(150)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setIconSize(QSize(120, 160))
        self.thumbs.setFlow(QListWidget.Flow.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setSpacing(6)
        self.thumbs.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.thumbs.itemClicked.connect(lambda it: self.view.go_to(self.thumbs.row(it)))
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(
            lambda pos: self.page_menu().exec(self.thumbs.mapToGlobal(pos)))
        self.sidebar.addTab(self.thumbs, _("Pages"))
        self.toc = QTreeWidget()
        self.toc.setHeaderHidden(True)
        self.toc.itemClicked.connect(self._toc_clicked)
        self.sidebar.addTab(self.toc, _("Bookmarks"))
        self.sigs = QTreeWidget()
        self.sigs.setHeaderLabels([_("Signature"), _("Status")])
        self.sidebar.addTab(self.sigs, _("Signatures"))
        self.fields = QTreeWidget()
        self.fields.setHeaderLabels([_("Field"), _("Type"), _("Value")])
        self.fields.itemDoubleClicked.connect(self._field_activated)
        self.sidebar.addTab(self.fields, _("Fields"))
        self.comments = QTreeWidget()
        self.comments.setHeaderLabels([_("Comment"), _("Page")])
        self.comments.itemClicked.connect(lambda it, _c: self.view.go_to(it.data(0, Qt.ItemDataRole.UserRole)))
        self.sidebar.addTab(self.comments, _("Comments"))
        split.addWidget(self.sidebar)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        self.banner = QWidget()
        self.banner.setObjectName("signatureBanner")
        banner_lay = QHBoxLayout(self.banner)
        banner_lay.setContentsMargins(12, 6, 8, 6)
        self.banner_icon = QLabel()
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_button = QPushButton(_("Signature panel"))
        self.banner_button.clicked.connect(self._banner_clicked)
        banner_lay.addWidget(self.banner_icon)
        banner_lay.addWidget(self.banner_text, 1)
        banner_lay.addWidget(self.banner_button)
        self.banner.hide()
        right_lay.addWidget(self.banner)
        self.stack = QStackedWidget()
        right_lay.addWidget(self.stack, 1)
        self.view = PageView()
        self.view.click_handler = self._canvas_click
        self.view.toolFinished.connect(self.main.tool_finished)
        self.view.contextRequested.connect(self._context_menu)
        self.view.pageChanged.connect(lambda i: self.main.page_changed(self, i))
        self.view.zoomChanged.connect(lambda z: self.main.zoom_changed(self, z))
        self.organizer = OrganizeView()
        self.organizer.orderChanged.connect(lambda order: self.modify(lambda d: ops.reorder(d, order), relayout=True))
        self.organizer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.organizer.customContextMenuRequested.connect(
            lambda pos: self.page_menu().exec(self.organizer.mapToGlobal(pos)))
        self.organizer.itemDoubleClicked.connect(lambda it: (self.set_organize(False),
                                                             self.view.go_to(it.data(Qt.ItemDataRole.UserRole))))
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.organizer)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([190, 900])

    def set_organize(self, on):
        self.view.finish_editing()
        if on:
            self.organizer.fill(self.doc)
        self.stack.setCurrentWidget(self.organizer if on else self.view)

    def organizing(self):
        return self.stack.currentWidget() is self.organizer

    def reload_view(self, keep=False):
        self.view.set_document(self.doc, keep_position=keep)
        if self.organizing():
            self.organizer.fill(self.doc)
        self.refresh_sidebar()

    def refresh_sidebar(self):
        self.refresh_thumbs()
        self.toc.clear()
        stack = [self.toc.invisibleRootItem()]
        for level, title, page, *_rest in self.doc.get_toc(simple=False):
            while len(stack) > level:
                stack.pop()
            it = QTreeWidgetItem(stack[-1], [title])
            it.setData(0, Qt.ItemDataRole.UserRole, page - 1)
            stack.append(it)
        self.toc.expandAll()
        self.fields.clear()
        for page, name, typ, value, xref in ops.all_fields(self.doc):
            it = QTreeWidgetItem(self.fields, [name, typ, str(value)])
            it.setData(0, Qt.ItemDataRole.UserRole, (page, xref))
        self.comments.clear()
        for page in self.doc:
            for annot in page.annots():
                text = annot.info.get("content") or annot.type[1]
                it = QTreeWidgetItem(self.comments, [f"{annot.type[1]}: {text[:60]}", str(page.number + 1)])
                it.setData(0, Qt.ItemDataRole.UserRole, page.number)
        self.refresh_signatures()

    def refresh_signatures(self):
        self.sigs.clear()
        empty_fields = [w for p in self.doc for w in p.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE])
                        if not w.is_signed]
        if not ops.has_signatures(self.doc):
            QTreeWidgetItem(self.sigs, [_("No digital signatures"), ""])
            if empty_fields:
                self._show_banner("info", _("This document has %d signature field(s) waiting to be signed.")
                                  % len(empty_fields), _("Sign"))
            else:
                self.banner.hide()
            return
        from . import signing
        results = signing.validate(self.bytes())
        states = []
        for r in results:
            if "error" in r:
                it = QTreeWidgetItem(self.sigs, [r["field"], _("Error")])
                QTreeWidgetItem(it, [r["error"][:200], ""])
                states.append("invalid")
                continue
            ok = r["intact"] and r["valid"]
            if ok and r["trusted"]:
                state, states_key = "✔ " + _("Valid"), "valid"
            elif ok:
                state, states_key = "✔ " + _("Intact (CA not verified)"), "untrusted"
            else:
                state, states_key = "✖ " + _("Invalid"), "invalid"
            states.append(states_key)
            it = QTreeWidgetItem(self.sigs, [r["signer"], state])
            it.setForeground(1, Qt.GlobalColor.darkGreen if ok else Qt.GlobalColor.red)
            for key, value in ((_("Field"), r["field"]), (_("Issuer"), r["issuer"]), (_("Date"), r["time"]),
                               (_("Coverage"), r["coverage"]), (_("Later changes"), r["modification"])):
                QTreeWidgetItem(it, [key, value])
        self.sigs.expandAll()
        names = ", ".join(sorted({r.get("signer", "?") for r in results if "signer" in r}))
        changed = any(r.get("modification") not in ("", "NONE", "FORM_FILLING", None) for r in results)
        if "invalid" in states:
            self._show_banner("error", _("At least one signature is invalid: the document was altered or "
                                         "the signature is damaged."))
        elif "untrusted" in states:
            self._show_banner("warning", _("Signed by %s. The signatures are intact, but at least one "
                                           "signer's identity could not be verified.") % names)
        else:
            self._show_banner("ok", _("Signed and all signatures are valid: %s.") % names
                              + (" " + _("The document was changed after signing.") if changed else ""))

    BANNER_STYLES = {"ok": ("#e7f4ea", "#1a7f37", "✔"), "warning": ("#fff6dd", "#8a6100", "⚠"),
                     "error": ("#fdecea", "#b3261e", "✖"), "info": ("#e8f0fe", "#1a56c4", "✍")}

    def _show_banner(self, kind, text, button=None):
        bg, fg, icon = self.BANNER_STYLES[kind]
        self.banner.setStyleSheet(f"#signatureBanner{{background:{bg};border-bottom:1px solid {fg};}}"
                                  f"QLabel{{color:{fg};}}")
        self.banner_icon.setText(f"<b style='font-size:16pt'>{icon}</b>")
        self.banner_text.setText(text)
        self.banner_button.setText(button or _("Signature panel"))
        self.banner_kind = kind
        self.banner.show()

    def _banner_clicked(self):
        if getattr(self, "banner_kind", "") == "info":
            for p in self.doc:
                for w in p.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
                    if not w.is_signed:
                        self.view.go_to(p.number, ops.to_visible(p, w.rect).y0)
                        self.main.digital_sign(field=w.field_name, page=p.number)
                        return
        self.sidebar.show()
        self.sidebar.setCurrentWidget(self.sigs)

    def refresh_thumbs(self, pages=None):
        n = self.doc.page_count
        if self.thumbs.count() != n or pages is None:
            self.thumbs.clear()
            pages = range(n)
            for i in range(n):
                self.thumbs.addItem(QListWidgetItem(str(i + 1)))
        for i in pages:
            if i < n:
                self.thumbs.item(i).setIcon(QIcon(page_pixmap(self.doc[i], 0.25)))

    def selected_pages(self):
        if self.organizing():
            rows = self.organizer.selected_pages()
        else:
            rows = sorted(self.thumbs.row(i) for i in self.thumbs.selectedItems())
        return rows or [self.view.current_page()]

    def page_menu(self):
        m = QMenu(self)
        m.addAction(_("Rotate right"), lambda: self.main.rotate(90))
        m.addAction(_("Rotate left"), lambda: self.main.rotate(-90))
        m.addAction(_("Duplicate"), self.main.duplicate_pages)
        m.addAction(_("Delete pages"), self.main.delete_pages)
        m.addAction(_("Extract pages…"), self.main.extract_pages)
        m.addAction(_("Insert blank page"), self.main.insert_blank)
        m.addAction(_("Insert from file…"), self.main.insert_file)
        return m

    def _toc_clicked(self, item, _col):
        p = item.data(0, Qt.ItemDataRole.UserRole)
        if p is not None and p >= 0:
            self.view.go_to(p)

    def show_search(self):
        self.search_bar.show()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def hide_search(self):
        self.search_bar.hide()
        self.view.clear_marks()

    def find_next(self, direction=1):
        text = self.search_edit.text()
        if not text:
            return
        if self._last_search != text:
            self._last_search = text
            self.search_hits = [(p.number, r) for p in self.doc for r in p.search_for(text)]
            self.search_pos = -1 if direction > 0 else 0
        if not self.search_hits:
            self.search_info.setText(_("No results"))
            return
        self.search_pos = (self.search_pos + direction) % len(self.search_hits)
        page, rect = self.search_hits[self.search_pos]
        rot = self.doc[page].rotation_matrix
        self.view.go_to(page, (rect * rot).y0)
        self.view.mark(page, [r * rot for p, r in self.search_hits if p == page], rect * rot)
        self.search_info.setText(_("%(i)d of %(n)d") % {"i": self.search_pos + 1, "n": len(self.search_hits)})

    def _canvas_click(self, idx, pt, _event):
        page = self.doc[idx]
        widget = ops.widget_at(page, pt)
        if self.view.tool == "select_field":
            if widget is not None:
                self.select_field(idx, widget.xref)
            return True
        if widget is not None:
            self.fill_widget(idx, widget.xref)
            return True
        graphic = ops.graphic_at(page, pt)
        if graphic is not None:
            self.select_graphic(idx, *graphic)
            return True
        upt = ops.to_unrotated_pt(page, pt)
        for link in page.get_links():
            if link["from"].contains(upt):
                if link.get("kind") == pymupdf.LINK_GOTO:
                    self.view.go_to(link["page"])
                elif link.get("uri"):
                    QDesktopServices.openUrl(QUrl(link["uri"]))
                return True
        return False

    def _text_fields(self):
        return [(p.number, w.xref) for p in self.doc for w in p.widgets()
                if w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT]

    def fill_widget(self, idx, xref):
        page = self.doc[idx]
        w = ops.find_widget(page, xref)
        if w is None:
            return
        scene_rect = self.view.page_rect_to_scene(idx, ops.to_visible(page, w.rect))
        t = w.field_type
        if t in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
            on = w.field_value not in (False, "Off", "", None, "False")
            self.modify(lambda d: ops.set_field(d, idx, xref, not on), [idx], sidebar=True)
        elif t == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
            if w.is_signed:
                self.sidebar.setCurrentWidget(self.sigs)
            else:
                self.main.digital_sign(field=w.field_name, page=idx)
        elif t in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
            choices = [v[0] if isinstance(v, (list, tuple)) else v for v in (w.choice_values or [])]
            ChoiceEditor(self.view, scene_rect, choices, w.field_value,
                         lambda v: self.modify(lambda d: ops.set_field(d, idx, xref, v), [idx], sidebar=True),
                         listbox=t == pymupdf.PDF_WIDGET_TYPE_LISTBOX)
        elif t == pymupdf.PDF_WIDGET_TYPE_TEXT:
            multiline = bool(w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE)
            current = w.field_value or ""

            def done(value, step):
                if value != current:
                    self.modify(lambda d: ops.set_field(d, idx, xref, value), [idx], sidebar=True)
                order = self._text_fields()
                if step and (idx, xref) in order:
                    next_page, next_xref = order[(order.index((idx, xref)) + step) % len(order)]
                    if next_page != idx:
                        target = ops.find_widget(self.doc[next_page], next_xref)
                        self.view.go_to(next_page, ops.to_visible(self.doc[next_page], target.rect).y0)
                    self.fill_widget(next_page, next_xref)
            FieldEditor(self.view, scene_rect, current, done, multiline, w.text_fontsize)

    def select_graphic(self, idx, xref, rect):
        from .dialogs import graphic_pixmap
        data = ops.graphic_source(self.doc, xref)
        if data is None or not self.confirm_change():
            return
        self.checkpoint()
        ops.remove_graphic(self.doc[idx], xref)
        self.view.refresh([idx])
        pixmap = graphic_pixmap(ops.render_graphic_png(data, 900), 900, 900)

        def commit(i, r):
            ops.insert_graphic(self.doc[i], r, data)
            self.set_modified()
            self.view.refresh([i])
            self.refresh_thumbs([i])

        def cancel():
            self._replace_bytes(self.undo_stack.pop())
            self.view.refresh([idx])

        def delete():
            self.set_modified()
            self.refresh_thumbs([idx])

        self.view.begin_placement(idx, rect, commit, pixmap=pixmap, keep_aspect=True, commit_text=_("Apply"),
                                  on_cancel=cancel, on_delete=delete,
                                  extra_buttons=[("🗑", _("Delete (Del)"),
                                                  lambda: (self.view.discard_placement(), delete()))])
        self.main.statusBar().showMessage(_("Drag to move, use the handles to resize, Del to delete."), 6000)

    def select_field(self, idx, xref):
        page = self.doc[idx]
        w = ops.find_widget(page, xref)
        if w is None:
            return
        rect = ops.to_visible(page, w.rect)
        self.view.begin_placement(
            idx, rect, lambda i, r: self.modify(lambda d: ops.set_widget_rect(d[i], xref, r), [i], sidebar=True),
            label=w.field_name, commit_text=_("Apply"),
            on_delete=lambda: self.modify(lambda d: ops.delete_widget(d, idx, xref), [idx], sidebar=True),
            extra_buttons=[("⚙", _("Properties"), lambda: self.field_properties(idx, xref)),
                           ("🗑", _("Delete field (Del)"),
                            lambda: (self.view.cancel_placement(),
                                     self.modify(lambda d: ops.delete_widget(d, idx, xref), [idx], sidebar=True)))])

    def field_properties(self, idx, xref):
        from .dialogs import FieldDialog
        w = ops.find_widget(self.doc[idx], xref)
        if w is None:
            return
        kind = {pymupdf.PDF_WIDGET_TYPE_TEXT: "text", pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "combo",
                pymupdf.PDF_WIDGET_TYPE_LISTBOX: "list"}.get(w.field_type, "other")
        choices = [v[0] if isinstance(v, (list, tuple)) else v for v in (w.choice_values or [])]
        d = FieldDialog(self, kind, w.field_name, choices)
        d.size.setValue(int(w.text_fontsize or 0))
        d.multiline.setChecked(bool(w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE))
        d.required.setChecked(bool(w.field_flags & pymupdf.PDF_FIELD_IS_REQUIRED))
        if not d.exec():
            return
        v = d.values()

        def apply(doc):
            widget = ops.find_widget(doc[idx], xref)
            widget.field_name = v["name"] or widget.field_name
            if v["tooltip"]:
                widget.field_label = v["tooltip"]
            if kind in ("combo", "list") and v["options"]:
                widget.choice_values = v["options"]
            if kind in ("text", "combo", "list"):
                widget.text_fontsize = v["fontsize"]
            flags = widget.field_flags & ~(pymupdf.PDF_TX_FIELD_IS_MULTILINE | pymupdf.PDF_FIELD_IS_REQUIRED)
            if v["multiline"] and kind == "text":
                flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
            if v["required"]:
                flags |= pymupdf.PDF_FIELD_IS_REQUIRED
            widget.field_flags = flags
            widget.update()
        self.view.cancel_placement()
        self.modify(apply, [idx], sidebar=True)

    def _field_activated(self, item, _col):
        page, xref = item.data(0, Qt.ItemDataRole.UserRole)
        w = ops.find_widget(self.doc[page], xref)
        if w is not None:
            self.view.go_to(page, ops.to_visible(self.doc[page], w.rect).y0)
            self.fill_widget(page, xref)

    def _context_menu(self, idx, pt, global_pos):
        page = self.doc[idx]
        m = QMenu(self)
        annot = ops.annot_at(page, pt)
        widget = ops.widget_at(page, pt)
        if widget is not None:
            name, xref = widget.field_name, widget.xref
            if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and not widget.is_signed:
                m.addAction(_("Sign this field with a certificate…"),
                            lambda: self.main.digital_sign(field=name, page=idx))
            m.addAction(_("Fill «%s»") % name, lambda: self.fill_widget(idx, xref))
            m.addAction(_("Move / resize"), lambda: self.select_field(idx, xref))
            m.addAction(_("Properties…"), lambda: self.field_properties(idx, xref))
            m.addAction(_("Delete field"),
                        lambda: self.modify(lambda d: ops.delete_widget(d, idx, xref), [idx], sidebar=True))
            m.addSeparator()
        elif annot is not None:
            axref = annot.xref
            if annot.type[0] in (pymupdf.PDF_ANNOT_TEXT, pymupdf.PDF_ANNOT_FREE_TEXT):
                m.addAction(_("Edit text…"), lambda: self._edit_annot_text(idx, axref))
            m.addAction(_("Delete comment"),
                        lambda: self.modify(lambda d: d[idx].delete_annot(d[idx].load_annot(axref)), [idx], sidebar=True))
            m.addSeparator()
        m.addAction(_("Copy page text"), lambda: QApplication.clipboard().setText(page.get_text()))
        m.addAction(_("Rotate page"), lambda: self.modify(lambda d: ops.rotate_pages(d, [idx], 90), relayout=True))
        m.addAction(_("Delete page"), lambda: self.modify(lambda d: ops.delete_pages(d, [idx]), relayout=True))
        m.exec(global_pos)

    def _edit_annot_text(self, idx, xref):
        annot = self.doc[idx].load_annot(xref)
        text, ok = QInputDialog.getMultiLineText(self, _("Comment"), _("Text:"), annot.info.get("content", ""))
        if ok:
            def apply(doc):
                a = doc[idx].load_annot(xref)
                a.set_info(content=text)
                a.update()
            self.modify(apply, [idx], sidebar=True)
