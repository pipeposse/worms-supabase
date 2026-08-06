"""Sección Repuestos: stock de repuestos, insumos y consumibles de mantenimiento.

render(USR, cat, conectar)
  cat      -> helper cacheado de app.py (query, params) -> DataFrame
  conectar -> context manager de etl.db que da (conn, audit)

Tablas: produccion.dim_repuesto / produccion.fact_repuesto_movimiento
Vista : produccion.v_repuesto_stock  (stock_actual, margen, estado)
"""
import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

UNIDADES = ["UN", "LT", "KG", "MT", "JGO", "M2", "ROLLO", "CAJA", "PAR"]

MOTIVOS_ING = ["Compra", "Devolución de taller", "Ajuste de inventario", "Reparación / recambio", "Otro"]
MOTIVOS_EGR = ["Consumo mantenimiento", "Rotura / recambio", "Préstamo", "Ajuste de inventario", "Baja", "Otro"]

_EST_ICONO = {"SIN STOCK": "⛔", "BAJO MINIMO": "🚨", "AL LIMITE": "⚠️", "OK": "✅"}


# ------------------------------------------------------------------ datos ---
def _stock(cat):
    df = cat(
        "SELECT id_repuesto, codigo, detalle, categoria, unidad, stock_minimo, ubicacion, "
        "       proveedor, equipo, activo, stock_actual, margen, estado, ultimo_mov, movimientos "
        "FROM produccion.v_repuesto_stock ORDER BY detalle")
    if df is None:
        return pd.DataFrame()
    for c in ("stock_actual", "stock_minimo", "margen"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _movs(cat, d1, d2):
    return cat(
        "SELECT m.id_movimiento, m.fecha, m.tipo, m.cantidad, r.codigo, r.detalle, r.categoria, r.unidad, "
        "       m.motivo, m.destino, m.proveedor, m.remito, m.costo_unitario, m.usuario, m.nota, m.anulado, m.creado_en "
        "FROM produccion.fact_repuesto_movimiento m "
        "JOIN produccion.dim_repuesto r ON r.id_repuesto = m.id_repuesto "
        "WHERE m.fecha BETWEEN %s AND %s "
        "ORDER BY m.fecha DESC, m.id_movimiento DESC", (d1, d2))


def _categorias(df):
    if df is None or df.empty:
        return []
    return sorted([c for c in df["categoria"].dropna().unique().tolist() if str(c).strip()])


def _xlsx(df, hoja="Datos"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=hoja[:30])
    return buf.getvalue()


def _dl(df, nombre, key, label="⬇️ Excel"):
    if df is None or df.empty:
        return
    st.download_button(label, _xlsx(df), file_name=nombre,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=key, use_container_width=True)


# ----------------------------------------------------------------- writes ---
def _grabar_movs(conectar, USR, filas):
    """filas: lista de dicts con id_repuesto, tipo, cantidad, fecha, motivo, destino,
    proveedor, remito, costo_unitario, nota. Devuelve lista de ids."""
    ids = []
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            for f in filas:
                cur.execute(
                    "INSERT INTO produccion.fact_repuesto_movimiento "
                    "(id_repuesto, tipo, cantidad, fecha, motivo, destino, proveedor, remito, "
                    " costo_unitario, usuario, nota) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_movimiento",
                    (int(f["id_repuesto"]), f["tipo"], float(f["cantidad"]), f.get("fecha"),
                     f.get("motivo"), f.get("destino"), f.get("proveedor"), f.get("remito"),
                     f.get("costo_unitario"), USR.get("nombre"), f.get("nota")))
                _id = cur.fetchone()[0]
                ids.append(_id)
                audit.log("I", "fact_repuesto_movimiento", _id, f)
    return ids


def _anular_mov(conectar, USR, id_mov, motivo):
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.fact_repuesto_movimiento SET anulado = true, "
                        "nota = COALESCE(nota,'') || ' | ANULADO: ' || %s WHERE id_movimiento = %s",
                        (motivo or "sin motivo", int(id_mov)))
        audit.log("U", "fact_repuesto_movimiento", id_mov, {"anulado": True, "motivo": motivo})


