"""Sección Fórmulas: administración de fórmulas con nombre (dic_formula).
Consumos por TN de MATERIA PRIMA CARGADA. La fórmula default (⭐) por combinación
(sector, proceso, MP, PF) es la que usa el Centro de Planificación.
render(USR, cat, conectar)
"""
import json as _json
import pandas as pd
import streamlit as st

UNIDADES = ["L", "KG"]
SECTORES = ["REACTORES", "BACHAS", "*"]


def _ins_dict(v):
    if isinstance(v, dict):
        return v
    try:
        return _json.loads(v or "{}")
    except Exception:
        return {}


def _fmt_ins(v):
    d = _ins_dict(v)
    if not d:
        return "—"
    return " · ".join(f"{k}: {x.get('cant')} {x.get('un', '')}/TN" for k, x in d.items())


def _editor_insumos(base: dict, key: str, insumos_cat: list):
    """Editor dinámico de insumos {cod: {cant, un}}. Devuelve el dict resultante."""
    out = {}
    if base:
        st.caption("Insumos de la fórmula (cantidad **por TN de MP cargada**). Cantidad 0 = se elimina.")
        for cod, x in base.items():
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"&nbsp;\n**{cod}**", unsafe_allow_html=True)
            cant = c2.number_input("Cantidad", 0.0, 100000.0, value=float(x.get("cant") or 0),
                                   step=0.5, key=f"{key}_c_{cod}")
            un = c3.selectbox("Unidad", UNIDADES, index=(0 if x.get("un", "L") == "L" else 1),
                              key=f"{key}_u_{cod}")
            if cant > 0:
                out[cod] = {"cant": cant, "un": un}
    n1, n2, n3 = st.columns([2, 1, 1])
    restantes = [c for c in insumos_cat if c not in base]
    nuevo = n1.selectbox("➕ Agregar insumo", ["(ninguno)"] + restantes, key=f"{key}_new")
    ncant = n2.number_input("Cantidad ", 0.0, 100000.0, value=0.0, step=0.5, key=f"{key}_newc")
    nun = n3.selectbox("Unidad ", UNIDADES, key=f"{key}_newu")
    if nuevo != "(ninguno)" and ncant > 0:
        out[nuevo] = {"cant": ncant, "un": nun}
    return out


def _set_default(conectar, uid, id_formula, sector, proc, mp, pf):
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.dic_formula SET es_default=FALSE "
                        "WHERE sector=%s AND tipo_proceso=%s AND codigo_mp=%s AND codigo_pf=%s AND es_default",
                        (sector, proc, mp, pf))
            cur.execute("UPDATE produccion.dic_formula SET es_default=TRUE, actualizado_en=now() WHERE id_formula=%s",
                        (id_formula,))
        audit.log("U", "dic_formula", id_formula, {"es_default": True})


