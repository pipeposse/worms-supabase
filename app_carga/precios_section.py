"""
Precios de referencia — Dirección.

Única pantalla donde se tocan los precios con los que la app valoriza TODO:
materia prima, productos finales, insumos y el tipo de cambio.

Dos precios por código:
  · Precio de exportación (normalmente USD/tn) — el que usa hoy toda la app
    para valorizar stock, despachos, rendimiento y costo de conversión.
  · Precio de mercado interno (normalmente ARS) — el que se cobra acá. Se carga
    en esta pantalla y se compara contra el de exportación para ver qué mercado
    conviene, pero todavía NO reemplaza al de exportación en el resto de la app:
    para eso falta marcar en cada despacho si la venta fue interna o export.

Todo cambio queda registrado en produccion.dim_precio_ref_hist por trigger de
base de datos (no por la app), así que ni un UPDATE manual por SQL se escapa.
"""

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
DIAS_PRECIO_VENCIDO = 30

ROL_ORDEN = ["FX", "MP", "FINAL", "INSUMO"]
ROL_TITULO = {
    "FX": "💱 Tipo de cambio",
    "MP": "🚛 Materia prima",
    "FINAL": "📦 Productos finales",
    "INSUMO": "🧪 Insumos de producción",
}
ROL_AYUDA = {
    "FX": "Pesos por dólar. Es el divisor de todo lo que se carga en ARS "
          "(fuel, glicerina, potasa) y de todo precio de mercado interno. Si queda "
          "atrasado, esos valores aparecen más caros en dólares de lo que realmente son.",
    "MP": "Lo que se paga por la materia prima que entra. Alimenta el costo de "
          "cada batch, la brecha de rendimiento y el agua que se paga como grasa.",
    "FINAL": "Lo que se cobra por el producto terminado. Alimenta el valor de "
             "lo despachado, el inventario valorizado y la salida sin respaldo.",
    "INSUMO": "Lo que cuesta cada insumo de proceso. Alimenta el costo de "
              "conversión de planta. Si además se vende (caso glicerina recuperada), "
              "cargale también el precio de mercado interno.",
}

UNIDADES = ["TN", "KG", "L", "USD"]
MONEDAS = ["USD", "ARS"]
MONEDAS_INT = ["ARS", "USD"]
DENSIDAD_DEFECTO = 0.9


def _num(x, d=0.0):
    try:
        if x is None or pd.isna(x):
            return d
        return float(x)
    except (TypeError, ValueError):
        return d


def _puede(USR):
    return str(USR.get("rol", "")).upper() in ROLES_DIRECCION


def _usuario(USR):
    return str(USR.get("nombre") or USR.get("id_usuario") or "?")


def _cargar(cat):
    """Precios vigentes + días desde la última actualización."""
    df = cat("SELECT codigo, rol, precio, unidad, moneda, descripcion, actualizado_en, "
             "usuario, precio_interno, moneda_interno, interno_actualizado_en "
             "FROM produccion.dim_precio_ref ORDER BY rol, codigo")
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["_al"] = pd.to_datetime(d["actualizado_en"], errors="coerce", utc=True)
    _hoy = pd.Timestamp.now(tz="UTC").normalize()
    d["_dias"] = (_hoy - d["_al"].dt.normalize()).dt.days
    for c in ("precio_interno", "moneda_interno"):
        if c not in d.columns:
            d[c] = None
    return d


def _tc(df):
    """Tipo de cambio vigente, o None si no está cargado."""
    if df is None or df.empty:
        return None
    _f = df[df["codigo"].astype(str) == "TC_USD"]
    if _f.empty:
        return None
    _v = _num(_f.iloc[0]["precio"], 0.0)
    return _v if _v > 0 else None


def _usd_t(precio, unidad, moneda, tc, densidad=DENSIDAD_DEFECTO):
    """Precio normalizado a USD por tonelada, misma lógica que v_dir_precio_producto.

    Se muestra para que quien carga vea el número con el que la app va a trabajar,
    y no el número que él tipeó. La mayoría de los errores de carga (kg en vez de
    tn, pesos en vez de dólares) se ven acá de un vistazo.
    """
    p = _num(precio, 0.0)
    if p <= 0:
        return None
    u = str(unidad or "").upper()
    m = str(moneda or "").upper()
    if m == "ARS":
        if not tc or tc <= 0:
            return None
        p = p / tc
    elif m != "USD":
        return None
    if u == "TN":
        return p
    if u == "KG":
        return p * 1000.0
    if u == "L":
        return p * 1000.0 / max(_num(densidad, DENSIDAD_DEFECTO) or DENSIDAD_DEFECTO, 0.01)
    return None


