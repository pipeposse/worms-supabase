# -*- coding: utf-8 -*-
"""PARÁMETROS — qué tiene que dar cada producto líquido para ser de cada calidad.

Es la planilla de parámetros de dirección puesta en la app, sin planilla: sale de
produccion.dim_maestro_parametro a través de v_parametro_producto. Una fila por producto
con su calidad, y una columna por parámetro con el límite que corresponde.

Hay dos maneras distintas de tener calidad y conviene no mezclarlas:

  · En casi todas las familias la CALIDAD ES EL PRODUCTO. AG-A, AG-B, AG-C y AG-D son
    cuatro productos distintos del maestro, y el parámetro es el que decide cuál es: un
    ácido graso con más de 30% de acidez y más de 250 ppm de azufre es AG-C, no AG-B.
    Lo mismo con ARE, BORRA, GLICERINA y SEBO.

  · En la familia AFE no. El maestro tiene un solo AFE-S, y la calidad A, B, C o D la
    pone laboratorio con el azufre y el fósforo del tanque: se calcula el índice
    máx(azufre/50, fósforo/150) y según dónde cae sale la letra. Por eso el stock muestra
    V-AFE-S-A, V-AFE-S-C y V-AFE-S-D como cuentas separadas aunque el maestro tenga un
    solo AFE-S. Esa tabla va primero, porque es la que usa exportación todos los días.

"Se mide" en una celda significa que el análisis se hace y queda registrado, pero ese
parámetro no define la calidad del producto — no es que falte el dato.
"""

import io

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

# Orden de lectura de los parámetros: primero lo que define calidad en casi todos, después
# lo que se mide para trazabilidad. El que no esté en la lista va al final, alfabético.
_ORDEN = ["% ACIDEZ", "% H2O - SEDIMENTO & Gomas", "% H2O", "% SEDIMENTO", "% GOMAS",
          "PPM AZUFRE", "PPM FOSFORO", "% MATERIA GRASA", "% ALCALINIDAD", "PH",
          "% GLICEROL", "% GLICERINA EN CENTRIFUGADO", "% MONG", "% CENIZAS",
          "ÍNDICE DE YODO", "CONCENTRACIÓN", "DENSIDAD G/ML"]
_CORTO = {"% H2O - SEDIMENTO & Gomas": "% H2O+SED+GOMAS", "DENSIDAD G/ML": "DENSIDAD",
          "% GLICERINA EN CENTRIFUGADO": "% GLIC. CENTRIF.", "CONCENTRACIÓN": "CONCENTR."}
_FAM_NOMBRE = {"AFE": "AFE — aceites filtrados", "AG": "AG — ácidos grasos",
               "ARE": "ARE — ácido graso refinado", "BORRA": "BORRA",
               "GLICERINA": "GLICERINA", "SEBO": "SEBO", "EMULSION": "EMULSIÓN",
               "FONDO_TK": "FONDO DE TANQUE", "TCO": "TCO — maíz",
               "INSUMOS QUIMICOS": "Insumos químicos"}


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _leer(_cf):
    p = ("SELECT familia, producto, calidad, descripcion, rubro, corriente, parametro, "
         "especificacion, define_calidad, codigo_producto, es_liquido, nombre_producto, "
         "densidad_g_ml, calidad_la_define_lab FROM produccion.v_parametro_producto "
         "WHERE es_liquido")
    a = ("SELECT orden, calidad, indice, azufre_max_ppm, fosforo_max_ppm, que_significa "
         "FROM produccion.v_calidad_afe ORDER BY orden")
    f = ("SELECT d.codigo_producto, d.nombre_producto, d.tipo_producto "
         "FROM produccion.dim_producto d WHERE d.activo AND d.es_liquido "
         "AND NOT EXISTS (SELECT 1 FROM produccion.v_parametro_producto v "
         "                 WHERE v.codigo_producto = d.codigo_producto) "
         "ORDER BY d.codigo_producto")
    try:
        with _cf() as conn:
            return (pd.read_sql_query(p, conn), pd.read_sql_query(a, conn),
                    pd.read_sql_query(f, conn))
    except Exception:
        return None, None, None


def invalidar():
    _leer.clear()


def _celda(esp, define):
    """El límite tal cual lo escribió dirección. 'SI' no es un límite: es un análisis que se
    hace y se registra, pero que no decide la calidad."""
    t = (esp or "").strip()
    if not t:
        return "—"
    if not define:
        return "se mide"
    return t.replace("  ", " ")


def _tabla(df):
    """Una fila por producto y calidad, una columna por parámetro."""
    params = [c for c in _ORDEN if c in set(df["parametro"])]
    params += sorted(set(df["parametro"]) - set(params))
    filas = []
    for (fam, prod, cal, desc), g in df.groupby(
            ["familia", "producto", "calidad", "descripcion"], dropna=False, sort=False):
        # ojo: un NaN de pandas es "verdadero" en un if, así que hay que preguntarle a pandas
        _sin_cal = pd.isna(cal) or not str(cal).strip()
        fila = {"PRODUCTO": prod,
                "CALIDAD": (("A · B · C · D (la pone laboratorio)" if fam == "AFE" else "—")
                            if _sin_cal else str(cal)),
                "QUÉ ES": ("" if pd.isna(desc) else str(desc)).title()}
        _e = dict(zip(g["parametro"], zip(g["especificacion"], g["define_calidad"])))
        for p in params:
            v = _e.get(p)
            fila[_CORTO.get(p, p)] = _celda(v[0], v[1]) if v else "—"
        filas.append(fila)
    return pd.DataFrame(filas)


