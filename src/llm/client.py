"""Shared JSON-mode LLM client for deterministic, cached, quoted model calls."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    import jsonschema
except ImportError:
    jsonschema = None


DEFAULT_URL = "http://127.0.0.1:11434/v1/chat/completions"


class LLMCallError(RuntimeError):
    pass


def _environment():
    url = os.getenv("SOONY_LLM_URL") or os.getenv("SOONY_LOCAL_URL") or DEFAULT_URL
    model = os.getenv("SOONY_LLM_MODEL") or os.getenv("SOONY_LOCAL_MODEL")
    api_key = os.getenv("SOONY_LLM_API_KEY") or os.getenv("SOONY_LOCAL_API_KEY")
    provider = os.getenv("SOONY_LLM_PROVIDER", "ollama").strip().lower()
    return url, model, api_key, provider


def _normalise_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise TypeError("schema must be a JSON object")
    return {"type": "object", **schema} if "type" not in schema else dict(schema)


def _validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Small JSON-Schema validator, sufficient for the project response schemas."""
    if jsonschema is not None:
        try:
            jsonschema.validate(instance=value, schema=schema)
        except jsonschema.ValidationError as exc:
            message = exc.message
            if exc.validator == "required" and isinstance(exc.validator_value, list):
                missing = [name for name in exc.validator_value if name not in exc.instance]
                if "quote" in missing:
                    message = "quote is required for an extracted value"
            raise LLMCallError(f"{path}: {message}") from exc
        return
    if "type" in schema:
        kind = schema["type"]
        kind_names = kind if isinstance(kind, list) else [kind]
        checks = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }
        if not any(name in checks and checks[name] for name in kind_names):
            raise LLMCallError(f"{path} has wrong type; expected {kind}")

    if "enum" in schema and value not in schema["enum"]:
        raise LLMCallError(f"{path} is not an allowed enum value")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                raise LLMCallError(f"{path}.{name} is required")
        properties = schema.get("properties", {})
        for name, child in value.items():
            child_schema = properties.get(name)
            if child_schema is not None:
                _validate_schema(child, child_schema, f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                raise LLMCallError(f"{path}.{name} is not allowed")

    if isinstance(value, list) and "items" in schema:
        for index, child in enumerate(value):
            _validate_schema(child, schema["items"], f"{path}[{index}]")

    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        raise LLMCallError(f"{path} is shorter than minLength")


def _quoted_fact_candidates(value: Any, source_text: str, path: str = "$"):
    if isinstance(value, dict):
        if "value" in value:
            quote = value.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                raise LLMCallError(f"{path}.quote is required for an extracted value")
            if quote not in source_text:
                raise LLMCallError(f"{path}.quote is not present in the source text")
        for key, child in value.items():
            yield from _quoted_fact_candidates(child, source_text, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _quoted_fact_candidates(child, source_text, f"{path}[{index}]")


class LLMClient:
    def __init__(
        self,
        *,
        model: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        transport: Callable[[str, str, dict[str, Any], dict[str, str], float], dict[str, Any]] | None = None,
        cache_dir: Path | str = "store/llm_cache",
        log_path: Path | str = "store/llm_log.jsonl",
        timeout: float | None = None,
        call_budget: int | None = None,
    ):
        env_url, env_model, env_api_key, env_provider = _environment()
        self.url = url or env_url
        self.model = model or env_model
        self.api_key = api_key if api_key is not None else env_api_key
        self.provider = provider or env_provider
        self.transport = transport
        self.cache_dir = Path(cache_dir)
        self.log_path = Path(log_path)
        self.timeout = timeout if timeout is not None else float(os.getenv("SOONY_LLM_TIMEOUT", "30"))
        configured_budget = os.getenv("SOONY_LLM_CALL_BUDGET", "20")
        self.call_budget = call_budget if call_budget is not None else int(configured_budget)
        self.calls = 0

    def configured(self) -> bool:
        return self.provider not in {"none", "disabled"} and bool(self.model)

    def cache_key(self, task: str, prompt: str, images: list | None) -> str:
        digest = hashlib.sha256()
        digest.update((self.model or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(task.encode("utf-8"))
        digest.update(b"\0")
        digest.update(prompt.encode("utf-8"))
        for image in images or []:
            if isinstance(image, dict):
                image_bytes = json.dumps(image, sort_keys=True, ensure_ascii=False).encode("utf-8")
            elif isinstance(image, (bytes, bytearray)):
                image_bytes = bytes(image)
            else:
                image_bytes = str(image).encode("utf-8")
            digest.update(b"\0")
            digest.update(image_bytes)
        return digest.hexdigest()

    def _http_transport(self, model: str, url: str, payload: dict[str, Any],
                        headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request_headers = {"Content-Type": "application/json", **headers}
        request = urllib.request.Request(
            url,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=request_headers,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            envelope = json.load(response)
        content = envelope["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return json.loads(content)
        raise LLMCallError("Model content was not a JSON string")

    def ping(self) -> dict[str, Any]:
        start = time.monotonic()
        result = self.complete_json(
            "ping",
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            "Reply with exactly this JSON object: {\"ok\": true}",
            source_text='{"ok": true}',
        )
        return {"ok": bool(result.get("ok")), "latency_seconds": round(time.monotonic() - start, 3)}

    def complete_json(
        self,
        task: str,
        schema: dict[str, Any],
        prompt: str,
        *,
        source_text: str = "",
        images: list | None = None,
        validate_quotes: bool = True,
    ) -> dict[str, Any]:
        if not self.configured():
            raise LLMCallError("No LLM model is configured")
        if self.calls >= self.call_budget:
            raise LLMCallError("Per-cycle LLM call budget exhausted")

        schema = _normalise_schema(schema)
        cache_key = self.cache_key(task, prompt, images)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                result = cached["result"]
                _validate_schema(result, schema)
                if validate_quotes:
                    list(_quoted_fact_candidates(result, source_text))
                self._log(task, cache_key, cached.get("latency_seconds", 0.0),
                          cached.get("input_tokens"), cached.get("output_tokens"), "cache")
                return result
            except (OSError, json.JSONDecodeError, LLMCallError):
                cache_path.unlink(missing_ok=True)

        messages = [
            {"role": "system", "content": "Return a single valid JSON object matching the supplied JSON schema. Do not add prose."},
            {"role": "user", "content": prompt},
        ]
        if images:
            messages[-1]["content"] = [
                {"type": "text", "text": prompt},
                *images,
            ]

        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        start = time.monotonic()
        self.calls += 1
        try:
            if self.transport:
                result = self.transport(self.model or "", self.url, payload, headers, self.timeout)
            else:
                result = self._http_transport(self.model or "", self.url, payload, headers, self.timeout)
            latency = time.monotonic() - start
            if not isinstance(result, dict):
                raise LLMCallError("Model response must be a JSON object")
            _validate_schema(result, schema)
            if validate_quotes:
                list(_quoted_fact_candidates(result, source_text))
            cache_record = {
                "result": result,
                "latency_seconds": round(latency, 6),
                "input_tokens": None,
                "output_tokens": None,
            }
            cache_path.write_text(json.dumps(cache_record, ensure_ascii=False), encoding="utf-8")
            self._log(task, cache_key, latency, None, None, "live")
            return result
        except (LLMCallError, OSError, ValueError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
            latency = time.monotonic() - start
            self._log(task, cache_key, latency, None, None, "error", str(exc))
            raise LLMCallError(str(exc)) from exc

    def _log(self, task: str, cache_key: str, latency: float, input_tokens: int | None,
             output_tokens: int | None, status: str, error: str | None = None) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "task": task,
            "model": self.model,
            "cache_key": cache_key,
            "latency_seconds": round(latency, 6),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": 0.0,
            "status": status,
        }
        if error:
            record["error"] = error
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
