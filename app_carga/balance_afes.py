"""Balance AFE-S ↔ Exportación (Centro de Planificación).

Responde una sola pregunta: ¿alcanza el AFE-S BUENO para sostener la exportación de AG-E?

  - Entradas de AFE por proveedor (portería, clases OTRO/INGRESO de familia AFE), cruzadas
    con el laboratorio del ticket (azufre y fósforo) y clasificadas por índice de calidad
    en EXCELENTE / BUENO / JUSTO / MALO.
  - Exportación: las salidas que portería registra como "AG" con procedencia EGNITRADE S.L.
    hacia las terminales (SOUTHCROSS, PADILLA, LIBRA, MERCOMAR, INTERALMAR…) SON el AG-E
    comercial. Laboratorio no mide cada contenedor porque comparten fórmula.
  - Proyección: cuánto AFE-S bueno exige exportar E tn/semana con x% de AG-E, contra lo que
    entra y lo que hay en tanques → semanas de autonomía del stock bueno.

La misma clasificación explica el algoritmo de despacho: maximizar AG-E y, entre los AFE-S,
usar primero los de PEOR calidad que la spec tolere, reservando los buenos.
"""
import altair as alt
import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
SPEC_S, SPEC_P = 50.0, 150.0          # spec de venta AG-E (máximos)
DENS_AFE = 0.89


# Índice de calidad IC = max(S/50, P/150): el peor de los dos parámetros relativo a la spec
# de venta. Es el MISMO score que usa el algoritmo de despacho para ordenar tanques, así la
# clasificación y la fórmula hablan el mismo idioma.
IC_EXC = 0.80   # EXCELENTE: IC <= 0.80 -> S <= 40 y P <= 120 (banca ~7% de AG-E por sí solo)
IC_BUE = 0.90   # BUENO:     IC <= 0.90 -> S <= 45 y P <= 135 (banca ~4%)
#               JUSTO:      IC <= 1.00 -> cumple spec pero casi sin margen (~0-3%)
#               MALO:       IC >  1.00 -> fuera de spec por sí solo: sólo entra mezclado
BANDAS = ["EXCELENTE", "BUENO", "JUSTO", "MALO", "SIN LAB"]
_B_COLORES = ["#166534", "#1d4ed8", "#f59e0b", "#dc2626", "#94a3b8"]
BUENAS = ("EXCELENTE", "BUENO")   # el "pool bueno" para la proyección


def _banda(s, p):
    if pd.isna(s) and pd.isna(p):
        return "SIN LAB"
    ic = max((float(s) / SPEC_S) if pd.notna(s) else 0.0,
             (float(p) / SPEC_P) if pd.notna(p) else 0.0)
    if ic <= IC_EXC:
        return "EXCELENTE"
    if ic <= IC_BUE:
        return "BUENO"
    if ic <= 1.0:
        return "JUSTO"
    return "MALO"


