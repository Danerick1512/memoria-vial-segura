"""Fixtures comunes. Las pruebas que usan Neo4j se omiten si la base no responde."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def _neo4j_disponible() -> bool:
    try:
        from grafo.conexion import driver

        driver()
        return True
    except Exception:
        return False


requiere_neo4j = pytest.mark.skipif(not _neo4j_disponible(), reason="Neo4j no disponible (docker compose up -d)")


@pytest.fixture(scope="session")
def ground_truth() -> dict:
    return json.loads(config.GROUND_TRUTH.read_text(encoding="utf-8"))
