"""Gazetteer de vías y POIs de Los Olivos construido desde OSM (data/geo).

Normaliza nombres ("Av.", "Jr.", "cdra.", tildes) y genera alias: nombre sin tipo de vía
("Antúnez de Mayolo"), sufijos distintivos y palabras únicas largas ("Antúnez").
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

TIPOS_VIA = {
    "avenida": "avenida", "av": "avenida", "jiron": "jiron", "jr": "jiron", "calle": "calle", "ca": "calle",
    "pasaje": "pasaje", "psje": "pasaje", "pje": "pasaje", "alameda": "alameda", "prolongacion": "prolongacion",
    "prol": "prolongacion", "malecon": "malecon", "ovalo": "ovalo", "via": "via", "carretera": "carretera",
}
VACIAS = {"de", "del", "la", "las", "los", "el", "y", "san", "santa", "santo", "jose", "juan", "maria", "norte",
          "sur", "este", "oeste", "nueva", "nuevo", "calle", "avenida"}


def normalizar(texto: str) -> str:
    """minúsculas, sin tildes, sin puntuación, espacios simples."""
    t = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9ñ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def separar_tipo(nombre_norm: str) -> tuple[str | None, str]:
    partes = nombre_norm.split(" ", 1)
    if len(partes) == 2 and partes[0] in TIPOS_VIA:
        return TIPOS_VIA[partes[0]], partes[1]
    return None, nombre_norm


def es_corto(nucleo: str) -> bool:
    """Núcleos como '12', '5', 'a', '16b' solo se reconocen precedidos del tipo de vía."""
    return len(nucleo) <= 3 or nucleo.isdigit() or bool(re.fullmatch(r"\d+[a-z]?", nucleo))


@dataclass
class Via:
    nombre: str
    via_id: str
    tipo: str | None
    nucleo: str
    cuadras: dict[int, str] = field(default_factory=dict)  # cuadra -> tramo_id


@dataclass
class Gazetteer:
    vias: dict[str, Via]
    alias: dict[str, list[str]]           # alias normalizado -> [nombre vía]
    pois: dict[str, dict]                 # osm_id -> props
    poi_por_nombre: dict[str, list[str]]  # nombre normalizado -> [osm_id]
    cerca: dict[str, list[tuple[str, float]]]  # tramo_id -> [(osm_id, distancia)]
    tramos: dict[str, dict]

    def patron_alias(self) -> re.Pattern:
        claves = sorted(self.alias, key=len, reverse=True)
        return re.compile(r"\b(" + "|".join(re.escape(k) for k in claves) + r")\b")


@lru_cache(maxsize=1)
def cargar() -> Gazetteer:
    feats = json.loads((config.GEO / "tramos.geojson").read_text(encoding="utf-8"))["features"]
    tramos = {f["properties"]["id"]: f["properties"] for f in feats}
    vias: dict[str, Via] = {}
    for t in tramos.values():
        v = vias.get(t["via"])
        if v is None:
            tipo, nucleo = separar_tipo(normalizar(t["via"]))
            v = vias[t["via"]] = Via(t["via"], t["via_id"], tipo, nucleo)
        v.cuadras[t["cuadra"]] = t["id"]

    alias: dict[str, set[str]] = defaultdict(set)
    frecuencia_palabra: dict[str, set[str]] = defaultdict(set)
    for v in vias.values():
        for w in v.nucleo.split():
            frecuencia_palabra[w].add(v.nombre)
    for v in vias.values():
        if v.tipo:
            # tipo + núcleo con sus abreviaturas: "av antunez de mayolo", "avenida ..."
            for abrev, tipo in TIPOS_VIA.items():
                if tipo == v.tipo:
                    alias[f"{abrev} {v.nucleo}"].add(v.nombre)
        if es_corto(v.nucleo):
            continue
        alias[v.nucleo].add(v.nombre)
        palabras = v.nucleo.split()
        for i in range(1, len(palabras)):  # sufijos de ≥2 palabras: "antunez de mayolo"
            suf = palabras[i:]
            if len(suf) >= 2 and suf[0] not in VACIAS:
                alias[" ".join(suf)].add(v.nombre)
        for w in palabras:  # palabra distintiva única: "antunez", "izaguirre"
            if len(w) >= 6 and w not in VACIAS and len(frecuencia_palabra[w]) == 1 and len(palabras) > 1:
                alias[w].add(v.nombre)

    pois = {p["properties"]["osm_id"]: p["properties"]
            for p in json.loads((config.GEO / "pois.geojson").read_text(encoding="utf-8"))["features"]}
    poi_por_nombre: dict[str, list[str]] = defaultdict(list)
    for oid, p in pois.items():
        n = normalizar(p["nombre"])
        if len(n) > 8:
            poi_por_nombre[n].append(oid)
    cerca: dict[str, list] = defaultdict(list)
    with open(config.GEO / "cerca_de.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            cerca[fila["tramo_id"]].append((fila["osm_id"], float(fila["distancia_m"])))
    return Gazetteer(vias, {k: sorted(v) for k, v in alias.items()}, pois, dict(poi_por_nombre), dict(cerca), tramos)
