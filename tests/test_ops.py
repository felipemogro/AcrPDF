import os

import pymupdf
import pytest

from acrpdf import ops


def test_text_and_annotations(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    page = doc[0]
    assert ops.markup(page, pymupdf.Rect(60, 80, 400, 110), "highlight", (1, 1, 0)) is not None
    ops.shape_annot(page, "rect", rect=pymupdf.Rect(100, 200, 200, 260))
    ops.insert_text_block(page, pymupdf.Rect(72, 300, 72, 300), "Hola ñandú", "DejaVu Sans", 12)
    assert "Hola ñandú" in page.get_text()
    assert {a.type[1] for a in page.annots()} == {"Highlight", "Square"}


def test_replace_span(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    page = doc[0]
    span = ops.find_span(page, pymupdf.Point(100, 95))
    ops.replace_span(page, span, "Edited")
    assert "Edited" in page.get_text()


def test_svg_graphic_is_vector(svg):
    doc = pymupdf.open()
    page = doc.new_page()
    ops.insert_graphic(page, pymupdf.Rect(50, 50, 350, 150), svg)
    assert page.get_drawings()
    assert ops.graphic_size(svg) == (300, 100)
    assert b"#000000" in ops.recolor_svg(svg, "#000000")


def test_forms(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    page = doc[0]
    ops.add_field(page, "text", pymupdf.Rect(72, 400, 250, 420), "name")
    ops.add_field(page, "check", pymupdf.Rect(300, 400, 316, 416), "agree")
    fields = {name: (p, xref) for p, name, _t, _v, xref in ops.all_fields(doc)}
    ops.set_field(doc, *fields["name"], "Juan")
    ops.set_field(doc, *fields["agree"], True)
    ops.set_widget_rect(page, fields["name"][1], pymupdf.Rect(72, 400, 400, 430))
    w = ops.find_widget(page, fields["name"][1])
    assert w.field_value == "Juan" and w.rect.width == pytest.approx(328)


def test_set_field_without_page_reference(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    ops.add_field(doc[0], "text", pymupdf.Rect(72, 400, 250, 420), "city")
    xref = ops.all_fields(doc)[0][4]
    assert ops.set_field(doc, 0, xref, "Madrid")
    assert ops.all_fields(doc)[0][3] == "Madrid"


def test_hide_ids(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    assert len(ops.find_ids(doc)) == 3
    assert ops.hide_ids(doc, "mask") == 3
    text = doc[0].get_text()
    assert "12345678Z" not in text and "***4567**" in text


def test_page_operations(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    ops.reorder(doc, [2, 0, 1])
    assert doc[0].get_text().startswith("Page 3")
    ops.duplicate_pages(doc, [0])
    assert doc.page_count == 4
    assert ops.parse_ranges("1-2, 4", 4) == [[0, 1], [3]]
    with pytest.raises(ops.OperationError):
        ops.parse_ranges("7", 4)


def test_file_tools(sample_pdf, tmp_path, svg):
    out = tmp_path / "out"
    out.mkdir()
    assert len(ops.split(sample_pdf, str(out), every=1)) == 3
    merged = str(tmp_path / "merged.pdf")
    ops.merge([sample_pdf, sample_pdf], merged)
    assert pymupdf.open(merged).page_count == 6
    compressed = str(tmp_path / "small.pdf")
    ops.compress(sample_pdf, compressed, "extreme")
    assert os.path.getsize(compressed) <= os.path.getsize(sample_pdf)
    svg_path = tmp_path / "s.svg"
    svg_path.write_bytes(svg)
    images = str(tmp_path / "images.pdf")
    ops.images_to_pdf([str(svg_path)], images)
    assert pymupdf.open(images).page_count == 1
    assert len(ops.pdf_to_images(sample_pdf, str(out), "png", 50)) == 3
    ops.pdf_to_excel(sample_pdf, str(tmp_path / "t.xlsx"))
    ops.pdf_to_powerpoint(sample_pdf, str(tmp_path / "t.pptx"), dpi=40)
    ops.numbers_file(sample_pdf, str(tmp_path / "n.pdf"))
    assert "1 / 3" in pymupdf.open(str(tmp_path / "n.pdf"))[0].get_text()


def test_protect_and_unlock(sample_pdf, tmp_path):
    locked, unlocked = str(tmp_path / "l.pdf"), str(tmp_path / "u.pdf")
    ops.protect(sample_pdf, locked, "pw")
    assert pymupdf.open(locked).needs_pass
    with pytest.raises(ops.OperationError):
        ops.unlock(locked, unlocked, "bad")
    ops.unlock(locked, unlocked, "pw")
    assert not pymupdf.open(unlocked).needs_pass


def test_compare(sample_pdf, tmp_path):
    changed = str(tmp_path / "b.pdf")
    doc = pymupdf.open(sample_pdf)
    doc[1].insert_text((72, 200), "new paragraph")
    doc.save(changed)
    _files, n = ops.compare(sample_pdf, changed, str(tmp_path / "diff.pdf"))
    assert n >= 2


@pytest.mark.skipif(not os.path.exists("/usr/bin/gs"), reason="Ghostscript not installed")
def test_pdfa(sample_pdf, tmp_path):
    out = str(tmp_path / "a.pdf")
    ops.pdf_to_pdfa(sample_pdf, out)
    doc = pymupdf.open(out)
    assert "OutputIntents" in doc.xref_object(doc.pdf_catalog())


@pytest.mark.parametrize("mode,ext", [("L", "png"), ("LA", "png"), ("1", "png"), ("P", "png"),
                                      ("RGB", "jpg"), ("RGBA", "png"), ("CMYK", "jpg")])
def test_recolor_any_image_mode(tmp_path, mode, ext):
    from PIL import Image
    path = tmp_path / f"sig.{ext}"
    Image.new(mode, (40, 20)).save(path)
    out = pymupdf.Pixmap(ops.recolor_png(path.read_bytes(), (0, 0, 0)))
    assert out.alpha and out.n == 4


def _photo(width, height, mode="RGB"):
    import io
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 255, (height, width, 4 if mode == "RGBA" else 3), dtype="uint8")
    buf = io.BytesIO()
    Image.fromarray(pixels, mode).save(buf, "PNG")
    return buf.getvalue()


def test_inserted_images_are_downscaled_and_keep_transparency():
    big = _photo(3000, 1000, "RGBA")
    doc = pymupdf.open()
    page = doc.new_page()
    ops.insert_graphic(page, pymupdf.Rect(50, 50, 266, 122), big)
    xref, smask = page.get_images(full=True)[0][:2]
    assert doc.extract_image(xref)["width"] <= 900
    assert smask > 0


def test_save_compression_levels(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=_photo(2480, 3508))
    data = doc.tobytes()
    sizes = {level: len(ops.compact_bytes(data, level)) for level in ("lossless", "high", "recommended", "small")}
    assert sizes["small"] < sizes["recommended"] < sizes["high"] <= sizes["lossless"] <= len(data)


@pytest.mark.skipif(not ops.ocr_languages(), reason="Tesseract not installed")
def test_hide_ids_in_scanned_image():
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1000, 160), "white")
    font = ImageFont.truetype(ops.font_file("DejaVu Sans"), 52)
    ImageDraw.Draw(img).text((30, 40), "DNI 12345678Z", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 410, 108), stream=buf.getvalue())
    hits = ops.scan_ids(doc)
    assert [h.value for h in hits] == ["12345678Z"] and hits[0].source == "ocr"
    ops.apply_id_hits(doc, hits, "mask")
    assert ops.scan_ids(doc) == []


def test_placed_graphics_can_be_moved_and_survive_saving(tmp_path, svg):
    doc = pymupdf.open()
    page = doc.new_page()
    png = _photo(300, 100, "RGBA")
    first = ops.insert_graphic(page, pymupdf.Rect(50, 50, 250, 117), png)
    second = ops.insert_graphic(page, pymupdf.Rect(50, 200, 250, 267), png)
    vector = ops.insert_graphic(page, pymupdf.Rect(50, 400, 350, 500), svg)
    assert len({first, second, vector}) == 3
    assert ops.graphic_at(page, (100, 230))[0] == second
    ops.move_graphic(page, second, pymupdf.Rect(300, 600, 500, 667))
    path = tmp_path / "g.pdf"
    doc.save(path)
    rects = [r for _x, r in ops.placed_graphics(pymupdf.open(path)[0])]
    assert pymupdf.Rect(300, 600, 500, 667) in rects and pymupdf.Rect(50, 200, 250, 267) not in rects
    assert len(rects) == 3


def test_protect_identity_watermark_and_flatten(sample_pdf):
    data = open(sample_pdf, "rb").read()
    hits = ops.scan_ids(pymupdf.open("pdf", data), ocr=False)
    wm = ops.IdWatermark(purpose="ALQUILER")
    visible = pymupdf.open("pdf", ops.protect_identity(data, hits, "mask", wm, flatten=False))
    text = visible[0].get_text()
    assert "***4567**" in text and "DNI para ALQUILER" in text
    assert "12345678Z" not in "".join(p.get_text() for p in visible)
    flat = pymupdf.open("pdf", ops.protect_identity(data, hits, "mask", wm, flatten=True))
    assert flat.page_count == 3 and flat[0].get_text().strip() == ""
    preview = pymupdf.open("pdf", ops.protect_identity(data, hits, "mask", wm, flatten=False, pages=[1]))
    assert preview.page_count == 1


def test_watermark_template_with_unknown_placeholder():
    assert ops.IdWatermark(purpose="X").render("Copia {nombre}") == "Copia {nombre}"


@pytest.mark.skipif(not ops.ocr_languages(), reason="Tesseract not installed")
def test_ocr_text_is_editable(tmp_path):
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1700, 600), (245, 243, 238))
    ImageDraw.Draw(img).text((150, 200), "El arrendatario pagará 850 euros.", fill=(20, 20, 20),
                              font=ImageFont.truetype(ops.font_file("DejaVu Serif"), 46))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=216)
    page.insert_image(page.rect, stream=buf.getvalue())
    src, out = tmp_path / "scan.pdf", tmp_path / "ocr.pdf"
    doc.save(src)
    ops.ocr(str(src), str(out), "spa")
    page = pymupdf.open(out)[0]
    span = next(s for b in page.get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]
                if "850" in s["text"])
    assert ops.is_ocr_span(span)
    ops.replace_span(page, span, "El arrendatario pagará 900 euros.")
    assert "900 euros" in page.get_text()
