# -*- coding: utf-8 -*-
"""Acopio de un sector: SUS tanques, SU disponibilidad, SUS productos.

Pedido de dirección (15/09/2026): "en acopio por sector también, mostrar disponibilidad
de los tanques y productos que use cada sector, no mezclar información entre sectores".

Antes, la tarjeta Acopio de cada sector abría la sección clásica de Tanques entera: los
126 tanques de la planta, sin filtro. El operario de Bachas veía las plataformas de
exportación y las piletas de efluentes.

Acá el sector sale del TANQUE (dim_tanque.sector contra dim_sector_nav.patron_tanques),
igual que en Stock y en Laboratorio: no hay un texto que alguien pueda cargar mal.
Sale todo de produccion.v_acopio_sector.

Dos disponibilidades, que no son lo mismo y por eso van separadas:
  · LUGAR LIBRE  = capacidad − lo que hay dentro   → dónde puedo descargar.
  · DISPONIBLE   = lo que hay dentro − lo comprometido en órdenes de venta confirmadas
                   → qué puedo sacar o procesar hoy.
Todo en toneladas: los litros se pasan a kilos con la densidad del producto del tanque.
"""

import io

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from .kpis import _FRAGMENT, _TTL, _kpi, _n, _i, _rerun_fragment

_GRUPO_LBL = {"MP": "Materia prima", "INSUMO": "Insumos", "PT": "Producto terminado", "OTRO": "Otros"}
_COND_ICO = {"EN USO": "🟢", "FUERA DE USO": "⛔", "EN LIMPIEZA": "🧽", "EN REPARACION": "🔧"}
_NUM = ("cap_l", "act_l", "libre_l", "comp_l", "disp_l",
        "cap_tn", "act_tn", "libre_tn", "comp_tn", "disp_tn", "pct_ocupado", "antiguedad_min",
        "movs_sin_conciliar", "delta_sin_conciliar_tn")


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _leer(_cf, sector):
    sql = ("SELECT id_tanque, tanque_codigo, tanque, grupo_fisico, tipo_tanque, producto, "
           "producto_codigo, grupo, densidad, cap_l, act_l, libre_l, comp_l, disp_l, "
           "cap_tn, act_tn, libre_tn, comp_tn, disp_tn, pct_ocupado, condicion, activo, "
           "confianza, ultima_medicion, antiguedad_min, movs_sin_conciliar, "
           "delta_sin_conciliar_tn, metodo_medicion "
           "FROM produccion.v_acopio_sector WHERE sector = %s "
           "ORDER BY grupo_fisico, tanque")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
        for c in _NUM:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        df["activo"] = df["activo"].fillna(False).astype(bool)
        df["producto"] = df["producto"].fillna("(vacío / sin producto)")
        df["grupo"] = df["grupo"].fillna("OTRO")
        # hora de planta (pandas devuelve UTC: la última medición salía 3 h adelantada)
        try:
            _t = pd.to_datetime(df["ultima_medicion"], errors="coerce")
            if getattr(_t.dt, "tz", None) is not None:
                _t = _t.dt.tz_convert("America/Argentina/Buenos_Aires").dt.tz_localize(None)
            df["ultima_medicion"] = _t
        except Exception:
            pass
        return df
    except Exception:
        return None


def invalidar():
    _leer.clear()


# ------------------------------------------------------------------ helpers
def _tn(x, cero="—"):
    """Toneladas con un decimal. El cero se escribe "—": una celda en blanco se lee como
    "no hay dato" y acá cero es un dato (no queda lugar / no hay producto)."""
    if x is None or pd.isna(x) or abs(float(x)) < 0.05:
        return cero
    return f"{float(x):,.1f}"


def _edad(m):
    """Antigüedad de la última medición, en palabras de planta."""
    m = float(m or 0)
    if m <= 0:
        return "sin medición"
    if m < 90:
        return f"hace {int(m)} min"
    if m < 60 * 36:
        return f"hace {int(m // 60)} h"
    return f"hace {int(m // 1440)} días"


