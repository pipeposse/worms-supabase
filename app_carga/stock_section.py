"""Sección Stock: movimientos (libro mayor), stock por tanque en tiempo real
(estimado = última medición + movimientos ejecutados) y reconciliación.
Todo descargable. render(USR, cat) recibe el helper cacheado de app.py.
"""
import pandas as pd
import streamlit as st


def _dl(df, name, key):
    st.download_button("⬇️ Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=name, mime="text/csv", key=key, use_container_width=True)


def render(USR, cat):
    st.title("📦 Stock y movimientos")
    with st.expander("¿Cómo se calcula el stock teórico?", expanded=False):
        st.markdown(
            "**Stock estimado = última medición física + Σ movimientos ejecutados desde esa medición.**\n\n"
            "- La medición física (sensor WeDo cada ~20 min o carga manual 1/día) es la **verdad**, pero discreta.\n"
            "- Cada movimiento confirmado (un ticket `MS-xxxxxxxx`) actualiza el stock al instante.\n"
            "- Así, incluso un tanque medido 1 vez al día queda **vivo**. La **confianza** indica qué tan fresco es el dato.\n"
            "- La **reconciliación** compara la próxima lectura física contra el libro y marca descuadres (posible fuga/movimiento no registrado).")

    t1, t2, t3 = st.tabs(["🛢️ Stock por tanque (tiempo real)", "🔁 Movimientos", "🛡️ Reconciliación"])

    # ---------- 1 · Stock por tanque ----------
    with t1:
        df = cat("SELECT codigo, sector, producto_principal_txt AS producto, fuente_medicion, "
                 "antiguedad_min, cadencia_sensor_min, litros_medido, delta_litros_ejecutado, "
                 "litros_estimado, confianza, movs_desde_medicion, movs_pendientes "
                 "FROM reporting.v_tanque_stock_estimado st "
                 "LEFT JOIN produccion.dim_tanque t USING (id_tanque) "
                 "ORDER BY litros_estimado DESC NULLS LAST")
        c1, c2 = st.columns(2)
        sectores = ["(todos)"] + sorted([s for s in df["sector"].dropna().unique()])
        fsec = c1.selectbox("Sector", sectores, key="stk_sec")
        confs = ["(todas)"] + sorted([s for s in df["confianza"].dropna().unique()])
        fcon = c2.selectbox("Confianza", confs, key="stk_conf")
        d = df.copy()
        if fsec != "(todos)":
            d = d[d["sector"] == fsec]
        if fcon != "(todas)":
            d = d[d["confianza"] == fcon]

        k1, k2, k3 = st.columns(3)
        k1.metric("Tanques", len(d))
        k2.metric("Stock estimado (L)", f"{pd.to_numeric(d['litros_estimado'], errors='coerce').sum():,.0f}")
        k3.metric("Con baja confianza", int((d["confianza"].isin(["BAJA", "SIN_DATO"])).sum()))

        st.dataframe(
            d, use_container_width=True, hide_index=True,
            column_config={
                "litros_medido": st.column_config.NumberColumn("Medido (L)", format="%.0f"),
                "delta_litros_ejecutado": st.column_config.NumberColumn("Δ movimientos (L)", format="%.0f"),
                "litros_estimado": st.column_config.NumberColumn("Estimado (L)", format="%.0f"),
                "antiguedad_min": st.column_config.NumberColumn("Antigüedad (min)", format="%.0f"),
                "cadencia_sensor_min": st.column_config.NumberColumn("Cadencia (min)", format="%.0f"),
            })
        _dl(d, "stock_tanques.csv", "dl_stk")

    # ---------- 2 · Movimientos ----------
    with t2:
        mv = cat("SELECT momento, ticket_mov, identificador_prod, estado_mov, tipo_movimiento, rol, "
                 "COALESCE(producto, codigo_insumo) AS item, fuente, "
                 "COALESCE(tanque_label, ticket_porteria) AS origen, cantidad, unidad, kg, litros, "
                 "kg_neto, litros_neto, origen AS registrado_por "
                 "FROM reporting.v_movimientos_stock ORDER BY momento DESC")
        f1, f2, f3 = st.columns(3)
        est = ["(todos)"] + sorted(mv["estado_mov"].dropna().unique().tolist())
        fest = f1.selectbox("Estado", est, key="mv_est")
        rol = ["(todos)"] + sorted(mv["rol"].dropna().unique().tolist())
        frol = f2.selectbox("Rol", rol, key="mv_rol")
        fue = ["(todas)"] + sorted(mv["fuente"].dropna().unique().tolist())
        ffue = f3.selectbox("Fuente", fue, key="mv_fue")
        d = mv.copy()
        if fest != "(todos)":
            d = d[d["estado_mov"] == fest]
        if frol != "(todos)":
            d = d[d["rol"] == frol]
        if ffue != "(todas)":
            d = d[d["fuente"] == ffue]

        k1, k2, k3 = st.columns(3)
        k1.metric("Movimientos", len(d))
        k2.metric("Ingresos netos (kg)", f"{pd.to_numeric(d['kg_neto'], errors='coerce').clip(lower=0).sum():,.0f}")
        k3.metric("Egresos netos (kg)", f"{-pd.to_numeric(d['kg_neto'], errors='coerce').clip(upper=0).sum():,.0f}")

        st.dataframe(
            d, use_container_width=True, hide_index=True,
            column_config={
                "momento": st.column_config.DatetimeColumn("Momento", format="DD/MM/YYYY HH:mm"),
                "kg": st.column_config.NumberColumn(format="%.0f"),
                "litros": st.column_config.NumberColumn(format="%.0f"),
                "kg_neto": st.column_config.NumberColumn("kg neto", format="%.0f"),
                "litros_neto": st.column_config.NumberColumn("L neto", format="%.0f"),
            })
        _dl(d, "movimientos_stock.csv", "dl_mv")
        st.caption("PLANIFICADO = creado por dirección · EJECUTADO = confirmado por el operario (afecta stock).")

    # ---------- 3 · Reconciliación ----------
    with t3:
        rc = cat("SELECT momento, tanque, litros_medido, litros_esperado, discrepancia_litros, "
                 "severidad, ajuste_ticket FROM reporting.v_reconciliacion_stock ORDER BY momento DESC")
        if rc.empty:
            st.info("Todavía no hay reconciliaciones registradas (el job corre cada 30 min).")
        else:
            a1, a2 = st.columns(2)
            a1.metric("Lecturas reconciliadas", len(rc))
            a2.metric("Alertas", int((rc["severidad"] == "ALERTA").sum()))
            solo_alerta = st.toggle("Sólo alertas", value=False, key="rc_alerta")
            d = rc[rc["severidad"] == "ALERTA"] if solo_alerta else rc
            st.dataframe(
                d, use_container_width=True, hide_index=True,
                column_config={
                    "momento": st.column_config.DatetimeColumn("Momento", format="DD/MM/YYYY HH:mm"),
                    "litros_medido": st.column_config.NumberColumn("Medido (L)", format="%.0f"),
                    "litros_esperado": st.column_config.NumberColumn("Esperado libro (L)", format="%.0f"),
                    "discrepancia_litros": st.column_config.NumberColumn("Discrepancia (L)", format="%.0f"),
                })
            _dl(d, "reconciliacion_stock.csv", "dl_rc")
            st.caption("ALERTA = la discrepancia superó el umbral (300 L o 2%). Se postea un AJUSTE con su ticket para no perder trazabilidad.")
