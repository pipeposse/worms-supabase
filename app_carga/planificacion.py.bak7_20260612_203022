"""Centro de Planificación (dirección) — réplica del motor de Cargas.
Misma lógica automática que "Nueva carga / reactores":
  - MP-first: el proceso se deriva de la MP (AG/SEBO -> PRODUCCION_ARE, AFE -> DESGOMADO).
  - Q AG objetivo = capacidad del reactor × densidad de la MP (se recalcula al cambiar reactor/MP).
  - temp / tiempo / acidez objetivo vienen de dic_proceso_parametros.
  - PRODUCCION_ARE: glicerina por muestra de laboratorio (define % glicerol y la glicerina total),
    catalizador NAOH/POTASIO excluyente (NAOH genera glicerina recuperada), fuel/soda/potasio por TN.
  - Fuente de la MP con `fuente_mp_combinada`: tanques filtrados por producto + parámetros de lab ponderados.
Genera el ID de producción PLANIFICADO + un ticket de movimiento por cada MP/insumo.

render(USR, cat, conectar, siguiente_identificador, H) — H = helpers de app.py.
"""
import json as _json
import re as _re
import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")

# ===== Bachas: recetas por (proceso, MP, PF) — rendimiento, insumos y tiempos =====
# Densidades para litros<->kg (kg/L). Sulfúrico 78% ~1.71, clorhídrico ~1.18.
DENS_INSUMO = {"FUEL_OIL": 0.95, "AGUA": 1.0, "soda_kg": 1.33, "acido_kg": 1.71,
               "GASOIL": 0.85, "ACIDO_CLORHIDRICO": 1.18}

def _formulas_sector(cat, sector):
    """Fórmulas activas de dic_formula para un sector (REACTORES/BACHAS)."""
    return cat("SELECT * FROM produccion.dic_formula WHERE activo AND sector IN (%s, '*') "
               "ORDER BY tipo_proceso, codigo_mp, codigo_pf, es_default DESC, nombre", (sector,))


def _ins_de(row):
    """Dict de insumos {codigo: {cant, un}} de una fila de dic_formula (cant por TN de MP CARGADA)."""
    v = row["insumos"]
    if isinstance(v, dict):
        return v
    try:
        return _json.loads(v or "{}")
    except Exception:
        return {}


def _params_de(row):
    """Dict de parámetros estequiométricos de una fórmula (parametros jsonb)."""
    try:
        v = row["parametros"]
    except Exception:
        return {}
    if isinstance(v, dict):
        return v
    try:
        return _json.loads(v or "{}")
    except Exception:
        return {}


def _selector_formula(df, key):
    """Selector de fórmula con nombre (⭐ = default, preseleccionada). Devuelve la fila elegida."""
    if df is None or len(df) == 0:
        return None
    opts = df.apply(lambda r: f"{'⭐ ' if r['es_default'] else ''}{r['nombre']}", axis=1).tolist()
    if len(opts) == 1:
        st.caption(f"Fórmula: **{opts[0]}** · administrala en la sección 🧪 Fórmulas.")
        return df.iloc[0]
    sel = st.selectbox("Fórmula a usar", opts, key=key,
                       help="⭐ = default. Creá variantes y cambiá la default en la sección 🧪 Fórmulas.")
    return df.iloc[opts.index(sel)]


def _render_planificadas(cat):
    """Vista de todo lo planificado + sus movimientos (tickets)."""
    df = listar_planificadas(cat)
    if df is None or df.empty:
        st.info("No hay producciones en estado PLANIFICADO.")
        return
    st.dataframe(df.drop(columns=["id_batch"]).rename(columns={
        "identificador_unidad": "ID", "sector": "Sector", "tipo_proceso": "Proceso",
        "reactor": "Equipo", "producto_final": "Producto final", "calidad_buscada": "Calidad",
        "tiempo_estimado_horas": "Horas est.", "creado_en": "Creada"}),
        use_container_width=True, hide_index=True,
        column_config={"Creada": st.column_config.DatetimeColumn(format="DD/MM HH:mm")})
    opts = df.apply(lambda r: f"{r['identificador_unidad']} · {r['tipo_proceso'] or '—'} · {r['producto_final'] or '—'}", axis=1).tolist()
    sel = st.selectbox("Ver movimientos de", opts, key="pl_ver_mov")
    mv = listar_movimientos_plan(cat, int(df.iloc[opts.index(sel)]["id_batch"]))
    st.dataframe(mv.rename(columns={
        "ticket_mov": "Ticket", "estado_mov": "Estado", "rol": "Rol", "item": "Item",
        "fuente": "Fuente", "origen": "Origen", "cantidad": "Cantidad", "unidad": "Unidad",
        "kg": "kg", "litros": "Litros"}), use_container_width=True, hide_index=True)


