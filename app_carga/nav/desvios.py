# -*- coding: utf-8 -*-
"""Desvíos por OP (Fase 4b) — vista DESVIOS de un sector. SEGUIMIENTO PRODUCCIÓN, parte 3.

Tabla DESVÍOS del Excel de dirección: por OP, cada variable de la fórmula (MP, cada
insumo, acidez y temperatura de cada revisión, tiempo de cada etapa) con lo esperado,
lo real, el desvío y si quedó fuera de tolerancia. Nadie lo tipea: sale de
produccion.v_desvio_op (instructivo × mediciones del operario).
"""

import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi
from .plan_semanal import _semana, _lunes


@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer(_cf, sector, anio, semana):
    sql = ("SELECT id_batch, op, formula, version, fecha, estado, orden, variable, unidad, esperado, real, desvio, "
           "desvio_pct, tolerancia, fuera_tolerancia, medido FROM produccion.v_desvio_op "
           "WHERE sector_nav = %s AND anio_iso = %s AND semana_iso = %s ORDER BY fecha, id_batch, orden, variable")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, int(anio), int(semana)))
        for c in ("esperado", "real", "desvio", "desvio_pct"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        return df
    except Exception:
        return None


def _fmt(x, d=1):
    return "" if x is None or pd.isna(x) else f"{float(x):,.{d}f}"


@_FRAGMENT
def _tabla(ctx, sec, anio, semana):
    df = _leer(ctx["conn_factory"], sec["codigo"], anio, semana)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if df.empty:
        st.info("No hay OP con instructivo esta semana (los desvíos aparecen cuando la fórmula tiene pasos publicados "
                "y el operario carga lo real).")
        return
    med = df[df["medido"].fillna(False).astype(bool)]
    fuera = med[med["fuera_tolerancia"].fillna(False).astype(bool)]
    ops = df["id_batch"].nunique()
    ops_fuera = fuera["id_batch"].nunique()
    top = fuera["variable"].str.split(" · ").str[0].value_counts()
    c1 = _kpi("Fuera de tolerancia", str(len(fuera)), f"en {ops_fuera} de {ops} OP de la semana", "bad" if len(fuera) else "ok")
    c2 = _kpi("Variables medidas", f"{len(med)}<span style='font-size:1rem;font-weight:700;'> / {len(df)}</span>",
              "lo que cargó el operario contra lo formulado", "")
    c3 = _kpi("Más frecuente", (top.index[0] if len(top) else "—"),
              (f"{int(top.iloc[0])} desvíos" if len(top) else "sin desvíos fuera de tolerancia"), "warn" if len(top) else "")
    c4 = _kpi("OP sin desvíos", f"{ops - ops_fuera}<span style='font-size:1rem;font-weight:700;'> / {ops}</span>",
              "dentro de tolerancia en todo lo medido", "ok" if ops and ops == ops - ops_fuera else "")
    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}{c4}</div>', unsafe_allow_html=True)

    solo_med = st.toggle("Sólo variables medidas", value=True, key=f"nav_dv_med_{semana}")
    v = med if solo_med else df
    tabla = pd.DataFrame({
        "# OP": v["op"], "FECHA": v["fecha"].map(lambda d: pd.to_datetime(d).strftime("%d/%m")), "SEM": semana,
        "FÓRMULA": v["formula"].fillna("—") + " v" + v["version"].fillna(0).astype(int).astype(str),
        "#": v["orden"], "VARIABLE": v["variable"], "UN.": v["unidad"].fillna(""),
        "ESPERADO": v["esperado"].map(_fmt), "REAL": v["real"].map(_fmt),
        "DESVÍO": v["desvio"].map(lambda x: "" if pd.isna(x) else f"{x:+,.1f}"),
        "DESVÍO %": v["desvio_pct"].map(lambda x: "" if pd.isna(x) else f"{x:+.1f} %"),
        "TOLERANCIA": v["tolerancia"].fillna(""),
        "ESTADO": v.apply(lambda r: ("⚠️ Fuera" if bool(r["fuera_tolerancia"]) else ("✅ OK" if bool(r["medido"]) else "⚪ sin dato")), axis=1),
    })
    st.dataframe(tabla, hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name=f"Desvíos S{semana}")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(), file_name=f"desvios_{sec['codigo'].lower()}_S{semana}_{anio}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"nav_dv_xls_{semana}")
    st.caption("Esperado = formulación (versión con la que arrancó la OP) escalada a los kg de la OP. "
               "Real = lo que cargó el operario en el instructivo (la MP, si no se cargó, es la registrada en la producción). "
               "Tiempo: ± 15 % de la duración prevista.")


@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer_tanques(_cf, sector, desde, hasta):
    """Lo declarado que salió contra lo que bajó la medición física, tanque por tanque."""
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                "SELECT * FROM produccion.fn_desvio_tanque_periodo(%s, %s, %s)",
                conn, params=(sector, desde, hasta))
    except Exception:
        return None


def _tn(x, signo=False):
    if x is None or pd.isna(x):
        return ""
    v = float(x) / 1000.0
    return f"{v:+,.1f}" if signo else f"{v:,.1f}"


