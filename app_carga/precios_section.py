"""
Precios de referencia — Dirección.

Única pantalla donde se tocan los precios con los que la app valoriza TODO:
materia prima, productos finales, insumos y el tipo de cambio.

Está armada en dos bloques, y en este orden a propósito:

  1. **Con qué precio se valoriza cada producto.** Una sola tabla con TODOS los
     productos de `dim_producto` — no solo los que ya tienen precio — donde se ve,
     y se cambia ahí mismo, con qué código de `dim_precio_ref` se valoriza cada
     uno. Es la pregunta que uno se hace primero ("¿por qué AG-E vale eso?") y
     antes había que cruzarla a mano entre cuatro tablas distintas.
  2. **Cuánto vale cada código.** Los pocos códigos de precio que existen, en un
     único editor. Muchos productos comparten código a propósito.

Dos precios por código:
  · Precio de exportación (normalmente USD/tn) — el que usa hoy toda la app
    para valorizar stock, despachos, rendimiento y costo de conversión.
  · Precio de mercado interno (normalmente ARS) — el que se cobra acá. Se carga
    en esta pantalla y se compara contra el de exportación para ver qué mercado
    conviene, pero todavía NO reemplaza al de exportación en el resto de la app:
    para eso falta marcar en cada despacho si la venta fue interna o export.

Todo cambio de precio queda registrado en produccion.dim_precio_ref_hist por
trigger de base de datos (no por la app), así que ni un UPDATE manual por SQL
se escapa.
"""

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
DIAS_PRECIO_VENCIDO = 30
DIAS_MOVIMIENTO = 90

ROL_ORDEN = ["FX", "MP", "FINAL", "INSUMO"]

UNIDADES = ["TN", "KG", "L", "USD"]
MONEDAS = ["USD", "ARS"]
MONEDAS_INT = ["ARS", "USD"]
DENSIDAD_DEFECTO = 0.9

SIN_PRECIO = "— sin precio —"
COL_MOV = "Movido %d d (t)" % DIAS_MOVIMIENTO

SQL_PRODUCTOS = (
    "SELECT p.codigo_producto, p.nombre_producto, p.tipo_producto, p.corriente, "
    "p.activo, p.es_exportacion, p.densidad_g_ml, "
    "m.codigo_precio, m.densidad_ref, "
    "r.precio, r.unidad, r.moneda, r.actualizado_en, "
    "COALESCE(mv.tn, 0) AS tn_mov "
    "FROM produccion.dim_producto p "
    "LEFT JOIN produccion.dim_precio_map m ON m.codigo_producto = p.codigo_producto "
    "LEFT JOIN produccion.dim_precio_ref r ON r.codigo = m.codigo_precio "
    "LEFT JOIN (SELECT id_producto, SUM(ABS(kg)) / 1000.0 AS tn "
    "FROM produccion.fact_movimiento_stock "
    "WHERE COALESCE(anulado, false) = false "
    "AND momento >= now() - interval '90 days' "
    "GROUP BY id_producto) mv ON mv.id_producto = p.id_producto "
    "ORDER BY p.activo DESC, COALESCE(mv.tn, 0) DESC, p.codigo_producto")


def _num(x, d=0.0):
    try:
        if x is None or pd.isna(x):
            return d
        return float(x)
    except (TypeError, ValueError):
        return d


def _opt(x):
    """float o None, tolerante a NaN / vacío / texto."""
    try:
        if x is None or pd.isna(x):
            return None
        if isinstance(x, str) and not x.strip():
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _txt(x, d=""):
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return d
    return str(x)


def _puede(USR):
    return str(USR.get("rol", "")).upper() in ROLES_DIRECCION


def _usuario(USR):
    return str(USR.get("nombre") or USR.get("id_usuario") or "?")


def _dias_desde(ts):
    _t = pd.to_datetime(ts, errors="coerce", utc=True)
    if pd.isna(_t):
        return None
    return int((pd.Timestamp.now(tz="UTC").normalize() - _t.normalize()).days)


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


