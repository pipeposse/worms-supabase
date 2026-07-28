"""Editor masivo de horarios y TN finales de reacciones terminadas.

Era el bloque que vivía en `performance_section.py` (módulo hoy desconectado del
menú). Se traslada acá para que viva dentro del Centro de Planificación, en
⚙️ Administrar en curso → 🛠️ Gestión de reacciones → ⏱️ Horarios & TN finales.

Qué edita, en una sola tabla, para TODAS las reacciones finalizadas:
  - Inicio real de reacción  → fact_batch_estado_log (REACCION) + fact_batch_proceso.inicio_ts
                               + fact_etapa_evento (etapa REACCION)
  - Fin de reacción real     → fact_batch_estado_log (REPOSO). Es el fin que usa el
                               desvío vs cronograma, NO el fin de acopio.
  - Final (TN) a mano        → fact_reaccion_cierre (metodo = 'EDITOR_MANUAL').
                               Pisa lo que venga de tickets / kg_obtenido.
  - Tanque de acopio final   → fact_batch_proceso (id_tanque_are_final o
                               desg_id_tanque_destino según el tipo de proceso).

La columna "Origen" muestra de dónde sale hoy el kg real: cierre manual, tickets
de pesada, kg_obtenido o nada. Así se ve de un vistazo qué reacción está
apoyada en tickets y cuál en una carga a mano.
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
    "vt.tickets_kg, vt.kg_obtenido, vt.real_asignado_kg, vt.real_metodo "
    "FROM produccion.v_perf_reaccion p "
    "LEFT JOIN produccion.v_reaccion_terminada vt ON vt.id_batch = p.id_batch "
    "ORDER BY p.fecha DESC NULLS LAST, p.id_batch DESC")


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


def render(USR, cat, conectar):
    st.caption(
        "Corregí **inicio de reacción, fin de reacción (pase a reposo), Final (TN) real y tanque "
        "de acopio** de todas las finalizadas en una sola tabla. 📐 El fin que se edita acá es el "
        "**fin de reacción** — es el que usa el desvío vs cronograma; el fin real de acopio se "
        "sumará más adelante. El **Final (TN)** que cargues acá se guarda como cierre manual y "
        "**pisa** lo que hubieran dado los tickets de pesada o el kg_obtenido: mirá la columna "
        "*Origen* para saber sobre qué estás escribiendo.")

    _puede = str(USR.get("rol") or "") in ROLES_DIRECCION
    df = cat(SQL_BASE)
    if df is None or df.empty:
        st.info("No hay reacciones finalizadas para editar.")
        return

    df = df.copy()
    df["inicio"] = pd.to_datetime(df["inicio"], errors="coerce")
    df["fin"] = pd.to_datetime(df["fin"], errors="coerce")
    for _c in ("prog_h", "mp_kg", "real_kg", "tickets_kg", "kg_obtenido", "real_asignado_kg"):
        if _c in df.columns:
            df[_c] = pd.to_numeric(df[_c], errors="coerce")

    # ---------- filtros ----------
    f1, f2, f3 = st.columns([1, 1, 1.4])
    _tipos = ["Todos"] + sorted([str(x) for x in df["tipo"].dropna().unique().tolist()])
    _tipo = f1.selectbox("Tipo de reacción", _tipos, key="ehz_f_tipo")
    _reac = ["Todos"] + sorted([str(x) for x in df["reactor"].dropna().unique().tolist()])
    _rx = f2.selectbox("Reactor", _reac, key="ehz_f_reactor")
    _prods_f = sorted([str(x) for x in df["producto"].dropna().unique().tolist()])
    _selp = f3.multiselect("Producto final", _prods_f, default=_prods_f, key="ehz_f_prod")
    if _tipo != "Todos":
        df = df[df["tipo"].astype(str) == _tipo]
    if _rx != "Todos":
        df = df[df["reactor"].astype(str) == _rx]
    if _selp:
        df = df[df["producto"].astype(str).isin(_selp) | df["producto"].isna()]
    _solo_sin = st.checkbox("Solo las que no tienen Final (TN) cargado", value=False, key="ehz_f_sin")
    if _solo_sin:
        df = df[df["real_kg"].fillna(0) <= 0]
    if df.empty:
        st.info("No hay reacciones finalizadas con esos filtros.")
        return
    base = df.reset_index(drop=True)

    # ---------- tanques habilitados para los productos finales presentes ----------
    _prods = sorted({int(x) for x in base["id_producto"].dropna().tolist()})
    _tk = None
    if _prods:
        _tk = cat("SELECT tp.id_producto, dp.codigo_producto, t.id_tanque, "
                  "COALESCE(NULLIF(t.nombre,''), t.codigo) AS tanque, t.codigo "
                  "FROM produccion.dim_tanque_producto tp "
                  "JOIN produccion.dim_tanque t ON t.id_tanque = tp.id_tanque AND COALESCE(t.activo, TRUE) "
                  "JOIN produccion.dim_producto dp ON dp.id_producto = tp.id_producto "
                  "WHERE tp.id_producto = ANY(%s) ORDER BY dp.codigo_producto, t.nombre", (_prods,))
    lbl2tk = {}      # etiqueta visible -> (id_tanque, id_producto, nombre, codigo)
    tk2lbl = {}      # (id_producto, id_tanque) -> etiqueta
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
            # tanque asignado que hoy no figura habilitado para el producto: mostrarlo igual
            _n = cat("SELECT COALESCE(NULLIF(nombre,''), codigo) AS n, codigo "
                     "FROM produccion.dim_tanque WHERE id_tanque=%s", (int(r["id_tanque_destino"]),))
            if _n is not None and not _n.empty:
                _l = "⚠️ %s · %s (no habilitado)" % (r["producto"] or "?", _n.iloc[0]["n"])
                lbl2tk.setdefault(_l, (int(r["id_tanque_destino"]),
                                       (_idp if _idp is not None else -1),
                                       str(_n.iloc[0]["n"]), str(_n.iloc[0]["codigo"] or "")))
        return _l

    base["tk_lbl"] = base.apply(_lbl_actual, axis=1)
    _opciones = sorted(lbl2tk.keys())

    view = pd.DataFrame({
        "ID": base["ident"],
        "Reacción": base["etiqueta"],
        "Producto": base["producto"],
        "MP (TN)": (base["mp_kg"] / 1000.0).round(2),
        "Final (TN)": (base["real_kg"] / 1000.0).round(2),
        "Origen": [_origen(base.iloc[i]) for i in range(len(base))],
        "Tickets (TN)": (base["tickets_kg"] / 1000.0).round(2),
        "Inicio real": base["inicio"],
        "Fin reacción real": base["fin"],
        "Programado (h)": base["prog_h"],
        "Real (h)": ((base["fin"] - base["inicio"]).dt.total_seconds() / 3600.0).round(1),
        "Tanque final": base["tk_lbl"],
    })
    view["Δ (h)"] = (view["Real (h)"] - view["Programado (h)"]).round(1)
    view = view[["ID", "Reacción", "Producto", "MP (TN)", "Final (TN)", "Origen", "Tickets (TN)",
                 "Inicio real", "Fin reacción real", "Programado (h)", "Real (h)", "Δ (h)",
                 "Tanque final"]]

    _bloq = ["ID", "Reacción", "Producto", "MP (TN)", "Origen", "Tickets (TN)",
             "Programado (h)", "Real (h)", "Δ (h)"]
    if not _puede:
        _bloq = list(view.columns)
        st.info("Solo Dirección (SUPERVISOR / ADMIN) puede editar horarios y kilos finales. "
                "Abajo se muestran los valores guardados.")

    ed = st.data_editor(
        view, hide_index=True, use_container_width=True, key="ehz_edit",
        disabled=_bloq,
        column_config={
            "MP (TN)": st.column_config.NumberColumn(
                format="%.2f", help="Materia prima cargada al reactor."),
            "Final (TN)": st.column_config.NumberColumn(
                format="%.2f", min_value=0.0, step=0.01,
                help="Producto final real en TN — EDITABLE. Se guarda como cierre manual "
                     "(metodo EDITOR_MANUAL) y pisa tickets/kg_obtenido. Vacío = sin real."),
            "Origen": st.column_config.TextColumn(
                "Origen", help="De dónde sale hoy el kg real: ✍️ carga a mano · 🎫 tickets de "
                               "pesada · 🛢️ variación de tanque asociada · 📐 kg_obtenido "
                               "calculado · sin real."),
            "Tickets (TN)": st.column_config.NumberColumn(
                format="%.2f", help="Suma de los tickets de pesada finales cargados para esta "
                                    "reacción. Si cargás Final (TN) distinto, este número queda "
                                    "como referencia pero deja de usarse."),
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

    if not _puede:
        return

    # ---------- detectar cambios ----------
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

    if st.button("💾 Guardar cambios", type="primary", key="ehz_save", disabled=(not cambios)):
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
                            # fin de REACCIÓN = pase a REPOSO (el fin real de acopio va aparte)
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
