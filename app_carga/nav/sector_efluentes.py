# -*- coding: utf-8 -*-
"""Home del sector Disposición Final de Líquidos (efluentes líquidos).

Pedido de dirección (14/09): al entrar a este sector se ve SOLO lo de efluentes
líquidos; nada de otros sectores. Antes la tarjeta abría la sección Laboratorio
completa (todos los productos, todas las vistas).

EL SECTOR NO EVALÚA: es de SOLO LECTURA. Laboratorio carga sus análisis desde su
propia sección; acá únicamente se consulta lo que ya cargó. Lo que se muestra,
todo filtrado por producto_base = "DISPOSICION FINAL DE LIQUIDOS":
    · indicadores del día y del mes (camiones, TN, cuántos tienen análisis)
    · resultados del mes: comparación entre meses, proyección de cierre y TN por mes
    · camiones ingresados por portería con el resultado del laboratorio al lado
    · el flujo de las piletas (entra efluente, sale AG recuperado)
    · exportación a CSV
"""

import calendar as _cal
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from .kpis import _TTL, _kpi, _n, _i

PB = "DISPOSICION FINAL DE LIQUIDOS"          # producto_base (portería) y producto_lab (laboratorio)
# El sector NO carga análisis: laboratorio los hace en su sección. Acá sólo se mira.
_MODOS = ["🚛 Camiones ingresados"]
_EXCL_CLI = ("NOT EXISTS (SELECT 1 FROM produccion.dic_cliente_excluido e WHERE e.activo "
             "AND upper(COALESCE(t.cliente,'')) LIKE upper(e.patron))")


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _leer_kpis(_cf, dia):
    sql = f"""
        SELECT count(*) FILTER (WHERE t.fecha_entrada::date = %s)                                   AS camiones_hoy,
               COALESCE(sum(abs(t.peso_neto)) FILTER (WHERE t.fecha_entrada::date = %s), 0)/1000.0   AS tn_hoy,
               count(*)                                                                             AS camiones_mes,
               COALESCE(sum(abs(t.peso_neto)), 0)/1000.0                                            AS tn_mes,
               count(*) FILTER (WHERE t.fecha_entrada::date = %s AND COALESCE(t.evaluado,'NO') <> 'SI') AS pend_hoy,
               count(*) FILTER (WHERE t.fecha_entrada::date = %s AND COALESCE(t.evaluado,'NO') = 'SI')  AS eval_hoy,
               count(DISTINCT t.cliente) FILTER (WHERE t.fecha_entrada::date = %s)                  AS clientes_hoy
        FROM produccion.v_transacciones_limpias t
        WHERE t.producto_base = %s
          AND t.fecha_entrada >= date_trunc('month', %s::date)
          AND t.fecha_entrada <  date_trunc('month', %s::date) + interval '1 month'
          AND {_EXCL_CLI}
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(dia, dia, dia, dia, dia, PB, dia, dia))
        return df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _camiones(_cf, desde, hasta):
    # "En stock": cada camión de efluente es una ENTRADA a piletas en el libro de stock
    # (produccion.fn_sync_movimientos_efluente, corre cada 15 minutos).
    sql = f"""
        SELECT t.transaccion::bigint AS ticket, t.fecha_entrada::date AS fecha, t.hora_e AS hora,
               t.cliente, t.procedencia, t.transporte, t.patente_chasis, t.patente_acoplado,
               abs(t.peso_neto) AS kg, t.evaluado,
               t.lab_calidad, t.lab_rechazado, t.lab_num_muestra, t.lab_fecha,
               EXISTS (SELECT 1 FROM produccion.fact_movimiento_stock m
                        WHERE m.origen = 'efluente_porteria' AND NOT m.anulado
                          AND regexp_replace(m.ticket_porteria, '\\.0+$', '')
                              = regexp_replace(t.transaccion::text, '\\.0+$', '')) AS en_stock
        FROM produccion.v_transacciones_limpias t
        WHERE t.producto_base = %s AND t.fecha_entrada::date BETWEEN %s AND %s AND {_EXCL_CLI}
        ORDER BY t.fecha_entrada DESC, t.transaccion DESC
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(PB, desde, hasta))
        df["kg"] = pd.to_numeric(df["kg"], errors="coerce")
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _historico(_cf, meses=6):
    """Un renglón por día de los últimos N meses: con eso se arma el acumulado
    por día del mes, la comparación entre meses y la proyección de cierre."""
    sql = f"""
        SELECT t.fecha_entrada::date AS fecha, abs(t.peso_neto) AS kg
        FROM produccion.v_transacciones_limpias t
        WHERE t.producto_base = %s
          AND t.fecha_entrada >= (date_trunc('month', current_date) - make_interval(months => %s))::date
          AND t.peso_neto IS NOT NULL
          AND {_EXCL_CLI}
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(PB, int(meses)))
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


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _flujo_piletas(_cf, n=6):
    """Mes a mes: efluente que entró a piletas vs AG recuperado que salió."""
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                "SELECT mes, camiones_efluente, efluente_tn, camiones_ag, ag_recuperado_tn, "
                "rendimiento_pct FROM produccion.v_piletas_flujo ORDER BY mes DESC LIMIT %s",
                conn, params=(int(n),))
    except Exception:
        return None


def _invalidar():
    _leer_kpis.clear()
    _camiones.clear()
    _historico.clear()
    _flujo_piletas.clear()


# ------------------------------------------------------------------ indicadores
def _indicadores(ctx):
    k = _leer_kpis(ctx["conn_factory"], date.today())
    if not k:
        st.caption("Indicadores del sector: sin conexión a la base en este momento.")
        return
    ch, th = _i(k.get("camiones_hoy")), float(k.get("tn_hoy") or 0)
    c1 = _kpi("Camiones de efluente hoy", str(ch),
              (f"{_n(th)} TN · {_i(k.get('clientes_hoy'))} cliente(s)" if ch else "todavía no ingresó ninguno"),
              "ok" if ch else "")
    c2 = _kpi("Efluente del mes",
              f"{_n(float(k.get('tn_mes') or 0))}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{_i(k.get('camiones_mes'))} camiones · {date.today().strftime('%B %Y')}", "")
    # Dato informativo, NO una tarea del sector: quien evalúa es laboratorio,
    # desde su propia sección.
    pend, ev = _i(k.get("pend_hoy")), _i(k.get("eval_hoy"))
    c3 = _kpi("Con análisis de laboratorio", ("%d de %d" % (ev, ev + pend)) if (ev + pend) else "—",
              ("los analiza laboratorio desde su sección" if (ev + pend) else "sin ingresos hoy"), "")
    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ resultados
def _resultados(ctx):
    """Cómo viene el mes contra los anteriores, y en cuánto cierra al ritmo de hoy."""
    st.markdown("#### 📊 Cómo viene el mes")
    hoy = date.today()
    n_meses = st.slider("Meses a comparar", 2, 12, 4, step=1, key="ef_res_meses",
                        help="Se comparan los últimos meses completos contra el mes en curso.")
    df = _historico(ctx["conn_factory"], max(6, n_meses))
    if df is None:
        st.caption("No pude leer el histórico de efluentes.")
        return
    if df.empty:
        st.info("Todavía no hay ingresos de efluente para comparar.")
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
    c1.bar_chart(por_mes, x="mes", y="TN", use_container_width=True, color="#0284c7")

    d3 = d2.copy()
    d3["sem"] = ((d3["dia"] - 1) // 7 + 1).clip(upper=5)
    sem_hoy = min(5, (hoy.day - 1) // 7 + 1)
    sem = c2.selectbox("Semana del mes", [1, 2, 3, 4, 5], index=sem_hoy - 1, key="ef_res_sem",
                       help="1 = días 1-7 · 2 = 8-14 · 3 = 15-21 · 4 = 22-28 · 5 = 29-31.")
    ds = d3[d3["sem"] == sem].groupby("mes", as_index=False)["tn"].sum().sort_values("mes")
    ds["TN"] = ds["tn"].round(1)
    if ds.empty:
        c2.info("Sin datos en esa semana.")
    else:
        c2.bar_chart(ds, x="mes", y="TN", use_container_width=True, color="#0284c7")
        c2.caption(f"Misma semana ({sem}ª) de cada mes, para comparar contra el mismo tramo.")


# ------------------------------------------------------------------ modos
def _modo_camiones(ctx):
    c1, c2 = st.columns(2)
    desde = c1.date_input("Desde", value=date.today().replace(day=1), key="ef_cam_desde", format="DD/MM/YYYY")
    hasta = c2.date_input("Hasta", value=date.today(), key="ef_cam_hasta", format="DD/MM/YYYY")
    df = _camiones(ctx["conn_factory"], desde, hasta)
    if df is None:
        st.warning("No pude leer los ingresos de portería.")
        return
    if df.empty:
        st.info("Sin camiones de efluente líquido en el rango.")
        return
    clis = sorted(df["cliente"].dropna().astype(str).str.strip().unique().tolist())
    sel = st.multiselect("Cliente (vacío = todos)", clis, key="ef_cam_cli")
    if sel:
        df = df[df["cliente"].astype(str).str.strip().isin(sel)]
    tot = float(df["kg"].sum() or 0)
    _falta_stock = int((~df["en_stock"].fillna(False).astype(bool)).sum())
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Camiones", len(df))
    m2.metric("TN netas", f"{tot/1000:,.1f}")
    m3.metric("TN por camión", f"{(tot/len(df))/1000:,.2f}" if len(df) else "—")
    m4.metric("Sin análisis de lab",
              int((df["evaluado"].fillna("NO").astype(str).str.upper() != "SI").sum()),
              help="Los carga laboratorio desde su propia sección. Acá es sólo información.")
    m5.metric("Sin registrar en stock", _falta_stock,
              help="Cada camión de efluente se registra solo como entrada a piletas en el libro de stock; "
                   "la sincronización corre cada 15 minutos.")
    dm = df.copy()
    dm["mes"] = pd.to_datetime(dm["fecha"]).dt.to_period("M").astype(str)
    por_mes = dm.groupby("mes")["kg"].sum().div(1000).round(1).reset_index().rename(columns={"kg": "TN"})
    if len(por_mes) > 1:
        st.bar_chart(por_mes, x="mes", y="TN", use_container_width=True)
    df = df.copy()
    df["_res"] = df.apply(
        lambda r: ("❌ RECHAZADO" if str(r.get("lab_rechazado") or "").upper().startswith("RECHAZ")
                   else ("✅ " + str(r.get("lab_calidad") or "OK")
                         if str(r.get("evaluado") or "").upper() == "SI" else "⏳ sin analizar")), axis=1)
    vista = df.rename(columns={"ticket": "Ticket", "fecha": "Fecha", "hora": "Hora", "cliente": "Cliente",
                               "procedencia": "Procedencia", "transporte": "Transporte",
                               "patente_chasis": "Chasis", "patente_acoplado": "Acoplado",
                               "kg": "Kg", "_res": "Resultado lab", "lab_num_muestra": "Nº muestra",
                               "en_stock": "En stock"})
    _cols = [c for c in ["Ticket", "Fecha", "Hora", "Cliente", "Procedencia", "Transporte",
                         "Chasis", "Acoplado", "Kg", "Resultado lab", "Nº muestra", "En stock"]
             if c in vista.columns]
    vista = vista[_cols]
    st.dataframe(vista, use_container_width=True, hide_index=True, height=420)
    st.download_button("⬇️ Descargar CSV", vista.to_csv(index=False).encode("utf-8"),
                       file_name=f"efluentes_{desde}_{hasta}.csv", mime="text/csv", key="ef_cam_csv")
    _flujo(ctx)


def _flujo(ctx):
    """Las piletas como proceso: entra efluente, sale AG recuperado."""
    st.markdown("#### 🕳️ Qué pasa con ese efluente en las piletas")
    fl = _flujo_piletas(ctx["conn_factory"])
    if fl is None or fl.empty:
        st.caption("Todavía no hay movimientos de piletas para mostrar.")
        return
    v = fl.rename(columns={"mes": "Mes", "camiones_efluente": "Camiones efluente",
                           "efluente_tn": "Efluente (TN)", "camiones_ag": "Camiones AG",
                           "ag_recuperado_tn": "AG recuperado (TN)", "rendimiento_pct": "Recuperado %"})
    st.dataframe(v, use_container_width=True, hide_index=True)
    st.caption("Cada camión de efluente entra al libro de stock como **entrada a piletas**; lo que vuelve a salir "
               "con valor es el **AG recuperado** que se manda a acopio. El resto es agua a tratar: las piletas no "
               "guardan inventario, por eso este cuadro se lee como flujo del mes y no como saldo.")


# ------------------------------------------------------------------ pantalla
def render_sector_efluentes(ctx, sec):
    from .portada import _hero, _pie_soporte

    USR = ctx["USR"]
    _hero(f"SECTOR {sec['nombre_ui'].upper()}", USR, icono=sec.get("icono") or "💧",
          sub="Efluentes líquidos: camiones ingresados y el resultado del laboratorio. Sólo consulta.")
    _indicadores(ctx)
    _resultados(ctx)
    st.divider()
    st.markdown("#### 🚛 Camiones ingresados")
    _modo_camiones(ctx)
    st.caption("Este sector muestra únicamente efluentes líquidos (DISPOSICION FINAL DE LIQUIDOS) y es de "
               "**sólo lectura**: los análisis los carga **Laboratorio** desde su propia sección. Acá se "
               "consulta lo que ya evaluó.")
    _pie_soporte(ctx)
    return True
