"""Small provider adapter. Credentials never leave the server process."""
import json
import os
import time
import urllib.request

NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def settings():
    provider = os.getenv("BRIEFOPS_LLM_PROVIDER") or ("nvidia" if os.getenv("NVIDIA_API_KEY") else "openrouter")
    if provider == "nvidia":
        return {"provider": provider, "model": os.getenv("NVIDIA_MODEL") or NVIDIA_MODEL,
                "key": os.getenv("NVIDIA_API_KEY", ""), "url": "https://integrate.api.nvidia.com/v1/chat/completions"}
    if provider == "openrouter":
        return {"provider": provider, "model": os.getenv("OPENROUTER_MODEL", ""),
                "key": os.getenv("OPENROUTER_API_KEY", ""), "url": "https://openrouter.ai/api/v1/chat/completions"}
    return {"provider": "none", "model": "", "key": "", "url": ""}


def load_local_settings(root):
    """Load ignored local credentials only from the application entrypoint."""
    try:
        config = json.loads((root / "data" / "llm-config.json").read_text(encoding="utf-8"))
        if config.get("provider") != "nvidia":
            return False
        os.environ.setdefault("BRIEFOPS_LLM_PROVIDER", "nvidia")
        os.environ.setdefault("NVIDIA_MODEL", config.get("model") or NVIDIA_MODEL)
        key_file = root / "data" / "nvidia-api-key.txt"
        if not os.getenv("NVIDIA_API_KEY") and key_file.exists():
            os.environ["NVIDIA_API_KEY"] = key_file.read_text(encoding="utf-8").strip()
        return config.get("enabled") is True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def complete_json(prompt, text):
    config = settings()
    body = {"model": config["model"], "temperature": 0, "max_tokens": 600,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}]}
    if config["provider"] == "nvidia" and config["model"].startswith("nvidia/nemotron-3"):
        body["chat_template_kwargs"] = {"enable_thinking": False}
    request = urllib.request.Request(config["url"], json.dumps(body).encode(),
                                     {"Authorization": "Bearer " + config["key"], "Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty model output")
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    extracted = json.loads(content)
    if not isinstance(extracted, dict):
        raise ValueError("Expected JSON object")
    return extracted, {"provider": config["provider"], "model": config["model"],
                       "latency_ms": round((time.monotonic() - started) * 1000)}
