# Calibración de los reportes sintéticos

> Datos sintéticos — prototipo TRL 4. Los 400 relatos son una **muestra ilustrativa**: respetan proporciones
> y patrones de fuentes oficiales, pero su volumen no pretende igualar las denuncias reales del distrito.

Archivo generado por `sinteticos/calibracion.py`, que **verifica** que cada cifra existe en la página citada.

## 1. Proporción de modalidades

Fuente: [INEI-8556475 p.19] — INEI, *Estadísticas de Seguridad Ciudadana*, semestre móvil feb–jul 2026, Gráfico 16:
«Lima Metropolitana y la Provincia Constitucional del Callao: población de 15 y más años víctima de algún
hecho delictivo, según tipo» (tasa por cada 100 habitantes). URL oficial: https://cdn.www.gob.pe/uploads/document/file/10563510/8556475-informe-tecnico-estadisticas-de-seguridad-ciudadana-del-semestre-movil-febrero-julio-2026.pdf?v=1788466861

| Categoría INEI | Tasa feb–jul 2026 |
|---|---|
| Robo de dinero, cartera, celular | 11,0 |
| Intento de robo de dinero, cartera, celular | 4,7 |
| Robo  de vehículo | 2,1 |
| Intento de robo de vehículo | 1,5 |
| Amenazas e intimidaciones | 1,5 |
| Extorsión | 1,2 |
| Robo de negocio | 1,0 |
| Maltrato y ofensa sexual | 2,0 |
| Estafa | 1,9 |

Se excluyen *delitos informáticos* (no ocurren en la vía pública). Reparto de cada categoría en modalidades
de calle (**supuestos** del equipo, editables en `PESOS_MODALIDAD`):

- Robo de dinero, cartera, celular → 60 % robo de celular, 28 % arrebato de cartera, 12 % cogoteo.
- Intento de robo (dinero/cartera/celular + vehículo) → tentativa de robo.
- Robo de vehículo → 50 % robo de vehículo, 50 % hurto de autopartes.
- Maltrato y ofensa sexual → 25 % (fracción en espacio público: acoso sexual callejero).
- Estafa → 25 % (fracción presencial: estafa al paso).

| Modalidad | ICCS | Peso | % esperado (fondo) | % observado (400 reportes, incl. patrones) |
|---|---|---|---|---|
| Robo de celular | 04011 | 6.60 | 27.5 % | 36.2 % |
| Tentativa de robo | 04011 | 6.20 | 25.9 % | 21.5 % |
| Arrebato de cartera o bolso | 04011 | 3.08 | 12.8 % | 12.2 % |
| Amenazas e intimidación | 0208 | 1.50 | 6.3 % | 6.2 % |
| Cogoteo (robo con sujeción del cuello) | 04011 | 1.32 | 5.5 % | 5.5 % |
| Extorsión | 02041 | 1.20 | 5.0 % | 4.0 % |
| Robo de vehículo | 04019 | 1.05 | 4.4 % | 3.5 % |
| Hurto de autopartes | 05021 | 1.05 | 4.4 % | 3.2 % |
| Robo a establecimiento comercial | 04013 | 1.00 | 4.2 % | 2.2 % |
| Acoso sexual en espacio público | 0302 | 0.50 | 2.1 % | 2.2 % |
| Estafa al paso («cuento») | 0701 | 0.47 | 2.0 % | 1.2 % |

El % observado difiere del esperado porque los patrones plantados (sección 3) añaden robos de celular,
arrebatos, bujiazos y marcajes.

## 2. Supuestos sin fuente oficial a nivel de calle

- **Hora del día**: perfil con pico en 18–21 h (`PESO_HORA` = [2, 1, 1, 1, 1, 2, 4, 6, 6, 5, 4, 4, 5, 5, 5, 6, 7, 8, 11, 12, 11, 9, 6, 3]). No hay cifra oficial por hora
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

Páginas del corpus que mencionan Los Olivos: **77**. Las más útiles como contexto:

- `sidpol-8482979-reporte-de-denuncias-registradas-en-el-sistema-de-de-cd620d` p.30 — Denuncias por robo y hurto por distrito, 2024 – ene.-jul. 2026
- `sidpol-8482979-reporte-de-denuncias-registradas-en-el-sistema-de-de-cd620d` p.31 — Denuncias por extorsión por distrito, 2024 – ene.-jul. 2026
- `inei-8253262-estadisticas-de-la-criminalidad-seguridad-ciudadana--7fe5c5` p.7 — Robo de vehículos por distrito, II sem. 2025 (Los Olivos +53)

Estas páginas se cargan como `(:Documento)-[:TIENE_PAGINA]->(:Pagina)` y el agente las cita como
`[SIDPOL-8482979 p.30]`.
