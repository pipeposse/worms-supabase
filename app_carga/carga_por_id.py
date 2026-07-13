"""Producción en planta — experiencia guiada para operarios.

Una sola producción a la vez y un solo paso a la vez, según el ESTADO del batch:
  PLANIFICADO → arrancar · REACCION → medir · REPOSO → esperar/decantar · DECANTACION → purgar.
Barra de progreso, cartel grande de "qué hacer ahora", botones grandes, poco texto.
El detalle (origen, parámetros, fórmula) queda escondido en "ver más".
"""
from datetime import datetime, timedelta
import json

import streamlit as st

from planificacion import listar_movimientos_plan, confirmar_movimientos_plan

try:
    from zoneinfo import ZoneInfo
    TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:
    TZ_AR = None

CHECKS = [
    ("mp_ok", "Las materias primas están y son las correctas"),
    ("insumos_ok", "Los insumos y el catalizador están"),
    ("caldera_encendida_ok", "La caldera está prendida (1 hora antes)"),
]

PASOS = [("PLANIFICADO", "🅿️", "Arrancar"), ("REACCION", "🔥", "Reacción"),
         ("REPOSO", "🧊", "Reposo"), ("DECANTACION", "🧴", "Decantar"),
         ("FINALIZADO", "✅", "Listo")]


def _ahora():
    return datetime.now(TZ_AR) if TZ_AR else datetime.now()


def _css():
    st.markdown(
        "<style>"
        "section.main div.stButton>button{font-size:1.15rem;padding:.75rem 1rem;font-weight:800;border-radius:14px}"
        "</style>", unsafe_allow_html=True)


def _stepper(estado):
    order = [s[0] for s in PASOS]
    cur = order.index(estado) if estado in order else 0
    cells = ""
    for i, (_code, ic, lbl) in enumerate(PASOS):
        if i < cur:
            bg, col = "#16a34a", "#fff"
        elif i == cur:
            bg, col = "#2563eb", "#fff"
        else:
            bg, col = "#e5e7eb", "#9ca3af"
        lblcol = "#111827" if i <= cur else "#9ca3af"
        cells += (f"<div style='flex:1;text-align:center'>"
                  f"<div style='width:48px;height:48px;line-height:48px;margin:0 auto;border-radius:50%;"
                  f"background:{bg};color:{col};font-size:1.5rem'>{ic}</div>"
                  f"<div style='font-size:.82rem;margin-top:5px;color:{lblcol};font-weight:700'>{lbl}</div></div>")
    return f"<div style='display:flex;gap:4px;align-items:flex-start;margin:8px 0 16px'>{cells}</div>"


def _cartel(texto, color="#2563eb", bg="#eff6ff", icon="👉"):
    st.markdown(
        f"<div style='background:{bg};border-left:8px solid {color};border-radius:12px;"
        f"padding:16px 18px;margin:6px 0 14px;font-size:1.25rem;font-weight:800;color:#111827'>"
        f"{icon} {texto}</div>", unsafe_allow_html=True)


def _banner_corriente(corr):
    c = (str(corr or "")).upper()
    if c == "VEGETAL":
        st.markdown("<div style='background:#dcfce7;border:2px solid #16a34a;border-radius:12px;"
                    "padding:12px;text-align:center;font-size:1.4rem;font-weight:800;color:#166534;margin:4px 0'>"
                    "🌱 VEGETAL (aceites)</div>", unsafe_allow_html=True)
    elif c == "ANIMAL":
        st.markdown("<div style='background:#ffedd5;border:2px solid #c2410c;border-radius:12px;"
                    "padding:12px;text-align:center;font-size:1.4rem;font-weight:800;color:#7c2d12;margin:4px 0'>"
                    "🐄 ANIMAL (sebos)</div>", unsafe_allow_html=True)


def _params(b):
    p = b.get("parametros_proceso") or {}
    if isinstance(p, str):
        try: p = json.loads(p)
        except Exception: p = {}
    return p or {}


