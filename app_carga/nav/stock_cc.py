# -*- coding: utf-8 -*-
"""Stock del sector: el modelo de stock de dirección, sin nada más.

Una cuenta por producto, con su código oficial (V-AFE-S-A, V-AG-C…), y por cada cuenta una
cuenta corriente: saldo inicial, ingresos, egresos y saldo corriendo fila por fila. Arriba, el
saldo consolidado de todas las cuentas a la fecha. El Q sale del libro de movimientos de la
planta (produccion.v_stock_cuenta_sector), que atribuye cada movimiento a un sector por el
tanque: cada sector ve lo suyo y nada más.

El saldo inicial es la medición física de los tanques del sector el primer día hábil del mes
(produccion.fact_stock_saldo_inicial); la cuenta corriente corre desde ahí.

Filtros (dirección, 23/09/2026): producto y sector (uno o varios, vacío = todos), fecha
desde/hasta con calendario, N° de ticket, y «➕ Más» con el resto. El resultado aparece al
apretar BUSCAR. Sin indicadores. Cada producto se muestra con su código oficial y el nombre
de la planilla de parámetros («V-AFE-S-A · AFE Soja»).
(Base: rediseño del 21/09/2026, "hiper simplista, robusta, con códigos oficiales".)
"""

import io
import re
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

_UM = {"TN": ("kg_neto", 1000.0), "KL": ("litros_neto", 1000.0)}   # lo usa stock_consolidado
_COLS = ("id_mov, momento, fecha, cuenta, tipo, origen, destino, ticket, tickets_detalle, "
         "kg_neto, litros_neto, referencia, es_ajuste_sistema, observacion, tanque, sector, es_stock, "
         "producto_codigo, usuario")
_TODOS = "TODOS"
_TZ = "America/Argentina/Buenos_Aires"

# Textos que arma el sistema al registrar un movimiento: no son comentarios de nadie y en
# la columna COMENTARIO sólo tapaban lo útil (revisión 24/09/2026).
_AUTO = re.compile(r"^(ODV \d+ línea \d+|Asignación AFE ticket.*|Ingreso capturado desde laboratorio.*"
                   r"|Asignación automática por laboratorio.*|Recuperación AG ticket \d+|RE-\d+|RX-[\d-]+"
                   r"|BA-\d+|MS-\d+)$", re.IGNORECASE)


def _hora_planta(serie):
    """Fechas en hora de PLANTA (Argentina), sin zona.

    pandas lee los timestamptz de la base y los devuelve en UTC: sin esta conversión
    todas las fechas y horas del stock salían 3 horas adelantadas (un movimiento de las
    19:00 figuraba a las 22:00; los de «medianoche» a las 03:00)."""
    t = pd.to_datetime(serie, errors="coerce")
    try:
        if getattr(t.dt, "tz", None) is not None:
            t = t.dt.tz_convert(_TZ).dt.tz_localize(None)
    except Exception:
        pass
    return t


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, desde, hasta):
    """`sector`: un código o una tupla de códigos (para comparar sectores)."""
    _secs = list(sector) if isinstance(sector, (list, tuple)) else [sector]
    sql = (f"SELECT {_COLS} FROM produccion.v_stock_cuenta_sector "
           "WHERE sector = ANY(%s) AND fecha BETWEEN %s AND %s ORDER BY momento, id_mov")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(_secs, desde, hasta))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        df["es_stock"] = df["es_stock"].fillna(True).astype(bool) if "es_stock" in df.columns else True
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        df["momento"] = _hora_planta(df["momento"])
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _saldo_inicial(_cf, sector, desde):
    """Saldo con el que arranca el período, por cuenta (produccion.fn_stock_saldo_a: el último
    corte del mes más los movimientos entre el corte y `desde`)."""
    sql = ("SELECT cuenta, kg_neto, litros_neto, base_fecha, base_fuente "
           "FROM produccion.fn_stock_saldo_a(%s, %s)")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


def _cerrar_corte(conectar, USR, sector, fecha):
    """Graba el saldo inicial del mes: la foto física de los tanques del sector."""
    with conectar(int(USR["id_usuario"])) as (conn, _audit):
        with conn.cursor() as cur:
            cur.execute("SELECT r_cuentas, r_tn FROM produccion.fn_stock_cerrar_saldo_inicial(%s, %s, %s)",
                        (sector, fecha, int(USR["id_usuario"])))
            return cur.fetchone()


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _catalogo(_cf):
    """Cuenta → código de producto, y código → nombre de la planilla de parámetros
    (dim_producto.nombre_producto). Para mostrar «V-AFE-S-A · AFE Soja»."""
    try:
        with _cf() as conn:
            c = pd.read_sql_query("SELECT DISTINCT cuenta, producto_codigo FROM produccion.v_cuenta_sector "
                                  "WHERE cuenta IS NOT NULL", conn)
            p = pd.read_sql_query("SELECT codigo_producto, nombre_producto FROM produccion.dim_producto", conn)
        return (dict(zip(c["cuenta"].astype(str), c["producto_codigo"].astype(str))),
                dict(zip(p["codigo_producto"].astype(str), p["nombre_producto"].fillna("").astype(str))))
    except Exception:
        return {}, {}


