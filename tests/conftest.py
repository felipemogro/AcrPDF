import datetime

import pymupdf
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100">'
       b'<path d="M10 70 C40 10 70 90 100 40 S160 20 180 60" fill="none" stroke="#123456" stroke-width="4"/></svg>')


@pytest.fixture
def sample_pdf(tmp_path):
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1} sample text for tests", fontsize=14)
        page.insert_text((72, 140), "Titular: Juan Ejemplo, DNI 12345678Z", fontsize=11)
    path = tmp_path / "sample.pdf"
    doc.save(path)
    return str(path)


@pytest.fixture(scope="session")
def p12(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EJEMPLO PRUEBA JUAN - 12345678Z")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(datetime.datetime(2025, 1, 1))
            .not_valid_after(datetime.datetime(2035, 1, 1)).sign(key, hashes.SHA256()))
    path = tmp_path_factory.mktemp("cert") / "test.p12"
    path.write_bytes(pkcs12.serialize_key_and_certificates(
        b"test", key, cert, None, serialization.BestAvailableEncryption(b"secret")))
    return str(path), "secret"


@pytest.fixture
def svg():
    return SVG
