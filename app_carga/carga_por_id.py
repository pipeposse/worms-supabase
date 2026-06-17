"""Iniciar producción (operario).
El operario elige una producción PLANIFICADA por la dirección, ve TODO heredado del
Centro de Planificación (proceso, reactor, cronograma de etapas, movimientos de stock
con su ticket y origen), completa el checklist, asigna el horario de encendido de la
caldera y da inicio. Al iniciar: confirma los movimientos (PLANIFICADO -> EJECUTADO),
pone el batch en REACCION y el cronograma de evaluación interna se genera solo (trigger).

render(USR, cat, conectar) recibe los helpers de app.py (evita imports circulares).
"""
from datetime import datetime, date, time, timedelta

import streamlit as st

from planificacion import listar_planificadas, listar_movimientos_plan, confirmar_movimientos_plan

try:
    from zoneinfo import ZoneInfo
    TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:
    TZ_AR = None

CHECKS = [
    ("mp_ok", "Materias primas disponibles y verificadas"),
    ("insumos_ok", "Insumos y catalizadores disponibles"),
    ("corriente_ok", "Corriente correcta (vegetal/animal)"),
    ("temperatura_inicial_ok", "Temperatura inicial OK"),
    ("parametros_ok", "Parámetros del proceso revisados"),
    ("caldera_encendida_ok", "Caldera encendida (≥1 h antes, 80 °C)"),
]


def _ahora():
    return datetime.now(TZ_AR) if TZ_AR else datetime.now()


def _eval_interna(USR, cat, conectar, etapas_de_proceso, params_proceso):
    if etapas_de_proceso is not None and params_proceso is not None:
        st.divider()
        st.header("🧪 Evaluación interna")
        st.caption("De ahora en más las evaluaciones internas de las reacciones se cargan en esta sección.")
        import eval_interna
        eval_interna.render(USR, cat, conectar, etapas_de_proceso, params_proceso)
    st.divider()
    import decantacion
    decantacion.produccion(USR, cat, conectar)


