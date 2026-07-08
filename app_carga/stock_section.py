"""Sección Stock: movimientos (libro mayor), stock por tanque en tiempo real,
real-vs-teórico por día, y conciliación. Todo descargable.
render(USR, cat) recibe el helper cacheado de app.py.
"""
import os
import pandas as pd
import streamlit as st


def _wconn():
    import psycopg2
    url = os.getenv("DATABASE_URL")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL")  # type: ignore[attr-defined]
        except Exception:
            url = None
    return psycopg2.connect(url)


def _reasignar(id_mov, id_tanque, motivo, uid):
    with _wconn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT produccion.fn_reasignar_movimiento(%s,%s,%s,%s)",
                        (int(id_mov), int(id_tanque), motivo, (int(uid) if uid else None)))
        c.commit()


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

    tp, tcov, tctrl, tdes, tsal, tmov, t1, t2, t4, t3, tcomp = st.tabs(
        ["📊 Por producto", "🌎 Cobertura total", "🎯 Control teórico", "🤖 Designación auto",
         "📤 Salidas / balance", "🧭 Movimientos y reasignación",
         "🛢️ Stock por tanque (tiempo real)", "🔁 Movimientos",
         "⚖️ Real vs teórico (por día)", "🛡️ Conciliación", "🧮 Composición del stock"])

    # ---------- Composición del stock / impacto de tickets evaluados ----------
    with tcomp:
        st.caption("¿Los **tickets evaluados por laboratorio** (pesados por portería) están **impactando el stock**? "
                   "Ticket por ticket: si generó su entrada y, si no, **por qué**.")
        _impp = cat("SELECT DISTINCT producto_lab FROM produccion.v_lab_ticket_impacto_stock WHERE producto_lab IS NOT NULL ORDER BY 1")
        _iplist = ["(todos)"] + (_impp["producto_lab"].tolist() if (_impp is not None and not _impp.empty) else [])
        cA, cB, cC = st.columns([2, 1, 1])
        _pf = cA.selectbox("Producto", _iplist, index=(_iplist.index("AFE") if "AFE" in _iplist else 0), key="comp_prodf")
        _dias = cB.selectbox("Últimos días", [3, 7, 15, 30], index=1, key="comp_dias")
        _solo_no = cC.checkbox("Solo los que NO impactan", key="comp_solo_no")

        _w = "fecha >= current_date - %s"
        _pr = [int(_dias)]
        if _pf != "(todos)":
            _w += " AND producto_lab=%s"; _pr.append(_pf)
        if _solo_no:
            _w += " AND NOT impacta_stock"

        _kpi = cat("SELECT count(*) t, count(*) FILTER (WHERE impacta_stock) si "
                   "FROM produccion.v_lab_ticket_impacto_stock WHERE " + _w, tuple(_pr))
        if _kpi is not None and not _kpi.empty:
            _t = int(_kpi.iloc[0]["t"]); _si = int(_kpi.iloc[0]["si"])
            m1, m2, m3 = st.columns(3)
            m1.metric("Tickets evaluados", _t)
            m2.metric("Impactan el stock ✅", _si)
            m3.metric("No impactan", _t - _si)

        _imp = cat("SELECT ticket, producto_lab AS producto, calidad, COALESCE(tanque_en_stock,'—') AS tanque, "
                   "kg, to_char(fecha,'DD/MM HH24:MI') AS evaluado, motivo "
                   "FROM produccion.v_lab_ticket_impacto_stock WHERE " + _w +
                   " ORDER BY impacta_stock ASC, fecha DESC LIMIT 300", tuple(_pr))
        if _imp is not None and not _imp.empty:
            st.dataframe(_imp, use_container_width=True, hide_index=True)
            _dl(_imp, "impacto_lab_stock.csv", "dl_comp_imp")
            st.caption("‘No impacta’ esperable: efluentes/fondo/insumos sin tanque de acopio. A revisar: "
                       "‘sin pesada de portería’ o ‘tanque del lab no reconocido’.")
        else:
            st.info("Sin tickets evaluados en el período.")

        with st.expander("🧮 Composición del stock físico por tanque (medición + movimientos que suman)", expanded=False):
            _prods = cat("SELECT DISTINCT producto FROM produccion.v_ingreso_lab_por_ticket WHERE producto IS NOT NULL ORDER BY 1")
            _plist = _prods["producto"].tolist() if (_prods is not None and not _prods.empty) else ["AFE-S"]
            _defi = _plist.index("AFE-S") if "AFE-S" in _plist else 0
            _prod = st.selectbox("Producto (stock físico)", _plist, index=_defi, key="comp_prod")
            _tks = cat("SELECT DISTINCT c.id_tanque, c.tanque_nombre FROM produccion.v_stock_composicion_tanque c "
                       "WHERE c.producto_tanque=%s OR c.id_tanque IN "
                       "  (SELECT id_tanque FROM produccion.v_ingreso_lab_por_ticket WHERE producto=%s) "
                       "ORDER BY c.tanque_nombre", (_prod, _prod))
            if _tks is None or _tks.empty:
                st.info("No hay tanques con ese producto.")
            else:
                _gk = 0.0; _gl = 0.0
                for _, _t in _tks.iterrows():
                    _comp = cat("SELECT tipo, to_char(ts,'DD/MM HH24:MI') AS hora, COALESCE(ticket,'') AS ticket, "
                                "producto_mov AS producto, detalle, round(kg) AS kg, round(litros) AS litros "
                                "FROM produccion.v_stock_composicion_tanque WHERE id_tanque=%s ORDER BY orden, ts",
                                (int(_t["id_tanque"]),))
                    if _comp is None or _comp.empty:
                        continue
                    _tk = float(pd.to_numeric(_comp["kg"], errors="coerce").fillna(0).sum())
                    _tl = float(pd.to_numeric(_comp["litros"], errors="coerce").fillna(0).sum())
                    _nmov = int((_comp["tipo"] == "MOVIMIENTO").sum()); _gk += _tk; _gl += _tl
                    st.markdown(f"**🛢️ {_t['tanque_nombre']}** — {_tk:,.0f} kg / {_tl:,.0f} L · {_nmov} mov. sumando")
                    st.dataframe(_comp, use_container_width=True, hide_index=True)
                st.metric(f"Total {_prod}", f"{_gk:,.0f} kg", f"{_gl:,.0f} L")

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

    # ---------- DESIGNACION AUTOMATICA: acierto vs desvio ----------
    with tdes:
        st.caption("¿La **asignación automática** de tanque acertó? Comparamos el tanque que el algoritmo "
                   "sugeriría (producto + capacidad libre + score aprendido) contra **dónde el laboratorio "
                   "realmente lo mandó**. Ventana: 60 días.")
        dz = cat("SELECT ticket, fecha, producto, kg, tanque_sugerido, tanque_real, tanque_lab_texto, "
                 "prod_tanque_real, motivo_desvio, veredicto FROM produccion.v_designacion_auto "
                 "ORDER BY fecha DESC, ticket DESC")
        if dz is None or dz.empty:
            st.info("Sin evaluaciones con tanque asignado en la ventana.")
        else:
            n_ac = int((dz["veredicto"] == "ACIERTO").sum())
            n_dv = int((dz["veredicto"] == "DESVIO").sum())
            n_sm = int((dz["veredicto"] == "SIN_MAPEAR").sum())
            n_ss = int((dz["veredicto"] == "SIN_SUGERENCIA").sum())
            base = n_ac + n_dv
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Acierto designación", f"{(100*n_ac/base if base else 0):.0f}%",
                      help=f"{n_ac} acierto / {n_dv} desvío (sobre los comparables)")
            m2.metric("Desvíos", n_dv)
            m3.metric("Sin mapear (alias)", n_sm, help="Abreviatura de tanque del lab que falta mapear")
            m4.metric("Sin sugerencia", n_ss, help="El algoritmo no encontró tanque con lugar/match")

            rs = cat("SELECT producto, evaluaciones, aciertos, desvios, sin_mapear, sin_sugerencia, pct_acierto "
                     "FROM produccion.v_designacion_resumen")
            if rs is not None and not rs.empty:
                st.markdown("**Por producto**")
                st.dataframe(rs.rename(columns={
                    "producto": "Producto", "evaluaciones": "Evals", "aciertos": "Acierto",
                    "desvios": "Desvío", "sin_mapear": "Sin mapear", "sin_sugerencia": "Sin sug.",
                    "pct_acierto": "Acierto %"}),
                    use_container_width=True, hide_index=True, column_config={
                        "Acierto %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})

            st.markdown("**🔎 Detalle por evaluación — sugerido vs real**")
            vf = st.selectbox("Veredicto", ["(todos)", "DESVIO", "ACIERTO", "SIN_SUGERENCIA", "SIN_MAPEAR"],
                              key="des_ver")
            d = dz if vf == "(todos)" else dz[dz["veredicto"] == vf]
            st.caption(f"{len(d)} evaluación(es)")
            st.dataframe(d.rename(columns={
                "ticket": "Ticket", "fecha": "Fecha", "producto": "Producto", "kg": "kg",
                "tanque_sugerido": "Sugerido", "tanque_real": "Real", "tanque_lab_texto": "Texto lab",
                "prod_tanque_real": "Prod. tanque real", "motivo_desvio": "Motivo", "veredicto": "Veredicto"}),
                use_container_width=True, hide_index=True, column_config={
                    "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "kg": st.column_config.NumberColumn(format="%.0f")})
            _dl(dz, "designacion_auto.csv", "dl_des")

            unm = dz[dz["veredicto"] == "SIN_MAPEAR"]["tanque_lab_texto"].dropna().unique().tolist()
            if unm:
                st.markdown("**🧩 Abreviaturas del lab sin mapear** (cargalas en `produccion.dim_tanque_alias` "
                            "para que cuenten en el control):")
                st.code(", ".join(sorted(map(str, unm))))
        st.caption("**ACIERTO** = fue al tanque que sugería el algoritmo · **DESVIO** = fue a otro (mirá el motivo) · "
                   "**SIN_SUGERENCIA** = el algoritmo no tenía tanque válido (sin lugar o producto sin tanque) · "
                   "**SIN_MAPEAR** = falta el alias del tanque que escribió el lab.")

    # ---------- SALIDAS / BALANCE ----------
    with tsal:
        st.caption("Todo lo que **sale** de la empresa por portería y el **balance** entró − salió = neto "
                   "por producto. Las salidas reducen el stock teórico. Ventana: 180 días.")
        bal = cat("SELECT producto, corriente, tn_entrada, tn_salida, tn_neto "
                  "FROM produccion.v_balance_producto")
        if bal is not None and not bal.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("TN entró", f"{pd.to_numeric(bal['tn_entrada'], errors='coerce').sum():,.0f}")
            m2.metric("TN salió", f"{pd.to_numeric(bal['tn_salida'], errors='coerce').sum():,.0f}")
            m3.metric("Neto (entró − salió)", f"{pd.to_numeric(bal['tn_neto'], errors='coerce').sum():,.0f}")
            st.markdown("**Balance por producto**")
            st.dataframe(bal.rename(columns={
                "producto": "Producto", "corriente": "Corriente", "tn_entrada": "TN entró",
                "tn_salida": "TN salió", "tn_neto": "TN neto"}),
                use_container_width=True, hide_index=True, column_config={
                    "TN entró": st.column_config.NumberColumn(format="%.1f"),
                    "TN salió": st.column_config.NumberColumn(format="%.1f"),
                    "TN neto": st.column_config.NumberColumn(format="%.1f")})
            _dl(bal, "balance_producto.csv", "dl_bal")
        st.markdown("**📤 Detalle de salidas**")
        sal = cat("SELECT fecha, ticket, producto, corriente, cliente, destino_final, kg "
                  "FROM produccion.v_salidas_porteria ORDER BY fecha DESC, ticket DESC LIMIT 1500")
        if sal is not None and not sal.empty:
            prods = ["(todos)"] + sorted(sal["producto"].dropna().unique().tolist())
            fp = st.selectbox("Producto", prods, key="sal_prod")
            d = sal if fp == "(todos)" else sal[sal["producto"] == fp]
            st.caption(f"{len(d)} salida(s) · {pd.to_numeric(d['kg'], errors='coerce').sum()/1000:,.0f} TN")
            st.dataframe(d.rename(columns={
                "fecha": "Fecha", "ticket": "Ticket", "producto": "Producto", "corriente": "Corriente",
                "cliente": "Cliente", "destino_final": "Destino", "kg": "kg"}),
                use_container_width=True, hide_index=True, column_config={
                    "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "kg": st.column_config.NumberColumn(format="%.0f")})
            _dl(d, "salidas_porteria.csv", "dl_sal")
        else:
            st.info("Sin salidas registradas en la ventana.")

    # ---------- MOVIMIENTOS Y REASIGNACION ----------
    with tmov:
        st.caption("Todo lo que pasó en cada tanque, qué quedó **sin asignar** y qué **entró sin registrarse**. "
                   "Reasigná en un clic si algo fue al tanque equivocado.")
        _sub = st.radio("Ver", ["📖 Libro por tanque", "🟠 Sin asignar / reasignar",
                                "🕳️ Huecos (sin movimiento)", "🔴 No explicado"],
                        horizontal=True, key="mov_sub")

        if _sub.startswith("📖"):
            _ORIG = {"lab_sync": "Laboratorio", "planificacion": "Planificación",
                     "carga_operario": "Operario", "decantacion": "Decantación",
                     "sistema": "Reconciliación", "sync_wedo": "Sensor WeDo",
                     "ajuste_manual": "Ajuste manual", "porteria_sync": "Portería"}
            _modo = st.radio("Agrupar por", ["🛢️ Por tanque", "🧪 Por producto"],
                             horizontal=True, key="mov_modo")
            _con_aj = st.checkbox("Incluir ajustes (movimiento no explicado por la reconciliación)",
                                  value=False, key="mov_aj")
            _df = None
            _grpcol = "producto"
            _sel = None
            if _modo.startswith("🛢️"):
                _tk = cat("SELECT DISTINCT id_tanque, tanque FROM produccion.v_tanque_libro ORDER BY tanque")
                if _tk is not None and not _tk.empty:
                    _opt = _tk["tanque"].tolist()
                    _sel = st.selectbox("Tanque", _opt, key="mov_libro_tk")
                    _idt = int(_tk.iloc[_opt.index(_sel)]["id_tanque"])
                    _df = cat("SELECT momento, tipo_movimiento, producto, tanque, kg_neto, litros_neto, "
                              "ticket_porteria, ticket_lab, origen FROM produccion.v_tanque_libro "
                              "WHERE id_tanque=%s ORDER BY momento DESC", (_idt,))
                    _grpcol = "producto"
            else:
                _pr = cat("SELECT DISTINCT producto FROM produccion.v_tanque_libro "
                          "WHERE producto IS NOT NULL ORDER BY producto")
                if _pr is not None and not _pr.empty:
                    _opt = _pr["producto"].tolist()
                    _sel = st.selectbox("Producto", _opt, key="mov_libro_pr")
                    _df = cat("SELECT momento, tipo_movimiento, producto, tanque, kg_neto, litros_neto, "
                              "ticket_porteria, ticket_lab, origen FROM produccion.v_tanque_libro "
                              "WHERE producto=%s ORDER BY momento DESC", (_sel,))
                    _grpcol = "tanque"

            if _df is None or _df.empty:
                st.info("Sin movimientos registrados todavía.")
            else:
                d = _df.copy()
                d["kg_neto"] = pd.to_numeric(d["kg_neto"], errors="coerce").fillna(0)
                d["litros_neto"] = pd.to_numeric(d["litros_neto"], errors="coerce").fillna(0)
                if not _con_aj:
                    d = d[d["tipo_movimiento"] != "AJUSTE"]
                if d.empty:
                    st.info("No hay entradas ni salidas registradas (probá tildar «Incluir ajustes»).")
                else:
                    _ent = d.loc[d["tipo_movimiento"] == "ENTRADA", "kg_neto"].sum() / 1000.0
                    _sal = -d.loc[d["tipo_movimiento"] == "SALIDA", "kg_neto"].sum() / 1000.0
                    _sdo = d["kg_neto"].sum() / 1000.0
                    k1, k2, k3 = st.columns(3)
                    k1.metric("🟢 Entró", f"{_ent:,.1f} TN")
                    k2.metric("🔴 Salió", f"{_sal:,.1f} TN")
                    k3.metric("Saldo del período", f"{_sdo:,.1f} TN")
                    d["Movimiento"] = d["tipo_movimiento"].map(
                        {"ENTRADA": "🟢 Entró", "SALIDA": "🔴 Salió", "AJUSTE": "🟡 Ajuste"}).fillna(d["tipo_movimiento"])
                    d["Cantidad"] = d.apply(
                        lambda r: (f"{abs(r['kg_neto'])/1000.0:,.1f} TN" if r["tipo_movimiento"] != "AJUSTE"
                                   else f"{r['litros_neto']:,.0f} L"), axis=1)
                    d["Ticket"] = d["ticket_porteria"].fillna(d["ticket_lab"])
                    d["Origen"] = d["origen"].map(_ORIG).fillna(d["origen"])
                    _hdr = "Tanque" if _grpcol == "tanque" else "Producto"
                    st.dataframe(
                        d[["momento", "Movimiento", _grpcol, "Cantidad", "Ticket", "Origen"]].rename(
                            columns={"momento": "Fecha", _grpcol: _hdr}),
                        use_container_width=True, hide_index=True,
                        column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})
                    _dl(d, f"movimientos_{_sel}.csv", "dl_libro")

        elif _sub.startswith("🟠"):
            sa = cat("SELECT id_mov_stock, momento, tipo_movimiento, producto, kg, litros, "
                     "ticket_porteria, ticket_lab, origen, estado_mov FROM produccion.v_mov_sin_asignar")
            if sa is None or sa.empty:
                st.success("✅ No hay movimientos sin asignar.")
            else:
                st.caption(f"{len(sa)} movimiento(s) sin tanque asignado")
                st.dataframe(sa.rename(columns={
                    "id_mov_stock": "# Mov", "momento": "Fecha", "tipo_movimiento": "Tipo",
                    "producto": "Producto", "kg": "kg", "litros": "L", "ticket_porteria": "Tk portería",
                    "ticket_lab": "Tk lab", "origen": "Origen", "estado_mov": "Estado"}),
                    use_container_width=True, hide_index=True, column_config={
                        "Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})
                st.markdown("**↪️ Reasignar un movimiento a su tanque**")
                _ids = sa["id_mov_stock"].tolist()
                r1, r2, r3 = st.columns([1, 2, 2])
                _mid = r1.selectbox("# Movimiento", _ids, key="rea_mid")
                _tks = cat("SELECT id_tanque, codigo, nombre FROM produccion.dim_tanque "
                           "WHERE COALESCE(activo,true) ORDER BY codigo")
                _tkl = _tks.apply(lambda x: f"{x['codigo']} · {x['nombre']}", axis=1).tolist()
                _tsel = r2.selectbox("Tanque destino", _tkl, key="rea_tk")
                _tid = int(_tks.iloc[_tkl.index(_tsel)]["id_tanque"])
                _mot = r3.text_input("Motivo", key="rea_mot")
                if st.button("↪️ Reasignar", type="primary", key="rea_btn"):
                    try:
                        _reasignar(_mid, _tid, _mot or None, USR.get("id_usuario"))
                        st.toast("Movimiento reasignado", icon="✅")
                        cat.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo reasignar: {e}")

        elif _sub.startswith("🕳️"):
            hk = cat("SELECT fecha, ticket, producto, corriente, cliente, kg, tiene_tanque_teorico "
                     "FROM produccion.v_gaps_movimiento LIMIT 1000")
            if hk is None or hk.empty:
                st.success("✅ No hay entradas sin movimiento.")
            else:
                st.warning(f"{len(hk)} entrada(s) de portería sin movimiento de stock "
                           "(no llegaron a un tanque en el sistema).")
                st.dataframe(hk.rename(columns={
                    "fecha": "Fecha", "ticket": "Ticket", "producto": "Producto", "corriente": "Corriente",
                    "cliente": "Proveedor", "kg": "kg", "tiene_tanque_teorico": "Hay tanque p/producto"}),
                    use_container_width=True, hide_index=True, column_config={
                        "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                        "kg": st.column_config.NumberColumn(format="%.0f")})
                st.caption("Estos huecos se cierran en Fase 2 (portería genera el movimiento sola). "
                           "Por ahora es la lista de lo que se está escapando.")

        else:
            ne = cat("SELECT tanque, sector, producto, ajustes, litros_no_explicados, movs_explicados, ultimo_ajuste "
                     "FROM produccion.v_tanque_no_explicado")
            if ne is None or ne.empty:
                st.success("✅ No hay movimiento sin explicar.")
            else:
                st.caption("Los **ajustes** son cambios físicos del tanque que producción NO justifica: "
                           "movimiento no explicado. Ordenado por magnitud (dónde se pierde el control).")
                st.dataframe(ne.rename(columns={
                    "tanque": "Tanque", "sector": "Sector", "producto": "Producto", "ajustes": "# Ajustes",
                    "litros_no_explicados": "L no explicados", "movs_explicados": "Movs explicados",
                    "ultimo_ajuste": "Último ajuste"}),
                    use_container_width=True, hide_index=True, column_config={
                        "L no explicados": st.column_config.NumberColumn(format="%.0f"),
                        "Último ajuste": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})
                _dl(ne, "no_explicado.csv", "dl_ne")

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
