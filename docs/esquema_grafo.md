# Esquema del grafo — Memoria Vial Segura

Se renderiza en GitHub, VS Code (extensión Mermaid) o en https://mermaid.live.

```mermaid
flowchart LR
    classDef hecho fill:#fde2e1,stroke:#c0392b,color:#000
    classDef geo fill:#e1f0fd,stroke:#2471a3,color:#000
    classDef prov fill:#fef5d4,stroke:#b7950b,color:#000
    classDef cat fill:#e8f8e8,stroke:#1e8449,color:#000

    I["Incidente<br/>id · fecha · hora · franja<br/>dia_semana · descripcion_resumen"]:::hecho
    R["Fuente:Reporte<br/>id · tipo='sintetico' · canal<br/>fecha_ingreso · texto · embedding"]:::prov
    M["Modalidad<br/>id · nombre · codigo_iccs"]:::cat
    ME["Medio<br/>nombre"]:::cat
    T["Tramo<br/>id · via · cuadra<br/>geom_wkt · ubicacion(point)"]:::geo
    P["PuntoInteres<br/>osm_id · tipo · nombre"]:::geo
    S["Sector<br/>id · nombre"]:::geo
    D["Distrito<br/>ubigeo='150117'"]:::geo
    IV["Intervencion<br/>id · tipo · fecha_inicio · fecha_fin"]:::hecho
    F["Fuente<br/>(plan operativo)"]:::prov
    DOC["Documento<br/>doc_id · cita · url · titulo"]:::prov
    PG["Pagina<br/>pagina · texto · embedding"]:::prov
    FT["FilaTabla<br/>contenido (pieza 3)"]:::prov
    C["Corrida<br/>fecha · n_reportes · n_ok · n_sin_tramo"]:::prov

    I -- REGISTRADO_EN --> R
    I -- "DERIVADO_DE (prov:wasDerivedFrom)" --> R
    I -- TIPO --> M
    I -- USA --> ME
    I -- OCURRE_EN --> T
    T -- "CERCA_DE {distancia_m}" --> P
    T -- CUBIERTO_POR --> S
    D -- CONTIENE --> S
    IV -- APLICADA_EN --> T
    IV -- DERIVADO_DE --> F
    DOC -- TIENE_PAGINA --> PG
    FT -- EXTRAIDA_DE --> PG
```

**Capas**

- Rojo: hechos (incidentes, intervenciones). Azul: geografía real de OpenStreetMap (GeoSPARQL: WKT).
- Amarillo: procedencia (PROV-O): toda afirmación remonta a un `Reporte` o a una `Pagina` oficial.
- Verde: vocabularios controlados (modalidades mapeadas a ICCS de UNODC, medios).

**Índices**: unicidad en cada identificador, `POINT INDEX` en `Tramo.ubicacion` y
`PuntoInteres.ubicacion`, `VECTOR INDEX` (384 dim, coseno) en `Pagina.embedding` y
`Reporte.embedding`. Ver `grafo/esquema.cypher`. Equivalente OWL: `ontologia/memoria_vial.ttl`.
