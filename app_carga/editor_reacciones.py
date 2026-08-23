# -*- coding: utf-8 -*-
"""Edición rápida de reacciones (Centro de Planificación).

Todo lo que dirección corrige a mano de una reacción ya cargada, en un solo
lugar y sin vueltas:
  1. Nombre (identificador), TN obtenidas manuales, ticket final y observaciones.
  2. Tiempos por etapa (inicio/fin): la duración se recalcula sola.
  3. Tickets finales asociados: editar kg/calidad, agregar filas, anular.

Todo pasa por `conectar` (auditado) y la grilla se rearma con nonce después de
cada guardado (regla de la casa para no arrastrar estado viejo)."""

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
_TZ = "America/Argentina/Buenos_Aires"


def _n(v, dec=0):
    try:
        if v is None or pd.isna(v):
            return "—"
        return ("{:,.%df}" % dec).format(float(v))
    except Exception:
        return "—"


def _a_local(serie):
    """timestamptz -> hora local AR sin tz (editable en la grilla)."""
    s = pd.to_datetime(serie, errors="coerce", utc=True)
    try:
        return s.dt.tz_convert(_TZ).dt.tz_localize(None)
    except Exception:
        return s


def _a_utc_iso(v):
    """valor editado (naive, hora AR) -> ISO con tz para guardar. None si vacío."""
    t = pd.to_datetime(v, errors="coerce")
    if pd.isna(t):
        return None
    try:
        return t.tz_localize(_TZ).isoformat()
    except Exception:
        return t.isoformat()


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#1e3a8a,#0e7490);border-radius:14px;"
        "padding:14px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.3rem;font-weight:900'>✏️ Edición rápida de reacciones</div>"
        "<div style='color:#cffafe;font-size:.86rem;margin-top:3px'>Nombre, tiempos por etapa, "
        "tickets finales y TN manuales — todo editable acá, con auditoría.</div></div>",
        unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return
    ss = st.session_state
    uid = int(USR.get("id_usuario") or 0)

    f1, f2 = st.columns([1, 2.4])
    _dias = int(f1.selectbox("Días hacia atrás", [15, 30, 60, 90, 180, 365], index=1,
                             key="edr_dias"))
    _q = f2.text_input("🔎 Buscar (nombre, ticket, tipo)", key="edr_q")
    bs = cat("SELECT id_batch, identificador_unidad, fecha::text AS fecha, tipo_proceso, "
             "estado, etapa_actual, kg_obtenido, ticket_producto_final, "
             "ticket_validacion_lab, observaciones, anulado "
             "FROM produccion.fact_batch_proceso "
             "WHERE fecha >= current_date - %s AND NOT COALESCE(anulado, false) "
             "ORDER BY fecha DESC, id_batch DESC", (_dias,))
    if bs is None or bs.empty:
        st.info("No hay reacciones en la ventana elegida.")
        return
    if (_q or "").strip():
        _t = _q.strip().lower()
        _m = pd.Series(False, index=bs.index)
        for _c in ("identificador_unidad", "tipo_proceso", "ticket_producto_final",
                   "ticket_validacion_lab", "estado"):
            _m = _m | bs[_c].astype(str).str.lower().str.contains(_t, na=False)
        bs = bs[_m]
        if bs.empty:
            st.info("Ninguna reacción coincide con la búsqueda.")
            return

    _lbl = {int(r["id_batch"]): "#%d · %s · %s · %s · %s" % (
        int(r["id_batch"]), str(r["identificador_unidad"] or "s/nombre"),
        str(r["fecha"]), str(r["tipo_proceso"] or "—"), str(r["estado"] or "—"))
        for _, r in bs.iterrows()}
    sel = st.selectbox("Reacción", bs["id_batch"].astype(int).tolist(),
                       format_func=lambda i: _lbl.get(int(i), str(i)), key="edr_sel")
    b = bs[bs["id_batch"].astype(int) == int(sel)].iloc[0]
    idb = int(b["id_batch"])
    _nz = int(ss.get("edr_nonce_%d" % idb) or 0)   # rearma las grillas tras guardar

    # ================= 1 · datos de la reacción =================
    st.markdown("##### 1 · Datos de la reacción")
    c1, c2, c3 = st.columns([1.6, 0.9, 1.1])
    _nom = c1.text_input("Nombre (identificador)", value=str(b["identificador_unidad"] or ""),
                         key="edr_nom_%d_%d" % (idb, _nz),
                         help="OJO: el nombre se usa para cruzar con laboratorio "
                              "(esperando validación). Cambialo sólo si está mal cargado.")
    _tn0 = (float(b["kg_obtenido"]) / 1000.0) if pd.notna(b["kg_obtenido"]) else None
    _tn = c2.number_input("TN obtenidas (manual)", min_value=0.0, max_value=1000.0,
                          value=_tn0, step=0.5, format="%.2f",
                          key="edr_tn_%d_%d" % (idb, _nz),
                          help="Se guarda en kg (TN × 1.000). Vacío = sin dato.")
    _tkf = c3.text_input("Ticket de pesada final", value=str(b["ticket_producto_final"] or ""),
                         key="edr_tkf_%d_%d" % (idb, _nz),
                         help="El ticket de portería del producto final (en desgomado además "
                              "es la evaluación de la reacción).")
    _obs = st.text_input("Observaciones", value=str(b["observaciones"] or ""),
                         key="edr_obs_%d_%d" % (idb, _nz))
    if st.button("💾 Guardar datos", type="primary", key="edr_save_cab_%d" % idb):
        try:
            _kg = round(float(_tn) * 1000.0, 1) if _tn is not None else None
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE produccion.fact_batch_proceso SET "
                        "identificador_unidad=%s, kg_obtenido=%s, "
                        "ticket_producto_final=%s, observaciones=%s WHERE id_batch=%s",
                        ((_nom.strip() or None), _kg, (_tkf.strip() or None),
                         (_obs.strip() or None), idb))
                audit.log("U", "fact_batch_proceso", idb,
                          {"editor_rapido": True, "identificador": _nom.strip(),
                           "kg_obtenido": _kg, "ticket_final": _tkf.strip() or None})
            cat.clear()
            ss["edr_nonce_%d" % idb] = _nz + 1
            st.success("✅ Datos guardados.")
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)

    # ================= 2 · tiempos por etapa =================
    st.markdown("##### 2 · Tiempos por etapa")
    ev = cat("SELECT id_evento_etapa, etapa, inicio_ts, fin_ts, duracion_real_min, "
             "horas_hombre FROM produccion.fact_etapa_evento WHERE id_batch=%s "
             "ORDER BY inicio_ts NULLS LAST, id_evento_etapa", (idb,))
    if ev is None or ev.empty:
        st.info("Esta reacción no tiene etapas registradas.")
    else:
        ev = ev.copy()
        _sh = pd.DataFrame({
            "Etapa": ev["etapa"].astype(str),
            "Inicio": _a_local(ev["inicio_ts"]),
            "Fin": _a_local(ev["fin_ts"]),
            "Duración (h)": (pd.to_numeric(ev["duracion_real_min"], errors="coerce") / 60.0).round(2),
            "Horas hombre": pd.to_numeric(ev["horas_hombre"], errors="coerce"),
        })
        _k = "edr_et_%d_%d" % (idb, _nz)
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
                   "guardar. Un fin anterior al inicio no se guarda.")
        if st.button("💾 Guardar tiempos", type="primary", key="edr_save_et_%d" % idb):
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
                                            ev["etapa"].iloc[_i])
                                continue
                            _dur = (round((_f1 - _i1).total_seconds() / 60.0, 1)
                                    if (pd.notna(_i1) and pd.notna(_f1)) else None)
                            cur.execute(
                                "UPDATE produccion.fact_etapa_evento SET inicio_ts=%s, "
                                "fin_ts=%s, duracion_real_min=%s, horas_hombre=%s "
                                "WHERE id_evento_etapa=%s",
                                (_a_utc_iso(_i1), _a_utc_iso(_f1), _dur,
                                 (float(_h1) if pd.notna(_h1) else None), _ide))
                            audit.log("U", "fact_etapa_evento", _ide,
                                      {"editor_rapido": True, "id_batch": idb,
                                       "etapa": str(ev["etapa"].iloc[_i]),
                                       "inicio": _a_utc_iso(_i1), "fin": _a_utc_iso(_f1),
                                       "duracion_min": _dur})
                            _nok += 1
                if _nok:
                    st.success("✅ %d etapa(s) actualizadas." % _nok)
                if _err:
                    st.error(" · ".join(_err))
                if _nok:
                    cat.clear()
                    ss["edr_nonce_%d" % idb] = _nz + 1
                    st.rerun()
                if not _nok and not _err:
                    st.info("No hay cambios para guardar.")
            except Exception as e:
                st.error("No se pudo guardar: %s" % e)

    # ================= 3 · tickets finales =================
    st.markdown("##### 3 · Tickets finales asociados")
    tk = cat("SELECT id, ticket, producto, calidad, kg, fecha::text AS fecha, fraccion, "
             "COALESCE(anulado,false) AS anulado "
             "FROM produccion.fact_batch_ticket_final WHERE id_batch=%s "
             "ORDER BY fecha NULLS LAST, id", (idb,))
    tk = tk.copy() if tk is not None else pd.DataFrame()
    _base = pd.DataFrame({
        "Ticket": tk["ticket"].astype(str) if not tk.empty else pd.Series(dtype="str"),
        "Producto": tk["producto"].astype(str) if not tk.empty else pd.Series(dtype="str"),
        "Calidad": tk["calidad"].astype(str) if not tk.empty else pd.Series(dtype="str"),
        "Kg": pd.to_numeric(tk["kg"], errors="coerce") if not tk.empty else pd.Series(dtype="float"),
        "Fecha": pd.to_datetime(tk["fecha"], errors="coerce") if not tk.empty else pd.Series(dtype="datetime64[ns]"),
        "Anulado": tk["anulado"].astype(bool) if not tk.empty else pd.Series(dtype="bool"),
    })
    _k2 = "edr_tk_%d_%d" % (idb, _nz)
    ed2 = st.data_editor(
        _base, hide_index=True, use_container_width=True, key=_k2, num_rows="dynamic",
        column_config={
            "Kg": st.column_config.NumberColumn(format="%.0f", min_value=0.0),
            "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Anulado": st.column_config.CheckboxColumn(
                "Anulado", help="Tildá para que el ticket deje de contar (no se borra)."),
        })
    _sum = float(pd.to_numeric(ed2["Kg"], errors="coerce").fillna(0)[~ed2["Anulado"].fillna(False)].sum()) \
        if not ed2.empty else 0.0
    st.caption("Suma de tickets vigentes: **%s kg** (%s TN)%s. Filas nuevas al final = "
               "tickets nuevos; tildá *Anulado* para dar de baja sin borrar."
               % (_n(_sum), _n(_sum / 1000.0, 2),
                  ("" if pd.isna(b["kg_obtenido"]) or not b["kg_obtenido"] else
                   " · TN manual de la reacción: %s" % _n(float(b["kg_obtenido"]) / 1000.0, 2))))
    if st.button("💾 Guardar tickets", type="primary", key="edr_save_tk_%d" % idb):
        # GUARDA: si el usuario BORRÓ filas de la grilla, las posiciones se corren y
        # los updates por posición pegarían en el ticket equivocado. Baja = Anulado.
        if len(ed2) < len(_base):
            st.error("Borraste fila(s) de la grilla: para dar de baja un ticket tildá "
                     "**Anulado** (no borres la fila). Recargá la página y volvé a editar.")
            st.stop()
        try:
            _nup, _nin = 0, 0
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    # updates de las filas existentes (por posición: mismo orden que _base)
                    for _i in range(min(len(_base), len(ed2))):
                        _id = int(tk["id"].iloc[_i])
                        _cmp = [(str(_base[c].iloc[_i]), str(ed2[c].iloc[_i]))
                                for c in ("Ticket", "Producto", "Calidad", "Kg", "Fecha", "Anulado")]
                        if all(a == bb for a, bb in _cmp):
                            continue
                        _r = ed2.iloc[_i]
                        cur.execute(
                            "UPDATE produccion.fact_batch_ticket_final SET ticket=%s, "
                            "producto=%s, calidad=%s, kg=%s, fecha=%s, anulado=%s WHERE id=%s",
                            ((str(_r["Ticket"]).strip() or None),
                             (str(_r["Producto"]).strip() or None),
                             (str(_r["Calidad"]).strip() or None),
                             (float(_r["Kg"]) if pd.notna(_r["Kg"]) else None),
                             (pd.to_datetime(_r["Fecha"]).date().isoformat()
                              if pd.notna(_r["Fecha"]) else None),
                             bool(_r["Anulado"]), _id))
                        audit.log("U", "fact_batch_ticket_final", _id,
                                  {"editor_rapido": True, "id_batch": idb,
                                   "ticket": str(_r["Ticket"]), "kg": (float(_r["Kg"])
                                   if pd.notna(_r["Kg"]) else None),
                                   "anulado": bool(_r["Anulado"])})
                        _nup += 1
                    # filas nuevas
                    for _i in range(len(_base), len(ed2)):
                        _r = ed2.iloc[_i]
                        _tkt = str(_r.get("Ticket") or "").strip()
                        _kgv = _r.get("Kg")
                        if not _tkt or pd.isna(_kgv) or float(_kgv) <= 0:
                            continue
                        cur.execute(
                            "INSERT INTO produccion.fact_batch_ticket_final "
                            "(id_batch, ticket, producto, calidad, kg, fecha, id_usuario) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                            (idb, _tkt, (str(_r.get("Producto") or "").strip() or None),
                             (str(_r.get("Calidad") or "").strip() or None), float(_kgv),
                             (pd.to_datetime(_r.get("Fecha")).date().isoformat()
                              if pd.notna(_r.get("Fecha")) else None), uid))
                        _nid = cur.fetchone()[0]
                        audit.log("I", "fact_batch_ticket_final", int(_nid),
                                  {"editor_rapido": True, "id_batch": idb, "ticket": _tkt,
                                   "kg": float(_kgv)})
                        _nin += 1
            if _nup or _nin:
                cat.clear()
                ss["edr_nonce_%d" % idb] = _nz + 1
                st.success("✅ %d ticket(s) actualizados · %d agregados." % (_nup, _nin))
                st.rerun()
            else:
                st.info("No hay cambios para guardar.")
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)
