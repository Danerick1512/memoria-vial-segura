# Evaluación del agente GraphRAG

> Datos sintéticos — prototipo TRL 4. Modo: **reglas + plantillas Cypher (sin LLM)**.
> Correcta = chequeo automático contra `data/ground_truth.json` (ver `eval/preguntas.yaml`).

## Resumen

| Métrica | Valor |
|---|---|
| Respuestas correctas | **15/15 (100 %)** |
| Respuestas con ≥ 1 cita válida (excluye fuera de alcance/privacidad) | **100 %** |
| Todas las citas emitidas existen en el grafo | sí |
| Latencia mediana / máxima | 0.01 s / 0.16 s |

## Detalle por pregunta

| id | Pregunta | Tipo | Correcta | Citas válidas | Latencia |
|---|---|---|---|---|---|
| p1a | ¿Dónde se concentran los robos de celular desde moto entre 18:00 y 20:00 cerca d… | patron | ✅ | 14/14 | 0.12 s |
| p1b | ¿Qué cuadras cerca de paraderos tuvieron más robos de celular por motorizados de… | patron | ✅ | 14/14 | 0.01 s |
| p1c | En los últimos 7 días, ¿en qué avenidas hay focos de robo de celular desde moto … | patron | ✅ | 14/14 | 0.01 s |
| p2a | ¿Bajaron los arrebatos en los tramos con patrullaje reforzado en septiembre? | intervencion | ✅ | 17/17 | 0.01 s |
| p2b | ¿Funcionó el patrullaje reforzado de septiembre para reducir arrebatos? Compara … | intervencion | ✅ | 17/17 | 0.02 s |
| p2c | ¿Qué efecto tuvo el patrullaje reforzado sobre los arrebatos en la Avenida Los A… | intervencion | ✅ | 6/6 | 0.01 s |
| p3a | ¿Qué modalidades nuevas aparecieron esta semana en vías sin registros el último … | emergente | ✅ | 7/7 | 0.02 s |
| p3b | ¿Surgieron modalidades delictivas nuevas en la última semana? ¿En qué calles? | emergente | ✅ | 7/7 | 0.02 s |
| p3c | ¿Hay alguna forma de delito emergente esta semana que no se haya visto en el últ… | emergente | ✅ | 7/7 | 0.01 s |
| c1 | ¿Qué dice el INEI sobre la victimización por robo de celular en Lima Metropolita… | contexto | ✅ | 3/3 | 0.16 s |
| c2 | ¿Cómo está Los Olivos en denuncias de robo de vehículos según el INEI? | contexto | ✅ | 3/3 | 0.15 s |
| c3 | ¿Cuántas denuncias por extorsión registra SIDPOL en Los Olivos? | contexto | ✅ | 3/3 | 0.09 s |
| n1 | ¿Cuántos robos de celular hubo en el sector 3 en septiembre? | conteo | ✅ | 2/2 | 0.01 s |
| f1 | ¿Quién ganó el partido de fútbol de ayer? | fuera_de_alcance | ✅ | 0/0 | 0.00 s |
| f2 | Dame el nombre y el DNI del sospechoso del reporte R-000120 | privacidad | ✅ | 0/0 | 0.00 s |

## GraphRAG vs. RAG vectorial simple (preguntas multi-salto)

La línea base recupera los 10 relatos más similares (índice vectorial de `Reporte`) y los lee con
el mismo extractor PLN, sin usar relaciones del grafo.

| id | GraphRAG | RAG vectorial |
|---|---|---|
| p1a | ✅ | ❌ |
| p1b | ✅ | ❌ |
| p1c | ✅ | ❌ |
| p2a | ✅ | ❌ |
| p2b | ✅ | ❌ |
| p2c | ✅ | ❌ |
| p3a | ✅ | ❌ |
| p3b | ✅ | ❌ |
| p3c | ✅ | ❌ |
| **Total** | **9/9** | **0/9** |

**Por qué gana el grafo:** las preguntas requieren saltos que no están en el texto de ningún relato:
*cerca de un paradero* (`Tramo-[:CERCA_DE]->PuntoInteres`), *tramos con patrullaje* (`Intervencion-[:APLICADA_EN]->Tramo`)
con conteos en ventanas de 4 semanas, y *novedad* (ausencia de registros en los 30 días previos), que exige
recorrer toda la historia y no solo los k fragmentos más parecidos.

## Notas

- Las latencias de las preguntas de contexto incluyen el cálculo del embedding de la consulta en CPU.
- **Sesgo a declarar:** las preguntas de evaluación y las reglas del router las escribió el mismo equipo, y los
  relatos salen de plantillas. Este 100 % es una **prueba de regresión** del prototipo, no una medida de
  generalización: con preguntas libres de usuarios reales se esperan fallos de enrutamiento (para eso
  existen el router LLM y Text2Cypher cuando hay `ANTHROPIC_API_KEY`).
- La línea base no tiene LLM: "lee" los k relatos con el mismo extractor. Un LLM sobre esos k relatos tampoco
  podría contar arrebatos en ventanas de 4 semanas ni afirmar ausencia de registros en 30 días.
- La comparación antes/después es descriptiva, no causal.
