"""Catálogos controlados de la ontología: modalidades (mapeo a ICCS de UNODC), medios y franjas.

Nota ICCS: la Clasificación Internacional de Delitos con Fines Estadísticos (UNODC, 2015)
agrupa por acto. Varias modalidades locales comparten código (p. ej. robo de celular y
arrebato de cartera son 04011 «robo a la persona»), por eso la clave de Modalidad es `id`
y `codigo_iccs` es un atributo. (0501 en ICCS es «allanamiento/burglary», no robo.)
"""
from __future__ import annotations

MODALIDADES = [
    # id, nombre, codigo_iccs, etiqueta ICCS
    ("robo_celular", "Robo de celular", "04011", "Robo a la persona"),
    ("arrebato_cartera", "Arrebato de cartera o bolso", "04011", "Robo a la persona"),
    ("cogoteo", "Cogoteo (robo con sujeción del cuello)", "04011", "Robo a la persona"),
    ("tentativa_robo", "Tentativa de robo", "04011", "Robo a la persona (tentativa)"),
    ("robo_vehiculo", "Robo de vehículo", "04019", "Otros robos"),
    ("hurto_autopartes", "Hurto de autopartes", "05021", "Hurto de vehículo motorizado o sus partes"),
    ("robo_negocio", "Robo a establecimiento comercial", "04013", "Robo a establecimiento o institución"),
    ("extorsion", "Extorsión", "02041", "Extorsión o chantaje"),
    ("amenazas", "Amenazas e intimidación", "0208", "Actos destinados a inducir miedo o angustia"),
    ("acoso_sexual", "Acoso sexual en espacio público", "0302", "Agresión sexual (no física)"),
    ("estafa_paso", "Estafa al paso («cuento»)", "0701", "Fraude"),
    # Modalidades que solo aparecen en la última semana (patrón 3: emergentes)
    ("bujiazo", "Bujiazo (rotura de luna para robar del vehículo)", "05029", "Otros hurtos"),
    ("marcaje", "Marcaje (robo tras retiro bancario)", "04011", "Robo a la persona"),
]
MODALIDAD = {m[0]: {"id": m[0], "nombre": m[1], "codigo_iccs": m[2], "iccs_etiqueta": m[3]} for m in MODALIDADES}

# Modalidades que cuentan como "arrebato" en la pregunta 2 (efecto de intervención)
ARREBATOS = ["robo_celular", "arrebato_cartera"]

MEDIOS = ["moto", "a pie", "auto", "mototaxi", "bicicleta"]

FRANJAS = [  # (nombre, hora_inicio, hora_fin) — fin exclusivo
    ("madrugada", 0, 6),
    ("mañana", 6, 12),
    ("tarde", 12, 18),
    ("noche", 18, 24),
]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def franja_de(hora: str) -> str:
    h = int(hora.split(":")[0])
    return next(n for n, a, b in FRANJAS if a <= h < b)
