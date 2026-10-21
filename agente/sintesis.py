"""Síntesis de la respuesta en español con citas obligatorias.

Formato de citas: [R-000123] para reportes y [INEI-7278873 p.30] para páginas oficiales.
Con LLM: redacta a partir de la evidencia y se verifica que cada cita exista en ella; si cita algo
que no está en la evidencia, se descarta y se usa la plantilla. Sin evidencia, se dice; nunca se
inventan cifras.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
from ontologia.catalogos import MODALIDAD  # noqa: E402

RE_CITA_R = re.compile(r"\[(R-\d{6})\]")
RE_CITA_DOC = re.compile(r"\[([A-Z][A-Z\-]*-[A-Z0-9\-]+) p\.(\d+)\]")
AVISO_CAUSAL = "Comparación descriptiva (antes/después), no prueba causalidad."


def citar(ids: list[str], n: int = 4) -> str:
    extra = f" (+{len(ids) - n})" if len(ids) > n else ""
    return " ".join(f"[{i}]" for i in ids[:n]) + extra


def citas_validas(texto: str, permitidas: set[str]) -> bool:
    usadas = set(RE_CITA_R.findall(texto)) | {f"{c} p.{p}" for c, p in RE_CITA_DOC.findall(texto)}
    return bool(usadas) and usadas <= permitidas


def _periodo(p: dict) -> str:
    return f"del {p['desde']} al {p['hasta']}" if p.get("desde") else "en todo el periodo"


# --- Plantillas (modo sin LLM, y respaldo si el LLM cita mal) ---------------------------------------
def plantilla_patron(filas: list[dict], p: dict) -> str:
    if not filas:
        return f"No hay incidentes que cumplan esos criterios {_periodo(p)}. No hay evidencia para afirmar un patrón."
    filtros = [MODALIDAD[p["modalidad"]]["nombre"].lower().replace("robo de", "robos de") if p.get("modalidad")
               else ("robos" if p.get("iccs_prefijo") == "04" else "incidentes"),
               f"con autores en {p['medio']}" if p.get("medio") and p["medio"] != "a pie" else ("a pie" if p.get("medio") else ""),
               f"entre {p['hora_desde']} y {p['hora_hasta']}" if p.get("hora_desde") else "",
               f"a ≤100 m de un {p['poi_tipo']}" if p.get("poi_tipo") else ""]
    total = sum(f["incidentes"] for f in filas)
    por_via = Counter()
    for f in filas:
        por_via[f["via"]] += f["incidentes"]
    vias = ", ".join(f"**{v}** ({n})" for v, n in por_via.most_common(4))
    top = filas[0]
    concentrados = [f for f in filas if f["incidentes"] >= 2]
    lineas = [f"{_periodo(p).capitalize()}, los {' '.join(x for x in filtros if x)} suman **{total}** en {len(filas)} tramos. "
              f"Se concentran en {vias}.",
              f"El tramo más afectado es {top['via']} cdra. {top['cuadra']} con {top['incidentes']} incidentes "
              f"({top.get('poi_cercano') or 'sin POI cercano'}) {citar(top['reportes'])}."]
    if len(concentrados) > 1:
        lineas.append(f"{len(concentrados)} tramos tienen 2 o más casos: " + "; ".join(
            f"{f['via']} cdra. {f['cuadra']} ({f['incidentes']}) {citar(f['reportes'], 2)}" for f in concentrados[1:6]) + ".")
    return " ".join(lineas)


def plantilla_intervencion(filas: list[dict], p: dict) -> str:
    con_datos = [f for f in filas if f["antes"] or f["despues"]]
    if not con_datos:
        return "No hay intervenciones con incidentes registrados en sus ventanas de comparación; no hay evidencia para evaluar su efecto."
    bajaron = [f for f in con_datos if f["despues"] < f["antes"]]
    no_bajaron = [f for f in con_datos if f["despues"] >= f["antes"]]
    ta, td = sum(f["antes"] for f in con_datos), sum(f["despues"] for f in con_datos)
    var = f"{100 * (td - ta) / ta:+.0f} %" if ta else "n/d"
    f0 = con_datos[0]
    texto = [f"Se comparan {'los arrebatos' if p.get('arrebatos') or not p.get('modalidad') else MODALIDAD[p['modalidad']]['nombre'].lower()} "
             f"4 semanas antes ({f0['ventana_antes_desde']} → {f0['inicio']}) y 4 semanas desde el inicio de la intervención "
             f"({f0['inicio']} → {f0['ventana_despues_hasta']}) en {len(con_datos)} tramos con {f0['tipo']}.",
             f"En total pasaron de **{ta} a {td}** ({var}). Bajaron en {len(bajaron)} de {len(con_datos)} tramos."]
    for f in bajaron[:4]:
        texto.append(f"- {f['via']} cdra. {f['cuadra']}: {f['antes']} → {f['despues']} ({f['variacion_pct']:+.0f} %) "
                     f"antes {citar(f['reportes_antes'], 2)} · después {citar(f['reportes_despues'], 2) or '—'}")
    for f in no_bajaron:
        texto.append(f"- ⚠️ {f['via']} cdra. {f['cuadra']} **no bajó**: {f['antes']} → {f['despues']} "
                     f"{citar(f['reportes_despues'], 3)}")
    texto.append(f"_{AVISO_CAUSAL}_")
    return "\n".join(texto)


def plantilla_emergente(filas: list[dict], p: dict) -> str:
    if not filas:
        return f"No se detectan modalidades nuevas {_periodo(p)} en vías sin registros previos (30 días)."
    nuevas = [f for f in filas if f["previos_modalidad"] == 0]
    lineas = [f"{_periodo(p).capitalize()} aparecen **{len({f['modalidad'] for f in nuevas})} modalidades nuevas** "
              f"(sin ningún registro en el distrito en los 30 días previos), todas en vías sin incidentes en ese mes:"]
    for f in nuevas:
        lineas.append(f"- **{f['nombre']}** (ICCS {f['codigo_iccs']}) en {f['via']}: {f['incidentes']} caso{'s' if f['incidentes'] != 1 else ''} {citar(f['reportes'])}")
    otras = [f for f in filas if f["previos_modalidad"] > 0]
    if otras:
        lineas.append("También hay vías sin registros previos con modalidades ya conocidas: " + "; ".join(
            f"{f['nombre']} en {f['via']} {citar(f['reportes'], 2)}" for f in otras[:3]) + ".")
    return "\n".join(lineas)


def plantilla_contexto(filas: list[dict], p: dict) -> str:
    if not filas:
        return "No encontré páginas oficiales relevantes en el corpus."
    lineas = ["Fragmentos más relevantes de documentos oficiales del corpus (cítelos al usarlos):"]
    for f in filas[:3]:
        lineas.append(f"- **{f['titulo']}** — «{f['fragmento']}» [{f['cita']} p.{f['pagina']}]")
    lineas.append("Las cifras son agregadas (Lima Metropolitana o distrito); no describen calles específicas.")
    return "\n".join(lineas)


def plantilla_conteo(filas: list[dict], p: dict) -> str:
    if not filas:
        return f"No hay incidentes con esos filtros {_periodo(p)}."
    total = sum(f["incidentes"] for f in filas)
    detalle = "; ".join(f"{f['modalidad']}: {f['incidentes']} {citar(f['reportes'], 2)}" for f in filas[:6])
    return f"{_periodo(p).capitalize()} hay **{total} incidentes** con esos filtros. Por modalidad: {detalle}."


def plantilla_libre(filas: list[dict], p: dict) -> str:
    if not filas:
        return "No tengo evidencia en el grafo para responder esa pregunta."
    ids = [f["reporte"] for f in filas if f.get("reporte")]
    if ids:
        return ("No hay una consulta plantilla para esta pregunta (Text2Cypher requiere LLM). "
                "Estos son los relatos más parecidos en el grafo: " + "; ".join(
                    f"{f['fecha']} {f['hora']}: «{f['texto'][:110]}…» [{f['reporte']}]" for f in filas[:4]))
    return "Resultado de la consulta: " + json.dumps(filas[:5], ensure_ascii=False, default=str)


PLANTILLAS = {"patron": plantilla_patron, "intervencion": plantilla_intervencion, "emergente": plantilla_emergente,
              "contexto": plantilla_contexto, "conteo": plantilla_conteo, "libre": plantilla_libre}

SISTEMA = """Eres el analista del sistema Memoria Vial Segura (Los Olivos, Lima). Responde en español, breve (≤ 150 palabras),
SOLO con la evidencia entregada. Cada afirmación lleva cita: [R-000123] para reportes o [INEI-7278873 p.30] para páginas
oficiales, copiadas tal cual de la evidencia. Prohibido inventar cifras, lugares o citas. Si la evidencia no alcanza, dilo.
Si comparas antes/después, aclara que es descriptivo, no causal. No menciones datos de personas."""


def sintetizar(pregunta: str, tipo: str, filas: list[dict], params: dict, permitidas: set[str]) -> tuple[str, str]:
    """Devuelve (texto, modo). Usa LLM si existe y sus citas son válidas; si no, la plantilla."""
    base = PLANTILLAS[tipo](filas, params)
    if not llm.disponible() or not filas:
        return base, "plantilla"
    evidencia = json.dumps([{k: v for k, v in f.items() if k not in ("texto", "embedding")} for f in filas[:25]],
                           ensure_ascii=False, default=str)[:14000]
    try:
        texto = llm.obtener().completar(SISTEMA, f"Pregunta: {pregunta}\nTipo: {tipo}\nParámetros: {params}\n"
                                                 f"Resumen calculado: {base}\nEvidencia: {evidencia}", max_tokens=900)
    except Exception:
        return base, "plantilla"
    return (texto, "LLM") if citas_validas(texto, permitidas) else (base, "plantilla (el LLM citó fuera de la evidencia)")
