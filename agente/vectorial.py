"""Búsqueda vectorial en Neo4j sobre Pagina (contexto oficial) y Reporte (relatos similares)."""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grafo.conexion import leer  # noqa: E402
from grafo.embeddings import consulta, limpiar  # noqa: E402
from pln.gazetteer import normalizar  # noqa: E402

CYPHER_PAGINAS = """
CALL db.index.vector.queryNodes('pagina_embedding', $k, $vector) YIELD node, score
MATCH (d:Documento)-[:TIENE_PAGINA]->(node)
RETURN d.cita AS cita, d.titulo AS titulo, d.url AS url, d.categoria AS categoria, node.pagina AS pagina,
       node.texto AS texto, node.menciona_los_olivos AS menciona_los_olivos, score
"""
CYPHER_REPORTES = """
CALL db.index.vector.queryNodes('reporte_embedding', $k, $vector) YIELD node, score
MATCH (i:Incidente)-[:REGISTRADO_EN]->(node)
RETURN node.id AS reporte, toString(i.fecha) AS fecha, i.hora AS hora, node.texto AS texto, score
"""
VACIAS = {"que", "del", "las", "los", "por", "para", "con", "una", "como", "segun", "sobre", "dice", "cual", "cuales",
          "hay", "fue", "son", "esta", "este", "donde", "the", "lima"}


def _terminos(pregunta: str) -> list[str]:
    return [t for t in normalizar(pregunta).split() if len(t) > 3 and t not in VACIAS]


def fragmento(texto: str, terminos: list[str], largo: int = 320) -> str:
    """Trozo del texto alrededor del primer término de la pregunta (sin columnas de números)."""
    lineas = [l for l in texto.splitlines() if not re.fullmatch(r"[\s\d.,%#/\-–*]*", l)]
    limpio = " ".join(" ".join(lineas).split())
    norm = normalizar(limpio)
    pos = min((norm.find(t) for t in terminos if norm.find(t) >= 0), default=0)
    ini = max(0, pos - largo // 3)
    return ("…" if ini else "") + limpio[ini:ini + largo] + "…"


CYPHER_TEXTO = """
CALL db.index.fulltext.queryNodes('pagina_texto', $consulta, {limit: $k}) YIELD node, score
MATCH (d:Documento)-[:TIENE_PAGINA]->(node)
RETURN d.cita AS cita, d.titulo AS titulo, d.url AS url, d.categoria AS categoria, node.pagina AS pagina,
       node.texto AS texto, node.menciona_los_olivos AS menciona_los_olivos, score
"""


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "setiembre",
         "octubre", "noviembre", "diciembre"]


def serie(titulo: str, categoria: str) -> str:
    """Serie del documento sin su periodo. SIDPOL y Congreso publican una sola serie mensual (Congreso: Lima/Callao)."""
    t = normalizar(titulo)
    if categoria in ("sidpol", "central-denuncias", "violencia-mujer"):
        return categoria
    if categoria == "congreso":
        return categoria + ("|callao" if "callao" in t else "|lima")
    abreviados = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "agos", "set", "sep", "oct", "nov", "dic"]
    t = re.sub(r"\b(" + "|".join(MESES + abreviados) + r"|de|del|la|el|y|informe|tecnico|primer|segundo|i|ii|iv|"
               r"trim|semestre|movil|\d+)\b", " ", t)
    return categoria + "|" + " ".join(t.split())


@lru_cache(maxsize=1)
def ediciones_vigentes() -> frozenset[str]:
    """Citas de la edición más reciente (mayor número gob.pe) de cada serie de documentos."""
    docs = leer("MATCH (d:Documento) RETURN d.cita AS cita, d.titulo AS titulo, d.categoria AS categoria")
    mejor: dict[str, tuple[int, str]] = {}
    for d in docs:
        m = re.search(r"(\d{6,})", d["cita"])
        num = int(m.group(1)) if m else 0
        s = serie(d["titulo"], d["categoria"])
        if s not in mejor or num > mejor[s][0]:
            mejor[s] = (num, d["cita"])
    return frozenset(c for _, c in mejor.values())