def _alta_repuesto(conectar, USR, d):
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO produccion.dim_repuesto "
                "(codigo, detalle, categoria, unidad, stock_minimo, ubicacion, proveedor, equipo, "
                " observaciones, creado_por) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (detalle_norm) DO NOTHING RETURNING id_repuesto",
                (d.get("codigo"), d["detalle"], d.get("categoria"), d.get("unidad") or "UN",
                 float(d.get("stock_minimo") or 0), d.get("ubicacion"), d.get("proveedor"),
                 d.get("equipo"), d.get("observaciones"), USR.get("nombre")))
            r = cur.fetchone()
        if r:
            audit.log("I", "dim_repuesto", r[0], d)
    return (r[0] if r else None)


def _update_repuestos(conectar, USR, cambios):
    """cambios: lista de dicts {id_repuesto, campo: valor, ...}"""
    n = 0
    campos = ("codigo", "detalle", "categoria", "unidad", "stock_minimo",
              "ubicacion", "proveedor", "equipo", "activo")
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            for c in cambios:
                sets, vals = [], []
                for k in campos:
                    if k in c:
                        sets.append("%s = %%s" % k)
                        vals.append(c[k])
                if not sets:
                    continue
                sets.append("actualizado_en = now()")
                vals.append(int(c["id_repuesto"]))
                cur.execute("UPDATE produccion.dim_repuesto SET " + ", ".join(sets) +
                            " WHERE id_repuesto = %s", tuple(vals))
                audit.log("U", "dim_repuesto", c["id_repuesto"], c)
                n += 1
    return n