def _por_producto(df):
    """La respuesta a "qué tengo y cuánto lugar me queda", producto por producto."""
    g = df.groupby(["producto", "grupo"], as_index=False).agg(
        TANQUES=("id_tanque", "count"), EN_TANQUE=("act_tn", "sum"), COMP=("comp_tn", "sum"),
        DISP=("disp_tn", "sum"), LIBRE=("libre_tn", "sum"), CAP=("cap_tn", "sum"))
    g = g.sort_values("DISP", ascending=False)
    out = pd.DataFrame({
        "PRODUCTO": g["producto"],
        "TIPO": g["grupo"].map(lambda x: _GRUPO_LBL.get(x, x)),
        "TANQUES": g["TANQUES"].astype(int).astype(str),
        "EN TANQUE TN": g["EN_TANQUE"].map(_tn),
        "COMPROMETIDO TN": g["COMP"].map(_tn),
        "DISPONIBLE TN": g["DISP"].map(_tn),
        "LUGAR LIBRE TN": g["LIBRE"].map(_tn),
        "% OCUPADO": [f"{100.0 * a / c:,.0f}%" if c else "—"
                      for a, c in zip(g["EN_TANQUE"], g["CAP"])],
    })
    return out


def _tabla_tanques(df):
    return pd.DataFrame({
        "TANQUE": df["tanque"].fillna(""),
        "DÓNDE": df["grupo_fisico"].fillna(""),
        "PRODUCTO": df["producto"],
        "TIPO": df["grupo"].map(lambda x: _GRUPO_LBL.get(x, x)),
        "EN TANQUE TN": df["act_tn"].map(_tn),
        "COMPROMETIDO TN": df["comp_tn"].map(_tn),
        "DISPONIBLE TN": df["disp_tn"].map(_tn),
        "LUGAR LIBRE TN": df["libre_tn"].map(_tn),
        "CAPACIDAD TN": df["cap_tn"].map(_tn),
        "% OCUPADO": df["pct_ocupado"].map(lambda v: f"{float(v):,.0f}%" if v else "0%"),
        "ESTADO": [f"{_COND_ICO.get(c, '•')} {str(c).capitalize()}" for c in df["condicion"].fillna("—")],
        "ÚLTIMA MEDICIÓN": [(pd.to_datetime(t).strftime("%d/%m %H:%M") + f" · {_edad(m)}") if pd.notna(t) else "sin medición"
                            for t, m in zip(df["ultima_medicion"], df["antiguedad_min"])],
        # Movimientos cargados DESPUÉS de la última medición: el número de arriba es la
        # medición física, así que esto avisa que el tanque ya no está en ese valor.
        "MOVIDO DESPUÉS DE MEDIR": [("" if not int(n or 0) else f"{int(n)} mov · {float(d):+,.1f} TN")
                                    for n, d in zip(df["movs_sin_conciliar"], df["delta_sin_conciliar_tn"])],
    })


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _acopio(ctx, sec):
    cod = sec["codigo"]
    df = _leer(ctx["conn_factory"], cod)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if df.empty:
        st.info(f"{sec['nombre_ui']} no tiene tanques asociados. El acopio de este sector no se lleva por tanque.")
        return

    # Los tanques fuera de uso no cuentan para la disponibilidad: no se puede descargar ahí.
    fuera = df[(~df["activo"]) | (df["condicion"] == "FUERA DE USO")]
    v = df.drop(fuera.index)

    grupos = [g for g in ("MP", "INSUMO", "PT", "OTRO") if (v["grupo"] == g).any()]
    prods = sorted(v["producto"].unique().tolist())

    f1, f2, f3, f4 = st.columns([1.9, 1.7, 1.5, 0.5])
    k_g = f"acp_grupo_{cod}"
    opciones = (["TODOS"] + grupos) if len(grupos) > 1 else grupos
    grupo = "TODOS"
    if opciones:
        if st.session_state.get(k_g) not in opciones:
            st.session_state[k_g] = opciones[0]
        grupo = f1.radio("Tipo", opciones, horizontal=True, key=k_g, label_visibility="collapsed",
                         format_func=lambda g: "Todo" if g == "TODOS" else _GRUPO_LBL.get(g, g))
    k_p = f"acp_prod_{cod}"
    if st.session_state.get(k_p) not in (["TODOS"] + prods):
        st.session_state[k_p] = "TODOS"
    prod = f2.selectbox("Producto", ["TODOS"] + prods, key=k_p, label_visibility="collapsed",
                        format_func=lambda p: "Todos los productos" if p == "TODOS" else p)
    solo_lugar = f3.toggle("Sólo con lugar libre", key=f"acp_lugar_{cod}",
                           help="Tanques donde todavía entra producto.")
    if f4.button("↻", key=f"acp_ref_{cod}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()

    # ---- indicadores del sector (sobre los tanques en uso, sin filtrar) ----
    cap, act = float(v["cap_tn"].sum()), float(v["act_tn"].sum())
    libre, comp, disp = float(v["libre_tn"].sum()), float(v["comp_tn"].sum()), float(v["disp_tn"].sum())
    pct = 100.0 * act / cap if cap else 0.0
    con_lugar = int((v["libre_tn"] >= 1.0).sum())
    k1 = _kpi("Lugar libre para descargar",
              f"{_n(libre)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{con_lugar} de {len(v)} tanques con lugar · {pct:.0f}% ocupado de {_n(cap)} TN",
              "bad" if pct >= 90 else ("warn" if pct >= 75 else "ok"))
    k2 = _kpi("Producto disponible",
              f"{_n(disp)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{_n(act)} TN en tanque" + (f" · {_n(comp)} TN comprometidas en órdenes de venta" if comp >= 0.05
                                           else " · nada comprometido"),
              "")
    _pp = v.groupby("producto")["act_tn"].sum().sort_values(ascending=False)
    _top = " · ".join(f"{p} {_n(t)} TN" for p, t in _pp.head(3).items() if t >= 0.05) or "sin producto en tanque"
    k3 = _kpi("Productos del sector", str(int(v["producto"].nunique())), _top, "")
    viejas = int((v["antiguedad_min"] > 1440).sum())
    pend = int(v["movs_sin_conciliar"].gt(0).sum())
    k4 = _kpi("Confianza de la medición",
              f"{len(v) - viejas}<span style='font-size:1rem;font-weight:700;'>/{len(v)}</span>",
              (f"{viejas} tanque(s) sin medir hace más de un día" if viejas else "todos medidos en el último día")
              + (f" · {pend} con movimientos posteriores a la medición" if pend else ""),
              "bad" if viejas > len(v) / 3 else ("warn" if viejas else "ok"))
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    # ---- filtros aplicados ----
    w = v
    if grupo and grupo != "TODOS":
        w = w[w["grupo"] == grupo]
    if prod != "TODOS":
        w = w[w["producto"] == prod]
    if solo_lugar:
        w = w[w["libre_tn"] >= 1.0]
    if w.empty:
        st.info("Ningún tanque de este sector cumple con esos filtros.")
        return

    st.markdown("<div class='section-title' style='margin:10px 0 2px'>Disponibilidad por producto</div>",
                unsafe_allow_html=True)
    pp = _por_producto(w)
    st.dataframe(pp, hide_index=True, use_container_width=True, height=min(560, 60 + 35 * len(pp)),
                 column_config={"PRODUCTO": st.column_config.TextColumn(width="medium")})

    st.markdown("<div class='section-title' style='margin:14px 0 2px'>Tanque por tanque</div>",
                unsafe_allow_html=True)
    tt = _tabla_tanques(w.sort_values(["grupo_fisico", "act_tn"], ascending=[True, False]))
    st.dataframe(tt, hide_index=True, use_container_width=True, height=min(620, 60 + 35 * len(tt)),
                 column_config={"TANQUE": st.column_config.TextColumn(width="medium"),
                                "DÓNDE": st.column_config.TextColumn(width="medium"),
                                "PRODUCTO": st.column_config.TextColumn(width="medium")})

    if not fuera.empty:
        with st.expander(f"Tanques fuera de uso del sector ({len(fuera)}) — no cuentan para la disponibilidad",
                         expanded=False):
            st.dataframe(_tabla_tanques(fuera), hide_index=True, use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pp.to_excel(xw, index=False, sheet_name="Por producto")
        tt.to_excel(xw, index=False, sheet_name="Tanques")
        if not fuera.empty:
            _tabla_tanques(fuera).to_excel(xw, index=False, sheet_name="Fuera de uso")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"acopio_{cod.lower()}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"acp_xls_{cod}")


def _ir_tanques_clasico():
    st.session_state.section = "TANQUES"


def render_acopio(ctx, sec):
    c1, c2 = st.columns([3, 1.3])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>🛢️ Acopio · {sec['nombre_ui']} · "
                "tanques del sector y qué hay disponible</div>", unsafe_allow_html=True)
    if ctx["puede_seccion"]("TANQUES"):
        c2.button("📋 Tanques (vista clásica)", key=f"acp_ir_{sec['codigo']}", use_container_width=True,
                  on_click=_ir_tanques_clasico,
                  help="Sección de Tanques: toda la planta, mediciones y carga.")
    _acopio(ctx, sec)
    st.caption("Sólo los tanques de este sector: el sector sale del tanque, no de un texto. "
               "**Lugar libre** es capacidad menos lo que hay dentro (dónde se puede descargar); "
               "**Disponible** es lo que hay dentro menos lo comprometido en órdenes de venta confirmadas "
               "(lo que se puede sacar o procesar). Todo en toneladas: los litros se pasan a kilos con la "
               "densidad del producto de cada tanque. La medición la carga el operario o el sensor: si dice "
               "'sin medir hace más de un día', el número es viejo.")
