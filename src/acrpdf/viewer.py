import pymupdf
from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QGraphicsDropShadowEffect, QGraphicsLineItem, QGraphicsObject,
                             QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
                             QGraphicsScene, QGraphicsView, QHBoxLayout, QToolButton, QWidget)

from .i18n import _

GAP = 14
BASE = 96 / 72

LINE_TOOLS = {"line", "arrow"}
POINT_TOOLS = {"note", "edit_text", "erase", "add_text", "freetext", "check_mark", "cross_mark"}
HANDLE = 7


class PlacementItem(QGraphicsObject):

    def __init__(self, rect, bounds, pixmap=None, keep_aspect=False, label=""):
        super().__init__()
        self._rect = QRectF(rect)
        self.bounds = QRectF(bounds)
        self.pixmap = pixmap
        self.keep_aspect = keep_aspect
        self.label = label
        self._mode = None
        self._press = None
        self._start = None
        self.setAcceptHoverEvents(True)
        self.setZValue(30)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsFocusable)

    def rect(self):
        return QRectF(self._rect)

    def boundingRect(self):
        return self._rect.adjusted(-HANDLE, -HANDLE - 16, HANDLE, HANDLE)

    def _handles(self):
        r = self._rect
        pts = {"tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(), "br": r.bottomRight(),
               "t": QPointF(r.center().x(), r.top()), "b": QPointF(r.center().x(), r.bottom()),
               "l": QPointF(r.left(), r.center().y()), "r": QPointF(r.right(), r.center().y())}
        return {k: QRectF(p.x() - HANDLE / 2, p.y() - HANDLE / 2, HANDLE, HANDLE) for k, p in pts.items()}

    def _hit(self, pos):
        for name, h in self._handles().items():
            if h.adjusted(-3, -3, 3, 3).contains(pos):
                return name
        return "move" if self._rect.contains(pos) else None

    def contains_scene(self, sp):
        return self._hit(self.mapFromScene(sp)) is not None

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.pixmap is not None and not self.pixmap.isNull():
            target = self._rect
            if self.keep_aspect:
                s = QSizeF(self.pixmap.size()).scaled(self._rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
                target = QRectF(self._rect.center().x() - s.width() / 2, self._rect.center().y() - s.height() / 2,
                                s.width(), s.height())
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        else:
            painter.fillRect(self._rect, QColor(20, 115, 230, 28))
        painter.setPen(QPen(QColor("#1473e6"), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._rect)
        painter.setPen(QPen(QColor("#1473e6"), 1))
        painter.setBrush(QColor("white"))
        for h in self._handles().values():
            painter.drawRect(h)
        if self.label:
            painter.setPen(QColor("#1473e6"))
            painter.drawText(self._rect.topLeft() + QPointF(0, -4), self.label)

    _CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                "move": Qt.CursorShape.SizeAllCursor}

    def hoverMoveEvent(self, e):
        self.setCursor(self._CURSORS.get(self._hit(e.pos()), Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, e):
        self._mode = self._hit(e.pos())
        self._press = e.pos()
        self._start = QRectF(self._rect)
        self.setFocus()
        e.accept()

    def mouseMoveEvent(self, e):
        if not self._mode:
            return
        d = e.pos() - self._press
        r = QRectF(self._start)
        if self._mode == "move":
            r.translate(d)
            r.moveLeft(max(self.bounds.left(), min(r.left(), self.bounds.right() - r.width())))
            r.moveTop(max(self.bounds.top(), min(r.top(), self.bounds.bottom() - r.height())))
        else:
            if "l" in self._mode:
                r.setLeft(min(r.left() + d.x(), r.right() - 8))
            if "r" in self._mode:
                r.setRight(max(r.right() + d.x(), r.left() + 8))
            if "t" in self._mode:
                r.setTop(min(r.top() + d.y(), r.bottom() - 8))
            if "b" in self._mode:
                r.setBottom(max(r.bottom() + d.y(), r.top() + 8))
            corner = len(self._mode) == 2
            if self.keep_aspect and corner and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                ratio = self._start.width() / max(self._start.height(), 1)
                w = max(r.width(), r.height() * ratio)
                h = w / ratio
                anchor = {"tl": self._start.bottomRight(), "tr": self._start.bottomLeft(),
                          "bl": self._start.topRight(), "br": self._start.topLeft()}[self._mode]
                x0 = anchor.x() - w if "l" in self._mode else anchor.x()
                y0 = anchor.y() - h if "t" in self._mode else anchor.y()
                r = QRectF(x0, y0, w, h)
            r = r.intersected(self.bounds)
        self.prepareGeometryChange()
        self._rect = r
        self.update()

    def mouseReleaseEvent(self, e):
        self._mode = None

    def mouseDoubleClickEvent(self, e):
        view = self.scene().views()[0]
        view.commit_placement()


class PlacementBar(QWidget):

    def __init__(self, parent, commit_text):
        super().__init__(parent)
        self.setStyleSheet("QWidget{background:#ffffff;border:1px solid #c9d6ea;border-radius:6px;}"
                           "QToolButton{border:none;padding:3px 8px;} QToolButton:hover{background:#e9eef7;}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(2)
        self.ok = QToolButton(text="✓ " + commit_text)
        self.cancel = QToolButton(text="✕")
        self.cancel.setToolTip(_("Cancel (Esc)"))
        self.extra = []
        lay.addWidget(self.ok)
        lay.addWidget(self.cancel)

    def add_button(self, text, tooltip, callback):
        b = QToolButton(text=text)
        b.setToolTip(tooltip)
        b.clicked.connect(callback)
        self.layout().insertWidget(self.layout().count() - 2, b)
        return b


class PageView(QGraphicsView):
    toolFinished = pyqtSignal(str, int, object)
    contextRequested = pyqtSignal(int, object, object)
    pageChanged = pyqtSignal(int)
    zoomChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#e4e4e4"))
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.doc = None
        self.zoom = 1.0
        self.fit_mode = "width"
        self.tool = "hand"
        self.pages = []
        self.version = {}
        self.click_handler = None
        self.editor = None
        self.placement = None
        self._placement_cb = None
        self._placement_bar = None
        self._placement_delete = None
        self._drag = None
        self._preview = None
        self._ink = []
        self._marks = []
        self._timer = QTimer(self, singleShot=True, interval=30, timeout=self.render_visible)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self._timer.start())
        self.set_tool("hand")

    def set_document(self, doc, keep_position=False):
        page = self.current_page() if keep_position else 0
        self.doc = doc
        self.relayout()
        if keep_position:
            self.go_to(page)

    def scale(self):
        return self.zoom * BASE

    def relayout(self):
        self.finish_editing()
        self.cancel_placement()
        scene = self.scene()
        for frame, _p, _k in self.pages:
            scene.removeItem(frame)
        self.pages = []
        self.clear_marks()
        if self.doc is None:
            return
        if self.fit_mode:
            self._apply_fit()
        s = self.scale()
        rects = [self.doc[i].rect for i in range(self.doc.page_count)]
        max_w = max((r.width * s for r in rects), default=0)
        y = GAP
        for r in rects:
            w, h = r.width * s, r.height * s
            frame = QGraphicsRectItem(0, 0, w, h)
            frame.setBrush(QBrush(Qt.GlobalColor.white))
            frame.setPen(QPen(QColor("#b8b8b8"), 0.5))
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(10)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(0, 0, 0, 70))
            frame.setGraphicsEffect(shadow)
            frame.setPos(GAP + (max_w - w) / 2, y)
            pix = QGraphicsPixmapItem(frame)
            pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            scene.addItem(frame)
            self.pages.append([frame, pix, None])
            y += h + GAP
        scene.setSceneRect(0, 0, max_w + 2 * GAP, y)
        self.zoomChanged.emit(self.zoom)
        self._timer.start()

    def _apply_fit(self):
        if not self.doc or not self.doc.page_count:
            return
        r = self.doc[min(self.current_page(), self.doc.page_count - 1)].rect
        vw = self.viewport().width() - 2 * GAP - 4
        vh = self.viewport().height() - 2 * GAP
        if self.fit_mode == "width":
            self.zoom = max(0.1, vw / (r.width * BASE))
        elif self.fit_mode == "page":
            self.zoom = max(0.1, min(vw / (r.width * BASE), vh / (r.height * BASE)))

    def render_visible(self):
        if self.doc is None:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect().adjusted(0, -400, 0, 400)
        dpr = self.devicePixelRatioF()
        s = self.scale()
        current = self.current_page()
        for i, entry in enumerate(self.pages):
            frame, pix, key = entry
            if not frame.sceneBoundingRect().intersects(visible):
                if key is not None and abs(i - current) > 6:
                    pix.setPixmap(QPixmap())
                    entry[2] = None
                continue
            want = (round(s, 4), self.version.get(i, 0), dpr)
            if key == want:
                continue
            pm = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(s * dpr, s * dpr), annots=True, alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888).copy()
            qpm = QPixmap.fromImage(img)
            qpm.setDevicePixelRatio(dpr)
            pix.setPixmap(qpm)
            entry[2] = want

    def refresh(self, pages=None):
        if self.doc is None:
            return
        for p in range(len(self.pages)) if pages is None else pages:
            self.version[p] = self.version.get(p, 0) + 1
        self.render_visible()

    def current_page(self):
        if not self.pages:
            return 0
        top = self.mapToScene(0, 0).y()
        probe = top + (self.mapToScene(self.viewport().rect().center()).y() - top) * 0.3
        for i, (frame, _p, _k) in enumerate(self.pages):
            if frame.sceneBoundingRect().bottom() + GAP >= probe:
                return i
        return len(self.pages) - 1

    def go_to(self, index, y_pdf=None):
        if not self.pages:
            return
        index = max(0, min(index, len(self.pages) - 1))
        frame = self.pages[index][0]
        y = frame.pos().y() - GAP / 2 if y_pdf is None else frame.pos().y() + y_pdf * self.scale() - 60
        self.verticalScrollBar().setValue(int(y))
        self.pageChanged.emit(index)

    def set_zoom(self, z, fit=None):
        page = self.current_page()
        self.fit_mode = fit
        self.zoom = max(0.1, min(z, 8.0))
        self.relayout()
        self.go_to(page)

    def zoom_in(self):
        self.set_zoom(self.zoom * 1.2)

    def zoom_out(self):
        self.set_zoom(self.zoom / 1.2)

    def _scrolled(self, _value):
        self._timer.start()
        self.pageChanged.emit(self.current_page())
        self._move_placement_bar()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode and self.doc is not None and not self.editor and not self.placement:
            old = self.zoom
            self._apply_fit()
            if abs(old - self.zoom) > 0.01:
                page = self.current_page()
                self.relayout()
                self.go_to(page)
        self._timer.start()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_in() if e.angleDelta().y() > 0 else self.zoom_out()
            return
        super().wheelEvent(e)

    def scene_to_page(self, sp):
        s = self.scale()
        for i, (frame, _p, _k) in enumerate(self.pages):
            if frame.sceneBoundingRect().adjusted(-GAP / 2, -GAP / 2, GAP / 2, GAP / 2).contains(sp):
                p = sp - frame.pos()
                return i, pymupdf.Point(p.x() / s, p.y() / s)
        return None, None

    def page_rect_to_scene(self, index, rect):
        s = self.scale()
        pos = self.pages[index][0].pos()
        return QRectF(pos.x() + rect.x0 * s, pos.y() + rect.y0 * s, rect.width * s, rect.height * s)

    def scene_rect_to_page(self, index, r):
        s = self.scale()
        pos = self.pages[index][0].pos()
        return pymupdf.Rect((r.left() - pos.x()) / s, (r.top() - pos.y()) / s,
                            (r.right() - pos.x()) / s, (r.bottom() - pos.y()) / s)

    def page_bounds(self, index):
        return self.pages[index][0].sceneBoundingRect()

    def clear_marks(self):
        for m in self._marks:
            if m.scene():
                self.scene().removeItem(m)
        self._marks = []

    def mark(self, index, rects, current=None):
        self.clear_marks()
        for r in rects:
            item = QGraphicsRectItem(self.page_rect_to_scene(index, r))
            item.setBrush(QColor(255, 140, 0, 110) if r == current else QColor(255, 230, 0, 90))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(10)
            self.scene().addItem(item)
            self._marks.append(item)

    def begin_placement(self, index, rect, on_commit, pixmap=None, keep_aspect=False, label="",
                        commit_text=None, on_cancel=None, extra_buttons=(), on_delete=None):
        self.finish_editing()
        self.cancel_placement()
        bounds = self.page_bounds(index)
        item = PlacementItem(self.page_rect_to_scene(index, rect).intersected(bounds), bounds,
                             pixmap, keep_aspect, label)
        self.scene().addItem(item)
        item.setFocus()
        self.placement = item
        self._placement_cb = (index, on_commit, on_cancel)
        self._placement_delete = on_delete
        bar = PlacementBar(self.viewport(), commit_text or _("Apply"))
        bar.ok.clicked.connect(self.commit_placement)
        bar.cancel.clicked.connect(self.cancel_placement)
        for text, tip, cb in extra_buttons:
            bar.add_button(text, tip, cb)
        bar.adjustSize()
        bar.show()
        self._placement_bar = bar
        self._move_placement_bar()
        self.ensureVisible(item.rect(), 40, 40)

    def _move_placement_bar(self):
        if self.placement is None or self._placement_bar is None:
            return
        r = self.mapFromScene(self.placement.rect()).boundingRect()
        bar = self._placement_bar
        x = max(2, min(r.left(), self.viewport().width() - bar.width() - 2))
        y = r.bottom() + 10
        if y + bar.height() > self.viewport().height():
            y = max(2, r.top() - bar.height() - 22)
        bar.move(int(x), int(y))

    def placement_rect(self):
        if self.placement is None:
            return None
        return self.scene_rect_to_page(self._placement_cb[0], self.placement.rect())

    def _drop_placement(self):
        if self.placement is not None and self.placement.scene():
            self.scene().removeItem(self.placement)
        if self._placement_bar is not None:
            self._placement_bar.hide()
            self._placement_bar.deleteLater()
        self.placement = None
        self._placement_bar = None

    def discard_placement(self):
        self._drop_placement()

    def commit_placement(self):
        if self.placement is None:
            return
        index, cb, _cancel = self._placement_cb
        rect = self.placement_rect()
        self._drop_placement()
        cb(index, rect)

    def cancel_placement(self):
        if self.placement is None:
            return
        _i, _cb, on_cancel = self._placement_cb
        self._drop_placement()
        if on_cancel:
            on_cancel()

    def show_editor(self, editor):
        self.finish_editing()
        self.editor = editor

    def finish_editing(self):
        if self.editor is not None:
            ed, self.editor = self.editor, None
            ed.commit()

    def set_tool(self, tool):
        self.tool = tool or "hand"
        self._cancel_preview()
        if self.tool == "hand":
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            text_tools = ("select_text", "highlight", "underline", "strike", "squiggly", "edit_text", "add_text")
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor if self.tool in text_tools
                                      else Qt.CursorShape.CrossCursor)

    def _cancel_preview(self):
        if self._preview is not None and self._preview.scene():
            self.scene().removeItem(self._preview)
        self._preview = None
        self._drag = None

    def mousePressEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        if self.placement is not None:
            if self.placement.contains_scene(sp):
                return super().mousePressEvent(e)
            if e.button() == Qt.MouseButton.LeftButton:
                self.commit_placement()
            return
        if self.editor is not None:
            if self.editor.contains_scene(sp):
                return super().mousePressEvent(e)
            self.finish_editing()
            return
        idx, pt = self.scene_to_page(sp)
        if e.button() == Qt.MouseButton.RightButton:
            if idx is not None:
                self.contextRequested.emit(idx, pt, e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton or idx is None:
            return super().mousePressEvent(e)
        if self.tool == "hand" or self.tool == "select_field":
            if self.click_handler and self.click_handler(idx, pt, e):
                return
            return super().mousePressEvent(e)
        if self.tool in POINT_TOOLS:
            self.toolFinished.emit(self.tool, idx, pt)
            return
        self._drag = (idx, sp)
        if self.tool in LINE_TOOLS:
            self._preview = QGraphicsLineItem(sp.x(), sp.y(), sp.x(), sp.y())
            self._preview.setPen(QPen(QColor("#d7263d"), 2))
        elif self.tool == "ink":
            self._ink = [pt]
            self._preview = QGraphicsPathItem(QPainterPath(sp))
            self._preview.setPen(QPen(QColor(self.property("inkColor") or "#000000"), 2))
        else:
            self._preview = QGraphicsRectItem(QRectF(sp, sp))
            self._preview.setPen(QPen(QColor("#1473e6"), 1.2, Qt.PenStyle.DashLine))
            self._preview.setBrush(QColor(20, 115, 230, 30))
        self._preview.setZValue(20)
        self.scene().addItem(self._preview)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return super().mouseMoveEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        start = self._drag[1]
        if isinstance(self._preview, QGraphicsLineItem):
            self._preview.setLine(start.x(), start.y(), sp.x(), sp.y())
        elif isinstance(self._preview, QGraphicsPathItem):
            path = self._preview.path()
            path.lineTo(sp)
            self._preview.setPath(path)
            p = sp - self.pages[self._drag[0]][0].pos()
            self._ink.append(pymupdf.Point(p.x() / self.scale(), p.y() / self.scale()))
        elif self._preview is not None:
            self._preview.setRect(QRectF(start, sp).normalized())

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return super().mouseReleaseEvent(e)
        idx, start = self._drag
        sp = self.mapToScene(e.position().toPoint())
        origin = self.pages[idx][0].pos()
        s = self.scale()
        a = pymupdf.Point((start - origin).x() / s, (start - origin).y() / s)
        b = pymupdf.Point((sp - origin).x() / s, (sp - origin).y() / s)
        tool, ink = self.tool, self._ink
        self._cancel_preview()
        self._ink = []
        if tool == "ink":
            if len(ink) > 1:
                self.toolFinished.emit(tool, idx, [ink])
        elif tool in LINE_TOOLS:
            if abs(a - b) > 3:
                self.toolFinished.emit(tool, idx, (a, b))
        else:
            r = pymupdf.Rect(a, b)
            r.normalize()
            self.toolFinished.emit(tool, idx, r)

    def keyPressEvent(self, e):
        if self.placement is not None:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return self.commit_placement()
            if e.key() == Qt.Key.Key_Escape:
                return self.cancel_placement()
            if e.key() == Qt.Key.Key_Delete and self._placement_delete:
                on_delete = self._placement_delete
                self._drop_placement()
                return on_delete()
        if e.key() == Qt.Key.Key_Escape:
            self._cancel_preview()
        super().keyPressEvent(e)