def render(USR, cat, conectar, etapas_de_proceso=None, params_proceso=None):
    st.title("👷 Producción en planta")
    st.caption("Elegí la producción planificada por dirección. Heredás todos los datos; sólo confirmás el checklist y la caldera.")

    planificadas = listar_planificadas(cat)
    if planificadas.empty:
        st.info("No hay producciones planificadas pendientes. La dirección las crea en el Centro de Planificación.")
        _eval_interna(USR, cat, conectar, etapas_de_proceso, params_proceso)
        return

    opts = {
        f"{r.identificador_unidad} · {r.producto_final or '—'} · {r.reactor or '—'}": int(r.id_batch)
        for r in planificadas.itertuples()
    }
    sel = st.selectbox("Producción planificada", list(opts.keys()), key="cid_sel")
    id_batch = opts[sel]

    # ---- Bloqueo por carga baja (<80%): requiere aprobación del director ----
    _bloq_apr = False
    try:
        _apr = cat("SELECT estado, pct_carga, motivo FROM produccion.fact_aprobacion_carga "
                   "WHERE id_batch=%s ORDER BY id_aprobacion DESC LIMIT 1", (id_batch,))
    except Exception:
        _apr = None
    if _apr is not None and not _apr.empty:
        _ea = str(_apr.iloc[0]["estado"])
        if _ea == "PENDIENTE":
            _bloq_apr = True
            st.error(f"🛂 Esta producción se planificó con carga al {float(_apr.iloc[0]['pct_carga']):.0f}% "
                     "(menos del 80% del equipo) y está **pendiente de aprobación del director**. "
                     "No se puede iniciar hasta que la apruebe en el Centro de Planificación.")
        elif _ea == "RECHAZADO":
            _bloq_apr = True
            st.error("⛔ El director **rechazó** la carga baja de esta producción. No se puede iniciar. "
                     "La dirección debe re-planificarla.")
        else:
            st.success(f"🛂 Carga baja ({float(_apr.iloc[0]['pct_carga']):.0f}%) **aprobada por el director**.")

    # ---- detalle heredado del batch ----
    det = cat(
        "SELECT b.identificador_unidad, b.sector, b.tipo_proceso, b.calidad_buscada, "
        "       b.tiempo_estimado_horas, b.parametros_proceso, "
        "       bu.nombre_ui AS reactor, bu.capacidad_max_l, "
        "       p.nombre_producto AS producto_final "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "LEFT JOIN produccion.dim_producto p ON p.id_producto=b.id_producto_buscado "
        "WHERE b.id_batch=%s", (id_batch,))
    if det.empty:
        st.error("No se encontró la producción."); return
    d = det.iloc[0]
    params = d["parametros_proceso"] or {}
    if isinstance(params, str):
        import json as _j
        try: params = _j.loads(params)
        except Exception: params = {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ID de producción", d["identificador_unidad"])
    c2.metric("Proceso", d["tipo_proceso"] or "—")
    c3.metric("Reactor", d["reactor"] or "—")
    c4.metric("Producto final", d["producto_final"] or "—")

    # litros de MP a cargar (desde los movimientos planificados) y % de llenado del reactor
    cap_l = float(d["capacidad_max_l"] or 0)
    _mpq = cat(
        "SELECT COALESCE(SUM(litros),0) lts, COALESCE(SUM(kg),0) kg "
        "FROM produccion.fact_movimiento_stock "
        "WHERE id_batch=%s AND rol='MP' AND anulado IS NOT TRUE", (id_batch,))
    litros_mp = float(_mpq.iloc[0]["lts"]) if not _mpq.empty else 0.0
    kg_mp = float(_mpq.iloc[0]["kg"]) if not _mpq.empty else 0.0
    pct_llen = (litros_mp / cap_l * 100.0) if cap_l else 0.0

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("MP a cargar", f"{litros_mp:,.0f} L", f"{kg_mp:,.0f} kg · {kg_mp/1000:,.1f} TN")
    c6.metric("Capacidad reactor", f"{cap_l:,.0f} L")
    c7.metric("Llenado del reactor", f"{pct_llen:.0f}%")
    c8.metric("Tiempo estimado (h)", f"{float(d['tiempo_estimado_horas'] or 0):,.1f}")
    st.progress(min(1.0, max(0.0, pct_llen / 100.0)))
    cT1, cT2 = st.columns(2)
    cT1.metric("Temp. inicial (°C)", f"{float(params.get('temp_inicial_c', 0)):,.0f}")
    cT2.metric("Kg objetivo (ref.)", f"{float(params.get('kg_objetivo', 0)):,.0f} kg")

    _fnom = params.get("formula_nombre")
    if _fnom:
        _extra = ""
        if params.get("glicerina_fresca_l") is not None:
            _extra = (f" · fresca {float(params.get('glicerina_fresca_l') or 0):,.0f} L · "
                      f"recuperada {float(params.get('glicerina_recup_l') or 0):,.0f} L · "
                      f"KOH {float(params.get('koh_kg') or 0):,.0f} kg · fuel {float(params.get('fuel_l') or 0):,.0f} L")
        st.info(f"🧪 Fórmula usada: **{_fnom}**{_extra}")

    # ---- de qué tanque/ticket viene cada materia prima e insumo ----
    st.markdown("##### 📍 Origen de cada materia prima e insumo (tanque / ticket)")
    movs = listar_movimientos_plan(cat, id_batch)
    if movs.empty:
        st.warning("Esta producción no tiene movimientos de stock cargados.")
    else:
        st.dataframe(movs, use_container_width=True, hide_index=True)
        st.caption("Al iniciar, estos tickets pasan de **PLANIFICADO** a **EJECUTADO** y descuentan/ingresan stock.")

    # ---- parámetros de laboratorio de la MP e insumos (por tanque de origen) ----
    parm = cat(
        "SELECT DISTINCT t.nombre AS \"Tanque\", pr.codigo_producto AS \"Producto\", m.rol AS \"Rol\", "
        "       f.acidez_pct AS \"Acidez %%\", f.agua_pct AS \"Agua %%\", f.sedimentos_pct AS \"Sedim. %%\", "
        "       f.densidad_g_ml AS \"Densidad\", "
        "       (f.parametros_extra->>'glicerina_pct')::numeric AS \"Glicerina %%\", "
        "       (f.parametros_extra->>'glicerol_pct')::numeric AS \"Glicerol %%\" "
        "FROM produccion.fact_movimiento_stock m "
        "JOIN produccion.dim_tanque t ON t.id_tanque=m.id_tanque "
        "JOIN produccion.dim_producto pr ON pr.id_producto=t.id_producto_principal "
        "LEFT JOIN produccion.fact_param_tanque f "
        "  ON f.id_tanque=t.id_tanque AND f.id_producto=t.id_producto_principal "
        "WHERE m.id_batch=%s AND m.id_tanque IS NOT NULL AND m.anulado IS NOT TRUE "
        "ORDER BY m.rol, t.nombre", (id_batch,))
    if parm is not None and not parm.empty:
        st.markdown("##### 🧪 Parámetros de laboratorio (MP e insumos por tanque)")
        st.dataframe(parm, use_container_width=True, hide_index=True)
        st.caption("Cada tanque de origen trae sus parámetros medidos en laboratorio.")

    # ---- cronograma de etapas heredado ----
    crono = cat(
        "SELECT pe.orden AS \"#\", pe.etapa AS \"Etapa\", COALESCE(e.descripcion,'') AS \"Descripción\", "
        "       pe.duracion_target_min AS \"Duración (min)\" "
        "FROM produccion.dic_proceso_etapa pe "
        "LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=pe.etapa "
        "WHERE pe.proceso_key=%s ORDER BY pe.orden", (d["tipo_proceso"],))
    if not crono.empty:
        with st.expander("📋 Cronograma de etapas del proceso", expanded=False):
            st.dataframe(crono, use_container_width=True, hide_index=True)
            tot_h = crono["Duración (min)"].fillna(0).sum() / 60.0
            st.caption(f"Duración total estimada: **{tot_h:.1f} h**.")

    # ---- caldera (horario de encendido) ----
    st.markdown("##### 🔥 Encendido de caldera")
    ahora = _ahora()
    cc1, cc2 = st.columns(2)
    cal_f = cc1.date_input("Fecha de encendido", value=ahora.date(), key="cid_cal_f")
    cal_h = cc2.time_input("Hora de encendido", value=(ahora - timedelta(hours=1)).time(), step=60, key="cid_cal_h")
    cal_dt = datetime.combine(cal_f, cal_h)
    if TZ_AR:
        cal_dt = cal_dt.replace(tzinfo=TZ_AR)
    anticipacion_min = (ahora - cal_dt).total_seconds() / 60.0
    caldera_lista = anticipacion_min >= 60
    if not caldera_lista:
        st.warning(f"La caldera debe estar encendida ≥ 1 h antes (lleva ~60 min llegar a 80 °C). "
                   f"Anticipación actual: {anticipacion_min:.0f} min.")
    else:
        st.success(f"Caldera con {anticipacion_min/60:.1f} h de anticipación. OK.")

    # ---- checklist ----
    st.markdown("##### ✅ Checklist previo")
    estados = {}
    cols = st.columns(2)
    for i, (campo, label) in enumerate(CHECKS):
        default = caldera_lista if campo == "caldera_encendida_ok" else False
        estados[campo] = cols[i % 2].checkbox(label, value=default, key=f"cid_chk_{campo}")

    todo_ok = all(estados.values()) and caldera_lista
    if not all(estados.values()):
        st.info("Marcá todos los ítems del checklist para habilitar el inicio.")

    if st.button("🔥 Iniciar reacción", type="primary", use_container_width=True,
                 disabled=(not todo_ok) or _bloq_apr):
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id_producto, COALESCE(SUM(COALESCE(kg, litros, cantidad)),0) q "
                        "FROM fact_movimiento_stock "
                        "WHERE id_batch=%s AND rol='MP' AND anulado IS NOT TRUE "
                        "GROUP BY id_producto ORDER BY q DESC", (id_batch,))
                    mp = cur.fetchall()
                    id_prod_ini = mp[0][0] if mp else None
                    kg_ini = float(sum(float(r[1]) for r in mp)) if mp else 0.0
                    if kg_ini <= 0:
                        kg_ini = 1.0

                    n_conf = confirmar_movimientos_plan(cur, id_batch, uid)

                    cur.execute(
                        "INSERT INTO fact_batch_checklist "
                        "(id_batch, mp_ok, insumos_ok, temperatura_inicial_ok, parametros_ok, "
                        " corriente_ok, caldera_encendida_ok, id_usuario, confirmado_en) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())",
                        (id_batch, estados["mp_ok"], estados["insumos_ok"], estados["temperatura_inicial_ok"],
                         estados["parametros_ok"], estados["corriente_ok"], estados["caldera_encendida_ok"], uid))

                    cur.execute(
                        "UPDATE fact_batch_proceso "
                        "SET estado='REACCION', etapa_actual='REACCION', id_usuario_carga=%s, "
                        "    inicio_ts=now(), caldera_encendida_ts=%s, "
                        "    id_producto_inicial=%s, kg_inicial=%s, "
                        "    id_usuario_estado=%s, motivo_estado='Iniciada por operario (checklist OK)' "
                        "WHERE id_batch=%s AND estado='PLANIFICADO'",
                        (uid, cal_dt.isoformat(), id_prod_ini, kg_ini, uid, id_batch))
                    if cur.rowcount == 0:
                        raise RuntimeError("La producción ya no está en estado PLANIFICADO (¿la inició otro?).")
            try:
                cat.clear()
            except Exception:
                pass
            st.success(f"Reacción **{d['identificador_unidad']}** iniciada. "
                       f"{n_conf} movimiento(s) de stock confirmado(s) (EJECUTADO).")
            # esquema de evaluación interna recién generado por el trigger
            ev = cat("SELECT secuencia AS \"#\", to_char(programado_ts,'DD/MM HH24:MI') AS \"Hora\", "
                     "etapa AS \"Etapa\", estado AS \"Estado\" "
                     "FROM produccion.fact_eval_programada WHERE id_batch=%s ORDER BY secuencia", (id_batch,))
            if not ev.empty:
                st.markdown("##### 🧪 Esquema de evaluación interna generado")
                st.dataframe(ev, use_container_width=True, hide_index=True)
            st.balloons()
        except Exception as e:
            st.error(f"No se pudo iniciar: {e}")
    _eval_interna(USR, cat, conectar, etapas_de_proceso, params_proceso)