def _estado(dias):
    if dias is None or pd.isna(dias):
        return "⚫ sin fecha"
    d = int(dias)
    if d > DIAS_PRECIO_VENCIDO:
        return "🔴 %d d" % d
    if d > 15:
        return "🟡 %d d" % d
    return "🟢 %d d" % d


def _portada(df):
    st.subheader("💵 Precios de referencia")
    st.markdown(
        "Esta es la **única** tabla de precios de la aplicación. No hay precios escritos "
        "en el código. Todo dólar que aparece en Dirección, en el inventario valorizado y "
        "en el costo de conversión sale de acá.\n\n"
        "Cambiar un número acá **re-valoriza toda la app al instante**, hacia adelante y "
        "hacia atrás: los informes históricos también se recalculan, porque la app guarda "
        "toneladas y multiplica por el precio vigente.")
    if df is None or df.empty:
        st.warning("No hay precios cargados en `dim_precio_ref`. Toda la pantalla de "
                   "Dirección va a mostrar ceros hasta que se cargue al menos MP, FINAL y TC_USD.")
        return
    _venc = df[df["_dias"].isna() | (df["_dias"] > DIAS_PRECIO_VENCIDO)]
    _int = df[pd.to_numeric(df["precio_interno"], errors="coerce").notna()]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Códigos de precio", len(df))
    c2.metric("Vencidos (+%d d)" % DIAS_PRECIO_VENCIDO, len(_venc),
              delta=None if _venc.empty else "revisar", delta_color="inverse")
    c3.metric("Con precio interno", len(_int))
    _tcv = _tc(df)
    c4.metric("TC_USD", "—" if _tcv is None else "%s" % format(int(_tcv), ","))
    if not _venc.empty:
        st.error(
            "⚠️ **%d precio(s) llevan más de %d días sin tocarse**: " % (len(_venc), DIAS_PRECIO_VENCIDO)
            + ", ".join("`%s`" % c for c in _venc["codigo"].astype(str).head(10))
            + ".\n\nUn precio viejo no da error: da un número creíble y equivocado.")


def _guardar(USR, conectar, cat, cambios):
    """Aplica los cambios de precio. Devuelve True si escribió."""
    if not cambios:
        return False
    try:
        with conectar(USR["id_usuario"]) as (conn, audit):
            with conn.cursor() as cur:
                for c in cambios:
                    if c.get("toco_interno"):
                        cur.execute(
                            "UPDATE produccion.dim_precio_ref SET precio = %s, unidad = %s, "
                            "moneda = %s, descripcion = %s, precio_interno = %s, "
                            "moneda_interno = %s, interno_actualizado_en = now(), "
                            "interno_usuario = %s, actualizado_en = now(), usuario = %s "
                            "WHERE codigo = %s",
                            (c["precio"], c["unidad"], c["moneda"], c["descripcion"],
                             c["precio_interno"], c["moneda_interno"], _usuario(USR),
                             _usuario(USR), c["codigo"]))
                    else:
                        cur.execute(
                            "UPDATE produccion.dim_precio_ref SET precio = %s, unidad = %s, "
                            "moneda = %s, descripcion = %s, actualizado_en = now(), usuario = %s "
                            "WHERE codigo = %s",
                            (c["precio"], c["unidad"], c["moneda"], c["descripcion"],
                             _usuario(USR), c["codigo"]))
        cat.clear()
        return True
    except Exception as e:
        st.error("No se pudieron guardar los precios: %s" % e)
        return False


