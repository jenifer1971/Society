"""AWS Bedrock provider — uses the Converse API for a unified message interface."""

import json
import re
from typing import Any, Dict, List, Optional

import boto3

from ...config import Config
from ..base import BaseLLMClient


class BedrockClient(BaseLLMClient):

    def __init__(self, model: Optional[str] = None, **_):
        self.model = model or Config.LLM_MODEL_NAME or Config.BEDROCK_MODEL
        if not Config.AWS_ACCESS_KEY_ID or not Config.AWS_SECRET_ACCESS_KEY:
            raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set")
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=Config.AWS_REGION,
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
    ) -> str:
        system_blocks: List[Dict] = []
        conversation: List[Dict] = []

        for msg in messages:
            if msg["role"] == "system":
                system_blocks.append({"text": msg["content"]})
            else:
                conversation.append({
                    "role": msg["role"],
                    "content": [{"text": msg["content"]}],
                })

        kwargs: Dict[str, Any] = dict(
            modelId=self.model,
            messages=conversation,
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        )
        if system_blocks:
            kwargs["system"] = system_blocks

        response = self.client.converse(**kwargs)
        text = response["output"]["message"]["content"][0]["text"]
        return self._strip_think_tags(text)

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
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
