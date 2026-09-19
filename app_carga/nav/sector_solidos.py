# -*- coding: utf-8 -*-
"""Home del sector Disposición Final de Sólidos.

Misma estructura que Disp. Final Líquidos (sector_efluentes.py), con la
definición que bajó dirección (16/09): **sólido = todo lo que entra a la planta
y no es líquido**. No se filtra por un producto_base puntual: se toma el ingreso
de portería y se descarta lo líquido (corrientes vegetal/animal/efluente líquido/
insumo y las bases líquidas conocidas). Así entran tierra, compost, barrido,
descarte, residuos, cubiertas, pellets, chatarra, cartón, polvo, NFU, etc.

EL SECTOR NO EVALÚA: es de SOLO LECTURA. Laboratorio no analiza sólidos (2 de
1.373 camiones del último año), por eso acá no hay ninguna tarjeta de análisis;
lo que se muestra es el ingreso físico:
    · indicadores del día y del mes (camiones, TN, clientes, tipos)
    · resultados del mes: comparación entre meses, proyección de cierre y TN por mes
    · camiones ingresados por portería, con tipo de residuo y destino
    · composición por tipo de sólido
    · exportación a CSV
"""

import calendar as _cal
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from .kpis import _TTL, _kpi, _n, _i

# --- qué NO es sólido ------------------------------------------------------
# Corrientes líquidas de portería (porteria_limpieza.corriente) + las bases que
# viajan como 'sin_declarar' pero son líquidas. Todo lo demás es sólido.
_CORR_LIQ = ("vegetal", "animal", "efluente_liquido", "insumo")
_BASES_LIQ = ("AG", "ARE", "AFE", "SEBO", "BORRA", "GLICERINA", "GLICERINA-FE",
              "GASOIL", "NAFTA", "DISPOSICION FINAL DE LIQUIDOS", "ACEITE_COCO", "ACIDO_KG")
_ES_SOLIDO = (
    "NOT (t.corriente IN ('vegetal','animal','efluente_liquido','insumo') "
    "     OR upper(COALESCE(t.producto_base,'')) IN "
    "        ('AG','ARE','AFE','SEBO','BORRA','GLICERINA','GLICERINA-FE','GASOIL','NAFTA',"
    "         'DISPOSICION FINAL DE LIQUIDOS','ACEITE_COCO','ACIDO_KG'))"
)
_EXCL_CLI = ("NOT EXISTS (SELECT 1 FROM produccion.dic_cliente_excluido e WHERE e.activo "
             "AND upper(COALESCE(t.cliente,'')) LIKE upper(e.patron))")
