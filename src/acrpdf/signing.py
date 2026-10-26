import datetime
import glob
import io
import logging
import os
import tempfile
import warnings
from dataclasses import dataclass, field

import pymupdf
from pyhanko import stamp
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers, timestamps
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from . import dni, ops
from .i18n import _

logging.getLogger("pyhanko").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", message="PKCS#12 bundle could not be parsed as DER")

CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")


class SignError(Exception):
    pass


@dataclass
class Appearance:
    graphic: bytes = None
    layout: str = "side"
    show_details: bool = True
    family: str = "DejaVu Sans"
    color: tuple = (0, 0, 0)
    hide_id: bool = True
    extra_lines: list = field(default_factory=list)


CA_CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "acrpdf", "ca")


def _load_any_cert(data):
    from asn1crypto import cms, pem, x509
    if pem.detect(data):
        return [x509.Certificate.load(der) for _t, _h, der in pem.unarmor(data, multiple=True)]
    try:
        return [x509.Certificate.load(data)]
    except ValueError:
        info = cms.ContentInfo.load(data)
        return [c.chosen for c in info["content"]["certificates"]]


def _issuer_from_aia(cert):
    import urllib.request
    aia = cert.authority_information_access_value
    for entry in aia.native if aia else []:
        if entry["access_method"] != "ca_issuers" or not entry["access_location"].startswith("http"):
            continue
        url = entry["access_location"]
        cached = os.path.join(CA_CACHE, url.rsplit("/", 1)[-1] or "issuer.crt")
        try:
            if os.path.exists(cached):
                with open(cached, "rb") as f:
                    data = f.read()
            else:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = resp.read(1 << 20)
                os.makedirs(CA_CACHE, exist_ok=True)
                with open(cached, "wb") as f:
                    f.write(data)
            for candidate in _load_any_cert(data):
                if candidate.subject == cert.issuer:
                    return candidate
        except Exception:
            continue
    return None


def cached_intermediates():
    certs = []
    for path in glob.glob(os.path.join(CA_CACHE, "*")):
        try:
            with open(path, "rb") as f:
                certs.extend(_load_any_cert(f.read()))
        except Exception:
            pass
    return certs


def complete_chain(signer, depth=4):
    cert = signer.signing_cert
    for _level in range(depth):
        if cert.issuer == cert.subject:
            break
        issuer = next((c for c in signer.cert_registry if c.subject == cert.issuer), None)
        if issuer is None:
            issuer = _issuer_from_aia(cert)
            if issuer is None or issuer.issuer == issuer.subject:
                break
            signer.cert_registry.register(issuer)
        cert = issuer


def load_signer(p12_path, password):
    try:
        signer = signers.SimpleSigner.load_pkcs12(p12_path, passphrase=password.encode() if password else None)
    except Exception as exc:
        raise SignError(_("Could not open the certificate: %s") % exc) from exc
    if signer is None:
        raise SignError(_("Wrong password or invalid certificate."))
    return signer


def describe_cert(cert):
    subject = cert.subject.native
    return {
        "name": subject.get("common_name", str(subject)),
        "serial": subject.get("serial_number", ""),
        "email": subject.get("email_address", ""),
        "issuer": cert.issuer.native.get("common_name", ""),
        "valid_to": cert["tbs_certificate"]["validity"]["not_after"].native,
    }


def display_name(name, hide_id=True):
    return dni.mask_in_text(name) if hide_id else name


def detail_lines(name, reason="", location="", when=None, hide_id=True):
    when = when or datetime.datetime.now()
    lines = [_("Digitally signed by:"), display_name(name, hide_id),
             _("Date: %s") % when.strftime("%d/%m/%Y %H:%M:%S")]
    if reason:
        lines.append(_("Reason: %s") % reason)
    if location:
        lines.append(_("Location: %s") % location)
    return lines


def build_appearance(width, height, appearance, lines, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    full = page.rect
    graphic = appearance.graphic if appearance.layout != "text" else None
    lines = lines if appearance.show_details else []
    img_rect = txt_rect = None
    if graphic and (appearance.layout == "image" or not lines):
        img_rect = full
    elif graphic and appearance.layout == "stack":
        img_rect = pymupdf.Rect(0, 0, width, height * 0.58)
        txt_rect = pymupdf.Rect(2, height * 0.58, width - 2, height)
    elif graphic:
        img_rect = pymupdf.Rect(0, 0, width * 0.48, height)
        txt_rect = pymupdf.Rect(width * 0.5, 0, width - 1, height)
    else:
        txt_rect = full + (2, 2, -2, -2)
    if img_rect is not None:
        ops.insert_graphic(page, img_rect, graphic)
    if txt_rect is not None and lines:
        kw = ops.font_args(appearance.family)
        text = "\n".join(lines)
        size = min(14.0, txt_rect.height / (len(lines) * 1.22))
        while size > 3 and page.insert_textbox(txt_rect, text, fontsize=size,
                                               color=appearance.color, **kw) < 0:
            size -= 0.5
    if rotation % 360:
        rotated = pymupdf.open()
        w2, h2 = (height, width) if rotation % 180 else (width, height)
        rp = rotated.new_page(width=w2, height=h2)
        rp.show_pdf_page(rp.rect, doc, 0, rotate=rotation)
        doc.close()
        doc = rotated
    doc.subset_fonts()
    return doc


def appearance_preview(width, height, appearance, lines, zoom=2.0):
    doc = build_appearance(width, height, appearance, lines)
    png = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).tobytes("png")
    doc.close()
    return png