def _tabla_rol(_d, tc, con_interno):
    _e = pd.DataFrame({
        "Código": _d["codigo"].astype(str).values,
        "Descripción": _d["descripcion"].fillna("").astype(str).values,
        "Precio export": pd.to_numeric(_d["precio"], errors="coerce").values,
        "Unidad": _d["unidad"].fillna("").astype(str).values,
        "Moneda": _d["moneda"].fillna("").astype(str).values,
    })
    _e["USD/t export"] = [_usd_t(p, u, m, tc) for p, u, m in
                          zip(_e["Precio export"], _e["Unidad"], _e["Moneda"])]
    if con_interno:
        _e["Precio interno"] = pd.to_numeric(_d["precio_interno"], errors="coerce").values
        _e["Mon. int."] = _d["moneda_interno"].fillna("ARS").astype(str).values
        _e["USD/t interno"] = [_usd_t(p, u, m, tc) for p, u, m in
                               zip(_e["Precio interno"], _e["Unidad"], _e["Mon. int."])]
        _e["Interno vs export"] = [
            None if (a is None or b is None or not b) else (a / b - 1.0) * 100.0
            for a, b in zip(_e["USD/t interno"], _e["USD/t export"])]
    _e["Estado"] = [_estado(x) for x in _d["_dias"].values]
    return _e


def _config_cols(con_interno):
    cfg = {
        "Código": st.column_config.TextColumn(
            help="Identificador que usan las tablas de mapeo. No se edita acá: "
                 "renombrarlo rompe el vínculo con los productos."),
        "Descripción": st.column_config.TextColumn(
            help="Texto libre, para que el próximo que abra esto sepa a qué se refiere."),
        "Precio export": st.column_config.NumberColumn(
            format="%.2f",
            help="El precio con el que la app valoriza hoy TODO: stock, despachos, "
                 "rendimiento y conversión. Normalmente el precio de exportación en USD."),
        "USD/t export": st.column_config.NumberColumn(
            format="%.0f",
            help="QUÉ MIDE: el precio de exportación normalizado a dólares por tonelada, "
                 "que es lo que la app usa internamente. CÓMO SE CALCULA: USD/tn queda igual; "
                 "USD/kg ×1000; ARS ÷ TC_USD; por litro además ÷ densidad 0,9. "
                 "OJO: se recalcula al guardar, no mientras tipeás."),
        "Estado": st.column_config.TextColumn(
            help="Días desde la última actualización. 🟢 hasta 15 d, 🟡 hasta 30 d, "
                 "🔴 más de 30 d, ⚫ nunca se registró fecha."),
    }
    if con_interno:
        cfg["Precio interno"] = st.column_config.NumberColumn(
            format="%.2f",
            help="Lo que se cobra en el mercado local, en la misma unidad que la columna "
                 "Unidad. Dejalo vacío si ese producto no se vende acá. "
                 "OJO: hoy es informativo — la app sigue valorizando con el precio de export "
                 "porque todavía no se marca en el despacho si la venta fue interna.")
        cfg["USD/t interno"] = st.column_config.NumberColumn(
            format="%.0f", help="El precio interno llevado a dólares por tonelada con "
                                "TC_USD, para poder compararlo contra el de exportación.")
        cfg["Interno vs export"] = st.column_config.NumberColumn(
            format="%.1f%%",
            help="Cuánto paga de más (+) o de menos (−) el mercado interno respecto del "
                 "de exportación, ya neteado el tipo de cambio. Es el número que dice a "
                 "qué mercado conviene mandar el producto, antes de flete y retenciones.")
    return cfg