# ------------------------------------------------------------------- vistas -
def _banner_alertas(df):
    if df is None or df.empty:
        return
    act = df[df["activo"] == True]  # noqa: E712
    sin = int((act["estado"] == "SIN STOCK").sum())
    bajo = int((act["estado"] == "BAJO MINIMO").sum())
    lim = int((act["estado"] == "AL LIMITE").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ítems activos", int(len(act)))
    c2.metric("⛔ Sin stock", sin)
    c3.metric("🚨 Bajo mínimo", bajo)
    c4.metric("⚠️ Al límite", lim)
    if sin or bajo:
        st.error("**%d ítem(s) sin stock** y **%d bajo el mínimo**. Mirá la vista 🚨 Alertas para el listado de reposición." % (sin, bajo))


def _filtros(df, key):
    cA, cB, cC = st.columns([2, 1.2, 1.2])
    txt = cA.text_input("🔎 Buscar (código, detalle, equipo, ubicación)", key=key + "_txt")
    cats = ["(todas)"] + _categorias(df)
    ca = cB.selectbox("Categoría", cats, key=key + "_cat")
    est = cC.selectbox("Estado", ["(todos)", "⛔ Sin stock", "🚨 Bajo mínimo", "⚠️ Al límite", "✅ OK"], key=key + "_est")
    v = df.copy()
    if txt:
        t = txt.strip().lower()
        cols = ["codigo", "detalle", "equipo", "ubicacion", "proveedor", "categoria"]
        m = pd.Series(False, index=v.index)
        for c in cols:
            m = m | v[c].astype(str).str.lower().str.contains(t, na=False, regex=False)
        v = v[m]
    if ca != "(todas)":
        v = v[v["categoria"] == ca]
    if est != "(todos)":
        v = v[v["estado"] == est.split(" ", 1)[1].upper().replace("BAJO MÍNIMO", "BAJO MINIMO")]
    return v


def _vista_movimiento(USR, cat, conectar, df):
    st.subheader("⚡ Cargar movimiento")
    st.caption("Ingreso = entra al depósito. Egreso = sale (consumo, rotura, préstamo). "
               "El stock se recalcula solo.")

    if df.empty:
        st.info("Todavía no hay repuestos cargados. Andá a ➕ Nuevo repuesto.")
        return

    act = df[df["activo"] == True].copy()  # noqa: E712
    cats = ["(todas)"] + _categorias(act)
    c0, c1 = st.columns([1, 3])
    fcat = c0.selectbox("Filtrar por categoría", cats, key="rep_mv_cat")
    op = act if fcat == "(todas)" else act[act["categoria"] == fcat]
    op = op.sort_values("detalle")

    def _lbl(i):
        r = op[op["id_repuesto"] == i].iloc[0]
        cod = ("%s · " % r["codigo"]) if r["codigo"] else ""
        return "%s%s  —  stock %s %s" % (cod, r["detalle"][:70], ("%g" % r["stock_actual"]), r["unidad"])

    idr = c1.selectbox("Repuesto", op["id_repuesto"].tolist(), format_func=_lbl,
                       index=None, placeholder="Escribí para buscar…", key="rep_mv_item")
    if idr is None:
        st.info("Elegí un repuesto para cargar el movimiento.")
        return

    r = op[op["id_repuesto"] == idr].iloc[0]
    k1, k2, k3 = st.columns(3)
    k1.metric("Stock actual", "%g %s" % (r["stock_actual"], r["unidad"]))
    k2.metric("Stock mínimo", "%g" % r["stock_minimo"])
    k3.metric("Estado", "%s %s" % (_EST_ICONO.get(r["estado"], ""), r["estado"].title()))

    tipo = st.radio("Tipo", ["📥 INGRESO", "📤 EGRESO"], horizontal=True, key="rep_mv_tipo")
    es_ing = tipo.endswith("INGRESO")

    with st.form("rep_mv_form", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        cant = f1.number_input("Cantidad (%s) *" % r["unidad"], min_value=0.0, step=1.0, value=1.0, key="rep_mv_cant")
        fecha = f2.date_input("Fecha", value=date.today(), key="rep_mv_fecha")
        motivo = f3.selectbox("Motivo", MOTIVOS_ING if es_ing else MOTIVOS_EGR, key="rep_mv_motivo")
        g1, g2, g3 = st.columns(3)
        if es_ing:
            destino = None
            prov = g1.text_input("Proveedor", key="rep_mv_prov")
            remito = g2.text_input("Remito / factura", key="rep_mv_rem")
            costo = g3.number_input("Costo unitario (opcional)", min_value=0.0, step=100.0, value=0.0, key="rep_mv_costo")
        else:
            prov, remito, costo = None, None, 0.0
            destino = g1.text_input("¿A dónde va? (equipo, sector, persona)", key="rep_mv_dest")
            g2.empty(); g3.empty()
        nota = st.text_input("Nota (opcional)", key="rep_mv_nota")
        ok = st.form_submit_button("💾 Registrar movimiento", type="primary", use_container_width=True)

    if ok:
        if cant <= 0:
            st.error("La cantidad tiene que ser mayor a 0.")
            return
        nuevo = float(r["stock_actual"]) + (cant if es_ing else -cant)
        if not es_ing and nuevo < 0:
            st.warning("⚠️ Ese egreso deja el stock en **%g** (negativo). Se registra igual, pero revisá el conteo." % nuevo)
        try:
            _grabar_movs(conectar, USR, [{
                "id_repuesto": int(idr), "tipo": "INGRESO" if es_ing else "EGRESO",
                "cantidad": float(cant), "fecha": fecha, "motivo": motivo, "destino": destino,
                "proveedor": prov or None, "remito": remito or None,
                "costo_unitario": (float(costo) if costo else None), "nota": nota or None}])
            cat.clear()
            st.balloons()
            st.success("✅ %s de **%g %s** de *%s*. Stock nuevo: **%g %s**." %
                       ("Ingreso" if es_ing else "Egreso", cant, r["unidad"], r["detalle"], nuevo, r["unidad"]))
            if nuevo < float(r["stock_minimo"]):
                st.error("🚨 **%s** quedó BAJO EL MÍNIMO (%g < %g). Hay que reponer." %
                         (r["detalle"], nuevo, r["stock_minimo"]))
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)

    # --------- carga múltiple ---------
    with st.expander("📋 Cargar varios movimientos de una (pegar / editar)", expanded=False):
        st.caption("Una fila por movimiento. `codigo` o `detalle` sirven para identificar el repuesto.")
        base = pd.DataFrame({"detalle": pd.Series(dtype="str"), "tipo": pd.Series(dtype="str"),
                             "cantidad": pd.Series(dtype="float"), "motivo": pd.Series(dtype="str"),
                             "destino_o_proveedor": pd.Series(dtype="str")})
        ed = st.data_editor(base, num_rows="dynamic", use_container_width=True, key="rep_mv_bulk",
                            column_config={
                                "detalle": st.column_config.SelectboxColumn("Repuesto", options=act["detalle"].tolist(), width="large"),
                                "tipo": st.column_config.SelectboxColumn("Tipo", options=["INGRESO", "EGRESO"]),
                                "cantidad": st.column_config.NumberColumn("Cantidad", min_value=0.0, step=1.0),
                            })
        fech_b = st.date_input("Fecha para todas", value=date.today(), key="rep_mv_bulk_f")
        if st.button("💾 Guardar lote", key="rep_mv_bulk_go", use_container_width=True):
            filas, errores = [], []
            for _, row in ed.iterrows():
                det = str(row.get("detalle") or "").strip()
                if not det:
                    continue
                m = act[act["detalle"] == det]
                if m.empty:
                    errores.append(det); continue
                try:
                    q = float(row.get("cantidad") or 0)
                except Exception:
                    q = 0.0
                tp = str(row.get("tipo") or "").upper()
                if q <= 0 or tp not in ("INGRESO", "EGRESO"):
                    errores.append(det + " (tipo/cantidad)"); continue
                dp = row.get("destino_o_proveedor") or None
                filas.append({"id_repuesto": int(m.iloc[0]["id_repuesto"]), "tipo": tp, "cantidad": q,
                              "fecha": fech_b, "motivo": row.get("motivo") or None,
                              "destino": (dp if tp == "EGRESO" else None),
                              "proveedor": (dp if tp == "INGRESO" else None),
                              "remito": None, "costo_unitario": None, "nota": "carga múltiple"})
            if errores:
                st.warning("Filas ignoradas: %s" % ", ".join(errores[:10]))
            if filas:
                try:
                    _grabar_movs(conectar, USR, filas)
                    cat.clear()
                    st.success("✅ %d movimiento(s) guardado(s)." % len(filas))
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo guardar el lote: %s" % e)
            else:
                st.info("No había filas válidas.")


def _vista_stock(USR, cat, conectar, df):
    st.subheader("📊 Stock actual")
    if df.empty:
        st.info("Sin repuestos cargados.")
        return
    v = _filtros(df, "rep_st")
    st.caption("%d ítem(s). Podés editar mínimo, categoría, unidad, ubicación y equipo directamente en la tabla." % len(v))

    vis = v.copy()
    vis["alerta"] = vis["estado"].map(lambda e: _EST_ICONO.get(e, ""))
    cols = ["alerta", "codigo", "detalle", "categoria", "stock_actual", "unidad", "stock_minimo",
            "margen", "ubicacion", "equipo", "proveedor", "ultimo_mov", "movimientos", "activo", "id_repuesto"]
    ed = st.data_editor(
        vis[cols], use_container_width=True, hide_index=True, key="rep_st_ed",
        disabled=["alerta", "stock_actual", "margen", "ultimo_mov", "movimientos", "id_repuesto"],
        column_config={
            "alerta": st.column_config.TextColumn("", width="small"),
            "codigo": st.column_config.TextColumn("Código", width="small"),
            "detalle": st.column_config.TextColumn("Detalle", width="large"),
            "categoria": st.column_config.TextColumn("Categoría"),
            "stock_actual": st.column_config.NumberColumn("Stock", format="%.2f"),
            "unidad": st.column_config.SelectboxColumn("Un.", options=UNIDADES, width="small"),
            "stock_minimo": st.column_config.NumberColumn("Mínimo", min_value=0.0, step=1.0, format="%.2f"),
            "margen": st.column_config.NumberColumn("Margen", format="%.2f", help="Stock - mínimo"),
            "ubicacion": st.column_config.TextColumn("Ubicación"),
            "equipo": st.column_config.TextColumn("Equipo / máquina"),
            "ultimo_mov": st.column_config.DateColumn("Últ. mov."),
            "movimientos": st.column_config.NumberColumn("N° mov.", format="%d"),
            "activo": st.column_config.CheckboxColumn("Activo"),
            "id_repuesto": st.column_config.NumberColumn("ID", format="%d"),
        })

    c1, c2 = st.columns([1, 1])
    if c1.button("💾 Guardar cambios de la tabla", key="rep_st_save", use_container_width=True):
        orig = vis[cols].set_index("id_repuesto")
        new = ed.set_index("id_repuesto")
        campos = ["codigo", "detalle", "categoria", "unidad", "stock_minimo", "ubicacion", "equipo", "activo"]
        cambios = []
        for i in new.index:
            if i not in orig.index:
                continue
            d = {"id_repuesto": int(i)}
            for k in campos:
                a, b = orig.loc[i, k], new.loc[i, k]
                if pd.isna(a) and pd.isna(b):
                    continue
                if a != b:
                    d[k] = (None if (pd.isna(b) or b == "") else b)
            if len(d) > 1:
                cambios.append(d)
        if not cambios:
            st.info("No hay cambios para guardar.")
        else:
            try:
                n = _update_repuestos(conectar, USR, cambios)
                cat.clear()
                st.success("✅ %d ítem(s) actualizado(s)." % n)
                st.rerun()
            except Exception as e:
                st.error("No se pudo guardar: %s" % e)
    with c2:
        _dl(v.drop(columns=["margen"], errors="ignore"), "stock_repuestos.xlsx", "rep_st_dl")

    # ------- fijar stock físico (inventario) -------
    with st.expander("🧮 Fijar stock físico (conteo de inventario)", expanded=False):
        st.caption("Poné la cantidad **real contada**: se genera el movimiento de ajuste por la diferencia.")
        act = df[df["activo"] == True]  # noqa: E712
        idr = st.selectbox("Repuesto", act["id_repuesto"].tolist(), index=None,
                           format_func=lambda i: "%s — stock sistema %g" % (
                               act[act["id_repuesto"] == i].iloc[0]["detalle"][:70],
                               act[act["id_repuesto"] == i].iloc[0]["stock_actual"]),
                           placeholder="Buscá el repuesto…", key="rep_st_inv_item")
        if idr is not None:
            r = act[act["id_repuesto"] == idr].iloc[0]
            cc1, cc2 = st.columns(2)
            real = cc1.number_input("Cantidad real contada (%s)" % r["unidad"], min_value=0.0, step=1.0,
                                    value=float(r["stock_actual"]), key="rep_st_inv_q")
            nota = cc2.text_input("Nota", value="Conteo de inventario", key="rep_st_inv_n")
            delta = float(real) - float(r["stock_actual"])
            st.write("Diferencia: **%+g %s**" % (delta, r["unidad"]))
            if st.button("💾 Ajustar", key="rep_st_inv_go", disabled=(abs(delta) < 1e-9), use_container_width=True):
                try:
                    _grabar_movs(conectar, USR, [{
                        "id_repuesto": int(idr), "tipo": ("AJUSTE" if delta > 0 else "EGRESO"),
                        "cantidad": abs(delta), "fecha": date.today(),
                        "motivo": "Ajuste de inventario", "destino": None, "proveedor": None,
                        "remito": None, "costo_unitario": None, "nota": nota or None}])
                    cat.clear()
                    st.success("✅ Stock de *%s* fijado en **%g %s**." % (r["detalle"], real, r["unidad"]))
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo ajustar: %s" % e)


def _vista_alertas(USR, cat, conectar, df):
    st.subheader("🚨 Alertas de stock mínimo")
    if df.empty:
        st.info("Sin datos.")
        return
    act = df[df["activo"] == True].copy()  # noqa: E712
    al = act[act["estado"].isin(["SIN STOCK", "BAJO MINIMO", "AL LIMITE"])].copy()
    if al.empty:
        st.success("✅ No hay ítems por debajo del mínimo. Ojo: los repuestos con mínimo en 0 no generan alerta — "
                   "cargá el mínimo en 📊 Stock actual para que el sistema avise.")
    else:
        al["reponer"] = (al["stock_minimo"] * 2 - al["stock_actual"]).clip(lower=0)
        al["prioridad"] = al["estado"].map({"SIN STOCK": 0, "BAJO MINIMO": 1, "AL LIMITE": 2})
        al = al.sort_values(["prioridad", "detalle"])
        al["alerta"] = al["estado"].map(lambda e: _EST_ICONO.get(e, ""))
        st.dataframe(al[["alerta", "codigo", "detalle", "categoria", "stock_actual", "unidad",
                         "stock_minimo", "reponer", "ubicacion", "equipo", "proveedor", "ultimo_mov"]],
                     use_container_width=True, hide_index=True)
        _dl(al[["codigo", "detalle", "categoria", "stock_actual", "unidad", "stock_minimo",
                "reponer", "proveedor", "equipo"]], "reposicion_repuestos.xlsx", "rep_al_dl",
            "⬇️ Excel de reposición")

    sin_min = act[act["stock_minimo"] <= 0]
    if not sin_min.empty:
        with st.expander("⚙️ %d ítem(s) todavía SIN mínimo definido (no alertan nunca)" % len(sin_min)):
            st.caption("Definí el mínimo acá y quedan bajo control.")
            base = sin_min[["id_repuesto", "codigo", "detalle", "categoria", "unidad", "stock_actual"]].copy()
            base["stock_minimo"] = 0.0
            ed = st.data_editor(base, use_container_width=True, hide_index=True, key="rep_al_min",
                                disabled=["id_repuesto", "codigo", "detalle", "categoria", "unidad", "stock_actual"])
            if st.button("💾 Guardar mínimos", key="rep_al_min_go", use_container_width=True):
                cambios = [{"id_repuesto": int(r["id_repuesto"]), "stock_minimo": float(r["stock_minimo"])}
                           for _, r in ed.iterrows() if float(r["stock_minimo"] or 0) > 0]
                if not cambios:
                    st.info("No pusiste ningún mínimo mayor a 0.")
                else:
                    try:
                        _update_repuestos(conectar, USR, cambios)
                        cat.clear()
                        st.success("✅ %d mínimo(s) cargado(s)." % len(cambios))
                        st.rerun()
                    except Exception as e:
                        st.error("No se pudo guardar: %s" % e)


def _vista_historial(USR, cat, conectar, df):
    st.subheader("🕐 Movimientos históricos")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1.4])
    d1 = c1.date_input("Desde", value=date.today() - timedelta(days=90), key="rep_h_d1")
    d2 = c2.date_input("Hasta", value=date.today(), key="rep_h_d2")
    tipo = c3.selectbox("Tipo", ["(todos)", "INGRESO", "EGRESO", "AJUSTE"], key="rep_h_tipo")
    txt = c4.text_input("🔎 Buscar repuesto / motivo / destino", key="rep_h_txt")

    try:
        mv = _movs(cat, d1, d2)
    except Exception as e:
        st.error("No se pudieron leer los movimientos: %s" % e)
        return
    if mv is None or mv.empty:
        st.info("No hay movimientos en ese rango.")
        return
    mv["cantidad"] = pd.to_numeric(mv["cantidad"], errors="coerce").fillna(0.0)
    v = mv.copy()
    if tipo != "(todos)":
        v = v[v["tipo"] == tipo]
    if txt:
        t = txt.strip().lower()
        m = pd.Series(False, index=v.index)
        for c in ("detalle", "codigo", "motivo", "destino", "proveedor", "remito", "usuario", "categoria"):
            m = m | v[c].astype(str).str.lower().str.contains(t, na=False, regex=False)
        v = v[m]

    vv = v[v["anulado"] == False]  # noqa: E712
    k1, k2, k3 = st.columns(3)
    k1.metric("Movimientos", int(len(vv)))
    k2.metric("📥 Ingresos", "%g" % float(vv[vv["tipo"] != "EGRESO"]["cantidad"].sum()))
    k3.metric("📤 Egresos", "%g" % float(vv[vv["tipo"] == "EGRESO"]["cantidad"].sum()))

    st.dataframe(v[["fecha", "tipo", "cantidad", "unidad", "codigo", "detalle", "categoria",
                    "motivo", "destino", "proveedor", "remito", "usuario", "nota", "anulado", "id_movimiento"]],
                 use_container_width=True, hide_index=True)
    _dl(v, "movimientos_repuestos.xlsx", "rep_h_dl")

    st.markdown("**Consumo por repuesto en el período**")
    res = vv.groupby(["codigo", "detalle", "unidad"], dropna=False).apply(
        lambda g: pd.Series({
            "ingresos": g[g["tipo"] != "EGRESO"]["cantidad"].sum(),
            "egresos": g[g["tipo"] == "EGRESO"]["cantidad"].sum()})).reset_index()
    if not res.empty:
        res["neto"] = res["ingresos"] - res["egresos"]
        res = res.sort_values("egresos", ascending=False)
        st.dataframe(res, use_container_width=True, hide_index=True)

    with st.expander("↩️ Anular un movimiento mal cargado"):
        ids = v[v["anulado"] == False]["id_movimiento"].tolist()  # noqa: E712
        if not ids:
            st.caption("Nada para anular en el filtro actual.")
        else:
            idm = st.selectbox("Movimiento", ids, index=None, key="rep_h_anul_id",
                               format_func=lambda i: "#%d · %s · %s %g · %s" % (
                                   i, v[v["id_movimiento"] == i].iloc[0]["fecha"],
                                   v[v["id_movimiento"] == i].iloc[0]["tipo"],
                                   v[v["id_movimiento"] == i].iloc[0]["cantidad"],
                                   v[v["id_movimiento"] == i].iloc[0]["detalle"][:50]))
            mot = st.text_input("Motivo de la anulación", key="rep_h_anul_mot")
            if st.button("↩️ Anular", key="rep_h_anul_go", disabled=(idm is None)):
                try:
                    _anular_mov(conectar, USR, idm, mot)
                    cat.clear()
                    st.success("Movimiento #%s anulado. El stock se recalculó." % idm)
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo anular: %s" % e)