def _producto_de(cuenta, cta_prod, productos):
    """Código de producto de una cuenta. Las cuentas históricas (V-AFE-M-NE, V-AFE-SG-NE…)
    no figuran en v_cuenta_sector: se deduce sacando la corriente (V-/A-) y la calidad."""
    c = str(cuenta or "")
    if c in cta_prod:
        return cta_prod[c]
    x = re.sub(r"^[VA]-", "", c)
    partes = x.split("-")
    for n in range(len(partes), 0, -1):
        cand = "-".join(partes[:n])
        if cand in productos:
            return cand
    return ""


def _nombre_cuenta(cuenta, cta_prod, nom_prod):
    """El producto se nombra SIEMPRE con su sigla oficial (V-AFE-S-A), nunca con el nombre
    largo («AFE Soja», «Aceite filtrado especial…»): regla de dirección, 24/09/2026."""
    return str(cuenta)


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _sectores(_cf):
    try:
        with _cf() as conn:
            # sólo los sectores que tienen stock (tanques): Administración, Portería,
            # Laboratorio… no tienen nada que mostrar acá
            df = pd.read_sql_query("SELECT codigo, nombre_ui FROM produccion.dim_sector_nav s "
                                   "WHERE COALESCE(activo,true) AND NOT COALESCE(en_construccion,false) "
                                   "  AND EXISTS (SELECT 1 FROM produccion.v_acopio_sector a WHERE a.sector = s.codigo) "
                                   "ORDER BY nombre_ui", conn)
        return dict(zip(df["codigo"].astype(str), df["nombre_ui"].astype(str)))
    except Exception:
        return {}


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _cuentas_de(_cf, sectores):
    """Todas las cuentas con movimiento o saldo en esos sectores (para el desplegable)."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT DISTINCT cuenta FROM produccion.v_stock_cuenta_sector "
                                   "WHERE sector = ANY(%s) AND cuenta IS NOT NULL AND es_stock ORDER BY 1",
                                   conn, params=(list(sectores),))
        return df["cuenta"].astype(str).tolist()
    except Exception:
        return []


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _tanques_de(_cf, sectores):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT DISTINCT tanque FROM produccion.v_stock_cuenta_sector "
                                   "WHERE sector = ANY(%s) AND tanque IS NOT NULL ORDER BY 1",
                                   conn, params=(list(sectores),))
        return df["tanque"].astype(str).tolist()
    except Exception:
        return []


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _medido(_cf, sectores):
    """Lo que hoy miden los tanques de esos sectores (TN, KL). Sólo para Notificaciones."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT COALESCE(SUM(act_tn),0) AS tn, COALESCE(SUM(act_l),0)/1000.0 AS kl "
                                   "FROM produccion.v_acopio_sector WHERE sector = ANY(%s) AND activo "
                                   "AND condicion <> 'FUERA DE USO'", conn, params=(list(sectores),))
        return float(df.iloc[0]["tn"]), float(df.iloc[0]["kl"])
    except Exception:
        return None


def invalidar():
    _movs.clear(); _saldo_inicial.clear(); _cuentas_de.clear(); _tanques_de.clear(); _medido.clear()
    for _f in ("_saldo_hoy", "_cuentas_con_tanque", "_porteria"):
        try:
            globals()[_f].clear()
        except Exception:
            pass


# ------------------------------------------------------------------ helpers
def _col(df, nombre, defecto=None):
    if nombre in df.columns:
        return df[nombre]
    return pd.Series([defecto] * len(df), index=df.index)


def _q(x, cero="—"):
    """La cantidad, con un decimal. Cero se escribe, no se deja en blanco."""
    if x is None or pd.isna(x) or abs(float(x)) < 0.05:
        return cero
    return f"{float(x):,.1f}"


def _primer_dia_habil(d):
    d = date(d.year, d.month, 1)
    while d.weekday() >= 5:
        d = d.fromordinal(d.toordinal() + 1)
    return d


def _contraparte(v):
    """ORIGEN / DESTINO en una sola columna: la contraparte del movimiento, nunca el tanque.
    En un ingreso es de dónde vino (portería · proveedor, la reacción, otro sector); en un
    egreso, a dónde fue (la ODV · cliente, el sector que lo tomó). El tanque va en TK / ACOPIO."""
    out = []
    for val, tipo, o, d in zip(v["_val"], v["tipo"].fillna(""), v["origen"].fillna(""), v["destino"].fillna("")):
        if tipo == "AJUSTE":
            out.append("AJUSTE")
        elif tipo == "ENTRADA" or (tipo != "SALIDA" and val > 0):
            out.append(o or "—")
        else:
            out.append(d or "—")
    return out


_OP = re.compile(r"^(RE|RX|BA)-[\w-]+$")