def _bloque_rol(USR, cat, conectar, df, rol, tc):
    _d = df[df["rol"].astype(str).str.upper() == rol]
    if _d.empty:
        return
    con_interno = rol != "FX"
    st.markdown("#### %s" % ROL_TITULO.get(rol, rol))
    st.caption(ROL_AYUDA.get(rol, ""))

    _e = _tabla_rol(_d, tc, con_interno)
    _cfg = _config_cols(con_interno)
    _orig = {}
    for _, r in _e.iterrows():
        _orig[str(r["Código"])] = (
            r["Precio export"], str(r["Unidad"]), str(r["Moneda"]), str(r["Descripción"]),
            r["Precio interno"] if con_interno else None,
            str(r["Mon. int."]) if con_interno else None)

    _bloq = ["Código", "USD/t export", "USD/t interno", "Interno vs export", "Estado"]
    if not _puede(USR):
        st.dataframe(_e, hide_index=True, use_container_width=True, column_config=_cfg)
        return

    _cfg_ed = dict(_cfg)
    _cfg_ed["Unidad"] = st.column_config.SelectboxColumn(
        options=UNIDADES,
        help="TN = por tonelada, KG = por kilo, L = por litro. Vale para las dos columnas "
             "de precio: si el export es por tonelada, el interno también.")
    _cfg_ed["Moneda"] = st.column_config.SelectboxColumn(
        options=MONEDAS,
        help="Si es ARS, el precio se convierte con TC_USD cada vez que se muestra.")
    if con_interno:
        _cfg_ed["Mon. int."] = st.column_config.SelectboxColumn(
            options=MONEDAS_INT,
            help="Moneda del precio de mercado interno. Casi siempre ARS.")
    try:
        _ed = st.data_editor(_e, hide_index=True, use_container_width=True,
                             key="px_ed_%s" % rol, disabled=_bloq, column_config=_cfg_ed)
    except Exception:
        st.dataframe(_e, hide_index=True, use_container_width=True, column_config=_cfg)
        st.caption("El editor no está disponible en esta versión de Streamlit.")
        return
    if _ed is None:
        return

    _cambios = []
    for _, r in _ed.iterrows():
        _cod = str(r["Código"])
        _o = _orig.get(_cod)
        if _o is None:
            continue
        _p = r["Precio export"]
        if _p is None or pd.isna(_p):
            continue
        _p = float(_p)
        _u = str(r["Unidad"] or "").upper()
        _m = str(r["Moneda"] or "").upper()
        _ds = str(r["Descripción"] or "")
        _pi = r["Precio interno"] if con_interno else None
        _pi = None if (_pi is None or pd.isna(_pi)) else float(_pi)
        _mi = (str(r["Mon. int."] or "ARS").upper() if con_interno else None)
        _op, _ou, _om, _od, _opi, _omi = _o
        _opi = None if (_opi is None or pd.isna(_opi)) else float(_opi)
        _toco_int = con_interno and (
            (_pi is None) != (_opi is None)
            or (_pi is not None and _opi is not None and abs(_pi - _opi) > 1e-9)
            or (_mi or "") != (str(_omi or "ARS").upper()))
        _toco_exp = (_op is None or pd.isna(_op) or abs(_p - float(_op)) > 1e-9
                     or _u != _ou.upper() or _m != _om.upper() or _ds != _od)
        if not (_toco_exp or _toco_int):
            continue
        if _p <= 0:
            st.warning("`%s`: el precio de exportación debe ser mayor a cero. Se ignora." % _cod)
            continue
        if _pi is not None and _pi <= 0:
            st.warning("`%s`: el precio interno debe ser mayor a cero, o vacío. Se ignora." % _cod)
            continue
        _cambios.append({
            "codigo": _cod, "precio": _p, "unidad": _u or None, "moneda": _m or None,
            "descripcion": _ds or None, "precio_interno": _pi,
            "moneda_interno": (_mi or "ARS") if _pi is not None else None,
            "toco_interno": _toco_int,
            "usd_t": _usd_t(_p, _u, _m, tc),
            "usd_t_int": _usd_t(_pi, _u, _mi, tc) if _pi is not None else None})
    if not _cambios:
        return

    _det = []
    for c in _cambios:
        _t = "- `%s` → export **%s %s/%s**" % (
            c["codigo"], format(round(c["precio"], 2), ","), c["unidad"] or "?", c["moneda"] or "?")
        if c["usd_t"]:
            _t += " (USD %s/t)" % format(int(round(c["usd_t"])), ",")
        if c["toco_interno"]:
            if c["precio_interno"] is None:
                _t += "  ·  interno: **se borra**"
            else:
                _t += "  ·  interno **%s %s/%s**" % (
                    format(round(c["precio_interno"], 2), ","), c["moneda_interno"], c["unidad"] or "?")
                if c["usd_t_int"]:
                    _t += " (USD %s/t)" % format(int(round(c["usd_t_int"])), ",")
        _det.append(_t)
    st.warning("**Cambios sin guardar en %s**\n\n%s" % (ROL_TITULO.get(rol, rol), "\n".join(_det)))
    if st.button("💾 Guardar %d cambio(s)" % len(_cambios), key="px_save_%s" % rol, type="primary"):
        if _guardar(USR, conectar, cat, _cambios):
            st.success("%d precio(s) actualizado(s) y registrados en el historial." % len(_cambios))
            try:
                st.rerun()
            except Exception:
                pass