# ======================================================================= RENDER
def render(USR, cat, conectar, etapas_de_proceso=None, params_proceso=None):
    st.title("👷 Producción en planta")
    _css()

    act = cat(
        "SELECT b.id_batch, b.identificador_unidad AS ident, b.estado, b.tipo_proceso, "
        "       bu.nombre_ui AS reactor, bu.capacidad_max_l, bu.reposo_horas, "
        "       p.nombre_producto AS producto, b.corriente, b.parametros_proceso, "
        "       b.tiempo_estimado_horas, "
        "       to_char(b.creado_en AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS creado_fmt, "
        "       COALESCE(mp.mp,'—') AS mp, COALESCE(mp.mp_tn,0) AS mp_tn, "
        "       (SELECT inicio_ts FROM produccion.fact_etapa_evento e "
        "          WHERE e.id_batch=b.id_batch AND e.etapa='REPOSANDO' "
        "          ORDER BY e.inicio_ts DESC LIMIT 1) AS reposo_ini "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "LEFT JOIN produccion.dim_producto p ON p.id_producto=b.id_producto_buscado "
        "LEFT JOIN produccion.v_reaccion_mp mp ON mp.id_batch=b.id_batch "
        "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
        "  AND b.estado IN ('PLANIFICADO','REACCION','REPOSO','DECANTACION') "
        "ORDER BY array_position(ARRAY['REACCION','DECANTACION','REPOSO','PLANIFICADO'], b.estado), b.creado_en DESC")

    if act is None or act.empty:
        st.info("No hay producciones para trabajar ahora. Cuando la dirección planifique una, aparece acá.")
        return

    _emoji = {"PLANIFICADO": "🅿️", "REACCION": "🔥", "REPOSO": "🧊", "DECANTACION": "🧴"}
    _label = {"PLANIFICADO": "Para arrancar", "REACCION": "En reacción",
              "REPOSO": "Reposando", "DECANTACION": "Decantando"}
    _tp_short = {"PRODUCCION_ARE": "ARE", "DESGOMADO_ACUOSO": "DESGOMADO"}
    opts = act.apply(lambda r: f"{_emoji.get(r['estado'],'•')} {r['ident']} · "
                               f"{_tp_short.get(r['tipo_proceso'], r['tipo_proceso'] or '—')} · {r['reactor'] or '—'} · "
                               f"MP: {r['mp']} ({float(r['mp_tn'] or 0):.1f} t) · "
                               f"{_label.get(r['estado'], r['estado'])} · 🗓️ {r['creado_fmt'] or '—'}", axis=1).tolist()
    sel = st.selectbox("¿En qué producción vas a trabajar?", opts, key="pp_sel")
    b = act.iloc[opts.index(sel)]
    estado = str(b["estado"])
    id_batch = int(b["id_batch"])

    st.markdown(
        f"<div style='background:#1e293b;border-radius:14px;padding:14px 18px;margin:6px 0 10px;text-align:center'>"
        f"<div style='color:#94a3b8;font-size:.8rem;font-weight:700;letter-spacing:1px'>N° DE PRODUCCIÓN / REACCIÓN</div>"
        f"<div style='color:#fff;font-size:2.1rem;font-weight:900;letter-spacing:1px'>{b['ident']}</div></div>",
        unsafe_allow_html=True)
    _tp = str(b["tipo_proceso"] or "")
    _tp_lbl = {"PRODUCCION_ARE": "🧴 PRODUCCIÓN ARE", "DESGOMADO_ACUOSO": "🫧 DESGOMADO ACUOSO"}.get(_tp, _tp or "—")
    _tp_bg = {"PRODUCCION_ARE": "#4338ca", "DESGOMADO_ACUOSO": "#0f766e"}.get(_tp, "#334155")
    st.markdown(
        f"<div style='background:{_tp_bg};border-radius:12px;padding:9px 14px;margin:2px 0 10px;"
        f"text-align:center;color:#fff;font-weight:800;letter-spacing:1.5px;font-size:1.2rem'>{_tp_lbl}</div>",
        unsafe_allow_html=True)
    st.markdown(_stepper(estado), unsafe_allow_html=True)
    _banner_corriente(b["corriente"])
    if str(b.get("tipo_proceso") or "") == "PRODUCCION_ARE":
        try:
            from planificacion import render_checklist_limpieza
            with st.expander("🧽 Limpieza post-corte (cañerías, bomba y filtros)", expanded=False):
                render_checklist_limpieza(USR, cat, conectar, int(b["id_batch"]), b.get("tipo_proceso"))
        except Exception:
            pass
    with st.expander("✏️ Editar N° de producción / reacción"):
        _nid = st.text_input("Nuevo N°", value=str(b["ident"] or ""), key=f"pp_editid_{id_batch}")
        if st.button("💾 Guardar N°", key=f"pp_editid_go_{id_batch}"):
            _nv = (_nid or "").strip()
            if not _nv:
                st.error("El N° no puede quedar vacío.")
            else:
                try:
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("UPDATE produccion.fact_batch_proceso SET identificador_unidad=%s WHERE id_batch=%s",
                                        (_nv, id_batch))
                        audit.log("U", "fact_batch_proceso", id_batch, {"ident": _nv})
                    st.success(f"N° actualizado a {_nv}.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.error("No se pudo cambiar el N° (¿ya existe ese número?).")
                    st.exception(e)

    es_desgomado = str(b["tipo_proceso"]) == "DESGOMADO_ACUOSO"
    if estado == "PLANIFICADO":
        _paso_arrancar(USR, cat, conectar, b)
    elif estado == "REACCION":
        _paso_reaccion(USR, cat, conectar, b)
    elif estado == "REPOSO":
        if es_desgomado:
            import desgomado
            desgomado.produccion(USR, cat, conectar, id_batch=id_batch)
        else:
            _paso_reposo(USR, cat, conectar, b)
    elif estado == "DECANTACION":
        if es_desgomado:
            import desgomado
            desgomado.produccion(USR, cat, conectar, id_batch=id_batch)
        else:
            import decantacion
            decantacion.produccion(USR, cat, conectar, id_batch=id_batch)

    _detalles(cat, id_batch)


# --------------------------------------------------------------- PASO: ARRANCAR
def _paso_arrancar(USR, cat, conectar, b):
    id_batch = int(b["id_batch"])
    # bloqueo por carga baja
    try:
        _apr = cat("SELECT estado FROM produccion.fact_aprobacion_carga "
                   "WHERE id_batch=%s ORDER BY id_aprobacion DESC LIMIT 1", (id_batch,))
    except Exception:
        _apr = None
    _bloq = False
    if _apr is not None and not _apr.empty and str(_apr.iloc[0]["estado"]) in ("PENDIENTE", "RECHAZADO"):
        _bloq = True
        st.error("⛔ Esta producción está esperando que el director la apruebe. Todavía no se puede arrancar.")

    _cartel("Revisá que esté todo y apretá el botón verde para arrancar.", "#16a34a", "#dcfce7", "🔥")

    cap = float(b["capacidad_max_l"] or 0)
    _mpq = cat("SELECT COALESCE(SUM(litros),0) lts FROM produccion.fact_movimiento_stock "
               "WHERE id_batch=%s AND rol='MP' AND anulado IS NOT TRUE", (id_batch,))
    litros_mp = float(_mpq.iloc[0]["lts"]) if (_mpq is not None and not _mpq.empty) else 0.0
    p = _params(b)
    gli = float(p.get("glicerina_fresca_l") or 0) + float(p.get("glicerina_recup_l") or 0)
    llen = ((litros_mp + gli) / cap * 100) if cap else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("Materia prima", f"{litros_mp:,.0f} L")
    m2.metric("Glicerina", f"{gli:,.0f} L")
    m3.metric("Llenado del reactor", f"{llen:.0f}%")

    st.markdown("##### 🔥 Caldera")
    ahora = _ahora()
    cc1, cc2 = st.columns(2)
    cal_f = cc1.date_input("Día que prendiste la caldera", value=ahora.date(), key="pp_cal_f")
    cal_h = cc2.time_input("Hora que la prendiste", value=(ahora - timedelta(hours=1)).time(), step=60, key="pp_cal_h")
    cal_dt = datetime.combine(cal_f, cal_h)
    if TZ_AR:
        cal_dt = cal_dt.replace(tzinfo=TZ_AR)
    lista = (ahora - cal_dt).total_seconds() / 60.0 >= 60
    if lista:
        st.success("✅ La caldera tiene tiempo suficiente.")
    else:
        st.warning("⏳ La caldera tiene que estar prendida al menos 1 hora antes.")

    st.markdown("##### ✅ Antes de arrancar, confirmá:")
    estados = {}
    for campo, label in CHECKS:
        dv = lista if campo == "caldera_encendida_ok" else False
        estados[campo] = st.checkbox(label, value=dv, key=f"pp_chk_{campo}")
    todo = all(estados.values()) and lista

    if st.button("🔥  ARRANCAR LA REACCIÓN", type="primary", use_container_width=True,
                 disabled=(not todo) or _bloq, key="pp_arrancar"):
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("SELECT id_producto, COALESCE(SUM(COALESCE(kg,litros,cantidad)),0) q "
                                "FROM fact_movimiento_stock WHERE id_batch=%s AND rol='MP' AND anulado IS NOT TRUE "
                                "GROUP BY id_producto ORDER BY q DESC", (id_batch,))
                    mp = cur.fetchall()
                    id_prod_ini = mp[0][0] if mp else None
                    kg_ini = float(sum(float(r[1]) for r in mp)) if mp else 1.0
                    if kg_ini <= 0:
                        kg_ini = 1.0
                    n_conf = confirmar_movimientos_plan(cur, id_batch, uid)
                    cur.execute(
                        "INSERT INTO fact_batch_checklist "
                        "(id_batch, mp_ok, insumos_ok, caldera_encendida_ok, id_usuario, confirmado_en) "
                        "VALUES (%s,%s,%s,%s,%s, now())",
                        (id_batch, estados["mp_ok"], estados["insumos_ok"], estados["caldera_encendida_ok"], uid))
                    cur.execute(
                        "UPDATE fact_batch_proceso SET estado='REACCION', etapa_actual='REACCION', "
                        "id_usuario_carga=%s, inicio_ts=now(), caldera_encendida_ts=%s, "
                        "id_producto_inicial=%s, kg_inicial=%s, id_usuario_estado=%s, "
                        "motivo_estado='Arrancada por operario' WHERE id_batch=%s AND estado='PLANIFICADO'",
                        (uid, cal_dt.isoformat(), id_prod_ini, kg_ini, uid, id_batch))
                    if cur.rowcount == 0:
                        raise RuntimeError("La producción ya fue arrancada por otra persona.")
            try: cat.clear()
            except Exception: pass
            st.success("¡Reacción arrancada! Ahora te toca ir midiendo.")
            st.balloons()
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo arrancar: {e}")


# --------------------------------------------------------------- PASO: REACCIÓN
def _paso_reaccion(USR, cat, conectar, b):
    id_batch = int(b["id_batch"])
    es_are = str(b["tipo_proceso"]) == "PRODUCCION_ARE"
    if es_are:
        _cartel("Cada tanto medí ACIDEZ y TEMPERATURA. Cuando la acidez baje a 13 o menos, la reacción pasa sola a reposo.",
                "#dc2626", "#fee2e2", "🔥")
    else:
        _cartel("Cada tanto medí la TEMPERATURA. Cuando llegue a 85°C o más, la reacción corta y pasa a reposo.",
                "#dc2626", "#fee2e2", "🔥")

    # próxima medición programada
    try:
        prog = cat("SELECT secuencia, to_char(programado_ts,'HH24:MI') hora FROM produccion.fact_eval_programada "
                   "WHERE id_batch=%s AND id_eval IS NULL AND estado<>'REALIZADA' ORDER BY secuencia LIMIT 1", (id_batch,))
    except Exception:
        prog = None
    id_prog = None
    if prog is not None and not prog.empty:
        st.info(f"⏰ Próxima medición: a las **{prog.iloc[0]['hora']}**")

    c1, c2 = st.columns(2)
    ac = c1.number_input("ACIDEZ (%)", 0.0, 200.0, value=0.0, step=0.1, key="pp_ac")
    tp = c2.number_input("TEMPERATURA (°C)", 0.0, 300.0, value=0.0, step=1.0, key="pp_tp")
    obs = st.text_input("Nota (opcional)", key="pp_obs")

    if st.button("✅  GUARDAR MEDICIÓN", type="primary", use_container_width=True, key="pp_med"):
        med = {}
        if ac > 0: med["acidez"] = float(ac)
        if tp > 0: med["temperatura"] = float(tp)
        if not med:
            st.error("Cargá al menos la acidez o la temperatura.")
        else:
            uid = int(USR["id_usuario"])
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO fact_evaluacion_interna "
                                    "(id_batch, etapa, mediciones, observaciones, id_usuario) "
                                    "VALUES (%s,'REACCION',%s::jsonb,%s,%s) RETURNING id_eval",
                                    (id_batch, json.dumps(med), (obs or None), uid))
                        _idm = cur.fetchone()[0]
                        cur.execute("UPDATE produccion.fact_eval_programada SET estado='REALIZADA', id_eval=%s "
                                    "WHERE id_prog = (SELECT id_prog FROM produccion.fact_eval_programada "
                                    "  WHERE id_batch=%s AND id_eval IS NULL AND estado<>'REALIZADA' "
                                    "  ORDER BY secuencia LIMIT 1)", (int(_idm), id_batch))
                    audit.log("I", "fact_evaluacion_interna", int(_idm), med)
                try: cat.clear()
                except Exception: pass
                st.success("¡Medición guardada!")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")

    _ev = cat("SELECT to_char(ts,'DD/MM HH24:MI') AS \"Hora\", (mediciones->>'acidez')::numeric AS \"Acidez\", "
              "(mediciones->>'temperatura')::numeric AS \"Temp\" "
              "FROM produccion.fact_evaluacion_interna WHERE id_batch=%s AND NOT anulado ORDER BY ts DESC LIMIT 6", (id_batch,))
    if _ev is not None and not _ev.empty:
        st.caption("Últimas mediciones:")
        st.dataframe(_ev, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------- PASO: REPOSO
def _paso_reposo(USR, cat, conectar, b):
    id_batch = int(b["id_batch"])
    import pandas as pd
    eta = None
    if b["reposo_ini"] is not None and not pd.isna(b["reposo_ini"]) and b["reposo_horas"] is not None:
        try:
            eta = pd.to_datetime(b["reposo_ini"]) + pd.Timedelta(hours=float(b["reposo_horas"]))
        except Exception:
            eta = None
    listo = True
    if eta is not None:
        _now = pd.Timestamp.now(tz=getattr(eta, "tz", None))
        rest = (eta - _now).total_seconds() / 60.0
        listo = rest <= 0
        if listo:
            _cartel("El reposo terminó. Ya podés empezar la decantación.", "#16a34a", "#dcfce7", "🧊")
        else:
            _h = int(rest // 60); _m = int(rest % 60)
            _cartel(f"Está reposando. Falta {_h} h {_m} min (termina {eta.strftime('%H:%M')}).", "#2563eb", "#eff6ff", "🧊")
    else:
        _cartel("Está reposando. Cuando esté listo, empezá la decantación.", "#2563eb", "#eff6ff", "🧊")

    if st.button("🧴  EMPEZAR LA DECANTACIÓN", type="primary", use_container_width=True, key="pp_decant"):
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_etapa_evento SET fin_ts=now() WHERE id_batch=%s AND fin_ts IS NULL",
                                (id_batch,))
                    cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch,etapa,inicio_ts,id_usuario) "
                                "VALUES (%s,'DECANTACION',now(),%s)", (id_batch, uid))
                    cur.execute("UPDATE produccion.fact_batch_proceso SET estado='DECANTACION', etapa_actual='DECANTACION', "
                                "id_usuario_estado=%s, motivo_estado='Inicio de decantación (operario)' WHERE id_batch=%s",
                                (uid, id_batch))
                audit.log("U", "fact_batch_proceso", id_batch, {"estado": "DECANTACION"})
            try: cat.clear()
            except Exception: pass
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo: {e}")


