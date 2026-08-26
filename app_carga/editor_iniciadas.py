# -*- coding: utf-8 -*-
"""Edición rápida de reacciones INICIADAS (Centro de Planificación).

Lo que dirección corrige a mano de una reacción EN CURSO (aún no finalizada),
en un solo lugar y sin frenar el proceso:
  1. Volumen inicial: TN de materia prima cargada, litros iniciales y objetivo —
     a mano y fácil, aunque la reacción ya esté andando.
  2. Materias primas: los kg de cada origen (tanque o tickets), anular líneas,
     agregar una que faltó, y sincronizar el total con el volumen inicial.
  3. Insumos: fuel, potasio, glicerinas, agua, temperatura… (parametros_proceso).
  4. Tiempos por etapa: inicio/fin reales; la duración se recalcula sola.

IMPORTANTE: esto es CORRECCIÓN DE DATOS. Cambiar kg acá NO mueve stock de
tanques ni genera movimientos: si la carga física fue otra, el stock se ajusta
por su propio circuito. Todo pasa por `conectar` (auditado) y las grillas se
rearman con nonce después de cada guardado."""

import json

import pandas as pd
import streamlit as st

from editor_reacciones import _a_local, _a_utc_iso

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")

# Estados que cuentan como "iniciada": todo lo que no terminó ni se anuló.
_ESTADOS_FIN = ("FINALIZADO",)

# Insumos/parámetros numéricos editables de parametros_proceso (clave -> etiqueta).
# Sólo se guardan los que cambian; vacío = sin dato (no se escribe).
_INS_NUM = [
    ("fuel_l", "Fuel oil (L)"),
    ("koh_kg", "Potasio KOH (kg)"),
    ("glicerina_fresca_l", "Glicerina fresca (L)"),
    ("glicerina_recup_l", "Glicerina recuperada (L)"),
    ("glicerol_pct", "Glicerol (%)"),
    ("agua_agc_pct", "Agua AGC (%)"),
    ("pct_goma", "% goma"),
    ("acidez_pct", "Acidez MP (%)"),
    ("temp_inicial_c", "Temp. inicial (°C)"),
    ("are_objetivo_kg", "ARE objetivo (kg)"),
    ("afe_objetivo_kg", "AFE objetivo (kg)"),
]