def _cobertura(USR, cat, conectar, df):
    """Productos activos sin precio.

    Un producto sin precio no da error: se valoriza en cero y desaparece de los
    totales en dólares sin dejar rastro. Ese es el peor tipo de error, porque el
    número sigue apareciendo prolijo. Por eso se listan explícitamente.
    """
    st.markdown("#### 🧭 Cobertura: qué producto tiene precio y cuál no")
    try:
        _c = cat("SELECT codigo_producto, nombre_producto, tipo_producto, codigo_precio, "
                 "precio_export, unidad, moneda, precio_interno, sin_precio "
                 "FROM produccion.v_dir_precio_cobertura")
    except Exception as e:
        st.caption("No se pudo leer la cobertura: %s" % e)
        return
    if _c is None or _c.empty:
        st.caption("Sin productos activos.")
        return
    _sin = _c[_c["sin_precio"] == True]  # noqa: E712
    _con = _c[_c["sin_precio"] != True]  # noqa: E712
    c1, c2 = st.columns(2)
    c1.metric("Productos activos con precio", len(_con))
    c2.metric("Sin precio", len(_sin), delta=None if _sin.empty else "valorizan en cero",
              delta_color="inverse")

    if not _sin.empty:
        st.warning(
            "**%d producto(s) activos no tienen ningún precio asignado.** Cada tonelada "
            "que entra o sale de estos productos vale USD 0 para la app: no aparece en el "
            "inventario valorizado ni en el costo de conversión, y nada avisa." % len(_sin))
        st.dataframe(
            _sin[["codigo_producto", "nombre_producto", "tipo_producto"]],
            hide_index=True, use_container_width=True,
            column_config={
                "codigo_producto": st.column_config.TextColumn("Código"),
                "nombre_producto": st.column_config.TextColumn("Producto"),
                "tipo_producto": st.column_config.TextColumn("Tipo")})
        _asignar(USR, cat, conectar, df, _sin)
    else:
        st.success("Todos los productos activos tienen un precio asignado.")

    with st.expander("Ver los que sí tienen precio (%d)" % len(_con)):
        st.caption("Varios productos comparten un mismo código de precio a propósito: "
                   "todas las borras y sebos usan AG-C, que es la referencia más "
                   "conservadora de la familia. Se subvalúan a propósito antes que inflarlos.")
        st.dataframe(
            _con[["codigo_producto", "nombre_producto", "tipo_producto", "codigo_precio",
                  "precio_export", "moneda", "precio_interno"]],
            hide_index=True, use_container_width=True,
            column_config={
                "codigo_producto": st.column_config.TextColumn("Código"),
                "nombre_producto": st.column_config.TextColumn("Producto"),
                "tipo_producto": st.column_config.TextColumn("Tipo"),
                "codigo_precio": st.column_config.TextColumn(
                    "Usa el precio", help="Código de dim_precio_ref con el que se valoriza."),
                "precio_export": st.column_config.NumberColumn("Export", format="%.2f"),
                "moneda": st.column_config.TextColumn("Mon."),
                "precio_interno": st.column_config.NumberColumn("Interno", format="%.2f")})


