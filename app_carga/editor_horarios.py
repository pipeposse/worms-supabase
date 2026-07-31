"""Editor masivo de reacciones terminadas: horarios, kilos finales, tickets de
pesada, tanque de acopio y evaluación de laboratorio — todo en una pantalla.

Vive en: Centro de Planificación → ⚙️ Administrar en curso → 🛠️ Gestión de
reacciones → ⏱️ Horarios & TN finales.

BLOQUE 1 — tabla de todas las reacciones finalizadas (filtrables por semana,
tipo, reactor y producto). Editable en la misma grilla:
  - Inicio real de reacción  → fact_batch_estado_log (REACCION) + fact_batch_proceso.inicio_ts
                               + fact_etapa_evento (etapa REACCION)
  - Fin de reacción real     → fact_batch_estado_log (REPOSO). Es el fin que usa el
                               desvío vs cronograma, NO el fin de acopio.
  - Final (TN) a mano        → fact_reaccion_cierre (metodo = 'EDITOR_MANUAL')
  - Tanque de acopio final   → fact_batch_proceso (id_tanque_are_final o
                               desg_id_tanque_destino según tipo de proceso)
Y muestra, sin editar: de dónde sale el kg real (Origen), cuántos tickets de
pesada tiene y si tuvo evaluación de laboratorio (columna Lab).

BLOQUE 2 — detalle de UNA reacción, con dos pestañas:
  🎫 Tickets de pesada final — asignar/quitar tickets de balanza ya evaluados.
     Un mismo ticket puede repartirse entre 2 (o más) reacciones: se guarda la
     fracción en fact_batch_ticket_final.fraccion y los kg proporcionales. La
     suma de los kg asignados define kg_obtenido de la reacción.
  🧪 Evaluación de laboratorio — ver de dónde viene el lab (muestra asignada a
     mano, ticket cargado con el ID de la reacción, o promedio de los tickets de
     pesada) y asignar una muestra de procesos_lab a mano.

Nota de esquema: el índice único vivo es (id_batch, ticket) WHERE anulado=false.
Por eso el mismo ticket SÍ puede ir a dos reacciones distintas, y el ON CONFLICT
correcto es (id_batch, ticket) — no (ticket).
"""
import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
_TZ = "America/Argentina/Buenos_Aires"

SQL_BASE = (
    "SELECT p.id_batch, p.ident, p.etiqueta, p.reactor, p.tipo, p.tipo_proceso, p.fecha, "
    "p.inicio_local AS inicio, p.fin_reaccion_local AS fin, p.prog_reaccion_h AS prog_h, "
    "p.mp_kg, p.real_kg, "
    "vt.id_producto, vt.producto, vt.id_tanque_destino, "
    "vt.tickets_kg, vt.kg_obtenido, vt.real_asignado_kg, vt.real_metodo, "
    "lf.fuente_lab, lf.id_procesos_lab, lf.n_tickets, lf.n_con_lab, "
    "lf.acidez_pct, lf.agua_pct, "
    "b.id_producto_buscado, dl.lab_producto, dl.lab_calidad "
    "FROM produccion.v_perf_reaccion p "
    "LEFT JOIN produccion.v_reaccion_terminada vt ON vt.id_batch = p.id_batch "
    "LEFT JOIN produccion.v_reaccion_lab_final lf ON lf.id_batch = p.id_batch "
    "LEFT JOIN produccion.fact_batch_proceso b ON b.id_batch = p.id_batch "
    "LEFT JOIN produccion.dic_producto_lab dl ON dl.id_producto = b.id_producto_buscado "
    "ORDER BY p.fecha DESC NULLS LAST, p.id_batch DESC")

SQL_TK_ASIG = (
    "SELECT f.id, f.ticket, f.producto, f.calidad, f.kg, f.fraccion, "
    "round(abs(COALESCE(tx.peso_neto,0))::numeric,0) AS kg_ticket "
    "FROM produccion.fact_batch_ticket_final f "
    "LEFT JOIN produccion.v_transacciones_limpias tx ON tx.transaccion::text = f.ticket "
    "WHERE f.id_batch = %s AND NOT COALESCE(f.anulado,false) ORDER BY f.ticket")

SQL_TK_CAND = (
    "SELECT tx.transaccion::text AS ticket, tx.lab_calidad AS calidad, "
    "round(abs(COALESCE(tx.peso_neto,0))::numeric,0) AS kg, tx.fecha_entrada AS fecha, "
    "COALESCE(a.frac_usada, 0) AS frac_usada, COALESCE(a.batches, '') AS batches "
    "FROM produccion.v_transacciones_limpias tx "
    "LEFT JOIN (SELECT f.ticket, SUM(COALESCE(f.fraccion, 1)) AS frac_usada, "
    "           string_agg(DISTINCT b.identificador_unidad, ', ') AS batches "
    "           FROM produccion.fact_batch_ticket_final f "
    "           LEFT JOIN produccion.fact_batch_proceso b ON b.id_batch = f.id_batch "
    "           WHERE NOT COALESCE(f.anulado,false) GROUP BY f.ticket) a "
    "       ON a.ticket = tx.transaccion::text "
    "WHERE tx.evaluado = 'SI' AND tx.peso_neto IS NOT NULL "
    "AND upper(COALESCE(tx.lab_producto,'') || '-' || COALESCE(tx.lab_calidad,'')) = upper(%s) "
    "AND COALESCE(a.frac_usada, 0) < 0.999 "
    "AND NOT EXISTS (SELECT 1 FROM produccion.fact_batch_ticket_final f2 "
    "                WHERE f2.ticket = tx.transaccion::text AND f2.id_batch = %s "
    "                AND NOT COALESCE(f2.anulado,false)) "
    "ORDER BY tx.fecha_entrada DESC NULLS LAST, tx.transaccion DESC LIMIT 200")

