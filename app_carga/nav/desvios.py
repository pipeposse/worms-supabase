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


def render_desvios(ctx, sec):
    hoy = date.today()
    anio, semana = st.session_state.get("nav_dv_semana") or _semana(hoy)
    c1, c2, c3, c4 = st.columns([0.6, 2.6, 0.6, 1])
    if c1.button("◀", key="nav_dv_prev", use_container_width=True):
        st.session_state["nav_dv_semana"] = _semana(_lunes(anio, semana) - timedelta(days=7)); st.rerun()
    c2.markdown(f"<div class='section-title' style='margin:6px 0'>⚠️ Desvíos · {sec['nombre_ui']} · semana {semana} / {anio}</div>",
                unsafe_allow_html=True)
    if c3.button("▶", key="nav_dv_next", use_container_width=True):
        st.session_state["nav_dv_semana"] = _semana(_lunes(anio, semana) + timedelta(days=7)); st.rerun()
    if c4.button("Hoy", key="nav_dv_hoy", use_container_width=True):
        st.session_state["nav_dv_semana"] = _semana(hoy); st.rerun()
    _tabla(ctx, sec, anio, semana)
