"""Extractor de incidentes desde relatos libres (puente con la pieza 3).

Interfaz enchufable: cualquier clase con `extraer(texto) -> IncidenteExtraido` sirve.
Para usar otro extractor: variable de entorno EXTRACTOR="paquete.modulo:Clase".

Estrategia: reglas (regex + gazetteer OSM + lemas de spaCy) y, solo si no se resuelve la
vía o la modalidad, respaldo con LLM (JSON validado con Pydantic). La geocodificación
nunca inventa: si no hay match, tramo_resuelto=False.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ValidationError, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
from ontologia.catalogos import MEDIOS, MODALIDAD, franja_de  # noqa: E402
from pln.gazetteer import TIPOS_VIA, Gazetteer, cargar, normalizar  # noqa: E402

log = logging.getLogger("pln")


class IncidenteExtraido(BaseModel):
    via: Optional[str] = None
    via_id: Optional[str] = None
    cuadra: Optional[int] = None
    hora: Optional[str] = None
    franja: Optional[str] = None
    modalidad: Optional[str] = None
    codigo_iccs: Optional[str] = None
    medio: Optional[str] = None
    punto_referencia: Optional[str] = None
    resumen: str = ""
    tramo_id: Optional[str] = None
    tramo_resuelto: bool = False
    metodo: Literal["reglas", "reglas+llm", "externo"] = "reglas"

    @field_validator("modalidad")
    @classmethod
    def _modalidad_valida(cls, v):
        if v is not None and v not in MODALIDAD:
            raise ValueError(f"modalidad desconocida: {v}")
        return v

    @field_validator("medio")
    @classmethod
    def _medio_valido(cls, v):
        if v is not None and v not in MEDIOS:
            raise ValueError(f"medio desconocido: {v}")
        return v


class Extractor(Protocol):
    def extraer(self, texto: str) -> IncidenteExtraido: ...


# --- Reglas --------------------------------------------------------------------------------
RE_CUADRA = re.compile(r"\b(?:cdra|cuadra|cuadras)\s*(\d{1,3})\b")
RE_HORA = re.compile(r"(\d{1,2})[:.](\d{2})\s*(a\.?\s*m\.?|p\.?\s*m\.?|horas|hrs\.?|h\b)?", re.I)
CORTE_LUGAR = re.compile(r"\b(cerca d|frente a|junto a|por inmediaciones|por el |por la |a pocos metros|dos |tres |un sujeto|un individuo|se reporta)")

# (modalidad, patrones sobre texto normalizado, lemas que la sugieren) — orden = prioridad
REGLAS_MODALIDAD = [
    ("bujiazo", [r"bujiazo", r"(luna|ventana) de (un|una) (auto|vehiculo)"], set()),
    ("marcaje", [r"marcaje", r"retirado dinero", r"salia del banco"], set()),
    ("cogoteo", [r"cogote", r"del cuello"], {"cogotear"}),
    ("tentativa_robo", [r"intent(aron|o) (robar|asaltar)", r"tentativa"], {"intentar"}),
    ("extorsion", [r"extors"], set()),
    ("acoso_sexual", [r"acos"], {"acosar"}),
    ("estafa_paso", [r"estaf", r"cuento"], {"estafar"}),
    ("hurto_autopartes", [r"autopartes", r"espejos de un vehiculo"], set()),
    ("robo_vehiculo", [r"despoj\w* a un conductor", r"rob\w* una motocicleta que"], {"despojar"}),
    ("robo_negocio", [r"bodega", r"establecimiento comercial", r"de la caja"], set()),
    ("amenazas", [r"amenaz", r"intimid"], {"amenazar", "intimidar"}),
    ("robo_celular", [r"celular", r"telefono", r"equipo movil"], set()),
    ("arrebato_cartera", [r"cartera", r"bolso", r"mochila"], set()),
]
REGLAS_MEDIO = [
    ("mototaxi", r"mototaxi"),
    ("bicicleta", r"bicicleta"),
    ("moto", r"(a bordo de una motocicleta|moto lineal|desplazaba\w* en una motocicleta|en una moto\b|en moto\b)"),
    ("auto", r"(a bordo de un auto|vehiculo particular|baj\w* de un automovil)"),
    ("a pie", r"(a pie|caminando)"),
]
REGLAS_POI = [("paradero", r"paradero"), ("mercado", r"mercado"), ("banco", r"\b(banco|agencia|bbva|bcp|interbank|scotiabank)\b"),
              ("colegio", r"(colegio|institucion educativa|\bi e\b|universidad|instituto)"), ("parque", r"parque")]


@lru_cache(maxsize=1)
def _nlp():
    try:
        import spacy

        return spacy.load("es_core_news_sm", disable=["ner", "parser"])
    except Exception as e:  # modelo no instalado: se sigue solo con regex
        log.warning("spaCy no disponible (%s); se usan solo regex", e)
        return None


def lemas(texto: str) -> set[str]:
    nlp = _nlp()
    return {normalizar(t.lemma_) for t in nlp(texto)} if nlp else set()


def extraer_hora(texto: str) -> str | None:
    m = RE_HORA.search(texto)
    if not m:
        return None
    h, mi, suf = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower().replace(" ", "").replace(".", "")
    if suf == "pm" and h < 12:
        h += 12
    elif suf == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def extraer_modalidad(norm: str, lem: set[str]) -> str | None:
    for mod, patrones, lemas_clave in REGLAS_MODALIDAD:
        if any(re.search(p, norm) for p in patrones) or (lemas_clave & lem):
            return mod
    return None


def extraer_medio(norm: str) -> str | None:
    for medio, patron in REGLAS_MEDIO:
        if re.search(patron, norm):
            return medio
    return None


def extraer_poi(norm: str) -> str | None:
    hallados = [(m.start(), tipo) for tipo, p in REGLAS_POI for m in [re.search(p, norm)] if m]
    return min(hallados)[1] if hallados else None


class ExtractorReglas:
    """Extractor por reglas con respaldo LLM opcional."""

    def __init__(self, gaz: Gazetteer | None = None, usar_llm: bool = True):
        self.gaz = gaz or cargar()
        self.patron = self.gaz.patron_alias()
        self.usar_llm = usar_llm

    # vía: se busca solo en la cláusula de lugar para no confundir con nombres de POI
    def _clausula_lugar(self, norm: str) -> str:
        m = re.search(r"\b(en|altura de)\b", norm)
        ini = m.start() if m else 0
        corte = CORTE_LUGAR.search(norm, ini + 3)
        return norm[ini: corte.start() if corte else len(norm)]

    def candidatos_via(self, norm: str) -> list[str]:
        """Vías cuyo alias más largo aparece en la cláusula de lugar (puede haber empate)."""
        clausula = self._clausula_lugar(norm)
        candidatos = []
        for m in self.patron.finditer(clausula):
            for via in self.gaz.alias[m.group(1)]:
                candidatos.append((-(m.end() - m.start()), m.start(), via))
        if not candidatos:
            return []
        candidatos.sort()
        empatados = sorted({c[2] for c in candidatos if c[0] == candidatos[0][0]})
        if len(empatados) > 1:  # desempate por el tipo de vía escrito ("av", "jr", "calle")
            con_tipo = [v for v in empatados if self.gaz.vias[v].tipo and re.search(
                r"\b(" + "|".join(a for a, t in TIPOS_VIA.items() if t == self.gaz.vias[v].tipo) + r")\s", clausula)]
            sin_tipo = [v for v in empatados if self.gaz.vias[v].tipo is None]
            empatados = con_tipo or sin_tipo or empatados
        return empatados

    def desempatar(self, candidatos: list[str], texto: str, cuadra: int | None, norm: str) -> str | None:
        """Vías homónimas en OSM: grafía exacta con tildes, luego cuadra existente cerca del POI citado."""
        if len(candidatos) <= 1:
            return candidatos[0] if candidatos else None
        bajo = texto.lower()
        exactos = [v for v in candidatos if self.gaz.vias[v].nombre.lower() in bajo
                   or self.gaz.vias[v].nombre.lower().split(" ", 1)[-1] in bajo]
        if len(exactos) == 1:
            return exactos[0]
        pool = exactos or candidatos
        if cuadra is not None:
            pool = [v for v in pool if cuadra in self.gaz.vias[v].cuadras] or pool
            poi_ids = {oid for nombre, ids in self.gaz.poi_por_nombre.items() if nombre in norm for oid in ids}
            if poi_ids:
                cerca = [v for v in pool if any(oid in poi_ids for oid, _ in self.gaz.cerca.get(self.gaz.vias[v].cuadras.get(cuadra, ""), []))]
                pool = cerca or pool
        return pool[0] if len(pool) == 1 else None  # sigue ambiguo: no se adivina

    def geocodificar(self, via: str | None, cuadra: int | None, poi_tipo: str | None, norm: str) -> str | None:
        if via and cuadra is not None:
            return self.gaz.vias[via].cuadras.get(cuadra)
        poi_ids = [oid for nombre, ids in self.gaz.poi_por_nombre.items() if nombre in norm for oid in ids]
        if via:  # sin cuadra: tramo de la vía junto al POI mencionado
            tramos = self.gaz.vias[via].cuadras.values()
            cands = [(d, t) for t in tramos for oid, d in self.gaz.cerca.get(t, [])
                     if (poi_ids and oid in poi_ids) or (not poi_ids and poi_tipo and self.gaz.pois[oid]["tipo"] == poi_tipo)]
            unicos = {t for _, t in cands}
            if poi_ids and cands:
                return min(cands)[1]
            return next(iter(unicos)) if len(unicos) == 1 else None
        if poi_ids:  # sin vía: tramo más cercano al POI nombrado (si es único)
            cands = [(d, t) for t, lst in self.gaz.cerca.items() for oid, d in lst if oid in poi_ids]
            return min(cands)[1] if cands and len(set(poi_ids)) == 1 else None
        return None

    def _respaldo_llm(self, texto: str, inc: dict) -> dict:
        sistema = ("Extraes datos de un reporte policial de Los Olivos (Lima). No inventes: usa null si no aparece. "
                   f"modalidad ∈ {list(MODALIDAD)}; medio ∈ {MEDIOS}. Campos: via (nombre de la vía), cuadra (entero), modalidad, medio.")
        datos = llm.completar_json(sistema, texto)
        if not datos:
            return inc
        try:
            parcial = IncidenteExtraido(**{k: datos.get(k) for k in ("cuadra", "modalidad", "medio")})
        except ValidationError as e:
            log.warning("JSON del LLM inválido: %s", e)
            return inc
        if inc["via"] is None and datos.get("via"):
            m = self.patron.search(normalizar(str(datos["via"])))
            if m and len(self.gaz.alias[m.group(1)]) == 1:
                inc["via"] = self.gaz.alias[m.group(1)][0]
        for k in ("cuadra", "modalidad", "medio"):
            if inc[k] is None and getattr(parcial, k) is not None:
                inc[k] = getattr(parcial, k)
        inc["metodo"] = "reglas+llm"
        return inc

    def extraer(self, texto: str) -> IncidenteExtraido:
        norm = normalizar(texto)
        m = RE_CUADRA.search(norm)
        candidatos = self.candidatos_via(norm)
        inc = {"cuadra": int(m.group(1)) if m else None, "metodo": "reglas"}
        inc["via"] = self.desempatar(candidatos, texto, inc["cuadra"], norm)
        inc["hora"] = extraer_hora(texto)
        inc["modalidad"] = extraer_modalidad(norm, lemas(texto))
        inc["medio"] = extraer_medio(norm)
        inc["punto_referencia"] = extraer_poi(norm)
        if self.usar_llm and (inc["via"] is None or inc["modalidad"] is None) and llm.disponible():
            inc = self._respaldo_llm(texto, inc)
        ambigua = inc["via"] is None and bool(candidatos)  # menciona una vía pero no se pudo decidir
        tramo = None if ambigua else self.geocodificar(inc["via"], inc["cuadra"], inc["punto_referencia"], norm)
        if tramo and inc["via"] is None:
            inc["via"] = self.gaz.tramos[tramo]["via"]
        if tramo and inc["cuadra"] is None:
            inc["cuadra"] = self.gaz.tramos[tramo]["cuadra"]
        inc.update(tramo_id=tramo, tramo_resuelto=tramo is not None,
                   via_id=self.gaz.vias[inc["via"]].via_id if inc["via"] else None,
                   franja=franja_de(inc["hora"]) if inc["hora"] else None,
                   codigo_iccs=MODALIDAD[inc["modalidad"]]["codigo_iccs"] if inc["modalidad"] else None)
        inc["resumen"] = resumir(inc)
        return IncidenteExtraido(**inc)


def resumir(inc: dict) -> str:
    partes = [MODALIDAD[inc["modalidad"]]["nombre"] if inc.get("modalidad") else "Incidente sin modalidad clara"]
    if inc.get("medio"):
        partes.append(f"autores {inc['medio'] if inc['medio'] == 'a pie' else 'en ' + inc['medio']}")
    if inc.get("via"):
        partes.append(f"{inc['via']}{' cdra. ' + str(inc['cuadra']) if inc.get('cuadra') else ''}")
    if inc.get("punto_referencia"):
        partes.append(f"cerca de {inc['punto_referencia']}")
    if inc.get("hora"):
        partes.append(f"{inc['hora']} h")
    return " · ".join(partes)


@lru_cache(maxsize=1)
def obtener_extractor() -> Extractor:
    """Extractor configurado (EXTRACTOR=modulo:Clase) o el de reglas por defecto."""
    ruta = os.getenv("EXTRACTOR")
    if ruta:
        modulo, clase = ruta.split(":")
        log.info("Usando extractor externo %s", ruta)
        return getattr(importlib.import_module(modulo), clase)()
    return ExtractorReglas()
