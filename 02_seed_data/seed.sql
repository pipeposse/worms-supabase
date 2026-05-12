-- =============================================================================
--  worms_supabase / 02_seed_data / seed.sql
--  Catálogos baseline. Idempotente.
-- =============================================================================
SET search_path TO produccion, public;

-- DICCIONARIOS
INSERT INTO dic_estado_analisis(codigo,descripcion) VALUES
 ('ACEPTADO','Cumple especificación'),
 ('RECHAZADO','No cumple, NO se libera'),
 ('FUERA_ESPECIFICACION','Algún parámetro fuera de rango'),
 ('PENDIENTE_REVISION','Cargado, sin revisión final')
ON CONFLICT DO NOTHING;

INSERT INTO dic_corriente(codigo,descripcion) VALUES
 ('VEGETAL','Origen vegetal/agrícola'),
 ('ANIMAL','Origen animal'),
 ('INSUMO','Insumos químicos'),
 ('NFU','Neumáticos fuera de uso'),
 ('OTRO','No clasificado')
ON CONFLICT DO NOTHING;

INSERT INTO dic_tipo_parametro(codigo,descripcion) VALUES
 ('COMPOSICION','Composición % (acidez, agua, sedimentos, producto)'),
 ('FISICOQUIMICO','Densidad, temperatura, viscosidad'),
 ('QUIMICO','Yodo, peróxidos, glicerol, ceniza, MONG, AyS'),
 ('VISCOSIDAD','Mediciones reológicas'),
 ('TEXTURA','Color, aspecto, olor')
ON CONFLICT DO NOTHING;

