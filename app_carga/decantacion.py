"""Decantación de PRODUCCION_ARE.
Tres paneles que comparten datos del batch:
  - destinos(...)      → Centro de Planificación: elegir destino de glicerina recuperada
                         (cónico 20-2 / Minion / 20-1) y destino final del ARE (export recomendado).
  - produccion(...)    → Producción en planta: prueba de solubilidad (¿el material purgado flota?),
                         envío de muestra a lab, ver purga/ticket, confirmar + generar movimientos.
  - laboratorio(...)   → Laboratorio: ver producciones en marcha que requieren evaluación y cargar
                         el % de glicerina del purgado (≤2% = purga OK) y azufre/fósforo del final.
Corta cuando glicerina del purgado ≤ 2%. Recomienda exportación si azufre y fósforo < 200.
"""
import json
import pandas as pd
import streamlit as st

REPOSO_DECANT = ("REPOSO", "DECANTACION")
GLI_RECUP_TANQUES = (88, 87, 81)   # cónico 20-2, cónico 20-1, Minion
PURGA_CORTE = 2.0                  # glicerina <= 2% => purga OK
SP_EXPORT = 200.0                  # azufre y fósforo < 200 => apto exportación


def _purga_corte(cat):
    """Umbral de purga (glicerina máx) leído de Condicionales; fallback al default."""
    try:
        _d = cat("SELECT valor FROM produccion.dic_condicion_produccion WHERE clave='ARE_PURGA_GLICERINA_MAX'")
        if _d is not None and not _d.empty and pd.notna(_d.iloc[0]["valor"]):
            return float(_d.iloc[0]["valor"])
    except Exception:
        pass
    return PURGA_CORTE


def _batches(cat):
    return cat(
        "SELECT b.id_batch, b.identificador_unidad AS ident, b.estado, b.etapa_actual, "
        "       bu.nombre_ui AS reactor, bu.reposo_horas, "
        "       b.id_tanque_gli_recup, b.id_tanque_are_final, "
        "       b.ticket_producto_final, b.ticket_validacion_lab, "
        "       b.solubilidad_flota, b.purga_glicerina_pct, b.purga_ok, "
        "       b.parametros_proceso, b.id_producto_buscado, "
        "       (SELECT inicio_ts FROM produccion.fact_etapa_evento e "
        "          WHERE e.id_batch=b.id_batch AND e.etapa='REPOSANDO' "
        "          ORDER BY e.inicio_ts DESC LIMIT 1) AS reposo_ini "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "WHERE b.tipo_proceso='PRODUCCION_ARE' AND b.estado IN ('REPOSO','DECANTACION') "
        "  AND COALESCE(b.anulado,false)=false AND b.decant_confirmada_ts IS NULL "
        "ORDER BY b.creado_en DESC")


def _batch_one(cat, id_batch):
    df = cat(
        "SELECT b.id_batch, b.identificador_unidad AS ident, b.estado, b.etapa_actual, "
        "       bu.nombre_ui AS reactor, bu.reposo_horas, "
        "       b.id_tanque_gli_recup, b.id_tanque_are_final, "
        "       b.ticket_producto_final, b.ticket_validacion_lab, "
        "       b.solubilidad_flota, b.purga_glicerina_pct, b.purga_ok, "
        "       b.parametros_proceso, b.id_producto_buscado, "
        "       (SELECT inicio_ts FROM produccion.fact_etapa_evento e "
        "          WHERE e.id_batch=b.id_batch AND e.etapa='REPOSANDO' "
        "          ORDER BY e.inicio_ts DESC LIMIT 1) AS reposo_ini "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "WHERE b.id_batch=%s", (int(id_batch),))
    return df.iloc[0] if (df is not None and not df.empty) else None


def _params(b):
    p = b.get("parametros_proceso") or {}
    if isinstance(p, str):
        try: p = json.loads(p)
        except Exception: p = {}
    return p or {}