def _vista_nuevo(USR, cat, conectar, df):
    st.subheader("➕ Nuevo repuesto")
    cats = _categorias(df)
    with st.form("rep_new", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 3, 1.4])
        cod = c1.text_input("Código")
        det = c2.text_input("Detalle * (así lo van a buscar)")
        ncat = c3.selectbox("Categoría", cats + ["➕ Nueva…"], index=None, placeholder="Elegí…")
        d1, d2, d3, d4 = st.columns(4)
        cat_new = d1.text_input("Categoría nueva (si elegiste ➕)")
        uni = d2.selectbox("Unidad", UNIDADES, index=0)
        mini = d3.number_input("Stock mínimo", min_value=0.0, step=1.0, value=0.0)
        ini = d4.number_input("Stock inicial", min_value=0.0, step=1.0, value=0.0)
        e1, e2, e3 = st.columns(3)
        ubi = e1.text_input("Ubicación (estantería, pañol)")
        equ = e2.text_input("Equipo / máquina")
        prov = e3.text_input("Proveedor habitual")
        obs = st.text_input("Observaciones")
        ok = st.form_submit_button("💾 Crear repuesto", type="primary", use_container_width=True)

    if ok:
        if not det or not det.strip():
            st.error("El detalle es obligatorio.")
            return
        categoria = cat_new.strip().upper() if (ncat == "➕ Nueva…" and cat_new.strip()) else (ncat if ncat and ncat != "➕ Nueva…" else "OTROS")
        try:
            nid = _alta_repuesto(conectar, USR, {
                "codigo": (cod.strip().upper() or None), "detalle": det.strip(), "categoria": categoria,
                "unidad": uni, "stock_minimo": mini, "ubicacion": (ubi.strip() or None),
                "equipo": (equ.strip() or None), "proveedor": (prov.strip() or None),
                "observaciones": (obs.strip() or None)})
            if nid is None:
                st.warning("Ya existía un repuesto con ese mismo detalle. No se duplicó.")
            else:
                if ini > 0:
                    _grabar_movs(conectar, USR, [{
                        "id_repuesto": int(nid), "tipo": "INGRESO", "cantidad": float(ini),
                        "fecha": date.today(), "motivo": "Ajuste de inventario", "destino": None,
                        "proveedor": (prov.strip() or None), "remito": None, "costo_unitario": None,
                        "nota": "stock inicial"}])
                cat.clear()
                st.balloons()
                st.success("✅ **%s** creado%s." % (det.strip(), (" con stock inicial %g %s" % (ini, uni)) if ini > 0 else ""))
                st.rerun()
        except Exception as e:
            st.error("No se pudo crear: %s" % e)

    with st.expander("📋 Alta masiva (pegar desde Excel)", expanded=False):
        st.caption("Columnas: código, detalle, categoría, unidad, mínimo, stock inicial, ubicación, equipo.")
        base = pd.DataFrame({"codigo": pd.Series(dtype="str"), "detalle": pd.Series(dtype="str"),
                             "categoria": pd.Series(dtype="str"), "unidad": pd.Series(dtype="str"),
                             "stock_minimo": pd.Series(dtype="float"), "stock_inicial": pd.Series(dtype="float"),
                             "ubicacion": pd.Series(dtype="str"), "equipo": pd.Series(dtype="str")})
        ed = st.data_editor(base, num_rows="dynamic", use_container_width=True, key="rep_new_bulk")
        if st.button("💾 Crear lote", key="rep_new_bulk_go", use_container_width=True):
            creados, saltados = 0, 0
            for _, row in ed.iterrows():
                det2 = str(row.get("detalle") or "").strip()
                if not det2:
                    continue
                try:
                    nid = _alta_repuesto(conectar, USR, {
                        "codigo": (str(row.get("codigo") or "").strip().upper() or None),
                        "detalle": det2,
                        "categoria": (str(row.get("categoria") or "OTROS").strip().upper() or "OTROS"),
                        "unidad": (str(row.get("unidad") or "UN").strip().upper() or "UN"),
                        "stock_minimo": float(row.get("stock_minimo") or 0),
                        "ubicacion": (str(row.get("ubicacion") or "").strip() or None),
                        "equipo": (str(row.get("equipo") or "").strip() or None),
                        "proveedor": None, "observaciones": None})
                    if nid is None:
                        saltados += 1
                        continue
                    q0 = float(row.get("stock_inicial") or 0)
                    if q0 > 0:
                        _grabar_movs(conectar, USR, [{
                            "id_repuesto": int(nid), "tipo": "INGRESO", "cantidad": q0,
                            "fecha": date.today(), "motivo": "Ajuste de inventario", "destino": None,
                            "proveedor": None, "remito": None, "costo_unitario": None,
                            "nota": "stock inicial (alta masiva)"}])
                    creados += 1
                except Exception as e:
                    st.error("Error con «%s»: %s" % (det2, e))
            if creados or saltados:
                cat.clear()
                st.success("✅ %d creado(s), %d ya existían." % (creados, saltados))
                st.rerun()


