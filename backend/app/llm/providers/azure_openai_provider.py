"""Azure OpenAI provider."""

from typing import Dict, List, Optional
from openai import AzureOpenAI

from ...config import Config
from ..base import BaseLLMClient


class AzureOpenAIClient(BaseLLMClient):

    def __init__(self, model: Optional[str] = None, **_):
        # Azure uses deployment names, not model names
        self.model = model or Config.LLM_MODEL_NAME or Config.AZURE_OPENAI_DEPLOYMENT
        if not Config.AZURE_OPENAI_API_KEY:
            raise ValueError("AZURE_OPENAI_API_KEY is not set")
        if not Config.AZURE_OPENAI_ENDPOINT:
            raise ValueError("AZURE_OPENAI_ENDPOINT is not set")
        self.client = AzureOpenAI(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
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
        response = self.client.chat.completions.create(**kwargs)
        return self._strip_think_tags(response.choices[0].message.content)
