"""Evaluación interna de reacciones (ARE / desgomado).
Migrado desde la sub-tab de Cargas. Se usa en Iniciar producción y (compat) en Cargas.
render(USR, cat, conectar, etapas_de_proceso, params_proceso)
"""
import json
import pandas as pd
import streamlit as st


def render(USR, cat, conectar, etapas_de_proceso, params_proceso):
    st.caption("Evaluaciones internas de reactores. **ARE**: medís acidez/temperatura/fósforo para bajar la acidez de ~60 a 10. "
               "**Desgomado acuoso**: cuando cargás **temperatura ≥ 85 °C** la reacción se corta y pasa a **reposo** (decantación).")
    df_rec2 = cat("""
        SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha,
               b.tipo_proceso, b.etapa_actual
        FROM fact_batch_proceso b
        WHERE NOT b.anulado AND b.sector='REACTORES'
          AND b.tipo_proceso IN ('PRODUCCION_ARE','DESGOMADO_ACUOSO')
        ORDER BY b.creado_en DESC LIMIT 100
    """)
    if df_rec2.empty:
        st.info("Sin reacciones de ARE ni desgomado todavía.")
    else:
        opt2 = df_rec2.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['tipo_proceso']}", axis=1).tolist()
        sel2 = st.selectbox("Reacción / ticket", opt2, key="m_sel")
        r2 = df_rec2.iloc[opt2.index(sel2)]
        tipo_actual = r2["tipo_proceso"]

        _flash = st.session_state.pop("m_flash", None)
        if _flash:
            try:
                _bf = cat("SELECT estado, ticket_producto_final, ticket_validacion_lab "
                          "FROM produccion.fact_batch_proceso WHERE id_batch=%s", (int(_flash.get("batch")),))
                _ef = _bf.iloc[0]["estado"] if not _bf.empty else None
                _tpf = _bf.iloc[0]["ticket_producto_final"] if not _bf.empty else None
                _tvl = _bf.iloc[0]["ticket_validacion_lab"] if not _bf.empty else None
            except Exception:
                _ef = _tpf = _tvl = None
            st.success(f"✅ Evaluación interna #{_flash.get('id')} guardada. Podés cargar otra.")
            if _ef == "REPOSO" and _tpf:
                st.warning(f"🟦 Acidez ≤ 10 → la reacción pasó a **REPOSO**. "
                           f"🎫 Ticket de producto final: **{_tpf}** (a evaluar en laboratorio). "
                           f"Validación con ticket MP **{_tvl or '—'}**.")
            elif _ef == "REPOSO":
                st.warning("🟦 Temperatura ≥ 85 °C → el desgomado **cortó la reacción y pasó a REPOSO**. "
                           "En decantación vas a separar **fondo de tanque** y **AFE-S**.")

        # ---------- Cronograma de evaluación (definido al iniciar la carga) ----------
        id_prog_sel = None
        _prog = cat("SELECT id_prog, secuencia, etapa, programado_ts, estado, id_eval "
                    "FROM produccion.fact_eval_programada WHERE id_batch=%s ORDER BY secuencia",
                    (int(r2["id_batch"]),))
        if not _prog.empty:
            st.markdown("##### 🗓️ Cronograma de evaluación de esta reacción")
            _nowp = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires")
            _pts = pd.to_datetime(_prog["programado_ts"], errors="coerce")
            try:
                _pts = _pts.dt.tz_convert("America/Argentina/Buenos_Aires")
            except Exception:
                pass
            _etq_lbl = {"ARMADO": "Armado", "REACCION": "Reacción", "REPOSANDO": "Reposo",
                        "DECANTACION": "Decantación", "EN_TANQUE": "Acopio final"}

            def _est_prog(i):
                r = _prog.iloc[i]
                ts = _pts.iloc[i]
                if pd.notna(r["id_eval"]) or str(r["estado"]).upper() == "REALIZADA":
                    return "✅ realizada"
                if pd.isna(ts):
                    return "⏳ pendiente"
                _dm = (ts - _nowp).total_seconds() / 60.0
                if _dm < -15:
                    return f"🔴 vencida · hace {abs(_dm)/60:.1f} h" if abs(_dm) >= 60 else f"🔴 vencida · hace {abs(_dm):.0f} min"
                if _dm <= 30:
                    return "🟡 le toca AHORA"
                return f"⏳ en {_dm/60:.1f} h" if _dm >= 60 else f"⏳ en {_dm:.0f} min"

            _ev_disp = pd.DataFrame({
                "Muestra": _prog["secuencia"].map(lambda x: f"#{int(x)}"),
                "Hora programada": _pts.dt.strftime("%d/%m %H:%M"),
                "Etapa": _prog["etapa"].map(lambda c: _etq_lbl.get(c, c)),
                "Estado": [_est_prog(i) for i in range(len(_prog))],
            })
            _selev = st.dataframe(_ev_disp, use_container_width=True, hide_index=True,
                                  on_select="rerun", selection_mode="single-row",
                                  key=f"m_prog_{int(r2['id_batch'])}")
            _rows_sel = []
            try:
                _rows_sel = list((_selev.get("selection", {}) or {}).get("rows", []))
            except Exception:
                _rows_sel = []
            _pendientes = [i for i in range(len(_prog))
                           if pd.isna(_prog.iloc[i]["id_eval"]) and str(_prog.iloc[i]["estado"]).upper() != "REALIZADA"]
            if _rows_sel:
                _i = _rows_sel[0]
                _pr = _prog.iloc[_i]
                if _i in _pendientes:
                    id_prog_sel = int(_pr["id_prog"])
                    st.session_state[f"m_etapa_{int(r2['id_batch'])}"] = (_pr["etapa"] if _pr["etapa"] else None) or st.session_state.get(f"m_etapa_{int(r2['id_batch'])}")
                    st.info(f"🎯 Estás cargando la **muestra programada #{int(_pr['secuencia'])}** "
                            f"({_etq_lbl.get(_pr['etapa'], _pr['etapa'])} · {_ev_disp.iloc[_i]['Hora programada']}). "
                            "Al guardar queda tildada ✅ en el cronograma.")
                else:
                    st.warning(f"La muestra #{int(_pr['secuencia'])} ya está ✅ realizada: "
                               "lo que guardes ahora entra como muestra extra (sin vincular).")
            elif _pendientes:
                _np = _prog.iloc[_pendientes[0]]
                st.caption(f"👉 Próxima programada: **#{int(_np['secuencia'])} · "
                           f"{_ev_disp.iloc[_pendientes[0]]['Hora programada']} · "
                           f"{_etq_lbl.get(_np['etapa'], _np['etapa'])}** — "
                           "tocá esa fila en la tabla para vincular la muestra que vas a cargar.")
            else:
                st.success("✅ Cronograma completo: todas las muestras programadas están realizadas. "
                           "Podés cargar muestras extra igual.")
        else:
            st.caption("Esta reacción no tiene cronograma de evaluación (se genera al Iniciar producción). "
                       "Las muestras se cargan sueltas, como siempre.")

        _et_lbl_r = {"ARMADO": "Armado", "REACCION": "Reacción", "REPOSANDO": "Reposo",
                     "DECANTACION": "Decantación", "EN_TANQUE": "Acopio final"}
        _et_eval = etapas_de_proceso(tipo_actual)
        _et_eval_codes = [c for c in _et_eval["etapa"].tolist() if c != "CARGA"]
        if not _et_eval_codes:
            _et_eval_codes = ["REACCION"]
        _cur_et = r2["etapa_actual"] if r2["etapa_actual"] in _et_eval_codes else _et_eval_codes[0]
        _k_et = f"m_etapa_{int(r2['id_batch'])}"
        if st.session_state.get(_k_et) not in _et_eval_codes:
            st.session_state.pop(_k_et, None)
        etapa_m = st.selectbox(
            "Etapa de la muestra (por defecto, la etapa actual de la reacción)",
            _et_eval_codes, index=_et_eval_codes.index(_cur_et),
            format_func=lambda c: _et_lbl_r.get(c, c),
            key=f"m_etapa_{int(r2['id_batch'])}",
        )
        st.caption(f"Etapa actual de la reacción: **{_et_lbl_r.get(r2['etapa_actual'], r2['etapa_actual'] or '—')}**")
        aplicables_m = params_proceso[params_proceso["aplica_a"].apply(
            lambda lst: tipo_actual in (lst if isinstance(lst, list) else [])
        )]
        med = {}
        cols_per_row = 3
        rows = [aplicables_m.iloc[i:i+cols_per_row] for i in range(0, len(aplicables_m), cols_per_row)]
        for row in rows:
            cs = st.columns(cols_per_row)
            for j, (_, p) in enumerate(row.iterrows()):
                v = cs[j].number_input(
                    f"{p['descripcion']} ({p['unidad']})",
                    min_value=0.0, max_value=1_000_000.0, step=0.1,
                    key=f"m_par_{p['codigo']}"
                )
                if v > 0:
                    med[p["codigo"]] = float(v)
        obs_m = st.text_input("Observación de la muestra", max_chars=200, key="m_obs")
        if st.button("🧪 Guardar muestra", type="primary", use_container_width=True, key="m_save"):
            if not med:
                st.error("Ingresá al menos una medición.")
            else:
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO fact_evaluacion_interna
                                (id_batch, etapa, mediciones, observaciones, id_usuario)
                                VALUES (%s,%s,%s::jsonb,%s,%s) RETURNING id_eval
                            """, (int(r2["id_batch"]), etapa_m, json.dumps(med), obs_m or None, int(USR["id_usuario"])))
                            id_m = cur.fetchone()[0]
                            if id_prog_sel:
                                cur.execute("UPDATE produccion.fact_eval_programada "
                                            "SET estado='REALIZADA', id_eval=%s WHERE id_prog=%s",
                                            (int(id_m), int(id_prog_sel)))
                        audit.insert("fact_evaluacion_interna", id_m, med)
                    st.session_state["m_flash"] = {"id": int(id_m), "batch": int(r2["id_batch"])}
                    cat.clear()
                    st.rerun()
                except Exception as e:
                    st.exception(e)

        st.divider()
        try:
            _bst = cat("SELECT estado, etapa_actual, ticket_producto_final "
                       "FROM produccion.fact_batch_proceso WHERE id_batch=%s", (int(r2["id_batch"]),))
            _estx = _bst.iloc[0]["estado"] if not _bst.empty else "—"
            _etx = _bst.iloc[0]["etapa_actual"] if not _bst.empty else "—"
            _tpfx = _bst.iloc[0]["ticket_producto_final"] if not _bst.empty else None
        except Exception:
            _estx = _etx = "—"; _tpfx = None
        _sm1, _sm2, _sm3 = st.columns(3)
        _sm1.metric("Estado de la reacción", _estx or "—")
        _sm2.metric("Etapa actual", _etx or "—")
        _sm3.metric("Ticket prod. final", _tpfx or "—")
        _evs = cat("""
            SELECT id_eval AS id, to_char(ts,'DD/MM HH24:MI') AS hora, etapa,
                   (mediciones->>'acidez')::numeric AS acidez,
                   (mediciones->>'temperatura')::numeric AS temperatura,
                   (mediciones->>'fosforo')::numeric AS fosforo,
                   (mediciones->>'azufre')::numeric AS azufre
            FROM produccion.fact_evaluacion_interna
            WHERE id_batch=%s AND NOT anulado ORDER BY ts DESC
        """, (int(r2["id_batch"]),))
        st.markdown("**🧪 Evaluaciones de esta reacción**")
        if _evs.empty:
            st.caption("Todavía no hay evaluaciones para esta reacción.")
        else:
            st.dataframe(_evs, hide_index=True, use_container_width=True)
