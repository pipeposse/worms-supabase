# Diagnóstico de archivos legacy (excluye efluentes)

Inspección hecha sobre `00_inputs/*.xlsx` (snapshot mayo 2026).

## are.xlsx — Reactor ARE (96 filas)
| Columna legacy | Tipo | Problema |
|---|---|---|
| Fecha | date | OK |
| Turno | str (mañana/tarde/noche) | sin diccionario |
| Operador | str libre | sin tabla maestra → typos |
| Producto a procesar | str (`aceite_refinado`) | naming snake_case, no matchea catálogo |
| Kg a procesar / Kg obtenido | numérico | unidad implícita |
| Producto obtenido | str (`biodiesel`) | debería ser `ARE(V)-B` |
| Kg glicerina, Metanol, Catalizador | numérico | no segregados; faltan unidades |
| Hs trabajadas | numérico | sin link a empleado |

## bachas.xlsx — Bachas (96)
| Columna | Problema |
|---|---|
| N Bacha | id físico de bacha — no existe `dim_tanque` |
| Producto inicial | snake_case sin diccionario |
| Producto obtenido | sí matchea catálogo (`AG-C`, `AFE`) |
| Ácido / Soda | unidad implícita kg |
| Hs | sin operador |

## desgomado.xlsx (96)
- Mezcla turno + operario en columnas separadas pero sin FK.
- Columnas con tildes (`Ácido sulfúrico`, `Soda cáustica`) → fragilidad de parser.
- `Observaciones` libre.

## piletas.xlsx (96)
- `N Pileta` — sin tanque maestro.
- `Estado inicial` (`decantado`) — no es producto, es estado del proceso → debería estar en otra dimensión.
- `Producto Final` matchea (`AFE`, `AG-C`).
- `Floculante` numérico sin unidad.

## laboratorio.xlsx (180)
- **único archivo en long-format** (parámetro / valor / unidad). Buen punto de partida.
- Columna `Sector` mezcla sectores y no-sectores (`RECUPERACION`, `ARE`).
- `Producto analizado` viene en formatos mixtos (`glicerina`, `AFE`).
- `Calidad final` y `Rechazo` son redundantes (rechazo = calidad RECH).
- Parámetros sin catálogo (`acidez`, `humedad`, `indice_iodo`).

## efluentes.xlsx
**No se modifica.** Sólo se replica al fact_efluente vía referencia / FK.

## Problemas transversales
1. Productos: cada archivo usa una nomenclatura distinta (`AFE`, `AFE-S`, `AFE(S)`).
2. Unidades implícitas: TODO en kg, sin marcador → mezclar con datos en TN o L produce errores silenciosos.
3. Operadores y tanques sin maestro: imposible auditar.
4. Mezclas wide / long: laboratorio es long, el resto es wide; el dashboard tiene que reconciliarlos cada vez.
5. No hay versión de formulación: cualquier cambio histórico se pierde.
6. No hay audit trail: si un valor cambia, no queda quién/cuándo.
7. Metas duplicadas: `metas.xlsx` + `metas_provisorias.yaml` + `config_dashboard.xlsx` (tres fuentes de verdad).
8. Carga manual frágil (Excel compartido en red `\\192.168.1.5\...`) sin lock ni validación.

## Decisión de rediseño
- Una sola BD relacional (PostgreSQL en servidor físico).
- **Productos**: catálogo único (`dim_producto`, código canónico).
- **Parámetros**: long-format global (`fact_parametro_valor`) — como laboratorio actual, extendido a todos.
- **Procesos**: `fact_batch_proceso` reemplaza are/bachas/desgomado/piletas. Los insumos van a `JSONB` para no inflar el schema.
- **Unidades**: cada valor lleva `unidad_original`. Trigger convierte a unidad estándar y marca `fuera_de_rango`.
- **Audit trail** automático con triggers + `app.usuario` por sesión.
- **Metas**: tabla única `ref_meta_produccion` (TN), reemplaza las 3 fuentes.
- **Efluentes**: tabla `fact_efluente` segregada con FK opcional al análisis. La base existente queda intacta.
