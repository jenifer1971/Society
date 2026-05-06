"""
Shared helper: maps LLM_PROVIDER env var to a CAMEL ModelFactory call.

CAMEL's ModelFactory supports all target providers natively.
Each provider needs specific env vars set before ModelFactory.create() is called.
"""

import os


# Maps our LLM_PROVIDER value to (ModelPlatformType attr name, default model name)
_PROVIDER_MAP = {
    "openai":       ("OPENAI",      "gpt-4o"),
    "azure_openai": ("AZURE",       ""),          # CAMEL reads AZURE_* env vars
    "gemini":       ("GOOGLE",      "gemini-2.0-flash"),
    "anthropic":    ("ANTHROPIC",   "claude-sonnet-4-6"),
    "bedrock":      ("BEDROCK",     "anthropic.claude-3-5-sonnet-20241022-v2:0"),
    "ollama":       ("OLLAMA",      "llama3"),
}


def create_camel_model():
    """
    Build and return a CAMEL model instance for the active LLM_PROVIDER.
    Sets any environment variables CAMEL expects before calling ModelFactory.
    """
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType

    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

    if provider not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            f"Choose: {', '.join(_PROVIDER_MAP)}"
        )

    platform_attr, default_model = _PROVIDER_MAP[provider]
    model_name = os.environ.get("LLM_MODEL_NAME", "") or default_model

    # --- OpenAI ---
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        os.environ["OPENAI_API_KEY"] = api_key

    # --- Azure OpenAI ---
    elif provider == "azure_openai":
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        if not api_key or not endpoint or not deployment:
            raise ValueError(
                "AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and "
                "AZURE_OPENAI_DEPLOYMENT must all be set"
            )
        os.environ["AZURE_OPENAI_API_KEY"] = api_key
        os.environ["AZURE_OPENAI_ENDPOINT"] = endpoint
        model_name = deployment

    # --- Google Gemini ---
    elif provider == "gemini":
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set")
        os.environ["GOOGLE_API_KEY"] = api_key

    # --- Anthropic ---
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        os.environ["ANTHROPIC_API_KEY"] = api_key

    # --- AWS Bedrock ---
    elif provider == "bedrock":
        if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
            raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set")

    # --- Ollama ---
    elif provider == "ollama":
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        os.environ["OLLAMA_API_BASE_URL"] = ollama_url.rstrip("/") + "/v1"

    platform = getattr(ModelPlatformType, platform_attr)
    print(f"LLM provider: {provider} | platform: {platform_attr} | model: {model_name}")

    return ModelFactory.create(
        model_platform=platform,
        model_type=model_name,
    )
