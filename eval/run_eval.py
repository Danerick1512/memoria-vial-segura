"""Evalúa el agente GraphRAG (y la línea base RAG vectorial) y escribe reports/eval_graphrag.md.

Métricas: respuesta correcta (chequeo automático contra ground_truth), % de respuestas con al
menos una cita válida (la cita existe en el grafo) y latencia.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import llm  # noqa: E402
from agente import consultas  # noqa: E402
from agente.agente import responder  # noqa: E402
from eval import rag_simple  # noqa: E402
from grafo.conexion import leer  # noqa: E402
from grafo.embeddings import consulta  # noqa: E402

log = logging.getLogger("eval")


def citas_validas(citas: list[str]) -> list[str]:
    ok = []
    for c in citas:
        if re.fullmatch(r"R-\d{6}", c):
            if leer("MATCH (r:Reporte {id: $id}) RETURN r.id", id=c):
                ok.append(c)
        elif m := re.fullmatch(r"(.+) p\.(\d+)", c):
            if leer("MATCH (:Documento {cita: $c})-[:TIENE_PAGINA]->(p:Pagina {pagina: $p}) RETURN p.id", c=m.group(1), p=int(m.group(2))):
                ok.append(c)
    return ok


def conteo_gt(gt: dict, filtros: dict) -> int:
    return sum(1 for r in gt["reportes"].values()
               if filtros["desde"] <= r["fecha"] <= filtros["hasta"]
               and (not filtros.get("modalidad") or r["modalidad"] == filtros["modalidad"])
               and (not filtros.get("sector") or r["sector"] == filtros["sector"]))


def correcta(q: dict, est: dict, tipo: str | None, gt: dict) -> bool:
    pat = gt["patrones"]
    chk = q["check"]
    if chk == "p1":
        plantados = {t for t, n in pat["P1"]["tramos"].items() if n >= 4}
        return plantados <= set(est.get("tramos", [])[:len(plantados)]) and set(pat["P1"]["avenidas"]) <= set(est.get("vias", [])[:3])
    if chk in ("p2", "p2_via"):
        iv = est.get("intervenciones", {})
        tramos = {t: v for t, v in pat["P2"]["tramos"].items() if chk == "p2" or t.startswith(q["via"].replace("Avenida ", "AV_").upper().replace(" ", "_"))}
        return bool(tramos) and all(iv.get(t) == [v["antes"], v["despues"]] for t, v in tramos.items())
    if chk == "p3":
        esperado = {(m, v) for m, vias in pat["P3"]["modalidades"].items() for v in vias}
        return {tuple(x) for x in est.get("emergentes", [])} == esperado
    if chk == "p3_modalidad":
        return {x[0] for x in est.get("emergentes", [])} == set(pat["P3"]["modalidades"])
    if chk == "pagina":
        return bool(set(q["esperado"]) & set(est.get("paginas", []) + est.get("citas", [])))
    if chk == "conteo":
        return est.get("total") == conteo_gt(gt, q["filtros"])
    if chk == "tipo":
        return tipo == q["esperado"]
    raise ValueError(chk)


def evaluar() -> dict:
    spec = yaml.safe_load((Path(__file__).with_name("preguntas.yaml")).read_text(encoding="utf-8"))
    gt = json.loads(config.GROUND_TRUTH.read_text(encoding="utf-8"))
    ref = consultas.fecha_referencia()
    consulta("calentamiento")  # carga el modelo de embeddings fuera de la medición
    filas = []
    for q in spec["preguntas"]:
        t0 = time.perf_counter()
        r = responder(q["pregunta"])
        lat = time.perf_counter() - t0
        validas = citas_validas(r.citas)
        fila = {"id": q["id"], "pregunta": q["pregunta"], "tipo": r.tipo, "ok": correcta(q, r.estructura, r.tipo, gt),
                "n_citas": len(r.citas), "citas_validas": len(validas), "latencia": lat, "modo": r.modo}
        if q["id"] in spec["multi_salto"]:
            t0 = time.perf_counter()
            b = rag_simple.responder(q["pregunta"], ref)
            fila["base_ok"] = correcta(q, b, None, gt)
            fila["base_latencia"] = time.perf_counter() - t0
        filas.append(fila)
        log.info("%-4s %-16s ok=%s citas=%d/%d %.2fs", q["id"], r.tipo, fila["ok"], len(validas), len(r.citas), lat)
    return {"filas": filas, "multi": spec["multi_salto"]}


def escribir(res: dict) -> str:
    filas = res["filas"]
    con_cita_esperada = [f for f in filas if f["tipo"] not in ("fuera_de_alcance", "privacidad")]
    pct_ok = 100 * sum(f["ok"] for f in filas) / len(filas)
    pct_cita = 100 * sum(f["citas_validas"] > 0 for f in con_cita_esperada) / len(con_cita_esperada)
    todas_validas = all(f["citas_validas"] == f["n_citas"] for f in filas)
    lat = [f["latencia"] for f in filas]
    multi = [f for f in filas if "base_ok" in f]
    tabla = "\n".join(f"| {f['id']} | {f['pregunta'][:80]}{'…' if len(f['pregunta']) > 80 else ''} | {f['tipo']} | "
                      f"{'✅' if f['ok'] else '❌'} | {f['citas_validas']}/{f['n_citas']} | {f['latencia']:.2f} s |" for f in filas)
    comp = "\n".join(f"| {f['id']} | {'✅' if f['ok'] else '❌'} | {'✅' if f['base_ok'] else '❌'} |" for f in multi)
    g_ok, b_ok = sum(f["ok"] for f in multi), sum(f["base_ok"] for f in multi)
    md = f"""# Evaluación del agente GraphRAG

