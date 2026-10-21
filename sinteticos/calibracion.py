"""Verifica contra el corpus las cifras usadas para calibrar los sintéticos y escribe CALIBRACION.md.

Cada proporción se respalda con un documento y una página de corpus/paginas.jsonl. Si la
página citada no contiene las cifras esperadas, el script falla (no se calibra a ciegas).
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from ontologia.catalogos import MODALIDAD  # noqa: E402
from sinteticos.generar_reportes import PESO_HORA, PESOS_MODALIDAD, TASAS_INEI  # noqa: E402

log = logging.getLogger("calibracion")

FUENTE_PRINCIPAL = ("inei-8556475", 19)
# Etiqueta del gráfico -> (clave TASAS_INEI, valor feb–jul 2026 tal como aparece en el PDF)
ETIQUETAS = {
    "Robo de dinero, cartera, celular": ("robo_dinero_cartera_celular", "11,0"),
    "Intento de robo de dinero, cartera, celular": ("intento_robo_dinero_cartera_celular", "4,7"),
    "Robo  de vehículo": ("robo_vehiculo", "2,1"),
    "Intento de robo de vehículo": ("intento_robo_vehiculo", "1,5"),
    "Amenazas e intimidaciones": ("amenazas", "1,5"),
    "Extorsión": ("extorsion", "1,2"),
    "Robo de negocio": ("robo_negocio", "1,0"),
    "Maltrato y ofensa sexual": ("maltrato_ofensa_sexual", "2,0"),
    "Estafa": ("estafa", "1,9"),
}
CONTEXTO_LOS_OLIVOS = [("sidpol-8482979", 30, "Denuncias por robo y hurto por distrito, 2024 – ene.-jul. 2026"),
                       ("sidpol-8482979", 31, "Denuncias por extorsión por distrito, 2024 – ene.-jul. 2026"),
                       ("inei-8253262", 7, "Robo de vehículos por distrito, II sem. 2025 (Los Olivos +53)")]


def cargar_paginas() -> dict[tuple[str, int], dict]:
    paginas = {}
    with open(config.PAGINAS_JSONL, encoding="utf-8") as f:
        for linea in f:
            d = json.loads(linea)
            paginas[(d["doc_id"], d["pagina"])] = d
    return paginas


def buscar(paginas: dict, prefijo: str, pagina: int) -> dict:
    for (doc, p), d in paginas.items():
        if doc.startswith(prefijo) and p == pagina:
            return d
    raise SystemExit(f"No se encontró {prefijo} p.{pagina} en paginas.jsonl")


def verificar(paginas: dict) -> dict:
    d = buscar(paginas, *FUENTE_PRINCIPAL)
    texto = d["texto"]
    if "LIMA METROPOLITANA" not in texto:
        raise SystemExit("La página citada no es la de Lima Metropolitana")
    lineas = [l.strip() for l in texto.splitlines()]
    for etiqueta, (clave, valor) in ETIQUETAS.items():
        if not any(l.startswith(etiqueta.strip()) for l in lineas):
            raise SystemExit(f"Etiqueta ausente en la página citada: {etiqueta}")
        if valor not in texto:
            raise SystemExit(f"Valor {valor} de {etiqueta} ausente en la página citada")
        if abs(float(valor.replace(",", ".")) - TASAS_INEI[clave]) > 1e-9:
            raise SystemExit(f"TASAS_INEI[{clave}] no coincide con el PDF")
    return d


def escribir(principal: dict, paginas: dict) -> None:
    menciones = sorted({(doc, p) for (doc, p), d in paginas.items() if "Los Olivos" in d["texto"] or "LOS OLIVOS" in d["texto"]})
    total = sum(PESOS_MODALIDAD.values())
    gt = json.loads(config.GROUND_TRUTH.read_text(encoding="utf-8")) if config.GROUND_TRUTH.exists() else None
    obs = Counter(r["modalidad"] for r in gt["reportes"].values()) if gt else Counter()
    n = sum(obs.values()) or 1
    filas = "\n".join(
        f"| {MODALIDAD[m]['nombre']} | {MODALIDAD[m]['codigo_iccs']} | {w:.2f} | {100 * w / total:.1f} % | {100 * obs[m] / n:.1f} % |"
        for m, w in sorted(PESOS_MODALIDAD.items(), key=lambda kv: -kv[1]))
    cita = f"[INEI-{principal['doc_id'].split('-')[1]} p.{principal['pagina']}]"
    contexto = "\n".join(f"- `{doc}` p.{p} — {desc}" for pref, p, desc in CONTEXTO_LOS_OLIVOS
                         for doc in [buscar(paginas, pref, p)["doc_id"]])
    md = f"""# Calibración de los reportes sintéticos