def _cargar_productos(cat):
    """Todos los productos de dim_producto con su código de precio y su movimiento."""
    try:
        p = cat(SQL_PRODUCTOS)
    except Exception as e:
        st.error("No se pudo leer el mapa de productos: %s" % e)
        return pd.DataFrame()
    if p is None or p.empty:
        return pd.DataFrame()
    return p.copy()


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


# ─────────────────────────────────────────────────────────────────────────────
# Portada
# ─────────────────────────────────────────────────────────────────────────────

def _portada(df, p):
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
    _vacios = df[pd.to_numeric(df["precio"], errors="coerce").fillna(0) <= 0]

    _sin = 0
    _sin_mov = 0
    if p is not None and not p.empty:
        _act = p[p["activo"] == True]  # noqa: E712
        _falta = (_act["codigo_precio"].isna()
                  | (pd.to_numeric(_act["precio"], errors="coerce").fillna(0) <= 0))
        _sin = int(_falta.sum())
        _sin_mov = int((_falta
                        & (pd.to_numeric(_act["tn_mov"], errors="coerce").fillna(0) > 0)).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Códigos de precio", len(df))
    c2.metric("Productos activos sin valorizar", _sin,
              delta=None if _sin == 0 else "valen USD 0", delta_color="inverse")
    c3.metric("…y con movimiento (%d d)" % DIAS_MOVIMIENTO, _sin_mov,
              delta=None if _sin_mov == 0 else "urgente", delta_color="inverse")
    _tcv = _tc(df)
    c4.metric("TC_USD", "—" if _tcv is None else "%s" % format(int(_tcv), ","))

    if not _vacios.empty:
        st.error(
            "🚨 **%d código(s) de precio existen pero no tienen precio cargado:** " % len(_vacios)
            + ", ".join("`%s`" % c for c in _vacios["codigo"].astype(str))
            + ".\n\nTodo producto vinculado a estos códigos **vale USD 0 en toda la app**: "
              "no suma al inventario valorizado, no suma al valor despachado, y ningún total "
              "da error — simplemente falta plata. Cargales el precio en el bloque 2️⃣, "
              "más abajo.")
    if not _venc.empty:
        st.warning(
            "⚠️ **%d precio(s) llevan más de %d días sin tocarse:** " % (len(_venc), DIAS_PRECIO_VENCIDO)
            + ", ".join("`%s`" % c for c in _venc["codigo"].astype(str).head(10))
            + ".\n\nUn precio viejo no da error: da un número creíble y equivocado.")


# ─────────────────────────────────────────────────────────────────────────────
# Bloque 1 — con qué precio se valoriza cada producto
# ─────────────────────────────────────────────────────────────────────────────

def _densidades(p):
    """Densidad efectiva por fila: la del mapeo, si no la del producto, si no vacío."""
    out = []
    for _dr, _dg in zip(p["densidad_ref"], p["densidad_g_ml"]):
        _v = _opt(_dr)
        if _v is None:
            _v = _opt(_dg)
        out.append(_v)
    return out


def _alerta(cod_prod, cod_precio, precio, cods_producto):
    """Por qué esta fila merece atención. Vacío = está bien."""
    if not cod_precio:
        return "🔴 sin precio"
    if _num(precio, 0.0) <= 0:
        return "🔴 código sin precio"
    if cod_precio != cod_prod and cod_precio in cods_producto:
        return "🟡 usa precio de %s" % cod_precio
    return ""


def _tabla_productos(p, tc, cods_producto):
    _dens = _densidades(p)
    _cp = [None if (c is None or pd.isna(c)) else str(c) for c in p["codigo_precio"]]

    _e = pd.DataFrame({
        "Producto": p["codigo_producto"].astype(str).values,
        "Nombre": p["nombre_producto"].fillna("").astype(str).values,
        "Tipo": p["tipo_producto"].fillna("").astype(str).values,
        "Se valoriza con": [c if c else SIN_PRECIO for c in _cp],
    })
    _e["USD/t"] = pd.Series(
        [_usd_t(pr, u, m, tc, d if d else DENSIDAD_DEFECTO)
         for pr, u, m, d in zip(p["precio"], p["unidad"], p["moneda"], _dens)],
        dtype="float64").values
    _e["Densidad"] = pd.Series(_dens, dtype="float64").values
    _e[COL_MOV] = pd.to_numeric(p["tn_mov"], errors="coerce").fillna(0.0).values
    _e["Estado"] = [_estado(_dias_desde(a)) if c else "—"
                    for a, c in zip(p["actualizado_en"], _cp)]
    _e["Activo"] = p["activo"].fillna(False).astype(bool).values
    _e["⚠"] = [_alerta(str(cp), cc, pr, cods_producto)
               for cp, cc, pr in zip(p["codigo_producto"], _cp, p["precio"])]
    return _e


def _config_productos(cods):
    return {
        "Producto": st.column_config.TextColumn(
            help="Código del producto en `dim_producto`. Es el mismo que aparece en stock, "
                 "reacciones y despachos."),
        "Nombre": st.column_config.TextColumn(help="Nombre largo del producto."),
        "Tipo": st.column_config.TextColumn(
            help="MP = materia prima que se compra. FINAL = producto terminado que se vende. "
                 "INSUMO = se consume en el proceso y no se vende."),
        "Se valoriza con": st.column_config.SelectboxColumn(
            options=[SIN_PRECIO] + list(cods),
            help="EL CAMPO CLAVE DE ESTA PANTALLA. Es el código de `dim_precio_ref` con el "
                 "que la app le pone precio a este producto. Se cambia acá mismo y se guarda "
                 "con el botón de abajo. Varios productos pueden compartir el mismo código a "
                 "propósito (todas las borras y sebos usan AG-C). Ponerlo en «%s» hace que el "
                 "producto valga USD 0 en toda la app." % SIN_PRECIO),
        "USD/t": st.column_config.NumberColumn(
            format="%.0f",
            help="QUÉ MIDE: lo que vale una tonelada de este producto para la app. "
                 "CÓMO SE CALCULA: se toma el precio del código elegido y se normaliza — "
                 "USD/tn queda igual; USD/kg ×1000; ARS ÷ TC_USD; por litro además ÷ densidad. "
                 "Vacío = este producto no suma dólares en ningún informe."),
        "Densidad": st.column_config.NumberColumn(
            format="%.3f", min_value=0.1, max_value=2.0, step=0.01,
            help="Solo importa cuando el código de precio está cargado POR LITRO, para pasar "
                 "de litros a kilos. Si el precio es por tonelada, es indiferente. "
                 "Vacío = se usa %.1f." % DENSIDAD_DEFECTO),
        COL_MOV: st.column_config.NumberColumn(
            format="%.1f",
            help="Toneladas movidas en los últimos %d días según `fact_movimiento_stock` "
                 "(entradas + salidas, en valor absoluto). Sirve para priorizar: un producto "
                 "sin precio que mueve cientos de toneladas es un agujero real; uno sin "
                 "precio que no se movió nunca, no." % DIAS_MOVIMIENTO),
        "Estado": st.column_config.TextColumn(
            help="Antigüedad del precio del código asignado. 🟢 hasta 15 d, 🟡 hasta 30 d, "
                 "🔴 más de 30 d, ⚫ sin fecha, — sin código asignado."),
        "Activo": st.column_config.CheckboxColumn(
            help="Si el producto sigue en uso. Los inactivos son códigos viejos o fusionados; "
                 "están ocultos salvo que se tilde el filtro."),
        "⚠": st.column_config.TextColumn(
            help="🔴 sin precio = no tiene código asignado, vale cero. "
                 "🔴 código sin precio = tiene código pero el código está vacío. "
                 "🟡 usa precio de X = se valoriza con el precio de OTRO producto; puede ser "
                 "a propósito, pero conviene revisar que sea el precio correcto."),
    }


def _filtros(p):
    _tipos = sorted([t for t in p["tipo_producto"].dropna().astype(str).unique()])
    _corr = sorted([c for c in p["corriente"].dropna().astype(str).unique()])
    c1, c2, c3 = st.columns(3)
    _ft = c1.multiselect("Tipo", _tipos, key="px_f_tipo", help="Vacío = todos.")
    _fc = c2.multiselect("Familia / corriente", _corr, key="px_f_corr",
                         help="Vacío = todas. VEGETAL, ANIMAL, INSUMO, OTRO.")
    _fb = str(c3.text_input("Buscar", key="px_f_txt",
                            placeholder="código o nombre") or "").strip().upper()
    c4, c5, c6 = st.columns(3)
    _sin = c4.checkbox("Solo sin precio", key="px_f_sin",
                       help="Deja solo los productos que hoy valorizan en cero.")
    _mov = c5.checkbox("Solo con movimiento", key="px_f_mov",
                       help="Deja solo los que tuvieron movimiento de stock en los últimos "
                            "%d días." % DIAS_MOVIMIENTO)
    _ina = c6.checkbox("Incluir inactivos", key="px_f_ina",
                       help="Productos dados de baja o fusionados. Normalmente no hace falta "
                            "tocarles el precio.")

    d = p
    if not _ina:
        d = d[d["activo"] == True]  # noqa: E712
    if _ft:
        d = d[d["tipo_producto"].astype(str).isin(_ft)]
    if _fc:
        d = d[d["corriente"].astype(str).isin(_fc)]
    if _fb:
        d = d[d["codigo_producto"].astype(str).str.upper().str.contains(_fb, regex=False)
              | d["nombre_producto"].fillna("").astype(str).str.upper()
              .str.contains(_fb, regex=False)]
    if _sin:
        d = d[d["codigo_precio"].isna()
              | (pd.to_numeric(d["precio"], errors="coerce").fillna(0) <= 0)]
    if _mov:
        d = d[pd.to_numeric(d["tn_mov"], errors="coerce").fillna(0) > 0]
    return d


def _guardar_mapa(USR, conectar, cat, cambios):
    """Aplica los cambios de vínculo producto → código de precio."""
    if not cambios:
        return False
    try:
        with conectar(USR["id_usuario"]) as (conn, audit):
            with conn.cursor() as cur:
                for c in cambios:
                    if c["codigo_precio"] is None:
                        cur.execute(
                            "DELETE FROM produccion.dim_precio_map WHERE codigo_producto = %s",
                            (c["codigo_producto"],))
                    else:
                        cur.execute(
                            "INSERT INTO produccion.dim_precio_map "
                            "(codigo_producto, codigo_precio, densidad_ref, nota) "
                            "VALUES (%s, %s, %s, %s) ON CONFLICT (codigo_producto) DO UPDATE "
                            "SET codigo_precio = EXCLUDED.codigo_precio, "
                            "densidad_ref = EXCLUDED.densidad_ref, nota = EXCLUDED.nota",
                            (c["codigo_producto"], c["codigo_precio"], c["densidad"],
                             "asignado desde Dirección por %s" % _usuario(USR)))
        cat.clear()
        return True
    except Exception as e:
        st.error("No se pudieron guardar los vínculos: %s" % e)
        return False


def _bloque_productos(USR, cat, conectar, p, cods, tc):
    st.markdown("### 1️⃣ Con qué precio se valoriza cada producto")
    st.caption(
        "Están **todos** los productos de `dim_producto`, no solo los que ya tienen precio. "
        "La columna **Se valoriza con** se edita acá mismo: elegís el código y guardás. Un "
        "producto sin código no da error en ningún lado — simplemente vale USD 0 y "
        "desaparece de los totales en dólares sin dejar rastro.")

    d = _filtros(p)
    st.caption("Mostrando **%d** de %d productos." % (len(d), len(p)))
    if d.empty:
        st.info("Ningún producto cumple los filtros.")
        return

    _cods_prod = set(p["codigo_producto"].astype(str))
    _e = _tabla_productos(d, tc, _cods_prod)
    _cfg = _config_productos(cods)
    _bloq = ["Producto", "Nombre", "Tipo", "USD/t", COL_MOV, "Estado", "Activo", "⚠"]

    if not _puede(USR) or conectar is None:
        st.dataframe(_e, hide_index=True, use_container_width=True, column_config=_cfg)
        return

    _orig = {}
    for _, r in _e.iterrows():
        _orig[str(r["Producto"])] = (str(r["Se valoriza con"]), _opt(r["Densidad"]))

    try:
        _ed = st.data_editor(_e, hide_index=True, use_container_width=True,
                             key="px_ed_map", disabled=_bloq, column_config=_cfg)
    except Exception:
        st.dataframe(_e, hide_index=True, use_container_width=True, column_config=_cfg)
        st.caption("El editor no está disponible en esta versión de Streamlit.")
        return
    if _ed is None:
        return

    _cambios = []
    for _, r in _ed.iterrows():
        _prod = str(r["Producto"])
        _o = _orig.get(_prod)
        if _o is None:
            continue
        _cod = _txt(r["Se valoriza con"], SIN_PRECIO) or SIN_PRECIO
        _dn = _opt(r["Densidad"])
        _ocod, _odn = _o
        _toco = (_cod != _ocod) or (
            (_dn is None) != (_odn is None)
            or (_dn is not None and _odn is not None and abs(_dn - _odn) > 1e-9))
        if not _toco:
            continue
        if _cod != SIN_PRECIO and _cod not in cods:
            st.warning("`%s`: el código `%s` no existe. Se ignora." % (_prod, _cod))
            continue
        _cambios.append({
            "codigo_producto": _prod,
            "codigo_precio": None if _cod == SIN_PRECIO else _cod,
            "densidad": _dn,
            "antes": _ocod})
    if not _cambios:
        return

    _det = []
    for c in _cambios:
        if c["codigo_precio"] is None:
            _det.append("- `%s` → **se desvincula**: pasa a valer USD 0 en toda la app"
                        % c["codigo_producto"])
        else:
            _det.append("- `%s` → se valoriza con **`%s`** (antes: %s)"
                        % (c["codigo_producto"], c["codigo_precio"], c["antes"]))
    st.warning("**Cambios sin guardar**\n\n%s" % "\n".join(_det))
    if st.button("💾 Guardar %d vínculo(s)" % len(_cambios), key="px_save_map", type="primary"):
        if _guardar_mapa(USR, conectar, cat, _cambios):
            st.success("%d producto(s) re-vinculado(s)." % len(_cambios))
            try:
                st.rerun()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Bloque 2 — cuánto vale cada código de precio
# ─────────────────────────────────────────────────────────────────────────────

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


def _orden_rol(df):
    d = df.copy()
    d["_ord"] = [ROL_ORDEN.index(str(r).upper()) if str(r).upper() in ROL_ORDEN else 99
                 for r in d["rol"]]
    d = d.sort_values(by=["_ord", "codigo"]).drop(columns=["_ord"])
    return d


def _tabla_codigos(_d, tc, uso, con_interno):
    _e = pd.DataFrame({
        "Código": _d["codigo"].astype(str).values,
        "Rol": _d["rol"].fillna("").astype(str).values,
        "Precio export": pd.to_numeric(_d["precio"], errors="coerce").values,
        "Unidad": _d["unidad"].fillna("").astype(str).values,
        "Moneda": _d["moneda"].fillna("").astype(str).values,
    })
    _e["USD/t export"] = pd.Series(
        [_usd_t(p, u, m, tc) for p, u, m in
         zip(_e["Precio export"], _e["Unidad"], _e["Moneda"])], dtype="float64").values
    if con_interno:
        _e["Precio interno"] = pd.to_numeric(_d["precio_interno"], errors="coerce").values
        _e["Mon. int."] = _d["moneda_interno"].fillna("ARS").astype(str).values
        _e["USD/t interno"] = pd.Series(
            [_usd_t(p, u, m, tc) for p, u, m in
             zip(_e["Precio interno"], _e["Unidad"], _e["Mon. int."])], dtype="float64").values
        _e["Interno vs export"] = pd.Series(
            [None if (a is None or pd.isna(a) or b is None or pd.isna(b) or not b)
             else (a / b - 1.0) * 100.0
             for a, b in zip(_e["USD/t interno"], _e["USD/t export"])], dtype="float64").values
    _e["Productos"] = [int(uso.get(str(c), 0)) for c in _e["Código"]]
    _e["Estado"] = [_estado(x) for x in _d["_dias"].values]
    _e["Descripción"] = _d["descripcion"].fillna("").astype(str).values
    return _e


def _config_codigos(con_interno):
    cfg = {
        "Código": st.column_config.TextColumn(
            help="Identificador que usa la tabla de arriba. No se edita acá: renombrarlo "
                 "rompería el vínculo con los productos."),
        "Rol": st.column_config.TextColumn(
            help="FX = tipo de cambio. MP = lo que se paga por la materia prima que entra. "
                 "FINAL = lo que se cobra por el producto terminado. INSUMO = lo que cuesta "
                 "un insumo de proceso. Se define al crear el código."),
        "Precio export": st.column_config.NumberColumn(
            format="%.2f",
            help="El precio con el que la app valoriza hoy TODO: stock, despachos, "
                 "rendimiento y conversión. Normalmente el precio de exportación en USD. "
                 "Vacío = este código no valoriza nada."),
        "USD/t export": st.column_config.NumberColumn(
            format="%.0f",
            help="QUÉ MIDE: el precio de exportación normalizado a dólares por tonelada, que "
                 "es lo que la app usa internamente. CÓMO SE CALCULA: USD/tn queda igual; "
                 "USD/kg ×1000; ARS ÷ TC_USD; por litro además ÷ densidad %.1f. "
                 "OJO: se recalcula al guardar, no mientras tipeás." % DENSIDAD_DEFECTO),
        "Productos": st.column_config.NumberColumn(
            format="%d",
            help="Cuántos productos se valorizan con este código, según la tabla de arriba. "
                 "Si dice 0, el código no está haciendo nada: falta vincularle productos."),
        "Estado": st.column_config.TextColumn(
            help="Días desde la última actualización. 🟢 hasta 15 d, 🟡 hasta 30 d, "
                 "🔴 más de 30 d, ⚫ nunca se registró fecha."),
        "Descripción": st.column_config.TextColumn(
            width="large",
            help="Texto libre, para que el próximo que abra esto sepa a qué se refiere."),
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
            help="Cuánto paga de más (+) o de menos (−) el mercado interno respecto del de "
                 "exportación, ya neteado el tipo de cambio. Es el número que dice a qué "
                 "mercado conviene mandar el producto, antes de flete y retenciones.")
    return cfg


def _bloque_codigos(USR, cat, conectar, df, p, tc):
    st.markdown("### 2️⃣ Cuánto vale cada código de precio")
    st.caption(
        "Son pocos a propósito: muchos productos comparten el mismo código para poder "
        "actualizarlos en un solo lugar. Todas las borras y sebos usan `AG-C`, que es la "
        "referencia más conservadora de la familia — se subvalúan a propósito antes que "
        "inflarlos. La columna **Productos** dice a cuántos afecta cada cambio.")

    uso = {}
    if p is not None and not p.empty:
        _u = p[p["codigo_precio"].notna()]["codigo_precio"].astype(str).value_counts()
        for k, v in _u.items():
            uso[str(k)] = int(v)

    con_interno = st.checkbox(
        "Ver y cargar precios de mercado interno", key="px_ver_interno",
        help="Agrega las columnas de precio local en ARS y la comparación contra el precio "
             "de exportación. Van ocultas por defecto porque hoy son informativas: la app "
             "todavía valoriza todo con el precio de export.")

    _d = _orden_rol(df)
    _e = _tabla_codigos(_d, tc, uso, con_interno)
    _cfg = _config_codigos(con_interno)

    _orig = {}
    for _, r in _e.iterrows():
        _orig[str(r["Código"])] = (
            _opt(r["Precio export"]), _txt(r["Unidad"]), _txt(r["Moneda"]),
            _txt(r["Descripción"]),
            _opt(r["Precio interno"]) if con_interno else None,
            _txt(r["Mon. int."], "ARS") if con_interno else None)

    _bloq = ["Código", "Rol", "USD/t export", "USD/t interno", "Interno vs export",
             "Productos", "Estado"]
    if not _puede(USR) or conectar is None:
        st.dataframe(_e, hide_index=True, use_container_width=True, column_config=_cfg)
        return

    _cfg_ed = dict(_cfg)
    _cfg_ed["Unidad"] = st.column_config.SelectboxColumn(
        options=UNIDADES,
        help="TN = por tonelada, KG = por kilo, L = por litro. Vale para las dos columnas de "
             "precio: si el export es por tonelada, el interno también.")
    _cfg_ed["Moneda"] = st.column_config.SelectboxColumn(
        options=MONEDAS,
        help="Si es ARS, el precio se convierte con TC_USD cada vez que se muestra.")
    if con_interno:
        _cfg_ed["Mon. int."] = st.column_config.SelectboxColumn(
            options=MONEDAS_INT,
            help="Moneda del precio de mercado interno. Casi siempre ARS.")
    try:
        _ed = st.data_editor(_e, hide_index=True, use_container_width=True,
                             key="px_ed_cod", disabled=_bloq, column_config=_cfg_ed)
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
        _p = _opt(r["Precio export"])
        _u = _txt(r["Unidad"]).upper()
        _m = _txt(r["Moneda"]).upper()
        _ds = _txt(r["Descripción"])
        _pi = _opt(r["Precio interno"]) if con_interno else None
        _mi = _txt(r["Mon. int."], "ARS").upper() if con_interno else None
        _op, _ou, _om, _od, _opi, _omi = _o
        _toco_int = con_interno and (
            (_pi is None) != (_opi is None)
            or (_pi is not None and _opi is not None and abs(_pi - _opi) > 1e-9)
            or (_mi or "") != str(_omi or "ARS").upper())
        _toco_exp = ((_p is None) != (_op is None)
                     or (_p is not None and _op is not None and abs(_p - _op) > 1e-9)
                     or _u != str(_ou or "").upper() or _m != str(_om or "").upper()
                     or _ds != str(_od or ""))
        if not (_toco_exp or _toco_int):
            continue
        if _p is None:
            st.warning("`%s`: cargale el precio de exportación para poder guardar el resto "
                       "de la fila." % _cod)
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
            "usd_t_int": _usd_t(_pi, _u, _mi, tc) if _pi is not None else None,
            "antes": _op})
    if not _cambios:
        return

    _det = []
    for c in _cambios:
        _t = "- `%s`: %s → **%s %s/%s**" % (
            c["codigo"],
            "sin precio" if c["antes"] is None else format(round(c["antes"], 2), ","),
            format(round(c["precio"], 2), ","), c["unidad"] or "?", c["moneda"] or "?")
        if c["usd_t"]:
            _t += " (USD %s/t)" % format(int(round(c["usd_t"])), ",")
        _n = uso.get(c["codigo"], 0)
        if _n:
            _t += "  ·  afecta a **%d producto(s)**" % _n
        if c["toco_interno"]:
            if c["precio_interno"] is None:
                _t += "  ·  interno: **se borra**"
            else:
                _t += "  ·  interno **%s %s/%s**" % (
                    format(round(c["precio_interno"], 2), ","), c["moneda_interno"],
                    c["unidad"] or "?")
                if c["usd_t_int"]:
                    _t += " (USD %s/t)" % format(int(round(c["usd_t_int"])), ",")
        _det.append(_t)
    st.warning("**Cambios sin guardar en los códigos**\n\n%s" % "\n".join(_det))
    if st.button("💾 Guardar %d cambio(s) de precio" % len(_cambios),
                 key="px_save_cod", type="primary"):
        if _guardar(USR, conectar, cat, _cambios):
            st.success("%d precio(s) actualizado(s) y registrados en el historial."
                       % len(_cambios))
            try:
                st.rerun()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Alta de código nuevo · historial · cierre
