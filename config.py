"""Configuración centralizada de Memoria Vial Segura (rutas, Neo4j, LLM, embeddings)."""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")

# --- Rutas -------------------------------------------------------------------
CORPUS = RAIZ.parent / "corpus"
PAGINAS_JSONL = CORPUS / "paginas.jsonl"
INVENTARIO_CSV = CORPUS / "inventario.csv"
TRIPLETAS_JSON = CORPUS / "vigia-lima-nlp" / "output" / "tripletas_extraidas.json"

DATA = RAIZ / "data"
GEO = DATA / "geo"
REPORTES = DATA / "reportes"
BOLETINES = DATA / "boletines"
GROUND_TRUTH = DATA / "ground_truth.json"
INTERVENCIONES_CSV = DATA / "intervenciones.csv"
EXTRAIDOS = DATA / "extraidos"
REPORTS = RAIZ / "reports"

# --- Dominio -----------------------------------------------------------------
DISTRITO_UBIGEO = "150117"
DISTRITO_NOMBRE = "Los Olivos"
OSM_RELACION_LOS_OLIVOS = 1944759
FECHA_INICIO = date(2026, 8, 1)
FECHA_FIN = date(2026, 10, 20)
N_REPORTES = 400
SEMILLA = 2026
LONGITUD_TRAMO_M = 100
RADIO_POI_M = 100
N_SECTORES = 7
CRS_METRICO = "EPSG:32718"  # UTM 18S, Lima

# --- Neo4j -------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- LLM y embeddings ----------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")
EMBED_DIM = 384

ETIQUETA_SINTETICO = "Datos sintéticos — prototipo TRL 4"


def configurar_logging(nivel: int = logging.INFO) -> None:
    import sys

    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")
    logging.basicConfig(level=nivel, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for ruidoso in ("neo4j", "httpx", "httpx2", "huggingface_hub", "sentence_transformers", "urllib3"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
