# ROADMAP — Implementación nueva_era (3 semanas)

> Inicio: lunes siguiente a aprobación. Las fechas se completan al firmar el plan.

## Equipo
- **Felipe (F)** — implementación, ETL, schema, app.
- **Eugenia (E)** — validación operativa, datos maestros, capacitación.
- **Pablo Z (P)** — métricas TN, formulaciones, reglas de negocio.
- **Supervisores (S)** — UAT (User Acceptance Testing).

---

## SEMANA 1 — Definición estándar + migración piloto

### Lun (D1) — Setup técnico
- [F] Crear DB `worms_prod` en servidor físico.
- [F] Ejecutar `01_schema/00_run_all.sql`.
- [F] Ejecutar `02_seed_data/00_run_all_seed.sql`.
- [F] Smoke test: `SELECT COUNT(*) FROM dim_producto;`
- **Aceptación:** schema creado sin errores, 25+ productos en `dim_producto`.

### Mar (D2) — Catálogo maestro
- [F + E] Revisar `dim_producto` completo (productos vivos hoy + descontinuados).
- [P] Confirmar `corriente` y flags (`usa_piletas`, `requiere_are`, etc.) por producto.
- [F] Cargar productos faltantes vía SQL.
- **Aceptación:** Euge firma lista de productos.

### Mié (D3) — Parámetros + unidades
- [E + P] Revisar `dim_parametro_lab`: rangos por producto, parámetros que faltan.
- [F] Cargar densidades reales en `ref_conversion_unidades` (L→KG por producto).
- [P] Cargar formulaciones baseline en `ref_formulacion_producto` (al menos ARE, AG-C, AFE-S).
- **Aceptación:** parámetros con rango realista, 5+ formulaciones cargadas y firmadas.

### Jue (D4) — ETL legacy (dry-run)
- [F] `python -m nueva_era.etl.etl_legacy --dry-run`.
- [F] Triage del reporte de errores → ajustar `PRODUCTO_ALIAS`, dar de alta lo que falte.
- [E] Revisar muestreo de 20 filas convertidas vs Excel original.
- **Aceptación:** dry-run con 0 errores ó errores listados y excusados.

### Vie (D5) — Carga real piloto + validación
- [F] ETL real, `fact_batch_proceso` + `fact_analisis_lab` + `fact_parametro_valor` poblados.
- [F] Rollup `fact_produccion_diaria`.
- [E] Cruzar 3 días aleatorios contra dashboard actual: TN debería coincidir ±2%.
- [F] Configurar backup nocturno (`pg_dump`).
- **Aceptación:** datos del trimestre cargados; cierre del viernes se compara contra Excel y coincide.

---

## SEMANA 2 — App de carga + dashboard v1

### Lun (D6) — App de carga (UAT)
- [F] Levantar `app_carga/app.py` en servidor.
- [E + 2 operadores] Carga manual de prueba (lab, batch, efluente).
- [F] Bug-fix UI según feedback.
- **Aceptación:** 3 cargas reales hechas por operadores sin asistencia.

### Mar (D7) — Validaciones + alertas
- [F] Ajustar `validaciones.py` con reglas adicionales que pida Pablo Z.
- [F] Vista `v_alertas_lab` exportada a email diario (parámetros fuera de rango ayer).
- **Aceptación:** Pablo recibe el primer email de alertas y lo aprueba.

### Mié (D8) — Dashboard v1 (Streamlit / reemplazo Dashboard.html)
- [F] KPIs: producción TN x sector x día, calidad %, efluentes resumidos.
- [F] Filtros: fecha, producto, empleado, corriente.
- [F] Vista mensual vs meta (`v_kpi_mensual_vs_meta`).
- **Aceptación:** Pablo Z ve los TN del mes y matchean su Excel.

### Jue (D9) — UAT supervisores
- [S] 3 supervisores prueban dashboard 30 min cada uno.
- [F] Logging del feedback, fix de blockers.
- **Aceptación:** lista de bugs P0/P1 resueltos.

### Vie (D10) — Documentación final
- [F] Actualizar `04_instalacion.md` con cualquier paso descubierto.
- [E + F] Pasar SOP a formato imprimible.
- [F] Tag `v1.0` en repo.
- **Aceptación:** SOP firmado por Euge, instalación replicada en máquina test.

---

## SEMANA 3 — Capacitación + launch

### Lun (D11) — Capacitación operadores (turnos mañana)
- [E] 1h x turno, hands-on con la app.
- Material: SOP impreso + cartelera con URL y password.

### Mar (D12) — Capacitación turnos tarde / noche
- [E] mismo formato.
- [F] Soporte en sala.

### Mié (D13) — Soft launch piloto
- 1 sector elegido (ARE), en paralelo con Excel viejo.
- [E + F] Comparación end-of-day: Excel vs BD; deberían coincidir.

### Jue (D14) — Launch full
- Todos los sectores cargan en la app.
- Excel viejo → modo lectura (`read-only` en NAS).
- [F] Monitoreo activo, support en Slack interno.

### Vie (D15) — Cierre + retrospectiva
- [F + E + P] Retro 1h.
- Plan de mejoras v1.1.
- Comunicación a equipo de "fin de semana 1 en producción".

---

## Entregables al final de S3
1. **BD PostgreSQL productiva** en servidor físico, con backup diario.
2. **Dashboard v1** (Streamlit) reemplazando `Dashboard.html`.
3. **App de carga** con audit trail.
4. **Documentación**: arquitectura, diccionario, instalación, SOP, troubleshooting.
5. **Script ETL** (`nueva_era/etl/`) reusable para migraciones futuras.
6. **Vistas KPI** consumibles por cualquier herramienta (PowerBI, Excel, etc.).
7. **Auditoría completa**: quién, cuándo, qué cambió.
8. **Alertas automáticas**: parámetros fuera de rango por email.

---

## Métricas de éxito (revisadas en retro)
| Métrica | Target | Cómo se mide |
|---|---|---|
| Errores de carga / 100 cargas | < 2 | conteo en `aud_eventos` con UPDATE inmediato |
| Tiempo medio de carga lab | < 90 s | timestamps app |
| Cobertura de datos vs Excel viejo | ≥ 98% | conciliación end-of-week |
| Alertas fuera de rango detectadas | 100% en < 24h | cruzar `v_alertas_lab` con plantillas papel |
| Adopción operadores | 100% sectores en S3D14 | logins distintos / día |

---

## Preguntas abiertas al equipo (responder antes de S1D1)

| # | Pregunta | Quién responde |
|---|---|---|
| 1 | ¿Productos final del catálogo o se agregan variantes nuevas? | Euge / Pablo Z |
| 2 | ¿Lista completa de parámetros de lab o falta alguno? | Euge |
| 3 | ¿Recetas / formulaciones documentadas o las derivamos del histórico? | Pablo Z |
| 4 | ¿Servidor PostgreSQL OK en 192.168.1.5? Puerto / firewall? | IT |
| 5 | ¿Migrar histórico completo o desde fecha X? | Pablo Z |
| 6 | ¿Métricas adicionales / gráficos específicos para el dashboard v1? | Pablo Z + supervisores |
| 7 | ¿Todos los análisis generan efluente o solo algunos? | Euge |
| 8 | ¿Quién es el dueño de los datos maestros (productos / parámetros)? | Euge (propuesta) |
| 9 | ¿Política de retención de backups? | IT |
| 10| ¿Acceso SSO o usuario/clave manual? | IT |
