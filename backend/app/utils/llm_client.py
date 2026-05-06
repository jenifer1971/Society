"""
LLM client — thin wrapper that delegates to the provider selected via LLM_PROVIDER.
All callers use the same LLMClient interface; the provider is swapped in config.
"""

from typing import Any, Dict, List, Optional

from ..llm import get_llm_client
from ..llm.base import BaseLLMClient


class LLMClient:
    """Backwards-compatible façade over the pluggable provider layer."""

    def __init__(
        self,
        model: Optional[str] = None,
        **kwargs,
    ):
        self._client: BaseLLMClient = get_llm_client(model=model, **kwargs)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
    ) -> str:
        return self._client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        return self._client.chat_json(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
