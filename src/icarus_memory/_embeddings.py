"""Embedding backend (lazy-loaded; only imported when the extras are installed).

Importing this module fails fast with a clear message if the optional
``[embeddings]`` extras are not installed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError as exc:
    raise ImportError(
        "icarus-memory hybrid retrieval requires the [embeddings] extra. "
        "Install with: pip install 'icarus-memory[embeddings]'"
    ) from exc


_MODELS: dict[str, Any] = {}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(model_name: str) -> str:
    return _SLUG_RE.sub("-", model_name.lower()).strip("-")


def get_model(model_name: str) -> Any:
    if model_name not in _MODELS:
        _MODELS[model_name] = SentenceTransformer(model_name)
    return _MODELS[model_name]


def embed(model_name: str, texts: list[str]) -> Any:
    model = get_model(model_name)
    return np.asarray(model.encode(texts, normalize_embeddings=True))


def cache_path(root: Path, model_name: str, entry_id: str) -> Path:
    suffix = entry_id.split(":", 1)[1]
    return root / ".cache" / "embeddings" / _slug(model_name) / f"{suffix}.npy"


def cache_meta_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(".meta")


def cache_key(model_name: str, source_path: Path) -> str:
    stat = source_path.stat()
    payload = f"{model_name}|{stat.st_mtime_ns}|{stat.st_size}".encode()
    return hashlib.sha256(payload).hexdigest()


def load_cached(cache_file: Path, expected_key: str) -> Any | None:
    meta = cache_meta_path(cache_file)
    if not cache_file.exists() or not meta.exists():
        return None
    if meta.read_text().strip() != expected_key:
        return None
    return np.load(cache_file)


def save_cached(cache_file: Path, key: str, vector: Any) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_file, vector)
    cache_meta_path(cache_file).write_text(key)


def cosine_rank(query_vec: Any, doc_vecs: Any) -> Any:
    """Return doc indices sorted by descending cosine similarity."""
    scores = doc_vecs @ query_vec
    return np.argsort(-scores), scores
