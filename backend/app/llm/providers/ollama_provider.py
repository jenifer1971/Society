"""Ollama provider — local/on-prem, uses OpenAI-compatible endpoint."""

from typing import Dict, List, Optional
from openai import OpenAI

from ...config import Config
from ..base import BaseLLMClient


class OllamaClient(BaseLLMClient):

    def __init__(self, model: Optional[str] = None, **_):
        self.model = model or Config.LLM_MODEL_NAME or Config.OLLAMA_MODEL
        base_url = Config.OLLAMA_BASE_URL.rstrip("/") + "/v1"
        # Ollama doesn't require a real key but the OpenAI SDK expects a non-empty string
        self.client = OpenAI(api_key="ollama", base_url=base_url)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
    ) -> str:
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format
        response = self.client.chat.completions.create(**kwargs)
        return self._strip_think_tags(response.choices[0].message.content)