def render(cf):
    par, afe, faltan = _leer(cf)
    if par is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if par.empty:
        st.caption("Todavía no hay parámetros cargados en el maestro de productos.")
        return

    # ---------- la calidad del AFE: la que pone laboratorio ----------
    st.markdown("**Calidad del AFE — la define laboratorio con el azufre y el fósforo del tanque**")
    if afe is not None and not afe.empty:
        st.dataframe(pd.DataFrame({
            "CALIDAD": afe["calidad"],
            "ÍNDICE": afe["indice"],
            "AZUFRE ppm": afe["azufre_max_ppm"].map(
                lambda x: "—" if pd.isna(x) else f"hasta {float(x):,.0f}".replace(",", ".")),
            "FÓSFORO ppm": afe["fosforo_max_ppm"].map(
                lambda x: "—" if pd.isna(x) else f"hasta {float(x):,.0f}".replace(",", ".")),
            "QUÉ SIGNIFICA": afe["que_significa"],
        }), hide_index=True, use_container_width=True,
            column_config={"QUÉ SIGNIFICA": st.column_config.TextColumn(width="large")})
    st.caption("El índice es **el mayor entre azufre/50 y fósforo/150**, así que los dos límites "
               "tienen que cumplirse a la vez: con 40 ppm de azufre y 150 de fósforo el producto "
               "es C, no A. Se aplica a toda la familia AFE (AFE-S, AFE-SG, AFE-AL, AFE-M, AFE-G "
               "y AFE-P). Lo que laboratorio todavía no midió queda en **NO EVALUADO**, nunca sin "
               "calidad. Los límites de acá son los mismos que usa el sistema para clasificar: "
               "salen de la misma regla, no de una copia.")

    # ---------- todos los productos líquidos con sus parámetros ----------
    st.divider()
    fams = [f for f in _FAM_NOMBRE if f in set(par["familia"])]
    fams += sorted(set(par["familia"]) - set(fams))
    k = "nav_par_fam"
    opciones = ["TODAS"] + fams
    if st.session_state.get(k) not in opciones:
        st.session_state[k] = "TODAS"
    fam = st.radio("Familia", opciones, horizontal=True, key=k, label_visibility="collapsed",
                   format_func=lambda f: "Todas" if f == "TODAS" else _FAM_NOMBRE.get(f, f.title()),
                   help="La familia agrupa las calidades del mismo producto para poder "
                        "compararlas de arriba hacia abajo.")
    v = par if fam == "TODAS" else par[par["familia"] == fam]
    v = v.sort_values(["familia", "producto", "parametro"])
    tabla = _tabla(v)
    st.dataframe(tabla, hide_index=True, use_container_width=True,
                 height=min(620, 60 + 35 * len(tabla)),
                 column_config={"PRODUCTO": st.column_config.TextColumn(width="small"),
                                "CALIDAD": st.column_config.TextColumn(width="small"),
                                "QUÉ ES": st.column_config.TextColumn(width="small")})
    st.caption("Cada fila es un producto del maestro con su calidad; la celda es el límite que "
               "tiene que cumplir. **«Se mide»** quiere decir que el análisis se hace y queda "
               "registrado pero no define la calidad — no es que falte el dato. En AG, ARE, BORRA, "
               "GLICERINA y SEBO la calidad **es** el producto: el parámetro decide cuál de ellos "
               "es. En AFE hay un solo producto por origen y la letra la pone laboratorio con la "
               "tabla de arriba.")

    # ---------- lo que está en uso y todavía no tiene parámetros ----------
    if faltan is not None and not faltan.empty:
        _l = ", ".join(f"**{r.codigo_producto}**" + (f" ({r.nombre_producto})" if r.nombre_producto else "")
                       for r in faltan.itertuples())
        st.caption(f"⚠️ {len(faltan)} producto(s) líquidos están dados de alta y se mueven en la "
                   f"planta, pero todavía no tienen parámetros en el maestro: {_l}. Sin parámetros "
                   "no hay contra qué comparar el análisis, así que laboratorio no puede decir si "
                   "están dentro de especificación.")

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        _tabla(par.sort_values(["familia", "producto", "parametro"])).to_excel(
            xw, index=False, sheet_name="PARAMETROS")
        if afe is not None and not afe.empty:
            afe.to_excel(xw, index=False, sheet_name="CALIDAD AFE")
        if faltan is not None and not faltan.empty:
            faltan.to_excel(xw, index=False, sheet_name="SIN PARAMETROS")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(), file_name="parametros_productos.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="nav_par_xls")