def _ticket(v):
    """N° TICKET completo: si el movimiento tiene varios (una ODV con 6 camiones) van todos,
    no «74681 +5». En los consumos y producciones de una reacción es la OP de la reacción
    (la de ORIGEN / DESTINO): 47 movimientos viejos tienen guardado otro código (RX-2026-00xx
    o la OP de otra reacción) y el N° TICKET no coincidía con la reacción."""
    det = _col(v, "tickets_detalle", "").fillna("").astype(str)
    tk = v["ticket"].fillna("").astype(str)
    cp = _contraparte(v) if "_val" in v.columns else [""] * len(v)
    out = []
    for d, t, c in zip(det, tk, cp):
        t2 = d if d.strip() else t
        m = re.match(r"^((?:RE|BA)-\d+) · ", str(c))
        if m and _OP.match(t2.strip()):
            t2 = m.group(1)
        out.append(t2)
    return out


def _f1(x):
    """Un decimal, sin «-0.0»."""
    x = round(float(x), 1)
    return f"{(x if x != 0 else 0.0):,.1f}"


def _comentario(v, con_tk):
    """COMENTARIO: la observación que escribió una persona; en las ODV, el contenedor; y en
    el consolidado (que no tiene columna TK) el tanque. Los textos automáticos del sistema
    («ODV 31 línea 442», «Ingreso capturado desde laboratorio…») no van."""
    out = []
    for o, r, d, tq in zip(v["observacion"].fillna(""), v["referencia"].fillna(""),
                           v["destino"].fillna(""), _col(v, "tanque", "").fillna("")):
        partes = []
        o, r = str(o).strip(), str(r).strip()
        if o and not _AUTO.match(o):
            partes.append(o)
        if r and str(d).startswith("ODV") and not _AUTO.match(r):
            partes.append(f"Contenedor {r}")
        if con_tk and str(tq).strip():
            partes.append(f"TK {str(tq).strip()}")
        out.append(" · ".join(partes))
    return out


def _fecha_txt(t):
    return pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if t is not None and not pd.isna(t) else ""