def _lucene(terminos: list[str]) -> str:
    return " OR ".join(re.sub(r"[^a-z0-9ñ]", "", t) for t in terminos if re.sub(r"[^a-z0-9ñ]", "", t)) or "seguridad"


def buscar_paginas(pregunta: str, k: int = 5, preferir_los_olivos: bool | None = None) -> tuple[list[dict], str]:
    """Híbrido: vecinos vectoriales + texto completo (Lucene) fusionados por rango recíproco (RRF).

    Desempates: páginas que mencionan Los Olivos (si la pregunta lo pide) y la edición más reciente
    (los informes se publican cada mes con texto casi idéntico; se deja uno por contenido).
    """
    terminos = _terminos(pregunta)
    if preferir_los_olivos is None:
        preferir_los_olivos = "olivos" in normalizar(pregunta)
    por_vector = leer(CYPHER_PAGINAS, k=250, vector=consulta(pregunta))
    por_texto = leer(CYPHER_TEXTO, k=400, consulta=_lucene(terminos))
    if not re.search(r"\b20\d\d\b|" + "|".join(MESES), normalizar(pregunta)):
        vigentes = ediciones_vigentes()  # sin periodo en la pregunta: solo la edición más reciente de cada serie
        por_vector = [f for f in por_vector if f["cita"] in vigentes]
        por_texto = [f for f in por_texto if f["cita"] in vigentes]
    fuentes = [c for c in ("inei", "sidpol", "congreso") if re.search(rf"\b{c}\b", normalizar(pregunta))]
    if fuentes:  # "según el INEI", "registra SIDPOL": solo documentos de esa institución
        por_vector = [f for f in por_vector if f["categoria"] in fuentes]
        por_texto = [f for f in por_texto if f["categoria"] in fuentes]
    # Pares consecutivos de la pregunta ("tasa ... victimizacion", "lima metropolitana"), hasta 2 palabras entre medio
    tokens = [t for t in normalizar(pregunta).split() if len(t) > 3 and t not in VACIAS - {"lima"}]
    bigramas = [rf"\b{a}\w*\W+(?:\w+\W+){{0,2}}{b}" for a, b in zip(tokens, tokens[1:])]
    fusion: dict[str, dict] = {}
    for lista in (por_vector, por_texto):
        for rango, f in enumerate(lista):
            clave = f"{f['cita']} p.{f['pagina']}"
            fila = fusion.setdefault(clave, {**f, "rrf": 0.0})
            fila["rrf"] += 1 / (60 + rango)
    numero = lambda c: int(re.search(r"(\d{6,})", c).group(1)) if re.search(r"(\d{6,})", c) else 0
    for f in fusion.values():
        norm = normalizar(f["texto"])
        f["coincidencias"] = sum(t in norm for t in terminos) + 2 * sum(bool(re.search(b, norm)) for b in bigramas)
        f["puntaje"] = (f["rrf"] + 0.004 * f["coincidencias"] + (0.01 if preferir_los_olivos and f["menciona_los_olivos"] else 0)
                        - (0.006 if f["pagina"] <= 2 else 0))  # portadas y presentación casi nunca traen la cifra
        f["fragmento"] = fragmento(f["texto"], terminos)
    filas, vistos = [], set()
    for f in sorted(fusion.values(), key=lambda f: (-round(f["puntaje"], 4), -numero(f["cita"]))):
        firma = f"{f['categoria']}|{f['pagina']}|{normalizar(limpiar(f['texto']))[:80]}"
        if firma in vistos:
            continue  # misma página en otra edición del informe
        vistos.add(firma)
        filas.append(f)
    return filas[:k], CYPHER_PAGINAS.strip() + "\n// + texto completo (RRF)\n" + CYPHER_TEXTO.strip()


def buscar_reportes(pregunta: str, k: int = 10) -> tuple[list[dict], str]:
    return leer(CYPHER_REPORTES, k=k, vector=consulta(pregunta)), CYPHER_REPORTES.strip()
