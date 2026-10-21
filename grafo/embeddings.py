"""Embeddings locales (sentence-transformers, multilingual-e5-small) para no gastar tokens."""
from __future__ import annotations

import logging
import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

log = logging.getLogger("embeddings")


@lru_cache(maxsize=1)
def modelo():
    from sentence_transformers import SentenceTransformer

    log.info("Cargando modelo de embeddings %s", config.EMBED_MODEL)
    return SentenceTransformer(config.EMBED_MODEL)


def limpiar(texto: str) -> str:
    """Quita las líneas que solo tienen números (columnas de gráficos) para que el vector refleje el texto."""
    lineas = [l for l in texto.splitlines() if not re.fullmatch(r"[\s\d.,%#/\-–*]*", l)]
    return " ".join(" ".join(lineas).split())[:2000]


def pasajes(textos: list[str], lote: int = 32) -> list[list[float]]:
    # e5 requiere el prefijo "passage: " para documentos y "query: " para consultas
    vecs = modelo().encode([f"passage: {limpiar(t)}" for t in textos], batch_size=lote,
                           normalize_embeddings=True, show_progress_bar=len(textos) > 200)
    return [v.tolist() for v in vecs]


def consulta(texto: str) -> list[float]:
    return modelo().encode(f"query: {texto}", normalize_embeddings=True).tolist()
