"""Sección Stock: movimientos (libro mayor), stock por tanque en tiempo real,
real-vs-teórico por día, y conciliación. Todo descargable.
render(USR, cat) recibe el helper cacheado de app.py.
"""
import pandas as pd
import streamlit as st


def _dl(df, name, key):
    st.download_button("⬇️ Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=name, mime="text/csv", key=key, use_container_width=True)


def render(USR, cat):
    st.title("📦 Stock")
    with st.expander("¿Cómo se calcula el stock teórico?", expanded=False):
        st.markdown(
            "**Stock estimado = última medición física + Σ movimientos ejecutados desde esa medición.**\n\n"
            "- La medición física (sensor WeDo cada ~20 min o carga manual 1/día) es la **verdad**, pero discreta.\n"
            "- Cada movimiento confirmado (un ticket `MS-xxxxxxxx`) actualiza el stock al instante.\n"
            "- Así, incluso un tanque medido 1 vez al día queda **vivo**. La **confianza** indica qué tan fresco es el dato.\n"
            "- **Real vs teórico**: comparamos la variación física medida contra lo que movió producción.")

    tp, tcov, tctrl, t1, t2, t4, t3 = st.tabs(
        ["📊 Por producto", "🌎 Cobertura total", "🎯 Control teórico",
         "🛢️ Stock por tanque (tiempo real)", "🔁 Movimientos",
         "⚖️ Real vs teórico (por día)", "🛡️ Conciliación"])

    # ---------- 0 · Stock por producto ----------
    with tp:
        st.caption("Cuánto hay de cada producto, cuánta **capacidad de acopio aperturada** (tanques asignados) "
                   "y cuánto **queda disponible** — total y abierto por tanque.")
        pp = cat("SELECT produccion.fn_prod_label(producto_principal) AS producto, count(*) tanques, "
                 "SUM(COALESCE(litros_actual,0)) litros, SUM(COALESCE(kg_actual,0)) kg, "
                 "SUM(COALESCE(capacidad_litros,0)) capacidad "
                 "FROM produccion.vw_tanque_panel WHERE activo AND producto_principal IS NOT NULL "
                 "GROUP BY produccion.fn_prod_label(producto_principal) ORDER BY litros DESC NULLS LAST")
        if pp is None or pp.empty:
            st.info("Sin datos de stock por producto.")
        else:
            pp = pp.copy()
            _lt = pd.to_numeric(pp["litros"], errors="coerce").fillna(0)
            _cap = pd.to_numeric(pp["capacidad"], errors="coerce").fillna(0)
            pp["disponible"] = (_cap - _lt).clip(lower=0)
            pp["ocupacion"] = (_lt / _cap.replace(0, pd.NA) * 100).fillna(0)
            t_lt = float(_lt.sum()); t_cap = float(_cap.sum()); t_disp = float(pp["disponible"].sum())
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Stock total (L)", f"{t_lt:,.0f}")
            m2.metric("Capacidad aperturada (L)", f"{t_cap:,.0f}")
            m3.metric("Disponible (L)", f"{t_disp:,.0f}")
            m4.metric("Ocupación total", f"{(t_lt/t_cap*100 if t_cap else 0):.0f}%")
            _disp = pp.rename(columns={"producto": "Producto", "tanques": "Tanques", "litros": "Stock (L)",
                                       "kg": "Stock (kg)", "capacidad": "Capacidad (L)",
                                       "disponible": "Disponible (L)", "ocupacion": "Ocupación %"})
            st.dataframe(_disp[["Producto", "Tanques", "Stock (L)", "Capacidad (L)", "Disponible (L)", "Ocupación %"]],
                         use_container_width=True, hide_index=True, column_config={
                "Stock (L)": st.column_config.NumberColumn(format="%.0f"),
                "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
                "Disponible (L)": st.column_config.NumberColumn(format="%.0f"),
                "Ocupación %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})
            _dl(_disp, "stock_por_producto.csv", "dl_pp")
            st.markdown("**🛢️ Aperturado por tanque**")
            _psel = st.selectbox("Producto", pp["producto"].tolist(), key="stk_pp_sel")
            tq = cat("SELECT nombre AS \"Tanque\", codigo AS \"Código\", sector AS \"Sector\", "
                     "COALESCE(litros_actual,0) AS \"Stock (L)\", COALESCE(capacidad_litros,0) AS \"Capacidad (L)\", "
                     "GREATEST(COALESCE(capacidad_litros,0)-COALESCE(litros_actual,0),0) AS \"Disponible (L)\", "
                     "COALESCE(nivel_pct_actual,0) AS \"Ocupación %%\" "
                     "FROM produccion.vw_tanque_panel WHERE activo AND produccion.fn_prod_label(producto_principal)=%s "
                     "ORDER BY litros_actual DESC NULLS LAST", (_psel,))
            if tq is not None and not tq.empty:
                st.dataframe(tq, use_container_width=True, hide_index=True, column_config={
                    "Stock (L)": st.column_config.NumberColumn(format="%.0f"),
                    "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
                    "Disponible (L)": st.column_config.NumberColumn(format="%.0f"),
                    "Ocupación %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})

    # ---------- COBERTURA TOTAL ----------
    with tcov:
        st.caption("Todo lo que hay en planta: **tanques reales** (rótulo oficial del diccionario) más "
                   "**tanques provisorios** para lo que entró sin destino asignado. Líquidos → PILETAS.")
        sv = cat("SELECT tipo, codigo, nombre, sector, producto, corriente, litros, tn, nivel_pct, es_provisorio "
                 "FROM reporting.v_stock_total ORDER BY es_provisorio DESC, tn DESC NULLS LAST")
        if sv is None or sv.empty:
            st.info("Sin datos de cobertura.")
        else:
            prov = sv[sv["es_provisorio"] == True]
            real = sv[sv["es_provisorio"] == False]
            c1, c2, c3 = st.columns(3)
            c1.metric("Tanques reales", len(real))
            c2.metric("Provisorios (sin destino)", len(prov))
            c3.metric("TN sin destino", f"{pd.to_numeric(prov['tn'], errors='coerce').sum():,.0f}")
            if not prov.empty:
                st.markdown("**🟠 Provisorios — entró a planta sin tanque asignado**")
                st.dataframe(prov[["codigo", "producto", "corriente", "tn"]].rename(columns={
                    "codigo": "Bucket", "producto": "Producto", "corriente": "Corriente", "tn": "TN"}),
                    use_container_width=True, hide_index=True,
                    column_config={"TN": st.column_config.NumberColumn(format="%.1f")})
            st.markdown("**🟢 Tanques reales**")
            st.dataframe(real[["codigo", "nombre", "sector", "producto", "corriente", "litros", "tn", "nivel_pct"]].rename(columns={
                "codigo": "Código", "nombre": "Tanque", "sector": "Sector", "producto": "Producto",
                "corriente": "Corriente", "litros": "Stock (L)", "tn": "TN", "nivel_pct": "Nivel %"}),
                use_container_width=True, hide_index=True, column_config={
                    "Stock (L)": st.column_config.NumberColumn(format="%.0f"),
                    "TN": st.column_config.NumberColumn(format="%.1f"),
                    "Nivel %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})
            _dl(sv, "stock_total.csv", "dl_cov")

    # ---------- CONTROL TEORICO vs REAL ----------
    with tctrl:
        st.caption("¿Todo lo que entra por portería llega a destino? Comparamos el **destino teórico** "
                   "(tanque del producto declarado) contra **dónde fue realmente**. Ventana: 180 días.")
        ct = cat("SELECT producto, corriente, tickets, tn_ingresado, tn_ok, tn_desviado, tn_sin_destino, pct_control "
                 "FROM produccion.v_control_teorico_producto")
        if ct is not None and not ct.empty:
            _in = pd.to_numeric(ct["tn_ingresado"], errors="coerce").sum()
            _ok = pd.to_numeric(ct["tn_ok"], errors="coerce").sum()
            _sd = pd.to_numeric(ct["tn_sin_destino"], errors="coerce").sum()
            _dv = pd.to_numeric(ct["tn_desviado"], errors="coerce").sum()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("TN ingresadas", f"{_in:,.0f}")
            m2.metric("Control teórico", f"{(100*_ok/_in if _in else 0):.0f}%",
                      help="% de TN que llegó al tanque correcto")
            m3.metric("Desviadas", f"{_dv:,.0f} TN")
            m4.metric("Sin destino", f"{_sd:,.0f} TN")
            st.dataframe(ct.rename(columns={
                "producto": "Producto", "corriente": "Corriente", "tickets": "Tickets",
                "tn_ingresado": "TN in", "tn_ok": "TN OK", "tn_desviado": "TN desviado",
                "tn_sin_destino": "TN sin destino", "pct_control": "Control %"}),
                use_container_width=True, hide_index=True, column_config={
                    "TN in": st.column_config.NumberColumn(format="%.1f"),
                    "TN OK": st.column_config.NumberColumn(format="%.1f"),
                    "TN desviado": st.column_config.NumberColumn(format="%.1f"),
                    "TN sin destino": st.column_config.NumberColumn(format="%.1f"),
                    "Control %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})
            _dl(ct, "control_teorico_producto.csv", "dl_ct")
        st.markdown("**🔎 Detalle por ticket — teórico vs real**")
        ef = st.selectbox("Estado", ["(todos)", "SIN_DESTINO", "DESVIADO", "OK"], key="ctrl_estado")
        tr = cat("SELECT fecha, ticket, producto, cliente, kg, estado, tanque_real, prod_tanque_real, "
                 "tiene_tanque_teorico FROM produccion.v_trazabilidad_destino "
                 "ORDER BY fecha DESC, ticket DESC LIMIT 1500")
        if tr is not None and not tr.empty:
            d = tr if ef == "(todos)" else tr[tr["estado"] == ef]
            st.caption(f"{len(d)} ticket(s)")
            st.dataframe(d.rename(columns={
                "fecha": "Fecha", "ticket": "Ticket", "producto": "Producto", "cliente": "Proveedor",
                "kg": "kg", "estado": "Estado", "tanque_real": "Tanque real",
                "prod_tanque_real": "Producto del tanque", "tiene_tanque_teorico": "Tiene tanque teórico"}),
                use_container_width=True, hide_index=True, column_config={
                    "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "kg": st.column_config.NumberColumn(format="%.0f")})
            _dl(d, "trazabilidad_destino.csv", "dl_tr")
        st.caption("**OK** = llegó al tanque de su producto · **DESVIADO** = entró a un tanque de otro producto · "
                   "**SIN_DESTINO** = no se registró movimiento de stock para ese ticket.")

    # ---------- 1 · Stock por tanque ----------
    with t1:
        df = cat("SELECT st.codigo, st.sector, COALESCE(t.producto_principal_txt,'') AS producto, "
                 "st.fuente_medicion, st.antiguedad_min, st.cadencia_sensor_min, st.litros_medido, "
                 "st.delta_litros_ejecutado, st.litros_estimado, st.confianza, "
                 "st.movs_desde_medicion, st.movs_pendientes "
                 "FROM reporting.v_tanque_stock_estimado st "
                 "LEFT JOIN produccion.dim_tanque t ON t.id_tanque=st.id_tanque "
                 "ORDER BY st.litros_estimado DESC NULLS LAST")
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
        st.dataframe(d, use_container_width=True, hide_index=True, column_config={
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
        fest = f1.selectbox("Estado", ["(todos)"] + sorted(mv["estado_mov"].dropna().unique().tolist()), key="mv_est")
        frol = f2.selectbox("Rol", ["(todos)"] + sorted(mv["rol"].dropna().unique().tolist()), key="mv_rol")
        ffue = f3.selectbox("Fuente", ["(todas)"] + sorted(mv["fuente"].dropna().unique().tolist()), key="mv_fue")
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
        st.dataframe(d, use_container_width=True, hide_index=True, column_config={
            "momento": st.column_config.DatetimeColumn("Momento", format="DD/MM/YYYY HH:mm"),
            "kg": st.column_config.NumberColumn(format="%.0f"),
            "litros": st.column_config.NumberColumn(format="%.0f"),
            "kg_neto": st.column_config.NumberColumn("kg neto", format="%.0f"),
            "litros_neto": st.column_config.NumberColumn("L neto", format="%.0f"),
        })
        _dl(d, "movimientos_stock.csv", "dl_mv")
        st.caption("PLANIFICADO = creado por dirección · EJECUTADO = confirmado por el operario (afecta stock).")

    # ---------- 4 · Real vs teórico por día ----------
    with t4:
        rv = cat("SELECT fecha, tanque, litros_medido_dia, litros_teorico_dia, "
                 "diferencia_litros, movimientos_produccion FROM reporting.v_tanque_real_vs_teorico "
                 "ORDER BY fecha DESC, tanque")
        g1, g2 = st.columns(2)
        tanques = ["(todos)"] + sorted(rv["tanque"].dropna().unique().tolist())
        ftq = g1.selectbox("Tanque", tanques, key="rv_tq")
        solo_dif = g2.toggle("Sólo con diferencia significativa (>100 L)", value=True, key="rv_dif")
        d = rv.copy()
        if ftq != "(todos)":
            d = d[d["tanque"] == ftq]
        if solo_dif:
            d = d[pd.to_numeric(d["diferencia_litros"], errors="coerce").abs() > 100]
        st.dataframe(d, use_container_width=True, hide_index=True, column_config={
            "fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"),
            "litros_medido_dia": st.column_config.NumberColumn("Medido físico (L/día)", format="%.0f"),
            "litros_teorico_dia": st.column_config.NumberColumn("Teórico producción (L/día)", format="%.0f"),
            "diferencia_litros": st.column_config.NumberColumn("Diferencia (L)", format="%.0f"),
            "movimientos_produccion": st.column_config.NumberColumn("# mov. prod.", format="%.0f"),
        })
        _dl(d, "real_vs_teorico.csv", "dl_rv")
        st.caption("**Medido** = variación física real del tanque (sensor/manual). **Teórico** = lo que movió producción ese día. "
                   "**Diferencia** = lo no explicado por producción (camiones a tanque, ventas, fugas).")

    # ---------- 3 · Conciliación ----------
    with t3:
        rc = cat("SELECT momento, tanque, litros_medido, litros_esperado, discrepancia_litros, "
                 "severidad, ajuste_ticket FROM reporting.v_reconciliacion_stock ORDER BY momento DESC")
        if rc.empty:
            st.info("Todavía no hay conciliaciones registradas (el job corre cada 30 min).")
        else:
            a1, a2 = st.columns(2)
            a1.metric("Lecturas conciliadas", len(rc))
            a2.metric("Alertas", int((rc["severidad"] == "ALERTA").sum()))
            solo_alerta = st.toggle("Sólo alertas", value=False, key="rc_alerta")
            d = rc[rc["severidad"] == "ALERTA"] if solo_alerta else rc
            st.dataframe(d, use_container_width=True, hide_index=True, column_config={
                "momento": st.column_config.DatetimeColumn("Momento", format="DD/MM/YYYY HH:mm"),
                "litros_medido": st.column_config.NumberColumn("Medido (L)", format="%.0f"),
                "litros_esperado": st.column_config.NumberColumn("Esperado libro (L)", format="%.0f"),
                "discrepancia_litros": st.column_config.NumberColumn("Discrepancia (L)", format="%.0f"),
            })
            _dl(d, "conciliacion_stock.csv", "dl_rc")
            st.caption("ALERTA = discrepancia sobre el umbral (300 L o 2%). Se postea un AJUSTE con su ticket.")