def _asignar(USR, cat, conectar, df, sin_precio):
    """Vincula un producto sin precio a un código existente (dim_precio_map)."""
    if not _puede(USR) or conectar is None:
        return
    with st.expander("🔗 Asignarle un precio a uno de estos productos"):
        st.caption("Elegí el producto y a qué código de precio se parece. No hace falta "
                   "crear un código nuevo para cada producto: si el precio es el mismo, "
                   "conviene reusarlo, así se actualiza en un solo lugar.")
        _prods = list(sin_precio["codigo_producto"].astype(str))
        _cods = list(df["codigo"].astype(str)) if df is not None and not df.empty else []
        if not _prods or not _cods:
            return
        c1, c2, c3 = st.columns(3)
        _p = c1.selectbox("Producto sin precio", _prods, key="px_map_prod")
        _c = c2.selectbox("Código de precio a usar", _cods, key="px_map_cod")
        _dens = c3.number_input("Densidad", min_value=0.1, max_value=2.0,
                                value=DENSIDAD_DEFECTO, step=0.01, key="px_map_dens")
        st.caption("La densidad solo se usa cuando el precio está por litro, para pasar "
                   "de litros a kilos. Si el precio es por tonelada, es indiferente.")
        if not st.button("Vincular", key="px_map_btn"):
            return
        try:
            with conectar(USR["id_usuario"]) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO produccion.dim_precio_map "
                        "(codigo_producto, codigo_precio, densidad_ref, nota) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT (codigo_producto) DO UPDATE "
                        "SET codigo_precio = EXCLUDED.codigo_precio, "
                        "densidad_ref = EXCLUDED.densidad_ref, nota = EXCLUDED.nota",
                        (_p, _c, float(_dens), "asignado desde Dirección por %s" % _usuario(USR)))
            cat.clear()
            st.success("`%s` ahora se valoriza con `%s`." % (_p, _c))
            try:
                st.rerun()
            except Exception:
                pass
        except Exception as e:
            st.error("No se pudo vincular: %s" % e)


def _alta(USR, cat, conectar, df):
    """Alta de un código de precio nuevo."""
    if not _puede(USR) or conectar is None:
        return
    with st.expander("➕ Crear un código de precio nuevo"):
        st.caption(
            "Crear el código es solo la mitad: después hay que vincularle al menos un "
            "producto, arriba en *Cobertura*. Un código suelto no rompe nada, pero "
            "tampoco valoriza nada.")
        c1, c2 = st.columns(2)
        _cod = str(c1.text_input("Código", key="px_new_cod", placeholder="Ej: CAUCHO") or "").strip().upper()
        _rol = c2.selectbox("Rol", ["MP", "FINAL", "INSUMO", "FX"], key="px_new_rol")
        c3, c4, c5 = st.columns(3)
        _pre = c3.number_input("Precio exportación", min_value=0.0, value=0.0, step=1.0, key="px_new_pre")
        _uni = c4.selectbox("Unidad", UNIDADES, key="px_new_uni")
        _mon = c5.selectbox("Moneda", MONEDAS, key="px_new_mon")
        c6, c7 = st.columns(2)
        _pint = c6.number_input("Precio mercado interno (0 = no aplica)", min_value=0.0,
                                value=0.0, step=1.0, key="px_new_pint")
        _mint = c7.selectbox("Moneda interna", MONEDAS_INT, key="px_new_mint")
        _des = st.text_input("Descripción", key="px_new_des",
                             placeholder="Qué es y con quién se negocia")
        _tcv = _tc(df)
        _u1 = _usd_t(_pre, _uni, _mon, _tcv)
        _u2 = _usd_t(_pint, _uni, _mint, _tcv)
        if _u1 or _u2:
            _txt = []
            if _u1:
                _txt.append("export **USD %s/t**" % format(int(round(_u1)), ","))
            if _u2:
                _txt.append("interno **USD %s/t**" % format(int(round(_u2)), ","))
            st.caption("Equivale a " + " · ".join(_txt) + ".")
        if not st.button("Crear código", key="px_new_btn"):
            return
        if not _cod:
            st.error("Falta el código.")
            return
        if df is not None and not df.empty and _cod in set(df["codigo"].astype(str)):
            st.error("`%s` ya existe. Editalo en la tabla de arriba." % _cod)
            return
        if _pre <= 0:
            st.error("El precio de exportación tiene que ser mayor a cero. Si el producto "
                     "solo se vende acá, cargá el mismo valor en ambos.")
            return
        try:
            with conectar(USR["id_usuario"]) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO produccion.dim_precio_ref "
                        "(codigo, rol, precio, unidad, moneda, descripcion, precio_interno, "
                        "moneda_interno, actualizado_en, usuario, interno_actualizado_en, "
                        "interno_usuario) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, "
                        "now(), %s)",
                        (_cod, _rol, float(_pre), _uni, _mon, _des or None,
                         float(_pint) if _pint > 0 else None,
                         _mint if _pint > 0 else None, _usuario(USR), _usuario(USR)))
            cat.clear()
            st.success("`%s` creado. Ahora asignale productos en *Cobertura*." % _cod)
            try:
                st.rerun()
            except Exception:
                pass
        except Exception as e:
            st.error("No se pudo crear el código: %s" % e)