# ─────────────────────────────────────────────────────────────────────────────

def _alta(USR, cat, conectar, df):
    """Alta de un código de precio nuevo."""
    if not _puede(USR) or conectar is None:
        return
    with st.expander("➕ Crear un código de precio nuevo"):
        st.caption(
            "Crear el código es solo la mitad: después hay que vincularle al menos un "
            "producto, en la tabla 1️⃣. Un código suelto no rompe nada, pero tampoco "
            "valoriza nada.")
        c1, c2 = st.columns(2)
        _cod = str(c1.text_input("Código", key="px_new_cod",
                                 placeholder="Ej: CAUCHO") or "").strip().upper()
        _rol = c2.selectbox("Rol", ["MP", "FINAL", "INSUMO", "FX"], key="px_new_rol")
        c3, c4, c5 = st.columns(3)
        _pre = c3.number_input("Precio exportación", min_value=0.0, value=0.0, step=1.0,
                               key="px_new_pre")
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
            _t = []
            if _u1:
                _t.append("export **USD %s/t**" % format(int(round(_u1)), ","))
            if _u2:
                _t.append("interno **USD %s/t**" % format(int(round(_u2)), ","))
            st.caption("Equivale a " + " · ".join(_t) + ".")
        if not st.button("Crear código", key="px_new_btn"):
            return
        if not _cod:
            st.error("Falta el código.")
            return
        if df is not None and not df.empty and _cod in set(df["codigo"].astype(str)):
            st.error("`%s` ya existe. Editalo en la tabla 2️⃣." % _cod)
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
            st.success("`%s` creado. Ahora asignale productos en la tabla 1️⃣." % _cod)
            try:
                st.rerun()
            except Exception:
                pass
        except Exception as e:
            st.error("No se pudo crear el código: %s" % e)


