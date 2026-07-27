"""
Precios de referencia — Dirección.

Única pantalla donde se tocan los precios con los que la app valoriza TODO:
materia prima, productos finales, insumos y el tipo de cambio.

Por qué existe separada del Control de gestión: los precios son un dato
comercial, no un dato de planta. Los carga quien conoce el mercado, no quien
mira los KPIs. Y si el precio está mal, no se rompe nada visible — simplemente
todos los dólares de la app quedan mal, en silencio, prolijos.

Todo cambio queda registrado en produccion.dim_precio_ref_hist por trigger de
base de datos (no por la app), así que ni un UPDATE manual por SQL se escapa.
"""

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
DIAS_PRECIO_VENCIDO = 30

VERDE = "#16a34a"
AMBAR = "#b45309"
ROJO = "#dc2626"
GRIS = "#64748b"

ROL_ORDEN = ["FX", "MP", "FINAL", "INSUMO"]
ROL_TITULO = {
    "FX": "💱 Tipo de cambio",
    "MP": "🚛 Materia prima",
    "FINAL": "📦 Productos finales",
    "INSUMO": "🧪 Insumos de producción",
}
ROL_AYUDA = {
    "FX": "Pesos por dólar. Es el divisor de todo lo que se carga en ARS "
          "(fuel, glicerina, potasa). Si queda atrasado, esos insumos aparecen "
          "más caros en dólares de lo que realmente son.",
    "MP": "Lo que se paga por la materia prima que entra. Alimenta el costo de "
          "cada batch, la brecha de rendimiento y el agua que se paga como grasa.",
    "FINAL": "Lo que se cobra por el producto terminado. Alimenta el valor de "
             "lo despachado, el inventario valorizado y la salida sin respaldo.",
    "INSUMO": "Lo que cuesta cada insumo de proceso. Alimenta el costo de "
              "conversión de planta.",
}

UNIDADES = ["TN", "KG", "L", "USD"]
MONEDAS = ["USD", "ARS"]


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
    df = cat("SELECT codigo, rol, precio, unidad, moneda, descripcion, "
             "actualizado_en, usuario FROM produccion.dim_precio_ref "
             "ORDER BY rol, codigo")
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["_al"] = pd.to_datetime(d["actualizado_en"], errors="coerce", utc=True)
    _hoy = pd.Timestamp.now(tz="UTC").normalize()
    d["_dias"] = (_hoy - d["_al"].dt.normalize()).dt.days
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


def _usd_t(precio, unidad, moneda, tc, densidad=0.9):
    """Precio normalizado a USD por tonelada, misma lógica que v_dir_precio_producto.

    Se muestra para que quien carga vea el número con el que la app va a
    trabajar, y no el número que él tipeó. La mayoría de los errores de carga
    (kg en vez de tn, pesos en vez de dólares) se ven acá de un vistazo.
    """
    p = _num(precio, 0.0)
    if p <= 0:
        return None
    u = str(unidad or "").upper()
    m = str(moneda or "").upper()
    if m == "ARS":
        if not tc or tc <= 0:
            return None
        if u == "KG":
            return p * 1000.0 / tc
        if u == "L":
            return p * 1000.0 / tc / max(densidad, 0.01)
        if u == "TN":
            return p / tc
        return None
    if m == "USD":
        if u == "TN":
            return p
        if u == "KG":
            return p * 1000.0
        if u == "L":
            return p * 1000.0 / max(densidad, 0.01)
    return None


def _estado(dias):
    if dias is None or pd.isna(dias):
        return "⚫ sin fecha"
    d = int(dias)
    if d > DIAS_PRECIO_VENCIDO:
        return f"🔴 {d} d"
    if d > 15:
        return f"🟡 {d} d"
    return f"🟢 {d} d"


