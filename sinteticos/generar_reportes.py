"""Genera 400 reportes sintéticos de incidentes en Los Olivos (1 ago – 20 oct 2026).

Relatos libres en español de serenazgo/PNP, sobre tramos reales de OSM, calibrados con
cifras agregadas del corpus (ver sinteticos/CALIBRACION.md). Planta tres patrones
verificables para las preguntas de la diapositiva 5. Cero datos personales.

Salidas: data/reportes/AAAA-MM-DD.jsonl, data/ground_truth.json, data/intervenciones.csv
"""
from __future__ import annotations

import csv
import json
import logging
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from ontologia.catalogos import ARREBATOS, DIAS, MODALIDAD, franja_de  # noqa: E402

log = logging.getLogger("sinteticos")

# --- Calibración (ver CALIBRACION.md) ----------------------------------------------
# INEI 8556475 p.19, Lima Metropolitana y Callao, feb–jul 2026 (tasa por 100 hab.)
TASAS_INEI = {
    "robo_dinero_cartera_celular": 11.0,
    "intento_robo_dinero_cartera_celular": 4.7,
    "robo_vehiculo": 2.1,
    "intento_robo_vehiculo": 1.5,
    "amenazas": 1.5,
    "extorsion": 1.2,
    "robo_negocio": 1.0,
    "maltrato_ofensa_sexual": 2.0,
    "estafa": 1.9,
}
# Reparto de cada categoría INEI en modalidades de calle (supuestos documentados)
PESOS_MODALIDAD = {
    "robo_celular": TASAS_INEI["robo_dinero_cartera_celular"] * 0.60,
    "arrebato_cartera": TASAS_INEI["robo_dinero_cartera_celular"] * 0.28,
    "cogoteo": TASAS_INEI["robo_dinero_cartera_celular"] * 0.12,
    "tentativa_robo": TASAS_INEI["intento_robo_dinero_cartera_celular"] + TASAS_INEI["intento_robo_vehiculo"],
    "robo_vehiculo": TASAS_INEI["robo_vehiculo"] * 0.5,
    "hurto_autopartes": TASAS_INEI["robo_vehiculo"] * 0.5,
    "amenazas": TASAS_INEI["amenazas"],
    "extorsion": TASAS_INEI["extorsion"],
    "robo_negocio": TASAS_INEI["robo_negocio"],
    "acoso_sexual": TASAS_INEI["maltrato_ofensa_sexual"] * 0.25,  # solo la fracción en vía pública
    "estafa_paso": TASAS_INEI["estafa"] * 0.25,                   # solo la fracción presencial
}
MEDIOS_POR_MODALIDAD = {
    "robo_celular": {"moto": 45, "a pie": 38, "mototaxi": 10, "auto": 4, "bicicleta": 3},
    "arrebato_cartera": {"moto": 40, "a pie": 45, "mototaxi": 8, "bicicleta": 7},
    "cogoteo": {"a pie": 70, "auto": 20, "mototaxi": 10},
    "tentativa_robo": {"moto": 40, "a pie": 50, "auto": 10},
    "robo_vehiculo": {"auto": 50, "moto": 50},
    "hurto_autopartes": {"a pie": 80, "auto": 20},
    "amenazas": {"a pie": 85, "moto": 15},
    "extorsion": {"moto": 60, "a pie": 40},
    "robo_negocio": {"moto": 45, "a pie": 45, "auto": 10},
    "acoso_sexual": {"a pie": 75, "auto": 25},
    "estafa_paso": {"a pie": 100},
    "bujiazo": {"a pie": 60, "auto": 40},
    "marcaje": {"moto": 80, "auto": 20},
}
# Supuesto: perfil horario con picos en salida laboral (18–21 h); sin fuente oficial por hora.
PESO_HORA = [2, 1, 1, 1, 1, 2, 4, 6, 6, 5, 4, 4, 5, 5, 5, 6, 7, 8, 11, 12, 11, 9, 6, 3]

