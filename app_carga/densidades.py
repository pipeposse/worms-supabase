# -*- coding: utf-8 -*-
"""⚖️ Densidades — catálogo único de densidades de los líquidos, visible y editable.

La densidad (g/ml = kg/L) es la que usa TODO el sistema para pasar de litros a
kilos: el armador de despachos, la asignación AFE, el balance, los informes de
stock y las reacciones. Acá se ven todas juntas y se corrigen en un solo lugar
(dim_producto.densidad_g_ml para productos, dic_insumo.densidad_g_ml para
insumos). Cada cambio queda auditado.

render(USR, cat, conectar)
"""
import pandas as pd
import streamlit as st

_DEF = 0.91   # default que usa densidad_de() cuando falta el dato


def _familia(c):
    c = str(c).upper()
    for p in ("AFE", "ARE", "AG", "BORRA", "SEBO", "GLICERINA", "CAUCHO", "AGUA"):
        if c == p or c.startswith(p + "-") or c.startswith(p + "("):
            return p
    return "OTROS"


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except Exception:
        return None


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#1e3a8a,#3b82f6);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>⚖️ Densidades</div>"
        "<div style='color:#dbeafe;font-size:.88rem;margin-top:3px'>La densidad (g/ml = kg/L) "
        "con la que el sistema convierte litros ↔ kilos en despachos, asignación, balance, "
        "stock y reacciones. Un solo catálogo, editable acá.</div></div>",
        unsafe_allow_html=True)

    df = cat("SELECT codigo_producto, nombre_producto, densidad_g_ml, activo "
             "FROM produccion.dim_producto ORDER BY codigo_producto")
    if df is None or df.empty:
        st.info("Sin productos en el maestro.")
        return
    df = df.copy()
    df["densidad_g_ml"] = pd.to_numeric(df["densidad_g_ml"], errors="coerce")
    df["fam"] = df["codigo_producto"].map(_familia)

    _solo_act = st.toggle("Solo productos activos", value=True, key="dns_act")
    v = df[df["activo"].fillna(False)] if _solo_act else df
    _con = v[v["densidad_g_ml"].notna()]
    _sin = v[v["densidad_g_ml"].isna()]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Productos", "%d" % len(v))
    k2.metric("Con densidad", "%d" % len(_con))
    k3.metric("Sin densidad", "%d" % len(_sin),
              help="Usan el default %.2f al convertir litros↔kg. Si alguno es un líquido "
                   "que se mueve por tanques, cargale la densidad real." % _DEF)
    _afem = df[df["codigo_producto"] == "AFE-M"]
    k4.metric("AFE-M", ("%.3f" % float(_afem.iloc[0]["densidad_g_ml"]))
              if not _afem.empty and pd.notna(_afem.iloc[0]["densidad_g_ml"]) else "⚠️ falta")
    if not _sin.empty:
        st.warning("Sin densidad cargada (convierten con el default %.2f): %s"
                   % (_DEF, ", ".join(_sin["codigo_producto"].tolist())))

    _fams = ["Todas"] + sorted(v["fam"].unique().tolist())
    _fsel = st.segmented_control("Familia", _fams, default="Todas", key="dns_fam") \
        if hasattr(st, "segmented_control") else st.radio("Familia", _fams, horizontal=True,
                                                          key="dns_fam")
    _v = v if (_fsel or "Todas") == "Todas" else v[v["fam"] == _fsel]

    _base = pd.DataFrame({
        "Código": _v["codigo_producto"].astype(str),
        "Producto": _v["nombre_producto"].fillna("").astype(str),
        "Densidad (g/ml)": _v["densidad_g_ml"],
    })
    ed = st.data_editor(
        _base, hide_index=True, use_container_width=True,
        key="dns_ed_%s" % (_fsel or "Todas"), num_rows="fixed",
        disabled=["Código", "Producto"],
        column_config={
            "Densidad (g/ml)": st.column_config.NumberColumn(
                format="%.3f", min_value=0.5, max_value=1.6, step=0.005,
                help="g/ml = kg/L. Referencias de planta: AFE 0.89 · AG 0.92 · ARE 0.94 · "
                     "borra 0.95 · sebo 0.91 · glicerina 1.26. Vacío = usa el default %.2f."
                % _DEF),
        })

    _cambios = []
    for _i in range(len(ed)):
        _cod = str(ed.iloc[_i]["Código"])
        _nva = _num(ed.iloc[_i]["Densidad (g/ml)"])
        _fila = _v[_v["codigo_producto"] == _cod]
        _vja = _num(_fila.iloc[0]["densidad_g_ml"]) if not _fila.empty else None
        if _nva != _vja:
            _cambios.append((_cod, _vja, _nva))

    c1, c2 = st.columns([1.2, 2.8])
    if c1.button("💾 Guardar densidades", type="primary", key="dns_save",
                 disabled=(not _cambios)):
        try:
            with conectar(USR["id_usuario"]) as (conn, _a):
                with conn.cursor() as cur:
                    for _cod, _vja, _nva in _cambios:
                        cur.execute("UPDATE produccion.dim_producto SET densidad_g_ml=%s, "
                                    "actualizado_en=now() WHERE codigo_producto=%s",
                                    (_nva, _cod))
                        _a.log("DENSIDAD", "dim_producto", _cod,
                               {"antes": _vja, "ahora": _nva})
            cat.clear()
            st.success("✅ %d densidad(es) actualizada(s): %s. Rige desde ya en todas las "
                       "pantallas que convierten litros↔kg."
                       % (len(_cambios),
                          ", ".join("%s %s→%s" % (c, ("%.3f" % a) if a is not None else "—",
                                                  ("%.3f" % n) if n is not None else "—")
                                    for c, a, n in _cambios)))
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)
    if _cambios:
        c2.caption("✏️ %d cambio(s) sin guardar: %s"
                   % (len(_cambios), ", ".join(c for c, _, _ in _cambios)))
    else:
        c2.caption("Editá la columna *Densidad* y apretá Guardar. Los cambios NO tocan "
                   "las densidades medidas por laboratorio tanque por tanque: esto es el "
                   "valor de catálogo del producto.")

    # ---------- insumos ----------
    with st.expander("🧪 Densidades de insumos (dic_insumo)"):
        ins = cat("SELECT codigo, descripcion, unidad, densidad_g_ml FROM produccion.dic_insumo "
                  "WHERE activo ORDER BY codigo")
        if ins is None or ins.empty:
            st.caption("Sin insumos activos.")
        else:
            ins = ins.copy()
            ins["densidad_g_ml"] = pd.to_numeric(ins["densidad_g_ml"], errors="coerce")
            _bi = pd.DataFrame({"Código": ins["codigo"].astype(str),
                                "Insumo": ins["descripcion"].fillna("").astype(str),
                                "Unidad": ins["unidad"].fillna("").astype(str),
                                "Densidad (g/ml)": ins["densidad_g_ml"]})
            edi = st.data_editor(_bi, hide_index=True, use_container_width=True,
                                 key="dns_ed_ins", num_rows="fixed",
                                 disabled=["Código", "Insumo", "Unidad"],
                                 column_config={"Densidad (g/ml)": st.column_config.NumberColumn(
                                     format="%.3f", min_value=0.3, max_value=2.5, step=0.005)})
            _ci = []
            for _i in range(len(edi)):
                _cod = str(edi.iloc[_i]["Código"])
                _nva = _num(edi.iloc[_i]["Densidad (g/ml)"])
                _fila = ins[ins["codigo"] == _cod]
                _vja = _num(_fila.iloc[0]["densidad_g_ml"]) if not _fila.empty else None
                if _nva != _vja:
                    _ci.append((_cod, _vja, _nva))
            if st.button("💾 Guardar insumos", key="dns_save_ins", disabled=(not _ci)):
                try:
                    with conectar(USR["id_usuario"]) as (conn, _a):
                        with conn.cursor() as cur:
                            for _cod, _vja, _nva in _ci:
                                cur.execute("UPDATE produccion.dic_insumo SET densidad_g_ml=%s "
                                            "WHERE codigo=%s", (_nva, _cod))
                                _a.log("DENSIDAD", "dic_insumo", _cod,
                                       {"antes": _vja, "ahora": _nva})
                    cat.clear()
                    st.success("✅ %d densidad(es) de insumo actualizada(s)." % len(_ci))
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo guardar: %s" % e)
