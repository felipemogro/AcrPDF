import pymupdf
import pytest
from PyQt6.QtGui import QTextCursor, QTextListFormat
from PyQt6.QtWidgets import QApplication, QMainWindow

from acrpdf.writer import WriterWindow


class FakeMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tabs = []

    def _new_tab(self, doc, title):
        self.tabs.append((doc, title))


@pytest.fixture
def writer():
    app = QApplication.instance() or QApplication([])
    main = FakeMain()
    w = WriterWindow(main)
    yield w, main
    w.edit.document().setModified(False)
    w.close()
    app.processEvents()


def test_create_pdf_with_formatting_and_page_break(writer):
    w, main = writer
    w.edit.insertPlainText("Informe anual")
    w._apply_style(1)
    w.edit.moveCursor(QTextCursor.MoveOperation.End)
    w.edit.textCursor().insertBlock()
    w._apply_style(0)
    w.edit.insertPlainText("Primer punto")
    w._list(QTextListFormat.Style.ListDisc)
    w.insert_page_break()
    w.edit.insertPlainText("Segunda página")
    w.create_pdf()
    doc, title = main.tabs[0]
    assert title.endswith(".pdf")
    assert doc.page_count == 2
    assert "Informe anual" in doc[0].get_text() and "Segunda página" in doc[1].get_text()


def test_save_and_reload_html(writer, tmp_path):
    w, _main = writer
    w.edit.insertPlainText("Hola")
    cursor = w.edit.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    w.edit.setTextCursor(cursor)
    w._bold(True)
    path = str(tmp_path / "doc.html")
    assert w._write(path)
    w.load(path)
    assert w.edit.toPlainText() == "Hola"
    assert w.path == path and not w.edit.document().isModified()


def test_save_odt(writer, tmp_path):
    w, _main = writer
    w.edit.insertPlainText("Texto")
    path = tmp_path / "doc.odt"
    assert w._write(str(path))
    assert path.read_bytes()[:2] == b"PK"


def test_export_pdf_file(writer, tmp_path):
    w, _main = writer
    w.edit.insertPlainText("Exportado")
    out = str(tmp_path / "out.pdf")
    w._print_pdf(out)
    assert "Exportado" in pymupdf.open(out)[0].get_text()
