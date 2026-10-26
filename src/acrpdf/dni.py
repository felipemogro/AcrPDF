import re

_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_GROUP_SEP = r"[ .]?"
_LETTER_SEP = r" ?[-‐–—]? ?"
DNI_RE = re.compile(r"(?<![\w.\-])(0?\d{2}" + _GROUP_SEP + r"\d{3}" + _GROUP_SEP + r"\d{3})"
                    + _LETTER_SEP + r"([A-Za-z])(?![\w])")
NIE_RE = re.compile(r"(?<![\w.\-])([XYZxyz])" + _LETTER_SEP + r"(\d" + _GROUP_SEP + r"\d{3}" + _GROUP_SEP
                    + r"\d{3})" + _LETTER_SEP + r"([A-Za-z])(?![\w])")
MRZ_RE = re.compile(r"(?<=[0-9A-Z])(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])(?=<)")
_TOKEN_RE = re.compile(r"(?=(\d{8}[A-Z]|[XYZ]\d{7}[A-Z]))")


def normalize(value):
    v = re.sub(r"[^0-9A-Za-z]", "", value).upper()
    if re.fullmatch(r"0\d{8}[A-Z]", v):
        v = v[1:]
    return v


def _check_letter(number):
    return _LETTERS[int(number) % 23]


def is_valid(value):
    v = normalize(value)
    if re.fullmatch(r"\d{8}[A-Z]", v):
        return _check_letter(v[:8]) == v[8]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):
        return _check_letter(str("XYZ".index(v[0])) + v[1:8]) == v[8]
    return False


def mask(value):
    v = normalize(value)
    if re.fullmatch(r"\d{8}[A-Z]", v):
        return "***" + v[3:7] + "**"
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):
        return "****" + v[4:8] + "*"
    return "*" * len(v)


def visible_positions(value):
    return range(3, 7) if normalize(value)[0].isdigit() else range(4, 8)


def find(text, validate=True):
    seen = set()
    for rx in (DNI_RE, NIE_RE, MRZ_RE):
        for m in rx.finditer(text):
            s = m.group(1) if rx is MRZ_RE else m.group(0)
            if s in seen or (validate and not is_valid(s)):
                continue
            seen.add(s)
            yield s


def find_in_token(token):
    t = token.upper()
    spans = []
    for m in _TOKEN_RE.finditer(t):
        value = m.group(1)
        if is_valid(value):
            spans.append((m.start(), m.start() + len(value)))
    return spans


def mask_in_text(text, validate=True):
    for s in list(find(text, validate)):
        text = text.replace(s, mask(s))
    return text
