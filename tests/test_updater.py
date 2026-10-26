import hashlib
import http.server
import json
import threading

import pytest

from acrpdf import updater


@pytest.fixture
def github(monkeypatch, tmp_path):
    package = b"fake deb contents"
    state = {"checksum": hashlib.sha256(package).hexdigest()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path == "/latest":
                body = json.dumps({"tag_name": "v9.9.9", "body": "notes", "html_url": base,
                                   "assets": [{"name": "acrpdf_9.9.9_amd64.deb", "browser_download_url": base + "/deb"},
                                              {"name": "acrpdf_9.9.9_amd64.deb.sha256",
                                               "browser_download_url": base + "/sha"}]}).encode()
            elif self.path == "/deb":
                body = package
            else:
                body = f"{state['checksum']}  acrpdf_9.9.9_amd64.deb\n".encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(updater, "API_URL", f"http://127.0.0.1:{server.server_address[1]}/latest")
    yield state
    server.shutdown()


def test_version_comparison():
    assert updater.is_newer("2.10.0", "2.9.9")
    assert not updater.is_newer("v2.1.0", "2.1.0")


def test_check_and_verified_download(github):
    release = updater.check(force=True)
    assert release.version == "9.9.9"
    path = updater.download(release)
    assert open(path, "rb").read() == b"fake deb contents"


def test_damaged_download_is_rejected(github):
    github["checksum"] = "0" * 64
    with pytest.raises(updater.UpdateError):
        updater.download(updater.latest_release())