> {config.ETIQUETA_SINTETICO}. Modo: **{'Claude ' + config.LLM_MODEL if llm.disponible() else 'reglas + plantillas Cypher (sin LLM)'}**.
> Correcta = chequeo automático contra `data/ground_truth.json` (ver `eval/preguntas.yaml`).

## Resumen

| Métrica | Valor |
|---|---|
| Respuestas correctas | **{sum(f['ok'] for f in filas)}/{len(filas)} ({pct_ok:.0f} %)** |
| Respuestas con ≥ 1 cita válida (excluye fuera de alcance/privacidad) | **{pct_cita:.0f} %** |
| Todas las citas emitidas existen en el grafo | {'sí' if todas_validas else 'no'} |
| Latencia mediana / máxima | {statistics.median(lat):.2f} s / {max(lat):.2f} s |

## Detalle por pregunta

| id | Pregunta | Tipo | Correcta | Citas válidas | Latencia |
|---|---|---|---|---|---|
{tabla}

## GraphRAG vs. RAG vectorial simple (preguntas multi-salto)

La línea base recupera los {rag_simple.K} relatos más similares (índice vectorial de `Reporte`) y los lee con
el mismo extractor PLN, sin usar relaciones del grafo.

| id | GraphRAG | RAG vectorial |
|---|---|---|
{comp}
| **Total** | **{g_ok}/{len(multi)}** | **{b_ok}/{len(multi)}** |

**Por qué gana el grafo:** las preguntas requieren saltos que no están en el texto de ningún relato:
*cerca de un paradero* (`Tramo-[:CERCA_DE]->PuntoInteres`), *tramos con patrullaje* (`Intervencion-[:APLICADA_EN]->Tramo`)
con conteos en ventanas de 4 semanas, y *novedad* (ausencia de registros en los 30 días previos), que exige
recorrer toda la historia y no solo los k fragmentos más parecidos.

## Notas

- Las latencias de las preguntas de contexto incluyen el cálculo del embedding de la consulta en CPU.
- **Sesgo a declarar:** las preguntas de evaluación y las reglas del router las escribió el mismo equipo, y los
  relatos salen de plantillas. Este 100 % es una **prueba de regresión** del prototipo, no una medida de
  generalización: con preguntas libres de usuarios reales se esperan fallos de enrutamiento (para eso
  existen el router LLM y Text2Cypher cuando hay `ANTHROPIC_API_KEY`).
- La línea base no tiene LLM: "lee" los k relatos con el mismo extractor. Un LLM sobre esos k relatos tampoco
  podría contar arrebatos en ventanas de 4 semanas ni afirmar ausencia de registros en 30 días.
- La comparación antes/después es descriptiva, no causal.
"""
    config.REPORTS.mkdir(exist_ok=True)
    (config.REPORTS / "eval_graphrag.md").write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    config.configurar_logging()
    escribir(evaluar())
    print((config.REPORTS / "eval_graphrag.md").read_text(encoding="utf-8"))
