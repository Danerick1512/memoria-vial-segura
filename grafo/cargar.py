"""Carga idempotente (MERGE) del grafo de Memoria Vial Segura en Neo4j.

Capas: Distrito, Sectores, Tramos, PuntosInteres, Modalidades ICCS, Medios, Intervenciones
y la capa de contexto (Documento -> Pagina con embeddings, FilaTabla de Los Olivos).
Los Reportes -> Incidentes los carga el flujo diario con `cargar_incidentes`.
Ejecutar dos veces no duplica nada.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from grafo.conexion import en_lotes, escribir, leer  # noqa: E402
from ontologia.catalogos import MEDIOS, MODALIDAD  # noqa: E402

log = logging.getLogger("grafo.cargar")


def aplicar_esquema() -> None:
    texto = (Path(__file__).with_name("esquema.cypher")).read_text(encoding="utf-8")
    sentencias = [s.strip() for s in re.sub(r"//.*", "", texto).split(";") if s.strip()]
    for s in sentencias:
        escribir(s)
    log.info("Esquema aplicado (%d sentencias)", len(sentencias))


def cargar_distrito_y_sectores() -> None:
    sectores = json.loads((config.GEO / "sectores.json").read_text(encoding="utf-8"))
    escribir("""MERGE (d:Distrito {ubigeo: $ubigeo}) SET d.nombre = $nombre, d.osm_relacion = $rel
                WITH d UNWIND $sectores AS s
                MERGE (x:Sector {id: s.id})
                SET x.nombre = s.nombre, x.centro = point({latitude: s.lat, longitude: s.lon}),
                    x.supuesto = 'Sector ficticio: k-means (k=7) sobre centroides de tramos'
                MERGE (d)-[:CONTIENE]->(x)""",
             ubigeo=config.DISTRITO_UBIGEO, nombre=config.DISTRITO_NOMBRE, rel=config.OSM_RELACION_LOS_OLIVOS, sectores=sectores)


def cargar_tramos() -> None:
    feats = json.loads((config.GEO / "tramos.geojson").read_text(encoding="utf-8"))["features"]
    filas = [f["properties"] for f in feats]
    en_lotes("""UNWIND $filas AS t
                MERGE (x:Tramo {id: t.id})
                SET x.via = t.via, x.via_id = t.via_id, x.cuadra = t.cuadra, x.highway = t.highway,
                    x.longitud_m = t.longitud_m, x.geom_wkt = t.geom_wkt,
                    x.ubicacion = point({latitude: t.lat, longitude: t.lon})
                WITH x, t MATCH (s:Sector {id: t.sector})
                MERGE (x)-[:CUBIERTO_POR]->(s)""", filas)
    log.info("Tramos: %d", len(filas))


def cargar_pois() -> None:
    pois = [dict(p["properties"], lon=p["geometry"]["coordinates"][0], lat=p["geometry"]["coordinates"][1])
            for p in json.loads((config.GEO / "pois.geojson").read_text(encoding="utf-8"))["features"]]
    en_lotes("""UNWIND $filas AS p
                MERGE (x:PuntoInteres {osm_id: p.osm_id})
                SET x.tipo = p.tipo, x.nombre = p.nombre, x.ubicacion = point({latitude: p.lat, longitude: p.lon}),
                    x.geom_wkt = 'POINT (' + toString(p.lon) + ' ' + toString(p.lat) + ')'""", pois)
    with open(config.GEO / "cerca_de.csv", encoding="utf-8") as f:
        cerca = [dict(r, distancia_m=float(r["distancia_m"])) for r in csv.DictReader(f)]
    en_lotes("""UNWIND $filas AS c
                MATCH (t:Tramo {id: c.tramo_id}) MATCH (p:PuntoInteres {osm_id: c.osm_id})
                MERGE (t)-[r:CERCA_DE]->(p) SET r.distancia_m = c.distancia_m""", cerca, tam=1000)
    log.info("PuntosInteres: %d | CERCA_DE: %d", len(pois), len(cerca))


def cargar_catalogos() -> None:
    escribir("""UNWIND $mods AS m MERGE (x:Modalidad {id: m.id})
                SET x.nombre = m.nombre, x.codigo_iccs = m.codigo_iccs, x.iccs_etiqueta = m.iccs_etiqueta""",
             mods=list(MODALIDAD.values()))
    escribir("UNWIND $medios AS n MERGE (:Medio {nombre: n})", medios=MEDIOS)


def cargar_intervenciones() -> None:
    with open(config.INTERVENCIONES_CSV, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    escribir("""UNWIND $filas AS i
                MERGE (f:Fuente {id: i.fuente})
                SET f.tipo = 'sintetico', f.descripcion = 'Plan operativo simulado de la Gerencia de Seguridad Ciudadana'
                MERGE (x:Intervencion {id: i.id})
                SET x.tipo = i.tipo, x.fecha_inicio = date(i.fecha_inicio), x.fecha_fin = date(i.fecha_fin), x.origen = 'sintetico'
                WITH x, f, i MATCH (t:Tramo {id: i.tramo_id})
                MERGE (x)-[:APLICADA_EN]->(t)
                MERGE (x)-[:DERIVADO_DE]->(f)""", filas=filas)
    log.info("Intervenciones: %d", len(filas))


# --- Capa de contexto estadístico -------------------------------------------------------------
def _titulo(archivo: str) -> str:
    base = Path(archivo.replace("\\", "/")).stem
    base = re.sub(r"^\d+-(\d+-)?", "", base)
    return re.sub(r"[-_]+", " ", base).strip().capitalize()


def cita_documento(doc_id: str, categoria: str) -> str:
    """'inei-7278873-informe-...' -> 'INEI-7278873'; congreso: 'CONGRESO-ABR-25-LIMA'."""
    resto = doc_id[len(categoria) + 1:] if doc_id.startswith(categoria + "-") else doc_id
    tokens = resto.split("-")
    if tokens[0].isdigit():
        return f"{categoria.upper()}-{tokens[0]}"
    lugar = next((t for t in tokens if t in ("lima", "callao")), "")
    return f"{categoria.upper()}-{'-'.join(tokens[:2]).upper()}{'-' + lugar.upper() if lugar else ''}"


def asignar_citas(docs: list[dict]) -> None:
    vistas: dict[str, int] = {}
    for d in sorted(docs, key=lambda d: d["doc_id"]):
        base = cita_documento(d["doc_id"], d["categoria"])
        vistas[base] = vistas.get(base, 0) + 1
        d["cita"] = base if vistas[base] == 1 else f"{base}-{vistas[base]}"


def _menciona_contexto(texto: str) -> bool:
    return bool(re.search(r"los olivos|lima metropolitana", texto, re.I))


def cargar_documentos(solo_relevantes: bool = False) -> None:
    from grafo.embeddings import pasajes

    with open(config.INVENTARIO_CSV, encoding="utf-8-sig") as f:
        inventario = {r["doc_id"]: r for r in csv.DictReader(f)}
    docs = [{"doc_id": k, "categoria": r["categoria"], "url": r["fuente"],
             "archivo": Path(r["archivo"].replace("\\", "/")).as_posix(), "titulo": _titulo(r["archivo"]),
             "paginas": int(r["paginas"] or 0)} for k, r in inventario.items()]
    asignar_citas(docs)
    escribir("""UNWIND $docs AS d MERGE (x:Documento {doc_id: d.doc_id})
                SET x.categoria = d.categoria, x.url = d.url, x.titulo = d.titulo, x.archivo = d.archivo, x.cita = d.cita,
                    x.n_paginas = d.paginas, x.tipo = 'oficial'""", docs=docs)

    paginas = []
    with open(config.PAGINAS_JSONL, encoding="utf-8") as f:
        for linea in f:
            p = json.loads(linea)
            relevante = _menciona_contexto(p["texto"])
            if solo_relevantes and not relevante:
                continue
            paginas.append({"id": f"{p['doc_id']}#p{p['pagina']}", "doc_id": p["doc_id"], "pagina": p["pagina"],
                            "texto": p["texto"], "menciona_los_olivos": "olivos" in p["texto"].lower(), "relevante": relevante})
    ya = {r["id"] for r in leer("MATCH (p:Pagina) WHERE p.embedding IS NOT NULL RETURN p.id AS id")}
    pendientes = [p for p in paginas if p["id"] not in ya]
    # Prioriza las páginas que mencionan Lima Metropolitana o Los Olivos
    pendientes.sort(key=lambda p: (not p["menciona_los_olivos"], not p["relevante"]))
    log.info("Páginas: %d (%d sin embedding)", len(paginas), len(pendientes))
    for i in range(0, len(pendientes), 128):
        lote = pendientes[i:i + 128]
        for p, v in zip(lote, pasajes([p["texto"] for p in lote])):
            p["embedding"] = v
        en_lotes("""UNWIND $filas AS p
                    MATCH (d:Documento {doc_id: p.doc_id})
                    MERGE (x:Pagina {id: p.id})
                    SET x.doc_id = p.doc_id, x.pagina = p.pagina, x.texto = p.texto,
                        x.menciona_los_olivos = p.menciona_los_olivos, x.embedding = p.embedding
                    MERGE (d)-[:TIENE_PAGINA]->(x)""", lote, tam=128)
        log.info("  embeddings %d/%d", min(i + 128, len(pendientes)), len(pendientes))


def cargar_filas_tabla() -> None:
    """Filas de tripletas_extraidas.json (pieza 3) que mencionan Los Olivos, ligadas a su página."""
    if not config.TRIPLETAS_JSON.exists():
        log.warning("No existe %s; se omite la capa de tablas", config.TRIPLETAS_JSON)
        return
    filas = []
    for r in json.loads(config.TRIPLETAS_JSON.read_text(encoding="utf-8")):
        contenido = {k: v for k, v in r["contenido"].items() if v is not None}
        texto = json.dumps(contenido, ensure_ascii=False)
        if "olivos" not in texto.lower() or len(contenido) < 2:
            continue  # filas vacías o cabeceras repetidas
        m = re.match(r"(.+)_p(\d+)_t(\d+)\.csv$", r["documento_fuente"])
        if not m:
            continue
        filas.append({"id": f"{r['documento_fuente']}#f{r['fila']}", "doc_id": m.group(1), "pagina": int(m.group(2)),
                      "tabla": int(m.group(3)), "fila": r["fila"], "contenido": texto})
    en_lotes("""UNWIND $filas AS f
                MERGE (x:FilaTabla {id: f.id})
                SET x.doc_id = f.doc_id, x.pagina = f.pagina, x.tabla = f.tabla, x.fila = f.fila, x.contenido = f.contenido
                WITH x, f MATCH (p:Pagina {id: f.doc_id + '#p' + toString(f.pagina)})
                MERGE (x)-[:EXTRAIDA_DE]->(p)""", filas)
    log.info("Filas de tabla con Los Olivos: %d", len(filas))


# --- Reportes -> Incidentes (usado por el flujo diario) --------------------------------------
CYPHER_INCIDENTES = """
UNWIND $filas AS r
MERGE (f:Fuente:Reporte {id: r.id})
SET f.tipo = r.tipo, f.canal = r.canal, f.fecha_ingreso = date(r.fecha_ingreso), f.texto = r.texto,
    f.embedding = r.embedding