def render(USR, cat, conectar):
    st.title("🧪 Fórmulas de producción")
    if USR.get("rol") not in ("SUPERVISOR", "ADMIN"):
        st.warning("Sección exclusiva de dirección (SUPERVISOR / ADMIN).")
        return
    st.caption("Cada fórmula define **insumos por TN de materia prima cargada**, rendimiento y tiempos, con un nombre. "
               "La marcada con ⭐ es la **default**: la que usa el Centro de Planificación para los estimados. "
               "Podés tener varias fórmulas por combinación (proceso + MP + producto final) e ir probando.")

    df = cat("SELECT * FROM produccion.dic_formula WHERE activo "
             "ORDER BY sector, tipo_proceso, codigo_mp, codigo_pf, es_default DESC, nombre")
    insumos_cat = cat("SELECT codigo FROM produccion.dic_insumo WHERE activo ORDER BY codigo")["codigo"].tolist()
    prods = cat("SELECT codigo_producto FROM produccion.dim_producto WHERE activo ORDER BY codigo_producto")["codigo_producto"].tolist()
    procs = cat("SELECT codigo FROM produccion.dic_tipo_proceso WHERE activo ORDER BY codigo")["codigo"].tolist()
    uid = int(USR["id_usuario"])

    t_list, t_edit, t_new = st.tabs(["📋 Todas las fórmulas", "✏️ Editar / default", "➕ Nueva fórmula"])

    # ---------- listado ----------
    with t_list:
        if df.empty:
            st.info("No hay fórmulas cargadas.")
        else:
            f1, f2 = st.columns(2)
            fsec = f1.selectbox("Sector", ["(todos)"] + sorted(df["sector"].unique().tolist()), key="fx_fsec")
            fpro = f2.selectbox("Proceso", ["(todos)"] + sorted(df["tipo_proceso"].unique().tolist()), key="fx_fpro")
            v = df.copy()
            if fsec != "(todos)":
                v = v[v["sector"] == fsec]
            if fpro != "(todos)":
                v = v[v["tipo_proceso"] == fpro]
            v["Default"] = v["es_default"].map(lambda b: "⭐" if b else "")
            v["Insumos (por TN MP)"] = v["insumos"].map(_fmt_ins)
            st.dataframe(
                v[["Default", "nombre", "sector", "tipo_proceso", "codigo_mp", "codigo_pf",
                   "rendimiento_pct", "Insumos (por TN MP)", "horas_proceso", "horas_reposo", "notas"]]
                .rename(columns={"nombre": "Fórmula", "sector": "Sector", "tipo_proceso": "Proceso",
                                 "codigo_mp": "MP", "codigo_pf": "Producto final",
                                 "rendimiento_pct": "Rend. %", "horas_proceso": "h proceso",
                                 "horas_reposo": "h reposo", "notas": "Notas"}),
                use_container_width=True, hide_index=True)
            st.caption("`*` = aplica a cualquier MP / producto final del proceso.")

    # ---------- editar ----------
    with t_edit:
        if df.empty:
            st.info("No hay fórmulas para editar.")
        else:
            opts = df.apply(lambda r: f"{'⭐ ' if r['es_default'] else ''}{r['nombre']} · {r['sector']} · "
                                      f"{r['tipo_proceso']} · {r['codigo_mp']}→{r['codigo_pf']}", axis=1).tolist()
            sel = st.selectbox("Fórmula", opts, key="fx_sel")
            row = df.iloc[opts.index(sel)]
            idf = int(row["id_formula"])
            e1, e2, e3, e4 = st.columns([2, 1, 1, 1])
            e_nom = e1.text_input("Nombre", value=row["nombre"], max_chars=60, key=f"fx_nom_{idf}")
            e_rend = e2.number_input("Rendimiento %", 0.0, 100.0,
                                     value=float(row["rendimiento_pct"]) if pd.notna(row["rendimiento_pct"]) else 0.0,
                                     step=0.5, key=f"fx_rend_{idf}", help="kg de PF por 100 kg de MP. 0 = no aplica.")
            e_hp = e3.number_input("Horas proceso", 0.0, 96.0,
                                   value=float(row["horas_proceso"]) if pd.notna(row["horas_proceso"]) else 0.0,
                                   step=1.0, key=f"fx_hp_{idf}")
            e_hr = e4.number_input("Horas reposo", 0.0, 96.0,
                                   value=float(row["horas_reposo"]) if pd.notna(row["horas_reposo"]) else 0.0,
                                   step=1.0, key=f"fx_hr_{idf}")
            nuevo_ins = _editor_insumos(_ins_dict(row["insumos"]), f"fx_ins_{idf}", insumos_cat)
            # Parámetros estequiométricos (clave en ARE: acidez del lab + % glicerol pegan acá)
            nuevo_par = _ins_dict(row.get("parametros"))
            if row["tipo_proceso"] == "PRODUCCION_ARE":
                st.markdown("**Parámetros estequiométricos** — la glicerina se calcula con la **acidez** (lab de la MP) "
                            "y el **% glicerol** (muestra): `MP × acidez × PMg/(2·PMa) × exceso ÷ glicerol`.")
                p1, p2, p3, p4 = st.columns(4)
                _fe = p1.number_input("Factor exceso glicerol", 0.5, 3.0,
                                      value=float(nuevo_par.get("factor_exceso_gli") or 1.1), step=0.05, key=f"fx_fe_{idf}")
                _pma = p2.number_input("PMa (ácido graso)", 100.0, 500.0,
                                       value=float(nuevo_par.get("PMa") or 282), step=1.0, key=f"fx_pma_{idf}")
                _pmg = p3.number_input("PMg (glicerol)", 50.0, 200.0,
                                       value=float(nuevo_par.get("PMg") or 92), step=1.0, key=f"fx_pmg_{idf}")
                _fr = p4.number_input("Factor recuperación gli.", 0.0, 1.0,
                                      value=float(nuevo_par.get("factor_recuperacion_gli") or 0.9), step=0.05, key=f"fx_fr_{idf}")
                nuevo_par.update({"factor_exceso_gli": _fe, "PMa": _pma, "PMg": _pmg, "factor_recuperacion_gli": _fr})
            e_not = st.text_input("Notas", value=row["notas"] or "", max_chars=200, key=f"fx_not_{idf}")
            b1, b2, b3 = st.columns(3)
            if b1.button("💾 Guardar cambios", type="primary", use_container_width=True, key=f"fx_save_{idf}"):
                try:
                    with conectar(uid) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE produccion.dic_formula SET nombre=%s, rendimiento_pct=%s, insumos=%s::jsonb, "
                                "parametros=%s::jsonb, horas_proceso=%s, horas_reposo=%s, notas=%s, "
                                "actualizado_en=now() WHERE id_formula=%s",
                                (e_nom.strip(), (e_rend or None), _json.dumps(nuevo_ins), _json.dumps(nuevo_par),
                                 (e_hp or None), (e_hr or None), (e_not.strip() or None), idf))
                        audit.log("U", "dic_formula", idf, {"nombre": e_nom, "insumos": nuevo_ins})
                    st.success("Fórmula guardada.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)
            if b2.button("⭐ Usar como default", use_container_width=True, key=f"fx_def_{idf}",
                         disabled=bool(row["es_default"]),
                         help="La default es la que usa el Centro de Planificación para esta combinación."):
                try:
                    _set_default(conectar, uid, idf, row["sector"], row["tipo_proceso"], row["codigo_mp"], row["codigo_pf"])
                    st.success("Marcada como default.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)
            if b3.button("🗑️ Desactivar", use_container_width=True, key=f"fx_del_{idf}",
                         disabled=bool(row["es_default"]),
                         help="No se puede desactivar la default: primero marcá otra como default."):
                try:
                    with conectar(uid) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("UPDATE produccion.dic_formula SET activo=FALSE, actualizado_en=now() WHERE id_formula=%s", (idf,))
                        audit.log("U", "dic_formula", idf, {"activo": False})
                    st.success("Fórmula desactivada.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    # ---------- nueva ----------
    with t_new:
        n1, n2 = st.columns(2)
        nv_nom = n1.text_input("Nombre de la fórmula *", max_chars=60, key="fxn_nom",
                               placeholder="ej. Borra húmeda invierno")
        nv_sec = n2.selectbox("Sector", SECTORES, key="fxn_sec")
        n3, n4, n5 = st.columns(3)
        nv_pro = n3.selectbox("Proceso *", procs, key="fxn_pro")
        nv_mp = n4.selectbox("Materia prima", ["*"] + prods, key="fxn_mp")
        nv_pf = n5.selectbox("Producto final", ["*"] + prods, key="fxn_pf")
        n6, n7, n8 = st.columns(3)
        nv_rend = n6.number_input("Rendimiento % (0 = no aplica)", 0.0, 100.0, value=0.0, step=0.5, key="fxn_rend")
        nv_hp = n7.number_input("Horas proceso", 0.0, 96.0, value=0.0, step=1.0, key="fxn_hp")
        nv_hr = n8.number_input("Horas reposo", 0.0, 96.0, value=0.0, step=1.0, key="fxn_hr")
        nv_ins = _editor_insumos({}, "fxn_ins", insumos_cat)
        if nv_ins:
            st.caption("Insumos cargados: " + _fmt_ins(nv_ins))
        nv_par = {}
        if nv_pro == "PRODUCCION_ARE":
            st.markdown("**Parámetros estequiométricos** — la glicerina se calcula con la **acidez** (lab de la MP) "
                        "y el **% glicerol** (muestra): `MP × acidez × PMg/(2·PMa) × exceso ÷ glicerol`.")
            q1, q2, q3, q4 = st.columns(4)
            nv_par["factor_exceso_gli"] = q1.number_input("Factor exceso glicerol", 0.5, 3.0, value=1.1, step=0.05, key="fxn_fe")
            nv_par["PMa"] = q2.number_input("PMa (ácido graso)", 100.0, 500.0, value=282.0, step=1.0, key="fxn_pma")
            nv_par["PMg"] = q3.number_input("PMg (glicerol)", 50.0, 200.0, value=92.0, step=1.0, key="fxn_pmg")
            nv_par["factor_recuperacion_gli"] = q4.number_input("Factor recuperación gli.", 0.0, 1.0, value=0.9, step=0.05, key="fxn_fr")
        nv_def = st.checkbox("⭐ Usar como default para su combinación", key="fxn_def")
        nv_not = st.text_input("Notas", max_chars=200, key="fxn_not")
        if st.button("➕ Crear fórmula", type="primary", use_container_width=True, key="fxn_go"):
            if not (nv_nom or "").strip():
                st.error("Poné un nombre a la fórmula.")
            else:
                try:
                    with conectar(uid) as (conn, audit):
                        with conn.cursor() as cur:
                            if nv_def:
                                cur.execute("UPDATE produccion.dic_formula SET es_default=FALSE "
                                            "WHERE sector=%s AND tipo_proceso=%s AND codigo_mp=%s AND codigo_pf=%s AND es_default",
                                            (nv_sec, nv_pro, nv_mp, nv_pf))
                            cur.execute(
                                "INSERT INTO produccion.dic_formula "
                                "(nombre, sector, tipo_proceso, codigo_mp, codigo_pf, rendimiento_pct, insumos, "
                                " parametros, horas_proceso, horas_reposo, es_default, notas) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s) RETURNING id_formula",
                                (nv_nom.strip(), nv_sec, nv_pro, nv_mp, nv_pf, (nv_rend or None),
                                 _json.dumps(nv_ins), _json.dumps(nv_par), (nv_hp or None), (nv_hr or None),
                                 bool(nv_def), (nv_not.strip() or None)))
                            _idn = cur.fetchone()[0]
                        audit.log("I", "dic_formula", _idn, {"nombre": nv_nom.strip(), "proceso": nv_pro})
                    st.success(f"Fórmula creada: {nv_nom.strip()}.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)
