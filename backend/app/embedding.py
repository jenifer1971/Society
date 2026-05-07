"""
Embedding client — generates vector embeddings using the enterprise's existing
LLM provider and API key.  No new service, no new credentials.

Provider mapping:
  openai       → text-embedding-3-small  (768-dim via Matryoshka)
  azure_openai → text-embedding-3-small  (768-dim, via Azure endpoint)
  gemini       → text-embedding-004      (768-dim natively)
  anthropic    → ⚠ no embedding model   → returns None (search falls back to keyword)
  bedrock      → amazon.titan-embed-text-v2:0 (1024-dim, truncated to 768)
  ollama       → nomic-embed-text        (768-dim natively)

All providers output 768 dimensions so the pgvector column is a fixed size.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from .config import Config
from .utils.logger import get_logger

logger = get_logger('mirofish.embedding')

# Fixed output dimension used across all providers.
EMBEDDING_DIM = 768


def _vec_str(v: List[float]) -> str:
    """Format a float list as a pgvector literal: '[0.1,0.2,...]'"""
    return '[' + ','.join(f'{x:.8f}' for x in v) + ']'


class EmbeddingClient:
    """
    Generates text embeddings using the provider already configured in .env.

    Usage:
        client = EmbeddingClient()
        vec = client.embed("Alice supports the new education policy.")
        # vec is a List[float] of length EMBEDDING_DIM, or None on failure/unsupported provider
    """

    def __init__(self):
        self._provider = Config.LLM_PROVIDER

    # ── Public API ─────────────────────────────────────────────────────────────

    def embed(self, text: str) -> Optional[List[float]]:
        """Return a EMBEDDING_DIM-dimensional embedding, or None if unsupported."""
        if not text or not text.strip():
            return None
        try:
            if self._provider == 'openai':
                return self._embed_openai(text.strip())
            elif self._provider == 'azure_openai':
                return self._embed_azure(text.strip())
            elif self._provider == 'gemini':
                return self._embed_gemini(text.strip())
            elif self._provider == 'anthropic':
                # Anthropic has no embedding model; caller falls back to keyword search
                return None
            elif self._provider == 'bedrock':
                return self._embed_bedrock(text.strip())
            elif self._provider == 'ollama':
                return self._embed_ollama(text.strip())
        except Exception as e:
            logger.warning(f"Embedding generation failed ({self._provider}): {e}")
        return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed a list of texts.  OpenAI/Azure send one batched request; others loop."""
        if not texts:
            return []
        if self._provider in ('openai', 'azure_openai'):
            try:
                return self._embed_batch_openai(texts)
            except Exception as e:
                logger.warning(f"Batch embedding failed, falling back to single: {e}")
        return [self.embed(t) for t in texts]

    def supported(self) -> bool:
        return self._provider != 'anthropic'

    # ── OpenAI ─────────────────────────────────────────────────────────────────

    def _embed_openai(self, text: str) -> Optional[List[float]]:
        import openai
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        resp = client.embeddings.create(
            model='text-embedding-3-small',
            input=text,
            dimensions=EMBEDDING_DIM,
        )
        return resp.data[0].embedding

    def _embed_batch_openai(self, texts: List[str]) -> List[Optional[List[float]]]:
        import openai
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        resp = client.embeddings.create(
            model='text-embedding-3-small',
            input=texts,
            dimensions=EMBEDDING_DIM,
        )
        result: List[Optional[List[float]]] = [None] * len(texts)
        for item in resp.data:
            result[item.index] = item.embedding
        return result

    # ── Azure OpenAI ───────────────────────────────────────────────────────────

    def _embed_azure(self, text: str) -> Optional[List[float]]:
        import openai
        client = openai.AzureOpenAI(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
        )
        # Azure embedding deployment name — defaults to "text-embedding-3-small"
        deployment = os.environ.get('AZURE_EMBEDDING_DEPLOYMENT', 'text-embedding-3-small')
        resp = client.embeddings.create(
            model=deployment,
            input=text,
            dimensions=EMBEDDING_DIM,
        )
        return resp.data[0].embedding

    # ── Google Gemini ──────────────────────────────────────────────────────────

    def _embed_gemini(self, text: str) -> Optional[List[float]]:
        # Gemini embedding via OpenAI-compatible endpoint (same key, no extra dep)
        import openai
        client = openai.OpenAI(
            api_key=Config.GOOGLE_API_KEY,
            base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
        )
        resp = client.embeddings.create(
            model='text-embedding-004',  # 768-dim natively
            input=text,
        )
        vec = resp.data[0].embedding
        return _truncate_or_pad(vec, EMBEDDING_DIM)

    # ── AWS Bedrock ────────────────────────────────────────────────────────────

    def _embed_bedrock(self, text: str) -> Optional[List[float]]:
        import boto3
        client = boto3.client(
            'bedrock-runtime',
            region_name=Config.AWS_REGION,
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
        )
        # Titan Embed v2 supports outputEmbeddingLength to get 256/512/1024
        body = json.dumps({
            'inputText': text[:8192],
            'dimensions': EMBEDDING_DIM,
            'normalize': True,
        })
        resp = client.invoke_model(
            modelId='amazon.titan-embed-text-v2:0',
            body=body,
            contentType='application/json',
        )
        result = json.loads(resp['body'].read())
        vec = result.get('embedding', [])
        return _truncate_or_pad(vec, EMBEDDING_DIM) if vec else None

    # ── Ollama ─────────────────────────────────────────────────────────────────

    def _embed_ollama(self, text: str) -> Optional[List[float]]:
        import openai
        base_url = Config.OLLAMA_BASE_URL.rstrip('/') + '/v1'
        client = openai.OpenAI(api_key='ollama', base_url=base_url)
        model = os.environ.get('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')
        resp = client.embeddings.create(model=model, input=text)
        vec = resp.data[0].embedding
        return _truncate_or_pad(vec, EMBEDDING_DIM)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _truncate_or_pad(vec: List[float], dim: int) -> List[float]:
    """Ensure vector has exactly `dim` dimensions."""
    if len(vec) == dim:
        return vec
    if len(vec) > dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))