def _reposo_eta(b):
    ini = b.get("reposo_ini"); hs = b.get("reposo_horas")
    if pd.isna(ini) or ini is None or hs is None:
        return None
    try:
        return pd.to_datetime(ini) + pd.Timedelta(hours=float(hs))
    except Exception:
        return None


def _sel_batch(cat, key):
    df = _batches(cat)
    if df is None or df.empty:
        st.info("No hay producciones ARE en reposo/decantación.")
        return None, None
    opt = df.apply(lambda r: f"#{r['id_batch']} · {r['ident'] or '—'} · {r['reactor'] or '—'} · {r['estado']}", axis=1).tolist()
    s = st.selectbox("Producción ARE", opt, key=key)
    return df.iloc[opt.index(s)], df


def _cabecera(b):
    eta = _reposo_eta(b)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estado", b["estado"])
    c2.metric("Reactor", b["reactor"] or "—")
    if eta is not None:
        _now = pd.Timestamp.now(tz=getattr(eta, "tz", None))
        _rest = (eta - _now).total_seconds()/3600.0
        c3.metric("Fin de reposo", eta.strftime("%d/%m %H:%M"),
                  ("listo" if _rest <= 0 else f"en {_rest:.1f} h"))
    else:
        c3.metric("Fin de reposo", "—")
    c4.metric("Ticket producto final", b["ticket_producto_final"] or "—")
    if b["ticket_producto_final"]:
        st.info(f"🎫 **Ticket de producto final: {b['ticket_producto_final']}** — visible para todos "
                "(laboratorio centrifuga y evalúa).")


def _tanques(cat, ids):
    return cat(
        "SELECT t.id_tanque, t.nombre, t.codigo, COALESCE(s.litros_actual,0) lt, "
        "       COALESCE(s.kg_actual,0) kg, COALESCE(t.capacidad_litros,0) cap "
        "FROM produccion.dim_tanque t "
        "LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
        "WHERE t.id_tanque = ANY(%s) ORDER BY t.nombre", (list(ids),))


