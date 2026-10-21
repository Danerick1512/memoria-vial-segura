"""Prepara todo de punta a punta: OSM -> tramos -> sintéticos -> calibración -> grafo -> backfill -> evaluación.

Uso:  python preparar.py            (todo)
      python preparar.py --rapido   (sin capa de documentos/embeddings de páginas)
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
log = logging.getLogger("preparar")


def paso(nombre: str, *args: str) -> None:
    log.info("==> %s", nombre)
    r = subprocess.run([sys.executable, *args], cwd=RAIZ)
    if r.returncode != 0:
        raise SystemExit(f"Falló el paso '{nombre}' (código {r.returncode})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rapido", action="store_true")
    a = ap.parse_args()
    paso("Descargar OSM (con caché)", "geo/descargar_osm.py")
    paso("Segmentar tramos, CERCA_DE y sectores", "geo/construir_tramos.py")
    paso("Generar 400 reportes sintéticos", "sinteticos/generar_reportes.py")
    paso("Verificar calibración contra el corpus", "sinteticos/calibracion.py")
    paso("Exportar ontología OWL/Turtle", "ontologia/exportar_ttl.py")
    paso("Cargar grafo base", "grafo/cargar.py", *(["--sin-documentos"] if a.rapido else []))
    paso("Backfill 1 ago – 20 oct 2026", "flujo/run_daily.py", "--desde", "2026-08-01", "--hasta", "2026-10-20")
    paso("Evaluar PLN", "pln/evaluar.py")
    if not a.rapido:
        paso("Evaluar GraphRAG", "eval/run_eval.py")
    log.info("Listo. Abre la demo con:  streamlit run app/streamlit_app.py")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    main()
