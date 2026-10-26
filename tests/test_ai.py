import http.server
import json
import threading

import pytest

from acrpdf import ai


@pytest.fixture
def fake_api(monkeypatch):
    class Handler(http.server.BaseHTTPRequestHandler):
        requests = []

        def log_message(self, *_args):
            pass

        def _reply(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._reply({"data": [{"id": "gpt-5.6-terra"}, {"id": "gpt-5.6-luna"}, {"id": "whisper-1"}]})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            Handler.requests.append(req)
            strings = json.loads(req["messages"][1]["content"])["strings"]
            content = json.dumps({"translations": [s.upper() for s in strings]})
            self._reply({"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setitem(ai.PROVIDERS, "openai", ("ChatGPT (OpenAI)", url, "X", "", "schema"))
    monkeypatch.setitem(ai.PROVIDERS, "deepseek", ("DeepSeek", url, "X", "deepseek-flash", "object"))
    yield Handler.requests
    server.shutdown()


def test_openai_picks_cheapest_model_and_uses_json_schema(fake_api):
    provider = ai.OpenAICompatibleProvider("openai", api_key="test")
    assert provider.model == "gpt-5.6-luna"
    assert ai.translate_texts(provider, ["hola", "adiós"]) == ["HOLA", "ADIÓS"]
    assert fake_api[-1]["response_format"]["type"] == "json_schema"


def test_deepseek_uses_json_mode(fake_api):
    provider = ai.OpenAICompatibleProvider("deepseek", api_key="test")
    assert ai.translate_texts(provider, ["uno"]) == ["UNO"]
    assert fake_api[-1]["model"] == "deepseek-flash"
    assert fake_api[-1]["response_format"] == {"type": "json_object"}


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.setattr(ai, "get_api_key", lambda provider="claude": None)
    with pytest.raises(ai.AIError):
        ai.OpenAICompatibleProvider("deepseek")
