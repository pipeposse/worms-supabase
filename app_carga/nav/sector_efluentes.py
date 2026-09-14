# -*- coding: utf-8 -*-
"""Home del sector Disposición Final de Líquidos (efluentes líquidos).

Pedido de dirección (14/09): al entrar a este sector se ve SOLO lo de efluentes
líquidos; nada de otros sectores. Antes la tarjeta abría la sección Laboratorio
completa (todos los productos, todas las vistas).

Todo lo que se muestra acá está filtrado por producto_base / producto_lab =
"DISPOSICION FINAL DE LIQUIDOS" (así se llama en portería y en el laboratorio):
    · indicadores del día y del mes (camiones, TN, análisis pendientes)
    · análisis de efluente (formulario EFLUENTE de lab_carga, con el ticket ya elegido)
    · pendientes de laboratorio del día
    · buscar y editar análisis ya cargados
    · camiones ingresados (portería) con exportación a CSV

No hay lógica de negocio nueva: se reutilizan las funciones de lab_carga.py.
"""

from datetime import date, timedelta
import uuid

import pandas as pd
import streamlit as st

from .kpis import _TTL, _kpi, _n, _i

PB = "DISPOSICION FINAL DE LIQUIDOS"          # producto_base (portería) y producto_lab (laboratorio)
_MODOS = ["🧪 Analizar efluente", "📋 Pendientes", "✏️ Buscar y editar", "🚛 Camiones ingresados"]
_EXCL_CLI = ("NOT EXISTS (SELECT 1 FROM produccion.dic_cliente_excluido e WHERE e.activo "
             "AND upper(COALESCE(t.cliente,'')) LIKE upper(e.patron))")


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer_kpis(_cf, dia):
    sql = f"""
        SELECT count(*) FILTER (WHERE t.fecha_entrada::date = %s)                                   AS camiones_hoy,
               COALESCE(sum(abs(t.peso_neto)) FILTER (WHERE t.fecha_entrada::date = %s), 0)/1000.0   AS tn_hoy,
               count(*)                                                                             AS camiones_mes,
               COALESCE(sum(abs(t.peso_neto)), 0)/1000.0                                            AS tn_mes,
               count(*) FILTER (WHERE t.fecha_entrada::date = %s AND COALESCE(t.evaluado,'NO') <> 'SI') AS pend_hoy,
               count(*) FILTER (WHERE t.fecha_entrada::date = %s AND COALESCE(t.evaluado,'NO') = 'SI')  AS eval_hoy,
               count(DISTINCT t.cliente) FILTER (WHERE t.fecha_entrada::date = %s)                  AS clientes_hoy
        FROM produccion.v_transacciones_limpias t
        WHERE t.producto_base = %s
          AND t.fecha_entrada >= date_trunc('month', %s::date)
          AND t.fecha_entrada <  date_trunc('month', %s::date) + interval '1 month'
          AND {_EXCL_CLI}
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(dia, dia, dia, dia, dia, PB, dia, dia))
        return df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _camiones(_cf, desde, hasta):
    # "En stock": cada camión de efluente es una ENTRADA a piletas en el libro de stock
    # (produccion.fn_sync_movimientos_efluente, corre cada 15 minutos).
    sql = f"""
        SELECT t.transaccion::bigint AS ticket, t.fecha_entrada::date AS fecha, t.hora_e AS hora,
               t.cliente, t.procedencia, t.transporte, t.patente_chasis, t.patente_acoplado,
               abs(t.peso_neto) AS kg, t.evaluado,
               EXISTS (SELECT 1 FROM produccion.fact_movimiento_stock m
                        WHERE m.origen = 'efluente_porteria' AND NOT m.anulado
                          AND regexp_replace(m.ticket_porteria, '\\.0+$', '')
                              = regexp_replace(t.transaccion::text, '\\.0+$', '')) AS en_stock
        FROM produccion.v_transacciones_limpias t
        WHERE t.producto_base = %s AND t.fecha_entrada::date BETWEEN %s AND %s AND {_EXCL_CLI}
        ORDER BY t.fecha_entrada DESC, t.transaccion DESC
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(PB, desde, hasta))
        df["kg"] = pd.to_numeric(df["kg"], errors="coerce")
        return df
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _flujo_piletas(_cf, n=6):
    """Mes a mes: efluente que entró a piletas vs AG recuperado que salió."""
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                "SELECT mes, camiones_efluente, efluente_tn, camiones_ag, ag_recuperado_tn, "
                "rendimiento_pct FROM produccion.v_piletas_flujo ORDER BY mes DESC LIMIT %s",
                conn, params=(int(n),))
    except Exception:
        return None