# --- Periodos de los patrones ---------------------------------------------------------
ULTIMA_SEMANA = (date(2026, 10, 14), date(2026, 10, 20))
INTERVENCION = (date(2026, 9, 7), date(2026, 10, 4))      # patrullaje reforzado (4 semanas)
ANTES = (INTERVENCION[0] - timedelta(days=28), INTERVENCION[0] - timedelta(days=1))
DESPUES = INTERVENCION

# --- Plantillas de redacción ---------------------------------------------------------------
APERTURAS = ["Siendo aprox. las {h}", "A las {h} aprox.", "Siendo las {h}", "Aproximadamente a las {h}",
             "Se reporta que a las {h}", "Hoy a las {h}"]
LUGARES = ["en la cdra. {c} de {v}", "en la cuadra {c} de {v}", "a la altura de la cdra. {c} de {v}",
           "en {v} cuadra {c}", "en {v} cdra {c}", "en {v}, cuadra {c},"]
SUJETOS = ["dos sujetos", "un sujeto", "tres sujetos", "dos desconocidos", "un individuo", "dos delincuentes"]
MEDIO_TXT = {
    "moto": ["a bordo de una motocicleta", "en moto lineal", "que se desplazaban en una motocicleta", "en una moto"],
    "a pie": ["a pie", "que se acercaron caminando", "que luego huyeron a pie"],
    "auto": ["a bordo de un auto", "en un vehículo particular", "que bajaron de un automóvil"],
    "mototaxi": ["a bordo de una mototaxi", "en un mototaxi"],
    "bicicleta": ["en bicicleta", "a bordo de una bicicleta"],
}
HECHOS = {
    "robo_celular": ["{s} {m} arrebataron el celular a un transeúnte que esperaba movilidad",
                     "{s} {m} sustrajeron el teléfono celular a una ciudadana",
                     "{s} {m} le robaron el equipo móvil a un vecino",
                     "{s} {m} arrebataron un celular a una persona que caminaba por la vereda"],
    "arrebato_cartera": ["{s} {m} arrebataron la cartera a una vecina",
                         "{s} {m} jalonearon y se llevaron el bolso de una transeúnte",
                         "{s} {m} le arrancaron la mochila a un estudiante"],
    "cogoteo": ["{s} {m} sujetaron del cuello a un ciudadano y le sustrajeron sus pertenencias (cogoteo)",
                "{s} {m} cogotearon a un transeúnte y le quitaron su billetera"],
    "tentativa_robo": ["{s} {m} intentaron robar a un transeúnte, pero huyeron ante la presencia de vecinos",
                       "{s} {m} intentaron asaltar a una persona sin lograr su objetivo"],
    "robo_vehiculo": ["{s} {m} despojaron a un conductor de su vehículo bajo amenaza",
                      "{s} {m} robaron una motocicleta que estaba siendo estacionada"],
    "hurto_autopartes": ["{s} {m} sustrajeron los espejos de un vehículo estacionado",
                         "se reporta el hurto de autopartes (faros y espejos) de un auto estacionado; {s} {m} fueron vistos huyendo"],
    "robo_negocio": ["{s} {m} ingresaron a una bodega y robaron el dinero de la caja",
                     "{s} {m} asaltaron un establecimiento comercial de la zona"],
    "extorsion": ["un comerciante de la zona denunció haber recibido una carta extorsiva dejada por {s} {m}",
                  "se reporta extorsión a un negocio: {s} {m} exigieron pagos a cambio de «protección»"],
    "amenazas": ["{s} {m} amenazaron con arma blanca a transeúntes",
                 "{s} {m} intimidaron a vecinos con amenazas verbales"],
    "acoso_sexual": ["se reporta acoso sexual verbal contra una transeúnte por parte de {s} {m}",
                     "{s} {m} acosaron sexualmente a una peatona con frases obscenas"],
    "estafa_paso": ["una vecina fue víctima de estafa al paso con el «cuento» de un falso premio por parte de {s} {m}",
                    "{s} {m} estafaron a un adulto mayor con el «cuento del sobre»"],
    "bujiazo": ["{s} {m} rompieron la luna de un vehículo estacionado con una bujía y sustrajeron una mochila (bujiazo)",
                "se reporta un bujiazo: {s} {m} reventaron la ventana de un auto y se llevaron pertenencias"],
    "marcaje": ["una persona que había retirado dinero de la agencia bancaria fue interceptada por {s} {m} que la venían siguiendo (marcaje)",
                "{s} {m} interceptaron a un cliente que salía del banco y le robaron el dinero retirado (marcaje)"],
}
REFERENCIAS = {
    "paradero": ["cerca del paradero", "junto al paradero de buses", "a pocos metros del paradero"],
    "mercado": ["frente a {n}", "por inmediaciones de {n}"],
    "colegio": ["cerca de {n}", "frente a {n}"],
    "parque": ["junto a {n}", "por {n}"],
    "banco": ["frente a la agencia {n}", "cerca de la agencia {n}"],
}
GENERICO = {"mercado": "mercado", "colegio": "colegio", "parque": "parque", "banco": "bancaria"}
# Conjugación en singular cuando el sujeto es uno solo
SINGULAR = {"arrebataron": "arrebató", "sustrajeron": "sustrajo", "robaron": "robó", "jalonearon": "jaloneó",
            "llevaron": "llevó", "arrancaron": "arrancó", "sujetaron": "sujetó", "cogotearon": "cogoteó",
            "quitaron": "quitó", "intentaron": "intentó", "huyeron": "huyó", "despojaron": "despojó",
            "ingresaron": "ingresó", "asaltaron": "asaltó", "exigieron": "exigió", "amenazaron": "amenazó",
            "intimidaron": "intimidó", "acosaron": "acosó", "estafaron": "estafó", "rompieron": "rompió",
            "reventaron": "reventó", "interceptaron": "interceptó", "venían": "venía", "fueron vistos": "fue visto",
            "acercaron": "acercó", "desplazaban": "desplazaba", "bajaron": "bajó"}


