import os
import shutil
import urllib.request
import uuid

import pymupdf
import pytest

from acrpdf import ops, tools

pytestmark = pytest.mark.filterwarnings("ignore")


def test_detect_fields():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Name: ________________________________")
    page.insert_text((72, 140), "Surname:")
    page.draw_line((150, 142), (400, 142))
    page.draw_rect(pymupdf.Rect(72, 170, 84, 182))
    found = ops.detect_fields(doc)
    assert sorted(kind for _p, kind, _r in found) == ["check", "text", "text"]
    ops.add_detected_fields(doc, found)
    assert len(list(doc[0].widgets())) == 3
    assert ops.detect_fields(doc) == []


def test_markdown_and_translation(tmp_path):
    src = tmp_path / "in.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_htmlbox(pymupdf.Rect(50, 50, 500, 400), "<h1>Title</h1><p>Hello world</p>")
    doc.save(src)
    md = tmp_path / "out.md"
    ops.pdf_to_markdown(str(src), str(md))
    assert "Title" in md.read_text()
    out = tmp_path / "tr.pdf"
    ops.translate_pdf(str(src), str(out), lambda texts: [t.upper() for t in texts])
    text = pymupdf.open(out)[0].get_text()
    assert "HELLO WORLD" in text and "Hello world" not in text


def test_excel_to_pdf_fits_width(tmp_path):
    if not shutil.which("soffice"):
        pytest.skip("LibreOffice not installed")
    from openpyxl import Workbook
    wb = Workbook()
    for r in range(20):
        wb.active.append([f"c{c}r{r}" for c in range(14)])
    xlsx = tmp_path / "t.xlsx"
    wb.save(xlsx)
    out = tmp_path / "t.pdf"
    ops.excel_to_pdf(str(xlsx), str(out), landscape=True)
    doc = pymupdf.open(out)
    assert doc.page_count == 1 and doc[0].rect.width > doc[0].rect.height


def test_workflow_chain(sample_pdf, tmp_path):
    steps = [("rotate", {"angle": 90, "spec": ""}), ("numbers", {}), ("compress", {"level": "recommended"})]
    outputs, _msg = tools.run_workflow(steps, [sample_pdf], str(tmp_path), "office")
    doc = pymupdf.open(outputs[0])
    assert outputs[0].endswith("_office.pdf")
    assert doc[0].rect.width > doc[0].rect.height
    assert "1 / 3" in doc[0].get_text()


def test_workflow_serialization():
    data = [{"name": "wf", "steps": [["watermark", {"image": b"\x89PNG", "text": "x"}]]}]
    assert tools._decode(tools._encode(data)) == data


def test_phone_upload_server(tmp_path):
    from acrpdf.scan import PhoneUploadServer
    server = PhoneUploadServer(str(tmp_path))
    server.start()
    try:
        url = server.url("127.0.0.1")
        assert b"<html" in urllib.request.urlopen(url).read()
        boundary = uuid.uuid4().hex
        png = pymupdf.open().new_page().get_pixmap().tobytes("png")
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"p.png\"\r\n"
                f"Content-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        assert urllib.request.urlopen(req).status == 200
        assert len(server.received) == 1 and os.path.exists(server.received[0])
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url + "x")
    finally:
        server.stop()


def test_network_addresses_prefer_physical_cards():
    from acrpdf.scan import network_addresses
    addresses = network_addresses()
    assert addresses and all(a["ip"] != "127.0.0.1" or len(addresses) == 1 for a in addresses)
    physical = [a for a in addresses if a["physical"]]
    if physical:
        assert addresses[0]["physical"]
