# Evaluación del PLN sobre relatos

> Datos sintéticos — prototipo TRL 4. Extractor: reglas + gazetteer OSM + lemas spaCy (respaldo LLM solo si hay
> `ANTHROPIC_API_KEY`). Precisión = coincidencia exacta con `data/ground_truth.json`.

**Reportes evaluados:** 400 · **Tramo resuelto:** 391 (97.8 %)

| Campo | Aciertos | Precisión | Meta |
|---|---|---|---|
| via | 391/400 | 97.8 % | ≥ 85 % ✅ |
| cuadra | 388/400 | 97.0 % |  |
| hora | 400/400 | 100.0 % |  |
| franja | 400/400 | 100.0 % |  |
| modalidad | 400/400 | 100.0 % | ≥ 85 % ✅ |
| medio | 400/400 | 100.0 % |  |
| punto_referencia | 400/400 | 100.0 % |  |
| tramo_id | 384/400 | 96.0 % |  |

## Por tipo de relato

`sin_cuadra`: el relato no menciona la cuadra; `sin_via`: solo menciona un punto de referencia.

| Tipo | n | vía | modalidad | tramo |
|---|---|---|---|---|
| limpio | 376 | 99 % | 100 % | 99 % |
| sin_cuadra | 18 | 100 % | 100 % | 61 % |
| sin_via | 6 | 17 % | 100 % | 17 % |

En los relatos `sin_via` la vía no aparece en el texto: no resolverla es el comportamiento correcto
(no se inventa); por eso cuentan como fallo en la tabla y como `tramo_resuelto=false` en el grafo.

## Ejemplos de error

- **via** `R-000013`: esperado `Avenida Alfredo Mendiola` / obtenido `None` — «Siendo aprox. las 21:55 en la zona, frente a la agencia BBVA, dos sujetos que se acercaron caminando intentaron asaltar a una persona sin lo…»
- **via** `R-000021`: esperado `Calle 11` / obtenido `None` — «Aproximadamente a las 2:10 p. m. en la zona, por el parque, tres sujetos en una moto arrebataron la cartera a una vecina. El personal de ser…»
- **via** `R-000062`: esperado `Río Santa` / obtenido `None` — «Hoy a las 8:25 p. m. en la cuadra 2 de Río Santa a pocos metros del paradero, dos desconocidos a pie le robaron el equipo móvil a un vecino.…»
- **cuadra** `R-000013`: esperado `95` / obtenido `None` — «Siendo aprox. las 21:55 en la zona, frente a la agencia BBVA, dos sujetos que se acercaron caminando intentaron asaltar a una persona sin lo…»
- **cuadra** `R-000021`: esperado `10` / obtenido `None` — «Aproximadamente a las 2:10 p. m. en la zona, por el parque, tres sujetos en una moto arrebataron la cartera a una vecina. El personal de ser…»
- **cuadra** `R-000030`: esperado `7` / obtenido `6` — «Siendo las 08:05 hrs. en la Avenida Malecón Chillón, frente a la Institución Educativa Inca Garcilaso De La Vega, tres sujetos a pie intenta…»
- **tramo_id** `R-000013`: esperado `AV_ALFREDO_MENDIOLA_C95` / obtenido `None` — «Siendo aprox. las 21:55 en la zona, frente a la agencia BBVA, dos sujetos que se acercaron caminando intentaron asaltar a una persona sin lo…»
- **tramo_id** `R-000021`: esperado `CA_11_C10` / obtenido `None` — «Aproximadamente a las 2:10 p. m. en la zona, por el parque, tres sujetos en una moto arrebataron la cartera a una vecina. El personal de ser…»
- **tramo_id** `R-000030`: esperado `AV_MALECON_CHILLON_C07` / obtenido `AV_MALECON_CHILLON_C06` — «Siendo las 08:05 hrs. en la Avenida Malecón Chillón, frente a la Institución Educativa Inca Garcilaso De La Vega, tres sujetos a pie intenta…»

## Limitaciones

Los relatos sintéticos se redactan con plantillas; las reglas cubren ese vocabulario. Con relatos
reales (serenazgo) la precisión esperada es menor: por eso existe el respaldo LLM y la interfaz
`Extractor` para enchufar el extractor de la pieza 3.