def _portada(df):
    st.subheader("💵 Precios de referencia")
    st.markdown(
        "Esta es la **única** tabla de precios de la aplicación. No hay precios escritos "
        "en el código. Todo dólar que aparece en Dirección, en el inventario valorizado y "
        "en el costo de conversión sale de acá.\n\n"
        "Cambiar un número en esta pantalla **re-valoriza toda la app al instante**, "
        "hacia adelante y hacia atrás: los informes históricos también se recalculan, "
        "porque la app guarda toneladas y multiplica por el precio vigente. "
        "Si necesitás que el pasado quede con el precio viejo, avisá — eso es otro diseño.")
    if df is None or df.empty:
        st.warning("No hay precios cargados en `dim_precio_ref`. Toda la pantalla de "
                   "Dirección va a mostrar ceros hasta que se cargue al menos MP, FINAL y TC_USD.")
        return
    _venc = df[df["_dias"].isna() | (df["_dias"] > DIAS_PRECIO_VENCIDO)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Precios cargados", len(df))
    c2.metric("Vencidos (+%d d)" % DIAS_PRECIO_VENCIDO, len(_venc),
              delta=None if _venc.empty else "revisar", delta_color="inverse")
    _tcv = _tc(df)
    c3.metric("TC_USD", "—" if _tcv is None else f"{_tcv:,.0f}")
    if not _venc.empty:
        st.error(
            f"⚠️ **{len(_venc)} precio(s) llevan más de {DIAS_PRECIO_VENCIDO} días sin tocarse**: "
            + ", ".join(f"`{c}`" for c in _venc["codigo"].astype(str).head(10))
            + ".\n\nUn precio viejo no da error: da un número creíble y equivocado.")


def _guardar(USR, conectar, cat, cambios):
    """Aplica los cambios de precio. Devuelve True si escribió."""
    if not cambios:
        return False
    try:
        with conectar(USR["id_usuario"]) as (conn, audit):
            with conn.cursor() as cur:
                for c in cambios:
                    cur.execute(
                        "UPDATE produccion.dim_precio_ref SET precio = %s, unidad = %s, "
                        "moneda = %s, descripcion = %s, actualizado_en = now(), usuario = %s "
                        "WHERE codigo = %s",
                        (c["precio"], c["unidad"], c["moneda"], c["descripcion"],
                         _usuario(USR), c["codigo"]))
        cat.clear()
        return True
    except Exception as e:
        st.error(f"No se pudieron guardar los precios: {e}")
        return False


def _bloque_rol(USR, cat, conectar, df, rol, tc):
    _d = df[df["rol"].astype(str).str.upper() == rol]
    if _d.empty:
        return
    st.markdown(f"#### {ROL_TITULO.get(rol, rol)}")
    st.caption(ROL_AYUDA.get(rol, ""))

    _e = pd.DataFrame({
        "Código": _d["codigo"].astype(str).values,
        "Descripción": _d["descripcion"].fillna("").astype(str).values,
        "Precio": pd.to_numeric(_d["precio"], errors="coerce").values,
        "Unidad": _d["unidad"].fillna("").astype(str).values,
        "Moneda": _d["moneda"].fillna("").astype(str).values,
    })
    _e["USD/t (calculado)"] = [
        _usd_t(p, u, m, tc) for p, u, m in
        zip(_e["Precio"], _e["Unidad"], _e["Moneda"])]
    _e["Estado"] = [_estado(x) for x in _d["_dias"].values]
    _e["Últ. cambio"] = _d["usuario"].fillna("—").astype(str).values

    _orig = {}
    for _, r in _e.iterrows():
        _orig[str(r["Código"])] = (r["Precio"], str(r["Unidad"]),
                                   str(r["Moneda"]), str(r["Descripción"]))

    _cfg = {
        "Código": st.column_config.TextColumn(
            help="Identificador que usan las tablas de mapeo. No se puede cambiar acá: "
                 "renombrar un código rompe el vínculo con los productos."),
        "Descripción": st.column_config.TextColumn(
            help="Texto libre para que el próximo que abra esto sepa a qué se refiere."),
        "Precio": st.column_config.NumberColumn(
            format="%.2f",
            help="El número tal cual se negocia, en la unidad y moneda de las columnas de al lado."),
        "USD/t (calculado)": st.column_config.NumberColumn(
            format="%.0f",
            help="QUÉ MIDE: el precio normalizado a dólares por tonelada, que es lo que "
                 "la app usa internamente. CÓMO SE CALCULA: USD/tn queda igual; USD/kg ×1000; "
                 "ARS/kg ×1000 ÷ TC_USD; ARS/L ×1000 ÷ TC_USD ÷ densidad 0,9. "
                 "OJO: se recalcula recién al guardar, no mientras tipeás."),
        "Estado": st.column_config.TextColumn(
            help="Días desde la última actualización. 🟢 hasta 15 d, 🟡 hasta 30 d, "
                 "🔴 más de 30 d, ⚫ nunca se registró fecha."),
        "Últ. cambio": st.column_config.TextColumn(help="Quién lo tocó por última vez."),
    }
    _bloqueadas = ["Código", "USD/t (calculado)", "Estado", "Últ. cambio"]

    if not _puede(USR):
        st.dataframe(_e, hide_index=True, use_container_width=True, column_config=_cfg)
        return

    try:
        _ed = st.data_editor(
            _e, hide_index=True, use_container_width=True,
            key=f"px_ed_{rol}", disabled=_bloqueadas,
            column_config=dict(
                _cfg,
                Unidad=st.column_config.SelectboxColumn(
                    options=UNIDADES,
                    help="TN = por tonelada, KG = por kilo, L = por litro. "
                         "USD solo para el tipo de cambio."),
                Moneda=st.column_config.SelectboxColumn(
                    options=MONEDAS,
                    help="Si es ARS, el precio se convierte con TC_USD cada vez que se muestra.")))
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
        _p = r["Precio"]
        if _p is None or pd.isna(_p):
            continue
        _p = float(_p)
        _u = str(r["Unidad"] or "").upper()
        _m = str(r["Moneda"] or "").upper()
        _ds = str(r["Descripción"] or "")
        _op, _ou, _om, _od = _o
        if (_op is None or pd.isna(_op) or abs(_p - float(_op)) > 1e-9
                or _u != _ou.upper() or _m != _om.upper() or _ds != _od):
            if _p <= 0:
                st.warning(f"`{_cod}`: el precio debe ser mayor a cero. Se ignora ese cambio.")
                continue
            _cambios.append({"codigo": _cod, "precio": _p, "unidad": _u or None,
                             "moneda": _m or None, "descripcion": _ds or None,
                             "usd_t": _usd_t(_p, _u, _m, tc)})
    if not _cambios:
        return

    st.warning("**Cambios sin guardar en " + ROL_TITULO.get(rol, rol) + "**\n\n" + "\n".join(
        "- `{c}` → {p:,.2f} {u}/{m}{x}".format(
            c=c["codigo"], p=c["precio"], u=c["unidad"] or "?", m=c["moneda"] or "?",
            x="" if c["usd_t"] is None else f"  ·  equivale a **USD {c['usd_t']:,.0f}/t**")
        for c in _cambios))
    if st.button(f"💾 Guardar {len(_cambios)} cambio(s)", key=f"px_save_{rol}", type="primary"):
        if _guardar(USR, conectar, cat, _cambios):
            st.success(f"{len(_cambios)} precio(s) actualizado(s) y registrados en el historial.")
            try:
                st.rerun()
            except Exception:
                pass


def _alta(USR, cat, conectar, df):
    """Alta de un código nuevo.

    Es una operación cara: un código que nadie mapea a un producto no valoriza
    nada y solo ensucia la tabla. Por eso queda plegado y con el aviso explícito
    de que hay un segundo paso en dim_precio_map.
    """
    if not _puede(USR) or conectar is None:
        return
    with st.expander("➕ Dar de alta un código de precio nuevo"):
        st.caption(
            "Crear el código es solo la mitad. Para que un producto se valorice hay que "
            "vincularlo después en `dim_precio_map` (producto → código de precio) o en "
            "`dic_flujo_porteria`. Un código suelto no rompe nada, pero tampoco hace nada.")
        c1, c2 = st.columns(2)
        _cod = c1.text_input("Código", key="px_new_cod",
                             placeholder="Ej: AG-D").strip().upper()
        _rol = c2.selectbox("Rol", ["MP", "FINAL", "INSUMO", "FX"], key="px_new_rol")
        c3, c4, c5 = st.columns(3)
        _pre = c3.number_input("Precio", min_value=0.0, value=0.0, step=1.0, key="px_new_pre")
        _uni = c4.selectbox("Unidad", UNIDADES, key="px_new_uni")
        _mon = c5.selectbox("Moneda", MONEDAS, key="px_new_mon")
        _des = st.text_input("Descripción", key="px_new_des",
                             placeholder="Qué es y con quién se negocia")
        _usd = _usd_t(_pre, _uni, _mon, _tc(df))
        if _usd:
            st.caption(f"Equivale a **USD {_usd:,.0f} por tonelada**.")
        if not st.button("Crear código", key="px_new_btn"):
            return
        if not _cod:
            st.error("Falta el código.")
            return
        if df is not None and not df.empty and _cod in set(df["codigo"].astype(str)):
            st.error(f"`{_cod}` ya existe. Editalo en la tabla de arriba.")
            return
        if _pre <= 0:
            st.error("El precio tiene que ser mayor a cero.")
            return
        try:
            with conectar(USR["id_usuario"]) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO produccion.dim_precio_ref "
                        "(codigo, rol, precio, unidad, moneda, descripcion, actualizado_en, usuario) "
                        "VALUES (%s, %s, %s, %s, %s, %s, now(), %s)",
                        (_cod, _rol, float(_pre), _uni, _mon, _des or None, _usuario(USR)))
            cat.clear()
            st.success(f"`{_cod}` creado. Ahora falta vincularlo a un producto en `dim_precio_map`.")
            try:
                st.rerun()
            except Exception:
                pass
        except Exception as e:
            st.error(f"No se pudo crear el código: {e}")


