"""Decantación de PRODUCCION_ARE.
Tres paneles que comparten datos del batch:
  - destinos(...)      → Centro de Planificación: elegir destino de glicerina recuperada
                         (cónico 20-2 / Minion / 20-1) y destino final del ARE (export recomendado).
  - produccion(...)    → Producción en planta: prueba de solubilidad (¿el material purgado flota?),
                         envío de muestra a lab, ver purga/ticket, confirmar + generar movimientos.
  - laboratorio(...)   → Laboratorio: ver producciones en marcha que requieren evaluación y cargar
                         el % de glicerina del purgado (<3% = purga OK) y azufre/fósforo del final.
Corta cuando glicerina del purgado < 3%. Recomienda exportación si azufre y fósforo < 200.
"""
import json
import pandas as pd
import streamlit as st

REPOSO_DECANT = ("REPOSO", "DECANTACION")
GLI_RECUP_TANQUES = (88, 87, 81)   # cónico 20-2, cónico 20-1, Minion
PURGA_CORTE = 3.0                  # glicerina < 3% => purga OK
SP_EXPORT = 200.0                  # azufre y fósforo < 200 => apto exportación


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

    st.markdown("##### 🎯 Destino final del ARE")
    fl = _params(b).get("final_lab") or {}
    _az = fl.get("azufre"); _fo = fl.get("fosforo")
    apto = (_az is not None and _fo is not None and float(_az) < SP_EXPORT and float(_fo) < SP_EXPORT)
    if _az is not None:
        if apto:
            st.success(f"✅ Lab final: azufre {float(_az):.0f} · fósforo {float(_fo):.0f} ppm (< {SP_EXPORT:.0f}) → "
                       "**apto para exportación**: se recomiendan tanques de exportación.")
        else:
            st.warning(f"Lab final: azufre {float(_az or 0):.0f} · fósforo {float(_fo or 0):.0f} ppm → "
                       "no apto para exportación; usar tanques de ARE.")
    else:
        st.caption("Aún sin azufre/fósforo del final (lo carga laboratorio). La recomendación de exportación aparece al tenerlos.")
    ft = cat(
        "SELECT t.id_tanque, t.nombre, t.codigo, t.sector, COALESCE(s.litros_actual,0) lt, COALESCE(t.capacidad_litros,0) cap "
        "FROM produccion.dim_tanque t JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
        "LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
        "WHERE COALESCE(t.activo,true) AND (p.codigo_producto='ARE-B' OR (%s AND t.sector ILIKE 'Exporta%%')) "
        "ORDER BY (t.sector ILIKE 'Exporta%%') DESC, t.nombre", (apto,))
    if ft is None or ft.empty:
        st.warning("No hay tanques destino para ARE-B.")
        dest_fin = None
    else:
        fop = ft.apply(lambda r: f"{r['nombre']} · {r['sector']} · {float(r['lt']):,.0f}/{float(r['cap']):,.0f} L", axis=1).tolist()
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
def produccion(USR, cat, conectar):
    st.header("🧴 Decantación (purga ARE)")
    st.caption("Durante la decantación hacés la **prueba de solubilidad**: si el material purgado **flota**, "
               "ese proceso terminó. Mandás muestra a laboratorio: corta cuando la glicerina del purgado es < 3%.")
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
    if pd.notna(b["solubilidad_flota"]):
        st.info("Última prueba: **flota ✅ → terminado**" if b["solubilidad_flota"] else "Última prueba: **no flota** (seguir decantando)")

    if st.button("📤 Enviar muestra de purga a laboratorio", key="dec_envio_lab"):
        st.success("Muestra de purga marcada para laboratorio. La verás en la sección Laboratorio "
                   "(carga el % de glicerina; corta en < 3%).")

    st.markdown("##### 🔬 Resultado de laboratorio (purga)")
    gp = b["purga_glicerina_pct"]
    if pd.isna(gp) or gp is None:
        st.caption("Laboratorio todavía no cargó el % de glicerina del material purgado.")
    elif bool(b["purga_ok"]):
        st.success(f"✅ Glicerina del purgado **{float(gp):.1f}% (< {PURGA_CORTE:.0f}%)** → **purga OK**. Podés confirmar y enviar a destino.")
    else:
        st.warning(f"🔴 Glicerina del purgado **{float(gp):.1f}% (≥ {PURGA_CORTE:.0f}%)** → **seguí decantando**.")

    st.divider()
    st.markdown("##### ✅ Confirmar decantación y enviar a destino")
    if not bool(b["purga_ok"]):
        st.info("Disponible cuando laboratorio confirme purga OK (< 3%).")
        return
    if pd.isna(dg) or pd.isna(df_):
        st.warning("Falta que dirección defina los tanques destino (glicerina recuperada y ARE final).")
        return
    p = _params(b)
    _are_def = float(p.get("are_objetivo_kg") or 0) / 0.88
    cc1, cc2 = st.columns(2)
    l_gli = cc1.number_input("Litros de glicerina recuperada → " + (_nm.get(int(dg)) or "destino"),
                             0.0, 1_000_000.0, value=0.0, step=50.0, key="dec_l_gli")
    l_are = cc2.number_input("Litros de ARE final → " + (_nm.get(int(df_)) or "destino"),
                             0.0, 1_000_000.0, value=float(round(_are_def, 0)), step=50.0, key="dec_l_are")
    if st.button("🚚 Confirmar y generar movimientos de stock", type="primary", use_container_width=True, key="dec_confirm"):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto='GLICERINA-RECUP'")
                    _r = cur.fetchone(); id_gli = _r[0] if _r else None
                    cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto='ARE-B'")
                    _r = cur.fetchone(); id_are = _r[0] if _r else None
                    _mov(cur, b, uid, "SUBPRODUCTO", id_gli, "Glicerina recuperada", int(dg), l_gli, 1.05)
                    _mov(cur, b, uid, "FINAL", id_are, "ARE-B", int(df_), l_are, 0.88)
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
        "VALUES (now(),%s,%s,'INGRESO',%s,1,%s,%s,'TANQUE',%s,%s,'L',%s,%s,%s,'decantacion','EJECUTADO')",
        (int(b["id_batch"]), b["ident"], rol, id_prod, prod_txt, int(id_tanque),
         float(litros), float(litros)*float(dens), float(litros), uid))