def _historial(cat):
    st.markdown("#### 🧾 Historial de cambios")
    st.caption(
        "Lo registra la base de datos con un trigger, no la app: aunque alguien cambie un "
        "precio por SQL directo, queda acá. Sirve para responder, dentro de seis meses, "
        "por qué un informe viejo no da lo mismo que hoy.")
    try:
        _h = cat("SELECT momento, codigo, rol, accion, precio_anterior, precio_nuevo, "
                 "variacion_pct, precio_interno_anterior, precio_interno_nuevo, "
                 "variacion_interno_pct, unidad, moneda, usuario "
                 "FROM produccion.v_dir_precio_hist LIMIT 200")
    except Exception as e:
        st.caption("No se pudo leer el historial: %s" % e)
        return
    if _h is None or _h.empty:
        st.info("Todavía no hay cambios registrados. El historial arranca desde que se "
                "instaló el trigger; no incluye la carga inicial.")
        return
    _v = _h.copy()
    try:
        _v["momento"] = pd.to_datetime(_v["momento"], errors="coerce", utc=True) \
            .dt.strftime("%d-%m-%Y %H:%M")
    except Exception:
        pass
    st.dataframe(
        _v, hide_index=True, use_container_width=True,
        column_config={
            "momento": st.column_config.TextColumn("Cuándo"),
            "codigo": st.column_config.TextColumn("Código"),
            "rol": st.column_config.TextColumn("Rol"),
            "accion": st.column_config.TextColumn(
                "Acción", help="ALTA = código nuevo. CAMBIO = se modificó precio, unidad "
                               "o moneda. BAJA = se eliminó el código."),
            "precio_anterior": st.column_config.NumberColumn("Export antes", format="%.2f"),
            "precio_nuevo": st.column_config.NumberColumn("Export después", format="%.2f"),
            "variacion_pct": st.column_config.NumberColumn("Var. %", format="%.1f%%"),
            "precio_interno_anterior": st.column_config.NumberColumn("Int. antes", format="%.2f"),
            "precio_interno_nuevo": st.column_config.NumberColumn("Int. después", format="%.2f"),
            "variacion_interno_pct": st.column_config.NumberColumn("Var. int. %", format="%.1f%%"),
            "unidad": st.column_config.TextColumn("Unidad"),
            "moneda": st.column_config.TextColumn("Moneda"),
            "usuario": st.column_config.TextColumn("Quién")})


def _cierre():
    st.caption(
        "El precio de mercado interno todavía es **informativo**: sirve para comparar "
        "contra el de exportación, pero la app sigue valorizando stock y despachos con el "
        "precio de export. Para que el interno pese de verdad hay que marcar en cada "
        "despacho si la venta fue interna o de exportación — decime y lo agrego.")


def render(USR, cat, conectar):
    df = _cargar(cat)
    _portada(df)
    if df is None or df.empty:
        _alta(USR, cat, conectar, df)
        return
    if not _puede(USR):
        st.info("Solo Dirección puede modificar precios. Abajo se muestran los vigentes.")
    st.divider()
    tc = _tc(df)
    if tc is None:
        st.warning("Falta `TC_USD`. Todo lo cargado en pesos (fuel, glicerina, potasa) y "
                   "todo precio de mercado interno no se puede convertir a dólares.")
    for rol in ROL_ORDEN:
        _bloque_rol(USR, cat, conectar, df, rol, tc)
        st.write("")
    _otros = df[~df["rol"].astype(str).str.upper().isin(ROL_ORDEN)]
    if not _otros.empty:
        st.markdown("#### Otros")
        st.dataframe(_otros[["codigo", "rol", "precio", "unidad", "moneda"]],
                     hide_index=True, use_container_width=True)
    _alta(USR, cat, conectar, df)
    st.divider()
    _cobertura(USR, cat, conectar, df)
    st.divider()
    _historial(cat)
    _cierre()
