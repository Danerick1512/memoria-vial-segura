"""Calidad del PLN y privacidad de los relatos sintéticos."""
import json
import re

import config
from pln.evaluar import evaluar
from pln.extraer import ExtractorReglas


def test_precision_via_y_modalidad_sobre_meta():
    r = evaluar()
    assert r["aciertos"]["via"] / r["n"] >= 0.85
    assert r["aciertos"]["modalidad"] / r["n"] >= 0.85


def test_no_inventa_tramo_sin_via():
    inc = ExtractorReglas(usar_llm=False).extraer("A las 20:10 en la zona, cerca del paradero, dos sujetos robaron un celular.")
    assert inc.tramo_resuelto is False and inc.tramo_id is None
    assert inc.modalidad == "robo_celular" and inc.hora == "20:10"


def test_alias_y_abreviaturas():
    inc = ExtractorReglas(usar_llm=False).extraer(
        "Siendo las 7:20 p. m. en la cdra. 8 de la Av. Universitaria, dos sujetos en moto lineal arrebataron un celular.")
    assert inc.via == "Avenida Universitaria" and inc.cuadra == 8 and inc.hora == "19:20"
    assert inc.medio == "moto" and inc.tramo_id == "AV_UNIVERSITARIA_C08"


def test_relatos_sin_datos_personales():
    """Ley 29733: sin DNI (8 dígitos), placas (ABC-123) ni rasgos físicos en los relatos."""
    prohibido = re.compile(r"\b\d{8}\b|\b[A-Z]{1,3}-?\d{3,4}\b|\btez\b|\bestatura\b|\bcabello\b|\btatuaje\b|\bDNI\b", re.I)
    for f in config.REPORTES.glob("*.jsonl"):
        for linea in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(linea)
            assert r["tipo"] == "sintetico"
            assert not prohibido.search(r["texto"]), r["id"]