FEMENINOS = ("institución", "i.e.", "i.e", "universidad", "plaza", "academia", "escuela")


def nombre_poi(poi: dict) -> str:
    """Nombre del POI con artículo, sin duplicar el tipo ('el mercado Mercado X')."""
    n, tipo = poi["nombre"], poi["tipo"]
    if tipo == "paradero":
        return n
    if tipo == "banco":
        return n if n != "Agencia bancaria" else "bancaria"
    if n.lower() in ("mercado", "colegio", "parque"):
        return f"el {GENERICO[tipo]}"
    primera = n.split()[0].lower()
    if primera in FEMENINOS:
        return f"la {n}"
    if primera in ("mercado", "colegio", "parque", "supermercado", "centro", "instituto", "complejo"):
        return f"el {n}"
    return f"el {GENERICO[tipo]} {n}"


def contraer(texto: str) -> str:
    """'a el' -> 'al', 'de el' -> 'del'."""
    return re.sub(r"\b([Aa]) el\b", r"\1l", re.sub(r"\b([Dd]e) el\b", r"\1l", texto))
CIERRES = ["Se dio aviso a la comisaría del sector.", "El personal de serenazgo acudió sin ubicar a los autores.",
           "La víctima no requirió atención médica.", "Se orientó a la víctima para formular la denuncia.",
           "Se solicitará revisar las cámaras de videovigilancia.", "Los autores huyeron con dirección desconocida."]
CANALES = ["serenazgo", "serenazgo", "parte"]


