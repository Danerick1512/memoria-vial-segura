"""Conexión a Neo4j (driver único) y utilidades de lectura/escritura."""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path

from neo4j import GraphDatabase, READ_ACCESS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

log = logging.getLogger("grafo")


@lru_cache(maxsize=1)
def driver():
    d = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    d.verify_connectivity()
    return d


def escribir(cypher: str, **params) -> list[dict]:
    with driver().session() as s:
        return s.execute_write(lambda tx: [r.data() for r in tx.run(cypher, **params)])


def leer(cypher: str, **params) -> list[dict]:
    """Ejecuta en una transacción de SOLO LECTURA (Neo4j rechaza cualquier escritura)."""
    with driver().session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(cypher, **params)])


def en_lotes(cypher: str, filas: list[dict], tam: int = 500) -> None:
    for i in range(0, len(filas), tam):
        escribir(cypher, filas=filas[i:i + tam])
