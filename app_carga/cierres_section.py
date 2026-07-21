# -*- coding: utf-8 -*-
"""Seccion Cierres mensuales: analisis de rentabilidad sobre schema cierres_worms.
render(USR, cat, conectar). Solo direccion (SUPERVISOR/ADMIN) o acceso CIERRES.
"""
import pandas as pd
import streamlit as st
try:
    import altair as alt
except Exception:
    alt = None

S = '"cierres_worms"'
SC = "cierres_calzim"
CC_PRI="#4f46e5"; CC_OK="#16a34a"; CC_BAD="#dc2626"; CC_AMB="#d97706"; CC_MUT="#94a3b8"


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
    _emp = st.radio("Empresa · reporte",
                    ["🏭 WORMS", "🐷 CALZIM · Facturas", "🐷 CALZIM · Producción"],
                    horizontal=True, key="cierres_empresa")
    if _emp == "🐷 CALZIM · Facturas":
        _render_calzim_facturas(cat); return
    if _emp == "🐷 CALZIM · Producción":
        _render_calzim_produccion(cat); return
    st.caption("Análisis de rentabilidad sobre los cierres (BBDD_GASTOS + BBDD_INGRESOS_FINAL). "
               "Valores en **ARS**, expresados en **millones (M)**. Período: ene–jun 2026.")

    pl = cat(f"SELECT to_char(mes,'YYYY-MM') AS mes, ingresos, gastos_total, costo_variable, costo_fijo, "
             f"mp, insumos, energia, personal, servicios, inversion, margen_contribucion, mc_pct, "
             f"resultado_operativo, resultado_neto, margen_neto_pct FROM {S}.v_pl_mensual ORDER BY mes")
    if pl is None or pl.empty:
        st.error("No hay datos de cierres cargados.")
        return

    t1, t9, t10, t2, t3, t4, t5, t6, t7, t8, t11 = st.tabs(
        ["📊 Resumen P&L", "🔑 Claves de rentabilidad", "🥧 Composición", "🧭 Dónde está el valor",
         "📈 Evolución / Q1·Q2", "💱 Precios MP vs venta", "⚠️ Observaciones", "💡 Insights",
         "💵 Pesos constantes", "🛢️ Precios MP", "📂 Datos originales"])

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
        st.caption("Acumulado del período cargado. **Acá se ve dónde se gana y dónde se pierde plata de verdad.**")
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
        st.caption("**De dónde sale:** *Venta USD/TN* = promedio del **PRECIO** (filas en USD) de la hoja **BBDD_INGRESOS_FINAL**; "
                   "*Compra USD/TN* = promedio del **PRECIO** de **BBDD_GASTOS** (rubro M.PRIMAS, por tonelada); *Spread* = venta − compra. "
                   "Mirá los registros crudos en la pestaña **📂 Datos originales**. "
                   "⚠️ Para productos que se **transforman** (AG/AFE → ARE), la venta de acá es **transferencia interna**, "
                   "no la exportación final: el margen real se realiza al exportar el ARE.")
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
        st.subheader("🎯 Insights accionables")
        st.caption("Calculado sobre los datos reales. Cada palanca muestra su **impacto en $** y la **acción** concreta. "
                   "El simulador deja probar decisiones antes de tomarlas.")
        _n = len(pl)
        ing_tot = float(pl["ingresos"].sum()); mp_tot = float(pl["mp"].sum())
        var_tot = float(pl["costo_variable"].sum()); fijo_tot = float(pl["costo_fijo"].sum())
        res_tot = float(pl["resultado_neto"].sum())
        otros_var = max(var_tot - mp_tot, 0.0)
        base_op = ing_tot - var_tot - fijo_tot
        _anu = 12.0 / max(_n, 1)
        seg = cat(f"SELECT sector, sum(ingreso) ing, sum(costo_directo) costo, sum(contribucion) contrib, "
                  f"round(sum(contribucion)/NULLIF(sum(ingreso),0)*100,0) pct FROM {S}.v_margen_segmento GROUP BY sector")
        _over = {"ADMINISTRACION", "INTENDENCIA", "TALLER", "LABORATORIO"}
        _transfer = {"REACTORES"}
        sane = esc = pd.DataFrame()
        if seg is not None and not seg.empty:
            sane = seg[(seg["ing"] > 0) & (seg["contrib"] < 0) & (~seg["sector"].isin(_over | _transfer))].copy()
            esc = seg[(seg["contrib"] > 0) & (seg["pct"] >= 40)].copy()
        recup = float(-sane["contrib"].sum()) if not sane.empty else 0.0
        contrib_alto = float(esc["contrib"].sum()) if not esc.empty else 0.0
        _d = pl.copy()
        _d["mp_pct"] = _d["mp"] / _d["ingresos"] * 100
        worst = _d.loc[_d["margen_neto_pct"].astype(float).idxmin()]
        target_mp = float(_d["mp_pct"].min())
        gap_worst = (float(worst["mp_pct"]) - target_mp) / 100.0 * float(worst["ingresos"])

        st.markdown("#### Las 3 palancas de mayor impacto")
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.markdown("**1 · Costo de materia prima** 🥇")
                st.metric("Impacto de bajar 1% la MP", f"+{mp_tot*0.01/1e6:,.0f} M", f"≈ {mp_tot*0.01/max(res_tot,1)*100:,.0f}% del resultado")
                st.caption(f"La MP es {mp_tot/ing_tot*100:,.0f}% del ingreso. Negociar/cubrir compra y mejorar **rendimiento de transformación** "
                           "(menos merma kg). Cada punto de MP mueve casi 1:1 el resultado.")
        with c2:
            with st.container(border=True):
                st.markdown("**2 · Sanear segmentos negativos** 🔴")
                st.metric("Valor que se está perdiendo", f"{recup/1e6:,.0f} M", f"en {len(sane)} segmentos · {recup*_anu/1e6:,.0f} M/año")
                st.caption("Reprecificar, bajar costo o discontinuar: " + (", ".join(sane["sector"].tolist()) if not sane.empty else "—") + ".")
        with c3:
            with st.container(border=True):
                st.markdown("**3 · Escalar servicios de alto margen** 🟢")
                st.metric("Upside por +10% de volumen", f"+{contrib_alto*0.10/1e6:,.0f} M", f"base {contrib_alto/1e6:,.0f} M de contribución")
                st.caption("Núcleo de valor (margen ≥40%): " + (", ".join(esc["sector"].tolist()) if not esc.empty else "—") + ". Poca inversión, alto retorno.")

        st.divider()
        st.markdown("#### 🧮 Simulador de sensibilidad")
        st.caption("Proyección sobre el período cargado (manteniendo precios de venta). Probá una decisión y mirá el resultado.")
        sc1, sc2 = st.columns(2)
        dmp = sc1.slider("Variación del precio de compra de MP (%)", -10.0, 10.0, 0.0, 0.5, key="sim_mp")
        dvol = sc2.slider("Variación de volumen de ventas (%)", -20.0, 20.0, 0.0, 1.0, key="sim_vol")
        nuevo_ing = ing_tot * (1 + dvol/100)
        nuevo_mp = mp_tot * (1 + dvol/100) * (1 + dmp/100)
        nuevo_res = nuevo_ing - nuevo_mp - otros_var * (1 + dvol/100) - fijo_tot
        m1, m2, m3 = st.columns(3)
        m1.metric("Resultado base (período)", f"{base_op/1e6:,.0f} M")
        m2.metric("Resultado proyectado", f"{nuevo_res/1e6:,.0f} M", f"{(nuevo_res-base_op)/1e6:+,.0f} M")
        m3.metric("Margen proyectado", f"{(nuevo_res/nuevo_ing*100 if nuevo_ing else 0):.1f}%",
                  f"{(nuevo_res/nuevo_ing*100 - base_op/ing_tot*100):+.1f} pts")
        if nuevo_res < 0:
            st.error("⚠️ Con esos parámetros el período da **pérdida**. La empresa no resiste una suba grande de MP sin compensar con volumen o precio.")
        elif dmp != 0 or dvol != 0:
            st.success(f"Con MP {dmp:+.1f}% y volumen {dvol:+.1f}%, el resultado del período pasa a **{nuevo_res/1e6:,.0f} M**.")

        st.divider()
        st.markdown("#### 🔎 Diagnóstico del mes más flojo")
        st.info(f"El peor mes fue **{worst['mes']}** (margen {float(worst['margen_neto_pct']):.1f}%): la MP se llevó "
                f"**{float(worst['mp_pct']):.0f}%** del ingreso, contra **{target_mp:.0f}%** del mejor mes. "
                f"Si ese mes hubiera comprado MP al mejor ratio, el resultado habría sido ~**+{gap_worst/1e6:,.0f} M** mejor. "
                "**Acción:** disciplina de procurement y monitoreo del ratio MP/ingreso mensual (alerta si supera el target).")

        st.markdown("#### 📋 Plan priorizado")
        _plan = pd.DataFrame({
            "Prioridad": ["P0", "P0", "P1", "P1", "P2"],
            "Acción": [
                "Bajar costo de MP (negociación + cobertura + rendimiento)",
                "Sanear segmentos negativos (" + (", ".join(sane["sector"].tolist()) if not sane.empty else "—") + ")",
                "Escalar PILETAS y disposición de líquidos (alto margen)",
                "Asignar overhead a segmentos (margen fully-loaded real)",
                "Reclasificar gastos sin tipo y prorratear capex"],
            "Impacto estimado (M/año)": [
                round(mp_tot*0.01*_anu/1e6), round(recup*_anu/1e6),
                round(contrib_alto*0.10*_anu/1e6), 0, 0]})
        st.dataframe(_plan, hide_index=True, use_container_width=True)
        st.caption("Impactos anualizados a partir de los " + str(_n) + " meses cargados. Se recalcula al sumar nuevos cierres.")

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

    # ============ 11 · Datos originales ============
    with t11:
        st.subheader("Datos originales (trazabilidad)")
        st.caption("Los **registros tal cual** salen de los cierres mensuales: hoja **BBDD_INGRESOS_FINAL** (ingresos) y "
                   "**BBDD_GASTOS** (gastos). Todo el análisis de las otras pestañas se calcula a partir de estas filas.")
        _tbl = st.radio("Tabla", ["Ingresos (BBDD_INGRESOS_FINAL)", "Gastos (BBDD_GASTOS)"], horizontal=True, key="orig_tbl")
        _mses = cat(f"SELECT DISTINCT to_char(mes,'YYYY-MM') m FROM {S}.gastos ORDER BY 1")
        _meses = _mses["m"].tolist() if _mses is not None else []
        cmes, cq = st.columns([1, 2])
        _msel = cmes.selectbox("Mes", ["(todos)"] + _meses, key="orig_mes")
        _q = cq.text_input("Buscar (producto / descripción / cliente / rubro…)", key="orig_q")
        _wm = "" if _msel == "(todos)" else f" WHERE to_char(mes,'YYYY-MM')='{_msel}'"
        if _tbl.startswith("Ingresos"):
            df = cat(f"SELECT to_char(mes,'YYYY-MM') AS mes, fecha, canal, area, sector, producto, cliente, descripcion, "
                     f"um, cantidad, precio, moneda, subtotal, tc, iva, total, fuente, origen FROM {S}.ingresos{_wm} "
                     f"ORDER BY mes, total DESC NULLS LAST")
        else:
            df = cat(f"SELECT to_char(mes,'YYYY-MM') AS mes, fecha, empresa, num, descripcion, precio, cantidad, um, monto, "
                     f"concepto, tipo_gasto_i, tipo_gasto_ii, rubro, sector_cco, centro_costos, subrubro, sector_directo "
                     f"FROM {S}.gastos{_wm} ORDER BY mes, monto DESC NULLS LAST")
        if df is not None and not df.empty:
            if _q.strip():
                _ql = _q.strip().lower()
                df = df[df.astype(str).apply(lambda r: _ql in " ".join(r.values).lower(), axis=1)]
            _tot_col = "total" if _tbl.startswith("Ingresos") else "monto"
            try:
                _suma = pd.to_numeric(df[_tot_col], errors="coerce").sum()
            except Exception:
                _suma = 0
            st.caption(f"**{len(df)} filas** · suma {('TOTAL' if _tbl.startswith('Ingresos') else 'MONTO_FINAL')}: {_suma/1e6:,.1f} M ARS")
            st.dataframe(df, hide_index=True, use_container_width=True, height=560)
            st.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name="cierres_datos_originales.csv", mime="text/csv", key="orig_dl")
        else:
            st.info("Sin registros para ese filtro.")