FRACCIONES = {"Entero (1/1)": 1.0, "Mitad (1/2)": 0.5, "Un tercio (1/3)": 1.0 / 3.0,
              "Un cuarto (1/4)": 0.25, "Otra…": None}


# ===================== helpers =====================

def _puede(USR):
    return str(USR.get("rol") or "") in ROLES_DIRECCION


def _origen(r):
    """De dónde sale hoy el kg real de esta reacción."""
    _a = r.get("real_asignado_kg")
    if pd.notna(_a) and float(_a or 0) > 0:
        _m = str(r.get("real_metodo") or "manual")
        if _m == "EDITOR_MANUAL":
            return "✍️ a mano"
        if _m == "tanque_asociado":
            return "🛢️ tanque"
        return "✍️ %s" % _m
    _t = r.get("tickets_kg")
    if pd.notna(_t) and float(_t or 0) > 0:
        return "🎫 tickets"
    _k = r.get("kg_obtenido")
    if pd.notna(_k) and float(_k or 0) > 0:
        return "📐 kg obtenido"
    return "— sin real"


def _lab_estado(r):
    """Texto corto de si la reacción tuvo evaluación de laboratorio y de dónde sale."""
    _f = str(r.get("fuente_lab") or "")
    _id = r.get("id_procesos_lab")
    _id = int(_id) if pd.notna(_id) else None
    if _f == "ASIGNADO":
        return "🧪 muestra #%s" % (_id if _id else "?")
    if _f == "TICKET_REACCION":
        return "🆔 ticket con el ID (#%s)" % (_id if _id else "?")
    if _f == "TICKETS":
        _n, _c = r.get("n_tickets"), r.get("n_con_lab")
        _n = int(_n) if pd.notna(_n) else 0
        _c = int(_c) if pd.notna(_c) else 0
        return "🎫 tickets (%d/%d)" % (_c, _n)
    return "⚪ sin lab"


def _sem_lbl(ts):
    """Etiqueta de semana ISO (lunes a domingo) a partir de una fecha."""
    if ts is None or pd.isna(ts):
        return "— sin fecha"
    _t = pd.Timestamp(ts)
    _lun = _t.normalize() - pd.Timedelta(days=int(_t.weekday()))
    return "S%02d · %s–%s" % (int(_lun.isocalendar()[1]), _lun.strftime("%d/%m"),
                              (_lun + pd.Timedelta(days=6)).strftime("%d/%m/%y"))


def _recompute_final(cur, idb):
    cur.execute("UPDATE produccion.fact_batch_proceso SET kg_obtenido = ("
                " SELECT COALESCE(sum(kg), 0) FROM produccion.fact_batch_ticket_final "
                " WHERE id_batch = %s AND NOT COALESCE(anulado, false)) WHERE id_batch = %s",
                (int(idb), int(idb)))


# ===================== bloque 1: tabla =====================

