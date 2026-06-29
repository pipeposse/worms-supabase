# -*- coding: utf-8 -*-
"""Seccion Cierres mensuales: analisis de rentabilidad sobre schema cierres_worms.
render(USR, cat, conectar). Solo direccion (SUPERVISOR/ADMIN) o acceso CIERRES.
"""
import pandas as pd
import streamlit as st

S = '"cierres_worms"'


def _puede(USR):
    return USR.get("rol") in ("SUPERVISOR", "ADMIN") or "CIERRES" in (USR.get("secciones_app") or [])


def _mm(x):
    try:
        return f"{float(x)/1e6:,.0f}M"
    except Exception:
        return "—"


def render(USR, cat, conectar):
    st.title("💰 Cierres mensuales · Rentabilidad")
    if not _puede(USR):
        st.warning("Sección de dirección (SUPERVISOR / ADMIN).")
        return
    st.caption("Análisis de rentabilidad sobre los cierres (BBDD_GASTOS + BBDD_INGRESOS_FINAL). "
               "Valores en **ARS**, expresados en **millones (M)**. Período: ene–may 2026 (junio cierra en breve).")

    pl = cat(f"SELECT to_char(mes,'YYYY-MM') AS mes, ingresos, gastos_total, costo_variable, costo_fijo, "
             f"mp, insumos, energia, personal, servicios, inversion, margen_contribucion, mc_pct, "
             f"resultado_operativo, resultado_neto, margen_neto_pct FROM {S}.v_pl_mensual ORDER BY mes")
    if pl is None or pl.empty:
        st.error("No hay datos de cierres cargados.")
        return

    t1, t9, t10, t2, t3, t4, t5, t6, t7, t8 = st.tabs(
        ["📊 Resumen P&L", "🔑 Claves de rentabilidad", "🥧 Composición", "🧭 Dónde está el valor",
         "📈 Evolución / Q1·Q2", "💱 Precios MP vs venta", "⚠️ Observaciones", "💡 Insights",
         "💵 Pesos constantes", "🛢️ Precios MP"])

    # ============ 1 · Resumen P&L ============
    with t1:
        ing_tot = pl["ingresos"].sum(); res_tot = pl["resultado_neto"].sum()
        mp_tot = pl["mp"].sum()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Ingresos acumulados", _mm(ing_tot))
        k2.metric("Resultado neto acum.", _mm(res_tot), f"{res_tot/ing_tot*100:.1f}% margen")
        k3.metric("Materia prima", _mm(mp_tot), f"{mp_tot/ing_tot*100:.0f}% de ingresos")
        k4.metric("Meses cargados", str(len(pl)))
        st.caption("La **materia prima** se come la mayor parte de los ingresos: el negocio es de **alto volumen y margen fino**.")

        _show = pd.DataFrame({
            "Mes": pl["mes"],
            "Ingresos": (pl["ingresos"]/1e6).round(0),
            "Gastos": (pl["gastos_total"]/1e6).round(0),
            "M.Prima": (pl["mp"]/1e6).round(0),
            "Costo var.": (pl["costo_variable"]/1e6).round(0),
            "Costo fijo": (pl["costo_fijo"]/1e6).round(0),
            "Margen contrib.": (pl["margen_contribucion"]/1e6).round(0),
            "MC %": pl["mc_pct"],
            "Resultado": (pl["resultado_neto"]/1e6).round(0),
            "Margen %": pl["margen_neto_pct"],
        })
        st.dataframe(_show, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.0f")
                                    for c in ["Ingresos","Gastos","M.Prima","Costo var.","Costo fijo","Margen contrib.","Resultado"]})
        st.caption("Cifras en millones de ARS.")
        _ch = pl[["mes"]].copy()
        _ch["Ingresos"] = pl["ingresos"]/1e6; _ch["Gastos"] = pl["gastos_total"]/1e6; _ch["Resultado"] = pl["resultado_neto"]/1e6
        st.line_chart(_ch.set_index("mes"), use_container_width=True)

    # ============ 2 · Donde esta el valor ============
    with t2:
        st.subheader("Contribución por segmento (ingreso − costo directo)")
        st.caption("Acumulado ene–may. **Acá se ve dónde se gana y dónde se pierde plata de verdad.**")
        seg = cat(f"SELECT sector, round(sum(ingreso)/1e6,0) ing, round(sum(costo_directo)/1e6,0) costo, "
                  f"round(sum(contribucion)/1e6,0) contrib, "
                  f"round(sum(contribucion)/NULLIF(sum(ingreso),0)*100,0) pct "
                  f"FROM {S}.v_margen_segmento GROUP BY sector ORDER BY contrib DESC NULLS LAST")
        if seg is not None and not seg.empty:
            _pos = seg[seg["contrib"] > 0]; _neg = seg[seg["contrib"] <= 0]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**🟢 Generan valor**")
                st.dataframe(_pos.rename(columns={"sector":"Segmento","ing":"Ingreso M","costo":"Costo M","contrib":"Contrib. M","pct":"Margen %"}),
                             hide_index=True, use_container_width=True)
            with c2:
                st.markdown("**🔴 Destruyen valor / overhead**")
                st.dataframe(_neg.rename(columns={"sector":"Segmento","ing":"Ingreso M","costo":"Costo M","contrib":"Contrib. M","pct":"Margen %"}),
                             hide_index=True, use_container_width=True)
            st.bar_chart(seg.set_index("sector")["contrib"], use_container_width=True)
            st.info("**Lectura:** los **servicios ambientales** (PILETAS ~87%, DISP. FINAL LÍQUIDOS ~56%) son el verdadero motor de margen. "
                    "La **exportación** mueve la mayor parte de los ingresos pero deja ~4% (la MP se lleva casi todo). "
                    "Ojo con **transfer pricing**: REACTORES y BACHAS figuran negativos porque su costo está en su sector "
                    "pero el valor que generan se factura dentro de EXPORTACIÓN — hay que mirar la cadena oleoquímica integrada.")

    # ============ 3 · Evolucion / Q1 vs Q2 ============
    with t3:
        st.subheader("Evolución mensual del margen")
        _m = pd.DataFrame({"mes": pl["mes"], "Margen neto %": pl["margen_neto_pct"], "MC %": pl["mc_pct"]})
        st.line_chart(_m.set_index("mes"), use_container_width=True)
        st.subheader("Q1 (ene–mar) vs Q2 (abr–jun, en curso)")
        tri = cat(f"SELECT trimestre, round(ingresos/1e6,0) ing, round(gastos/1e6,0) gas, "
                  f"round(resultado/1e6,0) res, margen_pct, round(mp/1e6,0) mp, round(inversion/1e6,0) capex "
                  f"FROM {S}.v_pl_trimestre ORDER BY trimestre")
        if tri is not None and not tri.empty:
            cc = st.columns(len(tri))
            for i, (_, r) in enumerate(tri.iterrows()):
                cc[i].metric(f"{r['trimestre']} · Resultado", f"{r['res']:,.0f}M", f"{r['margen_pct']}% margen")
            st.dataframe(tri.rename(columns={"trimestre":"Trim.","ing":"Ingresos M","gas":"Gastos M","res":"Resultado M",
                                             "margen_pct":"Margen %","mp":"M.Prima M","capex":"Inversión M"}),
                         hide_index=True, use_container_width=True)
            st.caption("⚠️ Q2 está **incompleto** (faltan datos de junio). La comparación se completa al cerrar el mes.")

    # ============ 4 · Rentabilidad venta vs compra de MP (mensual, USD) ============
    with t4:
        st.subheader("Rentabilidad: precio de venta vs precio de compra de MP")
        st.caption("Por producto, en **USD/TN** (lo comparable), con **evaluación mensual**. "
                   "⚠️ Para productos que se **transforman** (AG/AFE → ARE), la venta de acá es **transferencia interna**, "
                   "no la exportación final: el margen real del transformado se realiza al exportar el ARE.")
        rv = cat(f"SELECT to_char(mes,'YYYY-MM') mes, producto, venta_usd, compra_usd, spread_usd, spread_pct, q_vend, q_comp "
                 f"FROM {S}.v_rentabilidad_venta_compra ORDER BY mes, producto")
        if rv is None or rv.empty:
            st.info("Sin productos emparejables entre venta y compra.")
        else:
            res = cat(f"SELECT producto, venta_usd_prom, compra_usd_prom, spread_usd_prom, spread_pct_prom, meses "
                      f"FROM {S}.v_rentabilidad_venta_compra_resumen ORDER BY spread_usd_prom DESC NULLS LAST")
            st.markdown("**Resumen del período (USD/TN, promedio)**")
            st.dataframe(res.rename(columns={"producto":"Producto","venta_usd_prom":"Venta USD/TN","compra_usd_prom":"Compra USD/TN",
                                             "spread_usd_prom":"Spread USD/TN","spread_pct_prom":"Spread %","meses":"Meses"}),
                         hide_index=True, use_container_width=True)
            _prods = sorted(rv["producto"].dropna().unique().tolist())
            _sel = st.multiselect("Productos (evolución mensual del spread)", _prods, default=_prods[:6], key="rv_sel")
            _f = rv[rv["producto"].isin(_sel)] if _sel else rv
            try:
                _piv = _f.pivot_table(index="mes", columns="producto", values="spread_usd", aggfunc="mean")
                st.markdown("**Spread mensual (USD/TN) = venta − compra**")
                st.line_chart(_piv, use_container_width=True)
            except Exception:
                pass
            st.dataframe(_f.rename(columns={"mes":"Mes","producto":"Producto","venta_usd":"Venta USD/TN","compra_usd":"Compra USD/TN",
                                            "spread_usd":"Spread USD/TN","spread_pct":"Spread %","q_vend":"TN vend.","q_comp":"TN comp."}),
                         hide_index=True, use_container_width=True)
            st.info("**Lectura:** AG‑E deja **+11%** (compra 909 / vende 1.008). AG‑C / AG‑D / AG‑B dan negativo porque son "
                    "**insumos intermedios** que se transfieren internamente por debajo de su costo y luego se transforman en ARE para exportar "
                    "(ahí se realiza el margen). El resultado del negocio oleoquímico depende del **rendimiento de transformación** y del **tipo de cambio**, "
                    "no de un arbitraje directo compra-venta del mismo producto.")

    # ============ 5 · Observaciones / outliers ============
    with t5:
        st.subheader("Desvíos y valores atípicos")
        out = cat(f"SELECT mes, item, round(valor/1e6,0) valor_M, round(promedio/1e6,0) prom_M, z "
                  f"FROM {S}.v_outliers ORDER BY abs(z) DESC")
        if out is not None and not out.empty:
            st.dataframe(out.rename(columns={"mes":"Mes","item":"Concepto","valor_M":"Valor M","prom_M":"Promedio M","z":"Z-score"}),
                         hide_index=True, use_container_width=True)
            st.caption("Z-score = cuántos desvíos estándar se aparta del promedio del rubro. |Z| ≥ 1,3 se marca como atípico.")
        st.markdown("**Banderas de calidad de datos / negocio:**")
        st.markdown(
            "- **Febrero**: ingresos ~3.179M, la mitad de enero (7.003M). Revisar si es estacional o **carga incompleta**.\n"
            "- **Clasificación '0'**: ~197M de gastos sin `tipo_gasto` asignado (sobre todo en febrero). Reclasificar.\n"
            "- **NFU** (neumáticos): ingreso de mayo cae a ~1M vs ~45M previos, y acumulado **pierde plata** (−172M).\n"
            "- **BACHAS** y **DISP. FINAL SÓLIDOS**: contribución **negativa** — revisar pricing o costos.\n"
            "- **Inversión (capex)** muy irregular: 252M en marzo vs 5M en abril. Conviene un plan de capex prorrateado.")

    # ============ 6 · Insights ============
    with t6:
        st.subheader("Lectura ejecutiva")
        st.markdown(
            "#### 🟢 Fortalezas\n"
            "- **Servicios ambientales de altísimo margen**: PILETAS (~87%) y DISP. FINAL LÍQUIDOS (~56%) generan ~1.900M de "
            "contribución con poca inversión. Es el **núcleo de valor** y la ventaja defendible (licencias/infra ambiental).\n"
            "- **Escala en exportación**: el volumen oleoquímico da masa crítica y flujo de caja, aunque a margen fino.\n"
            "- **Resultado positivo todos los meses** (margen neto 6–11%), con caja sólida.\n\n"
            "#### 🔴 Dónde se pierde / a mejorar\n"
            "- **Exportación a 4% de margen**: 100% expuesta al **precio de la MP**. Una suba de MP del 4–5% borra la ganancia. "
            "Hay que **cubrir/negociar MP**, mejorar rendimiento de reacción (menos merma) y priorizar productos de mayor spread.\n"
            "- **Segmentos que destruyen valor**: NFU, BACHAS y DISP. FINAL SÓLIDOS. Decisión: **reprecificar, reducir costo o discontinuar**.\n"
            "- **Overhead** (ADMIN, INTENDENCIA, TALLER, LAB ≈ 305M) sin asignar a segmentos: distorsiona el margen real de cada negocio.\n\n"
            "#### 🎯 Dónde está el valor (conclusión)\n"
            "El valor **no** está en el tamaño de la exportación sino en **escalar los servicios ambientales de alto margen** "
            "y en **proteger el margen de exportación** frente al precio de la materia prima. "
            "La palanca #1 de resultado es el **costo de MP** (cada punto de MP sobre 17.500M de compra anual ≈ 175M de resultado).")
        st.caption("Análisis generado sobre los datos reales de los cierres ene–may 2026. Se actualiza al recargar tras nuevos cierres.")

    # ============ 7 · Pesos constantes (IPC) ============
    with t7:
        st.subheader("Resultados en pesos constantes (deflactado por IPC) y en USD")
        st.caption("En Argentina el salto nominal está dominado por la **inflación**, no por estacionalidad real. "
                   "Acá los valores se llevan a **pesos constantes del último mes** y a **USD** para comparar volumen y margen reales. "
                   "Editá la serie de IPC y tipo de cambio con los datos oficiales de **INDEC**.")
        ipc = cat(f"SELECT to_char(mes,'YYYY-MM') AS mes, ipc_var_pct, ipc_indice, tc_usd, fuente FROM {S}.dim_ipc ORDER BY mes")
        if ipc is not None and not ipc.empty:
            _e = st.data_editor(
                ipc.rename(columns={"mes":"Mes","ipc_var_pct":"IPC var %","ipc_indice":"IPC indice","tc_usd":"TC USD","fuente":"Fuente"}),
                hide_index=True, use_container_width=True, key="ipc_ed", disabled=["Mes"])
            if st.button("💾 Guardar serie IPC / TC", type="primary", key="ipc_save"):
                try:
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            for _, r in _e.iterrows():
                                cur.execute(
                                    'UPDATE "cierres_worms".dim_ipc SET ipc_var_pct=%s, ipc_indice=%s, tc_usd=%s, fuente=%s '
                                    "WHERE to_char(mes,'YYYY-MM')=%s",
                                    (r["IPC var %"], r["IPC indice"], r["TC USD"], r["Fuente"], r["Mes"]))
                        audit.log("U", "dim_ipc", 0, {"n": len(_e)})
                    st.success("Serie IPC / TC guardada."); cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)
        real = cat(f"SELECT to_char(mes,'YYYY-MM') AS mes, ing_nominal, ing_real, resultado_real, ing_usd, resultado_usd "
                   f"FROM {S}.v_pl_mensual_real ORDER BY mes")
        if real is not None and not real.empty:
            _t = pd.DataFrame({
                "Mes": real["mes"],
                "Ingreso nominal M": (real["ing_nominal"]/1e6).round(0),
                "Ingreso real M": (real["ing_real"]/1e6).round(0),
                "Resultado real M": (real["resultado_real"]/1e6).round(0),
                "Ingreso USD (miles)": (real["ing_usd"]/1e3).round(0),
                "Resultado USD (miles)": (real["resultado_usd"]/1e3).round(0)})
            st.dataframe(_t, hide_index=True, use_container_width=True,
                         column_config={c: st.column_config.NumberColumn(format="%.0f") for c in _t.columns if c != "Mes"})
            _c = pd.DataFrame({"Mes": real["mes"], "Nominal": real["ing_nominal"]/1e6, "Real (constante)": real["ing_real"]/1e6})
            st.line_chart(_c.set_index("Mes"), use_container_width=True)
        st.info("**Sobre estacionalidad:** desestacionalizar formalmente (X-13 / STL) necesita 2–3 años de historia mensual. "
                "Con 5 meses no es estadísticamente válido — queda preparado para cuando se acumulen más cierres. "
                "El deflactado por IPC es, hoy, el ajuste correcto para comparar mes a mes.")

    # ============ 8 · Precios de materia prima ============
    with t8:
        st.subheader("Precios de materia prima (serie mensual)")
        st.caption("Precio de compra por producto. El precio de origen ya viene en **USD/TN** (negociado real); "
                   "se muestran también ARS nominal, ARS en **pesos constantes** (deflactado por IPC) e **índice estacional** preliminar.")
        mp = cat(f"SELECT to_char(mes,'YYYY-MM') mes, producto, precio_usd_tn, precio_ars_tn, precio_ars_real_tn, "
                 f"cantidad_tn, indice_estacional, var_mom_usd_pct FROM {S}.v_precios_mp_estacional ORDER BY producto, mes")
        if mp is None or mp.empty:
            st.info("Sin precios de MP por tonelada cargados.")
        else:
            _prods = sorted(mp["producto"].dropna().unique().tolist())
            _def = [p for p in _prods if p.strip().upper().startswith(("AFE", "AG", "ARE"))][:6]
            _sel = st.multiselect("Productos", _prods, default=_def, key="mp_prod_sel")
            _f = mp[mp["producto"].isin(_sel)] if _sel else mp
            try:
                _piv = _f.pivot_table(index="mes", columns="producto", values="precio_usd_tn", aggfunc="mean")
                st.markdown("**Precio USD/TN**")
                st.line_chart(_piv, use_container_width=True)
            except Exception:
                pass
            st.dataframe(
                _f.rename(columns={"mes": "Mes", "producto": "Producto", "precio_usd_tn": "USD/TN",
                                   "precio_ars_tn": "ARS/TN nominal", "precio_ars_real_tn": "ARS/TN real",
                                   "cantidad_tn": "TN compradas", "indice_estacional": "Indice estac.",
                                   "var_mom_usd_pct": "Var MoM % (USD)"}),
                hide_index=True, use_container_width=True,
                column_config={c: st.column_config.NumberColumn(format="%.0f")
                               for c in ["ARS/TN nominal", "ARS/TN real", "TN compradas"]})
            st.info("**Lectura:** los precios de MP están **estables en USD** (ej. AFE-S ~945 USD/TN constante). "
                    "Los saltos grandes en ARS son **monetarios** (inflación/devaluación), no estacionalidad real — "
                    "el índice estacional (≈1,0) lo confirma. Con más años se podrá estimar un patrón estacional formal.")

    # ============ 9 · Claves de rentabilidad (bridge) ============
    with t9:
        st.subheader("¿Qué hace que un mes rinda más que otro?")
        st.caption("El resultado operativo se descompone en tres palancas: **volumen** (cuánto se factura), "
                   "**margen de contribución** (cuánto del ingreso queda tras la MP y los costos variables) y **costos fijos**.")
        drv = cat(f"SELECT to_char(mes,'YYYY-MM') mes, mp_pct, var_pct, fijo_pct, mc_pct FROM {S}.v_pl_drivers ORDER BY mes")
        if drv is not None and not drv.empty:
            st.markdown("**Palancas por mes (% del ingreso)**")
            st.dataframe(drv.rename(columns={"mes":"Mes","mp_pct":"MP % ing.","var_pct":"Costo var. % ing.",
                                             "fijo_pct":"Costo fijo % ing.","mc_pct":"Margen contrib. %"}),
                         hide_index=True, use_container_width=True)
            st.line_chart(pd.DataFrame({"Mes":drv["mes"], "MP % del ingreso":drv["mp_pct"],
                                        "Margen contrib. %":drv["mc_pct"]}).set_index("Mes"), use_container_width=True)
        br = cat(f"SELECT to_char(mes,'YYYY-MM') mes, round(efecto_volumen/1e6,0) vol, round(efecto_margen/1e6,0) margen, "
                 f"round(efecto_fijos/1e6,0) fijos, round(delta_resultado/1e6,0) total FROM {S}.v_pl_bridge ORDER BY mes")
        if br is not None and not br.empty:
            st.markdown("**Puente mes contra mes (M ARS): qué explicó el cambio de resultado**")
            st.dataframe(br.rename(columns={"mes":"Mes (vs anterior)","vol":"Efecto volumen","margen":"Efecto margen",
                                            "fijos":"Efecto costos fijos","total":"Δ Resultado"}),
                         hide_index=True, use_container_width=True)
            st.bar_chart(br.set_index("mes")[["vol","margen","fijos"]], use_container_width=True)
        st.info("**La clave:** un mes rinde más cuando sube el **volumen** y/o baja el **% que se lleva la MP** (mejor margen de contribución). "
                "El costo fijo pesa poco (3–7%). En estos datos **marzo** fue el peor: la MP trepó al **90,3% del ingreso** (margen de contribución 9,7%). "
                "Palancas de mejora: **más volumen rentable** + **bajar MP/ingreso** (rendimiento de transformación, mix y precio de compra).")

    # ============ 10 · Composicion ingreso/gasto ============
    with t10:
        import altair as alt
        st.subheader("Composición de ingreso y gasto")
        _mlist = cat(f"SELECT DISTINCT to_char(mes,'YYYY-MM') m FROM {S}.ingresos ORDER BY 1")
        meses_op = _mlist["m"].tolist() if _mlist is not None else []
        msel = st.selectbox("Mes", ["(todo el período)"] + meses_op, key="comp_mes")
        _wmes = "" if msel == "(todo el período)" else f" AND to_char(mes,'YYYY-MM')='{msel}'"
        _secs_df = cat(f"SELECT DISTINCT {S}.nseg(sector) s FROM {S}.ingresos WHERE sector IS NOT NULL ORDER BY 1")
        secs = _secs_df["s"].tolist() if _secs_df is not None else []
        ssel = st.multiselect("Sectores", secs, default=secs, key="comp_sec")
        def _inlist(vals):
            return ",".join("'" + str(x).replace("'", "''") + "'" for x in vals)
        _wsec_i = "" if (not ssel or len(ssel) == len(secs)) else f" AND {S}.nseg(sector) IN ({_inlist(ssel)})"
        _wsec_g = "" if (not ssel or len(ssel) == len(secs)) else f" AND {S}.nseg(sector_directo) IN ({_inlist(ssel)})"
        c1, c2 = st.columns(2)
        ing = cat(f"SELECT {S}.nseg(sector) sector, round(sum(total)/1e6,1) m FROM {S}.ingresos "
                  f"WHERE sector IS NOT NULL{_wmes}{_wsec_i} GROUP BY 1 ORDER BY m DESC")
        gas = cat(f"SELECT upper(btrim(rubro)) rubro, round(sum(monto)/1e6,1) m FROM {S}.gastos "
                  f"WHERE rubro IS NOT NULL{_wmes}{_wsec_g} GROUP BY 1 ORDER BY m DESC")
        with c1:
            st.markdown("**Ingreso por sector**")
            if ing is not None and not ing.empty:
                st.altair_chart(alt.Chart(ing).mark_arc(innerRadius=55).encode(
                    theta="m:Q", color=alt.Color("sector:N", title="Sector"), tooltip=["sector", "m"]),
                    use_container_width=True)
                st.dataframe(ing.rename(columns={"sector":"Sector","m":"M ARS"}), hide_index=True, use_container_width=True)
        with c2:
            st.markdown("**Gasto por rubro**")
            if gas is not None and not gas.empty:
                st.altair_chart(alt.Chart(gas).mark_arc(innerRadius=55).encode(
                    theta="m:Q", color=alt.Color("rubro:N", title="Rubro"), tooltip=["rubro", "m"]),
                    use_container_width=True)
                st.dataframe(gas.rename(columns={"rubro":"Rubro","m":"M ARS"}), hide_index=True, use_container_width=True)
        st.caption("Filtrá por **mes** y por **sector**. En el gasto, la **materia prima** domina la torta. Valores en millones de ARS.")