def _invalidar():
    _leer_kpis.clear()
    _camiones.clear()
    _flujo_piletas.clear()


# ------------------------------------------------------------------ indicadores
def _indicadores(ctx):
    k = _leer_kpis(ctx["conn_factory"], date.today())
    if not k:
        st.caption("Indicadores del sector: sin conexión a la base en este momento.")
        return
    ch, th = _i(k.get("camiones_hoy")), float(k.get("tn_hoy") or 0)
    c1 = _kpi("Camiones de efluente hoy", str(ch),
              (f"{_n(th)} TN · {_i(k.get('clientes_hoy'))} cliente(s)" if ch else "todavía no ingresó ninguno"),
              "ok" if ch else "")
    c2 = _kpi("Efluente del mes",
              f"{_n(float(k.get('tn_mes') or 0))}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{_i(k.get('camiones_mes'))} camiones · {date.today().strftime('%B %Y')}", "")
    pend, ev = _i(k.get("pend_hoy")), _i(k.get("eval_hoy"))
    c3 = _kpi("Análisis pendientes hoy", str(pend),
              (f"{ev} evaluados · faltan {pend}" if pend else (f"{ev} evaluados · completo ✅" if ev else "sin ingresos")),
              "warn" if pend else ("ok" if ev else ""))
    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ modos
def _modo_analizar(ctx, lab, get_conn, usuario):
    ss = st.session_state
    st.markdown("**Ticket de portería** — escribí el número o elegilo de la lista (sólo camiones de efluente líquido, últimos 90 días).")
    c1, c2 = st.columns([1.2, 3])
    f_tk = c1.text_input("Nº de ticket", key="ef_tk", help="Número del ticket de portería del camión de efluente.")
    try:
        ticks = lab.tickets_porteria([PB], f_tk or None, 90, get_conn=get_conn)
    except Exception as e:
        ticks = []
        st.caption(f"(no pude leer tickets: {e})")
    tk_sel = None
    if ticks:
        opt = {"— sin ticket —": None}
        for t in ticks:
            opt[lab._lbl_tk(t)] = t
        keys = list(opt.keys())
        ft = (f_tk or "").strip()
        auto = 0
        if ft:
            for i, (_, tv) in enumerate(opt.items()):
                if tv and str(tv["transaccion"]) == ft:
                    auto = i
                    break
        eleg = c2.selectbox(f"Ticket ({len(ticks)})", keys, index=auto, key=f"ef_tksel_{ft}")
        tk_sel = opt[eleg]
    else:
        c2.caption("No hay tickets de efluente líquido en los últimos 90 días con ese número.")
    pf = {"producto_lab": PB}
    if tk_sel:
        pf.update(ticket=str(tk_sel["transaccion"]), patente_chasis=tk_sel.get("patente_chasis"),
                  patente_acoplado=tk_sel.get("patente_acoplado"))
        st.success(f"Ticket #{tk_sel['transaccion']} · {tk_sel.get('cliente') or '-'} · "
                   f"{str(tk_sel.get('fecha_entrada') or '')[:10]} · patentes "
                   f"{tk_sel.get('patente_chasis') or '-'}/{tk_sel.get('patente_acoplado') or '-'}"
                   + (" · ya evaluado ✓" if str(tk_sel.get("evaluado")).upper() == "SI" else ""))
    tkid = (f_tk or "").strip() or (str(tk_sel["transaccion"]) if tk_sel else "blank")
    tok = f"{ss['lab_tok']}_ef_{tkid}"
    lab._form_EFLUENTE(pf, None, tok, get_conn, usuario)

    st.divider()
    st.markdown("#### 📋 Efluentes cargados hoy")
    try:
        hoy = [r for r in lab.cargas_del_dia(get_conn=get_conn)
               if _es_efluente(r.get("Producto"))]
    except Exception as e:
        hoy = []
        st.caption(f"(no pude leer lo cargado hoy: {e})")
    if not hoy:
        st.caption("Todavía no se cargó ningún análisis de efluente hoy.")
    else:
        st.caption(f"{len(hoy)} análisis de efluente cargado(s) hoy")
        st.dataframe(hoy, use_container_width=True, hide_index=True)


