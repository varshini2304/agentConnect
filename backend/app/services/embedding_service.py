"""Semantic embeddings service with caching, persistence, and graceful fallback.

Supports local SentenceTransformer models when available and deterministic
reproducible fake embeddings for zero-network testing and offline development.
"""
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
import logging
import math
import re
from typing import Any, Sequence
import unicodedata

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import (
    get_embedding_model_name,
    get_embedding_provider_name,
    is_semantic_relevance_enabled,
)
from app.db.models import utc_now
from app.db.network import StoredEmbedding

log = logging.getLogger(__name__)

# Dimension for deterministic fake embeddings
FAKE_EMBEDDING_DIM = 384


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider fails to initialize or generate vectors."""
    pass


def normalize_text(value: str) -> str:
    """Normalize text with NFKC and whitespace collapsing."""
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(value.split())


def hash_text(text: str) -> str:
    """Generate SHA-256 hash of normalized text for cache invalidation."""
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine_similarity(
    vec1: Sequence[float] | None,
    vec2: Sequence[float] | None,
) -> float:
    """Compute cosine similarity between two numeric vectors.
    
    Returns float in range [-1.0, 1.0], or 0.0 if vectors are missing or orthogonal.
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = 0.0
    norm1_sq = 0.0
    norm2_sq = 0.0
    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1_sq += a * a
        norm2_sq += b * b
    if norm1_sq <= 0.0 or norm2_sq <= 0.0:
        return 0.0
    sim = dot / (math.sqrt(norm1_sq) * math.sqrt(norm2_sq))
    return max(-1.0, min(1.0, sim))


class BaseEmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        pass


class SentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings using a sentence-transformers model."""

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or get_embedding_model_name()
        self._model = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            return self._model
        except Exception as exc:
            log.warning("sentence_transformers_unavailable model=%s error=%s", self._model_name, exc)
            raise EmbeddingProviderError(f"Could not load SentenceTransformer model {self._model_name}: {exc}") from exc

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        try:
            embeddings = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
            return [vec.tolist() if hasattr(vec, "tolist") else list(vec) for vec in embeddings]
        except Exception as exc:
            log.warning("sentence_transformers_encode_failed error=%s", exc)
            raise EmbeddingProviderError(f"Embedding encoding failed: {exc}") from exc


class DeterministicFakeEmbeddingProvider(BaseEmbeddingProvider):
    """Generates deterministic, zero-network unit vectors with realistic semantic clusters.
    
    Ensures tests pass deterministically without downloading models or accessing the internet,
    while accurately producing high cosine similarity for related concepts and paraphrases.
    """

    # Semantic concept clusters mapped to concept index dimensions (0 to 31)
    SEMANTIC_CLUSTERS: dict[str, int] = {
        # Logistics, maritime, freight, ports, shipping
        "shipping": 1, "maritime": 1, "cargo": 1, "port": 1, "ports": 1, "logistics": 1,
        "freight": 1, "vessels": 1, "sea": 1, "ocean": 1, "vessel": 1, "dock": 1, "transport": 1,
        # Retail, shopping, discounts, promotions
        "retail": 2, "shopping": 2, "ecommerce": 2, "store": 2, "discounts": 2, "deals": 2,
        "sale": 2, "electronics": 2, "gadgets": 2, "products": 2, "promotion": 2, "promotions": 2,
        # Food, dining, restaurants, food delivery
        "food": 3, "restaurant": 3, "restaurants": 3, "delivery": 3, "meals": 3, "dining": 3,
        "cuisine": 3, "dishes": 3, "orders": 3, "order": 3, "cooking": 3,
        # Digital payments, cashback, wallets
        "payment": 4, "payments": 4, "cashback": 4, "wallet": 4, "upi": 4, "transaction": 4,
        "transactions": 4, "transfer": 4, "pay": 4,
        # Banking, cards, credit, loan, emi
        "banking": 5, "bank": 5, "credit": 5, "card": 5, "cards": 5, "emi": 5, "loan": 5,
        "finance": 5, "account": 5, "deposit": 5, "interest": 5,
        # Technology, software, integrations
        "software": 6, "integration": 6, "integrations": 6, "api": 6, "cloud": 6, "tech": 6,
        "database": 6, "platform": 6, "developer": 6, "system": 6, "systems": 6,
    }

    def __init__(self, model_name: str = "deterministic-fake-minilm"):
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def _embed_single(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9]+", normalize_text(text))
        if not tokens:
            return [0.0] * FAKE_EMBEDDING_DIM

        vector = [0.0] * FAKE_EMBEDDING_DIM

        # 1. Project semantic concepts into primary cluster dimensions
        for token in tokens:
            cluster_id = self.SEMANTIC_CLUSTERS.get(token)
            if cluster_id is not None:
                # Dense activation across a localized block for this cluster
                base_idx = cluster_id * 16
                for offset in range(16):
                    vector[base_idx + offset] += 2.5 / (offset + 1)

            # 2. Hashing trick across remaining dimensions for general token fingerprinting
            token_hash = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
            dim_idx = 128 + (token_hash % (FAKE_EMBEDDING_DIM - 128))
            sign = 1.0 if (token_hash & 1) else -1.0
            vector[dim_idx] += sign * 1.0

        # L2-normalize
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0.0:
            vector = [x / norm for x in vector]
        return vector

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_single(t) for t in texts]


# In-memory cache: (model_name, content_hash) -> embedding
_MEMORY_CACHE: dict[tuple[str, str], list[float]] = {}


def clear_embedding_cache():
    """Clear the in-memory embedding cache (useful in tests)."""
    _MEMORY_CACHE.clear()


class EmbeddingService:
    """Orchestrates embedding generation, caching, database persistence, and fallbacks."""

    def __init__(self, provider: BaseEmbeddingProvider | None = None):
        self._provider = provider

    def get_provider(self) -> BaseEmbeddingProvider | None:
        if self._provider is not None:
            return self._provider
        mode = get_embedding_provider_name()
        if mode == "fake":
            self._provider = DeterministicFakeEmbeddingProvider()
        elif mode == "sentence_transformers":
            self._provider = SentenceTransformerEmbeddingProvider()
        else:
            # Auto-detect: if sentence_transformers is importable, use it; else fake
            try:
                import sentence_transformers  # noqa: F401
                self._provider = SentenceTransformerEmbeddingProvider()
            except ImportError:
                self._provider = DeterministicFakeEmbeddingProvider()
        return self._provider

    def set_provider(self, provider: BaseEmbeddingProvider | None):
        self._provider = provider

    def text_for_post(self, title: str, category: str, content: str) -> str:
        """Compose representative text for an announcement / post."""
        return f"{title} {category} {content}".strip()

    def text_for_agent(
        self,
        categories: Iterable[str] = (),
        keywords: Iterable[str] = (),
        topics: Iterable[str] = (),
        role: str = "",
        domain: str = "",
        description: str = "",
    ) -> str:
        """Compose representative text for an agent's domain interests."""
        parts: list[str] = []
        if role:
            parts.append(f"Role: {role}")
        if domain:
            parts.append(f"Domain: {domain}")
        if description:
            parts.append(description)
        cat_list = [c for c in categories if c]
        if cat_list:
            parts.append("Categories: " + " ".join(cat_list))
        kw_list = [k for k in dict.fromkeys(list(keywords) + list(topics)) if k]
        if kw_list:
            parts.append("Interests: " + " ".join(kw_list))
        return " ".join(parts).strip()

    def get_or_create_embeddings_batch(
        self,
        db: Session | None,
        entities: Sequence[tuple[str, int, str]],  # (entity_type, entity_id, raw_text)
    ) -> dict[tuple[str, int], list[float]]:
        """Retrieve cached/persisted embeddings or compute missing ones in one batch."""
        if not is_semantic_relevance_enabled():
            return {}

        provider = self.get_provider()
        if provider is None:
            return {}

        model_name = provider.model_name
        results: dict[tuple[str, int], list[float]] = {}
        missing_to_embed: list[tuple[str, int, str, str]] = []  # (entity_type, entity_id, text, content_hash)

        # 1. Check in-memory cache and prepare database lookup
        lookup_needed: list[tuple[str, int, str, str]] = []
        for entity_type, entity_id, text in entities:
            chash = hash_text(text)
            cached = _MEMORY_CACHE.get((model_name, chash))
            if cached is not None:
                results[(entity_type, entity_id)] = cached
            else:
                lookup_needed.append((entity_type, entity_id, text, chash))

        # 2. Check database persistence if session is provided
        if db is not None and lookup_needed:
            ids_by_type: dict[str, list[int]] = {}
            for etype, eid, _, _ in lookup_needed:
                ids_by_type.setdefault(etype, []).append(eid)

            persisted_map: dict[tuple[str, int], StoredEmbedding] = {}
            for etype, eids in ids_by_type.items():
                stmt = select(StoredEmbedding).where(
                    StoredEmbedding.entity_type == etype,
                    StoredEmbedding.entity_id.in_(eids),
                    StoredEmbedding.model_name == model_name,
                )
                for row in db.scalars(stmt):
                    persisted_map[(row.entity_type, row.entity_id)] = row

            for etype, eid, text, chash in lookup_needed:
                row = persisted_map.get((etype, eid))
                if row is not None and row.content_hash == chash and row.embedding:
                    results[(etype, eid)] = row.embedding
                    _MEMORY_CACHE[(model_name, chash)] = row.embedding
                else:
                    missing_to_embed.append((etype, eid, text, chash))
        else:
            missing_to_embed = lookup_needed

        # 3. Compute missing embeddings in one batch
        if missing_to_embed:
            texts = [item[2] for item in missing_to_embed]
            try:
                vectors = provider.embed_texts(texts)
            except Exception as exc:
                log.warning("embedding_batch_generation_failed count=%d error=%s", len(texts), exc)
                return results

            now = utc_now()
            for (etype, eid, _, chash), vec in zip(missing_to_embed, vectors):
                results[(etype, eid)] = vec
                _MEMORY_CACHE[(model_name, chash)] = vec
                if db is not None:
                    try:
                        # Add or update row in database
                        existing = db.scalar(
                            select(StoredEmbedding).where(
                                StoredEmbedding.entity_type == etype,
                                StoredEmbedding.entity_id == eid,
                                StoredEmbedding.model_name == model_name,
                            )
                        )
                        if existing is not None:
                            existing.content_hash = chash
                            existing.embedding = vec
                            existing.updated_at = now
                        else:
                            db.add(StoredEmbedding(
                                entity_type=etype,
                                entity_id=eid,
                                model_name=model_name,
                                content_hash=chash,
                                embedding=vec,
                                created_at=now,
                                updated_at=now,
                            ))
                    except Exception as db_exc:
                        log.warning("stored_embedding_save_failed entity=%s:%d error=%s", etype, eid, db_exc)
            if db is not None:
                try:
                    db.flush()
                except Exception as flush_exc:
                    log.warning("stored_embedding_flush_failed error=%s", flush_exc)

        return results

    def get_or_create_post_embedding(
        self,
        db: Session | None,
        post_id: int,
        title: str,
        category: str,
        content: str,
        entity_type: str = "publication",
    ) -> list[float] | None:
        """Get or compute an embedding vector for a post or publication."""
        text = self.text_for_post(title, category, content)
        batch = self.get_or_create_embeddings_batch(db, [(entity_type, post_id, text)])
        return batch.get((entity_type, post_id))

    def get_or_create_agent_embedding(
        self,
        db: Session | None,
        agent_id: int,
        categories: Iterable[str] = (),
        keywords: Iterable[str] = (),
        topics: Iterable[str] = (),
        role: str = "",
        domain: str = "",
        description: str = "",
        entity_type: str = "agent",
    ) -> list[float] | None:
        """Get or compute an embedding vector for an agent profile."""
        text = self.text_for_agent(categories, keywords, topics, role, domain, description)
        batch = self.get_or_create_embeddings_batch(db, [(entity_type, agent_id, text)])
        return batch.get((entity_type, agent_id))


# Global default service instance
default_embedding_service = EmbeddingService()

