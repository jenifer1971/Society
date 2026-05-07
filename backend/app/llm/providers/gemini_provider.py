"""Google Gemini provider — uses OpenAI-compatible endpoint."""

from typing import Dict, List, Optional
from openai import OpenAI

from ...config import Config
from ..base import BaseLLMClient

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiClient(BaseLLMClient):

    def __init__(self, model: Optional[str] = None, **_):
        self.model = model or Config.LLM_MODEL_NAME or Config.GEMINI_MODEL
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set")
        self.client = OpenAI(
            api_key=Config.GOOGLE_API_KEY,
            base_url=_GEMINI_BASE_URL,
        )

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
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            # Gemini may reject response_format on some models — retry without it
            if response_format and "response_format" in str(e).lower() or "400" in str(e):
                kwargs.pop("response_format", None)
                response = self.client.chat.completions.create(**kwargs)
            else:
                raise
        return self._strip_think_tags(response.choices[0].message.content)

