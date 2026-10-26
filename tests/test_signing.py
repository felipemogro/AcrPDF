import pymupdf

from acrpdf import ops, signing


def _signed(tmp_path, data, p12, **kwargs):
    out = tmp_path / "signed.pdf"
    signing.sign_pdf(data, str(out), *p12, **kwargs)
    return out.read_bytes()


def test_visible_signature_with_svg_hides_dni(tmp_path, sample_pdf, p12, svg):
    data = open(sample_pdf, "rb").read()
    signed = _signed(tmp_path, data, p12, box=pymupdf.Rect(300, 650, 560, 730),
                     appearance=signing.Appearance(graphic=svg), reason="Test")
    result = signing.validate(signed)[0]
    assert result["intact"] and result["valid"]
    doc = pymupdf.open("pdf", signed)
    text = doc[0].get_text(clip=pymupdf.Rect(300, 650, 560, 730))
    assert "***4567**" in text and "12345678Z" not in text


def test_sign_existing_field_and_fill_afterwards(tmp_path, sample_pdf, p12):
    data = signing.add_signature_field(open(sample_pdf, "rb").read(), 0, pymupdf.Rect(72, 600, 272, 660), "Client")
    signed = _signed(tmp_path, data, p12, field_name="Client")
    assert [r["field"] for r in signing.validate(signed)] == ["Client"]
    doc = pymupdf.open("pdf", signed)
    assert ops.has_signatures(doc)


def test_rotated_page(tmp_path, p12):
    doc = pymupdf.open()
    page = doc.new_page()
    page.set_rotation(90)
    signed = _signed(tmp_path, doc.tobytes(), p12, box=pymupdf.Rect(50, 50, 300, 130),
                     appearance=signing.Appearance(hide_id=False))
    assert signing.validate(signed)[0]["intact"]


def test_wrong_password(tmp_path, sample_pdf, p12):
    try:
        signing.sign_pdf(open(sample_pdf, "rb").read(), str(tmp_path / "x.pdf"), p12[0], "bad")
    except signing.SignError:
        return
    raise AssertionError("SignError expected")


def test_signature_does_not_embed_whole_fonts(tmp_path, sample_pdf, p12, svg):
    data = open(sample_pdf, "rb").read()
    signed = _signed(tmp_path, data, p12, box=pymupdf.Rect(300, 650, 560, 730),
                     appearance=signing.Appearance(graphic=svg))
    assert len(signed) - len(data) < 120_000


def test_compact_bytes_shrinks_edited_documents(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    ops.insert_text_block(doc[0], pymupdf.Rect(72, 300, 72, 300), "Texto añadido", "DejaVu Sans", 12)
    data = doc.tobytes()
    compact = ops.compact_bytes(data)
    assert len(compact) < len(data) / 3
    assert "Texto añadido" in pymupdf.open("pdf", compact)[0].get_text()
