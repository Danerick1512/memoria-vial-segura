"""Descarga desde OpenStreetMap (Overpass API) la red vial y los puntos de interés de Los Olivos.

Salidas en data/geo/: limite.geojson, vias.geojson, pois.geojson. Si el archivo ya
existe no se vuelve a descargar (caché). Si Overpass falla, se informa y se detiene:
no se inventa la red vial.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

log = logging.getLogger("geo.osm")

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
AREA = 3600000000 + config.OSM_RELACION_LOS_OLIVOS
TIPOS_VIA = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|primary_link|secondary_link|tertiary_link"

CONSULTAS = {
    "limite": f"[out:json][timeout:120];relation({config.OSM_RELACION_LOS_OLIVOS});out geom;",
    "vias": f'[out:json][timeout:180];area({AREA})->.a;way["highway"~"^({TIPOS_VIA})$"]["name"](area.a);out geom tags;',
    "pois": f"""[out:json][timeout:180];area({AREA})->.a;
(
  node["highway"="bus_stop"](area.a);
  node["public_transport"="platform"](area.a);
  nwr["amenity"="marketplace"](area.a);
  nwr["shop"="supermarket"](area.a);
  nwr["amenity"~"^(school|college|university)$"](area.a);
  nwr["leisure"="park"](area.a);
  nwr["amenity"="bank"](area.a);
);
out center tags;""",
}

INSTRUCCIONES_MANUALES = """
No se pudo descargar desde Overpass. Alternativa manual:
  1. Abre https://overpass-turbo.eu/ y pega la consulta impresa arriba.
  2. Ejecuta y usa Exportar -> 'datos sin procesar (JSON de Overpass)'.
  3. Guarda el archivo como data/geo/<nombre>.overpass.json y vuelve a correr este script.
"""


def consultar(nombre: str, consulta: str) -> dict:
    ultimo_error = None
    for url in SERVIDORES:
        for intento in range(3):
            try:
                log.info("Overpass %s (%s, intento %d)", nombre, url, intento + 1)
                r = requests.post(url, data={"data": consulta}, timeout=240,
                                  headers={"User-Agent": "MemoriaVialSegura/0.1 (curso UNMSM)"})
                r.raise_for_status()
                return r.json()
            except Exception as e:  # red, 429, 504...
                ultimo_error = e
                log.warning("Fallo Overpass: %s", e)
                time.sleep(5 * (intento + 1))
    raise RuntimeError(f"Overpass no respondió para '{nombre}': {ultimo_error}")


def _geom_linea(el: dict) -> list[list[float]]:
    return [[p["lon"], p["lat"]] for p in el.get("geometry", [])]


def a_geojson_limite(datos: dict) -> dict:
    """Arma el polígono del límite uniendo los 'outer' de la relación."""
    from shapely.geometry import LineString, mapping
    from shapely.ops import polygonize, unary_union

    lineas = []
    for el in datos["elements"]:
        for m in el.get("members", []):
            if m.get("type") == "way" and m.get("role", "outer") in ("outer", "") and m.get("geometry"):
                lineas.append(LineString([(p["lon"], p["lat"]) for p in m["geometry"]]))
    poligono = unary_union(list(polygonize(unary_union(lineas))))
    tags = datos["elements"][0].get("tags", {})
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"nombre": tags.get("name"), "ubigeo": tags.get("pe:ubigeo")},
         "geometry": mapping(poligono)}]}


def a_geojson_vias(datos: dict) -> dict:
    feats = []
    for el in datos["elements"]:
        if el["type"] != "way" or len(el.get("geometry", [])) < 2:
            continue
        t = el.get("tags", {})
        feats.append({"type": "Feature",
                      "properties": {"osm_id": f"way/{el['id']}", "nombre": t["name"], "highway": t.get("highway")},
                      "geometry": {"type": "LineString", "coordinates": _geom_linea(el)}})
    return {"type": "FeatureCollection", "features": feats}


def _tipo_poi(t: dict) -> str | None:
    if t.get("highway") == "bus_stop" or t.get("public_transport") == "platform":
        return "paradero"
    if t.get("amenity") == "marketplace" or t.get("shop") == "supermarket":
        return "mercado"
    if t.get("amenity") in ("school", "college", "university"):
        return "colegio"
    if t.get("leisure") == "park":
        return "parque"
    if t.get("amenity") == "bank":
        return "banco"
    return None


def a_geojson_pois(datos: dict) -> dict:
    feats, vistos = [], set()
    for el in datos["elements"]:
        t = el.get("tags", {})
        tipo = _tipo_poi(t)
        if el["type"] == "node":
            lon, lat = el["lon"], el["lat"]
        else:
            c = el.get("center")
            if not c:
                continue
            lon, lat = c["lon"], c["lat"]
        osm_id = f"{el['type']}/{el['id']}"
        if tipo is None or osm_id in vistos:
            continue
        vistos.add(osm_id)
        nombre = t.get("name") or {"paradero": "Paradero", "mercado": "Mercado", "colegio": "Colegio",
                                   "parque": "Parque", "banco": "Agencia bancaria"}[tipo]
        feats.append({"type": "Feature", "properties": {"osm_id": osm_id, "tipo": tipo, "nombre": nombre},
                      "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    return {"type": "FeatureCollection", "features": feats}


CONVERSORES = {"limite": a_geojson_limite, "vias": a_geojson_vias, "pois": a_geojson_pois}


def descargar(forzar: bool = False) -> None:
    config.GEO.mkdir(parents=True, exist_ok=True)
    for nombre, consulta in CONSULTAS.items():
        destino = config.GEO / f"{nombre}.geojson"
        crudo = config.GEO / f"{nombre}.overpass.json"
        if destino.exists() and not forzar:
            log.info("Caché: %s ya existe, no se descarga", destino.name)
            continue
        if crudo.exists() and not forzar:
            datos = json.loads(crudo.read_text(encoding="utf-8"))
        else:
            try:
                datos = consultar(nombre, consulta)
            except RuntimeError as e:
                log.error("%s\nConsulta:\n%s\n%s", e, consulta, INSTRUCCIONES_MANUALES)
                raise SystemExit(1)
            crudo.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        gj = CONVERSORES[nombre](datos)
        destino.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
        log.info("%s: %d elementos -> %s", nombre, len(gj["features"]), destino.name)


if __name__ == "__main__":
    config.configurar_logging()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forzar", action="store_true", help="ignora la caché y vuelve a descargar")
    descargar(ap.parse_args().forzar)
