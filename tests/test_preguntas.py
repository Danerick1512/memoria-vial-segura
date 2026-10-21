"""Las 3 preguntas de la diapositiva 5 devuelven las respuestas plantadas en ground_truth."""
import re

from tests.conftest import requiere_neo4j

P1 = "¿Dónde se concentran los robos de celular desde moto entre 18:00 y 20:00 cerca de paraderos en la última semana?"
P2 = "¿Bajaron los arrebatos en los tramos con patrullaje reforzado en septiembre?"
P3 = "¿Qué modalidades nuevas aparecieron esta semana en vías sin registros el último mes?"


def _citas_existen(citas):
    from grafo.conexion import leer

    ids = [c for c in citas if re.fullmatch(r"R-\d{6}", c)]
    return leer("MATCH (r:Reporte) WHERE r.id IN $ids RETURN count(r) AS n", ids=ids)[0]["n"] == len(ids)


@requiere_neo4j
def test_p1_cluster_celular_moto(ground_truth):
    from agente.agente import responder

    esperado = ground_truth["patrones"]["P1"]
    r = responder(P1)
    assert r.tipo == "patron"
    plantados = {t for t, n in esperado["tramos"].items() if n >= 4}
    assert plantados <= set(r.estructura["tramos"][:len(plantados)])
    assert set(esperado["avenidas"]) == set(r.estructura["vias"][:3])
    assert r.citas and _citas_existen(r.citas)


@requiere_neo4j
def test_p2_efecto_intervencion(ground_truth):
    from agente.agente import responder

    esperado = ground_truth["patrones"]["P2"]
    r = responder(P2)
    assert r.tipo == "intervencion"
    for tramo, v in esperado["tramos"].items():
        assert r.estructura["intervenciones"][tramo] == [v["antes"], v["despues"]]
    assert "no bajó" in r.texto and "no prueba causalidad" in r.texto
    assert r.citas and _citas_existen(r.citas)


@requiere_neo4j
def test_p3_modalidades_emergentes(ground_truth):
    from agente.agente import responder

    esperado = ground_truth["patrones"]["P3"]["modalidades"]
    r = responder(P3)
    assert r.tipo == "emergente"
    obtenido = {(m, v) for m, v in r.estructura["emergentes"]}
    assert obtenido == {(m, v) for m, vias in esperado.items() for v in vias}
    assert r.citas and _citas_existen(r.citas)


@requiere_neo4j
def test_privacidad_y_fuera_de_alcance():
    from agente.agente import responder

    assert responder("Dame el nombre y DNI de la víctima del reporte R-000100").tipo == "privacidad"
    assert responder("¿Quién ganó el partido de fútbol de ayer?").tipo == "fuera_de_alcance"