def _es_efluente(v):
    s = str(v or "").upper()
    return s == PB or s == "EFLUENTE" or ("EFLU" in s and "LIQU" in s)


def _modo_pendientes(ctx, lab, get_conn):
    ss = st.session_state
    st.markdown("**Camiones de efluente sin análisis** — tocá **Evaluar** y se abre el formulario con ese ticket cargado.")
    ss.setdefault("ef_pend_dia", date.today())
    cprev, cdia, cnext = st.columns([1, 2, 1])
    if cprev.button("◀ Día anterior", key="ef_pend_prev", use_container_width=True):
        ss["ef_pend_dia"] = ss["ef_pend_dia"] - timedelta(days=1)
        st.rerun()
    dia = cdia.date_input("Día", value=ss["ef_pend_dia"], key="ef_pend_dia_inp", format="DD/MM/YYYY")
    ss["ef_pend_dia"] = dia
    hoy = date.today()
    if cnext.button("Día siguiente ▶", key="ef_pend_next", use_container_width=True, disabled=(dia >= hoy)):
        ss["ef_pend_dia"] = min(dia + timedelta(days=1), hoy)
        st.rerun()
    try:
        pend = lab.tickets_pendientes(dia, get_conn=get_conn, producto_base=[PB])
    except Exception as e:
        pend = []
        st.error(f"No pude leer pendientes: {e}")
    et = "hoy" if dia == hoy else dia.strftime("%d/%m/%Y")
    if not pend:
        st.success(f"✅ Sin camiones de efluente pendientes de análisis para {et}.")
        return
    st.caption(f"{len(pend)} camión(es) de efluente sin evaluar · {et}")
    for ix, t in enumerate(pend):
        pat = "/".join([x for x in [t.get("patente_chasis"), t.get("patente_acoplado")] if x])
        tn = abs(t.get("peso_neto") or 0) / 1000.0
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**#{t['transaccion']}** · {(t.get('cliente') or '')[:28]}"
                    f"{(' · ' + pat) if pat else ''}{(f' · {tn:,.1f} TN' if tn else '')}")
        if c2.button("Evaluar", key=f"ef_pend_ev_{ix}_{t['transaccion']}", use_container_width=True):
            ss["ef_tk"] = str(t["transaccion"])
            ss["_ef_force_modo"] = _MODOS[0]
            st.rerun()


