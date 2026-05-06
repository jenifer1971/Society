"""
LLM adapter layer — returns a provider-specific client based on LLM_PROVIDER env var.
"""

from ..config import Config
from .base import BaseLLMClient


def get_llm_client(**kwargs) -> BaseLLMClient:
    """Factory: instantiate the right LLM client for the configured provider."""
    provider = Config.LLM_PROVIDER

    if provider == 'openai':
        from .providers.openai_provider import OpenAIClient
        return OpenAIClient(**kwargs)

    if provider == 'azure_openai':
        from .providers.azure_openai_provider import AzureOpenAIClient
        return AzureOpenAIClient(**kwargs)

    if provider == 'gemini':
        from .providers.gemini_provider import GeminiClient
        return GeminiClient(**kwargs)

    if provider == 'anthropic':
        from .providers.anthropic_provider import AnthropicClient
        return AnthropicClient(**kwargs)

    if provider == 'bedrock':
        from .providers.bedrock_provider import BedrockClient
        return BedrockClient(**kwargs)

    if provider == 'ollama':
        from .providers.ollama_provider import OllamaClient
        return OllamaClient(**kwargs)

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        "Choose: openai, azure_openai, gemini, anthropic, bedrock, ollama"
    )
