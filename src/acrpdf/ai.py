import json
import os
import re
import urllib.error
import urllib.request

from .i18n import _

CLAUDE_MODEL = "claude-opus-5-5"
KEYRING_SERVICE = "acrpdf-ai"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"

LANGUAGE_NAMES = {"es": "Spanish", "en": "English", "fr": "French", "pt": "Portuguese", "de": "German",
                  "it": "Italian", "ca": "Catalan", "gl": "Galician", "eu": "Basque", "nl": "Dutch",
                  "pl": "Polish", "ro": "Romanian", "zh": "Chinese", "ja": "Japanese", "ar": "Arabic"}


class AIError(Exception):
    pass


PROVIDERS = {
    "claude": ("Claude (Anthropic)", None, "ANTHROPIC_API_KEY", CLAUDE_MODEL, "schema"),
    "openai": ("ChatGPT (OpenAI)", "https://api.openai.com/v1", "OPENAI_API_KEY", "", "schema"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-flash", "object"),
    "ollama": ("Ollama", DEFAULT_OLLAMA_URL, None, DEFAULT_OLLAMA_MODEL, "schema"),
}
OPENAI_PREFERENCE = (r"luna", r"mini", r"nano", r"^gpt-")


def get_api_key(provider="claude"):
    name = "anthropic" if provider == "claude" else provider
    try:
        import keyring
        key = keyring.get_password(KEYRING_SERVICE, name)
    except Exception:
        key = None
    env = PROVIDERS.get(provider, (None, None, None))[2]
    return key or (os.environ.get(env) if env else None)


def set_api_key(key, provider="claude"):
    import keyring
    name = "anthropic" if provider == "claude" else provider
    if key:
        keyring.set_password(KEYRING_SERVICE, name, key)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, name)
        except Exception:
            pass


class Provider:
    def complete(self, system, prompt, schema=None, max_tokens=16000):
        raise NotImplementedError