def _pdf_box(data, page_index, box):
    doc = pymupdf.open("pdf", data)
    page = doc[page_index]
    r = pymupdf.Rect(box) * page.derotation_matrix * ~page.transformation_matrix
    r.normalize()
    rotation = page.rotation
    doc.close()
    return (r.x0, r.y0, r.x1, r.y1), rotation


def add_signature_field(data, page_index, box, name):
    pdf_box, _rot = _pdf_box(data, page_index, box)
    writer = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
    fields.append_signature_field(writer, fields.SigFieldSpec(sig_field_name=name, on_page=page_index,
                                                              box=pdf_box))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _existing_signature_fields(data):
    found = {}
    doc = pymupdf.open("pdf", data)
    for page in doc:
        for w in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
            r = w.rect * ~page.transformation_matrix
            r.normalize()
            found[w.field_name] = (page.number, (r.x0, r.y0, r.x1, r.y1), page.rotation)
    doc.close()
    return found


def sign_pdf(data, out_path, p12_path, password, *, field_name=None, page_index=0, box=None,
             appearance=None, reason="", location="", contact="", certify=False,
             lock_document=False, tsa_url=None):
    appearance = appearance or Appearance()
    signer = load_signer(p12_path, password)
    complete_chain(signer)
    info = describe_cert(signer.signing_cert)

    existing = _existing_signature_fields(data)
    sig_box, rotation = (None, 0)
    if field_name in existing:
        page_index, sig_box, rotation = existing[field_name]
    elif box is not None:
        sig_box, rotation = _pdf_box(data, page_index, box)
    if not field_name:
        i = 1
        while f"Signature{i}" in existing:
            i += 1
        field_name = f"Signature{i}"

    writer = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
    if field_name not in existing:
        fields.append_signature_field(writer, fields.SigFieldSpec(
            sig_field_name=field_name, on_page=page_index, box=sig_box or (0, 0, 0, 0)))

    style = None
    ap_path = None
    if sig_box and sig_box[2] - sig_box[0] > 1:
        width, height = sig_box[2] - sig_box[0], sig_box[3] - sig_box[1]
        if rotation % 180:
            width, height = height, width
        lines = detail_lines(info["name"], reason, location, hide_id=appearance.hide_id)
        ap_doc = build_appearance(width, height, appearance, lines + appearance.extra_lines, rotation)
        fd, ap_path = tempfile.mkstemp(suffix=".pdf", prefix="acrpdf-ap-")
        os.close(fd)
        ap_doc.save(ap_path, garbage=3, deflate=True)
        ap_doc.close()
        style = stamp.StaticStampStyle.from_pdf_file(ap_path, border_width=0)

    meta = signers.PdfSignatureMetadata(
        field_name=field_name, reason=reason or None, location=location or None,
        contact_info=contact or None, md_algorithm="sha256",
        subfilter=fields.SigSeedSubFilter.PADES, certify=certify,
        docmdp_permissions=fields.MDPPerm.NO_CHANGES if lock_document else fields.MDPPerm.FILL_FORMS,
        name=display_name(info["name"], appearance.hide_id),
    )
    timestamper = timestamps.HTTPTimeStamper(tsa_url) if tsa_url else None
    pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=style, timestamper=timestamper)
    out = io.BytesIO()
    try:
        pdf_signer.sign_pdf(writer, output=out)
    except Exception as exc:
        raise SignError(_("Signing failed: %s") % exc) from exc
    finally:
        if ap_path:
            os.unlink(ap_path)
    with open(out_path, "wb") as f:
        f.write(out.getvalue())
    return info


def _trust_roots():
    from asn1crypto import pem, x509
    roots = []
    for path in CA_BUNDLES:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            for _type, _headers, der in pem.unarmor(f.read(), multiple=True):
                try:
                    roots.append(x509.Certificate.load(der))
                except ValueError:
                    pass
        break
    return roots


def validate(data):
    results = []
    try:
        sigs = PdfFileReader(io.BytesIO(data), strict=False).embedded_signatures
    except Exception as exc:
        return [{"field": "-", "error": str(exc)}]
    context = ValidationContext(trust_roots=_trust_roots(), other_certs=cached_intermediates(),
                                allow_fetching=False)
    for sig in sigs:
        item = {"field": sig.field_name}
        try:
            status = validate_pdf_signature(sig, context)
            cert = status.signing_cert
            item.update({
                "signer": cert.subject.native.get("common_name", "?"),
                "issuer": cert.issuer.native.get("common_name", "?"),
                "intact": status.intact,
                "valid": status.valid,
                "trusted": status.trusted,
                "time": str(status.signer_reported_dt or ""),
                "coverage": str(status.coverage).rsplit(".", 1)[-1],
                "modification": str(status.modification_level).rsplit(".", 1)[-1]
                if status.modification_level else "",
            })
        except Exception as exc:
            item["error"] = str(exc)
        results.append(item)
    return results
