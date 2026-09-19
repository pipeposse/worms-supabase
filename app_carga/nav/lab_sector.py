# -*- coding: utf-8 -*-
"""Laboratorio del sector — SÓLO CONSULTA.

Pedido de dirección (15/09/2026): "laboratorio en cada sección tiene que reportar la
calidad de los productos de esa sección; no es para cargar ni para editar datos, es
para los operarios de planta".

Antes, la tarjeta Laboratorio de cada sector abría la sección clásica de Laboratorio
entera: todos los productos de la planta y, peor, los formularios de alta y edición.
Un operario de Reactores veía —y podía tocar— los análisis de efluentes.

Acá no hay un solo botón que escriba: se lee produccion.v_lab_sector, que atribuye cada
análisis a un sector por el TANQUE analizado y, si no tiene tanque, por la familia de
producto que ese sector maneja (los productos de sus tanques).
"""

import io

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

# parámetro que mira cada familia: no tiene sentido mostrarle acidez a un efluente
_PARAMS = {
    "AFE":      [("prc_acidez", "Acidez %"), ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %"),
                 ("ppm_azufre", "Azufre ppm"), ("ppm_fosforo", "Fósforo ppm")],
    "AG":       [("prc_acidez", "Acidez %"), ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %"),
                 ("ppm_azufre", "Azufre ppm")],
    "ARE":      [("prc_acidez", "Acidez %"), ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %"),
                 ("prc_producto", "Producto %")],
    "BORRA":    [("borra_prc_grasa", "Grasa %"), ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %")],
    "EMULSION": [("prc_emulsion", "Emulsión %"), ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %")],
    "GLICERINA": [("gli_glicerol", "Glicerol %"), ("prc_agua", "Agua %")],
    "DISPOSICION FINAL DE LIQUIDOS": [("eflu_ph", "pH"), ("eflu_prc_grasa", "Grasa %"),
                                      ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %")],
}
_PARAMS_DEF = [("prc_acidez", "Acidez %"), ("prc_agua", "Agua %"), ("prc_sedimentos", "Sed. %")]
_OK = ("ACEPTADO",)
_RESULTADO = {"ACEPTADO": "✅ Aceptado", "RECHAZADO": "⛔ Rechazado",
              "FUERA DE ESPECIFICACION": "⚠️ Fuera de especificación",
              "REMUESTREO": "🔁 A remuestrear", "SIN DATO": "— sin resultado"}


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _leer(_cf, sector, desde, hasta):
    sql = ("SELECT fecha, dia, ticket, num_muestra, familia_lab, producto_lab, calidad, estado, "
           "corriente, empleado, tanque, conclusion, prc_acidez, prc_agua, prc_sedimentos, "
           "prc_producto, prc_emulsion, ppm_azufre, ppm_fosforo, densidad__g_ml, "
           "eflu_ph, eflu_prc_grasa, borra_prc_grasa, gli_glicerol "
           "FROM produccion.v_lab_sector WHERE sector = %s AND dia BETWEEN %s AND %s "
           "ORDER BY fecha DESC")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde, hasta))
        for c in df.columns:
            if c.startswith(("prc_", "ppm_", "eflu_", "borra_", "gli_")) or c == "densidad__g_ml":
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception:
        return None


def invalidar():
    _leer.clear()


def _fmt(x, d=2):
    return "" if x is None or pd.isna(x) else f"{float(x):,.{d}f}".replace(",", ".")


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _tabla(ctx, sec):
    cod = sec["codigo"]
    desde, hasta, etiqueta = _per.selector(f"lab_{cod}")
    df = _leer(ctx["conn_factory"], cod, desde, hasta)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if df.empty:
        st.info(f"No hay análisis de laboratorio de {sec['nombre_ui']} en {etiqueta}.")
        return

    fams = sorted(df["familia_lab"].dropna().unique().tolist())
    c1, c2, c3 = st.columns([2.4, 1.6, 0.5])
    k_f = f"lab_fam_{cod}"
    if st.session_state.get(k_f) not in (["TODOS"] + fams):
        st.session_state[k_f] = "TODOS"
    fam = c1.radio("Producto", ["TODOS"] + fams, horizontal=True, key=k_f,
                   label_visibility="collapsed",
                   format_func=lambda f: "Todos" if f == "TODOS" else f.title())
    solo_mal = c2.toggle("Sólo lo que no dio bien", key=f"lab_mal_{cod}",
                         help="Rechazado, fuera de especificación o a remuestrear.")
    if c3.button("↻", key=f"lab_ref_{cod}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()

    v = df if fam == "TODOS" else df[df["familia_lab"] == fam]
    _mal = ~v["estado"].fillna("").isin(_OK)
    if solo_mal:
        v = v[_mal]

    n = len(df if fam == "TODOS" else df[df["familia_lab"] == fam])
    n_ok = int((df["estado"].fillna("").isin(_OK)).sum())
    pct = 100.0 * n_ok / len(df) if len(df) else 0.0
    _ult = pd.to_datetime(df["fecha"]).max()
    k1 = _kpi("Análisis del período", str(len(df)), f"{etiqueta} · {len(fams)} producto(s)", "")
    k2 = _kpi("En especificación", f"{pct:.0f}<span style='font-size:1rem;font-weight:700;'> %</span>",
              f"{n_ok} de {len(df)} aceptados por laboratorio", "ok" if pct >= 95 else ("warn" if pct >= 85 else "bad"))
    _nm = int((~df["estado"].fillna("").isin(_OK)).sum())
    k3 = _kpi("No conformes", str(_nm),
              "rechazados, fuera de especificación o a remuestrear" if _nm else "ninguno en el período",
              "bad" if _nm else "ok")
    k4 = _kpi("Último análisis", _ult.strftime("%d/%m %H:%M") if pd.notna(_ult) else "—",
              (df.iloc[0]["producto_lab"] or "") + (f" · {df.iloc[0]['tanque']}" if df.iloc[0]["tanque"] else ""), "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    if v.empty:
        st.success("Todos los análisis del período dieron dentro de especificación.")
        return

    cols = _PARAMS.get(fam, None)
    if cols is None:                       # con "Todos" se muestran los parámetros más comunes
        cols = _PARAMS_DEF
    tabla = pd.DataFrame({
        "FECHA": v["fecha"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if pd.notna(t) else ""),
        "#TICKET": v["ticket"].fillna(""),
        "PRODUCTO": v["producto_lab"].fillna(""),
        "CALIDAD": v["calidad"].fillna("—"),
        "RESULTADO": v["estado"].map(lambda e: _RESULTADO.get(str(e).upper(), f"⚠️ {e}")),
        "TANQUE": v["tanque"].fillna("—"),
    })
    for c, lbl in cols:
        if c in v.columns:
            tabla[lbl.upper()] = v[c].map(_fmt)
    tabla["QUIÉN"] = v["empleado"].fillna("")
    st.dataframe(tabla, hide_index=True, use_container_width=True,
                 height=min(620, 60 + 35 * len(tabla)))

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name="Laboratorio")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"lab_{cod.lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"lab_xls_{cod}")


def _ir_lab_clasico():
    st.session_state.section = "LAB"


def render_lab(ctx, sec):
    c1, c2 = st.columns([3, 1.3])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>🧪 Laboratorio · {sec['nombre_ui']} · "
                "calidad de los productos del sector</div>", unsafe_allow_html=True)
    # Cargar y corregir análisis sigue siendo de Laboratorio: el botón aparece sólo si la
    # persona tiene esa sección habilitada. El operario de planta no lo ve.
    if ctx["puede_seccion"]("LAB"):
        c2.button("🧪 Cargar análisis (Laboratorio)", key=f"lab_ir_{sec['codigo']}",
                  use_container_width=True, on_click=_ir_lab_clasico,
                  help="Sección de Laboratorio: alta y edición de análisis.")
    _tabla(ctx, sec)
    st.caption("Pantalla de consulta: acá no se carga ni se corrige nada. Los análisis los hace y los "
               "edita Laboratorio; si ves un resultado raro o falta uno, avisales. "
               "Se muestran los análisis hechos sobre tanques de este sector y, cuando el análisis no "
               "tiene tanque, los de los productos que este sector maneja.")
