"""Correr la carga y el flujo dos veces no duplica nodos ni relaciones."""
from datetime import date

from tests.conftest import requiere_neo4j


def _conteos():
    from grafo.conexion import leer

    nodos = {r["e"]: r["n"] for r in leer("MATCH (n) UNWIND labels(n) AS e RETURN e, count(*) AS n")}
    rels = {r["t"]: r["n"] for r in leer("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n")}
    return nodos, rels


@requiere_neo4j
def test_carga_base_idempotente():
    from grafo.cargar import cargar_base

    cargar_base(con_documentos=False)
    primero = _conteos()
    cargar_base(con_documentos=False)
    assert _conteos() == primero


@requiere_neo4j
def test_flujo_diario_idempotente():
    from flujo.run_daily import procesar_dia

    dia = date(2026, 10, 15)
    procesar_dia(dia, con_boletin=False)
    primero = _conteos()
    procesar_dia(dia, con_boletin=False)
    assert _conteos() == primero