def _filas(v, saldo_ini, con_cuenta):
    """Las filas de la cuenta corriente. El saldo corre sobre TODAS las filas de `v`; si
    después se filtra por ticket, cada fila conserva el saldo real del libro en ese punto."""
    ing = v["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = saldo_ini + (ing - egr).cumsum()
    f = pd.DataFrame({
        "ID": v["id_mov"].map(lambda i: "" if pd.isna(i) else f"{int(i)}"),
        "FECHA": v["momento"].map(_fecha_txt),
        "CUENTA": v["cuenta"].fillna(""),
        "ORIGEN / DESTINO": _contraparte(v),
        "TK / ACOPIO": _col(v, "tanque", "").fillna("").replace("", "—"),
        "N° TICKET": _ticket(v),
        "INGRESO": ing.map(lambda x: _q(x, "")),
        "EGRESO": egr.map(lambda x: _q(x, "")),
        "SALDO": saldo.map(_f1),
        "COMENTARIOS": _comentario(v, con_tk=False),
    }, index=v.index)
    return f if con_cuenta else f.drop(columns=["CUENTA"])


def _cuenta_corriente(v, saldo_ini, fecha_ini, comentario_ini="", con_cuenta=False, mascara=None):
    cols = ["ID", "FECHA"] + (["CUENTA"] if con_cuenta else []) + \
           ["ORIGEN / DESTINO", "TK / ACOPIO", "N° TICKET", "INGRESO", "EGRESO", "SALDO", "COMENTARIOS"]
    filas = pd.DataFrame(columns=cols) if v.empty else _filas(v, saldo_ini, con_cuenta)
    if mascara is not None and not v.empty:
        filas = filas[mascara.values]
    cab = pd.DataFrame([{
        "ID": "", "FECHA": f"{fecha_ini:%d/%m/%Y}", "CUENTA": "", "ORIGEN / DESTINO": "SALDO INICIAL",
        "TK / ACOPIO": "", "N° TICKET": "", "INGRESO": "", "EGRESO": "",
        "SALDO": _f1(saldo_ini), "COMENTARIOS": comentario_ini,
    }])
    return pd.concat([cab, filas], ignore_index=True)[cols]


def _consolidado(v, ini, um, nombre_de, fecha_ini, orden=None):
    """SALDO CONSOLIDADO POR PRODUCTO (dirección, 23/09): producto por producto, cada uno
    con su SALDO INICIAL y sus movimientos en orden de fecha, con el saldo corriendo.
    FECHA · PRODUCTO · ORIGEN / DESTINO · N° TICKET · UM · INGRESO · EGRESO · SALDO · COMENTARIO.
    Revisión 24/09: antes mezclaba todos los productos por fecha (el saldo de cada renglón
    era de un producto distinto al de arriba) y el saldo inicial ponía el texto en FECHA.
    `orden`: función cuenta → clave de orden (Reactor: materia prima, insumo, terminado)."""
    cols = ["FECHA", "PRODUCTO", "ORIGEN / DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO", "SALDO", "COMENTARIO"]
    partes = []
    ctas = sorted(set(v["cuenta"].dropna()) | set(ini["cuenta"].dropna()),
                  key=(orden or (lambda c: str(c))))
    for c in ctas:
        w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
        s0 = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
        if w.empty and abs(s0) < 0.05:
            continue
        partes.append(pd.DataFrame([{"FECHA": f"{fecha_ini:%d/%m/%Y}", "PRODUCTO": nombre_de(c),
                                     "ORIGEN / DESTINO": "SALDO INICIAL", "N° TICKET": "", "UM": um,
                                     "INGRESO": "", "EGRESO": "", "SALDO": _f1(s0), "COMENTARIO": ""}]))
        if w.empty:
            continue
        ing = w["_val"].map(lambda x: x if x > 0 else 0.0)
        egr = w["_val"].map(lambda x: -x if x < 0 else 0.0)
        saldo = s0 + (ing - egr).cumsum()
        partes.append(pd.DataFrame({
            "FECHA": w["momento"].map(_fecha_txt).values,
            "PRODUCTO": nombre_de(c),
            "ORIGEN / DESTINO": _contraparte(w),
            "N° TICKET": _ticket(w),
            "UM": um,
            "INGRESO": ing.map(lambda x: _q(x, "")).values,
            "EGRESO": egr.map(lambda x: _q(x, "")).values,
            "SALDO": saldo.map(_f1).values,
            "COMENTARIO": _comentario(w, con_tk=True),
        }))
    if not partes:
        return pd.DataFrame(columns=cols)
    return pd.concat(partes, ignore_index=True)[cols]


def _texto_saldo_inicial(ini, desde):
    """De dónde sale el saldo inicial, dicho bien: la medición es de otro día que el
    «desde» elegido casi siempre."""
    bf = ini["base_fecha"].dropna() if "base_fecha" in ini.columns else pd.Series([], dtype=object)
    if not len(bf):
        return "arrastre del libro (sin medición de corte cargada)"
    b = pd.to_datetime(bf.iloc[0]).date()
    if b == desde:
        return f"medición de tanques del {b:%d/%m/%Y}"
    if b < desde:
        return f"medición de tanques del {b:%d/%m/%Y} + movimientos hasta el {desde:%d/%m/%Y}"
    return f"medición de tanques del {b:%d/%m/%Y} − movimientos del {desde:%d/%m/%Y} al {b:%d/%m/%Y}"


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


# ------------------------------------------------------------------ pantalla
def _cat_de(cf):
    """La barra de filtros compartida (filtros_stock) lee con cat(sql, params)."""
    def _cat(sql, params=None):
        with cf() as conn:
            return pd.read_sql_query(sql, conn, params=params)
    return _cat


def _notificaciones(slot, avisos):
    """Todo lo que antes era leyenda va acá: un botón «🔔 Notificaciones» con el número de
    avisos; adentro, uno por renglón. La pantalla queda con filtros y cuadros, nada más."""
    if slot is None:
        return
    with slot:
        with st.popover(f"🔔 Notificaciones · {len(avisos)}" if avisos else "🔔 Notificaciones",
                        use_container_width=True):
            if not avisos:
                st.write("Sin notificaciones.")
            for a in avisos:
                st.markdown(f"- {a}")


@_FRAGMENT
def _movimientos(ctx, sec, slot=None):
    import filtros_stock as _fs
    # el botón de Notificaciones vive dentro del fragmento (un fragmento no puede escribir
    # en contenedores de afuera)
    if slot is None:
        slot = st.columns([5, 1.3])[1].container()
    cod = sec["codigo"]
    cf = ctx["conn_factory"]
    hoy = date.today()
    corte = _primer_dia_habil(hoy)
    key = f"stkcc_{cod}"

    secs_nav = _sectores(cf)
    cta_prod, nom_prod = _catalogo(cf)

    def nombre_de(c):
        """«V-AFE-S-A · AFE Soja»: código oficial + nombre de la planilla de parámetros."""
        return _nombre_cuenta(c, cta_prod, nom_prod)

    # Sector: arranca en el de la pantalla; se pueden sumar otros para comparar.
    st.session_state.setdefault(f"{key}_sec", [cod])
    st.session_state.setdefault(f"{key}_desde", corte)
    st.session_state.setdefault(f"{key}_hasta", hoy)
    _secs_sel = tuple(st.session_state.get(f"{key}_sec") or [cod])
    _ctas = _cuentas_de(cf, _secs_sel)
    _etq = {c: nombre_de(c) for c in _ctas}
    _etq.update(secs_nav)

    def _mas():
        out = {}
        out["Unidad"] = st.radio("Unidad", list(_UM), horizontal=True, key=f"{key}_um")
        out["Tipo"] = st.selectbox("Tipo de movimiento", ["(todos)", "Ingresos", "Egresos"], key=f"{key}_tipo")
        out["Tanque"] = st.selectbox("TK / Acopio", ["(todos)"] + _tanques_de(cf, _secs_sel), key=f"{key}_tq")
        out["Origen/Destino"] = st.text_input("Origen / destino contiene", key=f"{key}_od",
                                              placeholder="proveedor, cliente, ODV, reactor, sector…")
        out["Usuario"] = st.text_input("Usuario", key=f"{key}_usr", placeholder="quien cargó el movimiento")
        out["Ajustes"] = st.checkbox("Incluir ajustes automáticos de medición", key=f"{key}_aj", value=False)
        return out

    f, apretado = _fs.barra(_cat_de(cf), key=key, titulo=None,
                            campos=("prod", "sec", "fecha", "tk"),
                            catalogos={"prod": _ctas, "sec": list(secs_nav)},
                            multi=True, extras_fn=_mas, buscar=True, etiquetas=_etq)

    k_ap = f"{key}_aplicado"
    if apretado:
        st.session_state[k_ap] = f
    fa = st.session_state.get(k_ap)
    if not fa:
        _notificaciones(slot, [])
        return

    desde = fa["desde"] or corte
    hasta = fa["hasta"] or hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    secs = list(fa["sec"] or [cod])
    prop = fa.get("propios") or {}
    um = prop.get("Unidad") or "TN"
    col, div = _UM[um]

    df = _movs(cf, tuple(secs), desde, hasta)
    inis = [_saldo_inicial(cf, s_, desde) for s_ in secs]
    if df is None or any(x is None for x in inis):
        _notificaciones(slot, ["Sin conexión a la base en este momento: volvé a apretar Buscar."])
        return
    ini = pd.concat(inis, ignore_index=True) if inis else pd.DataFrame(columns=["cuenta", "kg_neto", "litros_neto"])

    v = df[df["es_stock"]].copy()
    v = v[(v["kg_neto"] != 0) | (v["litros_neto"] != 0)]     # asignaciones de 0 kg: no son movimientos
    if not prop.get("Ajustes"):
        v = v[~v["es_ajuste_sistema"]]
    v = v[v["sector"].isin(secs)] if "sector" in v.columns else v   # red de seguridad
    v["_val"] = v[col] / div
    ini = ini.copy()
    ini["_val"] = pd.to_numeric(ini[col], errors="coerce").fillna(0.0) / div

    # ---- filtros ----
    if fa["prod"]:
        v = v[v["cuenta"].isin(fa["prod"])]
        ini = ini[ini["cuenta"].isin(fa["prod"])]
    if prop.get("Tipo") == "Ingresos":
        v = v[v["_val"] > 0]
    elif prop.get("Tipo") == "Egresos":
        v = v[v["_val"] < 0]
    if prop.get("Tanque") not in (None, "", "(todos)"):
        v = v[_col(v, "tanque", "").fillna("").astype(str) == prop["Tanque"]]
    if (prop.get("Origen/Destino") or "").strip():
        q = prop["Origen/Destino"].strip().lower()
        v = v[pd.Series(_contraparte(v), index=v.index).str.lower().str.contains(q, regex=False)]
    if (prop.get("Usuario") or "").strip():
        q = prop["Usuario"].strip().lower()
        v = v[_col(v, "usuario", "").fillna("").astype(str).str.lower().str.contains(q, regex=False)]
    # el ticket filtra las FILAS pero el saldo sigue siendo el real del libro
    m_tk = None
    if fa["tk"]:
        q = fa["tk"].strip().lower()
        m_tk = v["id_mov"].astype(str).str.contains(q, regex=False)
        for c in ("ticket", "tickets_detalle", "referencia"):
            m_tk = m_tk | v[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)

    _secs_txt = ", ".join(secs_nav.get(x, x) for x in secs)

    # ---- notificaciones (lo que antes eran leyendas) ----
    avisos = []
    _bf0 = ini["base_fecha"].dropna() if "base_fecha" in ini.columns else pd.Series([], dtype=object)
    s_fin = float(ini["_val"].sum()) + float(v["_val"].sum())
    med = _medido(cf, tuple(secs))
    avisos.append(f"Saldo inicial al {desde:%d/%m/%Y} ({_secs_txt}): {_texto_saldo_inicial(ini, desde)}.")
    if med is not None:
        _m = med[0] if um == "TN" else med[1]
        avisos.append(f"Hoy los tanques miden **{_m:,.1f} {um}** y el libro cierra en **{s_fin:,.1f} {um}**: "
                      f"diferencia **{s_fin - _m:+,.1f} {um}**.")
    _neg = sorted(ini.loc[ini["_val"] < -0.05, "cuenta"].dropna().astype(str).unique().tolist())
    if _neg:
        avisos.append("Arrancan en negativo: **" + ", ".join(_neg) + "** — falta cargar salidas o asentar un "
                      "cambio de categoría.")
    _notificaciones(slot, avisos)

    # ---- SALDO CONSOLIDADO POR PRODUCTO ----
    st.markdown("<div class='section-title' style='margin:10px 0 2px'>SALDO CONSOLIDADO POR PRODUCTO</div>",
                unsafe_allow_html=True)
    if m_tk is not None:
        # el ticket filtra los renglones; el saldo de cada uno sigue siendo el real del libro
        _cons_all = _consolidado(v, ini, um, nombre_de, desde)
        _vm = v[m_tk]
        _keep = set(_ticket(_vm))
        cons = _cons_all[(_cons_all["ORIGEN / DESTINO"] == "SALDO INICIAL")
                         | _cons_all["N° TICKET"].astype(str).isin(_keep)]
    else:
        cons = _consolidado(v, ini, um, nombre_de, desde)
    st.dataframe(cons, hide_index=True, use_container_width=True, height=min(560, 40 + 35 * len(cons)),
                 column_config={"PRODUCTO": st.column_config.TextColumn(width="medium"),
                                "ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "COMENTARIO": st.column_config.TextColumn(width="medium"),
                                "UM": st.column_config.TextColumn(width="small")})

    # ---- CUENTA CORRIENTE DEL PRODUCTO ----
    ctas = sorted(set(v["cuenta"].dropna()) | set(ini.loc[ini["_val"].abs() >= 0.05, "cuenta"].dropna()))
    st.markdown("<div class='section-title' style='margin:14px 0 2px'>CUENTA CORRIENTE DEL PRODUCTO</div>",
                unsafe_allow_html=True)
    if not ctas:
        st.dataframe(_cuenta_corriente(v.iloc[0:0], 0.0, desde), hide_index=True, use_container_width=True)
        return
    k_c = f"{key}_cta"
    if st.session_state.get(k_c) not in ctas:
        st.session_state[k_c] = ctas[0]
    cta = st.selectbox("Producto", ctas, key=k_c, label_visibility="collapsed", format_func=nombre_de)
    w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
    s_ini_cta = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
    _com_ini = _texto_saldo_inicial(ini, desde)
    mw = m_tk.loc[w.index] if m_tk is not None else None
    tabla = _cuenta_corriente(w, s_ini_cta, desde, _com_ini, con_cuenta=False, mascara=mw)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 40 + 35 * len(tabla)),
                 column_config={"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "TK / ACOPIO": st.column_config.TextColumn(width="small"),
                                "COMENTARIOS": st.column_config.TextColumn(width="medium")})

    # ---- Excel y corte del mes ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cons.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        for c in ctas[:40]:
            hoja = str(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _si = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
            _cuenta_corriente(_w, _si, desde, _com_ini).to_excel(xw, index=False, sheet_name=hoja)
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Excel", buf.getvalue(),
                       file_name=f"stock_{'_'.join(secs).lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}", use_container_width=True)
    conectar = ctx.get("conectar")
    if conectar is not None and ctx["puede_seccion"]("STOCK") and secs == [cod]:
        if b2.button(f"🔄 Recalcular saldo inicial {corte:%d/%m}", key=f"nav_mv_corte_{cod}",
                     use_container_width=True):
            try:
                row = _cerrar_corte(conectar, ctx["USR"], cod, hoy)
                invalidar()
                st.toast(f"Saldo inicial recalculado: {int(row[0])} cuenta(s), {float(row[1]):,.1f} TN.")
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo recalcular el saldo inicial: {e}")