class Generador:
    def __init__(self, semilla: int = config.SEMILLA):
        self.rnd = random.Random(semilla)
        feats = json.loads((config.GEO / "tramos.geojson").read_text(encoding="utf-8"))["features"]
        self.tramos = {f["properties"]["id"]: f["properties"] for f in feats}
        pois = json.loads((config.GEO / "pois.geojson").read_text(encoding="utf-8"))["features"]
        self.pois = {p["properties"]["osm_id"]: p["properties"] for p in pois}
        self.cerca = defaultdict(list)  # tramo -> [(poi, distancia)]
        with open(config.GEO / "cerca_de.csv", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                self.cerca[fila["tramo_id"]].append((fila["osm_id"], float(fila["distancia_m"])))
        self.por_via = defaultdict(list)
        for t in self.tramos.values():
            self.por_via[t["via"]].append(t["id"])
        self.reportes: list[dict] = []
        self.patrones: dict = {}
        self.excluidos: set[str] = set()  # tramos reservados para patrones (sin ruido de fondo)

    # --- utilidades ---------------------------------------------------------------------
    def _elegir(self, pesos: dict):
        claves = list(pesos)
        return self.rnd.choices(claves, weights=[pesos[k] for k in claves])[0]

    def _hora(self, desde: int | None = None, hasta: int | None = None) -> str:
        if desde is None:
            h = self.rnd.choices(range(24), weights=PESO_HORA)[0]
        else:
            h = self.rnd.randint(desde, hasta)
        return f"{h:02d}:{self.rnd.randrange(0, 60, 5):02d}"

    def _poi_de(self, tramo_id: str, tipo: str | None = None):
        cands = [(self.pois[o], d) for o, d in self.cerca.get(tramo_id, []) if tipo is None or self.pois[o]["tipo"] == tipo]
        return min(cands, key=lambda x: x[1])[0] if cands else None

    def _tiene_poi(self, tramo_id: str, tipo: str) -> bool:
        return self._poi_de(tramo_id, tipo) is not None

    def _nombre_via(self, via: str) -> str:
        """Variantes de escritura de una vía con su artículo, como las escribiría un sereno."""
        v = via
        if v.startswith("Avenida "):
            resto = v[len("Avenida "):]
            return "la " + self.rnd.choice([f"Av. {resto}", f"Avenida {resto}", f"av. {resto}", f"Av {resto}"])
        if v.startswith("Jirón "):
            return "el " + self.rnd.choice([f"Jr. {v[6:]}", v, f"jirón {v[6:]}"])
        if v.startswith("Calle "):
            return "la " + self.rnd.choice([v, f"calle {v[6:]}", f"Ca. {v[6:]}"])
        if v.startswith(("Pasaje ", "Malecón ", "Óvalo ")):
            return f"el {v}"
        if v.startswith(("Alameda ", "Prolongación ", "Vía ")):
            return f"la {v}"
        if any(o.split(" ", 1)[-1] == v for o in self.por_via if o != v):
            return v  # existe "Calle X" además de "X": no se antepone tipo para no crear ambigüedad
        return self.rnd.choice([f"la calle {v}", f"el jr. {v}"])  # nombres sin tipo de vía en OSM

    def _hora_txt(self, hora: str) -> str:
        h, m = map(int, hora.split(":"))
        estilos = [f"{hora}", f"{hora} horas", f"{hora} hrs.",
                   f"{(h % 12) or 12}:{m:02d} {'a. m.' if h < 12 else 'p. m.'}"]
        return self.rnd.choice(estilos)

    # --- redacción ------------------------------------------------------------------------
    def _relato(self, inc: dict, ruido: str | None) -> str:
        t = self.tramos[inc["tramo_id"]]
        h = self._hora_txt(inc["hora"])
        apertura = self.rnd.choice(APERTURAS).format(h=h)
        poi = self._poi_de(t["id"], inc.get("poi_tipo"))
        ref = ""
        if poi:
            ref = self.rnd.choice(REFERENCIAS[poi["tipo"]]).format(n=nombre_poi(poi))
            inc["punto_referencia"] = poi["tipo"]
        via = self._nombre_via(t["via"])
        if ruido == "sin_cuadra" and poi:
            lugar = f"en {via}, {ref}"
            ref = ""
        elif ruido == "sin_via" and poi:
            lugar = f"en la zona, {ref}"
            ref = ""
        else:
            lugar = self.rnd.choice(LUGARES).format(c=t["cuadra"], v=via)
        m = self.rnd.choice(MEDIO_TXT[inc["medio"]])
        sujeto = self.rnd.choice(SUJETOS)
        hecho = self.rnd.choice(HECHOS[inc["modalidad"]]).format(s=sujeto, m=m)
        cierre = self.rnd.choice(CIERRES)
        if sujeto.startswith("un "):
            for pl, sg in SINGULAR.items():
                hecho = re.sub(r"\b" + pl + r"\b", sg, hecho)
            cierre = cierre.replace("Los autores huyeron", "El autor huyó").replace("a los autores", "al autor")
        texto = f"{apertura} {lugar}{(' ' + ref) if ref else ''}, {hecho}. {cierre}"
        texto = contraer(re.sub(r",\s*,", ",", re.sub(r"\s+,", ",", texto)))
        return texto[0].upper() + texto[1:]

    def _agregar(self, fecha: date, hora: str, tramo_id: str, modalidad: str, medio: str | None = None,
                 patron: str | None = None, poi_tipo: str | None = None) -> None:
        medio = medio or self._elegir(MEDIOS_POR_MODALIDAD[modalidad])
        t = self.tramos[tramo_id]
        r = self.rnd.random()
        ruido = "sin_cuadra" if r < 0.05 else ("sin_via" if r < 0.08 else None)
        if patron:  # los relatos de patrones se redactan completos
            ruido = None
        inc = {"fecha": fecha.isoformat(), "hora": hora, "franja": franja_de(hora), "dia_semana": DIAS[fecha.weekday()],
               "tramo_id": tramo_id, "via": t["via"], "cuadra": t["cuadra"], "sector": t["sector"],
               "modalidad": modalidad, "codigo_iccs": MODALIDAD[modalidad]["codigo_iccs"], "medio": medio,
               "patron": patron, "poi_tipo": poi_tipo, "ruido": ruido, "punto_referencia": None}
        inc["texto"] = self._relato(inc, ruido)
        self.reportes.append(inc)

    # --- selección de escenarios -------------------------------------------------------------
    def _avenidas_con_paraderos(self) -> list[tuple[str, list[str]]]:
        av = []
        for via, ids in self.por_via.items():
            if not via.startswith("Avenida"):
                continue
            con_paradero = [i for i in ids if self._tiene_poi(i, "paradero")]
            av.append((via, con_paradero))
        return sorted(av, key=lambda x: -len(x[1]))

    def patron_1_cluster_celular_moto(self) -> None:
        """Robo de celular desde moto, 18–20 h, cuadras junto a paraderos de 3 avenidas, última semana."""
        avenidas = self._avenidas_con_paraderos()[:3]
        tramos_cluster = []
        for via, ids in avenidas:
            elegidos = self.rnd.sample(ids, 3)
            tramos_cluster += elegidos
        conteo = Counter()
        for i, tid in enumerate(tramos_cluster):
            n = [5, 4, 2][i % 3]
            for _ in range(n):
                f = ULTIMA_SEMANA[0] + timedelta(days=self.rnd.randint(0, 6))
                self._agregar(f, self._hora(18, 19), tid, "robo_celular", "moto", "P1_cluster", poi_tipo="paradero")
                conteo[tid] += 1
        self.excluidos |= set(tramos_cluster)
        self.patrones["P1"] = {"descripcion": "Clúster de robo de celular desde moto 18:00–20:00 cerca de paraderos, última semana",
                               "periodo": [d.isoformat() for d in ULTIMA_SEMANA],
                               "avenidas": [a for a, _ in avenidas], "tramos": dict(conteo)}

    def patron_2_intervenciones(self) -> list[dict]:
        """Patrullaje reforzado en septiembre: baja de arrebatos en 4 tramos, sin cambio en 1."""
        usadas = set(self.patrones["P1"]["avenidas"])
        cands = [t for t in self.tramos.values() if t["via"].startswith("Avenida") and t["via"] not in usadas
                 and t["id"] not in self.excluidos and (self._tiene_poi(t["id"], "mercado") or self._tiene_poi(t["id"], "paradero"))]
        cands.sort(key=lambda t: (t["via"], t["cuadra"]))
        vias = sorted({t["via"] for t in cands}, key=lambda v: -sum(1 for t in cands if t["via"] == v))[:2]
        elegidos = [t["id"] for v in vias for t in self.rnd.sample([t for t in cands if t["via"] == v], 3)][:5]
        plan = [(6, 1), (5, 2), (7, 2), (6, 1), (5, 6)]  # (antes, después); el último no baja
        intervenciones = []
        for k, (tid, (n_antes, n_despues)) in enumerate(zip(elegidos, plan)):
            for periodo, n in ((ANTES, n_antes), (DESPUES, n_despues)):
                for _ in range(n):
                    f = periodo[0] + timedelta(days=self.rnd.randint(0, 27))
                    self._agregar(f, self._hora(16, 21), tid, self.rnd.choice(ARREBATOS), patron="P2_intervencion")
            intervenciones.append({"id": f"INT-2026-09-{k + 1:02d}", "tramo_id": tid, "tipo": "patrullaje reforzado",
                                   "fecha_inicio": INTERVENCION[0].isoformat(), "fecha_fin": INTERVENCION[1].isoformat(),
                                   "fuente": "F-PLAN-PATRULLAJE-2026-09"})
        self.excluidos |= set(elegidos)
        self.patrones["P2"] = {"descripcion": "Patrullaje reforzado 7 set – 4 oct 2026; arrebatos 4 semanas antes vs. después",
                               "ventana_antes": [d.isoformat() for d in ANTES], "ventana_despues": [d.isoformat() for d in DESPUES],
                               "tramos": {tid: {"antes": a, "despues": d} for tid, (a, d) in zip(elegidos, plan)},
                               "tramo_sin_descenso": elegidos[-1]}
        # Intervenciones adicionales (contexto, sin patrón plantado)
        otros = [t for t in self.tramos.values() if t["id"] not in self.excluidos and self._tiene_poi(t["id"], "parque")]
        for k, t in enumerate(self.rnd.sample(otros, 2)):
            intervenciones.append({"id": f"INT-2026-10-{k + 1:02d}", "tramo_id": t["id"], "tipo": "mejora de iluminación",
                                   "fecha_inicio": "2026-10-01", "fecha_fin": "2026-10-31", "fuente": "F-PLAN-ILUMINACION-2026-10"})
        return intervenciones

    def patron_3_emergentes(self) -> None:
        """Modalidades nuevas (bujiazo, marcaje) en la última semana, en vías sin registros en el último mes."""
        usadas = set(self.patrones["P1"]["avenidas"]) | {self.tramos[t]["via"] for t in self.patrones["P2"]["tramos"]}
        jirones = sorted([v for v, ids in self.por_via.items() if not v.startswith("Avenida") and v not in usadas and len(ids) >= 4])
        vias_bujiazo = self.rnd.sample(jirones, 2)
        con_banco = sorted({t["via"] for t in self.tramos.values() if self._tiene_poi(t["id"], "banco")
                            and t["via"] not in usadas and t["via"] not in vias_bujiazo and len(self.por_via[t["via"]]) <= 30})
        via_marcaje = self.rnd.choice(con_banco)
        eventos = []
        for via, n in ((vias_bujiazo[0], 3), (vias_bujiazo[1], 2)):
            for _ in range(n):
                tid = self.rnd.choice(self.por_via[via])
                f = ULTIMA_SEMANA[0] + timedelta(days=self.rnd.randint(0, 6))
                self._agregar(f, self._hora(0, 5) if self.rnd.random() < .5 else self._hora(20, 23), tid, "bujiazo", patron="P3_emergente")
                eventos.append(tid)
        tramo_banco = next(t for t in self.por_via[via_marcaje] if self._tiene_poi(t, "banco"))
        for _ in range(2):
            f = ULTIMA_SEMANA[0] + timedelta(days=self.rnd.randint(0, 6))
            self._agregar(f, self._hora(10, 16), tramo_banco, "marcaje", patron="P3_emergente", poi_tipo="banco")
        vias = vias_bujiazo + [via_marcaje]
        for v in vias:
            self.excluidos |= set(self.por_via[v])
        self.patrones["P3"] = {"descripcion": "Modalidades emergentes en la última semana en vías sin registros en los 30 días previos",
                               "periodo": [d.isoformat() for d in ULTIMA_SEMANA],
                               "modalidades": {"bujiazo": vias_bujiazo, "marcaje": [via_marcaje]}}

    def fondo(self, n: int) -> None:
        """Incidentes de fondo, sin patrón, con proporciones calibradas."""
        libres = [t for t in self.tramos.values() if t["id"] not in self.excluidos]
        pesos = [(3 if t["via"].startswith("Avenida") else 1) * (1.5 if self.cerca.get(t["id"]) else 1) for t in libres]
        dias = (config.FECHA_FIN - config.FECHA_INICIO).days + 1
        fechas = [config.FECHA_INICIO + timedelta(days=i) for i in range(dias)]
        peso_dia = [1.25 if f.weekday() >= 4 else 1.0 for f in fechas]
        for _ in range(n):
            t = self.rnd.choices(libres, weights=pesos)[0]
            f = self.rnd.choices(fechas, weights=peso_dia)[0]
            self._agregar(f, self._hora(), t["id"], self._elegir(PESOS_MODALIDAD))

    # --- salida --------------------------------------------------------------------------------
    def generar(self) -> list[dict]:
        self.patron_1_cluster_celular_moto()
        intervenciones = self.patron_2_intervenciones()
        self.patron_3_emergentes()
        self.fondo(config.N_REPORTES - len(self.reportes))
        self.reportes.sort(key=lambda r: (r["fecha"], r["hora"], r["tramo_id"]))
        for i, r in enumerate(self.reportes, 1):
            r["id"] = f"R-{i:06d}"
        return intervenciones


def guardar(gen: Generador, intervenciones: list[dict]) -> None:
    if config.REPORTES.exists():
        shutil.rmtree(config.REPORTES)
    config.REPORTES.mkdir(parents=True)
    por_dia = defaultdict(list)
    for r in gen.reportes:
        por_dia[r["fecha"]].append(r)
    for fecha, lista in sorted(por_dia.items()):
        with open(config.REPORTES / f"{fecha}.jsonl", "w", encoding="utf-8") as f:
            for r in lista:
                f.write(json.dumps({"id": r["id"], "tipo": "sintetico", "canal": gen.rnd.choice(CANALES),
                                    "fecha": r["fecha"], "fecha_ingreso": r["fecha"], "texto": r["texto"]},
                                   ensure_ascii=False) + "\n")
    campos = ["fecha", "hora", "franja", "dia_semana", "tramo_id", "via", "cuadra", "sector", "modalidad",
              "codigo_iccs", "medio", "punto_referencia", "patron", "ruido"]
    gt = {"aviso": config.ETIQUETA_SINTETICO, "semilla": config.SEMILLA,
          "reportes": {r["id"]: {k: r[k] for k in campos} for r in gen.reportes}, "patrones": gen.patrones}
    config.GROUND_TRUTH.write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(config.INTERVENCIONES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "tramo_id", "tipo", "fecha_inicio", "fecha_fin", "fuente"])
        w.writeheader()
        w.writerows(intervenciones)
    log.info("Reportes: %d en %d días | intervenciones: %d", len(gen.reportes), len(por_dia), len(intervenciones))
    log.info("Modalidades: %s", dict(Counter(r["modalidad"] for r in gen.reportes).most_common()))


if __name__ == "__main__":
    config.configurar_logging()
    g = Generador()
    guardar(g, g.generar())
