"""Boletín para el turno siguiente (Markdown + HTML) en data/boletines/.

Contenido: top 5 tramos calientes de las últimas 72 h por franja, modalidades emergentes,
intervenciones activas o recientes con su tendencia y 3 recomendaciones de patrullaje
redactadas SOLO a partir de los datos, con citas [R-xxxxxx].
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import llm  # noqa: E402
from agente import consultas  # noqa: E402
from grafo.conexion import leer  # noqa: E402
from ontologia.catalogos import FRANJAS  # noqa: E402

log = logging.getLogger("boletin")


def _citas(ids: list[str], n: int = 3) -> str:
    return " ".join(f"[{i}]" for i in ids[:n])


def recopilar(fecha: date) -> dict:
    f = fecha.isoformat()
    calientes, _, _ = consultas.tramos_calientes(f, dias=3, top=5)
    por_franja = {r["franja"]: r["top"] for r in calientes}
    emerg, _, _ = consultas.emergentes((fecha - timedelta(days=6)).isoformat(), f)
    activas = leer("""MATCH (iv:Intervencion) WHERE iv.fecha_inicio <= date($f) AND iv.fecha_fin >= date($f) - duration({days: 30})
                      RETURN DISTINCT iv.tipo AS tipo, toString(iv.fecha_inicio) AS inicio""", f=f)
    intervenciones = []
    for a in activas:
        filas, _, _ = consultas.efecto_intervencion(tipo=a["tipo"], desde=a["inicio"], hasta=a["inicio"],
                                                    modalidades=None if a["tipo"] == "patrullaje reforzado" else
                                                    [m["id"] for m in leer("MATCH (m:Modalidad) RETURN m.id AS id")])
        intervenciones += filas
    corrida = leer("MATCH (c:Corrida {fecha: date($f)}) RETURN c.n_reportes AS n, c.n_ok AS ok, c.n_sin_tramo AS sin_tramo", f=f)
    return {"fecha": f, "por_franja": por_franja, "emergentes": emerg, "intervenciones": intervenciones,
            "corrida": corrida[0] if corrida else None}


def recomendaciones_reglas(d: dict) -> list[str]:
    recs = []
    top = sorted(((t, fr) for fr, lst in d["por_franja"].items() for t in lst), key=lambda x: -x[0]["incidentes"])
    if top:
        t, fr = top[0]
        recs.append(f"Priorizar patrullaje en la franja **{fr}** en {t['via']} cdra. {t['cuadra']} (sector {t['sector']}): "
                    f"{t['incidentes']} incidentes en 72 h ({', '.join(t['modalidades'])}) {_citas(t['reportes'])}.")
    if d["emergentes"]:
        e = d["emergentes"][0]
        recs.append(f"Alertar al turno sobre la modalidad emergente **{e['nombre']}** en {e['via']}, "
                    f"sin registros previos en 30 días {_citas(e['reportes'])}.")
    sin_baja = [i for i in d["intervenciones"] if i["antes"] and i["despues"] >= i["antes"]]
    con_baja = [i for i in d["intervenciones"] if i["antes"] and i["despues"] < i["antes"]]
    if sin_baja:
        i = sin_baja[0]
        recs.append(f"Revisar la intervención {i['intervencion']} ({i['tipo']}) en {i['via']} cdra. {i['cuadra']}: "
                    f"no hubo descenso ({i['antes']} → {i['despues']}) {_citas(i['reportes_despues'])}.")
    elif con_baja:
        i = con_baja[0]
        recs.append(f"Mantener {i['tipo']} en {i['via']} cdra. {i['cuadra']}: bajó de {i['antes']} a {i['despues']} "
                    f"{_citas(i['reportes_antes'])}.")
    return recs[:3]


def recomendaciones_llm(d: dict) -> list[str] | None:
    datos = json.dumps({k: d[k] for k in ("por_franja", "emergentes", "intervenciones")}, ensure_ascii=False, default=str)[:12000]
    sistema = ("Eres analista de seguridad ciudadana de Los Olivos. Redacta exactamente 3 recomendaciones de patrullaje "
               "para el turno siguiente usando SOLO los datos entregados. Cada recomendación debe citar al menos un "
               "reporte con el formato [R-000123] tomado de los datos. No inventes cifras ni lugares. Devuelve JSON "
               '{"recomendaciones": ["...", "...", "..."]}.')
    r = llm.completar_json(sistema, datos, max_tokens=1500)
    if not r or len(r.get("recomendaciones", [])) < 3:
        return None
    validos = set(re.findall(r"R-\d{6}", datos))
    recs = [x for x in r["recomendaciones"][:3] if set(re.findall(r"R-\d{6}", x)) and set(re.findall(r"R-\d{6}", x)) <= validos]
    return recs if len(recs) == 3 else None  # si cita algo inexistente, se descarta


def a_markdown(d: dict, recs: list[str], origen: str) -> str:
    lineas = [f"# Boletín para el turno siguiente — {d['fecha']}", "",
              f"> **{config.ETIQUETA_SINTETICO}.** Distrito de Los Olivos. Generado automáticamente desde el grafo.", ""]
    if d["corrida"]:
        c = d["corrida"]
        lineas += [f"Reportes del día: **{c['n']}** · completos: {c['ok']} · sin tramo resuelto: {c['sin_tramo']}", ""]
    lineas += ["## 1. Tramos calientes (últimas 72 h) por franja", ""]
    for nombre, _, _ in FRANJAS:
        top = d["por_franja"].get(nombre, [])
        lineas.append(f"**{nombre.capitalize()}**")
        if not top:
            lineas += ["- Sin incidentes.", ""]
            continue
        lineas += [f"{k}. {t['via']} cdra. {t['cuadra']} (sector {t['sector']}) — {t['incidentes']} · "
                   f"{', '.join(t['modalidades'])} {_citas(t['reportes'])}" for k, t in enumerate(top, 1)] + [""]
    lineas += ["## 2. Modalidades emergentes (últimos 7 días, sin registros en los 30 previos)", ""]
    lineas += [f"- **{e['nombre']}** (ICCS {e['codigo_iccs']}) en {e['via']}: {e['incidentes']} {_citas(e['reportes'])}"
               for e in d["emergentes"]] or ["- Ninguna."]
    lineas += ["", "## 3. Intervenciones activas o recientes y tendencia (4 semanas antes vs. después)", "",
               "| Intervención | Tipo | Tramo | Antes | Después | Var. % |", "|---|---|---|---|---|---|"]
    lineas += [f"| {i['intervencion']} | {i['tipo']} | {i['via']} cdra. {i['cuadra']} | {i['antes']} | {i['despues']} | "
               f"{'' if i['variacion_pct'] is None else str(i['variacion_pct']) + ' %'} |" for i in d["intervenciones"]]
    lineas += ["", "*Comparación descriptiva, no causal.*", "",
               f"## 4. Recomendaciones de patrullaje ({origen})", ""]
    lineas += [f"{k}. {r}" for k, r in enumerate(recs, 1)] or ["- Sin datos suficientes."]
    return "\n".join(lineas) + "\n"


def generar(fecha: date) -> Path:
    import markdown

    d = recopilar(fecha)
    recs, origen = None, "reglas"
    if llm.disponible():
        recs, origen = recomendaciones_llm(d), "LLM a partir de los datos"
    if not recs:
        recs, origen = recomendaciones_reglas(d), "reglas sobre los datos"
    md = a_markdown(d, recs, origen)
    config.BOLETINES.mkdir(parents=True, exist_ok=True)
    destino = config.BOLETINES / f"boletin_{d['fecha']}.md"
    destino.write_text(md, encoding="utf-8")
    html = markdown.markdown(md, extensions=["tables"])
    (destino.with_suffix(".html")).write_text(
        f"<!doctype html><html lang='es'><head><meta charset='utf-8'><title>Boletín {d['fecha']}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}blockquote{background:#fff3cd;"
        f"margin:0;padding:.5rem 1rem}}</style></head><body>{html}</body></html>", encoding="utf-8")
    log.info("Boletín -> %s", destino)
    return destino


if __name__ == "__main__":
    config.configurar_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat, default=None)
    a = ap.parse_args()
    generar(a.fecha or consultas.fecha_referencia())
