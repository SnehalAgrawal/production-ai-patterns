"""
The model calls, all to a local Ollama server:

  embed()   turns text into vectors (nomic-embed-text by default)
  chat()    one chat call whose output is constrained to a JSON schema (llama3.2:3b by default)
  unload()  frees a model's memory after a run
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()


def chat_model() -> str:
    return os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2:3b")


def embedding_model() -> str:
    return os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")


def base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def embed(texts: list[str]) -> list[list[float]]:
    body = {"model": embedding_model(), "input": texts, "truncate": False}
    response = requests.post(f"{base_url()}/api/embed", json=body, timeout=300)
    response.raise_for_status()
    return response.json()["embeddings"]


def chat(messages: list[dict], *, schema: dict, options: dict, max_tokens: int) -> dict:
    """The raw output text and the call's token counts. The caller parses and checks the output."""
    body = {"model": chat_model(), "messages": messages, "stream": False, "format": schema,
            "options": {**options, "num_predict": max_tokens}}
    started = time.perf_counter()
    response = requests.post(f"{base_url()}/api/chat", json=body, timeout=600)
    response.raise_for_status()
    data = response.json()
    if data["prompt_eval_count"] + max_tokens > options["num_ctx"]:
        # Ollama would have cut the prompt to fit the context window without saying so.
        raise RuntimeError(f"prompt of {data['prompt_eval_count']} tokens is too long for num_ctx {options['num_ctx']}")
    return {"content": data["message"]["content"], "prompt_tokens": data["prompt_eval_count"],
            "output_tokens": data["eval_count"], "done_reason": data["done_reason"],
            "seconds": round(time.perf_counter() - started, 2)}


def unload(model: str) -> None:
    requests.post(f"{base_url()}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60).raise_for_status()
