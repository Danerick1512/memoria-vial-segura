"""Consultas Cypher plantilla y parametrizadas (más confiables que el texto libre).

Cada función devuelve (filas, cypher, parametros) para mostrar el Cypher ejecutado en la UI.
Las usan el agente, el boletín y el dashboard.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grafo.conexion import leer  # noqa: E402
from ontologia.catalogos import ARREBATOS  # noqa: E402

Resultado = tuple[list[dict], str, dict]


def _ejecutar(cypher: str, **params) -> Resultado:
    return leer(cypher, **params), cypher.strip(), params


def fecha_referencia() -> date:
    """Último día con incidentes cargados (el 'hoy' del grafo)."""
    r = leer("MATCH (i:Incidente) RETURN max(i.fecha) AS f")
    f = r[0]["f"] if r else None
    return f.to_native() if f else date.today()


def ultima_semana(ref: date | None = None) -> tuple[str, str]:
    ref = ref or fecha_referencia()
    return (ref - timedelta(days=6)).isoformat(), ref.isoformat()


# --- Pregunta 1: patrón de incidentes ---------------------------------------------------------
CYPHER_PATRON = """
MATCH (i:Incidente)-[:OCURRE_EN]->(t:Tramo)
WHERE i.fecha >= date($desde) AND i.fecha <= date($hasta)
  AND ($modalidad IS NULL OR EXISTS { (i)-[:TIPO]->(:Modalidad {id: $modalidad}) })
  AND ($medio IS NULL OR EXISTS { (i)-[:USA]->(:Medio {nombre: $medio}) })
  AND ($iccs IS NULL OR EXISTS { (i)-[:TIPO]->(mx:Modalidad) WHERE mx.codigo_iccs STARTS WITH $iccs })
  AND ($hora_desde IS NULL OR i.hora >= $hora_desde)
  AND ($hora_hasta IS NULL OR i.hora < $hora_hasta)
  AND ($poi_tipo IS NULL OR EXISTS { (t)-[:CERCA_DE]->(:PuntoInteres {tipo: $poi_tipo}) })
  AND ($sector IS NULL OR EXISTS { (t)-[:CUBIERTO_POR]->(:Sector {id: $sector}) })
MATCH (i)-[:REGISTRADO_EN]->(r:Reporte)
WITH t, collect(DISTINCT r.id) AS reportes, collect(DISTINCT i.hora) AS horas
OPTIONAL MATCH (t)-[c:CERCA_DE]->(p:PuntoInteres)
WHERE $poi_tipo IS NULL OR p.tipo = $poi_tipo
WITH t, reportes, horas, c, p ORDER BY c.distancia_m
WITH t, reportes, horas, collect(p.tipo + ': ' + p.nombre)[0] AS poi_cercano, min(c.distancia_m) AS distancia_m
OPTIONAL MATCH (t)-[:CUBIERTO_POR]->(s:Sector)
RETURN t.id AS tramo, t.via AS via, t.cuadra AS cuadra, s.id AS sector, size(reportes) AS incidentes,
       reportes, horas, poi_cercano, distancia_m, t.ubicacion.latitude AS lat, t.ubicacion.longitude AS lon
ORDER BY incidentes DESC, tramo
LIMIT $limite
"""


def patron(desde: str, hasta: str, modalidad: str | None = None, medio: str | None = None,
           hora_desde: str | None = None, hora_hasta: str | None = None, poi_tipo: str | None = None,
           sector: str | None = None, iccs: str | None = None, limite: int = 15) -> Resultado:
    return _ejecutar(CYPHER_PATRON, desde=desde, hasta=hasta, modalidad=modalidad, medio=medio, hora_desde=hora_desde,
                     hora_hasta=hora_hasta, poi_tipo=poi_tipo, sector=sector, iccs=iccs, limite=limite)


# --- Pregunta 2: efecto de una intervención ---------------------------------------------------
CYPHER_INTERVENCION = """
MATCH (iv:Intervencion)-[:APLICADA_EN]->(t:Tramo)
WHERE ($tipo IS NULL OR iv.tipo = $tipo)
  AND ($desde IS NULL OR iv.fecha_inicio >= date($desde))
  AND ($hasta IS NULL OR iv.fecha_inicio <= date($hasta))
  AND ($via IS NULL OR t.via = $via)
OPTIONAL MATCH (iv)-[:DERIVADO_DE]->(f:Fuente)
WITH iv, t, f, iv.fecha_inicio - duration({days: 7 * $semanas}) AS ini_antes,
     iv.fecha_inicio + duration({days: 7 * $semanas - 1}) AS fin_despues
OPTIONAL MATCH (i:Incidente)-[:OCURRE_EN]->(t)
WHERE i.fecha >= ini_antes AND i.fecha <= fin_despues
  AND EXISTS { (i)-[:TIPO]->(m:Modalidad) WHERE m.id IN $modalidades }