# ---------------------------------------------------------------- PLANIFICACIÓN
def destinos(USR, cat, conectar):
    st.subheader("🧴 Decantación ARE — destinos (dirección)")
    st.caption("Cuando la acidez llegó a ≤13 la reacción pasó a reposo y luego a decantación. "
               "Elegí a qué tanque va la **glicerina recuperada** (purga) y el **destino final del ARE**.")
    b, _ = _sel_batch(cat, "dec_dest_sel")
    if b is None:
        return
    _cabecera(b)
    uid = int(USR["id_usuario"])

    if b["estado"] == "REPOSO":
        if st.button("▶️ Pasar a decantación", type="primary", key="dec_to_decant"):
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur:
                        cur.execute("UPDATE produccion.fact_etapa_evento SET fin_ts=now() "
                                    "WHERE id_batch=%s AND fin_ts IS NULL", (int(b["id_batch"]),))
                        cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch,etapa,inicio_ts,id_usuario) "
                                    "VALUES (%s,'DECANTACION',now(),%s)", (int(b["id_batch"]), uid))
                        cur.execute("UPDATE produccion.fact_batch_proceso SET estado='DECANTACION', "
                                    "etapa_actual='DECANTACION', id_usuario_estado=%s, "
                                    "motivo_estado='Inicio de decantación' WHERE id_batch=%s", (uid, int(b["id_batch"])))
                    audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"estado": "DECANTACION"})
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)

    # ---- Producto producido + parámetros de laboratorio (para decidir el destino) ----
    p = _params(b)
    _are_kg = float(p.get("are_objetivo_kg") or 0)
    _lit_gli = float(p.get("litros_glicerina_total") or 0)
    _aporte = float(p.get("aporte_glicerina_pct") or 10)
    _gli_recup_l = (1 - _aporte / 100.0) * _lit_gli
    _le = None
    if b["ticket_producto_final"]:
        try:
            _le = cat("SELECT calidad_final_lab, rechazado, prc_acidez, prc_hkf, prc_sedimentos, "
                      "ppm_azufre, ppm_fosforo, densidad__g_ml, prc_glicerina, color, to_char(fecha,'DD/MM HH24:MI') fecha "
                      "FROM produccion.v_procesos_lab_efectivo WHERE ticket=%s ORDER BY fecha DESC NULLS LAST LIMIT 1",
                      (str(b["ticket_producto_final"]),))
        except Exception:
            _le = None
    st.markdown("##### 📦 ARE producido (evaluado por laboratorio)")
    _a1, _a2, _a3 = st.columns(3)
    _a1.metric("ARE producido", f"{_are_kg/0.88:,.0f} L", f"{_are_kg:,.0f} kg")
    if _le is not None and not _le.empty:
        _r = _le.iloc[0]
        _a2.metric("Calidad final", str(_r["calidad_final_lab"] or "—"))
        _a3.metric("Resultado lab", str(_r["rechazado"] or "—"))
        _par = {"Acidez %": _r["prc_acidez"], "HKF %": _r["prc_hkf"], "Sedim. %": _r["prc_sedimentos"],
                "Azufre ppm": _r["ppm_azufre"], "Fósforo ppm": _r["ppm_fosforo"],
                "Densidad": _r["densidad__g_ml"], "Color": _r["color"]}
        _par = {k: v for k, v in _par.items() if v is not None and str(v).strip() != ""}
        if _par:
            st.dataframe(pd.DataFrame([_par]), use_container_width=True, hide_index=True)
        st.caption(f"Evaluado por laboratorio · {_r['fecha']}. Guía: azufre y fósforo < {SP_EXPORT:.0f} ppm = apto exportación.")
    else:
        _a2.metric("Calidad final", "—")
        st.caption(f"Laboratorio todavía no evaluó el producto final (ticket {b['ticket_producto_final'] or '—'}).")
    st.markdown("##### 🟡 Glicerina recuperada producida")
    _g1, _g2 = st.columns(2)
    _g1.metric("Glicerina recuperada", f"{_gli_recup_l:,.0f} L", f"{100 - _aporte:.0f}% de la cargada")
    _g2.metric("Glicerina del purgado (lab)",
               f"{float(b['purga_glicerina_pct']):.1f}%" if pd.notna(b["purga_glicerina_pct"]) else "—")

    st.markdown("##### 🟡 Destino de la glicerina recuperada (purga)")
    gt = _tanques(cat, GLI_RECUP_TANQUES)
    if gt is None or gt.empty:
        st.warning("No se encontraron los tanques de glicerina recuperada (20-2 / 20-1 / Minion).")
        dest_gli = None
    else:
        cols = st.columns(len(gt))
        for i, (_, r) in enumerate(gt.iterrows()):
            _pct = (float(r["lt"])/float(r["cap"])*100) if r["cap"] else 0
            cols[i].metric(r["nombre"], f"{float(r['lt']):,.0f} L", f"{_pct:.0f}% lleno · {float(r['kg']):,.0f} kg")
        gop = gt.apply(lambda r: f"{r['nombre']} · {float(r['lt']):,.0f} L disp.", axis=1).tolist()
        _cur = b["id_tanque_gli_recup"]
        _ix = next((i for i, (_, r) in enumerate(gt.iterrows()) if int(r["id_tanque"]) == (int(_cur) if pd.notna(_cur) else -1)), 0)
        gsel = st.selectbox("Tanque destino (elegí por stock disponible)", gop, index=_ix, key="dec_gli_tk")
        dest_gli = int(gt.iloc[gop.index(gsel)]["id_tanque"])

    st.markdown("##### 🎯 Tanque destino del ARE final")
    _buscado = b.get("id_producto_buscado")
    _bid = int(_buscado) if pd.notna(_buscado) else -1
    ft = cat(
        "SELECT t.id_tanque, t.nombre, t.codigo, t.sector, COALESCE(p.codigo_producto,'') AS prod, "
        "       COALESCE(s.litros_actual,0) lt, COALESCE(t.capacidad_litros,0) cap "
        "FROM produccion.dim_tanque t "
        "LEFT JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
        "LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
        "WHERE COALESCE(t.activo,true) AND ( "
        "   t.id_producto_principal=%s "
        "   OR p.codigo_producto ILIKE 'ARE%%' "
        "   OR EXISTS (SELECT 1 FROM produccion.dim_tanque_producto_permitido pp "
        "              JOIN produccion.dim_producto p2 ON p2.id_producto=pp.id_producto "
        "              WHERE pp.id_tanque=t.id_tanque AND (pp.id_producto=%s OR p2.codigo_producto ILIKE 'ARE%%')) "
        "   OR t.sector ILIKE 'Exporta%%' OR t.codigo='FORM-AG-E') "
        "ORDER BY (t.id_producto_principal=%s) DESC, (t.sector ILIKE '%%Acopio%%') DESC, "
        "         (t.sector ILIKE 'Exporta%%') ASC, t.nombre",
        (_bid, _bid, _bid))
    if ft is None or ft.empty:
        st.warning("No hay tanques destino para ese ARE.")
        dest_fin = None
    else:
        fop = ft.apply(lambda r: f"{r['nombre']} · {r['prod'] or '—'} · {r['sector']} · {float(r['lt']):,.0f}/{float(r['cap']):,.0f} L", axis=1).tolist()
        _curf = b["id_tanque_are_final"]
        _ixf = next((i for i, (_, r) in enumerate(ft.iterrows()) if int(r["id_tanque"]) == (int(_curf) if pd.notna(_curf) else -1)), 0)
        fsel = st.selectbox("Tanque destino del ARE final", fop, index=_ixf, key="dec_fin_tk")
        dest_fin = int(ft.iloc[fop.index(fsel)]["id_tanque"])

    if st.button("💾 Guardar destinos", type="primary", use_container_width=True, key="dec_save_dest"):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_batch_proceso "
                                "SET id_tanque_gli_recup=%s, id_tanque_are_final=%s WHERE id_batch=%s",
                                (dest_gli, dest_fin, int(b["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(b["id_batch"]),
                          {"gli_recup": dest_gli, "are_final": dest_fin})
            st.success("Destinos guardados.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


# ---------------------------------------------------------------- PRODUCCIÓN
def produccion(USR, cat, conectar, id_batch=None):
    st.header("🧴 Decantación (purga ARE)")
    st.caption("Durante la decantación hacés la **prueba de solubilidad**: si el material purgado **flota**, "
               "ese proceso terminó. Mandás muestra a laboratorio: corta cuando la glicerina del purgado es ≤ 2%.")
    if id_batch is not None:
        b = _batch_one(cat, int(id_batch))
        if b is None:
            st.info("No se encontró la producción.")
            return
    else:
        b, _ = _sel_batch(cat, "dec_prod_sel")
        if b is None:
            return
    _cabecera(b)
    uid = int(USR["id_usuario"])

    # destinos elegidos por dirección
    dg = b["id_tanque_gli_recup"]; df_ = b["id_tanque_are_final"]
    nt = cat("SELECT id_tanque, nombre FROM produccion.dim_tanque WHERE id_tanque = ANY(%s)",
             ([int(x) for x in (dg, df_) if pd.notna(x)] or [-1],))
    _nm = {int(r["id_tanque"]): r["nombre"] for _, r in nt.iterrows()} if (nt is not None and not nt.empty) else {}
    d1, d2 = st.columns(2)
    d1.metric("Destino glicerina recuperada", _nm.get(int(dg)) if pd.notna(dg) else "— (lo define dirección)")
    d2.metric("Destino final ARE", _nm.get(int(df_)) if pd.notna(df_) else "— (lo define dirección)")

    st.markdown("##### 🧪 Prueba de solubilidad")
    st.caption("Criterio de observación: **¿el material purgado flota?**")
    cflo, cno = st.columns(2)
    if cflo.button("✅ Sí, flota (proceso terminado)", use_container_width=True, key="dec_flota_si"):
        _set_flota(USR, cat, conectar, int(b["id_batch"]), True)
        st.rerun()
    if cno.button("❌ No flota (seguir)", use_container_width=True, key="dec_flota_no"):
        _set_flota(USR, cat, conectar, int(b["id_batch"]), False)
        st.rerun()
    _sh = cat("SELECT to_char(ts,'DD/MM HH24:MI') AS \"Hora\", "
              "CASE WHEN flota THEN 'Flota ✅ (terminado)' ELSE 'No flota' END AS \"Resultado\" "
              "FROM produccion.fact_decant_solubilidad WHERE id_batch=%s ORDER BY ts DESC", (int(b["id_batch"]),))
    if _sh is not None and not _sh.empty:
        st.caption("Historial de pruebas de solubilidad (con horario):")
        st.dataframe(_sh, use_container_width=True, hide_index=True)

    if st.button("📤 Enviar muestra de purga a laboratorio", key="dec_envio_lab"):
        st.success("Muestra de purga marcada para laboratorio. La verás en la sección Laboratorio "
                   "(carga el % de glicerina; corta en ≤ 2%).")

    st.markdown("##### 🔬 Resultado de laboratorio (purga)")
    gp = b["purga_glicerina_pct"]
    _corte = _purga_corte(cat)
    if pd.isna(gp) or gp is None:
        st.caption("Laboratorio todavía no cargó el % de glicerina del material purgado.")
    elif bool(b["purga_ok"]):
        st.success(f"✅ Última purga **{float(gp):.1f}% (≤ {_corte:g}%)** → **purga OK**. Podés confirmar y enviar a destino.")
    else:
        st.warning(f"🔴 Última purga **{float(gp):.1f}% (> {_corte:g}%)** → **seguí decantando**.")
    _ph = cat("SELECT to_char(ts,'DD/MM HH24:MI') AS \"Hora\", glicerina_pct AS \"Glicerina %%\", "
              "CASE WHEN purga_ok THEN 'Purga OK ✅' ELSE 'Seguir' END AS \"Resultado\" "
              "FROM produccion.fact_decant_purga WHERE id_batch=%s ORDER BY ts DESC", (int(b["id_batch"]),))
    if _ph is not None and not _ph.empty:
        st.caption("Historial de evaluaciones de purga (laboratorio, con horario):")
        st.dataframe(_ph, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("##### ✅ Confirmar decantación y enviar a destino")
    if not bool(b["purga_ok"]):
        st.info("Disponible cuando laboratorio confirme purga OK (≤ 2%).")
        return
    if pd.isna(dg) or pd.isna(df_):
        st.warning("Falta que dirección defina los tanques destino (glicerina recuperada y ARE final).")
        return
    p = _params(b)
    _are_kg = float(p.get("are_objetivo_kg") or 0)
    _lit_gli_tot = float(p.get("litros_glicerina_total") or 0)
    _aporte = float(p.get("aporte_glicerina_pct") or 10)
    l_are = _are_kg / 0.88
    l_gli = (1.0 - _aporte / 100.0) * _lit_gli_tot
    cc1, cc2 = st.columns(2)
    cc1.metric("Glicerina recuperada → " + (_nm.get(int(dg)) or "destino"),
               f"{l_gli:,.0f} L", f"{100 - _aporte:.0f}% de {_lit_gli_tot:,.0f} L cargados")
    cc2.metric("ARE final → " + (_nm.get(int(df_)) or "destino"),
               f"{l_are:,.0f} L", f"{_are_kg:,.0f} kg (fórmula)")
    st.caption("Calculado por la fórmula: ARE = AG-C − agua(AG-C, lab) + aporte%·L glicerina · "
               "glicerina recuperada = (100−aporte)%·L glicerina cargada.")
    if st.button("🚚 Confirmar y generar movimientos de stock", type="primary", use_container_width=True, key="dec_confirm"):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto='GLICERINA-RECUP'")
                    _r = cur.fetchone(); id_gli = _r[0] if _r else None
                    cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto='ARE-B'")
                    _r = cur.fetchone(); id_are = _r[0] if _r else None
                    _mov(cur, b, uid, "SUBPRODUCTO", id_gli, "Glicerina recuperada", int(dg), l_gli, 1.05)
                    _mov(cur, b, uid, "PRODUCTO_FINAL", id_are, "ARE-B", int(df_), l_are, 0.88)
                    cur.execute("UPDATE produccion.fact_etapa_evento SET fin_ts=now() WHERE id_batch=%s AND fin_ts IS NULL",
                                (int(b["id_batch"]),))
                    cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch,etapa,inicio_ts,fin_ts,id_usuario) "
                                "VALUES (%s,'EN_TANQUE',now(),now(),%s)", (int(b["id_batch"]), uid))
                    cur.execute("UPDATE produccion.fact_batch_proceso SET estado='FINALIZADO', etapa_actual='EN_TANQUE', "
                                "decant_confirmada_ts=now(), id_usuario_estado=%s, "
                                "motivo_estado='Decantación confirmada: glicerina recuperada y ARE a destino' "
                                "WHERE id_batch=%s", (uid, int(b["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"estado": "FINALIZADO"})
            st.success("Decantación confirmada. Movimientos generados y producción FINALIZADA.")
            st.balloons(); cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def _mov(cur, b, uid, rol, id_prod, prod_txt, id_tanque, litros, dens):
    if not litros or litros <= 0:
        return
    cur.execute(
        "INSERT INTO produccion.fact_movimiento_stock "
        "(momento,id_batch,identificador_prod,tipo_movimiento,rol,sentido,id_producto,producto,"
        " fuente,id_tanque,cantidad,unidad,kg,litros,id_usuario,origen,estado_mov) "
        "VALUES (now(),%s,%s,'ENTRADA',%s,1,%s,%s,'TANQUE',%s,%s,'LT',%s,%s,%s,'decantacion','EJECUTADO')",
        (int(b["id_batch"]), b["ident"], rol, id_prod, prod_txt, int(id_tanque),
         float(litros), float(litros)*float(dens), float(litros), uid))


def _set_flota(USR, cat, conectar, id_batch, flota):
    try:
        with conectar(int(USR["id_usuario"])) as (conn, audit):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO produccion.fact_decant_solubilidad (id_batch, flota, id_usuario) "
                            "VALUES (%s,%s,%s)", (int(id_batch), bool(flota), int(USR["id_usuario"])))
                cur.execute("UPDATE produccion.fact_batch_proceso SET solubilidad_flota=%s, solubilidad_ts=now() "
                            "WHERE id_batch=%s", (bool(flota), int(id_batch)))
            audit.log("I", "fact_decant_solubilidad", int(id_batch), {"flota": bool(flota)})
        cat.clear()
    except Exception as e:
        st.exception(e)


# ---------------------------------------------------------------- LABORATORIO
def laboratorio(USR, cat, conectar):
    st.subheader("🔬 Evaluaciones de producciones en marcha (ARE en decantación)")
    _corte = _purga_corte(cat)
    st.caption("Producciones que requieren evaluación de laboratorio. Cargá el **% de glicerina del material purgado** "
               f"(corta en ≤ {_corte:g}%) y, para el producto final, azufre/fósforo (apto exportación si < {SP_EXPORT:.0f}).")
    b, df = _sel_batch(cat, "dec_lab_sel")
    if b is None:
        return
    _cabecera(b)
    uid = int(USR["id_usuario"])

    st.markdown("##### 🧴 Purga: % de glicerina del material purgado")
    gp = st.number_input("% glicerina del purgado", 0.0, 100.0, value=0.0, step=0.1, key="dec_lab_gli")
    _obsp = st.text_input("Observación (opcional)", key="dec_lab_purga_obs")
    if st.button("💾 Guardar % glicerina (purga)", type="primary", key="dec_lab_save_gli"):
        ok = gp <= _corte
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO produccion.fact_decant_purga (id_batch, glicerina_pct, purga_ok, observacion, id_usuario) "
                                "VALUES (%s,%s,%s,%s,%s)", (int(b["id_batch"]), float(gp), bool(ok), (_obsp or None), uid))
                    cur.execute("UPDATE produccion.fact_batch_proceso "
                                "SET purga_glicerina_pct=%s, purga_ok=%s, purga_lab_ts=now() WHERE id_batch=%s",
                                (float(gp), bool(ok), int(b["id_batch"])))
                audit.log("I", "fact_decant_purga", int(b["id_batch"]), {"purga_pct": gp, "ok": ok})
            st.success(f"Glicerina {gp:.1f}% → " + (f"✅ purga OK (≤ {_corte:g}%)" if ok else f"🔴 seguir decantando (> {_corte:g}%)"))
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)
    _ph = cat("SELECT to_char(ts,'DD/MM HH24:MI') AS \"Hora\", glicerina_pct AS \"Glicerina %%\", "
              "CASE WHEN purga_ok THEN 'Purga OK ✅' ELSE 'Seguir' END AS \"Resultado\", "
              "COALESCE(observacion,'') AS \"Obs\" "
              "FROM produccion.fact_decant_purga WHERE id_batch=%s ORDER BY ts DESC", (int(b["id_batch"]),))
    if _ph is not None and not _ph.empty:
        st.caption("Historial de evaluaciones de purga (con horario):")
        st.dataframe(_ph, use_container_width=True, hide_index=True)

    st.markdown("##### 🎯 Evaluación del producto final (ticket " + (b["ticket_producto_final"] or "—") + ")")
    st.caption("Evaluación COMPLETA: producto, calidad y todos los parámetros. Se guarda en laboratorio "
               "(lab_evaluaciones → procesos_lab) e impacta la base total. Puede haber varias (incluidos rechazos).")
    _tkfin = b["ticket_producto_final"]
    if not _tkfin:
        st.info("Esta producción todavía no tiene ticket de producto final.")
    else:
        try:
            _cals = cat("SELECT codigo FROM produccion.dic_calidad WHERE activo ORDER BY orden")["codigo"].tolist()
        except Exception:
            _cals = ["UNICA", "A", "B", "C", "D", "E"]
        ef1, ef2, ef3, ef4 = st.columns(4)
        _pbase = ef1.selectbox("Producto base", ["ARE", "AFE", "AG"], key="dec_fin_pbase")
        _cal = ef2.selectbox("Calidad final", [""] + _cals, key="dec_fin_cal")
        _rech = ef3.selectbox("Resultado", ["ACEPTADO", "RECHAZADO", "REMUESTREO"], key="dec_fin_rech")
        _color = ef4.text_input("Color", key="dec_fin_color")
        _es_are = (_pbase == "ARE")
        if _es_are:
            st.caption("ℹ️ Para **ARE** no se miden Agua ni Hexano/impurezas; se usa **HKF**.")
        st.markdown("**Parámetros (%)**")
        q1, q2, q3, q4 = st.columns(4)
        _ac = q1.number_input("Acidez (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_ac")
        _ag = 0.0 if _es_are else q2.number_input("Agua (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_ag")
        _sed = q3.number_input("Sedimentos (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_sed")
        _prodp = q4.number_input("Producto (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_prodp")
        q5, q6, q7, q8 = st.columns(4)
        _hkf = q5.number_input("HKF (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_hkf")
        _hex = 0.0 if _es_are else q6.number_input("Hexano/imp. (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_hex")
        _gliP = q7.number_input("Glicerina (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_gliP")
        _poli = q8.number_input("Poliglicerol (%)", 0.0, 100.0, value=0.0, step=0.1, key="dec_fin_poli")
        st.markdown("**Otros**")
        r1, r2, r3, r4 = st.columns(4)
        _dens = r1.number_input("Densidad (kg/L)", 0.0, 5.0, value=0.0, step=0.001, key="dec_fin_dens")
        _az = r2.number_input("Azufre (ppm)", 0.0, 100000.0, value=0.0, step=1.0, key="dec_fin_az")
        _fo = r3.number_input("Fósforo (ppm)", 0.0, 100000.0, value=0.0, step=1.0, key="dec_fin_fo")
        _temp = r4.number_input("Temp (°C)", 0.0, 300.0, value=0.0, step=1.0, key="dec_fin_temp")
        _concl = st.text_input("Conclusión / observación", key="dec_fin_concl")
        if _az and _fo:
            if _az < SP_EXPORT and _fo < SP_EXPORT:
                st.success(f"✅ Azufre {_az:.0f} · Fósforo {_fo:.0f} (< {SP_EXPORT:.0f}) → **apto exportación**.")
            else:
                st.warning(f"Azufre {_az:.0f} · Fósforo {_fo:.0f} → no apto exportación.")
        if st.button("💾 Guardar evaluación del producto final", type="primary", key="dec_fin_save"):
            try:
                import lab_carga
                _data = {"tipo_formulario": "GENERICO",
                         "usuario_app": str(USR.get("nombre_full") or USR.get("id_usuario") or ""),
                         "ticket": str(_tkfin), "producto_lab": _pbase,
                         "calidad_final_lab": (_cal or None), "rechazado": _rech, "color": (_color or None),
                         "prc_acidez": (_ac or None), "prc_agua": (_ag or None), "prc_sedimentos": (_sed or None),
                         "prc_producto": (_prodp or None), "prc_hkf": (_hkf or None), "prc_hexano_impurezas": (_hex or None),
                         "prc_glicerina": (_gliP or None), "prc_poliglicerol": (_poli or None),
                         "densidad__g_ml": (_dens or None), "ppm_azufre": (_az or None), "ppm_fosforo": (_fo or None),
                         "temp_celcius": (_temp or None), "conclusion": (_concl or None),
                         "id_tanque_1": (int(b["id_tanque_are_final"]) if pd.notna(b["id_tanque_are_final"]) else None)}
                _newid = lab_carga.insertar_evaluacion(_data)
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur:
                        try:
                            cur.execute("UPDATE produccion.lab_evaluaciones SET fecha=now() WHERE id=%s AND fecha IS NULL", (int(_newid),))
                        except Exception:
                            pass
                        cur.execute("UPDATE produccion.fact_batch_proceso "
                                    "SET parametros_proceso = COALESCE(parametros_proceso,'{}'::jsonb) "
                                    "  || jsonb_build_object('final_lab', jsonb_build_object('azufre',%s,'fosforo',%s,'calidad',%s,'producto',%s,'rechazado',%s)) "
                                    "WHERE id_batch=%s",
                                    (float(_az or 0), float(_fo or 0), (_cal or None), _pbase, _rech, int(b["id_batch"])))
                    audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"final_lab_eval": int(_newid)})
                st.success(f"Evaluación guardada en laboratorio (id {_newid}, ticket {_tkfin}). Espejada a procesos_lab.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
        try:
            _le = cat("SELECT to_char(fecha,'DD/MM HH24:MI') AS \"Fecha\", producto_lab AS \"Producto\", "
                      "calidad_final_lab AS \"Calidad\", rechazado AS \"Resultado\", "
                      "prc_acidez AS \"Acidez\", prc_agua AS \"Agua\", ppm_azufre AS \"Azufre\", ppm_fosforo AS \"Fósforo\" "
                      "FROM produccion.v_procesos_lab_efectivo WHERE ticket=%s ORDER BY fecha DESC NULLS LAST", (str(_tkfin),))
        except Exception:
            _le = None
        if _le is not None and not _le.empty:
            st.caption("Historial de evaluaciones del ticket final (con horario; puede incluir rechazos):")
            st.dataframe(_le, use_container_width=True, hide_index=True)