def _mapeo(cat):
    with st.expander("🔗 Qué producto usa qué precio"):
        st.caption(
            "Esta tabla es la que decide, para cada producto, qué precio se le aplica. "
            "Si un producto no aparece acá, la app cae al precio más conservador de su "
            "familia — es decir, lo subvalúa a propósito antes que inflarlo.")
        try:
            _m = cat("SELECT codigo_producto, codigo_precio, densidad_ref "
                     "FROM produccion.dim_precio_map ORDER BY codigo_precio, codigo_producto")
        except Exception:
            _m = None
        if _m is None or _m.empty:
            st.caption("Sin mapeos cargados.")
            return
        st.dataframe(
            _m, hide_index=True, use_container_width=True,
            column_config={
                "codigo_producto": st.column_config.TextColumn(
                    "Producto", help="Código tal como se carga en planta."),
                "codigo_precio": st.column_config.TextColumn(
                    "Precio que usa", help="Código de dim_precio_ref con el que se valoriza."),
                "densidad_ref": st.column_config.NumberColumn(
                    "Densidad", format="%.3f",
                    help="Solo se usa cuando el precio está en litros, para pasar de L a kg."),
            })


def _historial(cat):
    st.markdown("#### 🧾 Historial de cambios")
    st.caption(
        "Lo registra la base de datos con un trigger, no la app: aunque alguien cambie un "
        "precio por SQL directo, queda acá. Sirve para responder, dentro de seis meses, "
        "por qué un informe viejo no da lo mismo que hoy.")
    try:
        _h = cat("SELECT momento, codigo, rol, accion, precio_anterior, precio_nuevo, "
                 "variacion_pct, unidad, moneda, usuario "
                 "FROM produccion.v_dir_precio_hist LIMIT 200")
    except Exception as e:
        st.caption(f"No se pudo leer el historial: {e}")
        return
    if _h is None or _h.empty:
        st.info("Todavía no hay cambios registrados. El historial arranca desde que se "
                "instaló el trigger, no incluye la carga inicial.")
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
            "precio_anterior": st.column_config.NumberColumn("Antes", format="%.2f"),
            "precio_nuevo": st.column_config.NumberColumn("Después", format="%.2f"),
            "variacion_pct": st.column_config.NumberColumn(
                "Var. %", format="%.1f%%",
                help="Cuánto se movió respecto del valor anterior. Vacío en altas y bajas."),
            "unidad": st.column_config.TextColumn("Unidad"),
            "moneda": st.column_config.TextColumn("Moneda"),
            "usuario": st.column_config.TextColumn("Quién"),
        })


def _cierre():
    st.caption(
        "Regla práctica: revisar esta pantalla cuando cambia una condición comercial "
        "(nuevo contrato, salto del dólar, cambio de proveedor de insumo), no en una fecha fija. "
        "El semáforo de días es un recordatorio, no un vencimiento real.")


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
        st.warning("Falta `TC_USD`. Todo lo cargado en pesos (fuel, glicerina, potasa) "
                   "no se puede convertir a dólares y aparece en cero.")
    for rol in ROL_ORDEN:
        _bloque_rol(USR, cat, conectar, df, rol, tc)
        st.write("")
    _otros = df[~df["rol"].astype(str).str.upper().isin(ROL_ORDEN)]
    if not _otros.empty:
        st.markdown("#### Otros")
        st.dataframe(_otros[["codigo", "rol", "precio", "unidad", "moneda"]],
                     hide_index=True, use_container_width=True)
    st.divider()
    _alta(USR, cat, conectar, df)
    _mapeo(cat)
    st.divider()
    _historial(cat)
    _cierre()
