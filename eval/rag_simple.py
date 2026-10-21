"""Línea base: RAG vectorial simple (solo embeddings de reportes, sin grafo).

Recupera los k relatos más parecidos a la pregunta y "lee" esos relatos (con el mismo
extractor PLN) para armar una respuesta. No tiene acceso a OCURRE_EN, CERCA_DE,
intervenciones ni a la historia completa: es lo que vería un LLM con esos k fragmentos.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agente.vectorial import buscar_reportes  # noqa: E402
from pln.extraer import ExtractorReglas  # noqa: E402

K = 10


def responder(pregunta: str, ref: date) -> dict:
    filas, _ = buscar_reportes(pregunta, k=K)
    ext = ExtractorReglas(usar_llm=False)
    leidos = [dict(ext.extraer(f["texto"]).model_dump(), reporte=f["reporte"], fecha=f["fecha"]) for f in filas]
    semana = (ref - timedelta(days=6)).isoformat()
    recientes = [l for l in leidos if l["fecha"] >= semana]
    por_tramo = Counter(l["tramo_id"] for l in leidos if l["tramo_id"])
    por_via = Counter(l["via"] for l in leidos if l["via"])
    # Intervenciones: los relatos no mencionan intervenciones ni ventanas temporales -> sin antes/después
    emergentes = sorted({(l["modalidad"], l["via"]) for l in recientes if l["modalidad"] and l["via"]})
    return {"tramos": [t for t, _ in por_tramo.most_common()], "vias": [v for v, _ in por_via.most_common()],
            "intervenciones": {}, "emergentes": emergentes, "citas": [l["reporte"] for l in leidos], "paginas": [],
            "total": None, "tipo": None}
