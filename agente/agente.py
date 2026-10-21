"""Agente GraphRAG híbrido: router -> Cypher plantilla -> Text2Cypher -> vectorial -> síntesis con citas."""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import llm  # noqa: E402
from agente import consultas, sintesis, text2cypher, vectorial  # noqa: E402
from agente.parametros import enrutar  # noqa: E402
from ontologia.catalogos import ARREBATOS  # noqa: E402

log = logging.getLogger("agente")

MSG_PRIVACIDAD = ("No puedo entregar datos de personas (nombres, DNI, placas, rasgos físicos). El sistema registra solo "
                  "incidentes y patrones, conforme a la Ley N.° 29733 de Protección de Datos Personales.")
MSG_FUERA = ("Esa pregunta está fuera del alcance de Memoria Vial Segura: solo respondo sobre incidentes, intervenciones "
             "y estadísticas de seguridad ciudadana en Los Olivos, con evidencia del grafo.")


@dataclass
class Respuesta:
    pregunta: str
    tipo: str
    texto: str
    evidencia: list[dict] = field(default_factory=list)
    cypher: list[str] = field(default_factory=list)
    citas: list[str] = field(default_factory=list)
    parametros: dict = field(default_factory=dict)
    modo: str = "plantilla"
    latencia_s: float = 0.0
    estructura: dict = field(default_factory=dict)  # resultado normalizado para evaluación automática


def _citas_de(filas: list[dict]) -> set[str]:
    citas = set()
    for f in filas:
        for k in ("reportes", "reportes_antes", "reportes_despues"):
            citas |= set(f.get(k) or [])
        if f.get("reporte"):
            citas.add(f["reporte"])
        if f.get("cita") and f.get("pagina"):
            citas.add(f"{f['cita']} p.{f['pagina']}")
    return citas


def _ejecutar(tipo: str, p: dict, pregunta: str, ref) -> tuple[list[dict], list[str], dict]:
    sem_desde, sem_hasta = consultas.ultima_semana(ref)
    if tipo == "patron":
        desde, hasta = p["desde"] or sem_desde, p["hasta"] or sem_hasta
        mods = p["modalidad"]
        filas, cy, _ = consultas.patron(desde, hasta, modalidad=mods, medio=p["medio"], hora_desde=p["hora_desde"],
                                        hora_hasta=p["hora_hasta"], poi_tipo=p["poi_tipo"], sector=p["sector"],
                                        iccs=p["iccs_prefijo"])
        p.update(desde=desde, hasta=hasta)
        return filas, [cy], {"tramos": [f["tramo"] for f in filas], "vias": list(dict.fromkeys(f["via"] for f in filas))}
    if tipo == "intervencion":
        desde, hasta = p["desde"], p["hasta"]
        mods = [p["modalidad"]] if p["modalidad"] and not p["arrebatos"] else ARREBATOS
        filas, cy, _ = consultas.efecto_intervencion(tipo=p["tipo_intervencion"] or "patrullaje reforzado", desde=desde,
                                                     hasta=hasta, via=p["via"], modalidades=mods)
        return filas, [cy], {"intervenciones": {f["tramo"]: [f["antes"], f["despues"]] for f in filas}}
    if tipo == "emergente":
        desde, hasta = p["desde"] or sem_desde, p["hasta"] or sem_hasta
        filas, cy, _ = consultas.emergentes(desde, hasta)
        p.update(desde=desde, hasta=hasta)
        return filas, [cy], {"emergentes": sorted({(f["modalidad"], f["via"]) for f in filas if f["previos_modalidad"] == 0})}
    if tipo == "contexto":
        filas, cy = vectorial.buscar_paginas(pregunta)
        return filas, [cy], {"paginas": [f"{f['cita']} p.{f['pagina']}" for f in filas]}
    if tipo == "conteo":
        desde, hasta = p["desde"] or config.FECHA_INICIO.isoformat(), p["hasta"] or ref.isoformat()
        filas, cy, _ = consultas.conteo(desde, hasta, modalidad=p["modalidad"], medio=p["medio"], franja=p["franja"],
                                        sector=p["sector"], via=p["via"], iccs=p["iccs_prefijo"])
        p.update(desde=desde, hasta=hasta)
        return filas, [cy], {"total": sum(f["incidentes"] for f in filas)}
    # libre: Text2Cypher si hay LLM; si no (o si falla), relatos similares por vector
    if llm.disponible():
        try:
            filas, cy = text2cypher.generar_y_ejecutar(pregunta)
            return filas, [cy], {}
        except RuntimeError as e:
            log.warning("Text2Cypher falló: %s", e)
    filas, cy = vectorial.buscar_reportes(pregunta, k=6)
    return filas, [cy], {}


def responder(pregunta: str) -> Respuesta:
    t0 = time.perf_counter()
    ref = consultas.fecha_referencia()
    ruta = enrutar(pregunta, ref)
    p = ruta.parametros.model_dump()
    if ruta.tipo in ("privacidad", "fuera_de_alcance"):
        texto = MSG_PRIVACIDAD if ruta.tipo == "privacidad" else MSG_FUERA
        return Respuesta(pregunta, ruta.tipo, texto, parametros=p, latencia_s=round(time.perf_counter() - t0, 2))
    filas, cyphers, estructura = _ejecutar(ruta.tipo, p, pregunta, ref)
    permitidas = _citas_de(filas)
    texto, modo = sintesis.sintetizar(pregunta, ruta.tipo, filas, p, permitidas)
    citas = sorted(set(sintesis.RE_CITA_R.findall(texto)) | {f"{c} p.{n}" for c, n in sintesis.RE_CITA_DOC.findall(texto)})
    estructura["citas"] = citas
    return Respuesta(pregunta, ruta.tipo, texto, filas, cyphers, citas, p, f"{modo} · router {ruta.origen}",
                     round(time.perf_counter() - t0, 2), estructura)


if __name__ == "__main__":
    config.configurar_logging()
    r = responder(" ".join(sys.argv[1:]) or "¿Dónde se concentran los robos de celular desde moto entre 18:00 y 20:00 cerca de paraderos en la última semana?")
    print(f"[{r.tipo} | {r.modo} | {r.latencia_s}s]\n{r.texto}\n\nCitas: {r.citas}\nParámetros: {r.parametros}")