# ------------------------------------------------------------------ EXPORTACIÓN (24/09/2026)
# Pedido de dirección: primero SALDO CONSOLIDADO (PRODUCTO · SALDO, siempre visible y al día),
# abajo CUENTA CORRIENTE POR PRODUCTO (FECHA · ORIGEN / DESTINO · N° TICKET · UM · INGRESO ·
# EGRESO · SALDO · COMENTARIOS), con el formato de la planilla de Fer. El saldo consolidado de
# cada producto es exactamente el último SALDO de su cuenta corriente (misma fuente, misma
# fórmula): saldo inicial del corte + movimientos hasta hoy, de los tanques de las tres
# plataformas (Plataforma 1 BPV, Plataforma 2 BPN y Plataforma central).

@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _saldo_hoy(_cf, sector, hoy):
    """Saldo de cada cuenta al cierre de hoy: fn_stock_saldo_a(sector, mañana)."""
    return _saldo_inicial(_cf, sector, date.fromordinal(hoy.toordinal() + 1))


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _cuentas_con_tanque(_cf, sector):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT cuenta FROM produccion.v_cuenta_sector "
                                   "WHERE sector = %s AND tanques_en_uso > 0", conn, params=(sector,))
        return set(df["cuenta"].dropna().astype(str))
    except Exception:
        return set()


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _porteria(_cf, tickets):
    """Ticket de portería → (cliente, procedencia). La procedencia dice de qué sector viene un
    «MOVIMIENTO INTERNO»."""
    if not tickets:
        return {}
    sql = ("SELECT DISTINCT ON (tk) tk, cliente, procedencia FROM ("
           "  SELECT regexp_replace(transaccion::text, '\\.0+$', '') AS tk, cliente, procedencia, fecha_entrada"
           "    FROM produccion.v_transacciones_limpias"
           "   WHERE regexp_replace(transaccion::text, '\\.0+$', '') = ANY(%s)) x "
           "ORDER BY tk, fecha_entrada DESC NULLS LAST")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(list(tickets),))
        return {str(r.tk): (str(r.cliente or "").strip(), str(r.procedencia or "").strip()) for r in df.itertuples()}
    except Exception:
        return {}


