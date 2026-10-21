// Memoria Vial Segura — esquema del grafo (Neo4j 5). Idempotente: IF NOT EXISTS.
// Unicidad de identificadores
CREATE CONSTRAINT incidente_id IF NOT EXISTS FOR (n:Incidente) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT fuente_id IF NOT EXISTS FOR (n:Fuente) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT reporte_id IF NOT EXISTS FOR (n:Reporte) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT modalidad_id IF NOT EXISTS FOR (n:Modalidad) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT medio_nombre IF NOT EXISTS FOR (n:Medio) REQUIRE n.nombre IS UNIQUE;
CREATE CONSTRAINT tramo_id IF NOT EXISTS FOR (n:Tramo) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT poi_osm_id IF NOT EXISTS FOR (n:PuntoInteres) REQUIRE n.osm_id IS UNIQUE;
CREATE CONSTRAINT sector_id IF NOT EXISTS FOR (n:Sector) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT intervencion_id IF NOT EXISTS FOR (n:Intervencion) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT distrito_ubigeo IF NOT EXISTS FOR (n:Distrito) REQUIRE n.ubigeo IS UNIQUE;
CREATE CONSTRAINT documento_id IF NOT EXISTS FOR (n:Documento) REQUIRE n.doc_id IS UNIQUE;
CREATE CONSTRAINT documento_cita IF NOT EXISTS FOR (n:Documento) REQUIRE n.cita IS UNIQUE;
CREATE CONSTRAINT pagina_id IF NOT EXISTS FOR (n:Pagina) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT fila_id IF NOT EXISTS FOR (n:FilaTabla) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT corrida_fecha IF NOT EXISTS FOR (n:Corrida) REQUIRE n.fecha IS UNIQUE;
// Índices de consulta
CREATE INDEX incidente_fecha IF NOT EXISTS FOR (n:Incidente) ON (n.fecha);
CREATE INDEX incidente_franja IF NOT EXISTS FOR (n:Incidente) ON (n.franja);
CREATE INDEX tramo_via IF NOT EXISTS FOR (n:Tramo) ON (n.via);
// Índices espaciales (point WGS-84)
CREATE POINT INDEX tramo_ubicacion IF NOT EXISTS FOR (n:Tramo) ON (n.ubicacion);
CREATE POINT INDEX poi_ubicacion IF NOT EXISTS FOR (n:PuntoInteres) ON (n.ubicacion);
// Índices vectoriales (multilingual-e5-small: 384 dimensiones, coseno)
CREATE VECTOR INDEX pagina_embedding IF NOT EXISTS FOR (n:Pagina) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
CREATE VECTOR INDEX reporte_embedding IF NOT EXISTS FOR (n:Reporte) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
// Índice de texto completo (Lucene, analizador español) para búsqueda híbrida en páginas oficiales
CREATE FULLTEXT INDEX pagina_texto IF NOT EXISTS FOR (n:Pagina) ON EACH [n.texto]
  OPTIONS {indexConfig: {`fulltext.analyzer`: 'spanish'}};