def _historial(cat):
    with st.expander("🧾 Historial de cambios de precio"):
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
                "precio_interno_anterior": st.column_config.NumberColumn("Int. antes",
                                                                        format="%.2f"),
                "precio_interno_nuevo": st.column_config.NumberColumn("Int. después",
                                                                     format="%.2f"),
                "variacion_interno_pct": st.column_config.NumberColumn("Var. int. %",
                                                                      format="%.1f%%"),
                "unidad": st.column_config.TextColumn("Unidad"),
                "moneda": st.column_config.TextColumn("Moneda"),
                "usuario": st.column_config.TextColumn("Quién")})


def _cierre():
    st.caption(
        "El precio de mercado interno todavía es **informativo**: sirve para comparar contra "
        "el de exportación, pero la app sigue valorizando stock y despachos con el precio de "
        "export. Para que el interno pese de verdad hay que marcar en cada despacho si la "
        "venta fue interna o de exportación — decime y lo agrego.")


# ─────────────────────────────────────────────────────────────────────────────

def render(USR, cat, conectar):
    df = _cargar(cat)
    p = _cargar_productos(cat)
    _portada(df, p)
    if df is None or df.empty:
        _alta(USR, cat, conectar, df)
        return
    if not _puede(USR):
        st.info("Solo Dirección puede modificar precios. Abajo se muestran los vigentes.")
    tc = _tc(df)
    if tc is None:
        st.warning("Falta `TC_USD`. Todo lo cargado en pesos (fuel, glicerina, potasa) y "
                   "todo precio de mercado interno no se puede convertir a dólares.")
    st.divider()

    _cods = sorted([str(c) for c in df["codigo"].astype(str)])
    if p is not None and not p.empty:
        _bloque_productos(USR, cat, conectar, p, _cods, tc)
    else:
        st.warning("No se pudo leer `dim_producto`: no se puede mostrar con qué precio se "
                   "valoriza cada producto.")

    st.divider()
    _bloque_codigos(USR, cat, conectar, df, p, tc)
    _alta(USR, cat, conectar, df)
    st.divider()
    _historial(cat)
    _cierre()