INSERT INTO dic_unidad(codigo,descripcion,magnitud,es_estandar) VALUES
 ('KG','Kilogramos','MASA',FALSE),('TN','Toneladas','MASA',TRUE),('G','Gramos','MASA',FALSE),
 ('L','Litros','VOLUMEN',TRUE),('ML','Mililitros','VOLUMEN',FALSE),
 ('PCT','Porcentaje','FRACCION',TRUE),
 ('PPM','Partes por millón','CONCENTRACION',TRUE),
 ('MS_CM','mS/cm','CONCENTRACION',TRUE),
 ('MG_O2_L','mg O2/L (DQO)','CONCENTRACION',TRUE),
 ('G_ML','g/mL densidad','OTRO',TRUE),
 ('GI_GMU','g yodo / g muestra','OTRO',TRUE),
 ('C','Grados Celsius','OTRO',TRUE),
 ('H','Horas','OTRO',TRUE),
 ('ADIM','Adimensional','OTRO',TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO dic_sector(codigo,nombre_ui,color_hex,unidad_principal) VALUES
 ('ARE','REACTORES - ARE','#2563eb','TN'),
 ('DESGOMADO','REACTORES - DESGOMADO','#0891b2','TN'),
 ('BACHAS','BACHAS','#7c3aed','TN'),
 ('RECUPERACION','PILETAS','#059669','TN'),
 ('LABORATORIO','LABORATORIO','#475569','TN'),
 ('EXPO','EXPORTACION','#b45309','TN')
ON CONFLICT DO NOTHING;

INSERT INTO dic_calidad(codigo,descripcion,orden) VALUES
 ('A','Calidad A (premium)',1),('B','Calidad B',2),('C','Calidad C',3),
 ('SG','Sin grado',4),('RECH','Rechazado',9)
ON CONFLICT DO NOTHING;

INSERT INTO dic_turno(codigo) VALUES ('mañana'),('tarde'),('noche')
ON CONFLICT DO NOTHING;

INSERT INTO dic_insumo(codigo,descripcion,unidad) VALUES
 ('acido_kg','Ácido sulfúrico','KG'),
 ('soda_kg','Soda cáustica','KG'),
 ('metanol_kg','Metanol','KG'),
 ('catalizador_kg','Catalizador KOH-CH3OH','KG'),
 ('floculante_kg','Floculante','KG'),
 ('kg_glicerina','Glicerina (subproducto)','KG'),
 ('fuel_l','Fuel','L')
ON CONFLICT DO NOTHING;

-- CONVERSIONES
INSERT INTO ref_conversion_unidades(unidad_origen,unidad_destino,factor,contexto,notas) VALUES
 ('KG','TN', 0.001, 'GLOBAL','1 kg = 0.001 tn'),
 ('TN','KG', 1000.0,'GLOBAL', NULL),
 ('G','KG',  0.001, 'GLOBAL', NULL),
 ('KG','G',  1000.0,'GLOBAL', NULL),
 ('G','TN',  0.000001,'GLOBAL', NULL),
 ('TN','G',  1000000.0,'GLOBAL', NULL),
 ('L','ML',  1000.0,'GLOBAL', NULL),
 ('ML','L',  0.001,'GLOBAL', NULL),
 ('PPM','PCT', 0.0001,'GLOBAL','1 ppm = 1e-4 %'),
 ('PCT','PPM', 10000.0,'GLOBAL', NULL),
 ('L','KG', 0.880,'ARE(V)-B','biodiesel'),
 ('L','TN', 0.000880,'ARE(V)-B','biodiesel'),
 ('L','KG', 0.910,'AFE-S','aceite refinado'),
 ('L','TN', 0.000910,'AFE-S','aceite refinado'),
 ('L','KG', 0.920,'AG-C','AG-C aprox'),
 ('L','TN', 0.000920,'AG-C','AG-C aprox'),
 ('L','KG', 1.260,'GLICERINA-PURA','glicerina'),
 ('L','TN', 0.001260,'GLICERINA-PURA','glicerina'),
 ('L','KG', 0.792,'METANOL','metanol'),
 ('L','TN', 0.000792,'METANOL','metanol'),
 ('L','KG', 1.000,'GLOBAL','fallback agua'),
 ('L','TN', 0.001,'GLOBAL','fallback agua')
ON CONFLICT (unidad_origen,unidad_destino,contexto,vigente_desde) DO NOTHING;

-- PRODUCTOS
-- Drop temporal del CHECK para permitir INSERTs legacy con 'INTERMEDIO';
-- el CHECK final (sin INTERMEDIO) se vuelve a aplicar al final del seed.
ALTER TABLE dim_producto DROP CONSTRAINT IF EXISTS chk_tipo_producto;

INSERT INTO dim_producto
 (codigo_producto,nombre_producto,variante,corriente,tipo_producto,
  usa_piletas,usa_bachas,usa_reactor,es_exportacion,
  usa_sales,requiere_ag,requiere_are,es_mezcla)
VALUES
 ('AFE-S','Aceite filtrado especial','S','VEGETAL','INTERMEDIO',TRUE,FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('AFE-SG','Aceite filtrado especial SG','SG','VEGETAL','INTERMEDIO',TRUE,FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('AG-A','Aceite genérico A','A','VEGETAL','INTERMEDIO',TRUE,TRUE,FALSE,FALSE,FALSE,TRUE,FALSE,FALSE),
 ('AG-B','Aceite genérico B','B','VEGETAL','INTERMEDIO',TRUE,TRUE,FALSE,FALSE,FALSE,TRUE,FALSE,FALSE),
 ('AG-C','Aceite genérico C','C','VEGETAL','INTERMEDIO',TRUE,TRUE,FALSE,FALSE,FALSE,TRUE,FALSE,FALSE),
 ('AG-D','Aceite genérico D','D','VEGETAL','INTERMEDIO',TRUE,TRUE,FALSE,FALSE,FALSE,TRUE,FALSE,FALSE),
 ('AG-E','Aceite genérico exportación','E','VEGETAL','FINAL',FALSE,FALSE,FALSE,TRUE,FALSE,TRUE,FALSE,FALSE),
 ('ARE(V)-B','ARE Vegetal B (biodiesel)','B','VEGETAL','FINAL',FALSE,FALSE,TRUE,FALSE,TRUE,TRUE,TRUE,FALSE),
 ('ARE(AN)','ARE Animal',NULL,'ANIMAL','FINAL',FALSE,FALSE,TRUE,FALSE,TRUE,FALSE,TRUE,FALSE),
 ('ARE-A','ARE A','A','VEGETAL','FINAL',FALSE,FALSE,TRUE,FALSE,TRUE,FALSE,TRUE,FALSE),
 ('SEBO-A.1ra','Sebo A primera','1ra','ANIMAL','FINAL',FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('SEBO-2DA-C','Sebo segunda C','2C','ANIMAL','FINAL',FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('A-PESCADO','Aceite de pescado',NULL,'ANIMAL','FINAL',FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('BORRA-A','Borra A','A','VEGETAL','INTERMEDIO',FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('BORRA-B','Borra B','B','VEGETAL','INTERMEDIO',FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('GLICERINA-CRUDA','Glicerina cruda',NULL,'VEGETAL','INTERMEDIO',FALSE,FALSE,TRUE,FALSE,FALSE,FALSE,TRUE,FALSE),
 ('GLICERINA-PURA','Glicerina pura',NULL,'VEGETAL','FINAL',FALSE,FALSE,TRUE,FALSE,FALSE,FALSE,TRUE,FALSE),
 ('POLIGLICEROL','Poliglicerol',NULL,'VEGETAL','INTERMEDIO',FALSE,FALSE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('METANOL','Metanol',NULL,'INSUMO','INSUMO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('ACIDO-SULF','Ácido sulfúrico',NULL,'INSUMO','INSUMO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('SODA','Soda cáustica',NULL,'INSUMO','INSUMO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('KOH','KOH-Metanol catalizador',NULL,'INSUMO','INSUMO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('FLOCULANTE','Floculante piletas',NULL,'INSUMO','INSUMO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('FUEL','Fuel',NULL,'INSUMO','INSUMO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('EMULSION','Emulsión proceso',NULL,'VEGETAL','INTERMEDIO',TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('ACEITE-CRUDO','Aceite crudo (MP desgomado)',NULL,'VEGETAL','INTERMEDIO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('ACEITE-FILTRADO','Aceite filtrado (MP bachas)',NULL,'VEGETAL','INTERMEDIO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('ACEITE-REFINADO','Aceite refinado (MP ARE)',NULL,'VEGETAL','INTERMEDIO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE)
ON CONFLICT DO NOTHING;

-- PARAMETROS
INSERT INTO dim_parametro_lab
 (codigo_parametro,nombre_display,unidad,rango_min,rango_max,
  aplica_a_corriente,aplica_a_productos,tipo_parametro,es_critico)
VALUES
 ('prc_acidez','% Acidez','PCT',0,5,'["VEGETAL","ANIMAL"]','[]','COMPOSICION',TRUE),
 ('prc_sedimentos','% Sedimentos','PCT',0,2,'["VEGETAL","ANIMAL"]','[]','COMPOSICION',FALSE),
 ('prc_agua','% Agua','PCT',0,3,'["VEGETAL","ANIMAL"]','[]','COMPOSICION',TRUE),
 ('prc_producto','% Producto','PCT',80,100,'["VEGETAL","ANIMAL"]','[]','COMPOSICION',FALSE),
 ('prc_HKF','% HKF','PCT',0,10,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_emulsion','% Emulsión','PCT',0,50,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_goma_arriba','% Goma arriba','PCT',0,30,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_goma_medio','% Goma medio','PCT',0,30,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_goma_abajo','% Goma abajo','PCT',0,30,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_poliglicerol','% Poliglicerol','PCT',0,100,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_glicerina','% Glicerina','PCT',0,100,'["VEGETAL"]','[]','COMPOSICION',FALSE),
 ('prc_hexano_impurezas','% Hexano/impurezas','PCT',0,1,'["VEGETAL","ANIMAL"]','[]','COMPOSICION',FALSE),
 ('densidad','Densidad','G_ML',0.7,1.4,'[]','[]','FISICOQUIMICO',FALSE),
 ('temperatura','Temperatura','C',0,150,'[]','[]','FISICOQUIMICO',FALSE),
 ('color','Color','ADIM',NULL,NULL,'[]','[]','TEXTURA',FALSE),
 ('viscosidad','Viscosidad','ADIM',NULL,NULL,'[]','[]','VISCOSIDAD',FALSE),
 ('ppm_azufre','ppm Azufre','PPM',0,50,'["VEGETAL","ANIMAL"]','[]','QUIMICO',TRUE),
 ('ppm_fosforo','ppm Fósforo','PPM',0,50,'["VEGETAL"]','[]','QUIMICO',TRUE),
 ('sebo_indice_yodo','Índice yodo (sebo)','GI_GMU',30,80,'["ANIMAL"]','["SEBO-A.1ra","SEBO-2DA-C"]','QUIMICO',FALSE),
 ('gli_glicerol','Glicerol (glicerina)','PCT',80,100,'["VEGETAL"]','["GLICERINA-PURA","GLICERINA-CRUDA"]','QUIMICO',TRUE),
 ('gli_humedad','Humedad (glicerina)','PCT',0,5,'["VEGETAL"]','["GLICERINA-PURA","GLICERINA-CRUDA"]','QUIMICO',FALSE),
 ('gli_ceniza','Ceniza (glicerina)','PCT',0,10,'["VEGETAL"]','["GLICERINA-PURA","GLICERINA-CRUDA"]','QUIMICO',FALSE),
 ('gli_mong','MONG (glicerina)','PCT',0,5,'["VEGETAL"]','["GLICERINA-PURA","GLICERINA-CRUDA"]','QUIMICO',FALSE),
 ('gli_ays','AyS (glicerina)','PCT',0,100,'["VEGETAL"]','["GLICERINA-PURA","GLICERINA-CRUDA"]','QUIMICO',FALSE),
 ('borra_prc_grasa','% Grasa (borra)','PCT',0,100,'["VEGETAL"]','["BORRA-A","BORRA-B"]','QUIMICO',FALSE),
 ('borra_ph','pH (borra)','ADIM',2,12,'["VEGETAL"]','["BORRA-A","BORRA-B"]','QUIMICO',FALSE),
 ('borra_alcalinidad','Alcalinidad (borra)','PCT',0,100,'["VEGETAL"]','["BORRA-A","BORRA-B"]','QUIMICO',FALSE),
 ('concentracion','Concentración','PCT',0,100,'[]','[]','QUIMICO',FALSE)
ON CONFLICT DO NOTHING;

-- Limpieza idempotente: parámetros y catálogos de efluente eliminados del proyecto
DELETE FROM dim_parametro_lab WHERE codigo_parametro LIKE 'eflu%';

-- USUARIO ADMIN inicial: nombre="admin", PIN="1234"
-- (sha256 de "1234" = 03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4)
INSERT INTO dim_usuario(nombre, nombre_full, pin_hash, rol)
VALUES ('admin','Administrador',
        '03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4',
        'ADMIN')
ON CONFLICT DO NOTHING;

-- ===========================================================================
-- LISTA REAL DE PRODUCTOS / MATERIAS PRIMAS WORMS
-- Sincroniza dim_producto con la lista operativa pasada por el cliente.
-- Idempotente: INSERT ... ON CONFLICT DO NOTHING.
-- ===========================================================================

-- 1) Desactivar placeholders previos (no se usan en la planta)
UPDATE dim_producto SET activo=FALSE
WHERE codigo_producto IN ('ACEITE-CRUDO','ACEITE-FILTRADO','ACEITE-REFINADO',
                          'ARE(V)-B','ARE(AN)','SEBO-A.1ra','SEBO-2DA-C',
                          'A-PESCADO','GLICERINA-CRUDA','GLICERINA-PURA');

-- 2) Insertar la lista real (33 productos)
INSERT INTO dim_producto (codigo_producto, nombre_producto, variante, corriente, tipo_producto,
                          usa_piletas, usa_bachas, usa_reactor, es_exportacion,
                          usa_sales, requiere_ag, requiere_are, es_mezcla)
VALUES
  ('AFE-S',           'Aceite filtrado especial S',  'S',  'VEGETAL','INTERMEDIO',TRUE, FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE),
  ('AFE-G',           'Aceite filtrado especial G',  'G',  'VEGETAL','INTERMEDIO',TRUE, FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE),
  ('AFE-SG',          'Aceite filtrado especial SG', 'SG', 'VEGETAL','INTERMEDIO',TRUE, FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE),
  ('AFE-AL',          'Aceite filtrado especial AL', 'AL', 'VEGETAL','INTERMEDIO',TRUE, FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE),
  ('AFE-P',           'Aceite filtrado especial P',  'P',  'VEGETAL','INTERMEDIO',TRUE, FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE),
  ('TCO',             'TCO',                          NULL,'VEGETAL','INTERMEDIO',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('AG-A',            'Aceite genérico A',           'A',  'VEGETAL','INTERMEDIO',TRUE, TRUE, FALSE,FALSE,FALSE,TRUE, FALSE,FALSE),
  ('AG-B',            'Aceite genérico B',           'B',  'VEGETAL','INTERMEDIO',TRUE, TRUE, FALSE,FALSE,FALSE,TRUE, FALSE,FALSE),
  ('AG-C',            'Aceite genérico C',           'C',  'VEGETAL','INTERMEDIO',TRUE, TRUE, FALSE,FALSE,FALSE,TRUE, FALSE,FALSE),
  ('AG-D',            'Aceite genérico D',           'D',  'VEGETAL','INTERMEDIO',TRUE, TRUE, FALSE,FALSE,FALSE,TRUE, FALSE,FALSE),
  ('AG-E',            'Aceite genérico E',           'E',  'VEGETAL','FINAL',     FALSE,FALSE,FALSE,TRUE, FALSE,TRUE, FALSE,FALSE),
  ('ARE-A',           'ARE A',                       'A',  'VEGETAL','FINAL',     FALSE,FALSE,TRUE, FALSE,TRUE, FALSE,TRUE, FALSE),
  ('ARE-B',           'ARE B',                       'B',  'VEGETAL','FINAL',     FALSE,FALSE,TRUE, FALSE,TRUE, FALSE,TRUE, FALSE),
  ('ARE-A-ANIMAL',    'ARE A animal',                'A',  'ANIMAL', 'FINAL',     FALSE,FALSE,TRUE, FALSE,TRUE, FALSE,TRUE, FALSE),
  ('SEBO-A-1RA',      'Sebo A primera',              '1ra','ANIMAL', 'FINAL',     FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('SEBO-B-1RA',      'Sebo B primera',              '1ra','ANIMAL', 'FINAL',     FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('SEBO-A-2DA',      'Sebo A segunda',              '2da','ANIMAL', 'FINAL',     FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('SEBO-B-2DA',      'Sebo B segunda',              '2da','ANIMAL', 'FINAL',     FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('SEBO-C-2DA',      'Sebo C segunda',              '2da','ANIMAL', 'FINAL',     FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('BORRA-A',         'Borra A',                     'A',  'VEGETAL','INTERMEDIO',FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('BORRA-B',         'Borra B',                     'B',  'VEGETAL','INTERMEDIO',FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('BORRA-ANIMAL',    'Borra animal',                NULL, 'ANIMAL', 'INTERMEDIO',FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('BORRA-PES',       'Borra pescado',               NULL, 'ANIMAL', 'INTERMEDIO',FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('AG-PES',          'Aceite genérico pescado',     NULL, 'ANIMAL', 'INTERMEDIO',FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('GLICERINA',       'Glicerina',                   NULL, 'VEGETAL','INTERMEDIO',FALSE,FALSE,TRUE, FALSE,FALSE,FALSE,TRUE, FALSE),
  ('GLICERINA-FE',    'Glicerina F/E',               NULL, 'VEGETAL','FINAL',     FALSE,FALSE,TRUE, FALSE,FALSE,FALSE,TRUE, FALSE),
  ('SAL-GLICERINOSA', 'Sal glicerinosa',             NULL, 'VEGETAL','INTERMEDIO',FALSE,FALSE,TRUE, FALSE,FALSE,FALSE,FALSE,FALSE),
  ('FONDO-TK',        'Fondo de tanque',             NULL, 'VEGETAL','INTERMEDIO',TRUE, TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('EMULSION',        'Emulsión',                    NULL, 'VEGETAL','INTERMEDIO',TRUE, FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('CAUCHO-P1',       'Granulado de caucho P1',      'P1', 'OTRO',   'FINAL',     FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('CAUCHO-P2',       'Granulado de caucho P2',      'P2', 'OTRO',   'FINAL',     FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('CAUCHO-P3',       'Granulado de caucho P3',      'P3', 'OTRO',   'FINAL',     FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
  ('ACERO',           'Acero',                       NULL, 'OTRO',   'FINAL',     FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE)
ON CONFLICT (codigo_producto) DO NOTHING;

-- 3) Asegurar que la lista del usuario esté ACTIVA (por si quedaron desactivados)
UPDATE dim_producto SET activo=TRUE
WHERE codigo_producto IN (
  'AFE-S','AFE-G','AFE-SG','AFE-AL','AFE-P','TCO',
  'AG-A','AG-B','AG-C','AG-D','AG-E',
  'ARE-A','ARE-B','ARE-A-ANIMAL',
  'SEBO-A-1RA','SEBO-B-1RA','SEBO-A-2DA','SEBO-B-2DA','SEBO-C-2DA',
  'BORRA-A','BORRA-B','BORRA-ANIMAL','BORRA-PES','AG-PES',
  'GLICERINA','GLICERINA-FE','SAL-GLICERINOSA',
  'FONDO-TK','EMULSION',
  'CAUCHO-P1','CAUCHO-P2','CAUCHO-P3','ACERO'
);

-- ===========================================================================
-- RANGOS DE KG por producto (validación UI · ajustables desde Admin a futuro)
-- Si el operador carga fuera de estos kg, exige motivo escrito.
-- Editables con UPDATE dim_producto SET rango_kg_min=..., rango_kg_max=...
-- Defaults conservadores; ajustar con datos reales de planta.
-- ===========================================================================
-- Aceites filtrados especiales
UPDATE dim_producto SET rango_kg_min=12000, rango_kg_max=24000
WHERE codigo_producto IN ('AFE-S','AFE-G','AFE-SG','AFE-AL','AFE-P');

-- Aceites genéricos
UPDATE dim_producto SET rango_kg_min=10000, rango_kg_max=22000
WHERE codigo_producto IN ('AG-A','AG-B','AG-C','AG-D','AG-E');

-- ARE
UPDATE dim_producto SET rango_kg_min=15000, rango_kg_max=25000
WHERE codigo_producto IN ('ARE-A','ARE-B','ARE-A-ANIMAL');

-- Sebos
UPDATE dim_producto SET rango_kg_min=8000, rango_kg_max=20000
WHERE codigo_producto IN ('SEBO-A-1RA','SEBO-B-1RA','SEBO-A-2DA','SEBO-B-2DA','SEBO-C-2DA');

-- Borras
UPDATE dim_producto SET rango_kg_min=500, rango_kg_max=3000
WHERE codigo_producto IN ('BORRA-A','BORRA-B','BORRA-ANIMAL','BORRA-PES');

-- Pescado
UPDATE dim_producto SET rango_kg_min=500, rango_kg_max=5000
WHERE codigo_producto IN ('AG-PES');

-- Glicerina y subproductos químicos
UPDATE dim_producto SET rango_kg_min=1000, rango_kg_max=5000
WHERE codigo_producto IN ('GLICERINA','GLICERINA-FE','SAL-GLICERINOSA');

-- Emulsión / fondo
UPDATE dim_producto SET rango_kg_min=200, rango_kg_max=4000
WHERE codigo_producto IN ('EMULSION','FONDO-TK');

-- TCO (sin data → dejar NULL para que admin defina)
-- Caucho / Acero (sin data) → NULL

-- ===========================================================================
-- TIPO_PRODUCTO definitivo · derivado del análisis de ARE/BACHAS/DESGOMADO/PILETAS
-- legacy: AFE/AG/borras/glicerina cruda son INTERMEDIO (vuelven a procesarse).
-- FINAL = lo que se vende y sale de planta. "No son muchos" (9 de 33).
-- ===========================================================================
-- FINAL (sale de planta)
UPDATE dim_producto SET tipo_producto='FINAL'
WHERE codigo_producto IN (
  'AG-E',                                  -- aceite genérico de exportación
  'ARE-A','ARE-B','ARE-A-ANIMAL',          -- biodiesel
  'GLICERINA-FE',                          -- glicerina farma/exportación
  'CAUCHO-P1','CAUCHO-P2','CAUCHO-P3',     -- granulado de caucho (línea aparte)
  'ACERO'                                  -- subproducto recuperado
);

-- MP (materia prima · entra al proceso)
UPDATE dim_producto SET tipo_producto='MP'
WHERE codigo_producto IN (
  'AFE-S','AFE-G','AFE-SG','AFE-AL','AFE-P','TCO',
  'AG-A','AG-B','AG-C','AG-D',
  'SEBO-A-1RA','SEBO-B-1RA','SEBO-A-2DA','SEBO-B-2DA','SEBO-C-2DA',
  'BORRA-A','BORRA-B','BORRA-ANIMAL','BORRA-PES','AG-PES',
  'GLICERINA','SAL-GLICERINOSA',
  'FONDO-TK','EMULSION'
);

-- Migrar productos viejos que quedaron como 'INTERMEDIO' (placeholders desactivados)
-- a 'MP' por consistencia. No tiene efecto operativo (están activo=FALSE).
UPDATE dim_producto SET tipo_producto='MP'
WHERE tipo_producto='INTERMEDIO';

-- Limpieza idempotente: producto 'EFLUENTE' fuera del proyecto
DELETE FROM dim_producto WHERE codigo_producto='EFLUENTE';

-- Aplicar CHECK · sin EFLUENTE (efluentes vienen de otra fuente)
ALTER TABLE dim_producto DROP CONSTRAINT IF EXISTS chk_tipo_producto;
ALTER TABLE dim_producto
  ADD CONSTRAINT chk_tipo_producto
  CHECK (tipo_producto IN ('MP','FINAL','INSUMO'));

-- ===========================================================================
-- REACTORES · sector unificado, bienes de uso, procesos principales, etapas
-- ===========================================================================

-- Sector REACTORES
INSERT INTO dic_sector(codigo, nombre_ui, color_hex, unidad_principal) VALUES
 ('REACTORES','REACTORES','#1d4ed8','TN')
ON CONFLICT (codigo) DO NOTHING;

UPDATE dic_sector SET activo=FALSE WHERE codigo IN ('ARE','DESGOMADO');

-- Bienes de uso
INSERT INTO dim_bien_uso(codigo, nombre_ui, tipo) VALUES
 ('REACTOR_1','REACTOR 1','REACTOR'),
 ('REACTOR_2','REACTOR 2','REACTOR')
ON CONFLICT (codigo) DO NOTHING;

-- Procesos principales (solo 2)
DELETE FROM dic_tipo_proceso WHERE codigo IN ('REACCION','TRATAMIENTO_CITRICO','TRATAMIENTO_TERMICO','ELABORACION_ARE');
INSERT INTO dic_tipo_proceso(codigo, descripcion) VALUES
 ('PRODUCCION_ARE',   'Producción de ARE (biodiesel)'),
 ('DESGOMADO_ACUOSO', 'Desgomado acuoso')
ON CONFLICT (codigo) DO NOTHING;

-- Etapas dentro de un proceso
INSERT INTO dic_etapa_proceso(codigo, descripcion, orden) VALUES
 ('ARMADO',           'Armado · mezcla de insumos',                1),
 ('REACCION',         'Reacción · fuel, calor',                    2),
 ('INSISTENCIA',      'Insistencia · hasta acidez objetivo',       3),
 ('REPOSANDO',        'Producto reposando',                        4),
 ('DECANTACION',      'Decantación · salen finales y paralelos',   5),
 ('EN_TANQUE',        'Producto final en tanque (a laboratorio)',  6)
ON CONFLICT (codigo) DO NOTHING;

-- Parámetros de proceso (con rangos típicos en notas)
DELETE FROM dic_parametro_proceso WHERE codigo IN ('acidez_inicial','acidez_final','temperatura_inicio','temperatura_fin','ppm_fosforo','prc_goma','q_merma_kg');
INSERT INTO dic_parametro_proceso(codigo, descripcion, unidad, aplica_a) VALUES
 ('acidez',            'Acidez',              '%',   '["PRODUCCION_ARE","DESGOMADO_ACUOSO"]'),
 ('temperatura',       'Temperatura',         '°C',  '["PRODUCCION_ARE","DESGOMADO_ACUOSO"]'),
 ('ppm_fosforo',       'ppm Fósforo',         'ppm', '["DESGOMADO_ACUOSO"]'),
 ('prc_goma',          '% Goma',              '%',   '["DESGOMADO_ACUOSO"]'),
 ('q_merma_kg',        'Merma',               'kg',  '["PRODUCCION_ARE","DESGOMADO_ACUOSO"]')
ON CONFLICT (codigo) DO NOTHING;

-- Insumo AGUA para desgomado acuoso (estaba faltando)
INSERT INTO dic_insumo(codigo, descripcion, unidad) VALUES
 ('AGUA','Agua proceso','L')
ON CONFLICT (codigo) DO NOTHING;

-- Densidades (g/mL · sirven para convertir L↔kg en la app)
UPDATE dim_producto SET densidad_g_ml=0.890 WHERE codigo_producto IN ('AFE-S','AFE-G','AFE-SG','AFE-AL','AFE-P','AG-A','AG-B','AG-C','AG-D','AG-E');
UPDATE dim_producto SET densidad_g_ml=0.880 WHERE codigo_producto IN ('ARE-A','ARE-B','ARE-A-ANIMAL');
UPDATE dim_producto SET densidad_g_ml=1.260 WHERE codigo_producto IN ('GLICERINA','GLICERINA-FE');
UPDATE dim_producto SET densidad_g_ml=0.920 WHERE codigo_producto IN ('SEBO-A-1RA','SEBO-B-1RA','SEBO-A-2DA','SEBO-B-2DA','SEBO-C-2DA');
UPDATE dim_producto SET densidad_g_ml=0.950 WHERE codigo_producto IN ('BORRA-A','BORRA-B','BORRA-ANIMAL','BORRA-PES');
UPDATE dim_producto SET densidad_g_ml=0.910 WHERE codigo_producto IN ('AG-PES','EMULSION','FONDO-TK');

-- ===========================================================================
-- DEMO: 10 reacciones random + muestras intermedias (idempotente)
-- Borra cargas previas del usuario "admin" en sector REACTORES y reinserta.
-- ===========================================================================

-- Borrar demo previa
DELETE FROM fact_muestra_proceso
WHERE id_batch IN (
  SELECT id_batch FROM fact_batch_proceso b
  WHERE b.sector='REACTORES'
    AND b.observaciones='[DEMO]'
);
DELETE FROM fact_batch_proceso WHERE sector='REACTORES' AND observaciones='[DEMO]';

-- Generar 10 reacciones (5 PRODUCCION_ARE + 5 DESGOMADO_ACUOSO)
WITH gen AS (
  SELECT
    n,
    CASE WHEN n <= 5 THEN 'PRODUCCION_ARE' ELSE 'DESGOMADO_ACUOSO' END        AS tipo,
    CASE WHEN n % 2 = 0 THEN 'REACTOR_1' ELSE 'REACTOR_2' END                 AS reactor,
    (CURRENT_DATE - (n || ' days')::INTERVAL)::DATE                           AS fecha,
    CASE WHEN n <= 5 THEN 'ARE-A' ELSE 'AFE-S' END                            AS p_obt,
    CASE WHEN n <= 5 THEN 'AG-A'  ELSE 'AG-C'  END                            AS p_ini,
    (15000 + (random()*8000))::NUMERIC(10,1)                                  AS kg_ini,
    (14000 + (random()*8000))::NUMERIC(10,1)                                  AS kg_obt,
    (random()*4 + 4)::NUMERIC(4,1)                                            AS horas
  FROM generate_series(1,10) n
)
INSERT INTO fact_batch_proceso (
  fecha, sector, turno, id_usuario_carga, tipo_operacion,
  identificador_unidad, id_producto_inicial, kg_inicial, id_producto_obtenido, kg_obtenido,
  horas_trabajadas, calidad_final, insumos, materias_primas_extras,
  id_bien_uso, tipo_proceso, etapa_actual, inicio_ts, fin_ts, tiempo_estimado_horas,
  parametros_proceso,
  gli_fresca_lts, gli_fresca_kg, gli_recup_lts, gli_recup_kg, gli_pct_real,
  agua_lts, observaciones
)
SELECT
  g.fecha, 'REACTORES', 'mañana', 1, 'NORMAL',
  'T-DEMO-' || lpad(g.n::text, 3, '0'),
  (SELECT id_producto FROM dim_producto WHERE codigo_producto=g.p_ini),
  g.kg_ini::DOUBLE PRECISION,
  (SELECT id_producto FROM dim_producto WHERE codigo_producto=g.p_obt),
  g.kg_obt::DOUBLE PRECISION,
  g.horas::DOUBLE PRECISION,
  (ARRAY['A','B','C'])[1 + floor(random()*3)::int],
  CASE WHEN g.tipo='PRODUCCION_ARE'
       THEN jsonb_build_object('METANOL', round((300 + random()*200)::numeric,1),
                               'KOH',     round(( 80 + random()* 40)::numeric,1))
       ELSE jsonb_build_object('ACIDO-SULF', round(( 50 + random()* 30)::numeric,1),
                               'SODA',       round(( 30 + random()* 20)::numeric,1),
                               'AGUA',       round((800 + random()*400)::numeric,1))
  END,
  '[]'::jsonb,
  (SELECT id_bien_uso FROM dim_bien_uso WHERE codigo=g.reactor),
  g.tipo,
  'EN_TANQUE',
  (g.fecha + TIME '06:00')::TIMESTAMPTZ,
  (g.fecha + TIME '06:00')::TIMESTAMPTZ + (g.horas || ' hours')::INTERVAL,
  round((g.horas + (random()-0.5))::numeric, 1)::DOUBLE PRECISION,
  CASE WHEN g.tipo='PRODUCCION_ARE'
       THEN jsonb_build_object('acidez', 9.8 + random()*0.4,
                               'temperatura', 60 + random()*5,
                               'q_merma_kg', round((50 + random()*150)::numeric,0))
       ELSE jsonb_build_object('acidez', round((0.5 + random()*1.5)::numeric,2),
                               'temperatura', 55 + random()*8,
                               'ppm_fosforo', round((60 + random()*120)::numeric,0),
                               'prc_goma', round((1 + random()*5)::numeric,1),
                               'q_merma_kg', round((30 + random()*100)::numeric,0))
  END,
  -- Glicerina fresca (solo PRODUCCION_ARE)
  CASE WHEN g.tipo='PRODUCCION_ARE' THEN round((300 + random()*100)::numeric,1) END,
  CASE WHEN g.tipo='PRODUCCION_ARE' THEN round(((300 + random()*100) * 1.26)::numeric,1) END,
  -- Glicerina recuperada
  CASE WHEN g.tipo='PRODUCCION_ARE' THEN round((100 + random()*60)::numeric,1) END,
  CASE WHEN g.tipo='PRODUCCION_ARE' THEN round(((100 + random()*60) * 1.26)::numeric,1) END,
  CASE WHEN g.tipo='PRODUCCION_ARE' THEN round((85 + random()*10)::numeric,1) END,
  -- Agua (solo DESGOMADO_ACUOSO)
  CASE WHEN g.tipo='DESGOMADO_ACUOSO' THEN round((800 + random()*400)::numeric,1) END,
  '[DEMO]'
FROM gen g;

-- 3 muestras intermedias por batch demo (inicio · medio · fin)
INSERT INTO fact_muestra_proceso (id_batch, ts, etapa, mediciones, id_usuario_carga)
SELECT
  b.id_batch,
  b.inicio_ts + ((etapa_n-1) * (b.fin_ts - b.inicio_ts) / 2),
  CASE etapa_n WHEN 1 THEN 'ARMADO' WHEN 2 THEN 'REACCION' WHEN 3 THEN 'INSISTENCIA' END,
  CASE
    WHEN b.tipo_proceso='PRODUCCION_ARE'
      THEN jsonb_build_object(
             'acidez',  round((30 - etapa_n*8 + random()*3)::numeric, 2),
             'temperatura', round((55 + etapa_n*2 + random()*3)::numeric, 1)
           )
    ELSE jsonb_build_object(
             'acidez',       round((0.5 + (3-etapa_n)*0.6 + random()*0.4)::numeric, 2),
             'ppm_fosforo',  round((150 - etapa_n*30 + random()*15)::numeric, 0),
             'prc_goma',     round((6 - etapa_n*1.5 + random())::numeric, 2)
           )
  END,
  1
FROM fact_batch_proceso b
CROSS JOIN generate_series(1,3) etapa_n
WHERE b.sector='REACTORES' AND b.observaciones='[DEMO]';
