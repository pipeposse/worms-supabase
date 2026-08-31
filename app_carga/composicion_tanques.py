# -*- coding: utf-8 -*-
"""Composición multi-producto por tanque (pedido de jefatura de planta).

Un tanque puede tener varios líquidos a la vez — ej. Cónico 8 = AFE-M / ARE-B /
AFE-S — y acá se declara **producto por producto, con sus litros**, sin usar la
designación AG-E. La declaración fija las PROPORCIONES: el litraje por producto
se recalcula solo con cada medición de nivel (WeDo o manual), así lo declarado
no queda viejo cuando el tanque sube o baja.

- `render`: editor completo (elegir tanque, cargar producto + litros, guardar
  con historial y auditoría, sincronizar el producto principal al mayoritario).
- `etiquetas`: dict id_tanque -> "AFE-M 30% · ARE-B 70%" para que las demás
  pantallas muestren la composición declarada.
"""

import json

import pandas as pd
import streamlit as st

ROLES_EDIT = ("SUPERVISOR", "ADMIN")


def _f(v, d=0.0):
    try:
        if v is None or pd.isna(v):
            return d
        return float(v)
    except Exception:
        return d


def etiquetas(cat):
    """id_tanque -> 'AFE-M 30% · ARE-B 70%' (sólo tanques con composición declarada)."""
    try:
        c = cat("SELECT id_tanque, codigo_producto, fraccion "
                "FROM produccion.vw_tanque_composicion WHERE declarado "
                "ORDER BY id_tanque, fraccion DESC")
        if c is None or c.empty:
            return {}
        out = {}
        for _id, _g in c.groupby("id_tanque"):
            out[int(_id)] = " · ".join(
                "%s %.0f%%" % (str(r["codigo_producto"]), 100.0 * _f(r["fraccion"]))
                for _, r in _g.iterrows())
        return out
    except Exception:
        return {}


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#3b0764,#7c3aed);border-radius:14px;"
        "padding:14px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.3rem;font-weight:900'>🧪 Composición por tanque</div>"
        "<div style='color:#ede9fe;font-size:.86rem;margin-top:3px'>Qué líquidos tiene cada "
        "tanque y cuántos litros de cada uno — sin la designación AG-E: se declara la "
        "composición real (ej. AFE-M / ARE-B / AFE-S).</div></div>",
        unsafe_allow_html=True)
    uid = int(USR.get("id_usuario") or 0)
    ss = st.session_state
    _puede = (USR.get("rol") in ROLES_EDIT
              or "PLANIFICACION" in (USR.get("secciones_app") or [])
              or "INICIAR" in (USR.get("secciones_app") or []))

    tks = cat("SELECT p.id_tanque, p.nombre, p.sector, p.producto_principal, "
              "p.litros_actual, p.capacidad_litros "
              "FROM produccion.vw_tanque_panel p WHERE p.activo "
              "ORDER BY p.sector, p.nombre")
    if tks is None or tks.empty:
        st.info("No hay tanques activos.")
        return
    tks = tks.copy()
    tks["litros_actual"] = pd.to_numeric(tks["litros_actual"], errors="coerce").fillna(0.0)

    # ---- resumen: qué tanques ya tienen composición declarada
    _lbl = etiquetas(cat)
    if _lbl:
        _nom = dict(zip(tks["id_tanque"].astype(int), tks["nombre"].astype(str)))
        st.caption("**%d tanque(s) con composición declarada:** " % len(_lbl) +
                   " · ".join("**%s** (%s)" % (_nom.get(k, k), v)
                              for k, v in sorted(_lbl.items(), key=lambda x: _nom.get(x[0], ""))))

    _ids = tks["id_tanque"].astype(int).tolist()
    _fmt = {int(r["id_tanque"]): "%s · %s · %s L%s" % (
        r["nombre"], r["sector"],
        "{:,.0f}".format(_f(r["litros_actual"])),
        (" · " + _lbl[int(r["id_tanque"])]) if int(r["id_tanque"]) in _lbl
        else (" · %s" % (r["producto_principal"] or "sin producto")))
        for _, r in tks.iterrows()}
    sel = st.selectbox("Tanque", _ids, format_func=lambda i: _fmt.get(int(i), str(i)),
                       key="ct_sel")
    t = tks[tks["id_tanque"].astype(int) == int(sel)].iloc[0]
    _stk = _f(t["litros_actual"])
    _nz = int(ss.get("ct_nonce_%d" % int(sel)) or 0)

    _pr = cat("SELECT codigo_producto FROM produccion.dim_producto "
              "WHERE COALESCE(activo,true) ORDER BY codigo_producto")
    _prods = _pr["codigo_producto"].astype(str).str.strip().str.upper().tolist() \
        if _pr is not None and not _pr.empty else []

    cur = cat("SELECT codigo_producto, litros, nota "
              "FROM produccion.fact_tanque_composicion WHERE id_tanque=%s "
              "ORDER BY litros DESC", (int(sel),))
    _tiene = cur is not None and not cur.empty
    _base = pd.DataFrame({
        "Producto": (cur["codigo_producto"].astype(str) if _tiene
                     else pd.Series(dtype="object")),
        "Litros": (pd.to_numeric(cur["litros"], errors="coerce") if _tiene
                   else pd.Series(dtype="float64")),
        "Nota": (cur["nota"].fillna("").astype(str) if _tiene
                 else pd.Series(dtype="object")),
    })

    c1, c2 = st.columns([2.1, 1.2])
    with c1:
        st.markdown("**Composición declarada de %s** (stock medido: **%s L**)"
                    % (t["nombre"], "{:,.0f}".format(_stk)))
        ed = st.data_editor(
            _base, hide_index=True, use_container_width=True, num_rows="dynamic",
            key="ct_ed_%d_%d" % (int(sel), _nz),
            column_config={
                "Producto": st.column_config.SelectboxColumn(options=_prods, required=True),
                "Litros": st.column_config.NumberColumn(
                    format="%.0f", min_value=0.0, required=True,
                    help="Litros de ESTE producto dentro del tanque."),
                "Nota": st.column_config.TextColumn(help="De dónde salió (opcional)."),
            })
        st.caption("La declaración fija las **proporciones**: si el nivel del tanque cambia, "
                   "los litros por producto se recalculan solos manteniendo el porcentaje. "
                   "Agregá una fila por producto; para volver a un solo producto dejá una fila.")

    # ---- panel de control: suma declarada vs stock medido
    _lts = pd.to_numeric(ed["Litros"], errors="coerce").fillna(0.0)
    _tot = float(_lts.sum())
    with c2:
        st.markdown("**Control**")
        st.metric("Suma declarada", "%s L" % "{:,.0f}".format(_tot))
        st.metric("Stock medido", "%s L" % "{:,.0f}".format(_stk))
        if _tot > 0:
            _dif = _tot - _stk
            if _stk > 0 and abs(_dif) > max(0.10 * _stk, 500.0):
                st.warning("La suma declarada difiere **%s L** del stock medido. Se puede "
                           "guardar igual (valen las proporciones), pero conviene revisar."
                           % "{:,.0f}".format(abs(_dif)))
            for _i in range(len(ed)):
                _l = _f(ed["Litros"].iloc[_i])
                if _l > 0:
                    st.caption("· **%s** → %.1f%%" % (str(ed["Producto"].iloc[_i] or "—"),
                                                      100.0 * _l / _tot))

    if not _puede:
        st.info("Sólo lectura para tu usuario.")
        return

    b1, b2, b3 = st.columns([1.2, 1.6, 1.6])
    if b1.button("💾 Guardar composición", type="primary", key="ct_save_%d" % int(sel)):
        _fil = []
        for _i in range(len(ed)):
            _p = str(ed["Producto"].iloc[_i] or "").strip().upper()
            _l = round(_f(ed["Litros"].iloc[_i]), 0)
            if _p and _l > 0:
                _fil.append((_p, _l, (str(ed["Nota"].iloc[_i] or "").strip() or None)))
        _vist = [p for p, _l, _n in _fil]
        if len(_vist) != len(set(_vist)):
            st.error("Hay productos repetidos: dejá una sola fila por producto.")
        else:
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur2:
                        cur2.execute("DELETE FROM produccion.fact_tanque_composicion "
                                     "WHERE id_tanque=%s", (int(sel),))
                        for _p, _l, _n in _fil:
                            cur2.execute(
                                "INSERT INTO produccion.fact_tanque_composicion "
                                "(id_tanque, codigo_producto, litros, nota, actualizado_por) "
                                "VALUES (%s,%s,%s,%s,%s)",
                                (int(sel), _p, _l, _n, (USR.get("nombre") or str(uid))))
                        cur2.execute(
                            "INSERT INTO produccion.fact_tanque_composicion_hist "
                            "(id_tanque, composicion, litros_total, declarado_por) "
                            "VALUES (%s,%s::jsonb,%s,%s)",
                            (int(sel),
                             json.dumps([{"producto": _p, "litros": _l} for _p, _l, _n in _fil]),
                             sum(_l for _p, _l, _n in _fil),
                             (USR.get("nombre") or str(uid))))
                    audit.log("U", "fact_tanque_composicion", int(sel),
                              {"tanque": str(t["nombre"]),
                               "composicion": {p: l for p, l, _n in _fil}})
                cat.clear()
                ss["ct_nonce_%d" % int(sel)] = _nz + 1
                st.success("✅ Composición de %s guardada (%d producto(s))."
                           % (t["nombre"], len(_fil)))
                st.rerun()
            except Exception as e:
                st.error("No se pudo guardar: %s" % e)

    _may = None
    if _tot > 0 and len(ed):
        _ix = _lts.idxmax()
        _may = str(ed["Producto"].loc[_ix] or "").strip().upper() or None
    if _may and _may != str(t["producto_principal"] or "").strip().upper():
        if b2.button("🔁 Producto principal → %s (mayoritario)" % _may,
                     key="ct_sync_%d" % int(sel),
                     help="El resto del sistema (formulación, asignación, stock por "
                          "producto) sigue leyendo el producto principal del tanque: "
                          "conviene que sea el mayoritario de la composición."):
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur2:
                        cur2.execute("SELECT id_producto FROM produccion.dim_producto "
                                     "WHERE upper(btrim(codigo_producto))=%s "
                                     "AND COALESCE(activo,true) LIMIT 1", (_may,))
                        _rp = cur2.fetchone()
                        if not _rp:
                            raise RuntimeError("no existe el producto %s en el maestro" % _may)
                        cur2.execute("UPDATE produccion.dim_tanque SET id_producto_principal=%s "
                                     "WHERE id_tanque=%s", (int(_rp[0]), int(sel)))
                    audit.log("U", "dim_tanque", int(sel),
                              {"producto_principal": _may, "motivo": "mayoritario composicion"})
                cat.clear()
                st.success("✅ Producto principal de %s → %s." % (t["nombre"], _may))
                st.rerun()
            except Exception as e:
                st.error("No se pudo cambiar: %s" % e)

    if _tiene and b3.button("🗑️ Quitar la declaración (vuelve al producto principal)",
                            key="ct_del_%d" % int(sel)):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur2:
                    cur2.execute("DELETE FROM produccion.fact_tanque_composicion "
                                 "WHERE id_tanque=%s", (int(sel),))
                audit.log("D", "fact_tanque_composicion", int(sel),
                          {"tanque": str(t["nombre"])})
            cat.clear()
            ss["ct_nonce_%d" % int(sel)] = _nz + 1
            st.success("✅ %s vuelve a leerse por su producto principal." % t["nombre"])
            st.rerun()
        except Exception as e:
            st.error("No se pudo quitar: %s" % e)

    hist = cat("SELECT declarado_en, declarado_por, litros_total, composicion "
               "FROM produccion.fact_tanque_composicion_hist WHERE id_tanque=%s "
               "ORDER BY id_hist DESC LIMIT 10", (int(sel),))
    if hist is not None and not hist.empty:
        with st.expander("🕘 Historial de declaraciones de este tanque", expanded=False):
            for _, h in hist.iterrows():
                try:
                    _c = h["composicion"]
                    if isinstance(_c, str):
                        _c = json.loads(_c)
                    _txt = " · ".join("%s %s L" % (x.get("producto"),
                                                   "{:,.0f}".format(_f(x.get("litros"))))
                                      for x in _c)
                except Exception:
                    _txt = str(h["composicion"])[:120]
                st.caption("**%s** · %s · total %s L → %s"
                           % (str(h["declarado_en"])[:16], str(h["declarado_por"] or "—"),
                              "{:,.0f}".format(_f(h["litros_total"])), _txt))