def _set_flota(USR, cat, conectar, id_batch, flota):
    try:
        with conectar(int(USR["id_usuario"])) as (conn, audit):
            with conn.cursor() as cur:
                cur.execute("UPDATE produccion.fact_batch_proceso SET solubilidad_flota=%s, solubilidad_ts=now() "
                            "WHERE id_batch=%s", (bool(flota), int(id_batch)))
            audit.log("U", "fact_batch_proceso", int(id_batch), {"flota": bool(flota)})
        cat.clear()
    except Exception as e:
        st.exception(e)


# ---------------------------------------------------------------- LABORATORIO
def laboratorio(USR, cat, conectar):
    st.subheader("🔬 Evaluaciones de producciones en marcha (ARE en decantación)")
    st.caption("Producciones que requieren evaluación de laboratorio. Cargá el **% de glicerina del material purgado** "
               f"(corta en < {PURGA_CORTE:.0f}%) y, para el producto final, azufre/fósforo (apto exportación si < {SP_EXPORT:.0f}).")
    b, df = _sel_batch(cat, "dec_lab_sel")
    if b is None:
        return
    _cabecera(b)
    uid = int(USR["id_usuario"])

    st.markdown("##### 🧴 Purga: % de glicerina del material purgado")
    gp = st.number_input("% glicerina del purgado", 0.0, 100.0,
                         value=float(b["purga_glicerina_pct"]) if pd.notna(b["purga_glicerina_pct"]) else 0.0,
                         step=0.1, key="dec_lab_gli")
    if st.button("💾 Guardar % glicerina (purga)", type="primary", key="dec_lab_save_gli"):
        ok = gp < PURGA_CORTE
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_batch_proceso "
                                "SET purga_glicerina_pct=%s, purga_ok=%s, purga_lab_ts=now() WHERE id_batch=%s",
                                (float(gp), bool(ok), int(b["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"purga_pct": gp, "ok": ok})
            st.success(f"Glicerina {gp:.1f}% → " + ("✅ purga OK (< 3%)" if ok else "🔴 seguir decantando (≥ 3%)"))
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)

    st.markdown("##### 🎯 Evaluación del producto final (ticket " + (b["ticket_producto_final"] or "—") + ")")
    fl = _params(b).get("final_lab") or {}
    e1, e2 = st.columns(2)
    az = e1.number_input("Azufre (ppm)", 0.0, 100000.0,
                         value=float(fl.get("azufre") or 0.0), step=1.0, key="dec_lab_az")
    fo = e2.number_input("Fósforo (ppm)", 0.0, 100000.0,
                         value=float(fl.get("fosforo") or 0.0), step=1.0, key="dec_lab_fo")
    if az and fo:
        if az < SP_EXPORT and fo < SP_EXPORT:
            st.success(f"✅ Azufre {az:.0f} · Fósforo {fo:.0f} (< {SP_EXPORT:.0f}) → **apto exportación** (tanques de exportación recomendados).")
        else:
            st.warning(f"Azufre {az:.0f} · Fósforo {fo:.0f} → no apto exportación.")
    if st.button("💾 Guardar lab del producto final", key="dec_lab_save_fin"):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_batch_proceso "
                                "SET parametros_proceso = COALESCE(parametros_proceso,'{}'::jsonb) "
                                "      || jsonb_build_object('final_lab', jsonb_build_object('azufre',%s,'fosforo',%s)) "
                                "WHERE id_batch=%s", (float(az), float(fo), int(b["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"final_az": az, "final_fo": fo})
            st.success("Evaluación del producto final guardada.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)