OPTIONAL MATCH (i)-[:REGISTRADO_EN]->(r:Reporte)
WITH iv, t, f, ini_antes, fin_despues,
     collect(CASE WHEN i.fecha < iv.fecha_inicio THEN r.id END) AS reportes_antes,
     collect(CASE WHEN i.fecha >= iv.fecha_inicio THEN r.id END) AS reportes_despues
RETURN iv.id AS intervencion, iv.tipo AS tipo, toString(iv.fecha_inicio) AS inicio, toString(iv.fecha_fin) AS fin,
       f.id AS fuente, t.id AS tramo, t.via AS via, t.cuadra AS cuadra,
       toString(ini_antes) AS ventana_antes_desde, toString(fin_despues) AS ventana_despues_hasta,
       size(reportes_antes) AS antes, size(reportes_despues) AS despues, reportes_antes, reportes_despues,
       t.ubicacion.latitude AS lat, t.ubicacion.longitude AS lon
ORDER BY via, cuadra
LIMIT $limite
"""


def efecto_intervencion(tipo: str | None = "patrullaje reforzado", desde: str | None = None, hasta: str | None = None,
                        via: str | None = None, modalidades: list[str] | None = None, semanas: int = 4,
                        limite: int = 50) -> Resultado:
    filas, cy, params = _ejecutar(CYPHER_INTERVENCION, tipo=tipo, desde=desde, hasta=hasta, via=via,
                                  modalidades=modalidades or ARREBATOS, semanas=semanas, limite=limite)
    for f in filas:
        f["variacion_pct"] = round(100 * (f["despues"] - f["antes"]) / f["antes"], 1) if f["antes"] else None
    return filas, cy, params


# --- Pregunta 3: modalidades emergentes -------------------------------------------------------
CYPHER_EMERGENTES = """
MATCH (i:Incidente)-[:TIPO]->(m:Modalidad), (i)-[:OCURRE_EN]->(t:Tramo), (i)-[:REGISTRADO_EN]->(r:Reporte)
WHERE i.fecha >= date($desde) AND i.fecha <= date($hasta)
WITH m, t.via AS via, collect(DISTINCT r.id) AS reportes, collect(DISTINCT t.id) AS tramos
WITH m, via, reportes, tramos,
     COUNT { MATCH (j:Incidente)-[:TIPO]->(m)
             WHERE j.fecha >= date($desde) - duration({days: $dias_previos}) AND j.fecha < date($desde) } AS previos_modalidad,
     COUNT { MATCH (j:Incidente)-[:OCURRE_EN]->(x:Tramo) WHERE x.via = via
             AND j.fecha >= date($desde) - duration({days: $dias_previos}) AND j.fecha < date($desde) } AS previos_via
WHERE previos_via = 0 AND ($solo_modalidades_nuevas = false OR previos_modalidad = 0)
RETURN m.id AS modalidad, m.nombre AS nombre, m.codigo_iccs AS codigo_iccs, via, size(reportes) AS incidentes,
       reportes, tramos, previos_modalidad, previos_via
ORDER BY previos_modalidad, incidentes DESC, via
LIMIT $limite
"""


def emergentes(desde: str, hasta: str, dias_previos: int = 30, solo_modalidades_nuevas: bool = True,
               limite: int = 25) -> Resultado:
    return _ejecutar(CYPHER_EMERGENTES, desde=desde, hasta=hasta, dias_previos=dias_previos,
                     solo_modalidades_nuevas=solo_modalidades_nuevas, limite=limite)


# --- Conteos genéricos (preguntas nuevas sin LLM) -------------------------------------------------
CYPHER_CONTEO = """
MATCH (i:Incidente)-[:REGISTRADO_EN]->(r:Reporte)
WHERE i.fecha >= date($desde) AND i.fecha <= date($hasta)
  AND ($modalidad IS NULL OR EXISTS { (i)-[:TIPO]->(:Modalidad {id: $modalidad}) })
  AND ($medio IS NULL OR EXISTS { (i)-[:USA]->(:Medio {nombre: $medio}) })
  AND ($iccs IS NULL OR EXISTS { (i)-[:TIPO]->(mx:Modalidad) WHERE mx.codigo_iccs STARTS WITH $iccs })
  AND ($franja IS NULL OR i.franja = $franja)
  AND ($sector IS NULL OR EXISTS { (i)-[:OCURRE_EN]->(:Tramo)-[:CUBIERTO_POR]->(:Sector {id: $sector}) })
  AND ($via IS NULL OR EXISTS { (i)-[:OCURRE_EN]->(:Tramo {via: $via}) })
