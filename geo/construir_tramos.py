"""Segmenta las vías de OSM en tramos ≈ cuadras, calcula CERCA_DE y sectores de patrullaje.

Entradas: data/geo/{limite,vias,pois}.geojson
Salidas:  data/geo/tramos.geojson, data/geo/cerca_de.csv, data/geo/sectores.json

Supuestos (documentados en el README):
- Una "cuadra" es un tramo de ~100 m a lo largo de la vía, numerado desde el extremo
  oeste/sur de la vía (C01, C02...). Lima numera cuadras por centenas de la numeración
  municipal; este es un aproximado reproducible.
- Los sectores de patrullaje son ficticios: k-means (k=7, semilla fija) sobre los
  centroides de los tramos.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, shape, mapping
import shapely
from shapely.ops import linemerge, substring, unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

log = logging.getLogger("geo.tramos")

A_METRICO = Transformer.from_crs("EPSG:4326", config.CRS_METRICO, always_xy=True).transform
A_WGS84 = Transformer.from_crs(config.CRS_METRICO, "EPSG:4326", always_xy=True).transform


def transform(fn, geom):
    """Reproyecta una geometría con una función pyproj (x, y) -> (x, y)."""
    return shapely.transform(geom, fn, interleaved=False)

PREFIJOS = {
    "avenida": "AV", "av": "AV", "jiron": "JR", "jr": "JR", "calle": "CA", "pasaje": "PJ",
    "psje": "PJ", "alameda": "AL", "malecon": "ML", "carretera": "CR", "prolongacion": "PROL",
    "ovalo": "OV", "via": "VIA", "autopista": "AU",
}


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def id_via(nombre: str) -> str:
    """'Avenida Antúnez de Mayolo' -> 'AV_ANTUNEZ_DE_MAYOLO'."""
    palabras = re.findall(r"[a-z0-9]+", sin_tildes(nombre).lower())
    if palabras and palabras[0] in PREFIJOS:
        palabras[0] = PREFIJOS[palabras[0]].lower()
    return "_".join(palabras).upper()


def partes_ordenadas(lineas: list[LineString]) -> list[LineString]:
    """Une los ways de una misma vía y orienta cada parte de oeste/sur a este/norte."""
    unido = unary_union(lineas)
    if not isinstance(unido, LineString):
        unido = linemerge(unido)
    partes = list(unido.geoms) if isinstance(unido, MultiLineString) else [unido]
    # Doble calzada: se descarta una parte si corre paralela (<110 m) a otra ya aceptada
    aceptadas, zona = [], None
    for p in sorted(partes, key=lambda g: -g.length):
        if zona is not None and p.intersection(zona).length > 0.6 * p.length:
            continue
        aceptadas.append(p)
        zona = p.buffer(110) if zona is None else zona.union(p.buffer(110))
    orientadas = []
    for p in aceptadas:
        (x0, y0), (x1, y1) = p.coords[0], p.coords[-1]
        orientadas.append(p if (x0, y0) <= (x1, y1) else LineString(list(p.coords)[::-1]))
    return sorted(orientadas, key=lambda p: (p.coords[0][0], p.coords[0][1]))


def cortar(linea: LineString, largo: float) -> list[LineString]:
    n = max(1, round(linea.length / largo))
    paso = linea.length / n
    return [substring(linea, i * paso, (i + 1) * paso) for i in range(n)]


def construir_tramos() -> list[dict]:
    limite = transform(A_METRICO, shape(json.loads((config.GEO / "limite.geojson").read_text(encoding="utf-8"))["features"][0]["geometry"]))
    limite_buf = limite.buffer(30)
    vias = json.loads((config.GEO / "vias.geojson").read_text(encoding="utf-8"))["features"]
    por_nombre: dict[str, list] = defaultdict(list)
    tipo_via: dict[str, str] = {}
    for f in vias:
        geom = transform(A_METRICO, shape(f["geometry"])).intersection(limite_buf)
        if geom.is_empty:
            continue
        geoms = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
        por_nombre[f["properties"]["nombre"]].extend(g for g in geoms if isinstance(g, LineString))
        tipo_via.setdefault(f["properties"]["nombre"], f["properties"]["highway"])

    tramos, ids_usados, bases = [], set(), defaultdict(int)
    for nombre in sorted(por_nombre):
        base = id_via(nombre)
        if not base:
            continue
        bases[base] += 1
        if bases[base] > 1:  # vías homónimas que solo difieren en tildes o mayúsculas
            base = f"{base}_{bases[base]}"
        cuadra = 0
        for parte in partes_ordenadas(por_nombre[nombre]):
            if parte.length < 25:
                continue
            for seg in cortar(parte, config.LONGITUD_TRAMO_M):
                cuadra += 1
                tid = f"{base}_C{cuadra:02d}"
                assert tid not in ids_usados, tid
                ids_usados.add(tid)
                geo = transform(A_WGS84, seg)
                c = geo.interpolate(0.5, normalized=True)
                tramos.append({"id": tid, "via": nombre, "via_id": base, "cuadra": cuadra,
                               "highway": tipo_via[nombre], "longitud_m": round(seg.length, 1),
                               "lat": round(c.y, 6), "lon": round(c.x, 6),
                               "geom_wkt": geo.wkt, "_metrico": seg})
    log.info("Tramos generados: %d en %d vías", len(tramos), len(por_nombre))
    return tramos


def calcular_cerca_de(tramos: list[dict]) -> list[dict]:
    pois = json.loads((config.GEO / "pois.geojson").read_text(encoding="utf-8"))["features"]
    puntos = [transform(A_METRICO, shape(p["geometry"])) for p in pois]
    arbol = STRtree(puntos)
    filas = []
    for t in tramos:
        for i in arbol.query(t["_metrico"].buffer(config.RADIO_POI_M)):
            d = t["_metrico"].distance(puntos[i])
            if d <= config.RADIO_POI_M:
                filas.append({"tramo_id": t["id"], "osm_id": pois[i]["properties"]["osm_id"], "distancia_m": round(d, 1)})
    log.info("Relaciones CERCA_DE: %d", len(filas))
    return filas


def asignar_sectores(tramos: list[dict]) -> list[dict]:
    from sklearn.cluster import KMeans

    xy = np.array([[t["_metrico"].centroid.x, t["_metrico"].centroid.y] for t in tramos])
    km = KMeans(n_clusters=config.N_SECTORES, random_state=config.SEMILLA, n_init=10).fit(xy)
    # Numeración estable: de norte a sur por el centroide del clúster
    orden = np.argsort(-km.cluster_centers_[:, 1])
    etiqueta = {int(c): i + 1 for i, c in enumerate(orden)}
    sectores = []
    for c, num in sorted(etiqueta.items(), key=lambda kv: kv[1]):
        miembros = [t for t, l in zip(tramos, km.labels_) if l == c]
        # El nombre del sector usa la avenida con más tramos dentro de él
        conteo = defaultdict(int)
        for m in miembros:
            if m["via_id"].startswith("AV_"):
                conteo[m["via"]] += 1
        principal = max(conteo, key=conteo.get) if conteo else miembros[0]["via"]
        cx, cy = A_WGS84(*km.cluster_centers_[c])
        sectores.append({"id": f"S{num}", "nombre": f"Sector {num} — {principal}", "lat": round(cy, 6), "lon": round(cx, 6),
                         "n_tramos": len(miembros)})
    for t, l in zip(tramos, km.labels_):
        t["sector"] = f"S{etiqueta[int(l)]}"
    return sectores


def main() -> None:
    tramos = construir_tramos()
    cerca = calcular_cerca_de(tramos)
    sectores = asignar_sectores(tramos)
    feats = [{"type": "Feature", "properties": {k: v for k, v in t.items() if k != "_metrico"},
              "geometry": mapping(transform(A_WGS84, t["_metrico"]))} for t in tramos]
    (config.GEO / "tramos.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    with open(config.GEO / "cerca_de.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tramo_id", "osm_id", "distancia_m"])
        w.writeheader()
        w.writerows(cerca)
    (config.GEO / "sectores.json").write_text(json.dumps(sectores, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Sectores: %s", ", ".join(f"{s['id']}({s['n_tramos']})" for s in sectores))


if __name__ == "__main__":
    config.configurar_logging()
    main()
