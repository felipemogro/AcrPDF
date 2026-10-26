import pytest

from acrpdf import dni


def test_valid_numbers():
    assert dni.is_valid("12345678Z")
    assert dni.is_valid("12.345.678-Z")
    assert dni.is_valid("12.345.678 - Z")
    assert dni.is_valid("012345678Z")
    assert dni.is_valid("X1234567L")
    assert not dni.is_valid("12345678A")


def test_mask_follows_aepd():
    assert dni.mask("12345678Z") == "***4567**"
    assert dni.mask("012345678Z") == "***4567**"
    assert dni.mask("X1234567L") == "****4567*"


@pytest.mark.parametrize("text,expected", [
    ("DNI 12345678Z, NIE X1234567L, falso 11111111A", {"12345678Z", "X1234567L"}),
    ("D.N.I. 12.345.678 - Z", {"12.345.678 - Z"}),
    ("NIF titular: 012345678Z", {"012345678Z"}),
    ("NIE: X-1234567-L", {"X-1234567-L"}),
    ("IDESPCNJ152433612345678Z<<<<<<", {"12345678Z"}),
    ("IBAN ES12 1234 5678 9012", set()),
])
def test_find_formats(text, expected):
    assert set(dni.find(text)) == expected


def test_find_in_ocr_token():
    token = "IDESPCNJ152433612345678Z<<<"
    assert [token[a:b] for a, b in dni.find_in_token(token)] == ["12345678Z"]


def test_mask_in_text():
    assert dni.mask_in_text("PEREZ JUAN - 12345678Z") == "PEREZ JUAN - ***4567**"
