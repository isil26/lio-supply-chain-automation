"""LLM transports used by the agent runtime.

The runtime deliberately keeps the wire format small so it can run with only
the Python standard library, or with a scripted FakeLLM in offline demos.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any


def _key(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class LLMError(RuntimeError):
    pass


MODEL_PRICES_USD_PER_MTOK = {
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}


def usage_cost(model: str, usage: dict) -> float:
    prices = MODEL_PRICES_USD_PER_MTOK.get(model)
    if not prices:
        return 0.0
    return (
        int(usage.get("input_tokens", 0)) * prices["input"]
        + int(usage.get("output_tokens", 0)) * prices["output"]
    ) / 1_000_000


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        result = {}
        key_text = ""
        for key, item in value.items():
            key_text = str(key).casefold()
            if "authorization" in key_text or key_text in ("api_key", "x-api-key", "token", "password", "secret"):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact(item, secrets)
        return result
    return value


def _configured_secrets() -> tuple[str, ...]:
    names = ("SOONY_LLM_KEY", "SOONY_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    return tuple(value for name in names if (value := os.getenv(name)))


class Adapter:
    def chat(self, messages, tools=(), system="", model=None):
        raise NotImplementedError


class HTTPAdapter(Adapter):
    def __init__(self, mode=None, cassette_dir="store/agent_cassettes"):
        self.mode = mode or os.getenv("SOONY_AGENT_MODE", "live")
        self.cassette_dir = Path(cassette_dir)

    def chat(self, messages, tools=(), system="", model=None):
        model = model or os.getenv("SOONY_AGENT_MODEL") or os.getenv("SOONY_LLM_MODEL", "gpt-4.1-mini")
        request = {"messages": messages, "tools": list(tools), "system": system, "model": model}
        path = self.cassette_dir / f"{_key(request)}.json"
        if self.mode == "replay":
            if not path.exists():
                raise LLMError(f"missing replay cassette: {path}")
            return json.loads(path.read_text())
        response = self._request(request)
        response = _redact(response, _configured_secrets())
        if self.mode == "record":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(response, sort_keys=True))
        return response

    def _request(self, request):
        url = os.getenv("SOONY_LLM_URL")
        if url:
            return self._openai(request, url)
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("no live provider configured: set SOONY_LLM_URL plus SOONY_LLM_API_KEY/OPENAI_API_KEY or ANTHROPIC_API_KEY")
        anthropic_messages = self._anthropic_messages(request["messages"])
        anthropic_tools = [{"name": item["function"]["name"],
                            "description": item["function"].get("description", item["function"]["name"]),
                            "input_schema": item["function"].get("parameters", {"type": "object", "properties": {}})}
                           for item in request["tools"]]
        payload = {"model": request["model"], "max_tokens": 1200, "system": request["system"],
                   "messages": anthropic_messages, "tools": anthropic_tools}
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", json.dumps(payload).encode(),
            {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        data = self._post(req)
        return self._normalise(data, "anthropic", request["model"])

    def _openai(self, request, url):
        if not url.rstrip("/").endswith("chat/completions"):
            url = url.rstrip("/") + "/chat/completions"
        messages = ([{"role": "system", "content": request["system"]}] if request["system"] else []) + self._openai_messages(request["messages"])
        payload = {"model": request["model"], "messages": messages, "tools": request["tools"]}
        headers = {"content-type": "application/json"}
        key = next((os.environ[name] for name in ("SOONY_LLM_KEY", "SOONY_LLM_API_KEY", "OPENAI_API_KEY") if os.getenv(name)), None)
        if not key:
            raise LLMError("no live API key configured: set SOONY_LLM_KEY, SOONY_LLM_API_KEY or OPENAI_API_KEY")
        headers["authorization"] = "Bearer " + key
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        data = self._post(req)
        return self._normalise(data, "openai", request["model"])

    def _post(self, req):
        last_error = None
        for attempt in range(2):
            try:
                return json.loads(urllib.request.urlopen(req, timeout=30).read())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 1:
                    body = _redact(body, _configured_secrets())
                    raise LLMError(f"live provider HTTP {exc.code}: {body[:500]}") from exc
                time.sleep(0.5 * (attempt + 1))
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt == 1:
                    raise LLMError(f"live provider unavailable: {exc.reason}") from exc
                time.sleep(0.5 * (attempt + 1))
        raise LLMError(f"live provider request failed: {last_error}")

    @staticmethod
    def _openai_messages(messages):
        converted = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                converted.append({"role": "tool", "tool_call_id": message.get("tool_call_id"),
                                  "content": message.get("content", "")})
            elif role == "assistant" and message.get("tool_calls"):
                converted.append({"role": "assistant", "content": message.get("content") or "",
                                  "tool_calls": [{"id": call["id"], "type": "function",
                                                  "function": {"name": call["name"],
                                                               "arguments": json.dumps(call.get("arguments", {}))}}
                                                 for call in message["tool_calls"]]})
            else:
                converted.append({"role": role, "content": message.get("content", "")})
        return converted

    @staticmethod
    def _anthropic_messages(messages):
        converted = []
        pending = None
        for message in messages:
            if message.get("role") == "tool":
                if pending is None:
                    pending = {"role": "user", "content": []}
                pending["content"].append({"type": "tool_result",
                                           "tool_use_id": message.get("tool_call_id"),
                                           "content": message.get("content", "")})
            elif message.get("role") == "assistant" and message.get("tool_calls"):
                if pending:
                    converted.append(pending)
                    pending = None
                content = []
                if message.get("content"):
                    content.append({"type": "text", "text": message["content"]})
                content.extend({"type": "tool_use", "id": call["id"],
                                "name": call["name"], "input": call.get("arguments", {})}
                               for call in message["tool_calls"])
                converted.append({"role": "assistant", "content": content})
            else:
                if pending:
                    converted.append(pending)
                    pending = None
                converted.append({"role": message.get("role"), "content": message.get("content", "")})
        if pending:
            converted.append(pending)
        return converted

    @staticmethod
    def _normalise(data, provider, model=None):
        if provider == "anthropic":
            text = "".join(x.get("text", "") for x in data.get("content", []) if x.get("type") == "text")
            calls = [{"id": x.get("id"), "name": x["name"], "arguments": x.get("input", {})}
                     for x in data.get("content", []) if x.get("type") == "tool_use"]
        else:
            message = data.get("choices", [{}])[0].get("message", {})
            text, calls = message.get("content") or "", []
            calls = [{"id": x.get("id"), "name": x["function"]["name"],
                      "arguments": json.loads(x["function"].get("arguments") or "{}")}
                     for x in message.get("tool_calls", [])]
        usage = data.get("usage", {})
        usage = {"input_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
                 "output_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0))}
        model = model or data.get("model", "")
        usage["cost_usd"] = usage_cost(model, usage)
        return {"text": text, "tool_calls": calls, "usage": usage}


class FakeLLM(Adapter):
    """Scripted responses; each response is returned once in order."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def chat(self, messages, tools=(), system="", model=None):
        self.requests.append({"messages": messages, "tools": tools})
        if not self.responses:
            return {"text": "No scripted response.", "tool_calls": [], "usage": {}}
        response = self.responses.pop(0)
        return response if isinstance(response, dict) else {"text": str(response), "tool_calls": [], "usage": {}}