@_FRAGMENT
def _tabla_tanques(ctx, sec, desde, hasta, etiqueta):
    df = _leer_tanques(ctx["conn_factory"], sec["codigo"], desde, hasta)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if df.empty:
        st.info(f"No hay mediciones ni movimientos de {sec['nombre_ui']} en {etiqueta}.")
        return
    for c in ("kg_ini", "kg_fin", "entradas_kg", "salidas_kg", "salidas_ov_kg", "bajada_medida_kg", "desvio_kg"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["dias_sin_medir"] = pd.to_numeric(df["dias_sin_medir"], errors="coerce").fillna(0).astype(int)

    declarado = float(df["salidas_kg"].sum())
    bajada = float(df["bajada_medida_kg"].sum())
    dif = bajada - declarado
    atrasados = int((df["dias_sin_medir"] >= 2).sum())
    k1 = _kpi("Salió según el sistema", f"{_tn(declarado)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"órdenes de venta y consumos cargados · {etiqueta}", "")
    k2 = _kpi("Bajó del tanque (medido)", f"{_tn(bajada)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              "diferencia entre las dos mediciones físicas, ya descontadas las entradas", "")
    k3 = _kpi("Diferencia", f"{_tn(dif, signo=True)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              ("bajó más de lo declarado" if dif > 0 else ("bajó menos de lo declarado" if dif < 0 else "cierra")),
              "bad" if abs(dif) > 0.05 * max(declarado, 1) else "ok")
    k4 = _kpi("Tanques sin medir al día", str(atrasados),
              ("la medición es manual: mientras no se mida, la diferencia no es real"
               if atrasados else "todos con medición dentro del período"), "warn" if atrasados else "ok")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    solo_dif = st.toggle("Sólo los que no cierran", value=True, key=f"nav_dvt_dif_{sec['codigo']}",
                         help="Esconde los tanques cuya diferencia es menor a 1 TN.")
    v = df[df["desvio_kg"].abs() >= 1000] if solo_dif else df
    if v.empty:
        st.success("Todos los tanques cierran dentro de 1 TN entre lo declarado y lo medido.")
        return
    tabla = pd.DataFrame({
        "TANQUE": v["tanque"], "PRODUCTO": v["producto"].fillna("—"),
        "MEDICIÓN INICIAL": v["medicion_ini"].map(lambda t: pd.to_datetime(t).strftime("%d/%m %H:%M") if pd.notna(t) else "sin medición"),
        "TN INICIAL": v["kg_ini"].map(_tn),
        "MEDICIÓN FINAL": v["medicion_fin"].map(lambda t: pd.to_datetime(t).strftime("%d/%m %H:%M") if pd.notna(t) else "sin medición"),
        "TN FINAL": v["kg_fin"].map(_tn),
        "ENTRÓ TN": v["entradas_kg"].map(_tn),
        "SALIÓ S/SISTEMA TN": v["salidas_kg"].map(_tn),
        "DE ESO, ÓRDENES DE VENTA TN": v["salidas_ov_kg"].map(_tn),
        "BAJÓ MEDIDO TN": v["bajada_medida_kg"].map(_tn),
        "DIFERENCIA TN": v["desvio_kg"].map(lambda x: _tn(x, signo=True)),
        "DÍAS SIN MEDIR": v["dias_sin_medir"],
    })
    st.dataframe(tabla, hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name="Declarado vs medido")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"desvios_{sec['codigo'].lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_dvt_xls_{sec['codigo']}")
    st.caption("La comparación se hace entre las DOS MEDICIONES REALES del tanque, no contra el borde del período: "
               "la medición es manual y puede demorar, así que se muestran la fecha de cada una y los días sin medir. "
               "BAJÓ MEDIDO = medición inicial + lo que entró − medición final. DIFERENCIA = bajó medido − lo declarado: "
               "positiva, salió más de lo que figura cargado; negativa, se cargó una salida que el tanque todavía no acusa.")


def render_desvios(ctx, sec):
    """Desvíos del sector. En Exportación (y en cualquier sector con tanques) lo primero
    es lo declarado contra lo que bajó el tanque; los desvíos de fórmula van después."""
    st.markdown(f"<div class='section-title' style='margin:6px 0'>⚠️ Desvíos · {sec['nombre_ui']}</div>",
                unsafe_allow_html=True)
    desde, hasta, etiqueta = _per.selector(f"dv_{sec['codigo']}")
    con_tanques = bool(sec.get("patron_tanques"))
    if con_tanques:
        st.markdown('<div class="section-title">Lo que salió según el sistema vs. lo que bajó el tanque</div>',
                    unsafe_allow_html=True)
        _tabla_tanques(ctx, sec, desde, hasta, etiqueta)
    if sec.get("sector_batch"):
        anio, semana = _semana(hasta)
        with st.expander(f"Desvíos de fórmula por producción · semana {semana} / {anio}", expanded=not con_tanques):
            _tabla(ctx, sec, anio, semana)