def _render_aprobaciones(USR, cat, conectar, compacto=True):
    """Tickets de aprobación por carga < 80% (falta grave). Resuelve el director (ADMIN).
    compacto=True: expander dentro de Planificación (se oculta si no hay tickets).
    compacto=False: vista completa para la sección 🛂 Dirección (siempre visible)."""
    try:
        ap = cat("SELECT a.id_aprobacion, a.id_batch, a.identificador, a.sector, a.equipo, a.capacidad_l, "
                 "a.litros_cargados, a.pct_carga, a.motivo, a.estado, a.solicitado_en, "
                 "u.nombre_full AS solicitante, a.comentario_resolucion "
                 "FROM produccion.fact_aprobacion_carga a "
                 "LEFT JOIN produccion.dim_usuario u ON u.id_usuario=a.solicitado_por "
                 "ORDER BY (a.estado='PENDIENTE') DESC, a.solicitado_en DESC LIMIT 100")
    except Exception:
        ap = None
    _vacio = ap is None or ap.empty
    if compacto and _vacio:
        return
    n_pend = 0 if _vacio else int((ap["estado"] == "PENDIENTE").sum())
    es_director = USR.get("rol") == "ADMIN"
    _ctx = (st.expander(f"🛂 Aprobaciones de carga baja (<80%) — {n_pend} pendiente(s)",
                        expanded=(n_pend > 0 and es_director)) if compacto else st.container())
    with _ctx:
        if _vacio:
            st.success("✔️ No hay planificaciones fuera de norma (todas las cargas ≥ 80% o sin tickets generados).")
            return
        st.caption("Cargar un reactor/bacha a menos del 80% es una **falta grave** (induce pérdidas económicas). "
                   "El operario no puede iniciar la producción hasta que el **director** apruebe el ticket.")
        st.dataframe(ap.rename(columns={
            "id_aprobacion": "Ticket", "identificador": "ID prod.", "sector": "Sector", "equipo": "Equipo",
            "capacidad_l": "Capacidad (L)", "litros_cargados": "Cargado (L)", "pct_carga": "% carga",
            "motivo": "Justificación", "estado": "Estado", "solicitado_en": "Solicitado",
            "solicitante": "Por", "comentario_resolucion": "Comentario director"}).drop(columns=["id_batch"]),
            use_container_width=True, hide_index=True,
            column_config={"Solicitado": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                           "% carga": st.column_config.NumberColumn(format="%.0f%%")})
        if not es_director:
            st.info("Solo el director (ADMIN) puede aprobar o rechazar estos tickets.")
            return
        pend = ap[ap["estado"] == "PENDIENTE"]
        if pend.empty:
            return
        opts = pend.apply(lambda r: f"#{r['id_aprobacion']} · {r['identificador']} · {r['equipo']} · {float(r['pct_carga']):.0f}%", axis=1).tolist()
        sel = st.selectbox("Ticket a resolver", opts, key="apr_sel")
        row = pend.iloc[opts.index(sel)]
        st.markdown(f"**Justificación de la supervisora:** {row['motivo']}")
        com = st.text_input("Comentario del director (opcional)", key="apr_com", max_chars=200)

        def _resolver(estado):
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_aprobacion_carga SET estado=%s, resuelto_por=%s, "
                                "resuelto_en=now(), comentario_resolucion=%s WHERE id_aprobacion=%s",
                                (estado, int(USR["id_usuario"]), ((com or "").strip() or None), int(row["id_aprobacion"])))
                audit.log("U", "fact_aprobacion_carga", int(row["id_aprobacion"]),
                          {"estado": estado, "batch": int(row["id_batch"])})

        a1, a2 = st.columns(2)
        if a1.button("✅ Aprobar carga baja", type="primary", use_container_width=True, key="apr_ok"):
            try:
                _resolver("APROBADO"); st.success("Aprobado: el operario ya puede iniciar la producción.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
        if a2.button("⛔ Rechazar", use_container_width=True, key="apr_no"):
            try:
                _resolver("RECHAZADO"); st.success("Rechazado: la producción queda bloqueada.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)


def _render_bachas(USR, cat, conectar, siguiente_identificador, H):
    """Planificación de bachas guiada por fórmula con nombre (dic_formula):
    ubicación + proceso + MP -> PF, insumos por TN de MP CARGADA, y tiempo."""
    fuente_mp_combinada = H.get("fuente_mp_combinada")
    densidad_de = H.get("densidad_de")
    productos = H.get("productos")

    R = _formulas_sector(cat, "BACHAS")
    R = R[R["sector"] == "BACHAS"] if (R is not None and not R.empty) else R
    if R is None or R.empty:
        st.error("No hay fórmulas de BACHAS activas. Creálas en la sección 🧪 Fórmulas.")
        return

    # ---------- 1 · Ubicación + proceso + MP + PF ----------
    st.markdown("#### 1 · Ubicación, proceso y materia prima")
    bachas = cat("SELECT id_bien_uso, codigo, nombre_ui, capacidad_max_l FROM produccion.dim_bien_uso "
                 "WHERE activo AND tipo='BACHA' ORDER BY codigo")
    if bachas.empty:
        st.error("No hay bachas cargadas en `dim_bien_uso`.")
        return
    c1, c2 = st.columns(2)
    _bop = bachas.apply(lambda r: r["nombre_ui"] + (f" · {r['capacidad_max_l']:,.0f} L" if pd.notna(r["capacidad_max_l"]) else " · sin cubicaje"), axis=1).tolist()
    _bsel = c1.selectbox("Ubicación (bacha)", _bop, key="plb_ubic")
    _brow = bachas.iloc[_bop.index(_bsel)]
    cap = float(_brow["capacidad_max_l"]) if pd.notna(_brow["capacidad_max_l"]) else 0.0
    procs = sorted(R["tipo_proceso"].unique().tolist())
    proc = c2.selectbox("Proceso", procs, format_func=lambda p: p.replace("_", " ").title(), key="plb_proc")
    Rp = R[R["tipo_proceso"] == proc]
    c3, c4 = st.columns(2)
    mp = c3.selectbox("Materia prima (producto inicial)", sorted(Rp["codigo_mp"].unique().tolist()), key=f"plb_mp_{proc}")
    Rm = Rp[Rp["codigo_mp"] == mp]
    pf = c4.selectbox("Producto final (según fórmula)", sorted(Rm["codigo_pf"].unique().tolist()), key=f"plb_pf_{proc}_{mp}")
    rec = _selector_formula(Rm[Rm["codigo_pf"] == pf], key=f"plb_fx_{proc}_{mp}_{pf}")
    ins_f = _ins_de(rec)
    _kk = f"{proc}_{mp}_{pf}_{int(rec['id_formula'])}".replace(" ", "")

    dens = float(densidad_de(mp) or 0.95) if callable(densidad_de) else 0.95
    _pfrow = productos[productos["codigo_producto"] == pf]
    if _pfrow.empty:
        st.error(f"El producto final {pf} no existe en dim_producto.")
        return
    dens_pf = float(_pfrow.iloc[0]["densidad_g_ml"]) if pd.notna(_pfrow.iloc[0].get("densidad_g_ml")) else 0.92
    pf_id = int(_pfrow.iloc[0]["id_producto"])
    q_obj = cap * dens

    e_rend = float(rec["rendimiento_pct"] or 0)
    e_hpro = float(rec["horas_proceso"] or 8)
    e_hrep = float(rec["horas_reposo"] or 0)
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Capacidad bacha", f"{cap:,.0f} L" if cap else "—")
    b2.metric("Q MP si se llena", f"{q_obj:,.0f} kg" if cap else "—")
    b3.metric("Rendimiento fórmula", f"{e_rend:.1f}%")
    b4.metric("⏱️ Ocupación bacha", f"{e_hpro + e_hrep:,.0f} h", f"{e_hpro:g} h proceso + {e_hrep:g} h reposo")
    if rec.get("notas"):
        st.caption(f"📝 {rec['notas']}")

    # ---------- 2 · Fuente MP ----------
    st.markdown(f"#### 2 · Fuente de la materia prima ({mp})")
    try:
        kg_src, ports, lab_avg, _corr = fuente_mp_combinada(mp, key_prefix="plb_mpf", target_kg=(q_obj or None))
    except Exception as e:
        st.error(f"No se pudo cargar la fuente de MP: {e}")
        kg_src, ports, lab_avg = 0.0, [], {}
    kg_used = float(kg_src or 0.0)
    litros_mp = kg_used / dens if dens else 0.0
    _pct = (litros_mp / cap * 100) if cap else None
    f1, f2, f3 = st.columns(3)
    f1.metric("MP a cargar", f"{litros_mp:,.0f} L", f"{kg_used:,.0f} kg · {kg_used/1000:,.2f} TN")
    f2.metric("Llenado de la bacha", f"{_pct:.0f}%" if _pct is not None else "—")
    f3.metric("Densidad MP", f"{dens:g} kg/L")
    if _pct is not None:
        st.progress(min(1.0, max(0.0, _pct / 100)))
    just_carga = ""
    _carga_baja = bool(_pct is not None and kg_used > 0 and _pct < 80.0)
    if _carga_baja:
        st.error(f"🚨 **Carga al {_pct:.0f}%** de la capacidad de la bacha (mínimo: 80%). "
                 "Cargar de menos es una falta grave: justificá el motivo. "
                 "Se genera un ticket que el **director debe aprobar** antes de poder iniciar.")
        just_carga = st.text_input("Justificación de carga baja (<80%) *", key="plb_just_carga", max_chars=250,
                                   placeholder="ej. no hay más MP disponible")

    # ---------- 3 · Estimados: fórmula × kg de MP CARGADA ----------
    st.markdown("#### 3 · Estimados (fórmula × TN de MP cargada)")
    tn_mp = kg_used / 1000.0
    est_form = {cod: tn_mp * float(x.get("cant") or 0) for cod, x in ins_f.items()}
    est_un = {cod: (x.get("un") or "L") for cod, x in ins_f.items()}
    kg_pf_form = kg_used * e_rend / 100.0
    est = dict(est_form)
    kg_pf = kg_pf_form
    with st.expander("✏️ Ajustar estimados a mano (si la fórmula no te cierra)", expanded=False):
        if est:
            cols = st.columns(len(est))
            for c, cod in zip(cols, list(est.keys())):
                est[cod] = c.number_input(f"{cod} ({est_un[cod]})", 0.0, 1_000_000.0,
                                          value=float(round(est_form[cod], 1)), step=5.0, key=f"rb_aj_{cod}_{_kk}")
        kg_pf = st.number_input("Producto final estimado (kg)", 0.0, 10_000_000.0,
                                value=float(round(kg_pf_form, 0)), step=100.0, key=f"rb_aj_pf_{_kk}")
        if st.button("🔄 Volver a la fórmula", key=f"rb_aj_rst_{_kk}"):
            for cod in est_form:
                st.session_state.pop(f"rb_aj_{cod}_{_kk}", None)
            st.session_state.pop(f"rb_aj_pf_{_kk}", None)
            st.rerun()

    ajustes = {}
    for cod in est_form:
        if abs(est[cod] - est_form[cod]) > 0.5:
            ajustes[f"{cod} ({est_un[cod]})"] = {"formula": round(est_form[cod], 1), "ajustado": round(est[cod], 1)}
    if abs(kg_pf - kg_pf_form) > 1:
        ajustes["PF estimado (kg)"] = {"formula": round(kg_pf_form), "ajustado": round(kg_pf)}

    # resumen de TODO lo que se carga (litros primero)
    filas = [{"Item": f"MP · {mp}", "Litros": round(litros_mp, 0), "kg": round(kg_used, 0), "TN": round(kg_used / 1000, 2)}]
    for cod, q in est.items():
        if q <= 0:
            continue
        _d = DENS_INSUMO.get(cod)
        if est_un[cod] == "L":
            filas.append({"Item": cod, "Litros": round(q, 0), "kg": round(q * (_d or 1.0), 0), "TN": round(q * (_d or 1.0) / 1000, 2)})
        else:
            filas.append({"Item": cod, "Litros": (round(q / _d, 0) if _d else None), "kg": round(q, 0), "TN": round(q / 1000, 2)})
    filas.append({"Item": f"PF estimado · {pf}", "Litros": round(kg_pf / dens_pf, 0) if dens_pf else None,
                  "kg": round(kg_pf, 0), "TN": round(kg_pf / 1000, 2)})
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.caption(f"⏱️ La bacha queda ocupada **{e_hpro + e_hrep:,.0f} h** ({e_hpro:g} h de proceso + {e_hrep:g} h de reposo). "
               "Para cambiar la fórmula de forma permanente usá la sección 🧪 Fórmulas.")

    motivo_ajuste = ""
    if ajustes:
        st.warning("✏️ Cambiaste a mano: **" + ", ".join(ajustes.keys()) +
                   "** (vs. fórmula). Indicá el motivo — es obligatorio y queda registrado. "
                   "Si el cambio es definitivo, guardá una fórmula nueva en 🧪 Fórmulas.")
        motivo_ajuste = st.text_input("Motivo del ajuste *", key="plb_aj_motivo", max_chars=200,
                                      placeholder="ej. borra con mucha agua, dosificamos más ácido")
    obs = st.text_input("Observaciones", key="plb_obs", placeholder="opcional")
    st.divider()
    if st.button("✅ Generar ID de producción + tickets de movimiento", type="primary",
                 use_container_width=True, key="plb_go"):
        mp_ports = [p for p in (ports or []) if float(p.get("kg", 0) or 0) > 0]
        if not mp_ports:
            st.error("Elegí una fuente de materia prima (portería o tanque) con cantidad > 0.")
            return
        if ajustes and not (motivo_ajuste or "").strip():
            st.error("Cambiaste estimados a mano: **indicá el motivo del ajuste** antes de generar.")
            return
        if _carga_baja and not (just_carga or "").strip():
            st.error("Carga menor al 80%: **justificá el motivo** para generar el ticket de aprobación del director.")
            return
        mp_id = int(productos[productos["codigo_producto"] == mp].iloc[0]["id_producto"])
        ident = siguiente_identificador("BACHAS")
        params = {
            "kg_mp": round(kg_used, 0), "ubicacion": _brow["nombre_ui"],
            "formula": {"id_formula": int(rec["id_formula"]), "nombre": rec["nombre"],
                        "rendimiento_pct": e_rend, "insumos": ins_f},
            "insumos_estimados": {cod: round(q, 1) for cod, q in est.items() if q > 0},
            "pf_estimado_kg": round(kg_pf, 0),
            "horas_proceso": e_hpro, "horas_reposo": e_hrep,
            "ajustes_manuales": (ajustes or None),
            "motivo_ajuste": ((motivo_ajuste or "").strip() or None),
            "carga_baja": ({"pct": round(_pct, 1), "motivo": just_carga.strip()} if _carga_baja else None),
        }
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO fact_batch_proceso "
                        "(fecha, sector, id_usuario_carga, identificador_unidad, id_bien_uso, tipo_proceso, "
                        " id_producto_buscado, tiempo_estimado_horas, parametros_proceso, estado, "
                        " id_usuario_estado, motivo_estado, observaciones) "
                        "VALUES (CURRENT_DATE,'BACHAS',%s,%s,%s,%s,%s,%s,%s::jsonb,'PLANIFICADO',%s,"
                        " 'Planificado por dirección',%s) RETURNING id_batch",
                        (uid, ident, int(_brow["id_bien_uso"]), proc, pf_id, float(e_hpro + e_hrep),
                         _json.dumps(params), uid, (obs or None)))
                    id_b = cur.fetchone()[0]
                    n_mov = 0
                    if _carga_baja:
                        cur.execute(
                            "INSERT INTO produccion.fact_aprobacion_carga "
                            "(id_batch, identificador, sector, equipo, capacidad_l, litros_cargados, pct_carga, motivo, solicitado_por) "
                            "VALUES (%s,%s,'BACHAS',%s,%s,%s,%s,%s,%s)",
                            (id_b, ident, _brow["nombre_ui"], cap, round(litros_mp, 1), round(_pct, 1),
                             just_carga.strip(), uid))

                    def _mov(rol, id_producto, prod_txt, cod_ins, fuente, idt, tkp, kg, litros):
                        fmov = "TANQUE" if fuente == "TANQUE" else "PORTERIA"
                        cur.execute(
                            "INSERT INTO fact_movimiento_stock "
                            "(momento,id_batch,identificador_prod,tipo_movimiento,rol,sentido,id_producto,producto,"
                            " codigo_insumo,fuente,id_tanque,ticket_porteria,cantidad,unidad,kg,litros,id_usuario,"
                            " origen,estado_mov,id_usuario_planifica,planificado_en) "
                            "VALUES (now(),%s,%s,'SALIDA',%s,-1,%s,%s,%s,%s,%s,%s,%s,'KG',%s,%s,%s,"
                            " 'planificacion','PLANIFICADO',%s,now())",
                            (id_b, ident, rol, id_producto, prod_txt, cod_ins, fmov, idt, tkp,
                             float(kg), float(kg), litros, uid, uid))

                    for p in mp_ports:
                        es_tk = (p.get("fuente") == "TANQUE")
                        kgp = float(p["kg"])
                        litros = round(kgp / dens, 1) if dens else None
                        cur.execute(
                            "INSERT INTO fact_batch_insumo (id_batch,rol,id_producto,cantidad,unidad,fuente,id_tanque,ticket_porteria,id_usuario) "
                            "VALUES (%s,'MP',%s,%s,'KG',%s,%s,%s,%s)",
                            (id_b, mp_id, kgp, ("TANQUE" if es_tk else "TICKET"),
                             (int(p["id_tanque"]) if es_tk and p.get("id_tanque") else None),
                             (None if es_tk else p.get("ticket")), uid))
                        _mov("MP", mp_id, mp, None, ("TANQUE" if es_tk else "TICKET"),
                             (int(p["id_tanque"]) if es_tk and p.get("id_tanque") else None),
                             (None if es_tk else p.get("ticket")), kgp, litros)
                        n_mov += 1

                    for cod, q in est.items():
                        if not q or q <= 0:
                            continue
                        _d = DENS_INSUMO.get(cod)
                        if est_un[cod] == "L":
                            kgv, lts = round(q * (_d or 1.0), 1), round(q, 1)
                        else:
                            kgv, lts = round(q, 1), (round(q / _d, 1) if _d else None)
                        _mov("INSUMO", None, cod, cod, "PORTERIA", None, None, kgv, lts)
                        n_mov += 1
            try:
                cat.clear()
            except Exception:
                pass
            st.success(f"Producción **{ident}** (batch #{id_b}, {_brow['nombre_ui']}) planificada con "
                       f"**{n_mov} movimiento(s)** PLANIFICADO. Ocupación estimada: {e_hpro + e_hrep:,.0f} h.")
            st.balloons()
        except Exception as e:
            st.error(f"No se pudo guardar la planificación: {e}")


def _productos_proceso(cat, sector, tipo, rol):
    """Productos válidos para (proceso, rol) según dic_proceso_producto (patrones LIKE)."""
    return cat(
        "SELECT DISTINCT p.id_producto, p.codigo_producto, p.nombre_producto, "
        "       COALESCE(p.densidad_g_ml,0.91) dens, COALESCE(p.corriente,'') corriente "
        "FROM produccion.dim_producto p "
        "JOIN produccion.dic_proceso_producto pp "
        "  ON pp.rol=%s AND (pp.tipo_proceso=%s OR pp.tipo_proceso IS NULL) "
        "     AND (pp.sector=%s OR pp.sector IS NULL) "
        "WHERE p.activo AND p.codigo_producto LIKE pp.patron "
        "ORDER BY p.codigo_producto", (rol, tipo, sector))


def render(USR, cat, conectar, siguiente_identificador, H=None):
    if H is None:
        try:
            H = st.session_state.get("_plan_helpers", {})
        except Exception:
            H = {}
    H = H or {}
    proceso_desde_mp = H.get("proceso_desde_mp")
    fuente_mp_combinada = H.get("fuente_mp_combinada")
    corriente_de_mp_lab = H.get("corriente_de_mp_lab")
    densidad_de = H.get("densidad_de")
    K = H.get("K")
    ultimas_muestras_glicerina = H.get("ultimas_muestras_glicerina")
    productos = H.get("productos")
    bienes = H.get("bienes_uso_full")

    st.title("🗓️ Centro de Planificación")
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección (SUPERVISOR / ADMIN), salvo acceso otorgado por el administrador.")
        return
    if not all([callable(proceso_desde_mp), callable(fuente_mp_combinada), callable(densidad_de), callable(K)]) \
       or productos is None or bienes is None or getattr(productos, "empty", True) or getattr(bienes, "empty", True):
        st.error("No se pudieron cargar los catálogos/funciones de Cargas. Reintentá.")
        return
    with st.expander("📋 Ver planificadas y sus movimientos (todo lo cargado)", expanded=False):
        _render_planificadas(cat)
    _render_aprobaciones(USR, cat, conectar)

    modo = st.radio("Planificar en", ["🏭 Reactores", "🛁 Bachas"],
                    horizontal=True, key="pl_modo")
    if modo.startswith("🛁"):
        _render_bachas(USR, cat, conectar, siguiente_identificador, H)
        return
    st.caption("Misma lógica que Cargas: elegí reactor y materia prima; el proceso, la capacidad y todas las fórmulas se calculan solos.")

    # ---------- 1 · Reactor + MP (define el proceso) ----------
    st.markdown("#### 1 · Reactor y materia prima")
    mp_df = productos[productos["tipo_producto"] == "MP"].copy()
    mp_opts = [c for c in mp_df["codigo_producto"].tolist() if str(c).startswith(("AG-", "AFE", "SEBO", "BORRA"))] \
        or mp_df["codigo_producto"].tolist()

    c1, c2 = st.columns(2)
    cod_bien = c1.selectbox("Reactor (bien de uso)", bienes["codigo"].tolist(),
                            format_func=lambda c: bienes[bienes["codigo"] == c].iloc[0]["nombre_ui"], key="pl_react")
    fila = bienes[bienes["codigo"] == cod_bien].iloc[0]
    mp = c2.selectbox("Materia prima a tratar", mp_opts, key="pl_mp",
                      help="El proceso y la corriente se derivan de la MP. AG/SEBO → ARE · AFE → desgomado.")
    proc = proceso_desde_mp(mp)
    sector = str(fila["sector"]) if ("sector" in fila.index and pd.notna(fila["sector"])) else "REACTORES"
    corr = (corriente_de_mp_lab(mp) if callable(corriente_de_mp_lab) else None)
    cap = float(fila["capacidad_max_l"] or 0)
    dens = float(densidad_de(mp) or 0.92)
    q_ag = cap * dens

    par = cat("SELECT temp_inicial_c, tiempo_total_horas, acidez_objetivo_pct "
              "FROM produccion.dic_proceso_parametros WHERE tipo_proceso=%s", (proc,))
    temp = float(par.iloc[0]["temp_inicial_c"]) if (not par.empty and par.iloc[0]["temp_inicial_c"] is not None) else 0.0
    horas = float(par.iloc[0]["tiempo_total_horas"]) if (not par.empty and par.iloc[0]["tiempo_total_horas"] is not None) else 4.0
    acidez_obj = float(par.iloc[0]["acidez_objetivo_pct"]) if (not par.empty and par.iloc[0]["acidez_objetivo_pct"] is not None) else None

    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("Proceso", proc or "—")
    b2.metric("Corriente", corr or "—")
    b3.metric("Capacidad", f"{cap:,.0f} L")
    b4.metric("Q MP objetivo", f"{q_ag:,.0f} kg")
    b5.metric("Temp · Tiempo", f"{temp:.0f}°C · {horas:.0f} h")
    st.caption("Temp, tiempo y acidez objetivo vienen de `dic_proceso_parametros`. Q = capacidad × densidad de la MP (se recalcula).")

    # ---------- Producto final / calidad ----------
    if proc == "PRODUCCION_ARE":
        fin = _productos_proceso(cat, sector, proc, "FINAL")  # ARE-A/B + poliglicerol (dic_proceso_producto)
        if corr and not fin.empty and "corriente" in fin.columns:
            _ff = fin[(fin["corriente"] == corr) | (fin["corriente"].isin(["", None]))]
            if not _ff.empty:
                fin = _ff
    else:
        fin = cat("SELECT id_producto, codigo_producto, nombre_producto FROM produccion.dim_producto "
                  "WHERE activo AND codigo_producto='AFE-S'")
    if fin.empty:
        fin = cat("SELECT id_producto, codigo_producto, nombre_producto FROM produccion.dim_producto "
                  "WHERE activo AND tipo_producto='FINAL' ORDER BY codigo_producto")
    fin_opts = {f"{r.codigo_producto} · {r.nombre_producto}": int(r.id_producto) for r in fin.itertuples()}
    fin_code = {int(r.id_producto): r.codigo_producto for r in fin.itertuples()}
    if len(fin_opts) == 1:
        pf_lbl = list(fin_opts.keys())[0]
        st.info(f"Producto final: **{pf_lbl}**")
    else:
        pf_lbl = st.selectbox("Producto final / calidad", list(fin_opts.keys()), key="pl_pf")
    pf_id = fin_opts[pf_lbl]
    _cal_codes = set(cat("SELECT codigo FROM produccion.dic_calidad")["codigo"].tolist())
    _raw = (fin_code.get(pf_id, "").split("-")[-1] or "").upper()
    if proc != "PRODUCCION_ARE":
        calidad = "UNICA" if "UNICA" in _cal_codes else None  # AFE = calidad única
    elif _raw in _cal_codes:
        calidad = _raw
    else:
        calidad = "UNICA" if "UNICA" in _cal_codes else None
    pct_goma = None

    # ---------- PRODUCCION_ARE: glicerina (lab) + catalizador ----------
    glicerol_v = None
    gli_ticket = None
    catal = None
    gli_idt = None    # fuente física: tanque de glicerina
    gli_tkp = None    # fuente física: ticket de portería
    if proc == "PRODUCCION_ARE":
        PMa = float(K("PMa", 282)); PMg = float(K("PMg", 92)); FE = float(K("factor_exceso_gli", 1.1))
        st.markdown("#### 2 · Glicerina (laboratorio) — define el % glicerol y la glicerina total")
        gdf = ultimas_muestras_glicerina(3) if callable(ultimas_muestras_glicerina) else pd.DataFrame()
        if gdf is not None and not gdf.empty:
            gopts = gdf.apply(lambda r: f"ticket {r['ticket']} · {r['fecha']} · glicerol {float(r['gli_glicerol'])*100:.2f}%", axis=1).tolist()
            gsel = st.selectbox("Muestra de glicerina (lab)", gopts, key="pl_gli")
            grow = gdf.iloc[gopts.index(gsel)]
            glicerol_v = float(grow["gli_glicerol"]) * 100
            gli_ticket = str(grow["ticket"])
            st.caption(f"% glicerol de la muestra: **{glicerol_v:.2f}%** (ticket {gli_ticket}).")
        else:
            st.warning("No hay muestras de GLICERINA con glicerol en laboratorio. Cargá una para estimar la glicerina.")
        catal = st.radio("Catalizador (excluyente)", ["NAOH", "POTASIO"], index=1, horizontal=True,
                         format_func=lambda x: "🧪 Soda cáustica (NaOH)" if x == "NAOH" else "🧪 Hidróxido de potasio (KOH)",
                         key="pl_catal")
        st.caption("La glicerina recuperada vuelve en la **decantación** (se registra ahí con su muestra de lab), "
                   "con cualquiera de los dos catalizadores.")
        st.markdown("**Fuente física de la glicerina a cargar** (de dónde sale)")
        gli_fuente = st.radio("Fuente de la glicerina", ["Muestra de lab (solo ticket)", "Tanque", "Ticket de portería"],
                              horizontal=True, key="pl_gli_src", label_visibility="collapsed")
        if gli_fuente == "Tanque":
            _gtk = cat("SELECT id_tanque, nombre, codigo, COALESCE(litros_actual,0) lt, COALESCE(kg_actual,0) kgs "
                       "FROM produccion.vw_tanque_panel WHERE activo AND producto_principal ILIKE 'GLICER' || '%' "
                       "ORDER BY litros_actual DESC NULLS LAST")
            if _gtk.empty:
                st.warning("No hay tanques activos con glicerina como producto principal.")
            else:
                _gop = _gtk.apply(lambda r: f"{r['nombre']} · {r['codigo']} · {r['lt']:,.0f} L ({r['kgs']:,.0f} kg)", axis=1).tolist()
                _gse = st.selectbox("Tanque de glicerina", _gop, key="pl_gli_tk")
                gli_idt = int(_gtk.iloc[_gop.index(_gse)]["id_tanque"])
        elif gli_fuente == "Ticket de portería":
            gli_tkp = (st.text_input("Ticket de portería de la glicerina", key="pl_gli_tkp",
                                     placeholder="ej. 12345") or "").strip() or None

    # ---------- Fuente de la MP (tanques filtrados por producto + lab ponderado) ----------
    st.markdown(f"#### 3 · Fuente de la materia prima ({mp})")
    st.caption("Elegí portería (tickets) y/o tanque. Los tanques se filtran por el producto y traen los parámetros de laboratorio.")
    try:
        kg_src, ports, lab_avg, corr_src = fuente_mp_combinada(mp, key_prefix="pl_mpf", target_kg=float(q_ag))
    except Exception as e:
        st.error(f"No se pudo cargar la fuente de MP: {e}")
        kg_src, ports, lab_avg, corr_src = 0.0, [], {}, None
    lab_avg = lab_avg or {}
    kg_used = float(kg_src) if (kg_src and kg_src > 0) else float(q_ag)
    acidez = (float(lab_avg["prc_acidez"]) * 100) if lab_avg.get("prc_acidez") is not None else (acidez_obj or 0.0)

    # ---------- Llenado del reactor (en LITROS) ----------
    litros_mp = (kg_used / dens) if dens else 0.0
    _pct_llen = (litros_mp / cap * 100.0) if cap else 0.0
    lc1, lc2, lc3 = st.columns(3)
    lc1.metric("MP cargada", f"{litros_mp:,.0f} L", f"{kg_used/1000:,.1f} TN")
    lc2.metric("Capacidad reactor", f"{cap:,.0f} L")
    lc3.metric("Llenado del reactor", f"{_pct_llen:.0f}%")
    st.progress(min(1.0, max(0.0, _pct_llen / 100.0)))
    just_carga = ""
    _carga_baja = bool(cap and kg_used > 0 and _pct_llen < 80.0)
    if _carga_baja:
        st.error(f"🚨 **Carga al {_pct_llen:.0f}%** de la capacidad del reactor (mínimo: 80%). "
                 "Cargar de menos es una falta grave (induce pérdidas económicas): justificá el motivo. "
                 "Se genera un ticket que el **director debe aprobar** antes de poder iniciar la producción.")
        just_carga = st.text_input("Justificación de carga baja (<80%) *", key="pl_just_carga", max_chars=250,
                                   placeholder="ej. no hay más MP disponible de esta calidad")

    # ---------- Estimados por fórmula ----------
    st.markdown("#### 4 · Insumos estimados por fórmula")
    insumos_calc = []  # (codigo_insumo, rol, kg, fuente_default)
    ajustes = {}       # ajustes manuales vs fórmula -> exigen motivo
    gli_mov = None     # glicerina como movimiento (sin codigo_insumo)
    gli_recup_kg = None  # glicerina recuperada estimada (kg) — vuelve en decantación
    if proc == "PRODUCCION_ARE":
        if kg_used > 0 and acidez > 0 and glicerol_v:
            _Fa = _formulas_sector(cat, "REACTORES")
            _Fa = _Fa[(_Fa["tipo_proceso"] == proc) & (_Fa["codigo_mp"].isin([mp, "*"]))] if not _Fa.empty else _Fa
            _fx = _selector_formula(_Fa, key=f"pl_fx_{proc}_{mp}")
            _fi = _ins_de(_fx) if _fx is not None else {}
            _fp = _params_de(_fx) if _fx is not None else {}
            # Parámetros estequiométricos: manda la FÓRMULA; fallback a dic_constante_proceso.
            FE = float(_fp.get("factor_exceso_gli") or FE)
            PMa = float(_fp.get("PMa") or PMa)
            PMg = float(_fp.get("PMg") or PMg)
            # La glicerina sale de la ACIDEZ (lab de la MP) y del %GLICEROL (muestra) — sobre MP CARGADA.
            gli_consumido = kg_used * (acidez / 100) * (PMg / (PMa * 2))   # glicerol puro que reacciona
            gli_puro = gli_consumido * FE                               # glicerol cargado (con exceso)
            est_gli = gli_puro / (glicerol_v / 100)                     # glicerina total a cargar (según pureza)
            # Glicerina recuperada: la fórmula NO la incluye por ahora -> default 0.
            # Solo se carga a mano en "Ajustar estimados" (exige motivo y queda registrada).
            gli_recup_kg = 0.0
            dens_gli = float(K("densidad_glicerina", 1.25) or 1.25)
            tn = kg_used / 1000.0   # SIEMPRE sobre los kg de MP cargada (no la capacidad del reactor)

            def _rate(cod, fallback):
                x = _fi.get(cod)
                return float(x.get("cant")) if (x and x.get("cant") is not None) else float(fallback or 0)
            est_naoh = tn * _rate("soda_kg", fila["consumo_naoh_kg_x_tn"]) if catal == "NAOH" else 0.0
            est_pot = tn * _rate("POTASIO", fila["consumo_potasio_kg_x_tn"]) if catal == "POTASIO" else 0.0
            est_fuel = tn * _rate("FUEL_OIL", fila["consumo_fuel_kg_x_tn"])
            d_fuel = DENS_INSUMO["FUEL_OIL"]
            _gli_l_form = est_gli / dens_gli
            _fuel_l_form = est_fuel / d_fuel
            _cat_form = est_naoh if catal == "NAOH" else est_pot
            with st.expander("✏️ Ajustar estimados a mano (si la fórmula no te cierra)", expanded=False):
                aj1, aj2, aj3, aj4 = st.columns(4)
                _gli_l = aj1.number_input("Glicerina (L)", 0.0, 1_000_000.0,
                                          value=float(round(_gli_l_form, 0)), step=50.0, key="pl_aj_gli")
                _cat_adj = aj2.number_input(("NaOH (kg)" if catal == "NAOH" else "KOH (kg)"), 0.0, 100_000.0,
                                            value=float(round(_cat_form, 2)), step=1.0, key=f"pl_aj_cat_{catal}")
                _fuel_l = aj3.number_input("Fuel oil (L)", 0.0, 1_000_000.0,
                                           value=float(round(_fuel_l_form, 0)), step=25.0, key="pl_aj_fuel")
                _recup_l = aj4.number_input("Glicerina recuperada (L)", 0.0, 1_000_000.0, value=0.0, step=25.0,
                                            key="pl_aj_recup",
                                            help="La fórmula no incluye recuperada por ahora (default 0). Si esperás recuperar, cargala acá: pide motivo.")
                st.caption(f"Fórmula: glicerina {_gli_l_form:,.0f} L · catalizador {_cat_form:,.2f} kg · "
                           f"fuel {_fuel_l_form:,.0f} L · recuperada 0 L (no incluida en la fórmula)")
                if st.button("🔄 Volver a los valores de fórmula", key="pl_aj_rst"):
                    for _k in ("pl_aj_gli", f"pl_aj_cat_{catal}", "pl_aj_fuel", "pl_aj_recup"):
                        st.session_state.pop(_k, None)
                    st.rerun()
            est_gli = _gli_l * dens_gli
            est_fuel = _fuel_l * d_fuel
            if catal == "NAOH":
                est_naoh = _cat_adj
            else:
                est_pot = _cat_adj
            gli_recup_kg = _recup_l * dens_gli
            if _recup_l > 0.5:
                ajustes["glicerina recuperada (L)"] = {"formula": 0, "ajustado": round(_recup_l)}
            if abs(_gli_l - _gli_l_form) > 0.5:
                ajustes["glicerina (L)"] = {"formula": round(_gli_l_form), "ajustado": round(_gli_l)}
            if abs(_cat_adj - _cat_form) > 0.01:
                ajustes["NaOH (kg)" if catal == "NAOH" else "KOH (kg)"] = {"formula": round(_cat_form, 2), "ajustado": round(_cat_adj, 2)}
            if abs(_fuel_l - _fuel_l_form) > 0.5:
                ajustes["fuel (L)"] = {"formula": round(_fuel_l_form), "ajustado": round(_fuel_l)}
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Glicerina a cargar", f"{_gli_l:,.0f} L", f"{est_gli:,.0f} kg · glicerol {glicerol_v:.0f}%")
            if catal == "NAOH":
                e2.metric("NaOH (catalizador)", f"{est_naoh:,.1f} kg")
            else:
                e2.metric("KOH (catalizador)", f"{est_pot:,.2f} kg")
            e3.metric("Glicerina recuperada", f"{gli_recup_kg/dens_gli:,.0f} L",
                      f"{gli_recup_kg:,.0f} kg · " + ("manual" if gli_recup_kg > 0 else "no incluida en fórmula"))
            e4.metric("Fuel oil", f"{_fuel_l:,.0f} L", f"{est_fuel:,.0f} kg")
            st.metric("ARE estimado", f"{kg_used/0.88:,.0f} L", f"{kg_used:,.0f} kg · {kg_used/1000:.1f} TN (sobre MP cargada)")
            st.caption("Glicerina recuperada: **la fórmula no la incluye por ahora** (default 0). "
                       "Si esperás recuperar, cargala en ✏️ Ajustar estimados — exige motivo y queda registrada.")
            st.caption(f"🧪 La glicerina sale de la **acidez {acidez:.2f}%** (lab de la fuente de MP) y del "
                       f"**glicerol {glicerol_v:.2f}%** (muestra): MP × acidez × PMg/(2·PMa) × exceso ÷ glicerol. "
                       f"Parámetros de la fórmula: exceso {FE:g} · PMa {PMa:g} · PMg {PMg:g}.")
            gli_mov = round(est_gli, 0)
            if catal == "NAOH":
                insumos_calc.append(("soda_kg", "CATALIZADOR", round(est_naoh, 1)))
            else:
                insumos_calc.append(("POTASIO", "CATALIZADOR", round(est_pot, 2)))
            insumos_calc.append(("FUEL_OIL", "INSUMO", round(est_fuel, 0)))
        else:
            st.info("Elegí la fuente de MP (para la acidez) y la muestra de glicerina (para el % glicerol) para ver los estimados.")
    else:  # DESGOMADO_ACUOSO
        _Fd = _formulas_sector(cat, "REACTORES")
        _Fd = _Fd[(_Fd["tipo_proceso"] == proc) & (_Fd["codigo_mp"].isin([mp, "*"]))] if not _Fd.empty else _Fd
        _fx = _selector_formula(_Fd, key=f"pl_fx_{proc}_{mp}")
        _fi = _ins_de(_fx) if _fx is not None else {}
        _rend_d = (float(_fx["rendimiento_pct"]) if (_fx is not None and pd.notna(_fx["rendimiento_pct"]))
                   else 100.0 - float(K("desgomado_merma_pct_esperada", 5) or 5))
        _agua_l_x_tn = float((_fi.get("AGUA") or {}).get("cant") or (float(K("desgomado_pct_agua", 5) or 5) * 10))
        fuel_rate = float((_fi.get("FUEL_OIL") or {}).get("cant") or 8.7)   # kg por TN de MP cargada
        pct_agua = _agua_l_x_tn / 10.0
        merma = 100.0 - _rend_d
        # GOMA = SEDIMENTOS reportados. Prioridad 1: promedio ponderado de la fuente
        # (lo mismo que muestra la sección de parámetros de lab). Fallback: lab de los tickets.
        _goma_def = 0.0
        _gtxt = "—"
        if lab_avg.get("prc_sedimentos") is not None and float(lab_avg["prc_sedimentos"]) > 0:
            _goma_def = round(float(lab_avg["prc_sedimentos"]) * 100, 2)
            _gtxt = "sedimentos de la fuente (promedio ponderado)"
        _tok = []
        for _p in (ports or []):
            if _p.get("fuente") == "TICKET" and _p.get("ticket"):
                _tok += [t.strip() for t in _re.split(r"[;,\s]+", str(_p["ticket"])) if t.strip()]
        # En desgomado (AFE-SG) la GOMA = SEDIMENTOS reportados en laboratorio (conclusión "SED = GOMA").
        # Fuente primaria: prc_sedimentos de los tickets elegidos; luego prc_goma_*; luego sedimentos del promedio.
        if _goma_def == 0.0 and _tok:
            try:
                _gs = cat(
                    "SELECT AVG(prc_sedimentos) sed, COUNT(prc_sedimentos) n"
                    " FROM produccion.procesos_lab"
                    " WHERE TRIM(ticket) = ANY(%s) AND prc_sedimentos IS NOT NULL AND prc_sedimentos > 0",
                    (_tok,))
                if not _gs.empty and _gs.iloc[0]["sed"] is not None:
                    _goma_def = round(float(_gs.iloc[0]["sed"]) * 100, 2)
                    _gtxt = f"sedimentos de lab · {int(_gs.iloc[0]['n'])} muestra(s)"
            except Exception:
                pass
        if _goma_def == 0.0 and _tok:
            try:
                _g = cat(
                    "SELECT AVG(gm) gm, COUNT(*) n FROM ("
                    " SELECT (COALESCE(prc_goma_abajo,0)+COALESCE(prc_goma_medio,0)+COALESCE(prc_goma_arriba,0))"
                    "        / NULLIF((prc_goma_abajo IS NOT NULL)::int+(prc_goma_medio IS NOT NULL)::int+(prc_goma_arriba IS NOT NULL)::int,0) gm"
                    " FROM produccion.procesos_lab"
                    " WHERE TRIM(ticket) = ANY(%s)"
                    "   AND (prc_goma_abajo IS NOT NULL OR prc_goma_medio IS NOT NULL OR prc_goma_arriba IS NOT NULL)"
                    ") s", (_tok,))
                if not _g.empty and _g.iloc[0]["gm"] is not None:
                    _goma_def = round(float(_g.iloc[0]["gm"]) * 100, 2)
                    _gtxt = f"goma de lab · {int(_g.iloc[0]['n'])} muestra(s)"
            except Exception:
                pass
        if _goma_def == 0.0 and lab_avg.get("prc_sedimentos") is not None:
            _goma_def = round(float(lab_avg["prc_sedimentos"]) * 100, 2)
            _gtxt = "sedimentos = goma (promedio fuente)"
        pct_goma = st.number_input("% Goma (parámetro clave del desgomado)", min_value=0.0, step=0.1,
                                   value=_goma_def, key="pl_goma",
                                   help=f"Goma = sedimentos reportados ({_gtxt}). Si la cambiás, vas a tener que indicar el motivo.")
        if abs(pct_goma - _goma_def) > 0.005:
            ajustes["% goma"] = {"formula": _goma_def, "ajustado": pct_goma}
        if _tok and _goma_def == 0.0:
            st.caption("ℹ️ Los tickets elegidos no tienen % goma cargado en laboratorio (o está en 0).")
        agua_kg = round(kg_used * pct_agua / 100.0, 1)          # agua de proceso = 5% del peso de la MP
        fuel_kg = round(kg_used / 1000.0 * fuel_rate, 1)
        afe_s = round(kg_used * (1 - merma / 100.0), 0)         # AFE-S esperado (merma 5%)
        d_fuel = DENS_INSUMO["FUEL_OIL"]
        _agua_form, _fuel_form = agua_kg, fuel_kg
        with st.expander("✏️ Ajustar estimados a mano (si la fórmula no te cierra)", expanded=False):
            aj1, aj2 = st.columns(2)
            _agua_l = aj1.number_input("Agua de proceso (L)", 0.0, 1_000_000.0,
                                       value=float(round(agua_kg, 0)), step=50.0, key="pl_aj_agua")
            _fuel_l2 = aj2.number_input("Fuel oil (L)", 0.0, 1_000_000.0,
                                        value=float(round(fuel_kg / d_fuel, 0)), step=25.0, key="pl_aj_fuel2")
            st.caption(f"Fórmula: agua {agua_kg:,.0f} L · fuel {fuel_kg/d_fuel:,.0f} L ({fuel_kg:,.0f} kg)")
            if st.button("🔄 Volver a los valores de fórmula", key="pl_aj_rst2"):
                st.session_state.pop("pl_aj_agua", None); st.session_state.pop("pl_aj_fuel2", None)
                st.rerun()
        agua_kg = round(_agua_l * 1.0, 1)
        fuel_kg = round(_fuel_l2 * d_fuel, 1)
        if abs(agua_kg - _agua_form) > 1:
            ajustes["agua (L)"] = {"formula": round(_agua_form), "ajustado": round(agua_kg)}
        if abs(fuel_kg - _fuel_form) > 1:
            ajustes["fuel (L)"] = {"formula": round(_fuel_form / d_fuel), "ajustado": round(fuel_kg / d_fuel)}
        _dens_afe = float(densidad_de("AFE-S") or 0.92) if callable(densidad_de) else 0.92
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("% Goma", f"{pct_goma:.2f}%")
        d2.metric("Agua proceso", f"{_agua_l:,.0f} L", f"{agua_kg:,.0f} kg")
        d3.metric("Fuel", f"{fuel_kg/d_fuel:,.0f} L", f"{fuel_kg:,.0f} kg")
        d4.metric("AFE-S esperado", f"{afe_s/_dens_afe:,.0f} L", f"{afe_s:,.0f} kg")
        insumos_calc.append(("AGUA", "INSUMO", agua_kg))
        insumos_calc.append(("FUEL_OIL", "INSUMO", fuel_kg))

    # ---------- Resumen de parámetros de laboratorio (de la fuente) ----------
    if lab_avg:
        st.markdown("#### 5 · Parámetros de laboratorio de la fuente (promedio ponderado)")
        m = {"prc_acidez": "Acidez %", "prc_agua": "Agua %", "prc_sedimentos": "Sedimentos %",
             "densidad__g_ml": "Densidad", "ppm_azufre": "Azufre ppm", "ppm_fosforo": "Fósforo ppm"}
        cols = st.columns(len(m))
        for i, (k, lbl) in enumerate(m.items()):
            v = lab_avg.get(k)
            if v is None:
                cols[i].metric(lbl, "—")
            elif k in ("prc_acidez", "prc_agua", "prc_sedimentos"):
                cols[i].metric(lbl, f"{float(v)*100:.2f}")
            else:
                cols[i].metric(lbl, f"{float(v):.2f}")

    motivo_ajuste = ""
    if ajustes:
        st.warning("✏️ Cambiaste a mano: **" + ", ".join(ajustes.keys()) +
                   "** (vs. fórmula). Indicá el motivo — es obligatorio y queda registrado.")
        motivo_ajuste = st.text_input("Motivo del ajuste *", key="pl_aj_motivo", max_chars=200,
                                      placeholder="ej. la MP venía con más agua de lo normal")
    obs = st.text_input("Observaciones", key="pl_obs", placeholder="opcional")

    st.divider()
    if st.button("✅ Generar ID de producción + tickets de movimiento", type="primary", use_container_width=True):
        mp_ports = [p for p in (ports or []) if float(p.get("kg", 0) or 0) > 0]
        if not mp_ports:
            st.error("Elegí una fuente de materia prima (portería o tanque) con cantidad > 0.")
            return
        if ajustes and not (motivo_ajuste or "").strip():
            st.error("Cambiaste estimados a mano: **indicá el motivo del ajuste** antes de generar.")
            return
        if _carga_baja and not (just_carga or "").strip():
            st.error("Carga menor al 80%: **justificá el motivo** para generar el ticket de aprobación del director.")
            return
        mp_id = int(mp_df[mp_df["codigo_producto"] == mp].iloc[0]["id_producto"])
        ident = siguiente_identificador("REACTORES")
        params = {
            "kg_objetivo": round(q_ag, 0), "temp_inicial_c": temp, "tiempo_horas": horas,
            "acidez_pct": round(acidez, 3), "glicerol_pct": glicerol_v, "catalizador": catal,
            "glicerina_kg": gli_mov, "glicerina_recup_kg": gli_recup_kg, "pct_goma": pct_goma,
            "insumos_estimados": {c: k for c, _, k in insumos_calc},
            "glicerina_fuente": ({"tipo": "TANQUE", "id_tanque": gli_idt} if gli_idt
                                 else {"tipo": "PORTERIA", "ticket": gli_tkp} if gli_tkp
                                 else {"tipo": "LAB", "ticket": gli_ticket}),
            "ajustes_manuales": (ajustes or None),
            "motivo_ajuste": ((motivo_ajuste or "").strip() or None),
            "carga_baja": ({"pct": round(_pct_llen, 1), "motivo": just_carga.strip()} if _carga_baja else None),
        }
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO fact_batch_proceso "
                        "(fecha, sector, id_usuario_carga, identificador_unidad, id_bien_uso, tipo_proceso, "
                        " id_producto_buscado, calidad_buscada, corriente, catalizador_tipo, "
                        " tiempo_estimado_horas, parametros_proceso, estado, id_usuario_estado, motivo_estado, observaciones) "
                        "VALUES (CURRENT_DATE,'REACTORES',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,"
                        " 'PLANIFICADO',%s,'Planificado por dirección',%s) RETURNING id_batch",
                        (uid, ident, int(fila["id_bien_uso"]), proc, pf_id, calidad, corr, catal,
                         horas, _json.dumps(params), uid, (obs or None)))
                    id_b = cur.fetchone()[0]
                    n_mov = 0
                    if _carga_baja:
                        cur.execute(
                            "INSERT INTO produccion.fact_aprobacion_carga "
                            "(id_batch, identificador, sector, equipo, capacidad_l, litros_cargados, pct_carga, motivo, solicitado_por) "
                            "VALUES (%s,%s,'REACTORES',%s,%s,%s,%s,%s,%s)",
                            (id_b, ident, fila["nombre_ui"], cap, round(litros_mp, 1), round(_pct_llen, 1),
                             just_carga.strip(), uid))

                    def _mov(rol, id_producto, prod_txt, cod_ins, fuente, idt, tkp, kg, litros):
                        fmov = "TANQUE" if fuente == "TANQUE" else "PORTERIA"
                        cur.execute(
                            "INSERT INTO fact_movimiento_stock "
                            "(momento,id_batch,identificador_prod,tipo_movimiento,rol,sentido,id_producto,producto,"
                            " codigo_insumo,fuente,id_tanque,ticket_porteria,cantidad,unidad,kg,litros,id_usuario,"
                            " origen,estado_mov,id_usuario_planifica,planificado_en) "
                            "VALUES (now(),%s,%s,'SALIDA',%s,-1,%s,%s,%s,%s,%s,%s,%s,'KG',%s,%s,%s,"
                            " 'planificacion','PLANIFICADO',%s,now())",
                            (id_b, ident, rol, id_producto, prod_txt, cod_ins, fmov, idt, tkp,
                             float(kg), float(kg), litros, uid, uid))

                    # MP (cada fuente)
                    for p in mp_ports:
                        es_tk = (p.get("fuente") == "TANQUE")
                        kg = float(p["kg"])
                        litros = round(kg / dens, 1) if dens else None
                        cur.execute(
                            "INSERT INTO fact_batch_insumo (id_batch,rol,id_producto,cantidad,unidad,fuente,id_tanque,ticket_porteria,id_usuario) "
                            "VALUES (%s,'MP',%s,%s,'KG',%s,%s,%s,%s)",
                            (id_b, mp_id, kg, ("TANQUE" if es_tk else "TICKET"),
                             (int(p["id_tanque"]) if es_tk and p.get("id_tanque") else None),
                             (None if es_tk else p.get("ticket")), uid))
                        _mov("MP", mp_id, mp, None, ("TANQUE" if es_tk else "TICKET"),
                             (int(p["id_tanque"]) if es_tk and p.get("id_tanque") else None),
                             (None if es_tk else p.get("ticket")), kg, litros)
                        n_mov += 1

                    # Glicerina: fuente física elegida (tanque / ticket de portería / muestra de lab)
                    if gli_mov and gli_mov > 0:
                        _gl_l = round(gli_mov / dens_gli, 1) if dens_gli else None
                        if gli_idt:
                            _mov("INSUMO", None, "Glicerina", None, "TANQUE", gli_idt, None, gli_mov, _gl_l)
                        elif gli_tkp:
                            _mov("INSUMO", None, "Glicerina", None, "TICKET", None, gli_tkp, gli_mov, _gl_l)
                        else:
                            _mov("INSUMO", None, "Glicerina", None, "TICKET", None, gli_ticket, gli_mov, _gl_l)
                        n_mov += 1

                    # Insumos estimados (glicerina ya arriba; catalizador/fuel) → sólo movimiento
                    # (en la planificación aún no tienen ticket/tanque confirmado; la fuente real
                    #  la define el operario al ejecutar).
                    for cod_ins, rol, kg in insumos_calc:
                        if not kg or kg <= 0:
                            continue
                        _dl_ = DENS_INSUMO.get(cod_ins)
                        _mov(rol, None, cod_ins, cod_ins, "PORTERIA", None, None, kg,
                             (round(kg / _dl_, 1) if _dl_ else None))
                        n_mov += 1
            try:
                cat.clear()
            except Exception:
                pass
            st.success(f"Producción **{ident}** (batch #{id_b}) planificada con **{n_mov} movimiento(s)** PLANIFICADO. "
                       "El operario los confirma al iniciar.")
            st.balloons()
        except Exception as e:
            st.error(f"No se pudo guardar la planificación: {e}")