def _f(v):
    """numérico o None (tolerante a '', NaN, texto)."""
    try:
        if v is None or (isinstance(v, str) and not v.strip()) or pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#7c2d12,#b45309);border-radius:14px;"
        "padding:14px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.3rem;font-weight:900'>⏱️ Edición rápida de iniciadas</div>"
        "<div style='color:#ffedd5;font-size:.86rem;margin-top:3px'>Reacciones EN CURSO: volumen "
        "inicial, TN de materia prima, insumos y tiempos — corrección de datos con auditoría, "
        "sin frenar el proceso.</div></div>",
        unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return
    ss = st.session_state
    uid = int(USR.get("id_usuario") or 0)

    bs = cat("SELECT id_batch, identificador_unidad, fecha::text AS fecha, tipo_proceso, "
             "estado, etapa_actual, kg_inicial, litros_inicial, catalizador_tipo, "
             "tiempo_estimado_horas, parametros_proceso, observaciones "
             "FROM produccion.fact_batch_proceso "
             "WHERE NOT COALESCE(anulado, false) AND COALESCE(estado,'') NOT IN %s "
             "ORDER BY fecha DESC, id_batch DESC", (_ESTADOS_FIN,))
    if bs is None or bs.empty:
        st.info("No hay reacciones iniciadas (sin finalizar) para editar. Las terminadas se "
                "corrigen en **✏️ Edición rápida**.")
        return

    _lbl = {int(r["id_batch"]): "#%d · %s · %s · %s · %s%s" % (
        int(r["id_batch"]), str(r["identificador_unidad"] or "s/nombre"),
        str(r["fecha"]), str(r["tipo_proceso"] or "—"), str(r["estado"] or "—"),
        (" (%s)" % r["etapa_actual"]) if r["etapa_actual"] else "")
        for _, r in bs.iterrows()}
    sel = st.selectbox("Reacción iniciada", bs["id_batch"].astype(int).tolist(),
                       format_func=lambda i: _lbl.get(int(i), str(i)), key="edi_sel")
    b = bs[bs["id_batch"].astype(int) == int(sel)].iloc[0]
    idb = int(b["id_batch"])
    _nz = int(ss.get("edi_nonce_%d" % idb) or 0)
    _pp = b["parametros_proceso"]
    if isinstance(_pp, str):
        try:
            _pp = json.loads(_pp)
        except Exception:
            _pp = {}
    _pp = _pp if isinstance(_pp, dict) else {}

    st.caption("⚠️ **Corrección de datos, no de stock:** cambiar kg o litros acá NO mueve stock "
               "de tanques ni genera movimientos. Si la carga física fue distinta, el stock del "
               "tanque se ajusta por su circuito (medición / ajuste manual).")

    # ================= 1 · volumen inicial =================
    st.markdown("##### 1 · Volumen inicial (a mano)")
    c1, c2, c3, c4 = st.columns(4)
    _tn0 = (float(b["kg_inicial"]) / 1000.0) if pd.notna(b["kg_inicial"]) else None
    _tn = c1.number_input("TN de materia prima", min_value=0.0, max_value=1000.0,
                          value=_tn0, step=0.1, format="%.2f",
                          key="edi_tn_%d_%d" % (idb, _nz),
                          help="Lo que entró al reactor, en toneladas. Se guarda en kg "
                               "(TN × 1.000). Vacío = sin dato.")
    _lt0 = float(b["litros_inicial"]) if pd.notna(b["litros_inicial"]) else None
    _lt = c2.number_input("Litros iniciales", min_value=0.0, max_value=1000000.0,
                          value=_lt0, step=100.0, format="%.0f",
                          key="edi_lt_%d_%d" % (idb, _nz),
                          help="Volumen inicial en litros (si se maneja por volumen). "
                               "Vacío = sin dato.")
    _ko0 = _f(_pp.get("kg_objetivo"))
    _ko = c3.number_input("Kg objetivo", min_value=0.0, max_value=1000000.0,
                          value=_ko0, step=100.0, format="%.0f",
                          key="edi_ko_%d_%d" % (idb, _nz),
                          help="El objetivo de carga que se planificó.")
    _th0 = float(b["tiempo_estimado_horas"]) if pd.notna(b["tiempo_estimado_horas"]) else None
    _th = c4.number_input("Tiempo estimado (h)", min_value=0.0, max_value=200.0,
                          value=_th0, step=0.5, format="%.1f",
                          key="edi_th_%d_%d" % (idb, _nz))
    if st.button("💾 Guardar volumen inicial", type="primary", key="edi_save_vol_%d" % idb):
        try:
            _kg = round(float(_tn) * 1000.0, 1) if _tn is not None else None
            _mrg = {}
            if _ko is not None and _f(_ko) != _ko0:
                _mrg["kg_objetivo"] = _ko
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE produccion.fact_batch_proceso SET kg_inicial=%s, "
                        "litros_inicial=%s, tiempo_estimado_horas=%s, "
                        "parametros_proceso = COALESCE(parametros_proceso,'{}'::jsonb) || %s::jsonb "
                        "WHERE id_batch=%s",
                        (_kg, _lt, _th, json.dumps(_mrg), idb))
                audit.log("U", "fact_batch_proceso", idb,
                          {"editor_iniciadas": "volumen", "kg_inicial": _kg,
                           "litros_inicial": _lt, "kg_objetivo": _mrg.get("kg_objetivo"),
                           "tiempo_estimado_horas": _th})
            cat.clear()
            ss["edi_nonce_%d" % idb] = _nz + 1
            st.success("✅ Volumen inicial guardado.")
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)

    # ================= 2 · materias primas =================
    st.markdown("##### 2 · Materias primas (kg por origen)")
    mp = cat("SELECT i.id_batch_insumo, i.cantidad, i.unidad, i.fuente, i.ticket_porteria, "
             "i.id_tanque, i.anulado, t.nombre AS tanque "
             "FROM produccion.fact_batch_insumo i "
             "LEFT JOIN produccion.dim_tanque t ON t.id_tanque = i.id_tanque "
             "WHERE i.id_batch=%s AND i.rol='MP' ORDER BY i.id_batch_insumo", (idb,))
    if mp is None or mp.empty:
        st.info("Esta reacción no tiene líneas de materia prima registradas. "
                "Podés agregarlas abajo.")
        mp = pd.DataFrame(columns=["id_batch_insumo", "cantidad", "unidad", "fuente",
                                   "ticket_porteria", "id_tanque", "anulado", "tanque"])
    _org = ["🛢️ %s" % r["tanque"] if str(r["fuente"]) == "TANQUE" and pd.notna(r["tanque"])
            else ("🎫 Ticket(s) %s" % (r["ticket_porteria"] or "—")
                  if str(r["fuente"]) == "TICKET" else str(r["fuente"] or "—"))
            for _, r in mp.iterrows()]
    _shm = pd.DataFrame({
        "Origen": _org,
        "Kg": pd.to_numeric(mp["cantidad"], errors="coerce"),
        "Anulada": mp["anulado"].fillna(False).astype(bool),
    })
    _km = "edi_mp_%d_%d" % (idb, _nz)
    edm = st.data_editor(
        _shm, hide_index=True, use_container_width=True, key=_km,
        disabled=["Origen"], num_rows="fixed",
        column_config={
            "Kg": st.column_config.NumberColumn(format="%.0f", min_value=0.0,
                                                help="Kg reales de este origen."),
            "Anulada": st.column_config.CheckboxColumn(
                help="Tildá para anular la línea (no se borra: queda auditada)."),
        }) if not _shm.empty else _shm
    _tot_mp = float(pd.to_numeric(edm["Kg"], errors="coerce").fillna(0)[~edm["Anulada"]].sum()) \
        if not _shm.empty else 0.0
    _sync = st.checkbox("Al guardar, poner la TN inicial = suma de MP activas (%s kg = %.2f TN)"
                        % ("{:,.0f}".format(_tot_mp), _tot_mp / 1000.0),
                        value=True, key="edi_sync_%d_%d" % (idb, _nz))
    if not _shm.empty and st.button("💾 Guardar materias primas", type="primary",
                                    key="edi_save_mp_%d" % idb):
        try:
            _nreg = 0
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    for _i in range(len(mp)):
                        _idi = int(mp["id_batch_insumo"].iloc[_i])
                        _k0 = _f(_shm["Kg"].iloc[_i]) or 0.0
                        _k1 = _f(edm["Kg"].iloc[_i]) or 0.0
                        _a0 = bool(_shm["Anulada"].iloc[_i])
                        _a1 = bool(edm["Anulada"].iloc[_i])
                        if abs(_k0 - _k1) < 0.5 and _a0 == _a1:
                            continue
                        cur.execute("UPDATE produccion.fact_batch_insumo "
                                    "SET cantidad=%s, anulado=%s WHERE id_batch_insumo=%s",
                                    (round(_k1, 1), _a1, _idi))
                        _nreg += 1
                    if _sync:
                        cur.execute("UPDATE produccion.fact_batch_proceso SET kg_inicial=%s "
                                    "WHERE id_batch=%s", (round(_tot_mp, 1), idb))
                audit.log("U", "fact_batch_insumo", idb,
                          {"editor_iniciadas": "mp", "lineas_cambiadas": _nreg,
                           "kg_inicial_sync": (round(_tot_mp, 1) if _sync else None)})
            cat.clear()
            ss["edi_nonce_%d" % idb] = _nz + 1
            st.success("✅ Materias primas guardadas (%d línea(s))." % _nreg)
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)

    with st.expander("➕ Agregar una línea de materia prima que faltó", expanded=False):
        a1, a2, a3, a4 = st.columns([1.0, 1.6, 1.0, 0.9])
        _fu = a1.radio("Origen", ["🛢️ Tanque", "🎫 Ticket"], key="edi_add_fu_%d" % idb)
        _tks = cat("SELECT id_tanque, nombre FROM produccion.dim_tanque "
                   "WHERE activo ORDER BY nombre")
        _idt, _tkt = None, None
        if _fu.startswith("🛢️"):
            _opt = _tks["id_tanque"].astype(int).tolist() if _tks is not None and not _tks.empty else []
            _nmb = dict(zip(_tks["id_tanque"].astype(int), _tks["nombre"])) if _opt else {}
            _idt = a2.selectbox("Tanque", _opt, format_func=lambda i: _nmb.get(int(i), str(i)),
                                key="edi_add_tk_%d" % idb) if _opt else None
        else:
            _tkt = a2.text_input("Ticket(s) de portería", key="edi_add_tkt_%d" % idb,
                                 help="Uno o varios, separados por coma (ej: 6268, 6269).")
        _kga = a3.number_input("Kg", min_value=0.0, max_value=1000000.0, step=100.0,
                               format="%.0f", key="edi_add_kg_%d" % idb)
        a4.write("")
        if a4.button("Agregar", key="edi_add_go_%d" % idb, use_container_width=True):
            if _kga <= 0 or (_fu.startswith("🛢️") and _idt is None) or \
                    (_fu.startswith("🎫") and not (_tkt or "").strip()):
                st.warning("Completá el origen y los kg.")
            else:
                try:
                    with conectar(uid) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO produccion.fact_batch_insumo "
                                "(id_batch, rol, cantidad, unidad, fuente, ticket_porteria, "
                                " id_tanque, id_usuario, anulado) "
                                "VALUES (%s,'MP',%s,'KG',%s,%s,%s,%s,false) "
                                "RETURNING id_batch_insumo",
                                (idb, round(float(_kga), 1),
                                 ("TANQUE" if _fu.startswith("🛢️") else "TICKET"),
                                 ((_tkt or "").strip() or None),
                                 (int(_idt) if _fu.startswith("🛢️") else None), uid))
                            _new = cur.fetchone()[0]
                        audit.log("I", "fact_batch_insumo", int(_new),
                                  {"editor_iniciadas": "mp_alta", "id_batch": idb,
                                   "kg": float(_kga)})
                    cat.clear()
                    ss["edi_nonce_%d" % idb] = _nz + 1
                    st.success("✅ Línea agregada.")
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo agregar: %s" % e)

    # ================= 3 · insumos =================
    st.markdown("##### 3 · Insumos y parámetros del proceso")
    _rows = [{"_k": k, "Insumo / parámetro": lbl, "Valor": _f(_pp.get(k))}
             for k, lbl in _INS_NUM]
    _shi = pd.DataFrame(_rows)
    _ki = "edi_ins_%d_%d" % (idb, _nz)
    edi = st.data_editor(
        _shi.drop(columns=["_k"]), hide_index=True, use_container_width=True, key=_ki,
        disabled=["Insumo / parámetro"], num_rows="fixed",
        column_config={"Valor": st.column_config.NumberColumn(
            format="%.2f", help="Vacío = sin dato (no se escribe).")})
    _est = _pp.get("insumos_estimados") if isinstance(_pp.get("insumos_estimados"), dict) else {}
    _she = pd.DataFrame({"Insumo": list(_est.keys()),
                         "Cantidad": [_f(v) for v in _est.values()]}) \
        if _est else pd.DataFrame({"Insumo": pd.Series(dtype="object"),
                                   "Cantidad": pd.Series(dtype="float64")})
    st.caption("**Insumos estimados** (los del armado — editá cantidades o agregá filas):")
    _ke = "edi_est_%d_%d" % (idb, _nz)
    ede = st.data_editor(_she, hide_index=True, use_container_width=True, key=_ke,
                         num_rows="dynamic",
                         column_config={"Cantidad": st.column_config.NumberColumn(format="%.1f")})
    _cat0 = str(b["catalizador_tipo"] or _pp.get("catalizador") or "")
    _cat = st.text_input("Catalizador", value=_cat0, key="edi_cat_%d_%d" % (idb, _nz),
                         help="POTASIO / SODA… Se guarda en la reacción y en los parámetros.")
    if st.button("💾 Guardar insumos", type="primary", key="edi_save_ins_%d" % idb):
        try:
            _mrg = {}
            for _i in range(len(_shi)):
                _v0, _v1 = _f(_shi["Valor"].iloc[_i]), _f(edi["Valor"].iloc[_i])
                if _v0 != _v1:
                    _mrg[str(_shi["_k"].iloc[_i])] = _v1
            _nue = {}
            for _i in range(len(ede)):
                _nm = str(ede["Insumo"].iloc[_i] or "").strip().upper()
                if _nm:
                    _nue[_nm] = _f(ede["Cantidad"].iloc[_i])
            if _nue != _est:
                _mrg["insumos_estimados"] = _nue
            if (_cat or "").strip() != _cat0:
                _mrg["catalizador"] = (_cat or "").strip() or None
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE produccion.fact_batch_proceso SET catalizador_tipo=%s, "
                        "parametros_proceso = COALESCE(parametros_proceso,'{}'::jsonb) || %s::jsonb "
                        "WHERE id_batch=%s",
                        (((_cat or "").strip() or None), json.dumps(_mrg), idb))
                audit.log("U", "fact_batch_proceso", idb,
                          {"editor_iniciadas": "insumos", "cambios": _mrg})
            cat.clear()
            ss["edi_nonce_%d" % idb] = _nz + 1
            st.success("✅ Insumos guardados (%d cambio(s))." % len(_mrg))
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)

    # ================= 4 · tiempos por etapa =================
    st.markdown("##### 4 · Tiempos por etapa")
    ev = cat("SELECT id_evento_etapa, etapa, inicio_ts, fin_ts, duracion_real_min, "
             "horas_hombre FROM produccion.fact_etapa_evento WHERE id_batch=%s "
             "ORDER BY inicio_ts NULLS LAST, id_evento_etapa", (idb,))
    if ev is None or ev.empty:
        st.info("Esta reacción todavía no tiene etapas registradas (aparecen a medida "
                "que el proceso avanza).")
        return
    ev = ev.copy()
    _sh = pd.DataFrame({
        "Etapa": ev["etapa"].astype(str),
        "Inicio": _a_local(ev["inicio_ts"]),
        "Fin": _a_local(ev["fin_ts"]),
        "Duración (h)": (pd.to_numeric(ev["duracion_real_min"], errors="coerce") / 60.0).round(2),
        "Horas hombre": pd.to_numeric(ev["horas_hombre"], errors="coerce"),
    })
    _k = "edi_et_%d_%d" % (idb, _nz)
    ed = st.data_editor(
        _sh, hide_index=True, use_container_width=True, key=_k,
        disabled=["Etapa", "Duración (h)"],
        column_config={
            "Inicio": st.column_config.DatetimeColumn("Inicio", format="DD/MM/YYYY HH:mm"),
            "Fin": st.column_config.DatetimeColumn("Fin", format="DD/MM/YYYY HH:mm"),
            "Duración (h)": st.column_config.NumberColumn(
                format="%.2f", help="Se recalcula sola al guardar (fin − inicio)."),
            "Horas hombre": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
        })
    st.caption("Editá **Inicio** y **Fin** (hora argentina); la duración se recalcula al "
               "guardar. Un fin anterior al inicio no se guarda. La etapa EN CURSO puede "
               "quedar con Fin vacío.")
    if st.button("💾 Guardar tiempos", type="primary", key="edi_save_et_%d" % idb):
        _err, _nok = [], 0
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    for _i in range(len(ev)):
                        _ide = int(ev["id_evento_etapa"].iloc[_i])
                        _i0, _f0 = _sh["Inicio"].iloc[_i], _sh["Fin"].iloc[_i]
                        _i1, _f1 = ed["Inicio"].iloc[_i], ed["Fin"].iloc[_i]
                        _h0, _h1 = _sh["Horas hombre"].iloc[_i], ed["Horas hombre"].iloc[_i]
                        _chg = (str(_i0) != str(_i1) or str(_f0) != str(_f1)
                                or str(_h0) != str(_h1))
                        if not _chg:
                            continue
                        if pd.notna(_i1) and pd.notna(_f1) and _f1 < _i1:
                            _err.append("%s: el fin es anterior al inicio" %
                                        str(_sh["Etapa"].iloc[_i]))
                            continue
                        _dur = (round((_f1 - _i1).total_seconds() / 60.0, 1)
                                if (pd.notna(_i1) and pd.notna(_f1)) else None)
                        cur.execute(
                            "UPDATE produccion.fact_etapa_evento SET inicio_ts=%s, "
                            "fin_ts=%s, duracion_real_min=%s, horas_hombre=%s "
                            "WHERE id_evento_etapa=%s",
                            (_a_utc_iso(_i1), _a_utc_iso(_f1), _dur, _f(_h1), _ide))
                        audit.log("U", "fact_etapa_evento", _ide,
                                  {"editor_iniciadas": True, "id_batch": idb,
                                   "etapa": str(_sh["Etapa"].iloc[_i]),
                                   "inicio": _a_utc_iso(_i1), "fin": _a_utc_iso(_f1),
                                   "duracion_min": _dur})
                        _nok += 1
            if _err:
                st.error(" · ".join(_err))
            if _nok:
                st.success("✅ %d etapa(s) actualizadas." % _nok)
                cat.clear()
                ss["edi_nonce_%d" % idb] = _nz + 1
                st.rerun()
            if not _nok and not _err:
                st.info("No hay cambios para guardar.")
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)
