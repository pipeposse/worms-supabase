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

    t1, t2, t3, t4, t5, t6, t7 = st.tabs(
        ["📊 Resumen P&L", "🧭 Dónde está el valor", "📈 Evolución / Q1·Q2",
         "💱 Precios MP vs venta", "⚠️ Observaciones", "💡 Insights", "💵 Pesos constantes"])

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

    # ============ 4 · Precios MP vs venta ============
    with t4:
        st.subheader("Spread: precio de venta vs costo de materia prima (por producto)")
        st.caption("Donde el precio de venta del producto supera el costo de la MP comprada, hay margen. "
                   "Promedio del período (ARS por unidad).")
        sp = cat(f"SELECT producto_lbl AS producto, round(avg(precio_venta),0) venta, round(avg(precio_compra),0) compra, "
                 f"round(avg(spread_unit),0) spread, round(avg(spread_pct),0) spread_pct "
                 f"FROM {S}.v_precio_spread WHERE precio_venta IS NOT NULL AND precio_compra IS NOT NULL "
                 f"GROUP BY producto_lbl ORDER BY spread_pct DESC NULLS LAST")
        if sp is not None and not sp.empty:
            st.dataframe(sp.rename(columns={"producto":"Producto","venta":"Venta ARS/u","compra":"Compra MP ARS/u",
                                            "spread":"Spread ARS/u","spread_pct":"Spread %"}),
                         hide_index=True, use_container_width=True)
        else:
            st.info("No hay productos con precio de venta y de compra emparejables por nombre (los rótulos difieren entre gastos e ingresos). "
                    "Se puede mejorar normalizando el catálogo de productos.")

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