_SECTOR_UI = {"REACTORES": "REACTOR", "REACTOR": "REACTOR", "EXPORTACION": "EXPORTACIÓN",
              "EXPORTACIÓN": "EXPORTACIÓN", "BACHAS": "BACHAS", "BACHA": "BACHAS", "PILETAS": "PILETAS",
              "PILETA": "PILETAS"}


def _origen_destino(v, port):
    """ORIGEN / DESTINO como en la planilla: el proveedor (DIECI), el sector interno
    (REACTOR, BACHAS) o la ODV con su cliente. Nunca el tanque."""
    out = []
    for val, tipo, o, d, tk in zip(v["_val"], v["tipo"].fillna(""), v["origen"].fillna(""),
                                   v["destino"].fillna(""), v["ticket"].fillna("")):
        if tipo == "AJUSTE":
            out.append("AJUSTE")
            continue
        entra = tipo == "ENTRADA" or (tipo != "SALIDA" and val > 0)
        x = str(o if entra else d)
        if x.startswith("Portería · "):
            nom = x[len("Portería · "):].strip()
            if "MOVIMIENTO INTERNO" in nom.upper():
                proc = (port.get(re.sub(r"\.0+$", "", str(tk))) or ("", ""))[1].upper()
                nom = _SECTOR_UI.get(proc, proc) or "MOVIMIENTO INTERNO"
            out.append(nom)
        elif re.match(r"^RE-\d+", x):
            out.append("REACTOR")
        elif re.match(r"^BA-\d+", x):
            out.append("BACHAS")
        elif x.startswith("Cambio de categoría"):
            out.append("CAMBIO DE CATEGORÍA")
        else:
            out.append(x or "—")
    return out


