"""Router y extracción de parámetros de la pregunta.

Primero reglas (deterministas, sin costo); si hay LLM, este clasifica y rellena SOLO los
parámetros que falten, con salida JSON validada por Pydantic.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
from ontologia.catalogos import FRANJAS, MEDIOS, MODALIDAD  # noqa: E402
from pln.extraer import extraer_modalidad  # noqa: E402
from pln.gazetteer import TIPOS_VIA, cargar, normalizar  # noqa: E402
from geo.construir_tramos import sin_tildes  # noqa: E402

log = logging.getLogger("agente.router")

Tipo = Literal["patron", "intervencion", "emergente", "contexto", "conteo", "libre", "fuera_de_alcance", "privacidad"]
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


class Parametros(BaseModel):
    modalidad: Optional[str] = None
    arrebatos: bool = False
    medio: Optional[str] = None
    hora_desde: Optional[str] = None
    hora_hasta: Optional[str] = None
    franja: Optional[str] = None
    desde: Optional[str] = None
    hasta: Optional[str] = None
    poi_tipo: Optional[str] = None
    sector: Optional[str] = None
    via: Optional[str] = None
    iccs_prefijo: Optional[str] = None
    tipo_intervencion: Optional[str] = None


class Ruta(BaseModel):
    tipo: Tipo
    parametros: Parametros
    origen: Literal["reglas", "llm"] = "reglas"


# --- Reglas ----------------------------------------------------------------------------------
RE_PRIVACIDAD = re.compile(r"\b(nombre[s]? de|dni|placa|rostro|identidad|quien (es|fue|era)|sospechos|datos personales|"
                           r"direccion de la victima|telefono de|apellido)")
RE_DOMINIO = re.compile(r"(rob|hurt|arrebat|asalt|incident|delit|patrull|intervenc|modalidad|tramo|cuadra|avenida|\bav\b|"
                        r"sector|inei|sidpol|denuncia|seguridad|victim|celular|extors|paradero|crimin|cogote|bujiazo|marcaje|"
                        r"los olivos|calle|jiron|reporte|boletin|turno|iluminac|estafa|acoso|amenaz)")
REGLAS_TIPO = [
    ("intervencion", r"(patrull|intervenc|iluminac|funcion[oó]|efecto|bajaron|disminu|redujo|reduj|antes y despu|descend)"),
    ("emergente", r"(nueva|nuevas|nuevo|emergent|aparecier|novedad|surgi)"),
    ("contexto", r"(inei|sidpol|estadistic|lima metropolitana|nacional|oficial|tasa|victimizac|segun (el|la|los)|ranking|informe)"),
    ("patron", r"(donde|concentr|calientes|zonas|patron|cluster|cuadras|tramos|puntos criticos|focos)"),
    ("conteo", r"(cuant|numero de|total de|cantidad)"),
]


def detectar_horas(q: str) -> tuple[str | None, str | None]:
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(?:h|horas|hrs)?\s*(?:y|a|-|–|hasta)\s*(?:las\s*)?(\d{1,2})(?::(\d{2}))?\s*"
                  r"(pm|p m|de la noche|de la tarde|am|a m)?", q)
    if not m:
        return None, None
    h1, h2 = int(m.group(1)), int(m.group(3))
    sufijo = m.group(5) or ""
    if sufijo.startswith(("pm", "p m", "de la")) or ("noche" in q and h2 <= 12):
        h1, h2 = (h1 + 12 if h1 < 12 else h1), (h2 + 12 if h2 < 12 else h2)
    if not (0 <= h1 < 24 and 0 < h2 <= 24 and h1 < h2):
        return None, None
    return f"{h1:02d}:{m.group(2) or '00'}", ("24:00" if h2 == 24 else f"{h2:02d}:{m.group(4) or '00'}")


def detectar_fechas(q: str, ref: date) -> tuple[str | None, str | None]:
    if re.search(r"(ultima semana|esta semana|ultimos 7 dias|semana pasada)", q):
        return (ref - timedelta(days=6)).isoformat(), ref.isoformat()
    if re.search(r"(ultimas 72|ultimos 3 dias|ultimos tres dias)", q):
        return (ref - timedelta(days=2)).isoformat(), ref.isoformat()
    if re.search(r"(ultimo mes|ultimos 30 dias)", q):
        return (ref - timedelta(days=29)).isoformat(), ref.isoformat()
    if re.search(r"\b(hoy|ayer)\b", q):
        d = ref if "hoy" in q else ref - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    for nombre, mes in MESES.items():
        if re.search(rf"\b{nombre}\b", q):
            anio = 2026
            ini = date(anio, mes, 1)
            fin = (date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1))
            return ini.isoformat(), min(fin, ref).isoformat()
    return None, None


def detectar_via(q: str) -> str | None:
    """Vía mencionada en la pregunta: exige tipo de vía escrito o un alias de 2+ palabras (evita 'Lima Metropolitana')."""
    gaz = cargar()
    con_tipo = re.search(r"\b(" + "|".join(TIPOS_VIA) + r")\s", q)
    mejores = sorted(((-(m.end() - m.start()), m.group(1)) for m in gaz.patron_alias().finditer(q)
                      if (con_tipo or len(m.group(1).split()) >= 2) and "lima" not in m.group(1)), key=lambda x: x[0])
    if not mejores:
        return None
    vias = gaz.alias[mejores[0][1]]
    return vias[0] if len(vias) == 1 else None


def parametros_reglas(pregunta: str, ref: date) -> Parametros:
    q = normalizar(pregunta)
    p = Parametros()
    p.arrebatos = bool(re.search(r"arrebat", q))
    p.modalidad = None if p.arrebatos and "celular" not in q else extraer_modalidad(q, set())
    if re.search(r"(desde|en|a bordo de)( una)? (moto|motocicleta)\b|motorizad|\bmotos?\b", q) and "mototaxi" not in q:
        p.medio = "moto"
    else:
        p.medio = next((m for m in MEDIOS if m != "moto" and re.search(rf"\b{m}\b", q)), None)
    p.hora_desde, p.hora_hasta = detectar_horas(sin_tildes(pregunta.lower()))
    p.franja = next((n for n, _, _ in FRANJAS if re.search(rf"\b{normalizar(n)}\b", q)), None)
    if p.franja and not p.hora_desde:
        _, a, b = next(f for f in FRANJAS if f[0] == p.franja)
        p.hora_desde, p.hora_hasta = f"{a:02d}:00", ("24:00" if b == 24 else f"{b:02d}:00")
    p.desde, p.hasta = detectar_fechas(q, ref)
    p.poi_tipo = next((t for t in ("paradero", "mercado", "colegio", "parque", "banco") if t in q), None)
    m = re.search(r"sector\s*s?(\d)", q)
    p.sector = f"S{m.group(1)}" if m else None
    p.via = detectar_via(q)
    if p.modalidad is None and not p.arrebatos and re.search(r"\brob(o|os|ar|aron)\b", q):
        p.iccs_prefijo = "04"  # "robos" en general: familia ICCS 04 (robo)
    p.tipo_intervencion = ("patrullaje reforzado" if "patrull" in q else "mejora de iluminación" if "iluminac" in q else None)
    return p


def tipo_reglas(pregunta: str) -> Tipo:
    q = normalizar(pregunta)
    if RE_PRIVACIDAD.search(q):
        return "privacidad"
    if not RE_DOMINIO.search(q):
        return "fuera_de_alcance"
    for tipo, patron in REGLAS_TIPO:
        if re.search(patron, q):
            if tipo == "emergente" and not re.search(r"(modalidad|delito|tipo|forma)", q):
                continue
            return tipo  # type: ignore[return-value]
    return "libre"


# --- LLM ---------------------------------------------------------------------------------------
SISTEMA_ROUTER = f"""Clasificas preguntas sobre incidentes delictivos a nivel de calle en Los Olivos (Lima) y extraes parámetros.
Tipos: patron (dónde/cuándo se concentran incidentes), intervencion (efecto de patrullaje u otra intervención),
emergente (modalidades nuevas o recientes), contexto (cifras oficiales INEI/SIDPOL), conteo (cuántos),
libre (otra consulta sobre el grafo), privacidad (pide datos de personas: nombres, DNI, placas, rasgos — Ley 29733),
fuera_de_alcance (no trata de seguridad ciudadana en Los Olivos).
modalidad ∈ {list(MODALIDAD)}; medio ∈ {MEDIOS}; franja ∈ {[f[0] for f in FRANJAS]}; poi_tipo ∈ [paradero, mercado, colegio, parque, banco];
fechas ISO AAAA-MM-DD; horas HH:MM. Usa null si no aplica. No inventes.
Formato: {{"tipo": "...", "parametros": {{"modalidad": null, "arrebatos": false, "medio": null, "hora_desde": null,
"hora_hasta": null, "franja": null, "desde": null, "hasta": null, "poi_tipo": null, "sector": null, "via": null,
"tipo_intervencion": null}}}}"""


def enrutar(pregunta: str, ref: date) -> Ruta:
    reglas = Ruta(tipo=tipo_reglas(pregunta), parametros=parametros_reglas(pregunta, ref))
    if not llm.disponible() or reglas.tipo == "privacidad":
        return reglas
    datos = llm.completar_json(SISTEMA_ROUTER + f"\nFecha de referencia (último día con datos): {ref.isoformat()}.", pregunta)
    try:
        ruta_llm = Ruta(**datos, origen="llm") if datos else None
    except ValidationError as e:
        log.warning("Router LLM inválido, se usan reglas: %s", e)
        ruta_llm = None
    if ruta_llm is None:
        return reglas
    # Las reglas mandan en lo que detectaron; el LLM solo rellena huecos
    fusion = reglas.parametros.model_dump()
    for k, v in ruta_llm.parametros.model_dump().items():
        if fusion.get(k) in (None, False) and v not in (None, False):
            fusion[k] = v
    if fusion.get("via") and fusion["via"] not in cargar().vias:
        fusion["via"] = detectar_via(normalizar(fusion["via"]))
    if fusion.get("modalidad") not in (None, *MODALIDAD):
        fusion["modalidad"] = None
    return Ruta(tipo=ruta_llm.tipo, parametros=Parametros(**fusion), origen="llm")