# ==================== CALZIM · FACTURAS ====================
def _render_calzim_facturas(cat):
    st.caption("**CALZIM · Facturas** — P&L mensual: ingresos por venta (capón + chancha) menos egresos "
               "(union_gastos). ARS en millones. Período ene–jun 2026. El resultado real deflacta a "
               "pesos de junio con IPC INDEC 2026.")
    pl = cat(f"SELECT to_char(mes,'YYYY-MM') mes, ingresos, ing_capon, ing_chancha, cabezas, cab_capon, "
             f"precio_capon, egresos, e_nutricion, e_personal, e_otros, resultado, margen_pct "
             f"FROM {SC}.v_fact_pl ORDER BY mes")
    if pl is None or pl.empty:
        st.info("No hay datos de facturas de Calzim cargados.")
        return
    for c in pl.columns:
        if c != "mes":
            pl[c] = pd.to_numeric(pl[c], errors="coerce")
    defl = cat(f"SELECT to_char(mes,'YYYY-MM') mes, factor_a_hoy FROM {SC}.v_deflactor ORDER BY mes")
    if defl is not None and not defl.empty:
        defl["factor_a_hoy"] = pd.to_numeric(defl["factor_a_hoy"], errors="coerce")
        d = pl.merge(defl, on="mes", how="left")
    else:
        d = pl.assign(factor_a_hoy=1.0)
    d["factor_a_hoy"] = d["factor_a_hoy"].fillna(1.0)
    d["result_real"] = d["resultado"] * d["factor_a_hoy"]

    ing_t = pl["ingresos"].sum(); res_t = pl["resultado"].sum()
    k = st.columns(4)
    k[0].metric("Ingresos acum.", _mm(ing_t))
    k[1].metric("Resultado acum.", _mm(res_t), f"{res_t/ing_t*100:.1f}% margen" if ing_t else None)
    k[2].metric("Resultado real (jun $)", _mm(d["result_real"].sum()))
    k[3].metric("Meses cargados", str(len(pl)))

    st.markdown("#### P&L mensual")
    show = pd.DataFrame({
        "Mes": pl["mes"],
        "Ingresos": (pl["ingresos"]/1e6).round(0),
        "Egresos": (pl["egresos"]/1e6).round(0),
        "Resultado": (pl["resultado"]/1e6).round(0),
        "Margen %": pl["margen_pct"],
        "Result. real (jun$)": (d["result_real"]/1e6).round(0),
        "Capones": pl["cab_capon"],
        "Precio capón": pl["precio_capon"].round(0),
    })
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.0f")
                                for c in ["Ingresos","Egresos","Resultado","Result. real (jun$)",
                                          "Capones","Precio capón"]}
                 | {"Margen %": st.column_config.NumberColumn(format="%.1f%%")})
    st.caption("Cifras en millones de ARS salvo capones (cabezas) y precio (ARS/kg).")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ingresos vs egresos vs resultado**")
        ch = pl[["mes"]].copy()
        ch["Ingresos"] = pl["ingresos"]/1e6
        ch["Egresos"] = pl["egresos"]/1e6
        ch["Resultado"] = pl["resultado"]/1e6
        st.line_chart(ch.set_index("mes"), use_container_width=True)
    with c2:
        st.markdown("**Precio del capón (ARS/kg)** — evolución")
        pc = pl[["mes"]].copy(); pc["Precio capón"] = pl["precio_capon"]
        st.line_chart(pc.set_index("mes"), use_container_width=True)

    st.markdown("#### Egresos por rubro")
    er = cat(f"SELECT to_char(mes,'YYYY-MM') mes, rubro, monto FROM {SC}.v_fact_egreso_rubro ORDER BY mes")
    if er is not None and not er.empty:
        er["monto"] = pd.to_numeric(er["monto"], errors="coerce")/1e6
        piv = er.pivot_table(index="mes", columns="rubro", values="monto", aggfunc="sum").fillna(0).round(1)
        st.bar_chart(piv, use_container_width=True)
        with st.expander("Detalle egresos por rubro (M ARS)"):
            st.dataframe(piv, use_container_width=True)


