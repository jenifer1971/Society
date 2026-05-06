"""Anthropic Claude provider."""

import json
import re
from typing import Any, Dict, List, Optional

import anthropic

from ...config import Config
from ..base import BaseLLMClient


class AnthropicClient(BaseLLMClient):

    def __init__(self, model: Optional[str] = None, **_):
        self.model = model or Config.LLM_MODEL_NAME or Config.ANTHROPIC_MODEL
        if not Config.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
    ) -> str:
        # Anthropic separates the system prompt from the conversation
        system_prompt = ""
        conversation: List[Dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                conversation.append(msg)

        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=conversation,
        )
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.client.messages.create(**kwargs)
        return self._strip_think_tags(response.content[0].text)

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        # Ask the model explicitly to return JSON since Anthropic has no json_object mode
        json_hint = {"role": "user", "content": "Respond with valid JSON only, no markdown fences."}
        augmented = list(messages) + [json_hint]
        raw = self.chat(augmented, temperature=temperature, max_tokens=max_tokens)
        cleaned = raw.strip()
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned invalid JSON: {cleaned}")