def _tabla(USR, cat, conectar, base):
    _ed_ok = _puede(USR)

    # --- tanques habilitados para los productos finales presentes ---
    _prods = sorted({int(x) for x in base["id_producto"].dropna().tolist()})
    _tk = None
    if _prods:
        _tk = cat("SELECT tp.id_producto, dp.codigo_producto, t.id_tanque, "
                  "COALESCE(NULLIF(t.nombre,''), t.codigo) AS tanque, t.codigo "
                  "FROM produccion.dim_tanque_producto tp "
                  "JOIN produccion.dim_tanque t ON t.id_tanque = tp.id_tanque AND COALESCE(t.activo, TRUE) "
                  "JOIN produccion.dim_producto dp ON dp.id_producto = tp.id_producto "
                  "WHERE tp.id_producto = ANY(%s) ORDER BY dp.codigo_producto, t.nombre", (_prods,))
    lbl2tk, tk2lbl = {}, {}
    if _tk is not None and not _tk.empty:
        for _, t in _tk.iterrows():
            _l = "%s · %s" % (t["codigo_producto"], t["tanque"])
            lbl2tk[_l] = (int(t["id_tanque"]), int(t["id_producto"]), str(t["tanque"]),
                          str(t["codigo"] or ""))
            tk2lbl[(int(t["id_producto"]), int(t["id_tanque"]))] = _l

    def _lbl_actual(r):
        if pd.isna(r["id_tanque_destino"]):
            return None
        _idp = int(r["id_producto"]) if pd.notna(r["id_producto"]) else None
        _l = tk2lbl.get((_idp, int(r["id_tanque_destino"]))) if _idp is not None else None
        if _l is None:
            _n = cat("SELECT COALESCE(NULLIF(nombre,''), codigo) AS n, codigo "
                     "FROM produccion.dim_tanque WHERE id_tanque=%s", (int(r["id_tanque_destino"]),))
            if _n is not None and not _n.empty:
                _l = "⚠️ %s · %s (no habilitado)" % (r["producto"] or "?", _n.iloc[0]["n"])
                lbl2tk.setdefault(_l, (int(r["id_tanque_destino"]),
                                       (_idp if _idp is not None else -1),
                                       str(_n.iloc[0]["n"]), str(_n.iloc[0]["codigo"] or "")))
        return _l

    base = base.copy()
    base["tk_lbl"] = base.apply(_lbl_actual, axis=1)
    _opciones = sorted(lbl2tk.keys())

    view = pd.DataFrame({
        "ID": base["ident"],
        "Semana": base["_sem"],
        "Reacción": base["etiqueta"],
        "Producto": base["producto"],
        "MP (TN)": (base["mp_kg"] / 1000.0).round(2),
        "Final (TN)": (base["real_kg"] / 1000.0).round(2),
        "Origen": [_origen(base.iloc[i]) for i in range(len(base))],
        "Tickets (TN)": (base["tickets_kg"] / 1000.0).round(2),
        "N° tk": base["n_tickets"],
        "Lab": [_lab_estado(base.iloc[i]) for i in range(len(base))],
        "Acidez %": base["acidez_pct"],
        "Inicio real": base["inicio"],
        "Fin reacción real": base["fin"],
        "Programado (h)": base["prog_h"],
        "Real (h)": ((base["fin"] - base["inicio"]).dt.total_seconds() / 3600.0).round(1),
        "Tanque final": base["tk_lbl"],
    })
    view["Δ (h)"] = (view["Real (h)"] - view["Programado (h)"]).round(1)
    view = view[["ID", "Semana", "Reacción", "Producto", "MP (TN)", "Final (TN)", "Origen",
                 "Tickets (TN)", "N° tk", "Lab", "Acidez %", "Inicio real", "Fin reacción real",
                 "Programado (h)", "Real (h)", "Δ (h)", "Tanque final"]]

    _bloq = ["ID", "Semana", "Reacción", "Producto", "MP (TN)", "Origen", "Tickets (TN)",
             "N° tk", "Lab", "Acidez %", "Programado (h)", "Real (h)", "Δ (h)"]
    if not _ed_ok:
        _bloq = list(view.columns)

    ed = st.data_editor(
        view, hide_index=True, use_container_width=True, key="ehz_edit", disabled=_bloq,
        column_config={
            "Semana": st.column_config.TextColumn(
                "Semana", help="Semana ISO (lunes a domingo) de la fecha de la reacción."),
            "MP (TN)": st.column_config.NumberColumn(
                format="%.2f", help="Materia prima cargada al reactor."),
            "Final (TN)": st.column_config.NumberColumn(
                format="%.2f", min_value=0.0, step=0.01,
                help="Producto final real en TN — EDITABLE. Se guarda como cierre manual "
                     "(metodo EDITOR_MANUAL) y pisa tickets/kg_obtenido. Vacío = sin real."),
            "Origen": st.column_config.TextColumn(
                "Origen", help="De dónde sale hoy el kg real: ✍️ carga a mano · 🎫 tickets de "
                               "pesada · 🛢️ variación de tanque · 📐 kg_obtenido · sin real."),
            "Tickets (TN)": st.column_config.NumberColumn(
                format="%.2f", help="Suma de los tickets de pesada finales asignados. Se cargan "
                                    "abajo, en el detalle de la reacción."),
            "N° tk": st.column_config.NumberColumn(
                format="%d", help="Cantidad de tickets de pesada asignados a esta reacción."),
            "Lab": st.column_config.TextColumn(
                "Lab", help="Evaluación de laboratorio del producto final. 🧪 = muestra asignada a "
                            "mano · 🆔 = hay un ticket de lab cargado con el ID de la reacción · "
                            "🎫 = sale del promedio de los tickets de pesada (x/y = cuántos de "
                            "ellos tienen análisis) · ⚪ = sin lab."),
            "Acidez %": st.column_config.NumberColumn(
                format="%.2f", help="Acidez del producto final según la fuente de lab de la "
                                    "columna anterior."),
            "Inicio real": st.column_config.DatetimeColumn(
                "Inicio real", format="DD/MM/YYYY HH:mm", step=60,
                help="Arranque real de la reacción. Reescribe el log de estados, "
                     "fact_batch_proceso y la etapa REACCION."),
            "Fin reacción real": st.column_config.DatetimeColumn(
                "Fin reacción real", format="DD/MM/YYYY HH:mm", step=60,
                help="Fin de REACCIÓN = pase a REPOSO. No es el fin de acopio."),
            "Programado (h)": st.column_config.NumberColumn(
                format="%.1f", help="Duración Reacción del cronograma (sin reposo ni decantación)."),
            "Real (h)": st.column_config.NumberColumn(
                format="%.1f", help="Fin de reacción − inicio (valores guardados)."),
            "Δ (h)": st.column_config.NumberColumn(
                format="%.1f", help="Reacción real − programada. + = tardó más de lo previsto."),
            "Tanque final": st.column_config.SelectboxColumn(
                "Tanque final", options=_opciones, required=False,
                help="Tanque de acopio del producto final. Las opciones vienen de "
                     "dim_tanque_producto (tanques habilitados); elegí uno del MISMO producto "
                     "que la reacción — si no coincide, no se guarda."),
        })

    if not _ed_ok:
        st.info("Solo Dirección (SUPERVISOR / ADMIN) puede editar. Arriba, los valores guardados.")
        return

    # --- detectar cambios ---
    cambios, invalidas = [], []
    for i in range(len(base)):
        idb = int(base.iloc[i]["id_batch"])
        old_i, old_f = base.iloc[i]["inicio"], base.iloc[i]["fin"]
        old_t = base.iloc[i]["tk_lbl"]
        new_i = pd.to_datetime(ed.iloc[i]["Inicio real"]) if pd.notna(ed.iloc[i]["Inicio real"]) else pd.NaT
        new_f = pd.to_datetime(ed.iloc[i]["Fin reacción real"]) if pd.notna(ed.iloc[i]["Fin reacción real"]) else pd.NaT
        new_t = ed.iloc[i]["Tanque final"] if pd.notna(ed.iloc[i]["Tanque final"]) else None
        old_k = round(float(base.iloc[i]["real_kg"]) / 1000.0, 2) if pd.notna(base.iloc[i]["real_kg"]) else None
        new_k = float(ed.iloc[i]["Final (TN)"]) if pd.notna(ed.iloc[i]["Final (TN)"]) else None
        chg_i = pd.notna(new_i) and (pd.isna(old_i) or new_i != old_i)
        chg_f = pd.notna(new_f) and (pd.isna(old_f) or new_f != old_f)
        chg_t = (new_t is not None) and (new_t != old_t)
        chg_k = (new_k is not None) and (old_k is None or abs(new_k - old_k) > 0.005)
        if not (chg_i or chg_f or chg_t or chg_k):
            continue
        _ident = str(base.iloc[i]["ident"])
        eff_i = new_i if pd.notna(new_i) else old_i
        eff_f = new_f if pd.notna(new_f) else old_f
        if (chg_i or chg_f) and pd.notna(eff_i) and pd.notna(eff_f) and eff_f <= eff_i:
            invalidas.append("%s: fin ≤ inicio" % _ident)
            continue
        tk_new = None
        if chg_t:
            _info = lbl2tk.get(new_t)
            _idp = int(base.iloc[i]["id_producto"]) if pd.notna(base.iloc[i]["id_producto"]) else None
            if _info is None or _idp is None or _info[1] != _idp:
                invalidas.append("%s: el tanque elegido no es del producto %s"
                                 % (_ident, base.iloc[i]["producto"] or "?"))
                continue
            tk_new = _info
        cambios.append({"idb": idb, "ident": _ident,
                        "tipo_proceso": str(base.iloc[i]["tipo_proceso"] or ""),
                        "old_i": old_i, "old_f": old_f,
                        "new_i": (new_i if chg_i else None), "new_f": (new_f if chg_f else None),
                        "eff_i": eff_i, "eff_f": eff_f,
                        "tk": tk_new, "tk_lbl": (new_t if chg_t else None),
                        "kg": (round(new_k * 1000.0, 1) if chg_k else None),
                        "origen": str(view.iloc[i]["Origen"]),
                        "prog": base.iloc[i]["prog_h"]})

    if invalidas:
        st.error("No se van a guardar: " + " · ".join(invalidas))

    if cambios:
        _prev = pd.DataFrame([{
            "ID": c["ident"],
            "Nuevo inicio": (c["eff_i"].strftime("%d/%m %H:%M") if pd.notna(c["eff_i"]) else "—"),
            "Nuevo fin": (c["eff_f"].strftime("%d/%m %H:%M") if pd.notna(c["eff_f"]) else "—"),
            "Real (h)": (round((c["eff_f"] - c["eff_i"]).total_seconds() / 3600.0, 1)
                         if pd.notna(c["eff_i"]) and pd.notna(c["eff_f"]) else None),
            "Prog. (h)": (round(float(c["prog"]), 1) if pd.notna(c["prog"]) else None),
            "Nuevo tanque": (c["tk_lbl"] or "(sin cambio)"),
            "Final (TN)": (round(c["kg"] / 1000.0, 2) if c["kg"] is not None else "(sin cambio)"),
            "Pisa a": (c["origen"] if c["kg"] is not None else "—"),
        } for c in cambios])
        _prev["Δ (h)"] = (_prev["Real (h)"] - _prev["Prog. (h)"]).round(1)
        st.markdown("**%d reacción(es) con cambios:**" % len(cambios))
        st.dataframe(_prev, hide_index=True, use_container_width=True)
        _pisa = [c for c in cambios if c["kg"] is not None and "tickets" in c["origen"]]
        if _pisa:
            st.warning("⚠️ %d reacción(es) tenían el real sacado de **tickets de pesada** y vas a "
                       "reemplazarlo por una carga a mano: %s. Los tickets quedan guardados, pero "
                       "dejan de ser el número que usa la app."
                       % (len(_pisa), ", ".join(c["ident"] for c in _pisa)))
    else:
        st.caption("Sin cambios pendientes: editá Inicio real / Fin reacción real / Final (TN) / "
                   "Tanque final y apretá Guardar.")

    if st.button("💾 Guardar cambios de la tabla", type="primary", key="ehz_save",
                 disabled=(not cambios)):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for c in cambios:
                        idb = c["idb"]
                        if c["new_i"] is not None:
                            _v = str(c["new_i"])
                            cur.execute("UPDATE produccion.fact_batch_estado_log "
                                        "SET ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s AND estado_nuevo='REACCION'", (_v, _TZ, idb))
                            cur.execute("UPDATE produccion.fact_batch_proceso "
                                        "SET inicio_ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s", (_v, _TZ, idb))
                            if pd.notna(c["old_i"]):
                                cur.execute("UPDATE produccion.fact_etapa_evento "
                                            "SET inicio_ts=(%s::timestamp AT TIME ZONE %s) "
                                            "WHERE id_batch=%s AND etapa='REACCION' "
                                            "AND inicio_ts=(%s::timestamp AT TIME ZONE %s)",
                                            (_v, _TZ, idb, str(c["old_i"]), _TZ))
                        if c["new_f"] is not None:
                            _v = str(c["new_f"])
                            cur.execute("UPDATE produccion.fact_batch_estado_log "
                                        "SET ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s AND estado_nuevo='REPOSO'", (_v, _TZ, idb))
                            if cur.rowcount == 0:
                                cur.execute("INSERT INTO produccion.fact_batch_estado_log "
                                            "(id_batch, estado_anterior, estado_nuevo, ts, id_usuario, motivo) "
                                            "VALUES (%s,'REACCION','REPOSO',(%s::timestamp AT TIME ZONE %s),"
                                            "%s,'editor fin de reacción')",
                                            (idb, _v, _TZ, int(USR["id_usuario"])))
                        if c["tk"] is not None:
                            _idt, _, _nom, _cod = c["tk"]
                            _txt = ("%s · %s" % (_nom, _cod)) if _cod else _nom
                            if c["tipo_proceso"] == "DESGOMADO_ACUOSO":
                                cur.execute("UPDATE produccion.fact_batch_proceso "
                                            "SET desg_id_tanque_destino=%s, tanque_destino=%s "
                                            "WHERE id_batch=%s", (_idt, _txt, idb))
                            else:
                                cur.execute("UPDATE produccion.fact_batch_proceso "
                                            "SET id_tanque_are_final=%s, tanque_destino=%s "
                                            "WHERE id_batch=%s", (_idt, _txt, idb))
                        if c["kg"] is not None:
                            cur.execute("INSERT INTO produccion.fact_reaccion_cierre "
                                        "(id_batch, real_kg, metodo, id_usuario, actualizado_en) "
                                        "VALUES (%s,%s,'EDITOR_MANUAL',%s,now()) "
                                        "ON CONFLICT (id_batch) DO UPDATE SET "
                                        "real_kg=EXCLUDED.real_kg, metodo='EDITOR_MANUAL', "
                                        "id_usuario=EXCLUDED.id_usuario, actualizado_en=now()",
                                        (idb, float(c["kg"]), int(USR["id_usuario"])))
                        audit.log("U", "fact_batch_proceso", idb,
                                  {"inicio": (str(c["new_i"]) if c["new_i"] is not None else None),
                                   "fin": (str(c["new_f"]) if c["new_f"] is not None else None),
                                   "tanque_final": (c["tk"][0] if c["tk"] is not None else None),
                                   "real_kg": c["kg"],
                                   "via": "planificacion_editor_horarios"})
            st.success("Guardado: %d reacción(es) actualizadas." % len(cambios))
            cat.clear()
            st.rerun()
        except Exception as e:
            st.exception(e)