def _ar(x, dec=2):
    """Número como en la planilla: 1.234,56. Sin «-0,00»."""
    x = round(float(x), dec)
    x = x if x != 0 else 0.0
    return f"{x:,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _cc_expo(w, s_ini, desde, um, port, com_ini=""):
    cols = ["FECHA", "ORIGEN / DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO", "SALDO", "COMENTARIOS"]
    cab = {"FECHA": f"{desde:%d/%m/%Y}", "ORIGEN / DESTINO": "SALDO INICIAL", "N° TICKET": "", "UM": um,
           "INGRESO": _ar(s_ini) if s_ini > 0 else "", "EGRESO": _ar(-s_ini) if s_ini < 0 else "",
           "SALDO": _ar(s_ini), "COMENTARIOS": com_ini}
    if w.empty:
        return pd.DataFrame([cab], columns=cols)
    ing = w["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = w["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = s_ini + (ing - egr).cumsum()
    cuerpo = pd.DataFrame({
        "FECHA": w["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y") if not pd.isna(t) else "").values,
        "ORIGEN / DESTINO": _origen_destino(w, port),
        "N° TICKET": _ticket(w),
        "UM": um,
        "INGRESO": ing.map(lambda x: _ar(x) if x else "").values,
        "EGRESO": egr.map(lambda x: _ar(x) if x else "").values,
        "SALDO": saldo.map(_ar).values,
        "COMENTARIOS": _comentario(w, con_tk=True),
    })
    return pd.concat([pd.DataFrame([cab]), cuerpo], ignore_index=True)[cols]