_BASE = f"t.peso_neto > 0 AND {_ES_SOLIDO} AND {_EXCL_CLI}"


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _leer_kpis(_cf, dia):
    sql = f"""
        SELECT count(*) FILTER (WHERE t.fecha_entrada::date = %s)                                  AS camiones_hoy,
               COALESCE(sum(abs(t.peso_neto)) FILTER (WHERE t.fecha_entrada::date = %s), 0)/1000.0  AS tn_hoy,
               count(*)                                                                            AS camiones_mes,
               COALESCE(sum(abs(t.peso_neto)), 0)/1000.0                                           AS tn_mes,
               count(DISTINCT t.cliente) FILTER (WHERE t.fecha_entrada::date = %s)                 AS clientes_hoy,
               count(DISTINCT t.cliente)                                                           AS clientes_mes,
               count(DISTINCT t.producto_base)                                                     AS tipos_mes
        FROM produccion.v_transacciones_limpias t
        WHERE {_BASE}
          AND t.fecha_entrada >= date_trunc('month', %s::date)
          AND t.fecha_entrada <  date_trunc('month', %s::date) + interval '1 month'
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(dia, dia, dia, dia, dia))
        return df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _camiones(_cf, desde, hasta):
    sql = f"""
        SELECT t.transaccion::bigint AS ticket, t.fecha_entrada::date AS fecha, t.hora_e AS hora,
               t.cliente, t.procedencia, t.transporte, t.patente_chasis, t.patente_acoplado,
               COALESCE(NULLIF(t.producto_base,''), NULLIF(t.producto,''), 'SIN CLASIFICAR') AS tipo,
               t.producto, t.corriente, abs(t.peso_neto) AS kg
        FROM produccion.v_transacciones_limpias t
        WHERE {_BASE} AND t.fecha_entrada::date BETWEEN %s AND %s
        ORDER BY t.fecha_entrada DESC, t.transaccion DESC
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(desde, hasta))
        df["kg"] = pd.to_numeric(df["kg"], errors="coerce")
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _historico(_cf, meses=6):
    """Un renglón por camión de los últimos N meses: con eso se arma el acumulado
    por día del mes, la comparación entre meses y la proyección de cierre."""
    sql = f"""
        SELECT t.fecha_entrada::date AS fecha, abs(t.peso_neto) AS kg,
               COALESCE(NULLIF(t.producto_base,''), 'SIN CLASIFICAR') AS tipo
        FROM produccion.v_transacciones_limpias t
        WHERE {_BASE}
          AND t.fecha_entrada >= (date_trunc('month', current_date) - make_interval(months => %s))::date
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(int(meses),))
        if df.empty:
            return df
        df["kg"] = pd.to_numeric(df["kg"], errors="coerce").fillna(0.0)
        df["tn"] = df["kg"] / 1000.0
        _f = pd.to_datetime(df["fecha"])
        df["mes"] = _f.dt.to_period("M").astype(str)
        df["dia"] = _f.dt.day
        return df
    except Exception:
        return None


def _invalidar():
    _leer_kpis.clear()
    _camiones.clear()
    _historico.clear()


# ------------------------------------------------------------------ indicadores
def _indicadores(ctx):
    k = _leer_kpis(ctx["conn_factory"], date.today())
    if not k:
        st.caption("Indicadores del sector: sin conexión a la base en este momento.")
        return
    ch, th = _i(k.get("camiones_hoy")), float(k.get("tn_hoy") or 0)
    c1 = _kpi("Camiones de sólidos hoy", str(ch),
              (f"{_n(th)} TN · {_i(k.get('clientes_hoy'))} cliente(s)" if ch else "todavía no ingresó ninguno"),
              "ok" if ch else "")
    c2 = _kpi("Sólidos del mes",
              f"{_n(float(k.get('tn_mes') or 0))}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{_i(k.get('camiones_mes'))} camiones · {date.today().strftime('%B %Y')}", "")
    c3 = _kpi("Tipos de residuo", str(_i(k.get("tipos_mes"))),
              f"de {_i(k.get('clientes_mes'))} cliente(s) en el mes", "")
    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ resultados
def _resultados(ctx):
    """Cómo viene el mes contra los anteriores, y en cuánto cierra al ritmo de hoy."""
    st.markdown("#### 📊 Cómo viene el mes")
    hoy = date.today()
    n_meses = st.slider("Meses a comparar", 2, 12, 4, step=1, key="sl_res_meses",
                        help="Se comparan los últimos meses completos contra el mes en curso.")
    df = _historico(ctx["conn_factory"], max(6, n_meses))
    if df is None:
        st.caption("No pude leer el histórico de sólidos.")
        return
    if df.empty:
        st.info("Todavía no hay ingresos de sólidos para comparar.")
        return

    mes_act = pd.Period(hoy, freq="M").strftime("%Y-%m")
    mes_ant = (pd.Period(hoy, freq="M") - 1).strftime("%Y-%m")
    d_mes = df[df["mes"] == mes_act]
    d_ant = df[df["mes"] == mes_ant]
    dia = max(1, hoy.day)
    dias_mes = _cal.monthrange(hoy.year, hoy.month)[1]
    acum = float(d_mes["tn"].sum())
    ritmo = acum / dia
    proy = ritmo * dias_mes
    ant_mismo_dia = float(d_ant[d_ant["dia"] <= dia]["tn"].sum())
    ant_total = float(d_ant["tn"].sum())

    k1 = _kpi("Mes a hoy", f"{_n(acum)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{len(d_mes)} camiones · día {dia} de {dias_mes}", "")
    k2 = _kpi("Proyección de cierre", f"{_n(proy)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"al ritmo actual de {_n(ritmo)} TN por día", "")
    if ant_mismo_dia > 0:
        _var = (acum / ant_mismo_dia - 1) * 100
        k3 = _kpi("Contra el mes pasado", f"{_var:+.0f}<span style='font-size:1rem;font-weight:700;'> %</span>",
                  f"a esta altura del mes pasado iban {_n(ant_mismo_dia)} TN",
                  "ok" if _var >= 0 else "warn")
    else:
        k3 = _kpi("Contra el mes pasado", "—", "sin ingresos del mes pasado para comparar", "")
    k4 = _kpi("Mes pasado completo", f"{_n(ant_total)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{len(d_ant)} camiones en {mes_ant}", "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    meses_disp = sorted(df["mes"].unique())
    meses_sel = meses_disp[-int(n_meses):]
    d2 = df[df["mes"].isin(meses_sel)]

    try:
        import altair as alt
        diario = d2.groupby(["mes", "dia"], as_index=False)["tn"].sum()
        diario["acum"] = diario.sort_values("dia").groupby("mes")["tn"].cumsum()
        diario["tipo"] = "real"
        # La proyección arranca en el último día real del mes en curso y sigue al
        # ritmo diario de hoy hasta fin de mes: es una recta, no un pronóstico fino.
        filas = []
        if mes_act in meses_sel and not d_mes.empty:
            dm = diario[diario["mes"] == mes_act].sort_values("dia")
            if not dm.empty:
                d_ult = int(dm["dia"].iloc[-1])
                a_ult = float(dm["acum"].iloc[-1])
                filas.append({"mes": mes_act + " (proyección)", "dia": d_ult, "acum": a_ult,
                              "tipo": "proyección"})
                for dd in range(d_ult + 1, dias_mes + 1):
                    filas.append({"mes": mes_act + " (proyección)", "dia": dd,
                                  "acum": ritmo * dd, "tipo": "proyección"})
        plot = pd.concat([diario, pd.DataFrame(filas)], ignore_index=True) if filas else diario
        ch = (alt.Chart(plot).mark_line(point=False)
              .encode(x=alt.X("dia:Q", title="día del mes",
                              scale=alt.Scale(domain=[1, dias_mes], nice=False)),
                      y=alt.Y("acum:Q", title="TN acumuladas"),
                      color=alt.Color("mes:N", title="mes"),
                      strokeDash=alt.StrokeDash("tipo:N", title="",
                                                scale=alt.Scale(domain=["real", "proyección"],
                                                                range=[[1, 0], [6, 4]])),
                      tooltip=["mes:N", alt.Tooltip("dia:Q", title="día"),
                               alt.Tooltip("acum:Q", title="TN acum.", format=",.1f")])
              .properties(height=340, title="Acumulado del mes, día por día"))
        st.altair_chart(ch, use_container_width=True)
        st.caption("Línea llena = lo que entró de verdad. Línea punteada = en cuánto cierra el mes "
                   "si sigue entrando al ritmo de estos días.")
    except Exception as _e:
        st.caption("No se pudo dibujar la comparación: %s" % _e)

    c1, c2 = st.columns(2)
    por_mes = (d2.groupby("mes", as_index=False)["tn"].sum().sort_values("mes"))
    por_mes["TN"] = por_mes["tn"].round(1)
    c1.markdown("**Total por mes**")
    c1.bar_chart(por_mes, x="mes", y="TN", use_container_width=True, color="#a16207")

    d3 = d2.copy()
    d3["sem"] = ((d3["dia"] - 1) // 7 + 1).clip(upper=5)
    sem_hoy = min(5, (hoy.day - 1) // 7 + 1)
    sem = c2.selectbox("Semana del mes", [1, 2, 3, 4, 5], index=sem_hoy - 1, key="sl_res_sem",
                       help="1 = días 1-7 · 2 = 8-14 · 3 = 15-21 · 4 = 22-28 · 5 = 29-31.")
    ds = d3[d3["sem"] == sem].groupby("mes", as_index=False)["tn"].sum().sort_values("mes")
    ds["TN"] = ds["tn"].round(1)
    if ds.empty:
        c2.info("Sin datos en esa semana.")
    else:
        c2.bar_chart(ds, x="mes", y="TN", use_container_width=True, color="#a16207")
        c2.caption(f"Misma semana ({sem}ª) de cada mes, para comparar contra el mismo tramo.")

    # composición: qué tipo de sólido explica el mes
    st.markdown("**Composición del mes por tipo de residuo**")
    comp = (d_mes.groupby("tipo", as_index=False)["tn"].sum().sort_values("tn", ascending=False))
    if comp.empty:
        st.caption("Sin ingresos de sólidos en el mes en curso.")
    else:
        comp["TN"] = comp["tn"].round(1)
        comp["% del mes"] = (comp["tn"] / max(comp["tn"].sum(), 1e-9) * 100).round(1)
        st.dataframe(comp[["tipo", "TN", "% del mes"]].rename(columns={"tipo": "Tipo"}),
                     use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ camiones
def _modo_camiones(ctx):
    c1, c2 = st.columns(2)
    desde = c1.date_input("Desde", value=date.today().replace(day=1), key="sl_cam_desde", format="DD/MM/YYYY")
    hasta = c2.date_input("Hasta", value=date.today(), key="sl_cam_hasta", format="DD/MM/YYYY")
    df = _camiones(ctx["conn_factory"], desde, hasta)
    if df is None:
        st.warning("No pude leer los ingresos de portería.")
        return
    if df.empty:
        st.info("Sin camiones de sólidos en el rango.")
        return

    f1, f2 = st.columns(2)
    tipos = sorted(df["tipo"].dropna().astype(str).str.strip().unique().tolist())
    tsel = f1.multiselect("Tipo de residuo (vacío = todos)", tipos, key="sl_cam_tipo")
    if tsel:
        df = df[df["tipo"].astype(str).str.strip().isin(tsel)]
    clis = sorted(df["cliente"].dropna().astype(str).str.strip().unique().tolist())
    csel = f2.multiselect("Cliente (vacío = todos)", clis, key="sl_cam_cli")
    if csel:
        df = df[df["cliente"].astype(str).str.strip().isin(csel)]
    if df.empty:
        st.info("Sin camiones con ese filtro.")
        return

    tot = float(df["kg"].sum() or 0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Camiones", len(df))
    m2.metric("TN netas", f"{tot/1000:,.1f}")
    m3.metric("TN por camión", f"{(tot/len(df))/1000:,.2f}" if len(df) else "—")
    m4.metric("Tipos de residuo", int(df["tipo"].nunique()))

    dm = df.copy()
    dm["mes"] = pd.to_datetime(dm["fecha"]).dt.to_period("M").astype(str)
    por_mes = dm.groupby("mes")["kg"].sum().div(1000).round(1).reset_index().rename(columns={"kg": "TN"})
    if len(por_mes) > 1:
        st.bar_chart(por_mes, x="mes", y="TN", use_container_width=True)

    vista = df.rename(columns={"ticket": "Ticket", "fecha": "Fecha", "hora": "Hora", "cliente": "Cliente",
                               "procedencia": "Procedencia", "transporte": "Transporte",
                               "patente_chasis": "Chasis", "patente_acoplado": "Acoplado",
                               "tipo": "Tipo", "producto": "Producto (portería)", "kg": "Kg"})
    _cols = [c for c in ["Ticket", "Fecha", "Hora", "Cliente", "Tipo", "Producto (portería)",
                         "Procedencia", "Transporte", "Chasis", "Acoplado", "Kg"]
             if c in vista.columns]
    vista = vista[_cols]
    st.dataframe(vista, use_container_width=True, hide_index=True, height=420)
    st.download_button("⬇️ Descargar CSV", vista.to_csv(index=False).encode("utf-8"),
                       file_name=f"solidos_{desde}_{hasta}.csv", mime="text/csv", key="sl_cam_csv")

    with st.expander("📦 Total por tipo de residuo en el rango"):
        g = (df.groupby("tipo", as_index=False)
               .agg(camiones=("ticket", "count"), kg=("kg", "sum"))
               .sort_values("kg", ascending=False))
        g["TN"] = (g["kg"] / 1000).round(1)
        st.dataframe(g[["tipo", "camiones", "TN"]].rename(
            columns={"tipo": "Tipo", "camiones": "Camiones"}),
            use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ pantalla
def render_sector_solidos(ctx, sec):
    from .portada import _hero, _pie_soporte

    USR = ctx["USR"]
    _hero(f"SECTOR {sec['nombre_ui'].upper()}", USR, icono=sec.get("icono") or "🗑️",
          sub="Sólidos: todo lo que entra a la planta y no es líquido. Sólo consulta.")
    _indicadores(ctx)
    _resultados(ctx)
    st.divider()
    st.markdown("#### 🚛 Camiones ingresados")
    _modo_camiones(ctx)
    st.caption("**Sólido = todo ingreso de portería que no es líquido** (se descartan las corrientes "
               "vegetal, animal, efluente líquido e insumo, y las bases líquidas AG/ARE/AFE/sebo/borra/"
               "glicerina/gasoil/nafta). Sector de **sólo lectura**: laboratorio no analiza sólidos.")
    _pie_soporte(ctx)
    return True