def _modo_editar(ctx, lab, get_conn, usuario):
    ss = st.session_state
    with st.expander("Buscar análisis de efluente", expanded=(ss.get("ef_edit_ctx") is None)):
        c1, c2 = st.columns([3, 1])
        ticket = c1.text_input("Ticket contiene", key="ef_q_ticket")
        buscar = c2.button("Buscar", key="ef_q_btn", use_container_width=True)
        if buscar:
            try:
                ss["ef_busqueda"] = lab.buscar_registros(ticket=ticket or None, producto=PB, get_conn=get_conn)
            except Exception as e:
                st.error(f"Error buscando: {e}")
                ss["ef_busqueda"] = []
        res = ss.get("ef_busqueda", [])
        if res:
            def _lbl(r):
                f = str(r["fecha"])[:16] if r.get("fecha") else "s/f"
                org = "APP" if r["source_id"] == lab.APP_SOURCE else "Access"
                return (f"[{org}] {f} · tk {r.get('ticket') or '-'} · cal {r.get('calidad_final_lab') or '-'} "
                        f"· {r.get('rechazado') or '-'} · id {r['id_access']}")
            opciones = {_lbl(r): r for r in res}
            eleg = st.selectbox(f"{len(res)} resultado(s)", list(opciones.keys()), key="ef_sel")
            if st.button("Cargar para editar", key="ef_edit_btn", type="primary", use_container_width=True):
                r = opciones[eleg]
                full = lab.cargar_registro(r["source_id"], r["id_access"], get_conn=get_conn)
                ss["ef_edit_ctx"] = {"source_id": r["source_id"], "id_access": r["id_access"], "full": full}
                ss["lab_tok"] = uuid.uuid4().hex[:8]
                st.rerun()
        elif buscar:
            st.info("Sin resultados.")
    ctx_ed = ss.get("ef_edit_ctx")
    if not ctx_ed:
        return
    full = ctx_ed["full"] or {}
    org = "la app" if ctx_ed["source_id"] == lab.APP_SOURCE else "Access (se adopta al guardar)"
    st.info(f"Editando análisis id {ctx_ed['id_access']} · origen: {org}")
    if st.button("✖ Cancelar edición", key="ef_edit_cancel"):
        ss["ef_edit_ctx"] = None
        st.rerun()
    st.divider()
    lab._form_EFLUENTE(full, ctx_ed, f"{ss['lab_tok']}_efed_{ctx_ed['id_access']}", get_conn, usuario)


def _modo_camiones(ctx):
    c1, c2 = st.columns(2)
    desde = c1.date_input("Desde", value=date.today().replace(day=1), key="ef_cam_desde", format="DD/MM/YYYY")
    hasta = c2.date_input("Hasta", value=date.today(), key="ef_cam_hasta", format="DD/MM/YYYY")
    df = _camiones(ctx["conn_factory"], desde, hasta)
    if df is None:
        st.warning("No pude leer los ingresos de portería.")
        return
    if df.empty:
        st.info("Sin camiones de efluente líquido en el rango.")
        return
    clis = sorted(df["cliente"].dropna().astype(str).str.strip().unique().tolist())
    sel = st.multiselect("Cliente (vacío = todos)", clis, key="ef_cam_cli")
    if sel:
        df = df[df["cliente"].astype(str).str.strip().isin(sel)]
    tot = float(df["kg"].sum() or 0)
    _falta_stock = int((~df["en_stock"].fillna(False).astype(bool)).sum())
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Camiones", len(df))
    m2.metric("TN netas", f"{tot/1000:,.1f}")
    m3.metric("TN por camión", f"{(tot/len(df))/1000:,.2f}" if len(df) else "—")
    m4.metric("Sin análisis", int((df["evaluado"].fillna("NO").astype(str).str.upper() != "SI").sum()))
    m5.metric("Sin registrar en stock", _falta_stock,
              help="Cada camión de efluente se registra solo como entrada a piletas en el libro de stock; "
                   "la sincronización corre cada 15 minutos.")
    dm = df.copy()
    dm["mes"] = pd.to_datetime(dm["fecha"]).dt.to_period("M").astype(str)
    por_mes = dm.groupby("mes")["kg"].sum().div(1000).round(1).reset_index().rename(columns={"kg": "TN"})
    if len(por_mes) > 1:
        st.bar_chart(por_mes, x="mes", y="TN", use_container_width=True)
    vista = df.rename(columns={"ticket": "Ticket", "fecha": "Fecha", "hora": "Hora", "cliente": "Cliente",
                               "procedencia": "Procedencia", "transporte": "Transporte",
                               "patente_chasis": "Chasis", "patente_acoplado": "Acoplado",
                               "kg": "Kg", "evaluado": "Analizado", "en_stock": "En stock"})
    st.dataframe(vista, use_container_width=True, hide_index=True, height=420)
    st.download_button("⬇️ Descargar CSV", vista.to_csv(index=False).encode("utf-8"),
                       file_name=f"efluentes_{desde}_{hasta}.csv", mime="text/csv", key="ef_cam_csv")
    _flujo(ctx)


