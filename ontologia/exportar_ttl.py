"""Exporta la ontología a OWL/Turtle (ontologia/memoria_vial.ttl), coherente con las etiquetas del grafo.

Alineaciones: PROV-O (prov:Entity, prov:wasDerivedFrom), GeoSPARQL (geo:Feature, geo:hasGeometry,
geo:asWKT) y SKOS para el esquema de modalidades mapeado a ICCS (UNODC).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ontologia.catalogos import MEDIOS, MODALIDADES  # noqa: E402

CABECERA = """@prefix mv:   <https://memoriavial.pe/ontologia#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct:  <http://purl.org/dc/terms/> .

<https://memoriavial.pe/ontologia> a owl:Ontology ;
    rdfs:label "Memoria Vial Segura — ontología de incidentes a nivel de calle (Los Olivos)"@es ;
    dct:description "Ontología del prototipo TRL 4. Cada clase corresponde a una etiqueta del grafo Neo4j; cada propiedad de objeto a un tipo de relación."@es ;
    owl:imports <http://www.w3.org/ns/prov-o>, <http://www.opengis.net/ont/geosparql> .
"""

# (clase = etiqueta Neo4j, superclase, comentario)
CLASES = [
    ("Incidente", "prov:Entity", "Hecho delictivo ocurrido en un tramo, en fecha, hora y franja determinadas."),
    ("Fuente", "prov:Entity", "Origen de un dato: reporte, parte o plan operativo."),
    ("Reporte", "mv:Fuente", "Relato de serenazgo/PNP (tipo: sintetico | serenazgo | parte)."),
    ("Modalidad", "skos:Concept", "Modalidad delictiva local mapeada a un código ICCS de UNODC."),
    ("Medio", "skos:Concept", "Medio usado por los autores (moto, a pie, auto...)."),
    ("Tramo", "geo:Feature", "Segmento de vía de ~100 m (≈ cuadra) con geometría WKT."),
    ("PuntoInteres", "geo:Feature", "Paradero, mercado, colegio, parque o banco de OpenStreetMap."),
    ("Sector", "geo:Feature", "Sector de patrullaje (ficticio en el prototipo)."),
    ("Distrito", "geo:Feature", "Distrito (ubigeo INEI)."),
    ("Intervencion", "prov:Activity", "Acción preventiva aplicada en tramos durante un periodo."),
    ("Documento", "prov:Entity", "Publicación oficial (INEI, SIDPOL, Congreso...)."),
    ("Pagina", "prov:Entity", "Página de un documento oficial, unidad de cita."),
    ("FilaTabla", "prov:Entity", "Fila de tabla estadística extraída de una página (pieza 3)."),
    ("Corrida", "prov:Activity", "Ejecución diaria del flujo de ingesta."),
]

# (propiedad = tipo de relación Neo4j, dominio, rango, superpropiedad)
RELACIONES = [
    ("REGISTRADO_EN", "Incidente", "Reporte", None),
    ("TIPO", "Incidente", "Modalidad", None),
    ("USA", "Incidente", "Medio", None),
    ("OCURRE_EN", "Incidente", "Tramo", None),
    ("CERCA_DE", "Tramo", "PuntoInteres", None),
    ("CUBIERTO_POR", "Tramo", "Sector", None),
    ("APLICADA_EN", "Intervencion", "Tramo", None),
    ("DERIVADO_DE", None, "Fuente", "prov:wasDerivedFrom"),
    ("TIENE_PAGINA", "Documento", "Pagina", "dct:hasPart"),
    ("EXTRAIDA_DE", "FilaTabla", "Pagina", "prov:wasDerivedFrom"),
    ("CONTIENE", "Distrito", "Sector", "geo:sfContains"),
]

# (propiedad, dominio, tipo xsd)
ATRIBUTOS = [
    ("id", None, "string"), ("fecha", "Incidente", "date"), ("hora", "Incidente", "string"),
    ("franja", "Incidente", "string"), ("dia_semana", "Incidente", "string"),
    ("descripcion_resumen", "Incidente", "string"), ("tipo", None, "string"), ("fecha_ingreso", "Reporte", "date"),
    ("texto", None, "string"), ("codigo_iccs", "Modalidad", "string"), ("nombre", None, "string"),
    ("via", "Tramo", "string"), ("cuadra", "Tramo", "integer"), ("distancia_m", None, "decimal"),
    ("osm_id", "PuntoInteres", "string"), ("fecha_inicio", "Intervencion", "date"), ("fecha_fin", "Intervencion", "date"),
    ("doc_id", "Documento", "string"), ("url", "Documento", "anyURI"), ("pagina", "Pagina", "integer"),
    ("ubigeo", "Distrito", "string"),
]


def _lit(t: str) -> str:
    return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'


def generar() -> str:
    out = [CABECERA, "\n### Clases (= etiquetas Neo4j)\n"]
    for c, sup, com in CLASES:
        out.append(f"mv:{c} a owl:Class ; rdfs:subClassOf {sup} ;\n    rdfs:label {_lit(c)} ; rdfs:comment {_lit(com)}@es .\n")
    out.append("mv:Incidente owl:disjointWith mv:Intervencion .\n")
    out.append("\n### Propiedades de objeto (= tipos de relación Neo4j)\n")
    for r, dom, ran, sup in RELACIONES:
        partes = [f"mv:{r} a owl:ObjectProperty", f"rdfs:label {_lit(r)}"]
        if dom:
            partes.append(f"rdfs:domain mv:{dom}")
        partes.append(f"rdfs:range mv:{ran}")
        if sup:
            partes.append(f"rdfs:subPropertyOf {sup}")
        out.append(" ;\n    ".join(partes) + " .\n")
    out.append("mv:geom_wkt a owl:DatatypeProperty ; rdfs:subPropertyOf geo:asWKT ; rdfs:range geo:wktLiteral .\n")
    out.append("\n### Propiedades de datos\n")
    for a, dom, xsd in ATRIBUTOS:
        d = f" ; rdfs:domain mv:{dom}" if dom else ""
        out.append(f"mv:{a} a owl:DatatypeProperty{d} ; rdfs:range xsd:{xsd} .\n")
    out.append("\n### Esquema de modalidades (SKOS) con mapeo a ICCS — ver mapeo_iccs.csv\n")
    out.append('mv:EsquemaModalidades a skos:ConceptScheme ; rdfs:label "Modalidades delictivas de calle"@es .\n')
    for mid, nombre, iccs, etiqueta in MODALIDADES:
        out.append(f"mv:mod_{mid} a mv:Modalidad ; skos:inScheme mv:EsquemaModalidades ;\n"
                   f"    skos:prefLabel {_lit(nombre)}@es ; mv:codigo_iccs {_lit(iccs)} ;\n"
                   f"    skos:closeMatch <https://www.unodc.org/iccs/{iccs}> ; rdfs:comment {_lit('ICCS: ' + etiqueta)}@es .\n")
    out.append("\n### Medios\n")
    for m in MEDIOS:
        out.append(f"mv:medio_{m.replace(' ', '_')} a mv:Medio ; skos:prefLabel {_lit(m)}@es .\n")
    return "".join(out)


if __name__ == "__main__":
    destino = Path(__file__).with_name("memoria_vial.ttl")
    destino.write_text(generar(), encoding="utf-8")
    print(f"Ontología exportada -> {destino}")
