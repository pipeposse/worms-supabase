# -*- coding: utf-8 -*-
"""Barra de filtros del stock: un solo lugar para buscar movimientos.

Pedido de dirección (23/09): los filtros del stock estaban repartidos por solapa,
cada una con los suyos, sin fecha desde/hasta, sin ticket y sin sector. Acá hay una
sola barra, compacta: cada filtro es un DESPLEGABLE simple (una opción, con
«(todos)» arriba), con ayuda en cada control (tooltip) y los filtros activos
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
    for k in [k for k in st.session_state.keys() if str(k).startswith(_k(key, "g_"))]:
        st.session_state.pop(k, None)


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
_TODOS = "(todos)"


def _sel(col, label, opciones, key, help=None, fmt=None):
    """Desplegable simple con «(todos)» primero. Devuelve None si no se filtra."""
    ops = [_TODOS] + list(opciones)
    v = col.selectbox(label, ops, key=key,
                      format_func=(lambda o: _TODOS if o == _TODOS else (fmt(o) if fmt else o)))
    return None if v == _TODOS else v


def _multi(col, label, opciones, key, help=None, fmt=None, placeholder="Todos"):
    """Desplegable que admite una o varias opciones. Vacío = todos (no filtra)."""
    return col.multiselect(label, list(opciones), key=key, placeholder=placeholder,
                           format_func=(fmt or (lambda o: o)))


def barra(cat, key="stk", titulo="🔎 Buscar en el stock",
          campos=("prod", "sec", "fecha", "tk"),
          extras=("tq", "tipo", "orig", "est", "usr", "anul"),
          catalogos=None, multi=False, extras_fn=None, buscar=False, etiquetas=None, grupos=None):
    """Dibuja la barra y devuelve el dict de filtros elegidos.

    `campos`   → qué va en la barra principal (prod, sec, fecha, tk).
    `extras`   → qué va dentro de «➕ Más» (tq, tipo, orig, est, usr, anul). Vacío = sin botón.
    `catalogos`→ dict opcional para reemplazar las listas (p. ej. {"prod": [...]}) cuando la
                 pantalla filtra otra cosa que el libro de stock. Así la misma barra sirve
                 para Tanques, Portería, Remitos, etc. con el mismo diseño.
    `multi`    → Producto y Sector admiten varias opciones (para comparar). Vacío = todos.
    `extras_fn`→ función que dibuja filtros propios dentro de «➕ Más» y devuelve un dict;
                 reemplaza a `extras`.
    `buscar`   → agrega el botón 🔍 Buscar; la barra devuelve (filtros, apretado).
    `etiquetas`→ dict opcional para renombrar las opciones que se muestran ({valor: texto}).
    `grupos`   → [(clave, etiqueta, opciones)]: una fila de desplegables (uno o varios, vacío =
                 todos) arriba de la barra, en ese orden. Reactor: Materia prima · Insumo ·
                 Producto terminado. Vuelven en f["grupos"] = {clave: [...]}."""
    catalogos = catalogos or {}
    etiquetas = etiquetas or {}
    _fmt_prod = (lambda o: etiquetas.get(o, o)) if etiquetas else None
    if titulo:
        st.markdown(f"#### {titulo}")

    # Limpiar y período se resuelven ANTES de instanciar los widgets: Streamlit no
    # deja tocar session_state de un widget ya dibujado en la misma pasada.
    if st.session_state.pop(_k(key, "reset"), False):
        _limpiar(key)

    productos = catalogos.get("prod") if "prod" in catalogos else _lista(cat, _SQL_PRODUCTOS)
    sectores = catalogos.get("sec") if "sec" in catalogos else _lista(cat, _SQL_SECTORES)

    # desplegables por grupo de producto (primera fila, en el orden que pide la pantalla)
    elegidos_g = {}
    if grupos:
        gcols = st.columns(len(grupos))
        for gc, (clave, etq, ops) in zip(gcols, grupos):
            elegidos_g[clave] = _multi(gc, etq, ops, _k(key, f"g_{clave}"), fmt=_fmt_prod,
                                       placeholder="Todos")

    # valores por defecto: últimos 30 días, sin ningún otro filtro
    st.session_state.setdefault(_k(key, "desde"), date.today() - timedelta(days=29))
    st.session_state.setdefault(_k(key, "hasta"), date.today())

    # atajos de período (arriba de la barra: escriben Desde/Hasta antes de dibujarlos)
    per = st.pills("Período rápido", _PERIODOS, key=_k(key, "per"), default="30 días",
                   label_visibility="collapsed")
    if per and st.session_state.get(_k(key, "per_aplicado")) != per:
        st.session_state[_k(key, "per_aplicado")] = per
        _aplicar_periodo(key, per)
    if not per:
        st.session_state.pop(_k(key, "per_aplicado"), None)

    # columnas según lo que pide la pantalla
    anchos = {"prod": 2.0, "sec": 1.8, "fecha": 2.4, "tk": 1.4}
    _hay_mas = bool(extras) or extras_fn is not None
    # ➕ Más y ✖ Limpiar: chicos y discretos, sin ocupar columna entera (dirección, 24/09)
    cols = st.columns([anchos[c] for c in campos] + ([0.45] if _hay_mas else []) + [0.45])
    ci = 0
    prod = sec = desde = hasta = None
    tk = ""
    if "prod" in campos:
        if multi:
            prod = _multi(cols[ci], "🧪 Producto", productos, _k(key, "prod"), fmt=_fmt_prod,
                          placeholder="Todos los productos")
        else:
            prod = _sel(cols[ci], "🧪 Producto", productos, _k(key, "prod"), fmt=_fmt_prod)
        ci += 1
    if "sec" in campos:
        if multi:
            sec = _multi(cols[ci], "🏭 Sector", sectores, _k(key, "sec"), fmt=_fmt_prod,
                         placeholder="Todos los sectores")
        else:
            sec = _sel(cols[ci], "🏭 Sector", sectores, _k(key, "sec"))
        ci += 1
    if "fecha" in campos:
        cd, ch = cols[ci].columns(2); ci += 1
        desde = cd.date_input("📅 Desde", key=_k(key, "desde"), format="DD/MM/YYYY")
        hasta = ch.date_input("📅 Hasta", key=_k(key, "hasta"), format="DD/MM/YYYY")
    if "tk" in campos:
        tk = cols[ci].text_input("🎫 Ticket", key=_k(key, "tk"), placeholder="6850 · R1234 · MS-…"); ci += 1

    tq = tipo = orig = est = usr = None
    anul = False
    _tq_ids, _u_ids = {}, {}
    propios = {}
    if _hay_mas:
        with cols[ci]:
            ci += 1
            st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
            with st.popover("➕", use_container_width=False):
                if extras_fn is not None:
                    propios = extras_fn() or {}
                    extras = ()
                if "tq" in extras:
                    tqs = cat(_SQL_TANQUES)
                    if tqs is not None and not tqs.empty:
                        _tq_ids = {f"{r['nombre']}  ·  {r['sector']}": int(r["id_tanque"]) for _, r in tqs.iterrows()}
                    tq = _sel(st, "🛢️ Tanque", list(_tq_ids), _k(key, "tq"))
                if "tipo" in extras:
                    tipo = _sel(st, "↕️ Tipo de movimiento", list(_TIPO_UI), _k(key, "tipo"),
                                fmt=lambda t: _TIPO_UI.get(t, t))
                if "orig" in extras:
                    orig = _sel(st, "🔌 Origen", _lista(cat, _SQL_ORIGENES), _k(key, "orig"),
                                fmt=lambda o: _ORIGEN_UI.get(o, o))
                if "est" in extras:
                    est = _sel(st, "📌 Estado", list(_ESTADO_UI), _k(key, "est"),
                               fmt=lambda e: _ESTADO_UI.get(e, e))
                if "usr" in extras:
                    usrs = cat(_SQL_USUARIOS)
                    if usrs is not None and not usrs.empty:
                        _u_ids = {str(r["nombre"]): int(r["id_usuario"]) for _, r in usrs.iterrows()}
                    usr = _sel(st, "👤 Usuario", list(_u_ids), _k(key, "usr"))
                if "anul" in extras:
                    anul = st.checkbox("Incluir anulados", key=_k(key, "anul"), value=False)
    with cols[ci]:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        try:
            _clr = st.button("✖", key=_k(key, "clr"), type="tertiary")
        except Exception:
            _clr = st.button("✖", key=_k(key, "clr"))
        if _clr:
            st.session_state[_k(key, "reset")] = True
            st.rerun()

    if desde and hasta and desde > hasta:      # sin cartel: se invierte solo
        desde, hasta = hasta, desde

    _l = lambda x: (list(x) if isinstance(x, (list, tuple)) else ([x] if x else []))  # noqa: E731
    f = {"prod": _l(prod), "sec": _l(sec), "desde": desde, "hasta": hasta,
         "tk": (tk or "").strip(),
         "tq": [_tq_ids[tq]] if tq in _tq_ids else [], "tq_lbl": [tq] if tq else [],
         "tipo": [tipo] if tipo else [], "orig": [orig] if orig else [], "est": [est] if est else [],
         "usr": [_u_ids[usr]] if usr in _u_ids else [], "usr_lbl": [usr] if usr else [], "anul": bool(anul),
         "propios": propios, "grupos": elegidos_g}
    _chips(f, etiquetas, grupos)
    if buscar:
        apretado = st.button("🔍 Buscar", key=_k(key, "go"), type="primary")
        return f, apretado
    return f


def _chips(f, etiquetas=None, grupos=None):
    """Los filtros activos, como chips: se ve de un vistazo qué está filtrando."""
    etiquetas = etiquetas or {}
    chips = []
    for clave, etq, _ops in (grupos or []):
        sel = (f.get("grupos") or {}).get(clave) or []
        if sel:
            chips.append(etq.split(" ")[0] + " " + ", ".join(etiquetas.get(p, p).split(" · ")[0] for p in sel[:4])
                         + ("…" if len(sel) > 4 else ""))
    if f["prod"]:
        chips.append("🧪 " + ", ".join(etiquetas.get(p, p) for p in f["prod"][:4]) + ("…" if len(f["prod"]) > 4 else ""))
    if f["sec"]:
        chips.append("🏭 " + ", ".join(etiquetas.get(x, x) for x in f["sec"][:3]) + ("…" if len(f["sec"]) > 3 else ""))
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
    for k, val in (f.get("propios") or {}).items():
        if val not in (None, "", [], False, "(todos)"):
            chips.append(f"{k}: {', '.join(map(str, val)) if isinstance(val, (list, tuple)) else val}")
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
    # hora de planta: pandas devuelve los timestamptz en UTC (se veían 3 h adelantados)
    try:
        _t = pd.to_datetime(d["momento"], errors="coerce")
        if getattr(_t.dt, "tz", None) is not None:
            _t = _t.dt.tz_convert("America/Argentina/Buenos_Aires").dt.tz_localize(None)
        d["momento"] = _t
    except Exception:
        pass
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
