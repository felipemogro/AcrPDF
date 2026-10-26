import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__
from .i18n import _

REPOSITORY = "felipemogro/AcrPDF"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
INSTALL_PREFIX = "/opt/acrpdf/"
CHECK_INTERVAL = 24 * 3600


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    notes: str
    page: str
    deb_url: str
    checksum_url: str


def parse_version(text):
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def is_newer(candidate, current=__version__):
    return parse_version(candidate) > parse_version(current)


def installed_from_package():
    return sys.prefix.startswith(INSTALL_PREFIX)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"acrpdf/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(_("No published versions were found.")) from exc
        raise UpdateError(f"GitHub {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(_("Could not connect to GitHub.")) from exc


def latest_release(arch="amd64"):
    data = json.loads(_get(API_URL))
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    deb = next((n for n in assets if n.endswith(f"_{arch}.deb")), None)
    if deb is None:
        raise UpdateError(_("The latest version has no package for this computer."))
    return Release(version=data.get("tag_name", "").lstrip("v"), notes=data.get("body") or "",
                   page=data.get("html_url", RELEASES_URL), deb_url=assets[deb],
                   checksum_url=assets.get(deb + ".sha256", ""))


def check(force=False, settings=None):
    if settings is not None and not force:
        if settings.value("updates/auto", "true") != "true":
            return None
        if time.time() - float(settings.value("updates/last_check", 0)) < CHECK_INTERVAL:
            return None
    release = latest_release()
    if settings is not None:
        settings.setValue("updates/last_check", time.time())
    return release if is_newer(release.version) else None


def download(release, progress=None):
    folder = tempfile.mkdtemp(prefix="acrpdf-update-")
    path = os.path.join(folder, release.deb_url.rsplit("/", 1)[-1])
    req = urllib.request.Request(release.deb_url, headers={"User-Agent": f"acrpdf/{__version__}"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(path, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except urllib.error.URLError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(_("The download failed.")) from exc
    if release.checksum_url:
        expected = _get(release.checksum_url).decode().split()[0].lower()
        if digest.hexdigest() != expected:
            shutil.rmtree(folder, ignore_errors=True)
            raise UpdateError(_("The downloaded package is damaged (checksum mismatch)."))
    return path


def install(deb_path):
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        raise UpdateError(_("Install it with:\nsudo apt install %s") % deb_path)
    result = subprocess.run([pkexec, "apt-get", "install", "-y", "--reinstall", deb_path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        if result.returncode in (126, 127):
            raise UpdateError(_("The installation was cancelled."))
        raise UpdateError((result.stderr or result.stdout)[-800:])