OPTIONAL MATCH (i)-[:TIPO]->(m:Modalidad)
RETURN coalesce(m.nombre, 'sin modalidad') AS modalidad, count(*) AS incidentes, collect(r.id)[..10] AS reportes
ORDER BY incidentes DESC
LIMIT $limite
"""


def conteo(desde: str, hasta: str, modalidad=None, medio=None, franja=None, sector=None, via=None, iccs=None,
           limite: int = 20) -> Resultado:
    return _ejecutar(CYPHER_CONTEO, desde=desde, hasta=hasta, modalidad=modalidad, medio=medio, franja=franja,
                     sector=sector, via=via, iccs=iccs, limite=limite)


# --- Boletín: tramos calientes por franja -----------------------------------------------------------
CYPHER_CALIENTES = """
MATCH (i:Incidente)-[:OCURRE_EN]->(t:Tramo), (i)-[:REGISTRADO_EN]->(r:Reporte)
WHERE i.fecha > date($fecha) - duration({days: $dias}) AND i.fecha <= date($fecha)
OPTIONAL MATCH (i)-[:TIPO]->(m:Modalidad)
WITH i.franja AS franja, t, collect(r.id) AS reportes, collect(DISTINCT m.nombre) AS modalidades
OPTIONAL MATCH (t)-[:CUBIERTO_POR]->(s:Sector)
WITH franja, t, s, reportes, modalidades ORDER BY size(reportes) DESC, t.id
WITH franja, collect({tramo: t.id, via: t.via, cuadra: t.cuadra, sector: s.id, incidentes: size(reportes),
                      reportes: reportes, modalidades: modalidades})[..$top] AS top
RETURN franja, top
"""


def tramos_calientes(fecha: str, dias: int = 3, top: int = 5) -> Resultado:
    return _ejecutar(CYPHER_CALIENTES, fecha=fecha, dias=dias, top=top)


# --- Dashboard ---------------------------------------------------------------------------------
def serie_diaria() -> list[dict]:
    return leer("""MATCH (i:Incidente) OPTIONAL MATCH (i)-[:TIPO]->(m:Modalidad)
                   RETURN toString(i.fecha) AS fecha, coalesce(m.nombre, 'sin modalidad') AS modalidad, count(*) AS n
                   ORDER BY fecha""")


def franja_por_dia() -> list[dict]:
    return leer("MATCH (i:Incidente) RETURN i.franja AS franja, i.dia_semana AS dia, count(*) AS n")


def calidad_pln() -> list[dict]:
    return leer("""MATCH (c:Corrida) RETURN toString(c.fecha) AS fecha, c.n_reportes AS n_reportes, c.n_ok AS n_ok,
                   c.n_sin_tramo AS n_sin_tramo ORDER BY fecha""")


def incidentes_mapa(desde: str, hasta: str, modalidad=None, medio=None, franja=None) -> list[dict]:
    return leer("""MATCH (i:Incidente)-[:OCURRE_EN]->(t:Tramo)
                   WHERE i.fecha >= date($desde) AND i.fecha <= date($hasta)
                     AND ($modalidad IS NULL OR EXISTS { (i)-[:TIPO]->(:Modalidad {id: $modalidad}) })
                     AND ($medio IS NULL OR EXISTS { (i)-[:USA]->(:Medio {nombre: $medio}) })
                     AND ($franja IS NULL OR i.franja = $franja)
                   MATCH (i)-[:REGISTRADO_EN]->(r:Reporte)
                   RETURN t.id AS tramo, t.via AS via, t.cuadra AS cuadra, t.geom_wkt AS wkt, count(i) AS n,
                          collect(r.id)[..8] AS reportes""",
                desde=desde, hasta=hasta, modalidad=modalidad, medio=medio, franja=franja)


# --- Trazabilidad (PROV-O) ------------------------------------------------------------------------
def reporte(rid: str) -> dict | None:
    r = leer("""MATCH (f:Reporte {id: $id})<-[:REGISTRADO_EN]-(i:Incidente)
                OPTIONAL MATCH (i)-[:TIPO]->(m:Modalidad) OPTIONAL MATCH (i)-[:USA]->(me:Medio)
                OPTIONAL MATCH (i)-[:OCURRE_EN]->(t:Tramo) OPTIONAL MATCH (t)-[:CUBIERTO_POR]->(s:Sector)
                RETURN f.id AS id, f.tipo AS tipo, f.canal AS canal, toString(f.fecha_ingreso) AS fecha_ingreso, f.texto AS texto,
                       i.id AS incidente, toString(i.fecha) AS fecha, i.hora AS hora, i.franja AS franja,
                       i.descripcion_resumen AS resumen, m.nombre AS modalidad, m.codigo_iccs AS iccs, me.nombre AS medio,
                       t.id AS tramo, t.via AS via, t.cuadra AS cuadra, s.nombre AS sector""", id=rid)
    return r[0] if r else None


def pagina(cita: str, num: int) -> dict | None:
    r = leer("""MATCH (d:Documento {cita: $cita})-[:TIENE_PAGINA]->(p:Pagina {pagina: $num})
                RETURN d.cita AS cita, d.titulo AS titulo, d.url AS url, d.categoria AS categoria, p.pagina AS pagina, p.texto AS texto""",
             cita=cita, num=num)
    return r[0] if r else None
