"""
Configuration management — loads from .env at project root.
"""

import os
from dotenv import load_dotenv

project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    load_dotenv(override=True)


class Config:
    """Flask configuration and provider settings."""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    JSON_AS_ASCII = False

    # ---------------------------------------------------------------------------
    # LLM provider selection
    # Supported values: openai | azure_openai | gemini | anthropic | bedrock | ollama
    # ---------------------------------------------------------------------------
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'openai').lower()
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', '')

    # OpenAI
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')

    # Azure OpenAI
    AZURE_OPENAI_API_KEY = os.environ.get('AZURE_OPENAI_API_KEY', '')
    AZURE_OPENAI_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT', '')
    AZURE_OPENAI_DEPLOYMENT = os.environ.get('AZURE_OPENAI_DEPLOYMENT', '')
    AZURE_OPENAI_API_VERSION = os.environ.get('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')

    # Google Gemini
    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')

    # Anthropic
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-6')

    # AWS Bedrock
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
    BEDROCK_MODEL = os.environ.get('BEDROCK_MODEL', 'anthropic.claude-3-5-sonnet-20241022-v2:0')

    # Ollama (local / on-prem)
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3')

    # ---------------------------------------------------------------------------
    # PostgreSQL + pgvector — knowledge graph & agent memory store
    # ---------------------------------------------------------------------------
    POSTGRES_DSN = os.environ.get(
        'POSTGRES_DSN',
        'postgresql://society:society@localhost:5432/society',
    )

    # ---------------------------------------------------------------------------
    # Embeddings — reuses the same provider + key as the LLM.
    # Azure users: set AZURE_EMBEDDING_DEPLOYMENT to their embedding deployment name.
    # Ollama users: set OLLAMA_EMBEDDING_MODEL (default: nomic-embed-text).
    # Anthropic users: no embedding model available — search falls back to keyword.
    # ---------------------------------------------------------------------------
    AZURE_EMBEDDING_DEPLOYMENT = os.environ.get('AZURE_EMBEDDING_DEPLOYMENT', 'text-embedding-3-small')
    OLLAMA_EMBEDDING_MODEL = os.environ.get('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')

    # ---------------------------------------------------------------------------
    # File upload
    # ---------------------------------------------------------------------------
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # Text processing
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    # OASIS simulation
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report agent
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """Validate that the selected provider is fully configured."""
        errors = []
        p = cls.LLM_PROVIDER

        if p == 'openai':
            if not cls.OPENAI_API_KEY:
                errors.append("OPENAI_API_KEY is not set")
        elif p == 'azure_openai':
            if not cls.AZURE_OPENAI_API_KEY:
                errors.append("AZURE_OPENAI_API_KEY is not set")
            if not cls.AZURE_OPENAI_ENDPOINT:
                errors.append("AZURE_OPENAI_ENDPOINT is not set")
            if not cls.AZURE_OPENAI_DEPLOYMENT:
                errors.append("AZURE_OPENAI_DEPLOYMENT is not set")
        elif p == 'gemini':
            if not cls.GOOGLE_API_KEY:
                errors.append("GOOGLE_API_KEY is not set")
        elif p == 'anthropic':
            if not cls.ANTHROPIC_API_KEY:
                errors.append("ANTHROPIC_API_KEY is not set")
        elif p == 'bedrock':
            if not cls.AWS_ACCESS_KEY_ID:
                errors.append("AWS_ACCESS_KEY_ID is not set")
            if not cls.AWS_SECRET_ACCESS_KEY:
                errors.append("AWS_SECRET_ACCESS_KEY is not set")
        elif p == 'ollama':
            pass  # No credentials required
        else:
            errors.append(f"Unknown LLM_PROVIDER '{p}'. "
                          "Choose: openai, azure_openai, gemini, anthropic, bedrock, ollama")

        return errors