def _pond(df, col, kgcol="kg"):
    d = df[pd.notna(df[col])]
    if d.empty or float(d[kgcol].sum()) <= 0:
        return None
    return float((d[col] * d[kgcol]).sum() / d[kgcol].sum())


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#7c2d12,#ca8a04);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🧮 Balance</div>"
        "<div style='color:#fef3c7;font-size:.88rem;margin-top:3px'>Qué AFE entra y con qué calidad, "
        "qué AG-E sale a exportación, qué producen los reactores, y si el AFE-S bueno alcanza "
        "para sostener el ritmo.</div></div>",
        unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return

    # ---------------- configuración ----------------
    c3, c4 = st.columns(2)
    sem_h = int(c3.selectbox("Ventana de análisis", [8, 13, 26, 52], index=1, key="ba_h",
                             help="Semanas hacia atrás."))
    exp_obj = c4.number_input("Exportación objetivo (t/sem)", 100.0, 3000.0, 900.0, 50.0, key="ba_e",
                              help="Te dicen 800–1000 t semanales.")
    st.markdown(
        "**¿Qué es una banda?** El AG-E que se exporta se vende con una especificación máxima de "
        "impurezas (azufre ≤ 50 ppm, fósforo ≤ 150 ppm). Como el AG-E crudo viene muy sucio, se "
        "diluye con AFE-S — y no cualquier AFE-S sirve igual: uno limpio *absorbe* mucho AG-E "
        "sin que la mezcla se pase de la spec; uno al límite no absorbe nada. La **banda** resume, "
        "con el análisis de laboratorio de cada camión, cuánta capacidad de dilución tiene ese "
        "AFE-S.\n\n"
        "**Umbrales de calidad** — se clasifica por el peor de los dos parámetros contra la spec "
        "de venta (S 50 / P 150), el mismo criterio que usa el algoritmo de despacho:\n\n"
        "| Banda | Margen contra la spec | En números | Cuánto AG-E banca solo* |\n"
        "|---|---|---|---|\n"
        "| 🟢 **EXCELENTE** | 20% o más | S ≤ 40 **y** P ≤ 120 | ~7% |\n"
        "| 🔵 **BUENO** | 10–20% | S ≤ 45 **y** P ≤ 135 | ~4% |\n"
        "| 🟠 **JUSTO** | cumple, sin margen | S ≤ 50 y P ≤ 150 | ~0–3% |\n"
        "| 🔴 **MALO** | fuera de spec | S > 50 **o** P > 150 | 0 — sólo entra mezclado |\n"
        "| ⚪ **SIN LAB** | desconocido | sin análisis | desconocido |")
    st.caption("*Con AG-E típico (S ≈ 180 ppm): %% máximo de AG-E que ese AFE-S soporta él solo sin "
               "salirse de spec. Para la proyección, el **pool bueno** = EXCELENTE + BUENO.")

    _desde = (pd.Timestamp.today() - pd.Timedelta(weeks=sem_h)).date()

    # ---------------- 1 · lo que entra ----------------
    st.markdown("#### 1 · AFE que entra a planta (portería × laboratorio)")
    ing = cat(
        "SELECT p.fecha, to_char(p.fecha,'IYYY·\"S\"IW') AS semana, to_char(p.fecha,'YYYY-MM') AS mes, "
        "COALESCE(p.procedencia,'—') AS proveedor, abs(p.kg) AS kg, "
        "l.ppm_azufre AS s, l.ppm_fosforo AS p, l.prc_acidez AS ac0 "
        "FROM produccion.v_porteria_ticket p "
        "LEFT JOIN LATERAL (SELECT pl.ppm_azufre, pl.ppm_fosforo, pl.prc_acidez "
        "  FROM produccion.procesos_lab pl "
        "  WHERE btrim(pl.ticket)=p.ticket::text AND COALESCE(pl.anulado,false)=false "
        "  ORDER BY pl.fecha DESC NULLS LAST LIMIT 1) l ON true "
        "WHERE p.familia='AFE' AND p.clase IN ('OTRO','INGRESO') AND p.kg IS NOT NULL "
        "AND p.fecha >= %s", (_desde,))
    if ing is None or ing.empty:
        st.info("No hay ingresos de AFE en la ventana elegida.")
        return
    ing = ing.copy()
    for _c in ("kg", "s", "p"):
        ing[_c] = pd.to_numeric(ing[_c], errors="coerce")
    ing["tn"] = ing["kg"] / 1000.0
    ing["banda"] = [(_banda(a, b)) for a, b in zip(ing["s"], ing["p"])]
    # acidez de Access con unidades mezcladas: < 0.2 es fracción (x100), el resto ya es %
    ing["ac0"] = pd.to_numeric(ing["ac0"], errors="coerce")
    ing["ac"] = ing["ac0"].map(lambda v: (v * 100.0 if v < 0.2 else v) if pd.notna(v) else None)
    ing.loc[pd.to_numeric(ing["ac"], errors="coerce") > 100, "ac"] = None
    ing["ac"] = pd.to_numeric(ing["ac"], errors="coerce")

    _tot = float(ing["tn"].sum())
    _clab = ing[ing["banda"] != "SIN LAB"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ingreso total", "%.0f t" % _tot, "%.0f t/sem" % (_tot / sem_h))
    k2.metric("Con lab (S y P)", "%.0f %%" % (100.0 * float(_clab["tn"].sum()) / _tot if _tot else 0))
    _pb = float(ing.loc[ing["banda"].isin(BUENAS), "tn"].sum())
    k3.metric("EXCELENTE + BUENO", "%.0f t (%.0f%%)" % (_pb, 100.0 * _pb / _tot if _tot else 0),
              "%.0f t/sem" % (_pb / sem_h))
    _pm = float(ing.loc[ing["banda"].isin(["JUSTO", "MALO"]), "tn"].sum())
    k4.metric("JUSTO + MALO", "%.0f t (%.0f%%)" % (_pm, 100.0 * _pm / _tot if _tot else 0),
              "%.0f t/sem" % (_pm / sem_h))
    st.caption("⚠️ La banda se conoce sólo en lo medido: el **SIN LAB** puede esconder bueno o malo. "
               "Cuanto más mida laboratorio los ingresos, mejor la proyección.")

    _piv = ing.pivot_table(index="semana", columns="banda", values="tn", aggfunc="sum").fillna(0.0)
    for _c in BANDAS:
        if _c not in _piv.columns:
            _piv[_c] = 0.0
    _piv = _piv[BANDAS].round(1)

    # barra compuesta con tooltip: t, % de la semana, S/P/acidez ponderados y camiones por proveedor
    def _grp(d):
        _k = float(d["kg"].sum())
        _pv = d.groupby("proveedor").size().sort_values(ascending=False)
        _txt = " · ".join("%s ×%d" % (i, c) for i, c in _pv.head(4).items())
        if len(_pv) > 4:
            _txt += " (+%d prov.)" % (len(_pv) - 4)
        return pd.Series({
            "tn": d["tn"].sum(), "camiones": len(d),
            "s_prom": _pond(d, "s"), "p_prom": _pond(d, "p"), "ac_prom": _pond(d, "ac"),
            "proveedores": _txt})
    _lg = ing.groupby(["semana", "banda"]).apply(_grp).reset_index()
    _tot_sem = _lg.groupby("semana")["tn"].transform("sum")
    _lg["pct"] = (100.0 * _lg["tn"] / _tot_sem).round(1)
    _orden_b = {b: i for i, b in enumerate(BANDAS)}
    _lg["orden"] = _lg["banda"].map(_orden_b)
    _ch = alt.Chart(_lg).mark_bar().encode(
        x=alt.X("semana:N", sort=None, title=None),
        y=alt.Y("tn:Q", title="toneladas"),
        color=alt.Color("banda:N", title="Banda",
                        scale=alt.Scale(domain=BANDAS, range=_B_COLORES)),
        order=alt.Order("orden:Q"),
        tooltip=[alt.Tooltip("semana:N", title="Semana"),
                 alt.Tooltip("banda:N", title="Banda"),
                 alt.Tooltip("tn:Q", format=".1f", title="Toneladas"),
                 alt.Tooltip("pct:Q", format=".1f", title="% de la semana"),
                 alt.Tooltip("s_prom:Q", format=".1f", title="Azufre prom. (ppm)"),
                 alt.Tooltip("p_prom:Q", format=".1f", title="Fósforo prom. (ppm)"),
                 alt.Tooltip("ac_prom:Q", format=".2f", title="Acidez prom. (%)"),
                 alt.Tooltip("camiones:Q", title="Camiones"),
                 alt.Tooltip("proveedores:N", title="Camiones por proveedor")],
    ).properties(height=340)
    st.altair_chart(_ch, use_container_width=True)
    st.caption("🖱️ Pasá el mouse por cada tramo de barra: %% de la semana, promedios ponderados de "
               "azufre/fósforo/acidez de esa banda y camiones por proveedor.")

    ta, tb, tc = st.tabs(["📅 Por semana", "🗓️ Por mes", "🚚 Por proveedor"])
    with ta:
        st.dataframe(_piv.assign(TOTAL=_piv.sum(axis=1).round(1)).reset_index(),
                     hide_index=True, use_container_width=True)
    with tb:
        _pm2 = ing.pivot_table(index="mes", columns="banda", values="tn", aggfunc="sum").fillna(0.0).round(1)
        st.dataframe(_pm2.assign(TOTAL=_pm2.sum(axis=1).round(1)).reset_index(),
                     hide_index=True, use_container_width=True)
    with tc:
        _g = ing.groupby("proveedor").apply(lambda d: pd.Series({
            "t": d["tn"].sum(), "t/sem": d["tn"].sum() / sem_h,
            "S pond (ppm)": _pond(d, "s"), "P pond (ppm)": _pond(d, "p"),
            "% con lab": 100.0 * d.loc[d["banda"] != "SIN LAB", "tn"].sum() / max(d["tn"].sum(), 1e-9),
            "% EXC+BUENO (de lo medido)": (100.0 * d.loc[d["banda"].isin(BUENAS), "tn"].sum()
                                           / max(d.loc[d["banda"] != "SIN LAB", "tn"].sum(), 1e-9)),
        })).reset_index().sort_values("t", ascending=False)
        st.dataframe(_g.round(1), hide_index=True, use_container_width=True,
                     column_config={"% con lab": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                                    "% EXC+BUENO (de lo medido)": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})
        st.caption("Con esto se ve **qué proveedor trae el AFE-S bueno** y a quién conviene pedirle "
                   "más volumen (o más análisis de laboratorio).")

    # ---------------- 2 · lo que sale ----------------
    st.markdown("#### 2 · Exportación de AG-E (salidas EGNITRADE → terminales)")
    st.caption("Portería las registra como **AG / ACIDOS GRASOS** con procedencia **EGNITRADE S.L.** "
               "y destino la terminal (SOUTHCROSS, PADILLA, LIBRA, MERCOMAR, INTERALMAR…): eso es lo "
               "que nosotros llamamos **AG-E**. Laboratorio no mide cada contenedor porque son muchos "
               "con la misma fórmula.")
    exp = cat(
        "SELECT p.fecha, to_char(p.fecha,'IYYY·\"S\"IW') AS semana, to_char(p.fecha,'YYYY-MM') AS mes, "
        "COALESCE(p.destino,'—') AS destino, abs(p.kg) AS kg "
        "FROM produccion.v_porteria_ticket p "
        "WHERE p.clase='SALIDA' AND p.kg IS NOT NULL AND p.fecha >= %s", (_desde,))
    exp_sem_prom = 0.0
    if exp is None or exp.empty:
        st.info("No hay salidas de exportación en la ventana.")
    else:
        exp = exp.copy()
        exp["tn"] = pd.to_numeric(exp["kg"], errors="coerce") / 1000.0
        _te = float(exp["tn"].sum()); exp_sem_prom = _te / sem_h
        e1, e2, e3 = st.columns(3)
        e1.metric("Exportado", "%.0f t" % _te, "%.0f t/sem promedio" % exp_sem_prom)
        _uls = exp.groupby("semana")["tn"].sum().sort_index()
        e2.metric("Última semana", "%.0f t" % (float(_uls.iloc[-1]) if len(_uls) else 0.0))
        e3.metric("Camiones", "%d" % len(exp))
        st.bar_chart(_uls.round(1), use_container_width=True)
        with st.expander("Por mes y por terminal"):
            _em = exp.groupby("mes")["tn"].sum().round(1).reset_index()
            _ed = exp.groupby("destino")["tn"].sum().sort_values(ascending=False).round(1).reset_index()
            _x1, _x2 = st.columns(2)
            _x1.dataframe(_em, hide_index=True, use_container_width=True)
            _x2.dataframe(_ed, hide_index=True, use_container_width=True)

    # ---------------- 3 · producido en reactores ----------------
    st.markdown("#### 3 · Producido en reactores")
    st.caption("Reacciones **finalizadas** (desgomados → AFE-S y producción ARE), por semana y "
               "producto. Los kg reales salen de la mejor fuente disponible: tickets de pesada, "
               "cierre manual de la reacción, o kg_obtenido.")
    # el real de una reacción puede vivir en kg_obtenido (recomputado por tickets), en el
    # cierre manual (fact_reaccion_cierre.real_kg — el caso típico del ARE) o en los tickets
    # de pesada: se toma la mejor fuente disponible, si no el ARE aparecía en cero.
    prod = cat(
        "SELECT to_char(COALESCE(b.fin_ts, b.fecha::timestamp),'IYYY·\"S\"IW') AS semana, "
        "to_char(COALESCE(b.fin_ts, b.fecha::timestamp),'YYYY-MM') AS mes, "
        "COALESCE(dp.codigo_producto,'—') AS producto, "
        "sum(COALESCE(NULLIF(b.kg_obtenido,0), c.real_kg, t.kg, 0))/1000.0 AS tn, count(*) AS n "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.fact_reaccion_cierre c ON c.id_batch=b.id_batch "
        "LEFT JOIN (SELECT id_batch, sum(kg) AS kg FROM produccion.fact_batch_ticket_final "
        "           WHERE COALESCE(anulado,false)=false GROUP BY 1) t ON t.id_batch=b.id_batch "
        "LEFT JOIN produccion.dim_producto dp ON dp.id_producto=b.id_producto_buscado "
        "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
        "AND b.estado='FINALIZADO' AND COALESCE(b.fin_ts, b.fecha::timestamp) >= %s "
        "GROUP BY 1,2,3", (_desde,))
    if prod is None or prod.empty:
        st.info("No hay reacciones finalizadas en la ventana.")
    else:
        prod = prod.copy()
        prod["tn"] = pd.to_numeric(prod["tn"], errors="coerce").fillna(0.0)
        _tp = float(prod["tn"].sum())
        r1, r2, r3 = st.columns(3)
        r1.metric("Producido total", "%.0f t" % _tp, "%.0f t/sem" % (_tp / sem_h))
        _afe_p = float(prod.loc[prod["producto"].str.upper().str.startswith("AFE"), "tn"].sum())
        r2.metric("AFE producido", "%.0f t" % _afe_p, "%.0f t/sem" % (_afe_p / sem_h))
        r3.metric("Reacciones", "%d" % int(pd.to_numeric(prod["n"], errors="coerce").fillna(0).sum()))
        _pw = prod.pivot_table(index="semana", columns="producto", values="tn", aggfunc="sum").fillna(0.0).round(1)
        st.bar_chart(_pw, use_container_width=True)
        with st.expander("Por semana y por mes (tabla)"):
            _y1, _y2 = st.columns(2)
            _y1.dataframe(_pw.assign(TOTAL=_pw.sum(axis=1).round(1)).reset_index(),
                          hide_index=True, use_container_width=True)
            _pmm = prod.pivot_table(index="mes", columns="producto", values="tn", aggfunc="sum").fillna(0.0).round(1)
            _y2.dataframe(_pmm.assign(TOTAL=_pmm.sum(axis=1).round(1)).reset_index(),
                          hide_index=True, use_container_width=True)
        st.caption("El desgomado propio también alimenta el pool de AFE-S para exportar: si el "
                   "producido cae, la dependencia del AFE-S comprado (sección 1) sube.")

    # ---- calidad del AFE producido por desgomado, en bandas, comparable con lo comprado ----
    st.markdown("**Calidad del AFE producido por desgomado** (misma escala de bandas que lo comprado)")
    st.caption("La calidad de cada reacción sale del análisis de laboratorio de su **ticket de "
               "pesada final**. Sin ese análisis, la reacción cae en SIN LAB.")
    dprod = cat(
        "SELECT to_char(COALESCE(b.fin_ts, b.fecha::timestamp),'IYYY·\"S\"IW') AS semana, "
        "b.identificador_unidad AS ident, "
        "COALESCE(NULLIF(b.kg_obtenido,0), c.real_kg, t.kg, 0) AS kg, "
        "l.s, l.p, l.ac0 "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.fact_reaccion_cierre c ON c.id_batch=b.id_batch "
        "LEFT JOIN (SELECT id_batch, sum(kg) AS kg FROM produccion.fact_batch_ticket_final "
        "           WHERE COALESCE(anulado,false)=false GROUP BY 1) t ON t.id_batch=b.id_batch "
        "LEFT JOIN produccion.dim_producto dp ON dp.id_producto=b.id_producto_buscado "
        "LEFT JOIN LATERAL (SELECT pl.ppm_azufre AS s, pl.ppm_fosforo AS p, pl.prc_acidez AS ac0 "
        "  FROM produccion.fact_batch_ticket_final ft "
        "  JOIN produccion.procesos_lab pl ON btrim(pl.ticket)=btrim(ft.ticket) "
        "  WHERE ft.id_batch=b.id_batch AND COALESCE(ft.anulado,false)=false "
        "    AND COALESCE(pl.anulado,false)=false AND pl.ppm_azufre IS NOT NULL "
        "  ORDER BY pl.fecha DESC NULLS LAST LIMIT 1) l ON true "
        "WHERE b.sector='REACTORES' AND b.tipo_proceso='DESGOMADO_ACUOSO' "
        "AND b.estado='FINALIZADO' AND COALESCE(b.anulado,false)=false "
        "AND dp.codigo_producto LIKE 'AFE%%' "
        "AND COALESCE(b.fin_ts, b.fecha::timestamp) >= %s", (_desde,))
    if dprod is None or dprod.empty:
        st.info("No hay desgomados finalizados con kilos en la ventana.")
    else:
        dprod = dprod.copy()
        for _c in ("kg", "s", "p", "ac0"):
            dprod[_c] = pd.to_numeric(dprod[_c], errors="coerce")
        dprod = dprod[dprod["kg"].fillna(0) > 0]
        dprod["tn"] = dprod["kg"] / 1000.0
        dprod["banda"] = [(_banda(a, b)) for a, b in zip(dprod["s"], dprod["p"])]
        dprod["ac"] = dprod["ac0"].map(
            lambda v: (v * 100.0 if v < 0.2 else v) if pd.notna(v) else None)
        dprod["ac"] = pd.to_numeric(dprod["ac"], errors="coerce")

        # comparación compra vs producción propia, en cantidad y calidad
        _tp2 = float(dprod["tn"].sum())
        _pbp = float(dprod.loc[dprod["banda"].isin(BUENAS), "tn"].sum())
        _lbp = dprod[dprod["banda"] != "SIN LAB"]
        _pct_b_prod = (100.0 * _pbp / float(_lbp["tn"].sum())) if not _lbp.empty and _lbp["tn"].sum() > 0 else 0.0
        _tn_comp_lab = float(_clab["tn"].sum())
        _pct_b_comp = (100.0 * float(_clab.loc[_clab["banda"].isin(BUENAS), "tn"].sum())
                       / _tn_comp_lab) if _tn_comp_lab > 0 else 0.0
        d1_, d2_, d3_, d4_ = st.columns(4)
        d1_.metric("Producido (desgomado)", "%.0f t" % _tp2, "%.0f t/sem" % (_tp2 / sem_h))
        d2_.metric("Comprado", "%.0f t" % _tot, "%.0f t/sem" % (_tot / sem_h))
        d3_.metric("%% EXC+BUENO producido", "%.0f %%" % _pct_b_prod,
                   help="Sobre lo producido CON análisis del ticket final.")
        d4_.metric("%% EXC+BUENO comprado", "%.0f %%" % _pct_b_comp,
                   help="Sobre lo comprado con análisis.")
        _s_pr = _pond(dprod, "s", "tn"); _p_pr = _pond(dprod, "p", "tn")
        if _s_pr is not None:
            st.caption("Calidad ponderada del producido: **S %.1f / P %.1f** vs comprado "
                       "S %.1f / P %.1f. El desgomado propio pesa un %.0f%% del total de AFE."
                       % (_s_pr, _p_pr or 0,
                          _pond(_clab, "s") or 0, _pond(_clab, "p") or 0,
                          100.0 * _tp2 / (_tp2 + _tot) if (_tp2 + _tot) else 0))

        def _grp2(d):
            _tt = " · ".join(sorted(d["ident"].astype(str))[:5])
            if len(d) > 5:
                _tt += " (+%d)" % (len(d) - 5)
            return pd.Series({"tn": d["tn"].sum(), "reacciones": len(d),
                              "s_prom": _pond(d, "s", "tn"), "p_prom": _pond(d, "p", "tn"),
                              "ac_prom": _pond(d, "ac", "tn"), "cuales": _tt})
        _lg2 = dprod.groupby(["semana", "banda"]).apply(_grp2).reset_index()
        _tot2 = _lg2.groupby("semana")["tn"].transform("sum")
        _lg2["pct"] = (100.0 * _lg2["tn"] / _tot2).round(1)
        _lg2["orden"] = _lg2["banda"].map({b: i for i, b in enumerate(BANDAS)})
        _ch2 = alt.Chart(_lg2).mark_bar().encode(
            x=alt.X("semana:N", sort=None, title=None),
            y=alt.Y("tn:Q", title="toneladas producidas"),
            color=alt.Color("banda:N", title="Banda",
                            scale=alt.Scale(domain=BANDAS, range=_B_COLORES)),
            order=alt.Order("orden:Q"),
            tooltip=[alt.Tooltip("semana:N", title="Semana"),
                     alt.Tooltip("banda:N", title="Banda"),
                     alt.Tooltip("tn:Q", format=".1f", title="Toneladas"),
                     alt.Tooltip("pct:Q", format=".1f", title="% de la semana"),
                     alt.Tooltip("s_prom:Q", format=".1f", title="Azufre prom. (ppm)"),
                     alt.Tooltip("p_prom:Q", format=".1f", title="Fósforo prom. (ppm)"),
                     alt.Tooltip("ac_prom:Q", format=".2f", title="Acidez prom. (%)"),
                     alt.Tooltip("reacciones:Q", title="Reacciones"),
                     alt.Tooltip("cuales:N", title="Cuáles")],
        ).properties(height=300)
        st.altair_chart(_ch2, use_container_width=True)

    # ---------------- 4 · stock actual por banda ----------------
    st.markdown("#### 4 · Stock actual de AFE-S y AG-E por banda")
    tk = cat("SELECT nombre, producto_principal, litros_actual, capacidad_litros, densidad, "
             "azufre, fosforo, codigo FROM produccion.vw_tanque_panel "
             "WHERE activo AND upper(producto_principal) IN ('AFE-S','AG-E')")
    stock_bueno_t = 0.0
    _afe = pd.DataFrame()
    _age = pd.DataFrame()
    if tk is None or tk.empty:
        st.info("Sin tanques de AFE-S / AG-E.")
    else:
        tk = tk.copy()
        for _c in ("litros_actual", "capacidad_litros", "densidad", "azufre", "fosforo"):
            tk[_c] = pd.to_numeric(tk[_c], errors="coerce")
        # regla de fondo: en base plana sólo se usa el 90% de la capacidad; en cónicos, el 100%
        _nm = (tk["nombre"].astype(str) + " " + tk["codigo"].astype(str)).str.upper()
        _con = _nm.str.contains("CONIC") | _nm.str.contains("C-NICO") | _nm.str.contains("CÓNICO")
        _resv = (0.10 * tk["capacidad_litros"].fillna(0)).where(~_con, 0.0)
        tk["util_l"] = (tk["litros_actual"].fillna(0) - _resv).clip(lower=0)
        tk["tn"] = tk["util_l"] * tk["densidad"].fillna(DENS_AFE) / 1000.0
        tk["banda"] = [(_banda(a, b)) for a, b in zip(tk["azufre"], tk["fosforo"])]
        _afe = tk[tk["producto_principal"].str.upper() == "AFE-S"]
        _age = tk[tk["producto_principal"].str.upper() == "AG-E"]
        stock_bueno_t = float(_afe.loc[_afe["banda"].isin(BUENAS), "tn"].sum())
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("AFE-S EXC+BUENO", "%.0f t" % stock_bueno_t)
        s2.metric("AFE-S JUSTO/MALO", "%.0f t" % float(_afe.loc[_afe["banda"].isin(["JUSTO", "MALO"]), "tn"].sum()))
        s3.metric("AFE-S sin lab", "%.0f t" % float(_afe.loc[_afe["banda"] == "SIN LAB", "tn"].sum()))
        s4.metric("AG-E en tanques", "%.0f t" % float(_age["tn"].sum()))
        st.caption("Toneladas **útiles**: en base plana ya se descontó el 10% de capacidad que queda "
                   "como fondo de tanque; los cónicos se usan al 100%.")
        with st.expander("Detalle por tanque"):
            _d = tk.sort_values(["producto_principal", "tn"], ascending=[True, False])[
                ["nombre", "producto_principal", "banda", "util_l", "tn", "azufre", "fosforo"]]
            st.dataframe(_d.rename(columns={"nombre": "Tanque", "producto_principal": "Prod.",
                                            "banda": "Banda", "util_l": "Útil (L)", "tn": "t útiles",
                                            "azufre": "S ppm", "fosforo": "P ppm"}).round(1),
                         hide_index=True, use_container_width=True)

    # ---------------- 5 · simulación stock + flujo ----------------
    st.markdown("#### 5 · ¿Alcanza el AFE-S bueno? (simulación de stock + flujo)")
    st.caption("Modelo de tres pools de diluyente (**EXC+BUENO**, **JUSTO**, **MALO**): cada semana "
               "se despacha usando primero el MALO, después el JUSTO y recién al final el BUENO "
               "(la misma política que el botón *Sugerir* de Despachos), contra el stock útil en "
               "tanques más lo que entra por semana (compras + producción propia). El SIN LAB se "
               "prorratea con la proporción de lo medido.")

    # --- calidades ponderadas por pool: entrada (ventana) + stock en tanques
    def _qpool(bandas, s_def, p_def):
        parts = []
        d1 = ing[ing["banda"].isin(bandas)]
        if not d1.empty:
            parts.append(pd.DataFrame({"s": d1["s"], "p": d1["p"], "w": d1["tn"]}))
        if not _afe.empty:
            d2 = _afe[_afe["banda"].isin(bandas)]
            if not d2.empty:
                parts.append(pd.DataFrame({"s": d2["azufre"], "p": d2["fosforo"], "w": d2["tn"]}))
        if not parts:
            return s_def, p_def
        dd = pd.concat(parts, ignore_index=True)
        _s = _pond(dd, "s", "w")
        _p = _pond(dd, "p", "w")
        return (_s if _s is not None else s_def), (_p if _p is not None else p_def)

    q = {"BUENO": _qpool(BUENAS, 42.0, 115.0),
         "JUSTO": _qpool(("JUSTO",), 48.0, 142.0),
         "MALO": _qpool(("MALO",), 47.0, 220.0)}
    s_age = (_pond(_age, "azufre", "tn") if not _age.empty else None) or 180.0
    p_age = (_pond(_age, "fosforo", "tn") if not _age.empty else None) or 300.0

    # --- proporciones medidas (para prorratear SIN LAB y la producción propia)
    _lab_in = ing[ing["banda"] != "SIN LAB"]
    _tn_lab = float(_lab_in["tn"].sum())
    if _tn_lab > 0:
        _prop = {pl: float(_lab_in.loc[_lab_in["banda"].isin(bs), "tn"].sum()) / _tn_lab
                 for pl, bs in (("BUENO", BUENAS), ("JUSTO", ("JUSTO",)), ("MALO", ("MALO",)))}
    else:
        _prop = {"BUENO": 0.3, "JUSTO": 0.3, "MALO": 0.4}

    # --- stock inicial por pool (t útiles), con el sin-lab de tanques prorrateado
    def _stk_pool(bandas):
        return float(_afe.loc[_afe["banda"].isin(bandas), "tn"].sum()) if not _afe.empty else 0.0
    _stk_sin = _stk_pool(("SIN LAB",))
    stk0 = {pl: _stk_pool(bs) + _stk_sin * _prop[pl]
            for pl, bs in (("BUENO", BUENAS), ("JUSTO", ("JUSTO",)), ("MALO", ("MALO",)))}

    # --- flujo semanal por pool: compras (medido + sin-lab prorrateado) + producción propia AFE-S
    _in_sem = {pl: float(ing.loc[ing["banda"].isin(bs), "tn"].sum()) / sem_h
               for pl, bs in (("BUENO", BUENAS), ("JUSTO", ("JUSTO",)), ("MALO", ("MALO",)))}
    _in_sin = float(ing.loc[ing["banda"] == "SIN LAB", "tn"].sum()) / sem_h
    try:
        _prod_afe_sem = float(prod.loc[prod["producto"].str.upper().str.startswith("AFE-S"), "tn"].sum()) / sem_h
    except Exception:
        _prod_afe_sem = 0.0
    flujo = {pl: _in_sem[pl] + (_in_sin + _prod_afe_sem) * _prop[pl] for pl in ("BUENO", "JUSTO", "MALO")}

    st.caption("Calidades ponderadas — BUENO: S %.1f / P %.1f · JUSTO: S %.1f / P %.1f · MALO: "
               "S %.1f / P %.1f · AG-E: S %.1f / P %.1f. Flujo semanal estimado: BUENO %.0f t · "
               "JUSTO %.0f t · MALO %.0f t (incluye %.0f t/sem de producción propia de AFE-S y "
               "%.0f t/sem sin lab, prorrateadas)."
               % (q["BUENO"][0], q["BUENO"][1], q["JUSTO"][0], q["JUSTO"][1], q["MALO"][0],
                  q["MALO"][1], s_age, p_age, flujo["BUENO"], flujo["JUSTO"], flujo["MALO"],
                  _prod_afe_sem, _in_sin))

    # --- mezcla óptima: mínimo BUENO (y dentro de eso, mínimo JUSTO) que cumple S y P
    def _mix_min_bueno(D, disp, Ts, Tp):
        if D <= 0:
            return {"BUENO": 0.0, "JUSTO": 0.0, "MALO": 0.0}
        if Ts < 0 or Tp < 0 or (disp["BUENO"] + disp["JUSTO"] + disp["MALO"]) < D - 1e-6:
            return None
        sB, pB = q["BUENO"]; sJ, pJ = q["JUSTO"]; sM, pM = q["MALO"]

        def _fact(b):
            resto = D - b
            lo = max(0.0, resto - disp["MALO"])
            hi = min(disp["JUSTO"], resto)
            if lo > hi + 1e-9:
                return None
            for (vB, vJ, vM, T) in ((sB, sJ, sM, Ts), (pB, pJ, pM, Tp)):
                rhs = T * D - vB * b - vM * resto
                coef = vJ - vM
                if abs(coef) < 1e-12:
                    if rhs < -1e-9:
                        return None
                elif coef > 0:
                    hi = min(hi, rhs / coef)
                else:
                    lo = max(lo, rhs / coef)
            return lo if lo <= hi + 1e-9 else None

        b_hi = min(disp["BUENO"], D)
        if _fact(b_hi) is None:
            return None
        if _fact(0.0) is not None:
            b = 0.0
        else:
            lo_b, hi_b = 0.0, b_hi
            for _ in range(40):
                mid = (lo_b + hi_b) / 2.0
                if _fact(mid) is None:
                    lo_b = mid
                else:
                    hi_b = mid
            b = hi_b
        j = min(max(_fact(b) or 0.0, 0.0), D - b)
        return {"BUENO": b, "JUSTO": j, "MALO": max(0.0, D - b - j)}

    def _targets(x):
        return ((SPEC_S - x * s_age) / (1.0 - x), (SPEC_P - x * p_age) / (1.0 - x))

    # --- techo sostenible de AG-E usando SOLO el flujo semanal (régimen permanente)
    def _sostenible(x):
        Ts, Tp = _targets(x)
        return _mix_min_bueno(exp_obj * (1.0 - x), dict(flujo), Ts, Tp) is not None
    x_sost = 0.0
    if _sostenible(0.0):
        lo_x, hi_x = 0.0, 0.25
        for _ in range(40):
            mx = (lo_x + hi_x) / 2.0
            if _sostenible(mx):
                lo_x = mx
            else:
                hi_x = mx
        x_sost = lo_x

    c1, c2 = st.columns([1, 2])
    x_pct = c1.slider("% de AG-E en la carga", 0.0, 15.0, round(min(max(x_sost * 100, 2.0), 15.0), 1),
                      0.5, key="ba_x", help="Arranca en el techo sostenible calculado. Subilo para "
                                            "ver cuándo se rompe el stock.")
    x = x_pct / 100.0
    if _sostenible(0.0):
        c2.metric("📐 Techo sostenible de AG-E (sólo con el flujo semanal)", "%.1f %%" % (x_sost * 100),
                  "a %.0f t/sem de exportación" % exp_obj, delta_color="off")
    else:
        _volf = flujo["BUENO"] + flujo["JUSTO"] + flujo["MALO"]
        _motf = ("falta VOLUMEN: entran %.0f t/sem de AFE-S y hacen falta %.0f"
                 % (_volf, exp_obj) if _volf < exp_obj else
                 "falta CALIDAD: con lo que entra, ni la mejor mezcla cumple la spec")
        c2.error("Ni con 0%% de AG-E el flujo semanal sostiene %.0f t/sem — %s. La simulación de "
                 "abajo muestra cuántas semanas aguanta el stock." % (exp_obj, _motf))

    # --- simulación semanal hacia adelante (8 semanas): stock + flujo, mezcla óptima
    D_sem = exp_obj * (1.0 - x)
    Ts, Tp = _targets(x)
    stk_c = dict(stk0)
    filas, rotura = [], None
    for w in range(1, 9):
        disp = {pl: stk_c[pl] + flujo[pl] for pl in stk_c}
        uso = _mix_min_bueno(D_sem, disp, Ts, Tp)
        if uso is None:
            rotura = w
            _vol = disp["BUENO"] + disp["JUSTO"] + disp["MALO"]
            _mot = ("falta VOLUMEN: %d t disponibles vs %d t necesarias" % (_vol, D_sem)
                    if _vol < D_sem - 1e-6 else
                    "falta CALIDAD: ni la mejor mezcla posible cumple S/P")
            filas.append({"Semana": "+%d" % w, "AG-E (t)": round(exp_obj * x), "BUENO usado": "—",
                          "JUSTO usado": "—", "MALO usado": "—",
                          "Stock BUENO fin": round(disp["BUENO"]), "Stock JUSTO fin": round(disp["JUSTO"]),
                          "Estado": "🔴 " + _mot})
            break
        stk_c = {pl: max(0.0, disp[pl] - uso[pl]) for pl in disp}
        filas.append({"Semana": "+%d" % w, "AG-E (t)": round(exp_obj * x),
                      "BUENO usado": round(uso["BUENO"]), "JUSTO usado": round(uso["JUSTO"]),
                      "MALO usado": round(uso["MALO"]),
                      "Stock BUENO fin": round(stk_c["BUENO"]), "Stock JUSTO fin": round(stk_c["JUSTO"]),
                      "Estado": "✅"})
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
    if rotura:
        st.error("🔴 Con **%.1f%% de AG-E** a %.0f t/sem, la mezcla deja de cerrar en la "
                 "**semana +%d**: el stock de AFE-S bueno/justo se agota antes de que el flujo lo "
                 "reponga. Bajá el %% de AG-E, conseguí AFE-S bueno (mirá la pestaña por proveedor) "
                 "o bajá la exportación." % (x_pct, exp_obj, rotura))
    else:
        _fin_b = filas[-1]["Stock BUENO fin"]
        st.success("✅ Con **%.1f%% de AG-E** a %.0f t/sem, las 8 semanas cierran. Stock de BUENO "
                   "al final: %s t (hoy: %.0f t)." % (x_pct, exp_obj, _fin_b, stk0["BUENO"]))
    st.caption("La mezcla de cada semana usa el mínimo de BUENO posible (primero MALO, después "
               "JUSTO): es exactamente lo que hace *Sugerir mezcla* en Despachos. Si acá se rompe, "
               "en la planta se rompe igual — esto solo lo anticipa.")

    # ---------------- 6 · cómo ajusta la fórmula de despacho ----------------
    with st.expander("📐 Cómo ajusta esto la fórmula de despacho", expanded=True):
        st.markdown(
            "1. **El AG-E sigue al máximo** que la spec tolere (es lo más barato): eso no cambia.\n"
            "2. **Entre los AFE-S, la sugerencia ahora carga primero los de PEOR calidad** (azufre y "
            "fósforo altos) y va sumando buenos **sólo los necesarios** para que la mezcla cierre en "
            "spec. Antes hacía lo contrario (gastaba los mejores primero) y por eso el bueno se agotaba.\n"
            "3. El **techo sostenible de %% AG-E** sale de la tabla de arriba: si el despacho pide más "
            "AG-E que ese techo, cumple hoy pero funde el stock de bueno en las semanas indicadas.\n"
            "4. Regla operativa: si la autonomía baja de ~4 semanas, o se consigue AFE-S bueno "
            "(ver pestaña por proveedor: quién lo trae), o se baja un punto el %% de AG-E.\n"
            "5. Más análisis de laboratorio en ingresos = menos masa SIN LAB = proyección más firme.")