class ClaudeProvider(Provider):
    def __init__(self, api_key=None):
        try:
            import anthropic
        except ImportError as exc:
            raise AIError(_("The anthropic package is not installed.")) from exc
        self.anthropic = anthropic
        key = api_key or get_api_key("claude")
        try:
            self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        except Exception as exc:
            raise AIError(_("No Anthropic API key configured (Preferences → AI).")) from exc

    def complete(self, system, prompt, schema=None, max_tokens=16000):
        a = self.anthropic
        output_config = {"effort": "medium"}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        try:
            with self.client.beta.messages.stream(
                model=CLAUDE_MODEL, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}], output_config=output_config,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
        except a.AuthenticationError as exc:
            raise AIError(_("The Anthropic API key is not valid.")) from exc
        except a.RateLimitError as exc:
            raise AIError(_("Rate limit reached; try again in a minute.")) from exc
        except a.APIStatusError as exc:
            raise AIError(f"Anthropic API {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise AIError(_("Could not connect to the Anthropic API.")) from exc
        if response.stop_reason == "refusal":
            raise AIError(_("The model declined this request."))
        if response.stop_reason == "max_tokens":
            raise AIError(_("The answer was too long; try a shorter document or range."))
        return "".join(b.text for b in response.content if b.type == "text")


class OpenAICompatibleProvider(Provider):

    def __init__(self, provider, model="", api_key=None):
        self.provider = provider
        label, self.base_url, _env, default_model, self.json_mode = PROVIDERS[provider]
        self.label = label
        self.api_key = api_key or get_api_key(provider)
        if not self.api_key:
            raise AIError(_("No API key configured for %s (Preferences → AI).") % label)
        self.model = model or default_model or self._pick_model()

    def _request(self, path, body=None):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {self.api_key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 401:
                raise AIError(_("The %s API key is not valid.") % self.label) from exc
            if exc.code == 429:
                raise AIError(_("Rate limit reached; try again in a minute.")) from exc
            raise AIError(f"{self.label} {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AIError(_("Could not connect to %s.") % self.label) from exc

    def models(self):
        return sorted(m["id"] for m in self._request("/models").get("data", []))

    def _pick_model(self):
        available = [m for m in self.models() if m.startswith("gpt-")]
        for pattern in OPENAI_PREFERENCE:
            matches = [m for m in available if re.search(pattern, m)]
            if matches:
                return sorted(matches)[-1]
        raise AIError(_("No suitable model found; choose one in Preferences → AI."))

    def complete(self, system, prompt, schema=None, max_tokens=16000):
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if schema is not None:
            if self.json_mode == "schema":
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "result", "schema": schema, "strict": True}}
            else:
                body["response_format"] = {"type": "json_object"}
                body["messages"][0]["content"] += ("\nAnswer only with a JSON object that matches this schema: "
                                                   + json.dumps(schema))
        data = self._request("/chat/completions", body)
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise AIError(_("The answer was too long; try a shorter document or range."))
        if choice.get("finish_reason") == "content_filter":
            raise AIError(_("The model declined this request."))
        return choice["message"].get("content") or ""


class OllamaProvider(Provider):
    def __init__(self, url=DEFAULT_OLLAMA_URL, model=DEFAULT_OLLAMA_MODEL):
        self.url = url.rstrip("/")
        self.model = model

    def complete(self, system, prompt, schema=None, max_tokens=16000):
        body = {"model": self.model, "stream": False, "system": system, "prompt": prompt,
                "options": {"num_predict": max_tokens}}
        if schema is not None:
            body["format"] = schema
        req = urllib.request.Request(self.url + "/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                return json.loads(resp.read())["response"]
        except urllib.error.URLError as exc:
            raise AIError(_("Could not reach Ollama at %s. Is it running?") % self.url) from exc


def provider_from_settings(settings):
    kind = settings.value("ai/provider", "claude")
    if kind == "ollama":
        return OllamaProvider(settings.value("ai/ollama_url", DEFAULT_OLLAMA_URL),
                              settings.value("ai/ollama_model", DEFAULT_OLLAMA_MODEL))
    if kind in ("openai", "deepseek"):
        return OpenAICompatibleProvider(kind, settings.value(f"ai/{kind}_model", ""))
    return ClaudeProvider()


def summarize(provider, text, language="es", style="bullets"):
    if not text.strip():
        raise AIError(_("The document has no text (run OCR first if it is scanned)."))
    lang = LANGUAGE_NAMES.get(language, language)
    shape = {"bullets": "a short overview paragraph followed by the key points as a bullet list",
             "short": "one concise paragraph",
             "detailed": "a structured summary with headings for each main section"}[style]
    system = ("You summarize documents accurately. Never invent facts that are not in the document. "
              f"Write in {lang}, in Markdown, as {shape}.")
    return provider.complete(system, f"<document>\n{text}\n</document>\n\nSummarize this document.")


_TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {"translations": {"type": "array", "items": {"type": "string"}}},
    "required": ["translations"],
    "additionalProperties": False,
}


def translate_texts(provider, texts, target="es", batch=40, progress=None):
    lang = LANGUAGE_NAMES.get(target, target)
    system = (f"You are a professional translator. Translate each input string into {lang}. "
              "Keep numbers, names, codes, e-mail addresses and URLs unchanged. Keep line breaks. "
              "Return exactly one translation per input string, in the same order.")
    out = []
    for start in range(0, len(texts), batch):
        chunk = texts[start:start + batch]
        prompt = json.dumps({"strings": chunk}, ensure_ascii=False)
        raw = provider.complete(system, prompt, schema=_TRANSLATION_SCHEMA)
        try:
            translated = json.loads(raw)["translations"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AIError(_("The model returned an invalid answer.")) from exc
        if len(translated) != len(chunk):
            raise AIError(_("The model returned an invalid answer."))
        out.extend(translated)
        if progress:
            progress(min(start + batch, len(texts)), len(texts))
    return out
