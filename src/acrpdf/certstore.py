import glob
import hashlib
import os
import secrets
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass

from asn1crypto import pem, x509

from . import signing
from .i18n import _

DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "acrpdf")
CERT_DIR = os.path.join(DATA_DIR, "certificates")
KEYRING_SERVICE = "acrpdf-certificates"

MOZILLA_ROOTS = (
    "~/.mozilla/firefox", "~/snap/firefox/common/.mozilla/firefox",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    "~/.thunderbird", "~/snap/thunderbird/common/.thunderbird",
    "~/.var/app/org.mozilla.Thunderbird/.thunderbird",
)


@dataclass
class Certificate:
    source: str
    label: str
    issuer: str = ""
    valid_to: object = None
    path: str = ""
    nickname: str = ""
    key_id: str = ""

    @property
    def needs_password(self):
        return self.source != "mozilla"


def _keyring():
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        kr = keyring.get_keyring()
        return None if isinstance(kr, FailKeyring) else keyring
    except Exception:
        return None


def keyring_available():
    return _keyring() is not None


def saved_password(cert):
    kr = _keyring()
    if not kr or not cert.key_id:
        return None
    try:
        return kr.get_password(KEYRING_SERVICE, cert.key_id)
    except Exception:
        return None


def remember_password(cert, password):
    kr = _keyring()
    if not kr or not cert.key_id:
        return False
    try:
        kr.set_password(KEYRING_SERVICE, cert.key_id, password)
        return True
    except Exception:
        return False


def forget_password(cert):
    kr = _keyring()
    if kr and cert.key_id:
        try:
            kr.delete_password(KEYRING_SERVICE, cert.key_id)
        except Exception:
            pass


def _file_id(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:24]


def import_p12(path, password):
    info = signing.describe_cert(signing.load_signer(path, password).signing_cert)
    os.makedirs(CERT_DIR, mode=0o700, exist_ok=True)
    os.chmod(CERT_DIR, 0o700)
    target = os.path.join(CERT_DIR, f"{_file_id(path)}.p12")
    shutil.copyfile(path, target)
    os.chmod(target, 0o600)
    with open(target + ".name", "w", encoding="utf-8") as f:
        f.write(f"{info['name']}\n{info['issuer']}\n{info['valid_to'].isoformat()}\n")
    return store_certificate(target)


def store_certificate(p12_path):
    label, issuer, valid_to = os.path.basename(p12_path), "", None
    meta = p12_path + ".name"
    if os.path.exists(meta):
        with open(meta, encoding="utf-8") as f:
            parts = f.read().splitlines() + ["", "", ""]
        label, issuer, valid_to = parts[0], parts[1], parts[2] or None
    return Certificate("store", label, issuer, valid_to, p12_path, key_id=os.path.basename(p12_path))


def remove_from_store(cert):
    forget_password(cert)
    for p in (cert.path, cert.path + ".name"):
        if os.path.exists(p):
            os.unlink(p)


def store_certificates():
    return [store_certificate(p) for p in sorted(glob.glob(os.path.join(CERT_DIR, "*.p12")))]


def mozilla_profiles():
    found = []
    for root in MOZILLA_ROOTS:
        for db in glob.glob(os.path.join(os.path.expanduser(root), "*", "cert9.db")):
            found.append(os.path.dirname(db))
    return found


def _app_name(profile):
    return "Thunderbird" if "thunderbird" in profile.lower() else "Firefox"


def mozilla_certificates():
    certutil = shutil.which("certutil")
    if not certutil:
        return []
    out = []
    for profile in mozilla_profiles():
        try:
            listing = subprocess.run([certutil, "-L", "-d", f"sql:{profile}"], capture_output=True,
                                     text=True, timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in listing.splitlines()[4:]:
            parts = line.rsplit(None, 1)
            if len(parts) != 2 or "u" not in parts[1].split(",")[0]:
                continue
            nickname = parts[0].strip()
            cert = Certificate("mozilla", nickname, path=profile, nickname=nickname)
            try:
                pem_text = subprocess.run([certutil, "-L", "-d", f"sql:{profile}", "-n", nickname, "-a"],
                                          capture_output=True, timeout=15).stdout
                _t, _h, der = pem.unarmor(pem_text)
                info = signing.describe_cert(x509.Certificate.load(der))
                cert.label, cert.issuer, cert.valid_to = info["name"], info["issuer"], info["valid_to"]
            except Exception:
                pass
            cert.label = f"{cert.label}  ({_app_name(profile)})"
            out.append(cert)
    return out


@contextmanager
def exported_p12(cert, nss_password=""):
    if cert.source != "mozilla":
        yield cert.path, None
        return
    pk12util = shutil.which("pk12util")
    if not pk12util:
        raise signing.SignError(_("pk12util was not found (package libnss3-tools)."))
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    tmp = tempfile.mkdtemp(prefix="acrpdf-", dir=runtime)
    os.chmod(tmp, 0o700)
    p12 = os.path.join(tmp, "key.p12")
    pw_file = os.path.join(tmp, "pw")
    db_file = os.path.join(tmp, "db")
    password = secrets.token_urlsafe(24)
    try:
        for path, value in ((pw_file, password), (db_file, nss_password or "")):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(value)
        r = subprocess.run([pk12util, "-o", p12, "-n", cert.nickname, "-d", f"sql:{cert.path}",
                            "-w", pw_file, "-k", db_file], capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not os.path.exists(p12):
            msg = (r.stderr or r.stdout).strip()
            if "password" in msg.lower() or "SEC_ERROR_BAD_PASSWORD" in msg:
                raise signing.SignError(_("Wrong primary password for the Firefox certificate store."))
            raise signing.SignError(_("Could not read the certificate from Firefox: %s") % msg)
        yield p12, password
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def all_certificates():
    return store_certificates() + mozilla_certificates()
