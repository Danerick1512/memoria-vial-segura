"""Evalúa el extractor contra data/ground_truth.json y escribe reports/eval_pln.md."""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from pln.extraer import obtener_extractor  # noqa: E402

log = logging.getLogger("pln.eval")
CAMPOS = ["via", "cuadra", "hora", "franja", "modalidad", "medio", "punto_referencia", "tramo_id"]
META = {"via": 0.85, "modalidad": 0.85}


def leer_reportes() -> list[dict]:
    return [json.loads(l) for f in sorted(config.REPORTES.glob("*.jsonl")) for l in f.read_text(encoding="utf-8").splitlines() if l]


def evaluar() -> dict:
    gt = json.loads(config.GROUND_TRUTH.read_text(encoding="utf-8"))["reportes"]
    ext = obtener_extractor()
    aciertos, por_ruido, errores = Counter(), defaultdict(Counter), defaultdict(list)
    reportes = leer_reportes()
    n_resueltos = 0
    for r in reportes:
        pred = ext.extraer(r["texto"]).model_dump()
        real = gt[r["id"]]
        ruido = real["ruido"] or "limpio"
        por_ruido[ruido]["n"] += 1
        n_resueltos += pred["tramo_resuelto"]
        for c in CAMPOS:
            ok = pred[c] == real[c]
            aciertos[c] += ok
            por_ruido[ruido][c] += ok
            if not ok and len(errores[c]) < 5:
                errores[c].append((r["id"], real[c], pred[c], r["texto"][:140]))
    n = len(reportes)
    return {"n": n, "aciertos": aciertos, "por_ruido": por_ruido, "errores": errores, "resueltos": n_resueltos}


def escribir(res: dict) -> str:
    n = res["n"]
    filas = "\n".join(f"| {c} | {res['aciertos'][c]}/{n} | {100 * res['aciertos'][c] / n:.1f} % | "
                      f"{'≥ ' + str(int(META[c] * 100)) + ' % ' + ('✅' if res['aciertos'][c] / n >= META[c] else '❌') if c in META else ''} |"
                      for c in CAMPOS)
    ruidos = "\n".join(f"| {k} | {v['n']} | " + " | ".join(f"{100 * v[c] / v['n']:.0f} %" for c in ("via", "modalidad", "tramo_id")) + " |"
                       for k, v in sorted(res["por_ruido"].items()))
    errores = "\n".join(f"- **{c}** `{rid}`: esperado `{e}` / obtenido `{p}` — «{t}…»"
                        for c, lst in res["errores"].items() for rid, e, p, t in lst[:3])
    md = f"""# Evaluación del PLN sobre relatos

> {config.ETIQUETA_SINTETICO}. Extractor: reglas + gazetteer OSM + lemas spaCy (respaldo LLM solo si hay
> `ANTHROPIC_API_KEY`). Precisión = coincidencia exacta con `data/ground_truth.json`.

**Reportes evaluados:** {n} · **Tramo resuelto:** {res['resueltos']} ({100 * res['resueltos'] / n:.1f} %)

| Campo | Aciertos | Precisión | Meta |
|---|---|---|---|
{filas}

## Por tipo de relato

`sin_cuadra`: el relato no menciona la cuadra; `sin_via`: solo menciona un punto de referencia.

| Tipo | n | vía | modalidad | tramo |
|---|---|---|---|---|
{ruidos}

En los relatos `sin_via` la vía no aparece en el texto: no resolverla es el comportamiento correcto
(no se inventa); por eso cuentan como fallo en la tabla y como `tramo_resuelto=false` en el grafo.

## Ejemplos de error

{errores or '- (ninguno)'}

## Limitaciones

Los relatos sintéticos se redactan con plantillas; las reglas cubren ese vocabulario. Con relatos
reales (serenazgo) la precisión esperada es menor: por eso existe el respaldo LLM y la interfaz
`Extractor` para enchufar el extractor de la pieza 3.
"""
    config.REPORTS.mkdir(exist_ok=True)
    (config.REPORTS / "eval_pln.md").write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    config.configurar_logging()
    r = evaluar()
    escribir(r)
    for c in CAMPOS:
        log.info("%-17s %.1f %%", c, 100 * r["aciertos"][c] / r["n"])
