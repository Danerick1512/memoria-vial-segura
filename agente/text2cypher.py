"""Text2Cypher de respaldo para preguntas sin plantilla. SOLO LECTURA, con LIMIT obligatorio.

Tres barreras: (1) regex que rechaza cláusulas de escritura y procedimientos, (2) LIMIT forzado,
(3) ejecución en transacción de solo lectura (Neo4j rechaza cualquier escritura).
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
from grafo.conexion import leer  # noqa: E402

log = logging.getLogger("agente.t2c")

LIMITE_MAX = 200
RE_ESCRITURA = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|GRANT|REVOKE|ALTER|RENAME|TERMINATE)\b", re.I)
RE_CALL = re.compile(r"\bCALL\b", re.I)
RE_CALL_PERMITIDO = re.compile(r"\bCALL\s+db\.index\.vector\.queryNodes\s*\(", re.I)


class CypherRechazado(ValueError):
    pass


def _sin_literales(cypher: str) -> str:
    """Quita cadenas y comentarios para que 'set' dentro de un texto no dispare falsos positivos."""
    c = re.sub(r"//.*?$|/\*.*?\*/", " ", cypher, flags=re.S | re.M)
    return re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", c)


def validar(cypher: str) -> str:
    """Devuelve el Cypher seguro (con LIMIT) o lanza CypherRechazado."""
    c = cypher.strip().rstrip(";").strip()
    if not c:
        raise CypherRechazado("Cypher vacío")
    limpio = _sin_literales(c)
    if ";" in limpio:
        raise CypherRechazado("Solo se permite una sentencia")
    m = RE_ESCRITURA.search(limpio)
    if m:
        raise CypherRechazado(f"Cláusula de escritura no permitida: {m.group(1).upper()}")
    if re.search(r"\bapoc\.", limpio, re.I) and RE_CALL.search(limpio):
        raise CypherRechazado("Procedimientos APOC no permitidos")
    llamadas = len(RE_CALL.findall(limpio))
    if llamadas and llamadas != len(RE_CALL_PERMITIDO.findall(limpio)) + len(re.findall(r"\bCALL\s*(\(|\{)", limpio, re.I)):
        raise CypherRechazado("Solo se permite CALL db.index.vector.queryNodes o subconsultas de lectura")
    if not re.search(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|CALL|RETURN)\b", limpio, re.I):
        raise CypherRechazado("La consulta debe empezar con MATCH/WITH/UNWIND/CALL/RETURN")
    lim = re.search(r"\bLIMIT\s+(\d+)\s*$", limpio, re.I)
    if lim is None:
        c = f"{c}\nLIMIT 50"
    elif int(lim.group(1)) > LIMITE_MAX:
        c = re.sub(r"\bLIMIT\s+\d+\s*$", f"LIMIT {LIMITE_MAX}", c, flags=re.I)
    return c


ESQUEMA = """Grafo Neo4j (Los Olivos, Lima). Nodos y propiedades:
(:Incidente {id, fecha: date, hora: 'HH:MM', franja: 'madrugada'|'mañana'|'tarde'|'noche', dia_semana, descripcion_resumen, tramo_resuelto})
(:Reporte:Fuente {id: 'R-000123', tipo: 'sintetico', canal, fecha_ingreso: date, texto})
(:Modalidad {id, nombre, codigo_iccs})  ids: robo_celular, arrebato_cartera, cogoteo, tentativa_robo, robo_vehiculo,
   hurto_autopartes, robo_negocio, extorsion, amenazas, acoso_sexual, estafa_paso, bujiazo, marcaje
(:Medio {nombre})  'moto','a pie','auto','mototaxi','bicicleta'
(:Tramo {id: 'AV_UNIVERSITARIA_C08', via: 'Avenida Universitaria', cuadra: int, geom_wkt, ubicacion: point})
(:PuntoInteres {osm_id, tipo: 'paradero'|'mercado'|'colegio'|'parque'|'banco', nombre})
(:Sector {id: 'S1'..'S7', nombre}), (:Distrito {ubigeo, nombre})
(:Intervencion {id, tipo: 'patrullaje reforzado'|'mejora de iluminación', fecha_inicio: date, fecha_fin: date})
(:Documento {doc_id, cita, titulo, url}), (:Pagina {doc_id, pagina, texto}), (:Corrida {fecha, n_reportes, n_ok, n_sin_tramo})
Relaciones:
(Incidente)-[:REGISTRADO_EN]->(Reporte), (Incidente)-[:DERIVADO_DE]->(Fuente), (Incidente)-[:TIPO]->(Modalidad),
(Incidente)-[:USA]->(Medio), (Incidente)-[:OCURRE_EN]->(Tramo), (Tramo)-[:CERCA_DE {distancia_m}]->(PuntoInteres),
(Tramo)-[:CUBIERTO_POR]->(Sector), (Distrito)-[:CONTIENE]->(Sector), (Intervencion)-[:APLICADA_EN]->(Tramo),
(Documento)-[:TIENE_PAGINA]->(Pagina)"""

SISTEMA = f"""Traduces preguntas en español a UNA consulta Cypher de SOLO LECTURA para Neo4j 5.
{ESQUEMA}
Reglas: nunca CREATE/MERGE/DELETE/SET/REMOVE/DROP; termina con LIMIT; usa date('AAAA-MM-DD') para fechas;
devuelve SIEMPRE los ids de reporte (r.id) que respaldan el resultado para poder citarlos.
Responde solo con el Cypher, sin explicación ni bloque de código."""


def generar_y_ejecutar(pregunta: str, intentos: int = 2) -> tuple[list[dict], str]:
    """Genera Cypher con el LLM, lo valida y lo ejecuta; reintenta con el error si falla."""
    proveedor = llm.obtener()
    if proveedor is None:
        raise RuntimeError("Text2Cypher requiere un LLM (configura ANTHROPIC_API_KEY)")
    mensaje, ultimo_error = pregunta, None
    for _ in range(intentos):
        texto = proveedor.completar(SISTEMA, mensaje, max_tokens=800)
        cypher = re.sub(r"^```\w*|```$", "", texto.strip(), flags=re.M).strip()
        try:
            seguro = validar(cypher)
            return leer(seguro), seguro
        except CypherRechazado as e:
            ultimo_error = f"Consulta rechazada por seguridad: {e}"
        except Exception as e:  # error de sintaxis o de ejecución en Neo4j
            ultimo_error = f"Neo4j devolvió error: {e}"
        log.warning("Text2Cypher: %s", ultimo_error)
        mensaje = f"{pregunta}\n\nTu consulta anterior:\n{cypher}\n{ultimo_error}\nCorrígela."
    raise RuntimeError(ultimo_error or "No se pudo generar Cypher")