@_FRAGMENT
def _pantalla_expo(ctx, sec):
    cod = sec["codigo"]
    cf = ctx["conn_factory"]
    hoy = date.today()
    corte = _primer_dia_habil(hoy)
    key = f"stkexp_{cod}"
    _, c_um = st.columns([5, 1.2])      # dentro del fragmento: no puede escribir en contenedores de afuera
    um = c_um.radio("Unidad", ["KL", "TN"], horizontal=True, key=f"{key}_um", label_visibility="collapsed")
    col, div = _UM[um]

    # ---- SALDO CONSOLIDADO ----
    sh = _saldo_hoy(cf, cod, hoy)
    if sh is None:
        st.warning("Sin conexión a la base en este momento: volvé a entrar en unos segundos.")
        return
    sh = sh.copy()
    sh["_val"] = pd.to_numeric(sh[col], errors="coerce").fillna(0.0) / div
    sal = sh.groupby("cuenta")["_val"].sum()
    ctas = sorted(set(sal[sal.abs() >= 0.005].index.astype(str)) | _cuentas_con_tanque(cf, cod))
    cons = pd.DataFrame({"PRODUCTO": ctas, f"SALDO ({um})": [_ar(sal.get(c, 0.0)) for c in ctas]})
    st.markdown(f"<div class='section-title' style='margin:8px 0 2px'>SALDO CONSOLIDADO · al {hoy:%d/%m/%Y}</div>",
                unsafe_allow_html=True)
    k_c = f"{key}_prod"
    ev = st.dataframe(cons, hide_index=True, use_container_width=False, key=f"{key}_cons",
                      height=min(600, 38 + 35 * max(len(cons), 1)), on_select="rerun", selection_mode="single-row",
                      column_config={"PRODUCTO": st.column_config.TextColumn(width="medium"),
                                     f"SALDO ({um})": st.column_config.TextColumn(width="medium")})
    try:
        _rows = ev.selection.rows
    except Exception:
        _rows = []
    if _rows and 0 <= _rows[0] < len(ctas) and st.session_state.get(f"{key}_sel_prev") != _rows[0]:
        st.session_state[f"{key}_sel_prev"] = _rows[0]
        st.session_state[k_c] = ctas[_rows[0]]

    # ---- CUENTA CORRIENTE POR PRODUCTO ----
    st.markdown("<div class='section-title' style='margin:16px 0 2px'>CUENTA CORRIENTE POR PRODUCTO</div>",
                unsafe_allow_html=True)
    if not ctas:
        st.dataframe(pd.DataFrame(columns=["FECHA", "ORIGEN / DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO",
                                           "SALDO", "COMENTARIOS"]), hide_index=True, use_container_width=True)
        return
    if st.session_state.get(k_c) not in ctas:
        st.session_state[k_c] = ctas[0]
    st.session_state.setdefault(f"{key}_desde", corte)
    st.session_state.setdefault(f"{key}_hasta", hoy)
    c1, c2, c3 = st.columns([2, 1.2, 1.2])
    cta = c1.selectbox("Producto", ctas, key=k_c)
    desde = c2.date_input("Desde", key=f"{key}_desde", format="DD/MM/YYYY")
    hasta = c3.date_input("Hasta", key=f"{key}_hasta", format="DD/MM/YYYY")
    if hasta < desde:
        desde, hasta = hasta, desde

    df = _movs(cf, (cod,), desde, hasta)
    ini = _saldo_inicial(cf, cod, desde)
    if df is None or ini is None:
        st.warning("Sin conexión a la base en este momento: volvé a intentar en unos segundos.")
        return
    v = df[df["es_stock"] & ~df["es_ajuste_sistema"]].copy()
    v = v[(v["kg_neto"] != 0) | (v["litros_neto"] != 0)]
    v["_val"] = v[col] / div
    w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
    ini = ini.copy()
    ini["_val"] = pd.to_numeric(ini[col], errors="coerce").fillna(0.0) / div
    s_ini = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
    tks = tuple(sorted({re.sub(r"\.0+$", "", str(t)) for t, o, d in zip(w["ticket"].fillna(""), w["origen"].fillna(""),
                                                                      w["destino"].fillna(""))
                        if str(t).strip() and ("Portería" in str(o) or "Portería" in str(d))}))
    port = _porteria(cf, tks)
    tabla = _cc_expo(w, s_ini, desde, um, port, _texto_saldo_inicial(ini, desde))
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(640, 40 + 35 * len(tabla)),
                 column_config={"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "N° TICKET": st.column_config.TextColumn(width="medium"),
                                "COMENTARIOS": st.column_config.TextColumn(width="large")})

    # ---- Excel y avisos ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cons.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        tabla.to_excel(xw, index=False, sheet_name=str(cta)[:28])
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Descargar Excel", buf.getvalue(), file_name=f"stock_exportacion_{cta}_{hoy:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key}_xls", use_container_width=True)
    avisos = [f"Saldo inicial al {desde:%d/%m/%Y}: {_texto_saldo_inicial(ini, desde)}."]
    _neg = [c for c in ctas if sal.get(c, 0.0) < -0.005]
    if _neg:
        avisos.append("Saldo negativo hoy: **" + ", ".join(_neg) + "**.")
    med = _medido(cf, (cod,))
    if med is not None:
        _m = med[0] if um == "TN" else med[1]
        _l = float(sal.sum())
        avisos.append(f"Hoy los tanques miden **{_ar(_m, 1)} {um}** y el libro da **{_ar(_l, 1)} {um}**: "
                      f"diferencia **{_ar(_l - _m, 1)} {um}**.")
    _notificaciones(b2.container(), avisos)


def render_stock(ctx, sec):
    c1, c2 = st.columns([3, 1.2])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>📦 STOCK · {sec['nombre_ui'].upper()}</div>",
                unsafe_allow_html=True)
    if ctx["puede_seccion"]("STOCK"):
        c2.button("📋 Stock clásico (físico por tanque)", key="nav_cc_clasico", use_container_width=True,
                  on_click=_ir_stock_clasico(ctx))
    if sec.get("codigo") in ("REACTORES", "PILETAS"):   # regla de negocio propia (≠ Exportación)
        from .stock_reactor import pantalla
        pantalla(ctx, sec)
        return
    if sec.get("codigo") == "EXPORTACION":
        _pantalla_expo(ctx, sec)
        return
    _movimientos(ctx, sec)