# ==================== CALZIM · PRODUCCIÓN (por lote) ====================
def _render_calzim_produccion(cat):
    st.caption("**CALZIM · Producción** — análisis por **lote**. El resultado toma sólo la etapa **SITIO 3** "
               "(la venta real); la *venta de ½ res* se muestra aparte como referencia y NO entra al "
               "resultado. Foco: rendimientos, mortandad en Sitio 3, y por qué un lote rinde más que otro. "
               "Pesos constantes de junio con IPC INDEC 2026.")
    m = cat(f"SELECT to_char(mes,'YYYY-MM') mes, lotes, cabezas_s3, mort_s3_pct_prom, kg_producidos, "
            f"ingreso_sitio3, venta_media_res, costo_total, c_nutricion, c_genetica, c_sanidad, c_personal, "
            f"margen, margen_pct, costo_x_cabeza, ingreso_x_cabeza, costo_alim_x_kg "
            f"FROM {SC}.v_prod_mensual ORDER BY mes")
    if m is None or m.empty:
        st.info("No hay datos de producción de Calzim cargados.")
        return
    for c in m.columns:
        if c != "mes":
            m[c] = pd.to_numeric(m[c], errors="coerce")
    defl = cat(f"SELECT to_char(mes,'YYYY-MM') mes, factor_a_hoy FROM {SC}.v_deflactor ORDER BY mes")
    fac = {}
    if defl is not None and not defl.empty:
        fac = {r["mes"]: float(r["factor_a_hoy"]) for _, r in defl.iterrows()}
    m["factor"] = m["mes"].map(fac).fillna(1.0)
    m["margen_real"] = m["margen"] * m["factor"]

    ing_t = m["ingreso_sitio3"].sum(); mar_t = m["margen"].sum()
    k = st.columns(4)
    k[0].metric("Ingreso Sitio 3 acum.", _mm(ing_t))
    k[1].metric("Margen acum.", _mm(mar_t), f"{mar_t/ing_t*100:.1f}%" if ing_t else None)
    k[2].metric("Margen real (jun $)", _mm(m["margen_real"].sum()))
    k[3].metric("Mortandad S3 prom.", f"{m['mort_s3_pct_prom'].mean():.1f}%")

    st.markdown("#### Resumen mensual")
    show = pd.DataFrame({
        "Mes": m["mes"], "Lotes": m["lotes"], "Cabezas S3": m["cabezas_s3"],
        "Mort. S3 %": m["mort_s3_pct_prom"],
        "Ing. S3 (M)": (m["ingreso_sitio3"]/1e6).round(0),
        "Costo (M)": (m["costo_total"]/1e6).round(0),
        "Margen (M)": (m["margen"]/1e6).round(0),
        "Margen %": m["margen_pct"],
        "Margen real (M)": (m["margen_real"]/1e6).round(0),
        "Alim. $/kg": m["costo_alim_x_kg"].round(0),
        "Ing./cabeza": m["ingreso_x_cabeza"].round(0),
    })
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.0f")
                                for c in ["Cabezas S3","Ing. S3 (M)","Costo (M)","Margen (M)",
                                          "Margen real (M)","Alim. $/kg","Ing./cabeza"]}
                 | {"Mort. S3 %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Margen %": st.column_config.NumberColumn(format="%.1f%%")})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Margen % vs mortandad Sitio 3** — por mes")
        mm = m[["mes"]].copy(); mm["Margen %"] = m["margen_pct"]; mm["Mortandad S3 %"] = m["mort_s3_pct_prom"]
        st.line_chart(mm.set_index("mes"), use_container_width=True)
    with c2:
        st.markdown("**Costo de alimento (ARS/kg)** — evolución")
        al = m[["mes"]].copy(); al["Alimento $/kg"] = m["costo_alim_x_kg"]
        st.line_chart(al.set_index("mes"), use_container_width=True)

    # -------- comparativa entre lotes: el "por qué un lote rinde más" --------
    st.markdown("#### 🐷 Comparativa entre lotes")
    lo = cat(f"SELECT to_char(mes,'YYYY-MM') mes, lote, q_sitio3, kg_prom_s3, precio_s3, mortandad_s3_pct, "
             f"merma_total_pct, ingreso_sitio3, costo_total, margen, margen_pct, costo_x_cabeza, "
             f"ingreso_x_cabeza, margen_x_cabeza, costo_alim_x_kg, conversion_alim "
             f"FROM {SC}.v_prod_lote ORDER BY mes, lote")
    if lo is not None and not lo.empty:
        for c in lo.columns:
            if c not in ("mes", "lote"):
                lo[c] = pd.to_numeric(lo[c], errors="coerce")
        st.caption("Cada fila es un lote. Ordenado por margen %. Comparás mortandad, precio de venta, "
                   "alimento por kg y conversión para entender por qué un lote deja más que otro.")
        tab = pd.DataFrame({
            "Mes": lo["mes"], "Lote": lo["lote"],
            "Cabezas S3": lo["q_sitio3"], "Kg prom": lo["kg_prom_s3"].round(1),
            "Precio $/kg": lo["precio_s3"].round(0),
            "Mort. S3 %": lo["mortandad_s3_pct"], "Merma total %": lo["merma_total_pct"],
            "Margen (M)": (lo["margen"]/1e6).round(1), "Margen %": lo["margen_pct"],
            "Margen/cabeza": lo["margen_x_cabeza"].round(0),
            "Alim. $/kg": lo["costo_alim_x_kg"].round(0),
            "Conversión": lo["conversion_alim"].round(2),
        }).sort_values("Margen %", ascending=False)
        st.dataframe(tab, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.0f")
                                    for c in ["Cabezas S3","Precio $/kg","Margen/cabeza","Alim. $/kg"]}
                     | {"Mort. S3 %": st.column_config.NumberColumn(format="%.1f%%"),
                        "Merma total %": st.column_config.NumberColumn(format="%.1f%%"),
                        "Margen %": st.column_config.NumberColumn(format="%.1f%%"),
                        "Kg prom": st.column_config.NumberColumn(format="%.1f"),
                        "Margen (M)": st.column_config.NumberColumn(format="%.1f"),
                        "Conversión": st.column_config.NumberColumn(format="%.2f")})
        if alt is not None:
            st.markdown("**Mapa: mortandad S3 vs margen %** (tamaño = cabezas; arriba-izquierda = ideal)")
            sc = lo.dropna(subset=["mortandad_s3_pct", "margen_pct"]).copy()
            if not sc.empty:
                st.altair_chart(
                    alt.Chart(sc).mark_circle(opacity=0.8).encode(
                        x=alt.X("mortandad_s3_pct:Q", title="Mortandad Sitio 3 %"),
                        y=alt.Y("margen_pct:Q", title="Margen %"),
                        size=alt.Size("q_sitio3:Q", legend=None, scale=alt.Scale(range=[80, 700])),
                        color=alt.Color("mes:N", legend=alt.Legend(title="Mes", orient="top")),
                        tooltip=["mes", "lote",
                                 alt.Tooltip("mortandad_s3_pct:Q", title="Mort. S3 %", format=".1f"),
                                 alt.Tooltip("margen_pct:Q", title="Margen %", format=".1f"),
                                 alt.Tooltip("precio_s3:Q", title="Precio $/kg", format=",.0f"),
                                 alt.Tooltip("costo_alim_x_kg:Q", title="Alim $/kg", format=",.0f")],
                    ).properties(height=300), use_container_width=True)

    # -------- costo por rubro --------
    st.markdown("#### Costo por rubro")
    cr = cat(f"SELECT to_char(mes,'YYYY-MM') mes, rubro, sum(monto) monto FROM {SC}.v_prod_costo_rubro "
             f"GROUP BY 1,2 ORDER BY 1")
    if cr is not None and not cr.empty:
        cr["monto"] = pd.to_numeric(cr["monto"], errors="coerce")/1e6
        piv = cr.pivot_table(index="mes", columns="rubro", values="monto", aggfunc="sum").fillna(0).round(1)
        st.bar_chart(piv, use_container_width=True)

    # -------- precios MP nutrición --------
    with st.expander("🛢️ Precios de materia prima (nutrición)"):
        mp = cat(f"SELECT campo, um, ars, usd, proveedor, precio_final FROM {SC}.v_precio_mp "
                 f"WHERE rubro='NUTRICION' ORDER BY ars DESC NULLS LAST")
        if mp is not None and not mp.empty:
            st.dataframe(mp, hide_index=True, use_container_width=True)
        else:
            st.caption("Sin precios de MP cargados.")

    # -------- venta 1/2 res (dato aparte) --------
    vr = m[["mes", "venta_media_res"]].copy()
    vr = vr[vr["venta_media_res"].fillna(0) > 0]
    if not vr.empty:
        with st.expander("🥩 Venta de ½ res (referencia, NO entra al resultado)"):
            vr["Venta ½ res (M)"] = (vr["venta_media_res"]/1e6).round(0)
            st.dataframe(vr[["mes", "Venta ½ res (M)"]].rename(columns={"mes": "Mes"}),
                         hide_index=True, use_container_width=True)
            st.caption("Valorización de la venta en media res; se muestra sólo como referencia comercial.")