# -------------------------------------------------------------------- main --
def render(USR, cat, conectar):
    st.title("🔧 Repuestos")
    st.caption("Pañol de mantenimiento: ingresos, egresos, stock actual, mínimos y alertas.")

    try:
        df = _stock(cat)
    except Exception as e:
        st.error("No se pudo leer el stock de repuestos: %s" % e)
        st.caption("Verificá que existan las tablas `produccion.dim_repuesto` y `produccion.fact_repuesto_movimiento`.")
        return

    _banner_alertas(df)

    vista = st.segmented_control(
        "Vista", ["⚡ Movimiento", "📊 Stock actual", "🚨 Alertas", "🕐 Histórico", "➕ Nuevo repuesto"],
        default="⚡ Movimiento", key="rep_view", label_visibility="collapsed")
    if not vista:
        vista = "⚡ Movimiento"

    if vista.startswith("⚡"):
        _vista_movimiento(USR, cat, conectar, df)
    elif vista.startswith("📊"):
        _vista_stock(USR, cat, conectar, df)
    elif vista.startswith("🚨"):
        _vista_alertas(USR, cat, conectar, df)
    elif vista.startswith("🕐"):
        _vista_historial(USR, cat, conectar, df)
    else:
        _vista_nuevo(USR, cat, conectar, df)