> {config.ETIQUETA_SINTETICO}. Los 400 relatos son una **muestra ilustrativa**: respetan proporciones
> y patrones de fuentes oficiales, pero su volumen no pretende igualar las denuncias reales del distrito.

Archivo generado por `sinteticos/calibracion.py`, que **verifica** que cada cifra existe en la página citada.

## 1. Proporción de modalidades

Fuente: {cita} — INEI, *Estadísticas de Seguridad Ciudadana*, semestre móvil feb–jul 2026, Gráfico 16:
«Lima Metropolitana y la Provincia Constitucional del Callao: población de 15 y más años víctima de algún
hecho delictivo, según tipo» (tasa por cada 100 habitantes). URL oficial: {principal['fuente']}

| Categoría INEI | Tasa feb–jul 2026 |
|---|---|
""" + "\n".join(f"| {e.strip()} | {v} |" for e, (_, v) in ETIQUETAS.items()) + f"""

Se excluyen *delitos informáticos* (no ocurren en la vía pública). Reparto de cada categoría en modalidades
de calle (**supuestos** del equipo, editables en `PESOS_MODALIDAD`):

- Robo de dinero, cartera, celular → 60 % robo de celular, 28 % arrebato de cartera, 12 % cogoteo.
- Intento de robo (dinero/cartera/celular + vehículo) → tentativa de robo.
- Robo de vehículo → 50 % robo de vehículo, 50 % hurto de autopartes.
- Maltrato y ofensa sexual → 25 % (fracción en espacio público: acoso sexual callejero).
- Estafa → 25 % (fracción presencial: estafa al paso).

| Modalidad | ICCS | Peso | % esperado (fondo) | % observado (400 reportes, incl. patrones) |
|---|---|---|---|---|
{filas}

El % observado difiere del esperado porque los patrones plantados (sección 3) añaden robos de celular,
arrebatos, bujiazos y marcajes.

## 2. Supuestos sin fuente oficial a nivel de calle

- **Hora del día**: perfil con pico en 18–21 h (`PESO_HORA` = {PESO_HORA}). No hay cifra oficial por hora
  para Los Olivos en el corpus.
- **Medio** (moto, a pie, mototaxi…) por modalidad: `MEDIOS_POR_MODALIDAD`, criterio experto.
- **Ubicación**: avenidas pesan 3× y tramos con POI a ≤100 m pesan 1,5×.
- **Fin de semana** (viernes–domingo) pesa 1,25×.

## 3. Patrones plantados (verificables en `data/ground_truth.json`)

1. **P1** – Clúster de robo de celular desde moto, 18:00–19:59, en cuadras a ≤100 m de paraderos de las 3
   avenidas con más paraderos, del 14 al 20 de octubre de 2026.
2. **P2** – Patrullaje reforzado (7 set – 4 oct 2026) en 5 tramos: arrebatos 4 semanas antes vs. 4 semanas
   durante; 4 tramos bajan y 1 no baja.
3. **P3** – Modalidades nuevas (bujiazo, marcaje) solo en la última semana, en vías sin ningún registro
   en los 30 días previos.

## 4. Contexto oficial de Los Olivos (documentos citables)

Páginas del corpus que mencionan Los Olivos: **{len(menciones)}**. Las más útiles como contexto:

{contexto}

Estas páginas se cargan como `(:Documento)-[:TIENE_PAGINA]->(:Pagina)` y el agente las cita como
`[SIDPOL-8482979 p.30]`.
"""
    destino = Path(__file__).with_name("CALIBRACION.md")
    destino.write_text(md, encoding="utf-8")
    log.info("Calibración verificada; %d páginas mencionan Los Olivos -> %s", len(menciones), destino.name)


if __name__ == "__main__":
    config.configurar_logging()
    pags = cargar_paginas()
    escribir(verificar(pags), pags)
