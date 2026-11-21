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
from pathlib import Path
from typing import Any


def _key(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class LLMError(RuntimeError):
    pass


class Adapter:
    def chat(self, messages, tools=(), system="", model=None):
        raise NotImplementedError


class HTTPAdapter(Adapter):
    def __init__(self, mode=None, cassette_dir="store/agent_cassettes"):
        self.mode = mode or os.getenv("SOONY_AGENT_MODE", "live")
        self.cassette_dir = Path(cassette_dir)

    def chat(self, messages, tools=(), system="", model=None):
        model = model or os.getenv("SOONY_AGENT_MODEL", "claude-haiku-5-5")
        request = {"messages": messages, "tools": list(tools), "system": system, "model": model}
        path = self.cassette_dir / f"{_key(request)}.json"
        if self.mode == "replay":
            if not path.exists():
                raise LLMError(f"missing replay cassette: {path}")
            return json.loads(path.read_text())
        response = self._request(request)
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
            raise LLMError("no SOONY_LLM_URL or ANTHROPIC_API_KEY configured")
        payload = {"model": request["model"], "max_tokens": 1200, "system": request["system"],
                   "messages": request["messages"], "tools": request["tools"]}
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", json.dumps(payload).encode(),
            {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        return self._normalise(json.loads(urllib.request.urlopen(req, timeout=30).read()), "anthropic")

    def _openai(self, request, url):
        if not url.rstrip("/").endswith("chat/completions"):
            url = url.rstrip("/") + "/v1/chat/completions"
        messages = ([{"role": "system", "content": request["system"]}] if request["system"] else []) + request["messages"]
        payload = {"model": request["model"], "messages": messages, "tools": request["tools"]}
        headers = {"content-type": "application/json"}
        if os.getenv("SOONY_LLM_KEY"):
            headers["authorization"] = "Bearer " + os.environ["SOONY_LLM_KEY"]
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        return self._normalise(json.loads(urllib.request.urlopen(req, timeout=30).read()), "openai")

    @staticmethod
    def _normalise(data, provider):
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
        return {"text": text, "tool_calls": calls,
                "usage": {"input_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
                          "output_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0))}}


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