MERGE (i:Incidente {id: r.incidente_id})
SET i.fecha = date(r.fecha), i.hora = r.hora, i.franja = r.franja, i.dia_semana = r.dia_semana,
    i.descripcion_resumen = r.resumen, i.tipo = r.tipo, i.tramo_resuelto = r.tramo_resuelto,
    i.metodo_pln = r.metodo, i.via_texto = r.via, i.cuadra_texto = r.cuadra
MERGE (i)-[:REGISTRADO_EN]->(f)
MERGE (i)-[:DERIVADO_DE]->(f)
WITH i, r
// Las relaciones derivadas del PLN se rehacen para que una re-ejecución corrija sin duplicar
OPTIONAL MATCH (i)-[old:TIPO|USA|OCURRE_EN]->()
DELETE old
WITH DISTINCT i, r
CALL (i, r) { MATCH (m:Modalidad {id: r.modalidad}) MERGE (i)-[:TIPO]->(m) }
CALL (i, r) { MATCH (m:Medio {nombre: r.medio}) MERGE (i)-[:USA]->(m) }
CALL (i, r) { MATCH (t:Tramo {id: r.tramo_id}) MERGE (i)-[:OCURRE_EN]->(t) }
"""


def cargar_incidentes(filas: list[dict]) -> None:
    en_lotes(CYPHER_INCIDENTES, filas, tam=200)


def cargar_base(con_documentos: bool = True, solo_relevantes: bool = False) -> None:
    aplicar_esquema()
    cargar_distrito_y_sectores()
    cargar_tramos()
    cargar_pois()
    cargar_catalogos()
    cargar_intervenciones()
    if con_documentos:
        cargar_documentos(solo_relevantes)
        cargar_filas_tabla()


def conteos() -> dict:
    return {r["etiqueta"]: r["n"] for r in leer(
        "MATCH (n) UNWIND labels(n) AS etiqueta RETURN etiqueta, count(*) AS n ORDER BY etiqueta")}


if __name__ == "__main__":
    config.configurar_logging()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sin-documentos", action="store_true", help="omite la capa de contexto (más rápido)")
    ap.add_argument("--solo-relevantes", action="store_true", help="solo páginas que mencionan Lima Metropolitana o Los Olivos")
    a = ap.parse_args()
    cargar_base(not a.sin_documentos, a.solo_relevantes)
    log.info("Conteos: %s", conteos())