# ----------------------------------------------------------------- DETALLES
def _detalles(cat, id_batch):
    with st.expander("📋 Ver detalles (origen de materiales, parámetros)"):
        movs = listar_movimientos_plan(cat, id_batch)
        if movs is not None and not movs.empty:
            st.caption("De dónde sale cada material:")
            st.dataframe(movs, use_container_width=True, hide_index=True)
        parm = cat(
            "SELECT DISTINCT t.nombre AS \"Tanque\", pr.codigo_producto AS \"Producto\", m.rol AS \"Rol\", "
            "       f.acidez_pct AS \"Acidez %%\", f.agua_pct AS \"Agua %%\", f.densidad_g_ml AS \"Densidad\" "
            "FROM produccion.fact_movimiento_stock m "
            "JOIN produccion.dim_tanque t ON t.id_tanque=m.id_tanque "
            "JOIN produccion.dim_producto pr ON pr.id_producto=t.id_producto_principal "
            "LEFT JOIN produccion.fact_param_tanque f ON f.id_tanque=t.id_tanque AND f.id_producto=t.id_producto_principal "
            "WHERE m.id_batch=%s AND m.id_tanque IS NOT NULL AND m.anulado IS NOT TRUE ORDER BY m.rol, t.nombre", (id_batch,))
        if parm is not None and not parm.empty:
            st.caption("Parámetros de laboratorio de cada tanque:")
            st.dataframe(parm, use_container_width=True, hide_index=True)
