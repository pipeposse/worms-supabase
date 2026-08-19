# -*- coding: utf-8 -*-
"""🎯 Metas del mes — fijadas por dirección, editables desde la app.

Una fila por mes en `produccion.meta_mensual`. Cantidad y calidad:
despachos (TN y % máximo fuera de especificación), desgomado acuoso
(TN y % mínimo en categoría A/B) y producción de ARE (TN y acidez final
máxima del ARE-B). El brief semanal las lee y muestra "Metas del mes"
en la primera página, con lo real a la fecha y la proyección.
"""
from datetime import date

import pandas as pd
import streamlit as st

_COLS = ["mes", "despachos_tn", "fuera_spec_max_pct", "desgomado_tn",
         "desgomado_ab_pct", "are_tn", "are_acidez_max", "nota"]


def _usuario(USR):
    return str(USR.get("nombre") or USR.get("usuario") or USR.get("id_usuario") or "app")


def _num(v):
    if v is None or v == "":
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return float(v)


def _txt(v):
    if v is None or v == "":
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return str(v)


def editor(USR, cat, conectar):
    """Expander de edición. Upsert por mes; para 'borrar' un mes, vaciar sus valores."""
    with st.expander("🎯 Metas del mes — fijadas por dirección (editar)", expanded=False):
        st.caption(
            "Estas metas alimentan la sección **Metas del mes** de la primera página del "
            "brief. Una fila por mes (se puede agregar el mes que viene con ➕). "
            "Cantidad en TN; calidad: % máximo de despachos fuera de espec, % mínimo del "
            "desgomado en categoría A/B y acidez final máxima del ARE-B. Un valor vacío "
            "aparece como *s/d* en el brief.")
        try:
            df = cat("SELECT mes, despachos_tn, fuera_spec_max_pct, desgomado_tn, "
                     "desgomado_ab_pct, are_tn, are_acidez_max, nota "
                     "FROM produccion.meta_mensual ORDER BY mes DESC LIMIT 24")
        except Exception as e:
            st.error(f"No se pudieron leer las metas: {e}")
            return
        if df.empty:
            df = pd.DataFrame(columns=_COLS)
        df["mes"] = pd.to_datetime(df["mes"]).dt.date

        ed = st.data_editor(
            df, key="metas_editor", num_rows="dynamic", use_container_width=True,
            column_config={
                "mes": st.column_config.DateColumn(
                    "Mes", format="YYYY-MM",
                    help="Cualquier día del mes vale: se guarda como el mes entero."),
                "despachos_tn": st.column_config.NumberColumn(
                    "Despachos TN", min_value=0.0, step=50.0),
                "fuera_spec_max_pct": st.column_config.NumberColumn(
                    "Fuera de espec ≤ %", min_value=0.0, max_value=100.0, step=1.0),
                "desgomado_tn": st.column_config.NumberColumn(
                    "Desgomado TN", min_value=0.0, step=10.0),
                "desgomado_ab_pct": st.column_config.NumberColumn(
                    "Desgomado A/B ≥ %", min_value=0.0, max_value=100.0, step=5.0),
                "are_tn": st.column_config.NumberColumn(
                    "ARE TN", min_value=0.0, step=10.0),
                "are_acidez_max": st.column_config.NumberColumn(
                    "ARE acidez ≤ %", min_value=0.0, max_value=100.0, step=0.5),
                "nota": st.column_config.TextColumn("Nota"),
            })

        if conectar is None:
            st.info("Este contexto no tiene conexión de escritura (sólo lectura).")
            return
        if not st.button("💾 Guardar metas", type="primary", key="metas_guardar"):
            return

        filas = []
        for _, r in ed.iterrows():
            m = r.get("mes")
            if m is None or (isinstance(m, float) and pd.isna(m)) or m == "":
                continue
            if hasattr(m, "year"):
                m = date(int(m.year), int(m.month), 1)
            filas.append((m, _num(r.get("despachos_tn")), _num(r.get("fuera_spec_max_pct")),
                          _num(r.get("desgomado_tn")), _num(r.get("desgomado_ab_pct")),
                          _num(r.get("are_tn")), _num(r.get("are_acidez_max")),
                          _txt(r.get("nota"))))
        if not filas:
            st.warning("No hay filas con mes para guardar.")
            return
        try:
            with conectar(USR["id_usuario"]) as (conn, audit):
                with conn.cursor() as cur:
                    for f in filas:
                        cur.execute(
                            "INSERT INTO produccion.meta_mensual (mes, despachos_tn, "
                            "fuera_spec_max_pct, desgomado_tn, desgomado_ab_pct, are_tn, "
                            "are_acidez_max, nota, actualizado_en, actualizado_por) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now(), %s) "
                            "ON CONFLICT (mes) DO UPDATE SET "
                            "despachos_tn = EXCLUDED.despachos_tn, "
                            "fuera_spec_max_pct = EXCLUDED.fuera_spec_max_pct, "
                            "desgomado_tn = EXCLUDED.desgomado_tn, "
                            "desgomado_ab_pct = EXCLUDED.desgomado_ab_pct, "
                            "are_tn = EXCLUDED.are_tn, "
                            "are_acidez_max = EXCLUDED.are_acidez_max, "
                            "nota = EXCLUDED.nota, actualizado_en = now(), "
                            "actualizado_por = EXCLUDED.actualizado_por",
                            f + (_usuario(USR),))
            try:
                cat.clear()
            except Exception:
                pass
            st.success(f"✅ Metas guardadas ({len(filas)} mes/es). "
                       "El brief las toma al regenerarse.")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudieron guardar las metas: {e}")
