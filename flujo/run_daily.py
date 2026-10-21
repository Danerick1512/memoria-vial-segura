"""Flujo diario idempotente: reportes del día -> PLN -> grafo -> Corrida -> boletín del turno siguiente.

Uso:
  python flujo/run_daily.py --fecha 2026-10-20
  python flujo/run_daily.py --desde 2026-08-01 --hasta 2026-10-20     (backfill)
  python flujo/run_daily.py --simular-dias 3                           (demo: procesa los 3 días pendientes siguientes)
  python flujo/run_daily.py --hoy                                       (tarea programada: último día disponible)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from grafo.cargar import cargar_incidentes  # noqa: E402
from grafo.conexion import escribir, leer  # noqa: E402
from ontologia.catalogos import DIAS  # noqa: E402
from pln.extraer import obtener_extractor  # noqa: E402

log = logging.getLogger("flujo")


def leer_dia(fecha: date) -> list[dict]:
    archivo = config.REPORTES / f"{fecha.isoformat()}.jsonl"
    if not archivo.exists():
        return []
    return [json.loads(l) for l in archivo.read_text(encoding="utf-8").splitlines() if l.strip()]


def procesar_dia(fecha: date, con_boletin: bool = True) -> dict:
    from grafo.embeddings import pasajes

    reportes = leer_dia(fecha)
    if not reportes:  # un día sin reportes también es una corrida (queda constancia de que el flujo se ejecutó)
        log.warning("%s: sin reportes", fecha)
        corrida = {"fecha": fecha.isoformat(), "n_reportes": 0, "n_ok": 0, "n_sin_tramo": 0}
        escribir("""MERGE (c:Corrida {fecha: date($fecha)})
                    SET c.n_reportes = 0, c.n_ok = 0, c.n_sin_tramo = 0, c.ejecutada_en = datetime()""", fecha=corrida["fecha"])
        return corrida
    ext = obtener_extractor()
    filas = []
    for r, vec in zip(reportes, pasajes([r["texto"] for r in reportes])):
        inc = ext.extraer(r["texto"]).model_dump()
        filas.append({**inc, "id": r["id"], "incidente_id": "I-" + r["id"].split("-")[1], "tipo": r["tipo"],
                      "canal": r.get("canal"), "fecha": r["fecha"], "fecha_ingreso": r["fecha_ingreso"],
                      "texto": r["texto"], "dia_semana": DIAS[date.fromisoformat(r["fecha"]).weekday()], "embedding": vec})
    cargar_incidentes(filas)
    config.EXTRAIDOS.mkdir(parents=True, exist_ok=True)
    with open(config.EXTRAIDOS / f"{fecha.isoformat()}.jsonl", "w", encoding="utf-8") as f:
        for fl in filas:
            f.write(json.dumps({k: v for k, v in fl.items() if k != "embedding"}, ensure_ascii=False) + "\n")
    n_ok = sum(1 for f in filas if f["tramo_resuelto"] and f["modalidad"])
    corrida = {"fecha": fecha.isoformat(), "n_reportes": len(filas), "n_ok": n_ok,
               "n_sin_tramo": sum(1 for f in filas if not f["tramo_resuelto"])}
    escribir("""MERGE (c:Corrida {fecha: date($fecha)})
                SET c.n_reportes = $n_reportes, c.n_ok = $n_ok, c.n_sin_tramo = $n_sin_tramo, c.ejecutada_en = datetime()""",
             **corrida)
    log.info("%s: %d reportes, %d completos, %d sin tramo", fecha, len(filas), n_ok, corrida["n_sin_tramo"])
    if con_boletin:
        from boletin.generar import generar

        generar(fecha)
    return corrida


def rango(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def dias_disponibles() -> list[date]:
    return sorted(date.fromisoformat(p.stem) for p in config.REPORTES.glob("*.jsonl"))


def ultimo_procesado() -> date | None:
    r = leer("MATCH (c:Corrida) RETURN max(c.fecha) AS f")
    return r[0]["f"].to_native() if r and r[0]["f"] else None


def simular(n: int) -> list[dict]:
    """Procesa los N días siguientes al último procesado (para la demo en clase)."""
    ultimo = ultimo_procesado()
    pendientes = [d for d in dias_disponibles() if ultimo is None or d > ultimo][:n]
    if not pendientes:
        log.info("No hay días pendientes: el grafo ya está al día")
    return [procesar_dia(d) for d in pendientes]


def revertir_despues_de(fecha: date) -> int:
    """Demo: borra incidentes, reportes y corridas posteriores a `fecha` para volver a simular la llegada de días."""
    r = escribir("""MATCH (i:Incidente)-[:REGISTRADO_EN]->(f:Reporte) WHERE i.fecha > date($f)
                    WITH i, f, i.id AS id DETACH DELETE i, f RETURN count(id) AS n""", f=fecha.isoformat())
    escribir("MATCH (c:Corrida) WHERE c.fecha > date($f) DELETE c", f=fecha.isoformat())
    log.info("Revertido el grafo al %s (%d incidentes borrados)", fecha, r[0]["n"])
    return r[0]["n"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fecha", type=date.fromisoformat)
    ap.add_argument("--desde", type=date.fromisoformat)
    ap.add_argument("--hasta", type=date.fromisoformat)
    ap.add_argument("--simular-dias", type=int)
    ap.add_argument("--hoy", action="store_true", help="procesa el último día disponible (tarea programada)")
    ap.add_argument("--boletin-diario", action="store_true", help="en backfill, genera boletín para cada día")
    ap.add_argument("--revertir-a", type=date.fromisoformat, help="demo: borra lo posterior a esta fecha")
    a = ap.parse_args()
    if a.revertir_a:
        revertir_despues_de(a.revertir_a)
    if a.simular_dias:
        simular(a.simular_dias)
    elif a.desde or a.hasta:
        disponibles = dias_disponibles()
        desde, hasta = a.desde or disponibles[0], a.hasta or disponibles[-1]
        dias = list(rango(desde, hasta))
        for d in dias:
            procesar_dia(d, con_boletin=a.boletin_diario or d == dias[-1])
    elif a.fecha:
        procesar_dia(a.fecha)
    elif a.hoy:
        disponibles = [d for d in dias_disponibles() if d <= date.today()]
        procesar_dia(disponibles[-1])
    elif not a.revertir_a:
        ap.print_help()


if __name__ == "__main__":
    config.configurar_logging()
    main()
