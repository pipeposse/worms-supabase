# -*- coding: utf-8 -*-
"""Barra de filtros del stock: un solo lugar para buscar movimientos.

Pedido de dirección (23/09): los filtros del stock estaban repartidos por solapa,
cada una con los suyos, sin fecha desde/hasta, sin ticket y sin sector. Acá hay una
sola barra, compacta, con ayuda en cada control (tooltip) y los filtros activos
resumidos en chips:

    🧪 Producto · 🏭 Sector · 📅 Desde / Hasta (calendario) · 🎫 Ticket · ➕ Más

«➕ Más» abre los filtros secundarios (tanque, tipo, origen, estado, usuario,
anulados) sin ensuciar la barra. Los atajos de período (Hoy / 7 días / 30 días /
Este mes) escriben las fechas, no las reemplazan: el usuario siempre puede
ajustarlas con el calendario.

El filtrado es en la base (no en pandas): con 17.000 movimientos y creciendo, traer
todo para filtrar en memoria era lo que hacía lenta la solapa 🔁 Movimientos.
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

# ------------------------------------------------------------------ catálogos
_SQL_PRODUCTOS = ("SELECT DISTINCT COALESCE(producto, codigo_insumo) AS p "
                  "FROM produccion.fact_movimiento_stock WHERE COALESCE(producto, codigo_insumo) IS NOT NULL "
                  "ORDER BY 1")
_SQL_SECTORES = ("SELECT DISTINCT sector FROM produccion.dim_tanque "
                 "WHERE sector IS NOT NULL AND COALESCE(activo,true) ORDER BY 1")
_SQL_TANQUES = ("SELECT id_tanque, nombre, sector FROM produccion.dim_tanque "
                "WHERE COALESCE(activo,true) ORDER BY sector, nombre")
_SQL_ORIGENES = ("SELECT DISTINCT origen FROM produccion.fact_movimiento_stock "
                 "WHERE origen IS NOT NULL ORDER BY 1")
_SQL_USUARIOS = ("SELECT DISTINCT u.id_usuario, u.nombre FROM produccion.fact_movimiento_stock m "
                 "JOIN produccion.dim_usuario u ON u.id_usuario = COALESCE(m.id_usuario_ejecuta, m.id_usuario) "
                 "ORDER BY u.nombre")

_ORIGEN_UI = {"lab_sync": "Laboratorio (automático)", "planificacion": "Planificación",
              "carga_operario": "Operario", "decantacion": "Decantación",
              "sistema": "Reconciliación", "sync_wedo": "Sensor WeDo",
              "ajuste_manual": "Ajuste manual", "porteria_sync": "Portería",
              "recuperacion_ag": "Recuperación AG", "despacho": "Despacho / exportación",
              "asignacion_afe": "Asignación AFE", "efluente_porteria": "Efluentes (portería)"}
_TIPO_UI = {"ENTRADA": "🟢 Entrada", "SALIDA": "🔴 Salida", "AJUSTE": "🟡 Ajuste"}
_ESTADO_UI = {"EJECUTADO": "Ejecutado", "PLANIFICADO": "Planificado", "ANULADO": "Anulado"}

_PERIODOS = ["Hoy", "7 días", "30 días", "Este mes", "Todo"]


def _lista(cat, sql, col=0):
    try:
        df = cat(sql)
        return [] if df is None or df.empty else df.iloc[:, col].dropna().astype(str).tolist()
    except Exception:
        return []


def _k(key, nombre):
    return f"{key}_{nombre}"


# ------------------------------------------------------------------ estado
def _limpiar(key):
    for n in ("prod", "sec", "desde", "hasta", "tk", "tq", "tipo", "orig", "est", "usr", "anul", "per", "per_aplicado"):
        st.session_state.pop(_k(key, n), None)


def _aplicar_periodo(key, per):
    hoy = date.today()
    if per == "Hoy":
        d, h = hoy, hoy
    elif per == "7 días":
        d, h = hoy - timedelta(days=6), hoy
    elif per == "30 días":
        d, h = hoy - timedelta(days=29), hoy
    elif per == "Este mes":
        d, h = hoy.replace(day=1), hoy
    else:
        d, h = None, None
    st.session_state[_k(key, "desde")] = d
    st.session_state[_k(key, "hasta")] = h


# ------------------------------------------------------------------ barra
def barra(cat, key="stk", titulo="🔎 Buscar en el stock"):
    """Dibuja la barra y devuelve el dict de filtros elegidos."""
    st.markdown(f"#### {titulo}")

    # Limpiar y período se resuelven ANTES de instanciar los widgets: Streamlit no
    # deja tocar session_state de un widget ya dibujado en la misma pasada.
    if st.session_state.pop(_k(key, "reset"), False):
        _limpiar(key)

    productos = _lista(cat, _SQL_PRODUCTOS)
    sectores = _lista(cat, _SQL_SECTORES)

    # valores por defecto: últimos 30 días, sin ningún otro filtro
    st.session_state.setdefault(_k(key, "desde"), date.today() - timedelta(days=29))
    st.session_state.setdefault(_k(key, "hasta"), date.today())

    # atajos de período (arriba de la barra: escriben Desde/Hasta antes de dibujarlos)
    per = st.pills("Período rápido", _PERIODOS, key=_k(key, "per"), default="30 días",
                   label_visibility="collapsed",
                   help="Escribe Desde/Hasta; después podés ajustarlas con el calendario.")
    if per and st.session_state.get(_k(key, "per_aplicado")) != per:
        st.session_state[_k(key, "per_aplicado")] = per
        _aplicar_periodo(key, per)
    if not per:
        st.session_state.pop(_k(key, "per_aplicado"), None)

    c1, c2, c3, c4, c5, c6, c7 = st.columns([2.2, 1.8, 1.2, 1.2, 1.3, 0.8, 0.8])
    prod = c1.multiselect("🧪 Producto", productos, key=_k(key, "prod"), placeholder="Todos los productos",
                          help="Uno o varios productos. Vacío = todos.")
    sec = c2.multiselect("🏭 Sector", sectores, key=_k(key, "sec"), placeholder="Todos los sectores",
                         help="Sector del tanque donde ocurrió el movimiento (plataformas, reactores, piletas…).")
    desde = c3.date_input("📅 Desde", key=_k(key, "desde"), format="DD/MM/YYYY",
                          help="Primer día incluido. Tocá el campo para abrir el calendario.")
    hasta = c4.date_input("📅 Hasta", key=_k(key, "hasta"), format="DD/MM/YYYY",
                          help="Último día incluido (hasta las 23:59).")
    tk = c5.text_input("🎫 Ticket", key=_k(key, "tk"), placeholder="6850 · R1234 · MS-…",
                       help="Número de ticket de portería, ticket de laboratorio o ticket de movimiento (MS-…). "
                            "Busca por coincidencia parcial.")

    # ➕ Más filtros: los secundarios, en un popover para no cargar la barra
    with c6:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        with st.popover("➕ Más", help="Tanque, tipo de movimiento, origen, estado, usuario, anulados", use_container_width=True):
            tqs = cat(_SQL_TANQUES)
            _tq_opts = ([f"{r['nombre']}  ·  {r['sector']}" for _, r in tqs.iterrows()]
                        if tqs is not None and not tqs.empty else [])
            _tq_ids = ({f"{r['nombre']}  ·  {r['sector']}": int(r["id_tanque"]) for _, r in tqs.iterrows()}
                       if tqs is not None and not tqs.empty else {})
            tq = st.multiselect("🛢️ Tanque", _tq_opts, key=_k(key, "tq"), placeholder="Todos")
            tipo = st.multiselect("↕️ Tipo", list(_TIPO_UI), key=_k(key, "tipo"),
                                  format_func=lambda t: _TIPO_UI.get(t, t), placeholder="Entradas, salidas y ajustes")
            origs = _lista(cat, _SQL_ORIGENES)
            orig = st.multiselect("🔌 Origen", origs, key=_k(key, "orig"),
                                  format_func=lambda o: _ORIGEN_UI.get(o, o), placeholder="Todos")
            est = st.multiselect("📌 Estado", list(_ESTADO_UI), key=_k(key, "est"),
                                 format_func=lambda e: _ESTADO_UI.get(e, e), placeholder="Ejecutado y planificado")
            usrs = cat(_SQL_USUARIOS)
            _u_opts = usrs["nombre"].astype(str).tolist() if usrs is not None and not usrs.empty else []
            _u_ids = ({str(r["nombre"]): int(r["id_usuario"]) for _, r in usrs.iterrows()}
                      if usrs is not None and not usrs.empty else {})
            usr = st.multiselect("👤 Usuario", _u_opts, key=_k(key, "usr"), placeholder="Todos")
            anul = st.checkbox("Incluir anulados", key=_k(key, "anul"), value=False)
    with c7:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if st.button("✖ Limpiar", key=_k(key, "clr"), use_container_width=True, help="Vuelve a «últimos 30 días» sin filtros."):
            st.session_state[_k(key, "reset")] = True
            st.rerun()

    if desde and hasta and desde > hasta:
        st.warning("«Desde» es posterior a «Hasta»: no va a encontrar nada.")

    f = {"prod": prod, "sec": sec, "desde": desde, "hasta": hasta, "tk": (tk or "").strip(),
         "tq": [_tq_ids[x] for x in (tq or []) if x in _tq_ids], "tq_lbl": tq or [],
         "tipo": tipo or [], "orig": orig or [], "est": est or [],
         "usr": [_u_ids[x] for x in (usr or []) if x in _u_ids], "usr_lbl": usr or [], "anul": bool(anul)}
    _chips(f)
    return f


def _chips(f):
    """Los filtros activos, como chips: se ve de un vistazo qué está filtrando."""
    chips = []
    if f["prod"]:
        chips.append("🧪 " + ", ".join(f["prod"][:4]) + ("…" if len(f["prod"]) > 4 else ""))
    if f["sec"]:
        chips.append("🏭 " + ", ".join(f["sec"][:3]) + ("…" if len(f["sec"]) > 3 else ""))
    if f["desde"] or f["hasta"]:
        chips.append("📅 %s → %s" % (f["desde"].strftime("%d/%m/%y") if f["desde"] else "inicio",
                                     f["hasta"].strftime("%d/%m/%y") if f["hasta"] else "hoy"))
    if f["tk"]:
        chips.append("🎫 " + f["tk"])
    if f["tq_lbl"]:
        chips.append("🛢️ " + ", ".join(x.split("  ·  ")[0] for x in f["tq_lbl"][:3]) + ("…" if len(f["tq_lbl"]) > 3 else ""))
    if f["tipo"]:
        chips.append(" ".join(_TIPO_UI.get(t, t) for t in f["tipo"]))
    if f["orig"]:
        chips.append("🔌 " + ", ".join(_ORIGEN_UI.get(o, o) for o in f["orig"][:3]))
    if f["est"]:
        chips.append("📌 " + ", ".join(_ESTADO_UI.get(e, e) for e in f["est"]))
    if f["usr_lbl"]:
        chips.append("👤 " + ", ".join(f["usr_lbl"][:3]))
    if f["anul"]:
        chips.append("incluye anulados")
    if chips:
        st.markdown(" ".join(
            f"<span style='display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;border-radius:999px;"
            f"background:rgba(37,92,138,.10);border:1px solid rgba(37,92,138,.35);font-size:.82rem'>{c}</span>"
            for c in chips), unsafe_allow_html=True)


# ------------------------------------------------------------------ consulta
def consulta(f, limite=5000):
    """SQL + parámetros para fact_movimiento_stock con los filtros elegidos."""
    where, params = [], []
    if not f["anul"]:
        where.append("COALESCE(m.anulado,false) = false")
    if f["desde"]:
        where.append("m.momento >= %s"); params.append(f["desde"])
    if f["hasta"]:
        where.append("m.momento < %s"); params.append(f["hasta"] + timedelta(days=1))
    if f["prod"]:
        where.append("COALESCE(m.producto, m.codigo_insumo) = ANY(%s)"); params.append(list(f["prod"]))
    if f["sec"]:
        where.append("t.sector = ANY(%s)"); params.append(list(f["sec"]))
    if f["tq"]:
        where.append("m.id_tanque = ANY(%s)"); params.append(list(f["tq"]))
    if f["tipo"]:
        where.append("m.tipo_movimiento = ANY(%s)"); params.append(list(f["tipo"]))
    if f["orig"]:
        where.append("m.origen = ANY(%s)"); params.append(list(f["orig"]))
    if f["est"]:
        where.append("m.estado_mov = ANY(%s)"); params.append(list(f["est"]))
    if f["usr"]:
        where.append("COALESCE(m.id_usuario_ejecuta, m.id_usuario) = ANY(%s)"); params.append(list(f["usr"]))
    if f["tk"]:
        like = "%" + f["tk"].upper() + "%"
        if f["tk"].isdigit():
            # número pelado = ticket de portería exacto (el MS-000xxxx no debe colarse
            # porque contenga esos dígitos); lab y orden siguen por coincidencia parcial
            where.append("(regexp_replace(COALESCE(m.ticket_porteria,''),'\\.0+$','') = %s "
                         " OR upper(COALESCE(m.ticket_lab,'')) LIKE %s OR upper(COALESCE(m.identificador_prod,'')) LIKE %s)")
            params += [f["tk"], like, like]
        else:
            where.append("(upper(COALESCE(m.ticket_porteria,'')) LIKE %s OR upper(COALESCE(m.ticket_lab,'')) LIKE %s "
                         " OR upper(COALESCE(m.ticket_mov,'')) LIKE %s OR upper(COALESCE(m.identificador_prod,'')) LIKE %s)")
            params += [like, like, like, like]
    sql = ("SELECT m.id_mov_stock, m.momento, m.tipo_movimiento, COALESCE(m.producto, m.codigo_insumo) AS producto, "
           "       COALESCE(t.nombre, m.tanque_label) AS tanque, t.sector, "
           "       m.kg, m.litros, m.ticket_porteria, m.ticket_lab, m.ticket_mov, m.identificador_prod AS orden, "
           "       m.origen, m.estado_mov, COALESCE(m.anulado,false) AS anulado, u.nombre AS usuario, m.observaciones "
           "FROM produccion.fact_movimiento_stock m "
           "LEFT JOIN produccion.dim_tanque t ON t.id_tanque = m.id_tanque "
           "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = COALESCE(m.id_usuario_ejecuta, m.id_usuario) "
           + ("WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY m.momento DESC LIMIT %s")
    params.append(int(limite))
    return sql, tuple(params)


# ------------------------------------------------------------------ resultados
def resultados(cat, f, key="stk"):
    sql, params = consulta(f)
    try:
        df = cat(sql, params)
    except Exception as e:
        st.error(f"No se pudo leer el stock: {e}")
        return None
    if df is None or df.empty:
        st.info("Ningún movimiento coincide con estos filtros.")
        return df
    d = df.copy()
    d["kg"] = pd.to_numeric(d["kg"], errors="coerce").fillna(0)
    ent = d.loc[d["tipo_movimiento"] == "ENTRADA", "kg"].sum() / 1000.0
    sal = d.loc[d["tipo_movimiento"] == "SALIDA", "kg"].sum() / 1000.0
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Movimientos", f"{len(d):,}".replace(",", "."))
    k2.metric("🟢 Entró", f"{ent:,.1f} TN")
    k3.metric("🔴 Salió", f"{sal:,.1f} TN")
    k4.metric("Saldo", f"{ent - sal:,.1f} TN")
    if len(d) >= 5000:
        st.caption("Se muestran los 5.000 más recientes: acotá el período o el producto para ver el resto.")

    d["Tipo"] = d["tipo_movimiento"].map(_TIPO_UI).fillna(d["tipo_movimiento"])
    d["TN"] = d["kg"] / 1000.0
    d["Ticket"] = d["ticket_porteria"].fillna(d["ticket_lab"]).fillna(d["ticket_mov"])
    d["Origen"] = d["origen"].map(_ORIGEN_UI).fillna(d["origen"])
    d["Estado"] = d["estado_mov"].map(_ESTADO_UI).fillna(d["estado_mov"])
    d.loc[d["anulado"] == True, "Estado"] = "Anulado"  # noqa: E712
    cols = ["momento", "Tipo", "producto", "tanque", "sector", "TN", "Ticket", "orden", "Origen", "usuario", "Estado", "observaciones"]
    st.dataframe(d[cols].rename(columns={"momento": "Fecha", "producto": "Producto", "tanque": "Tanque",
                                         "sector": "Sector", "orden": "Orden", "usuario": "Usuario",
                                         "observaciones": "Obs."}),
                 use_container_width=True, hide_index=True, height=min(80 + 35 * len(d), 560),
                 column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm"),
                                "TN": st.column_config.NumberColumn(format="%.2f"),
                                "Obs.": st.column_config.TextColumn(width="medium")})
    st.download_button("⬇️ Descargar CSV", d[cols].to_csv(index=False).encode("utf-8"),
                       "movimientos_stock.csv", "text/csv", key=_k(key, "dl"))
    return d


def render(cat, key="stk"):
    f = barra(cat, key=key)
    return resultados(cat, f, key=key)