# ===================== bloque 2a: tickets de pesada =====================

def _tickets(USR, cat, conectar, r):
    idb = int(r["id_batch"])
    _pobj = str(r["producto"] or "").strip()
    st.caption("Tickets de balanza (pesadas) **ya evaluados por laboratorio** del producto final. "
               "La suma de los kg asignados define `kg_obtenido` de la reacción. Un mismo ticket "
               "puede repartirse entre dos reacciones: elegí la fracción al asignarlo.")
    if not _pobj:
        st.info("Esta reacción no tiene producto final definido; no puedo buscar tickets.")
        return

    asg = cat(SQL_TK_ASIG, (idb,))
    _tot = float(asg["kg"].fillna(0).sum()) if (asg is not None and not asg.empty) else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Producto final", _pobj)
    c2.metric("Tickets asignados", int(len(asg)) if asg is not None else 0)
    c3.metric("Total por tickets (t)", "%.2f" % (_tot / 1000.0))

    _real_manual = (pd.notna(r.get("real_asignado_kg")) and float(r.get("real_asignado_kg") or 0) > 0
                    and str(r.get("real_metodo") or "") == "EDITOR_MANUAL")
    if _real_manual and _tot > 0:
        st.warning("Esta reacción tiene un **cierre manual** de %.2f t que le gana a los tickets "
                   "(%.2f t). Mientras exista, la app usa el manual."
                   % (float(r["real_asignado_kg"]) / 1000.0, _tot / 1000.0))
        if _puede(USR) and st.button("↩️ Usar los tickets como kilos finales (borra el cierre manual)",
                                     key="ehz_tk_usar_%d" % idb):
            try:
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM produccion.fact_reaccion_cierre WHERE id_batch=%s", (idb,))
                        _recompute_final(cur, idb)
                        audit.log("D", "fact_reaccion_cierre", idb, {"motivo": "vuelve a tickets"})
                st.success("Listo: los kilos finales vuelven a salir de los tickets.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)

    if not _puede(USR):
        if asg is not None and not asg.empty:
            st.dataframe(asg.drop(columns=["id"]), hide_index=True, use_container_width=True)
        return

    # ---------- asignar ----------
    cand = cat(SQL_TK_CAND, (_pobj, idb))
    st.markdown("**Tickets pesados disponibles** (evaluados como `%s`, con saldo sin asignar)" % _pobj)
    if cand is not None and not cand.empty:
        def _fmt(x):
            _lib = max(0.0, 1.0 - float(x["frac_usada"] or 0))
            _kg = float(x["kg"] or 0)
            _txt = "#%s · %.2f t · cal %s · %s" % (x["ticket"], _kg / 1000.0,
                                                   x["calidad"] or "-", x["fecha"])
            if _lib < 0.999:
                _txt += "  ⚠️ queda %d%% (el resto ya está en %s)" % (round(_lib * 100),
                                                                      x["batches"] or "otra reacción")
            return _txt
        _copt = [_fmt(cand.iloc[i]) for i in range(len(cand))]
        _sel = st.multiselect("Elegí tickets para asignar a %s" % r["ident"], _copt,
                              key="ehz_tk_sel_%d" % idb)
        fc1, fc2 = st.columns([2, 1])
        _fl = fc1.radio("¿Cuánto de cada ticket entra en esta reacción?", list(FRACCIONES.keys()),
                        horizontal=True, key="ehz_tk_frac_%d" % idb,
                        help="Si el camión se repartió entre dos reacciones, poné Mitad en cada "
                             "una. Se guarda la fracción y los kg proporcionales.")
        _frac = FRACCIONES[_fl]
        if _frac is None:
            _frac = float(fc2.number_input("Fracción (0–1)", min_value=0.01, max_value=1.0,
                                           value=0.5, step=0.05, format="%.2f",
                                           key="ehz_tk_fracn_%d" % idb))
        else:
            fc2.metric("Fracción", "%.0f%%" % (_frac * 100))
        if st.button("➕ Asignar seleccionados", type="primary", key="ehz_tk_add_%d" % idb,
                     use_container_width=True, disabled=(not _sel)):
            try:
                _n = 0
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        for _s in _sel:
                            _rc = cand.iloc[_copt.index(_s)]
                            _lib = max(0.0, 1.0 - float(_rc["frac_usada"] or 0))
                            _f = min(_frac, _lib)
                            if _f <= 0:
                                continue
                            _kg = round(float(_rc["kg"] or 0) * _f, 1)
                            cur.execute(
                                "INSERT INTO produccion.fact_batch_ticket_final "
                                "(id_batch, ticket, producto, calidad, kg, fecha, fraccion, id_usuario) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                                "ON CONFLICT (id_batch, ticket) WHERE anulado = false "
                                "DO UPDATE SET kg = EXCLUDED.kg, fraccion = EXCLUDED.fraccion",
                                (idb, str(_rc["ticket"]), _pobj, _rc["calidad"], _kg,
                                 (str(_rc["fecha"]) if pd.notna(_rc["fecha"]) else None),
                                 round(_f, 4), int(USR["id_usuario"])))
                            _n += 1
                        _recompute_final(cur, idb)
                        audit.log("I", "fact_batch_ticket_final", idb,
                                  {"asignados": _n, "fraccion": round(_frac, 4)})
                st.success("%d ticket(s) asignados al %.0f%%." % (_n, _frac * 100))
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
    else:
        st.caption("No hay tickets pesados con saldo para este producto. Podés cargar uno a mano abajo.")

    with st.expander("➕ Agregar ticket a mano (no está en balanza o vino de otro lado)"):
        _mt = st.text_input("N° de ticket", key="ehz_tk_mt_%d" % idb)
        _mk = st.number_input("Kilos (0 = buscarlos en balanza)", min_value=0.0, value=0.0,
                              step=10.0, format="%g", key="ehz_tk_mk_%d" % idb)
        _mf = st.number_input("Fracción del ticket que entra acá", min_value=0.01, max_value=1.0,
                              value=1.0, step=0.05, format="%.2f", key="ehz_tk_mf_%d" % idb)
        _mc = st.text_input("Calidad", value="", key="ehz_tk_mc_%d" % idb)
        if st.button("➕ Asignar a mano", key="ehz_tk_man_%d" % idb):
            _mtv = (_mt or "").strip()
            if not _mtv:
                st.warning("Poné el N° de ticket.")
            else:
                try:
                    _kgv, _calv = float(_mk or 0), ((_mc or "").strip() or None)
                    if _kgv <= 0:
                        _look = cat("SELECT round(abs(COALESCE(peso_neto,0))::numeric,0) AS kg, "
                                    "lab_calidad FROM produccion.v_transacciones_limpias "
                                    "WHERE transaccion::text=%s LIMIT 1", (_mtv,))
                        if _look is not None and not _look.empty:
                            _kgv = float(_look.iloc[0]["kg"] or 0) * float(_mf)
                            if not _calv:
                                _calv = _look.iloc[0]["lab_calidad"]
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO produccion.fact_batch_ticket_final "
                                "(id_batch, ticket, producto, calidad, kg, fraccion, id_usuario) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                                "ON CONFLICT (id_batch, ticket) WHERE anulado = false "
                                "DO UPDATE SET kg = EXCLUDED.kg, fraccion = EXCLUDED.fraccion",
                                (idb, _mtv, _pobj, _calv, round(_kgv, 1), round(float(_mf), 4),
                                 int(USR["id_usuario"])))
                            _recompute_final(cur, idb)
                            audit.log("I", "fact_batch_ticket_final", idb, {"manual": _mtv})
                    st.success("Ticket %s asignado." % _mtv)
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    # ---------- asignados ----------
    if asg is not None and not asg.empty:
        st.markdown("**Tickets asignados a %s**" % r["ident"])
        _disp = pd.DataFrame({
            "Ticket": asg["ticket"],
            "Calidad": asg["calidad"],
            "Kg ticket": asg["kg_ticket"],
            "Fracción": pd.to_numeric(asg["fraccion"], errors="coerce").fillna(1.0),
            "Kg asignados": pd.to_numeric(asg["kg"], errors="coerce"),
            "Quitar": False,
        })
        edp = st.data_editor(
            _disp, hide_index=True, use_container_width=True, key="ehz_tk_ed_%d" % idb,
            disabled=["Ticket", "Calidad", "Kg ticket"],
            column_config={
                "Kg ticket": st.column_config.NumberColumn(
                    format="%g", help="Peso neto total del ticket en balanza."),
                "Fracción": st.column_config.NumberColumn(
                    format="%.2f", min_value=0.01, max_value=1.0, step=0.05,
                    help="Qué parte del ticket entra en esta reacción. Si la cambiás, los kg se "
                         "recalculan solos sobre el peso del ticket."),
                "Kg asignados": st.column_config.NumberColumn(
                    format="%g", help="Kilos que suman a esta reacción. Si los editás a mano, la "
                                      "fracción se recalcula a partir de ellos."),
                "Quitar": st.column_config.CheckboxColumn(
                    help="Marcá y guardá para desasignar el ticket (queda anulado, no se borra)."),
            })
        if st.button("💾 Guardar tickets", type="primary", key="ehz_tk_save_%d" % idb,
                     use_container_width=True):
            try:
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        for i in range(len(edp)):
                            _idr = int(asg.iloc[i]["id"])
                            if bool(edp.iloc[i]["Quitar"]):
                                cur.execute("UPDATE produccion.fact_batch_ticket_final "
                                            "SET anulado=true WHERE id=%s", (_idr,))
                                continue
                            _kgt = float(asg.iloc[i]["kg_ticket"] or 0)
                            _f_old = float(asg.iloc[i]["fraccion"] or 1.0)
                            _k_old = float(asg.iloc[i]["kg"] or 0)
                            _f_new = float(edp.iloc[i]["Fracción"] or 1.0)
                            _k_new = float(edp.iloc[i]["Kg asignados"] or 0)
                            if abs(_f_new - _f_old) > 0.001 and _kgt > 0:
                                _k_new = round(_kgt * _f_new, 1)          # manda la fracción
                            elif abs(_k_new - _k_old) > 0.5 and _kgt > 0:
                                _f_new = round(_k_new / _kgt, 4)          # manda el kg
                            cur.execute("UPDATE produccion.fact_batch_ticket_final "
                                        "SET kg=%s, fraccion=%s WHERE id=%s",
                                        (round(_k_new, 1), round(_f_new, 4), _idr))
                        _recompute_final(cur, idb)
                        audit.log("U", "fact_batch_ticket_final", idb, {"n": len(edp)})
                st.success("Tickets actualizados; los kilos finales se recalcularon.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
        st.caption("⚖️ **Kilos finales por tickets = %s kg (%.2f t)**" % ("{:,.0f}".format(_tot),
                                                                          _tot / 1000.0))


# ===================== bloque 2b: laboratorio =====================

def _lab(USR, cat, conectar, r):
    idb = int(r["id_batch"])
    _fuente = str(r.get("fuente_lab") or "")
    _idl = int(r["id_procesos_lab"]) if pd.notna(r.get("id_procesos_lab")) else None

    st.caption("De dónde sale el análisis del producto final de esta reacción. Si tiene tickets de "
               "pesada evaluados, el lab ya sale de ahí (promedio ponderado por kg). Si no, o si el "
               "ticket de lab se cargó con el ID de la reacción, se resuelve acá.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Fuente del lab", {"ASIGNADO": "🧪 muestra asignada",
                                 "TICKET_REACCION": "🆔 ticket con el ID",
                                 "TICKETS": "🎫 tickets de pesada"}.get(_fuente, "⚪ sin lab"))
    m2.metric("Acidez (%)", ("%.2f" % float(r["acidez_pct"])) if pd.notna(r.get("acidez_pct")) else "—")
    m3.metric("Agua (%)", ("%.2f" % float(r["agua_pct"])) if pd.notna(r.get("agua_pct")) else "—")
    if _fuente == "TICKET_REACCION":
        st.info("Detectado automático: hay una muestra en `procesos_lab` cargada con el ticket "
                "**%s** (el ID de la reacción). Muestra #%s." % (r["ident"], _idl))
    if not _fuente:
        st.warning("Esta reacción **no tiene evaluación de laboratorio** por ningún camino: ni "
                   "muestra asignada, ni ticket cargado con su ID, ni tickets de pesada evaluados.")

    if not _puede(USR):
        return

    _lab_prod = r.get("lab_producto") or (str(r.get("producto") or "").split("-")[0] or None)
    _lab_cal = r.get("lab_calidad")
    if not _lab_prod:
        st.warning("Esta reacción no tiene producto de laboratorio mapeado en `dic_producto_lab`; "
                   "no puedo filtrar muestras.")
        return

    _q = st.text_input("🔍 Buscar muestra por ticket / n° de muestra / id",
                       key="ehz_lab_q_%d" % idb,
                       placeholder="ej: %s · 5690 · 424 (vacío = últimas 30)" % (r["ident"] or "RE-1"))
    _flt, _par = "", [str(_lab_prod)]
    if _q.strip():
        _flt = "AND (ticket ILIKE %s OR num_muestra::text ILIKE %s OR id::text = %s) "
        _par += ["%" + _q.strip() + "%", "%" + _q.strip() + "%", _q.strip()]
    _par += [str(r["ident"] or ""), (str(_lab_cal) if _lab_cal else "")]
    _mu = cat("SELECT id, ticket, num_muestra, fecha, producto_lab, "
              "calidad_final_lab AS calidad, prc_acidez, prc_agua, ppm_azufre "
              "FROM produccion.procesos_lab WHERE producto_lab=%s "
              "AND COALESCE(anulado,false)=false " + _flt +
              "ORDER BY (CASE WHEN ticket ILIKE %s THEN 0 ELSE 1 END), "
              "(CASE WHEN calidad_final_lab=%s THEN 0 ELSE 1 END), "
              "fecha DESC NULLS LAST, id DESC LIMIT 30", tuple(_par))
    if _mu is None or _mu.empty:
        st.warning("No hay muestras de %s%s." % (_lab_prod,
                   (" que coincidan con «%s»" % _q.strip()) if _q.strip() else " en procesos_lab"))
        return

    def _fmt_mu(x):
        try:
            _f = pd.to_datetime(x["fecha"]).strftime("%d/%m/%y")
        except Exception:
            _f = "—"
        _tk = (str(x["ticket"]).strip() if pd.notna(x["ticket"]) and str(x["ticket"]).strip()
               else ("muestra %s" % x["num_muestra"] if pd.notna(x["num_muestra"]) else "sin ticket"))
        _cal = ("-%s" % x["calidad"]) if pd.notna(x["calidad"]) and str(x["calidad"]).strip() else ""
        _aci = (" · acidez %.2f%%" % float(x["prc_acidez"])) if pd.notna(x["prc_acidez"]) else ""
        _agu = (" · agua %.2f%%" % float(x["prc_agua"])) if pd.notna(x["prc_agua"]) else ""
        return "🎫 %s · %s · %s%s%s%s · #%d" % (_tk, _f, x["producto_lab"], _cal, _aci, _agu,
                                                int(x["id"]))

    _ops = [_fmt_mu(_mu.iloc[i]) for i in range(len(_mu))]
    _ix = next((i for i in range(len(_mu)) if _idl and int(_mu.iloc[i]["id"]) == _idl), 0)
    _s = st.selectbox("Muestra de laboratorio (%s%s)" % (_lab_prod,
                      (", calidad %s primero" % _lab_cal) if _lab_cal else ""),
                      _ops, index=_ix, key="ehz_lab_sel_%d" % idb)
    _id_lab = int(_mu.iloc[_ops.index(_s)]["id"])

    b1, b2 = st.columns([2, 1])
    if b1.button("💾 Asignar muestra #%d a %s" % (_id_lab, r["ident"]), type="primary",
                 key="ehz_lab_save_%d" % idb, use_container_width=True):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO produccion.fact_batch_lab_final "
                                "(id_batch, id_procesos_lab, id_usuario) VALUES (%s,%s,%s) "
                                "ON CONFLICT (id_batch) DO UPDATE SET "
                                "id_procesos_lab=EXCLUDED.id_procesos_lab, "
                                "id_usuario=EXCLUDED.id_usuario, creado_en=now()",
                                (idb, int(_id_lab), int(USR["id_usuario"])))
                    audit.log("U", "fact_batch_lab_final", idb, {"id_procesos_lab": int(_id_lab)})
            st.success("Muestra #%d asignada a %s." % (_id_lab, r["ident"]))
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)
    if _fuente == "ASIGNADO" and b2.button("🗑️ Quitar asignación", key="ehz_lab_del_%d" % idb,
                                           use_container_width=True):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM produccion.fact_batch_lab_final WHERE id_batch=%s", (idb,))
                    audit.log("D", "fact_batch_lab_final", idb, {})
            st.success("Asignación quitada; vuelve a resolverse por tickets o por ID.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


# ===================== render =====================

def render(USR, cat, conectar):
    st.caption(
        "Todo lo de una reacción terminada en una pantalla: **horarios reales, kilos finales, "
        "tickets de pesada, tanque de acopio y evaluación de laboratorio**. Arriba la tabla de "
        "todas (editable en la grilla); abajo el detalle de la que elijas.")

    df = cat(SQL_BASE)
    if df is None or df.empty:
        st.info("No hay reacciones finalizadas para editar.")
        return

    df = df.copy()
    df["inicio"] = pd.to_datetime(df["inicio"], errors="coerce")
    df["fin"] = pd.to_datetime(df["fin"], errors="coerce")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    for _c in ("prog_h", "mp_kg", "real_kg", "tickets_kg", "kg_obtenido", "real_asignado_kg",
               "n_tickets", "n_con_lab", "acidez_pct", "agua_pct"):
        if _c in df.columns:
            df[_c] = pd.to_numeric(df[_c], errors="coerce")
    # semana de referencia: fecha de la reacción, o el inicio real si no hay fecha
    df["_fref"] = df["fecha"].fillna(df["inicio"])
    df["_sem"] = [_sem_lbl(x) for x in df["_fref"]]

    # ---------- filtros ----------
    f1, f2, f3 = st.columns([2, 1, 1])
    _sems = sorted([s for s in df["_sem"].unique().tolist() if s != "— sin fecha"], reverse=True)
    if "— sin fecha" in df["_sem"].values:
        _sems = _sems + ["— sin fecha"]
    _selsem = f1.multiselect("Semana (lunes a domingo)", _sems, default=_sems, key="ehz_f_sem",
                             help="Vacío = todas. La semana sale de la fecha de la reacción.")
    _tipos = ["Todos"] + sorted([str(x) for x in df["tipo"].dropna().unique().tolist()])
    _tipo = f2.selectbox("Tipo", _tipos, key="ehz_f_tipo")
    _reac = ["Todos"] + sorted([str(x) for x in df["reactor"].dropna().unique().tolist()])
    _rx = f3.selectbox("Reactor", _reac, key="ehz_f_reactor")

    g1, g2, g3 = st.columns([2, 1, 1])
    _prods_f = sorted([str(x) for x in df["producto"].dropna().unique().tolist()])
    _selp = g1.multiselect("Producto final", _prods_f, default=_prods_f, key="ehz_f_prod")
    _sin_f = g2.checkbox("Solo sin Final (TN)", value=False, key="ehz_f_sin",
                         help="Reacciones terminadas a las que todavía no se les cargó el real.")
    _sin_l = g3.checkbox("Solo sin lab", value=False, key="ehz_f_sinlab",
                         help="Reacciones sin ninguna evaluación de laboratorio asociada.")

    if _selsem:
        df = df[df["_sem"].isin(_selsem)]
    if _tipo != "Todos":
        df = df[df["tipo"].astype(str) == _tipo]
    if _rx != "Todos":
        df = df[df["reactor"].astype(str) == _rx]
    if _selp:
        df = df[df["producto"].astype(str).isin(_selp) | df["producto"].isna()]
    if _sin_f:
        df = df[df["real_kg"].fillna(0) <= 0]
    if _sin_l:
        df = df[df["fuente_lab"].isna()]
    if df.empty:
        st.info("No hay reacciones finalizadas con esos filtros.")
        return
    base = df.reset_index(drop=True)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Reacciones", len(base))
    k2.metric("Producido (t)", "%.2f" % (base["real_kg"].fillna(0).sum() / 1000.0))
    k3.metric("Sin Final cargado", int((base["real_kg"].fillna(0) <= 0).sum()))
    k4.metric("Sin lab", int(base["fuente_lab"].isna().sum()))

    _tabla(USR, cat, conectar, base)

    st.divider()
    st.markdown("#### 🔎 Detalle de una reacción")
    _ops = ["%s · %s · %s · %s" % (base.iloc[i]["ident"], base.iloc[i]["producto"] or "?",
                                   base.iloc[i]["_sem"], _lab_estado(base.iloc[i]))
            for i in range(len(base))]
    _s = st.selectbox("Reacción", _ops, key="ehz_det_sel", label_visibility="collapsed")
    r = base.iloc[_ops.index(_s)]
    t1, t2 = st.tabs(["🎫 Tickets de pesada final", "🧪 Evaluación de laboratorio"])
    with t1:
        _tickets(USR, cat, conectar, r)
    with t2:
        _lab(USR, cat, conectar, r)