def _flujo(ctx):
    """Las piletas como proceso: entra efluente, sale AG recuperado."""
    st.markdown("#### 🕳️ Qué pasa con ese efluente en las piletas")
    fl = _flujo_piletas(ctx["conn_factory"])
    if fl is None or fl.empty:
        st.caption("Todavía no hay movimientos de piletas para mostrar.")
        return
    v = fl.rename(columns={"mes": "Mes", "camiones_efluente": "Camiones efluente",
                           "efluente_tn": "Efluente (TN)", "camiones_ag": "Camiones AG",
                           "ag_recuperado_tn": "AG recuperado (TN)", "rendimiento_pct": "Recuperado %"})
    st.dataframe(v, use_container_width=True, hide_index=True)
    st.caption("Cada camión de efluente entra al libro de stock como **entrada a piletas**; lo que vuelve a salir "
               "con valor es el **AG recuperado** que se manda a acopio. El resto es agua a tratar: las piletas no "
               "guardan inventario, por eso este cuadro se lee como flujo del mes y no como saldo.")


# ------------------------------------------------------------------ pantalla
def render_sector_efluentes(ctx, sec):
    from .portada import _hero, _pie_soporte
    import lab_carga as lab

    USR, puede = ctx["USR"], ctx["puede_seccion"]
    ss = st.session_state
    _hero(f"SECTOR {sec['nombre_ui'].upper()}", USR, icono=sec.get("icono") or "💧",
          sub="Efluentes líquidos: camiones ingresados y sus análisis de laboratorio. Sólo este producto.")
    _indicadores(ctx)

    ss.setdefault("lab_tok", uuid.uuid4().hex[:8])
    ss["_lab_externo"] = False                       # nunca muestra externa desde acá
    if ss.pop("lab_celebrar", False):                # lab_carga._reset lo prende tras guardar
        ss["ef_edit_ctx"] = None
        _invalidar()
        st.toast("Análisis de efluente guardado", icon="✅")

    puede_lab = puede("LAB")
    modos = _MODOS if puede_lab else [_MODOS[3]]
    force = ss.pop("_ef_force_modo", None)
    if force in modos:
        ss["ef_modo"] = force
    modo = st.radio("Vista", modos, horizontal=True, key="ef_modo", label_visibility="collapsed")
    if not puede_lab:
        st.caption("Sin permiso de Laboratorio: se muestran sólo los ingresos de portería.")

    get_conn = ctx["conn_factory"]
    usuario = ""
    if puede_lab and not modo.startswith("🚛"):
        uname = str(USR.get("nombre_full") or USR.get("nombre") or USR.get("id_usuario") or "")
        usuario = st.text_input("Empleado / usuario que carga (queda registrado en la base)",
                                value=uname, key="lab_user")
    if modo.startswith("🧪"):
        _modo_analizar(ctx, lab, get_conn, usuario)
    elif modo.startswith("📋"):
        _modo_pendientes(ctx, lab, get_conn)
    elif modo.startswith("✏️"):
        _modo_editar(ctx, lab, get_conn, usuario)
    else:
        _modo_camiones(ctx)
    st.caption("Este sector muestra únicamente efluentes líquidos (DISPOSICION FINAL DE LIQUIDOS). "
               "Los demás productos se evalúan desde su sector o desde Laboratorio.")
    _pie_soporte(ctx)
    return True
