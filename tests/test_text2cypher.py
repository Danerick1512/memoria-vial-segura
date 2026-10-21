"""Guardas de solo lectura de Text2Cypher (no requiere Neo4j para las validaciones)."""
import pytest

from agente.text2cypher import CypherRechazado, validar
from tests.conftest import requiere_neo4j

PELIGROSAS = [
    "MATCH (n) DETACH DELETE n",
    "CREATE (:Incidente {id: 'x'})",
    "MATCH (t:Tramo) SET t.via = 'x' RETURN t",
    "MERGE (n:Modalidad {id: 'y'}) RETURN n",
    "MATCH (n) REMOVE n.id RETURN n",
    "DROP INDEX pagina_embedding",
    "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'DETACH DELETE n', {})",
    "CALL dbms.components()",
    "LOAD CSV FROM 'file:///x.csv' AS r RETURN r",
    "MATCH (n) RETURN n; MATCH (m) DETACH DELETE m",
    "MATCH (n) FOREACH (x IN [1] | SET n.a = 1) RETURN n",
    "match (n) detach delete n",
]


@pytest.mark.parametrize("cypher", PELIGROSAS)
def test_rechaza_escrituras(cypher):
    with pytest.raises(CypherRechazado):
        validar(cypher)


def test_agrega_limit_si_falta():
    assert validar("MATCH (i:Incidente) RETURN i.id").rstrip().endswith("LIMIT 50")


def test_recorta_limit_excesivo():
    assert validar("MATCH (i:Incidente) RETURN i.id LIMIT 100000").rstrip().endswith("LIMIT 200")


def test_permite_texto_con_palabras_reservadas_en_literales():
    c = validar("MATCH (r:Reporte) WHERE r.texto CONTAINS 'set de llaves' RETURN r.id LIMIT 5")
    assert "LIMIT 5" in c


def test_permite_busqueda_vectorial():
    validar("CALL db.index.vector.queryNodes('reporte_embedding', 5, $v) YIELD node RETURN node.id LIMIT 5")


@requiere_neo4j
def test_transaccion_de_lectura_bloquea_escritura():
    """Segunda barrera: aunque una escritura pasara el filtro, la sesión READ la rechaza."""
    from grafo.conexion import leer

    with pytest.raises(Exception):
        leer("CREATE (:PruebaEscritura {x: 1})")
    assert leer("MATCH (n:PruebaEscritura) RETURN count(n) AS n")[0]["n"] == 0
