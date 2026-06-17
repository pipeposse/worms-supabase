# SOP — Carga diaria de datos · WORMS

## Quién
- **Operador** (turno): carga su propia producción del turno.
- **Laboratorista**: carga análisis de muestras del día.
- **Supervisor**: revisa, marca como `ACEPTADO` los pendientes.

## Cuándo
- Al finalizar el turno o cada vez que se cierra un batch.
- Lab: dentro de las 2 horas de obtenido el resultado.

## Cómo (5 pasos)
1. Abrí `http://192.168.1.5:8501` desde la PC del sector.
2. Ingresá tu **usuario** en la barra lateral (ej. `Sosa`, `euge`, `pabloz`).
3. Elegí la pestaña que corresponde:
   - **Laboratorio** → análisis de muestras.
   - **Batch proceso** → producción del reactor / desgomado / bachas / piletas.
   - **Efluente** → carga rápida de un efluente.
4. Completá los campos. Click **Validar y previsualizar**.
   - Si aparece ❌ rojo = no podés cargar; corrige.
   - Si aparece ⚠️ amarillo = revisá pero podés continuar.
5. Click **Confirmar e insertar**. Ves el ID asignado (ej. `Análisis #1234 guardado`).

## Reglas
- **No usar la planilla compartida vieja** una vez en producción la nueva BD.
- Si un parámetro no aparece en el desplegable, pedirle a Felipe que lo agregue al catálogo.
- Si te equivocás, NO borres: contactá al supervisor para corregir (queda en audit).
- Toda carga queda registrada con tu usuario y fecha/hora — no compartas tu nombre.

## Bulk upload (cargar Excel completo)
Sólo supervisor / Felipe:
1. Pestaña **Bulk upload**.
2. Elegir tipo (`laboratorio` / `batch` / `efluente`).
3. Subir archivo. La app muestra preview + errores.
4. Si hay errores → corregir el Excel y volver a subir.
5. Si OK → ejecutar comando indicado.

## Casos típicos
| Síntoma | Acción |
|---|---|
| "Producto no encontrado" | Pedir alta en `dim_producto` (Felipe) |
| "Parámetro fuera de rango" | Confirmar valor y elegir estado `FUERA_ESPECIFICACION` |
| "App no abre" | Reiniciar Streamlit en servidor (`run.bat`) |
| Caída de red | Anotar en planilla papel, cargar al volver la conexión |