def listar_planificadas(cat):
    return cat(
        "SELECT b.id_batch, b.identificador_unidad, b.sector, b.tipo_proceso, "
        "       bu.nombre_ui AS reactor, p.codigo_producto AS producto_final, "
        "       b.calidad_buscada, b.tiempo_estimado_horas, b.creado_en "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "LEFT JOIN produccion.dim_producto p ON p.id_producto=b.id_producto_buscado "
        "WHERE b.estado='PLANIFICADO' AND b.anulado IS NOT TRUE ORDER BY b.creado_en DESC")


def listar_movimientos_plan(cat, id_batch):
    return cat(
        "SELECT ticket_mov, estado_mov, rol, COALESCE(producto,codigo_insumo) AS item, "
        "       fuente, COALESCE(tanque_label,ticket_porteria) AS origen, cantidad, unidad, kg, litros "
        "FROM produccion.fact_movimiento_stock "
        "WHERE id_batch=%s AND anulado IS NOT TRUE ORDER BY id_mov_stock", (int(id_batch),))


def confirmar_movimientos_plan(cur, id_batch, uid):
    cur.execute(
        "UPDATE produccion.fact_movimiento_stock "
        "SET estado_mov='EJECUTADO', id_usuario_ejecuta=%s, ejecutado_en=now(), momento=now() "
        "WHERE id_batch=%s AND estado_mov='PLANIFICADO' AND anulado IS NOT TRUE",
        (int(uid), int(id_batch)))
    return cur.rowcount
