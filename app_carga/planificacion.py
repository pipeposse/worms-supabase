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

def _cond_val(cat, clave, default):
    """Lee un valor de dic_condicion_produccion (Condicionales); fallback al default."""
    try:
        _d = cat("SELECT valor FROM produccion.dic_condicion_produccion WHERE clave=%s", (clave,))
        if _d is not None and not _d.empty and pd.notna(_d.iloc[0]["valor"]):
            return float(_d.iloc[0]["valor"])
    except Exception:
        pass
    return default


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
                 "Cargar de menos es una falta grave. Abajo, junto al botón Generar, "
                 "tenés que **justificar el motivo**: lo aprueba el director.")

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
    if _carga_baja:
        st.error(f"🚨 Carga al {_pct:.0f}% de la bacha (<80%): justificá el motivo — va al ticket de aprobación del director.")
        just_carga = st.text_input("Justificación de carga baja (<80%) *", key="plb_just_carga", max_chars=250,
                                   placeholder="ej. no hay más MP disponible")
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


def _gli_tanques(cat, codigo):
    """Tanques activos de un producto de glicerina, con stock y parámetros de lab del tanque."""
    return cat(
        "SELECT t.id_tanque, t.nombre, t.codigo, COALESCE(s.litros_actual,0) lt, COALESCE(s.kg_actual,0) kg, "
        "       f.densidad_g_ml, f.agua_pct, "
        "       (f.parametros_extra->>'glicerol_pct')::numeric AS glicerol, "
        "       (f.parametros_extra->>'glicerina_pct')::numeric AS glicerina "
        "FROM produccion.dim_tanque t "
        "JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
        "LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
        "LEFT JOIN LATERAL (SELECT densidad_g_ml, agua_pct, parametros_extra FROM produccion.fact_param_tanque fp "
        "                   WHERE fp.id_tanque=t.id_tanque AND fp.id_producto=t.id_producto_principal "
        "                   ORDER BY actualizado_en DESC NULLS LAST LIMIT 1) f ON true "
        "WHERE t.activo AND p.codigo_producto=%s ORDER BY t.nombre", (codigo,))


def _pick_gli(cat, codigo, key, densidad_de=None, default_l=0.0):
    """Selector de UNO O VARIOS tanques de glicerina + litros por tanque.
    Devuelve un dict AGREGADO (l, kg, glicerol_kg, % ponderados) con la lista 'tanques' adentro."""
    agg = {"idt": None, "nombre": None, "l": 0.0, "dens": None, "glicerina_pct": None,
           "glicerol_pct": None, "glicerol_kg": 0.0, "kg": 0.0, "agua_pct": None, "tanques": []}
    df = _gli_tanques(cat, codigo)
    if df is None or df.empty:
        st.info("Sin tanques activos.")
        return agg
    labels = df.apply(lambda r: f"{r['nombre']} · {float(r['lt'] or 0):,.0f} L disp.", axis=1).tolist()
    sels = st.multiselect("Tanques (uno o varios)", labels, key=f"{key}_tks", label_visibility="collapsed")
    if not sels:
        return agg
    _per = (float(default_l or 0.0) / len(sels)) if default_l else 0.0
    picks = []
    for i, sname in enumerate(sels):
        r = df.iloc[labels.index(sname)]
        gpct = float(r["glicerol"]) if pd.notna(r["glicerol"]) else None
        npct = float(r["glicerina"]) if pd.notna(r["glicerina"]) else None
        dens = float(r["densidad_g_ml"]) if pd.notna(r["densidad_g_ml"]) else \
            (float(densidad_de(codigo)) if (callable(densidad_de) and densidad_de(codigo)) else 1.1)
        l = st.number_input(f"Litros · {r['nombre']}", 0.0, 1_000_000.0, value=float(_per), step=50.0,
                            key=f"{key}_l_{i}")
        kg = float(l) * dens
        picks.append({"idt": int(r["id_tanque"]), "nombre": r["nombre"], "l": float(l), "dens": dens,
                      "glicerina_pct": npct, "glicerol_pct": gpct,
                      "agua_pct": (float(r["agua_pct"]) if pd.notna(r["agua_pct"]) else None),
                      "kg": kg,
                      "glicerol_kg": kg * ((npct or 0) / 100.0) * ((gpct or 0) / 100.0)})
    tot_l = sum(p["l"] for p in picks)
    _wl = tot_l or 1.0
    agg.update({
        "tanques": picks,
        "l": tot_l,
        "kg": sum(p["kg"] for p in picks),
        "glicerol_kg": sum(p["glicerol_kg"] for p in picks),
        "glicerina_pct": sum((p["glicerina_pct"] or 0) * p["l"] for p in picks) / _wl,
        "glicerol_pct": sum((p["glicerol_pct"] or 0) * p["l"] for p in picks) / _wl,
        "agua_pct": sum((p["agua_pct"] or 0) * p["l"] for p in picks) / _wl,
        "idt": picks[0]["idt"] if picks else None,
        "nombre": ", ".join(p["nombre"] for p in picks),
        "dens": picks[0]["dens"] if picks else None,
    })
    st.caption(f"Total: {tot_l:,.0f} L · {agg['kg']:,.0f} kg · glicerol {agg['glicerol_kg']:,.0f} kg "
               f"(ponderado glicerina {agg['glicerina_pct']:.0f}% · glicerol {agg['glicerol_pct']:.0f}%)")
    return agg


_PLAN_TEXT_KEYS = {"pl_obs", "pl_aj_motivo", "pl_just_carga", "plb_obs", "plb_aj_motivo", "plb_just_carga"}


def _borrador_restaurar(cat, USR):
    """Restaura el borrador (números/notas) para no perder lo cargado tras un reinicio de la app."""
    try:
        if st.session_state.get("_plan_borr_cargado"):
            return
        st.session_state["_plan_borr_cargado"] = True
        df = cat("SELECT payload FROM produccion.plan_borrador WHERE id_usuario=%s", (int(USR["id_usuario"]),))
        if df is None or df.empty:
            return
        pl = df.iloc[0]["payload"] or {}
        if isinstance(pl, str):
            pl = _json.loads(pl)
        for k, v in (pl.items() if isinstance(pl, dict) else []):
            if k in st.session_state:
                continue
            if isinstance(v, bool):
                continue  # botones/checkbox: no se pueden (ni conviene) restaurar
            if isinstance(v, (int, float)):
                st.session_state[k] = v
            elif isinstance(v, str) and k in _PLAN_TEXT_KEYS:
                st.session_state[k] = v
    except Exception:
        pass


def _borrador_guardar(conectar, USR):
    try:
        snap = {k: v for k, v in st.session_state.items()
                if (k.startswith("pl_") or k.startswith("plb_"))
                and isinstance(v, (bool, int, float, str))}
        _js = _json.dumps(snap, sort_keys=True, default=str)
        if st.session_state.get("_plan_borr_last") == _js:
            return
        st.session_state["_plan_borr_last"] = _js
        with conectar(int(USR["id_usuario"])) as (conn, audit):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO produccion.plan_borrador (id_usuario, payload, actualizado) "
                            "VALUES (%s,%s::jsonb,now()) "
                            "ON CONFLICT (id_usuario) DO UPDATE SET payload=EXCLUDED.payload, actualizado=now()",
                            (int(USR["id_usuario"]), _js))
    except Exception:
        pass


def _borrador_limpiar(conectar, USR):
    try:
        st.session_state["_plan_borr_last"] = None
        with conectar(int(USR["id_usuario"])) as (conn, audit):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM produccion.plan_borrador WHERE id_usuario=%s", (int(USR["id_usuario"]),))
    except Exception:
        pass


def _tipo_badge(tp):
    _lbl = {"PRODUCCION_ARE": "🧴 PRODUCCIÓN ARE", "DESGOMADO_ACUOSO": "🫧 DESGOMADO ACUOSO"}.get(str(tp or ""), str(tp or "—"))
    _bg = {"PRODUCCION_ARE": "#4338ca", "DESGOMADO_ACUOSO": "#0f766e"}.get(str(tp or ""), "#334155")
    st.markdown(f"<div style='background:{_bg};border-radius:12px;padding:9px 14px;margin:2px 0 10px;"
                f"text-align:center;color:#fff;font-weight:800;letter-spacing:1.5px;font-size:1.2rem'>{_lbl}</div>",
                unsafe_allow_html=True)


def _editar_id_reaccion(USR, cat, conectar):
    st.subheader("✏️ Editar N° de reacción")
    st.caption("Cambiá el número identificador de una reacción. Queda registrado.")
    df = cat("SELECT b.id_batch, b.identificador_unidad AS ident, b.tipo_proceso, b.estado, bu.nombre_ui AS reactor "
             "FROM produccion.fact_batch_proceso b LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
             "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
             "  AND b.estado IN ('PLANIFICADO','REACCION','REPOSO','DECANTACION') ORDER BY b.creado_en DESC")
    if df is None or df.empty:
        st.info("No hay reacciones activas.")
        return
    _opt = df.apply(lambda r: f"#{r['id_batch']} · {r['ident'] or '—'} · {r['tipo_proceso']} · {r['reactor'] or '—'} · {r['estado']}", axis=1).tolist()
    sel = st.selectbox("Reacción", _opt, key="edid_sel")
    r = df.iloc[_opt.index(sel)]
    _tipo_badge(r["tipo_proceso"])
    _nid = st.text_input("Nuevo N°", value=str(r["ident"] or ""), key="edid_val")
    if st.button("💾 Guardar N°", type="primary", key="edid_go"):
        _nv = (_nid or "").strip()
        if not _nv:
            st.error("El N° no puede quedar vacío.")
            return
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_batch_proceso SET identificador_unidad=%s WHERE id_batch=%s",
                                (_nv, int(r["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(r["id_batch"]), {"ident": _nv})
            st.success(f"N° actualizado a {_nv}.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.error("No se pudo cambiar el N° (¿ya existe ese número?).")
            st.exception(e)


def _sel_reaccion_mp(cat, key, estados=("PLANIFICADO","REACCION","REPOSO","DECANTACION")):
    _est = "','".join(estados)
    df = cat("SELECT b.id_batch, b.identificador_unidad AS ident, b.tipo_proceso, b.estado, "
             "bu.nombre_ui AS reactor, COALESCE(mp.mp,'—') AS mp, COALESCE(mp.mp_tn,0) AS mp_tn "
             "FROM produccion.fact_batch_proceso b "
             "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
             "LEFT JOIN produccion.v_reaccion_mp mp ON mp.id_batch=b.id_batch "
             "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
             "  AND b.estado IN ('" + _est + "') ORDER BY b.creado_en DESC LIMIT 200")
    if df is None or df.empty:
        st.info("No hay reacciones.")
        return None
    _tp = {"PRODUCCION_ARE": "ARE", "DESGOMADO_ACUOSO": "DESGOMADO"}
    opt = df.apply(lambda r: f"#{r['id_batch']} · {r['ident'] or '—'} · {_tp.get(r['tipo_proceso'], r['tipo_proceso'] or '—')} · "
                             f"{r['reactor'] or '—'} · MP: {r['mp']} ({float(r['mp_tn']):.1f} t) · {r['estado']}", axis=1).tolist()
    sel = st.selectbox("Reacción", opt, key=key)
    return df.iloc[opt.index(sel)]


def _panel_en_marcha(USR, cat, conectar):
    st.caption("Todas las reacciones en marcha: tipo, **materia prima y cantidad**, estado, inicio y fin. "
               "Cambiá el N° directo en la tabla (rápido) y guardá.")
    df = cat("SELECT b.id_batch, b.identificador_unidad AS \"N°\", "
             " CASE b.tipo_proceso WHEN 'PRODUCCION_ARE' THEN 'ARE' WHEN 'DESGOMADO_ACUOSO' THEN 'DESGOMADO' ELSE b.tipo_proceso END AS \"Tipo\", "
             " bu.nombre_ui AS \"Reactor\", b.estado AS \"Estado\", "
             " COALESCE(mp.mp,'—') AS \"Materia prima\", COALESCE(mp.mp_tn,0) AS \"MP (t)\", "
             " COALESCE(dp.codigo_producto,'—') AS \"Producto\", "
             " round((COALESCE(NULLIF(b.parametros_proceso->>'are_objetivo_kg','')::numeric, "
             "         NULLIF(b.parametros_proceso->>'kg_objetivo','')::numeric, b.kg_obtenido, 0)/1000.0)::numeric,2) AS \"Obj. (t)\", "
             " to_char(b.inicio_ts AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS \"Inicio\", "
             " to_char(b.fin_ts AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS \"Fin\" "
             "FROM produccion.fact_batch_proceso b "
             "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
             "LEFT JOIN produccion.dim_producto dp ON dp.id_producto=b.id_producto_buscado "
             "LEFT JOIN produccion.v_reaccion_mp mp ON mp.id_batch=b.id_batch "
             "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
             "  AND b.estado IN ('PLANIFICADO','REACCION','REPOSO','DECANTACION') "
             "ORDER BY array_position(ARRAY['REACCION','DECANTACION','REPOSO','PLANIFICADO'], b.estado), b.creado_en DESC")
    if df is None or df.empty:
        st.info("No hay reacciones en marcha.")
        return
    _cnt = df["Estado"].value_counts().to_dict()
    _emj = {"PLANIFICADO":"🅿️","REACCION":"🔥","REPOSO":"🧊","DECANTACion":"🧴","DECANTACION":"🧴"}
    st.markdown("**" + str(len(df)) + " en marcha** · " + " · ".join(f"{_emj.get(k,'•')} {k}: {v}" for k, v in _cnt.items()))
    _orig = {int(df.iloc[i]["id_batch"]): str(df.iloc[i]["N°"] or "").strip() for i in range(len(df))}
    ed = st.data_editor(df.drop(columns=["id_batch"]), hide_index=True, use_container_width=True,
                        disabled=["Tipo", "Reactor", "Estado", "Materia prima", "MP (t)", "Producto", "Obj. (t)", "Inicio", "Fin"],
                        column_config={"MP (t)": st.column_config.NumberColumn(format="%.2f"),
                                       "Obj. (t)": st.column_config.NumberColumn(format="%.2f")}, key="gr_marcha_ed")
    if st.button("💾 Guardar nombres", type="primary", key="gr_marcha_save"):
        try:
            n = 0
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for i in range(len(ed)):
                        _idb = int(df.iloc[i]["id_batch"]); _new = str(ed.iloc[i]["N°"] or "").strip()
                        if _new and _new != _orig.get(_idb, ""):
                            cur.execute("UPDATE produccion.fact_batch_proceso SET identificador_unidad=%s WHERE id_batch=%s",
                                        (_new, _idb)); n += 1
                    audit.log("U", "fact_batch_proceso", 0, {"renombres": n})
            st.success(f"{n} nombre(s) actualizado(s)."); cat.clear(); st.rerun()
        except Exception as e:
            st.error("No se pudo guardar (¿algún número repetido?)."); st.exception(e)


def _panel_etapas(USR, cat, conectar):
    st.caption("Corregí los **horarios de inicio/fin de cada etapa** de una reacción (por si se cargaron mal).")
    r = _sel_reaccion_mp(cat, "gr_et_sel", estados=("PLANIFICADO","REACCION","REPOSO","DECANTACION","FINALIZADO"))
    if r is None:
        return
    idb = int(r["id_batch"])
    _ev = cat("SELECT id_evento_etapa, etapa, (inicio_ts AT TIME ZONE 'America/Argentina/Buenos_Aires') AS inicio, "
              "(fin_ts AT TIME ZONE 'America/Argentina/Buenos_Aires') AS fin "
              "FROM produccion.fact_etapa_evento WHERE id_batch=%s ORDER BY inicio_ts NULLS LAST", (idb,))
    if _ev is None or _ev.empty:
        st.info("Esta reacción no tiene etapas registradas.")
        return
    ed = st.data_editor(_ev.drop(columns=["id_evento_etapa"]), hide_index=True, use_container_width=True,
                        disabled=["etapa"], key=f"gr_et_ed_{idb}",
                        column_config={"etapa": st.column_config.TextColumn("Etapa"),
                                       "inicio": st.column_config.DatetimeColumn("Inicio", format="DD/MM/YYYY HH:mm"),
                                       "fin": st.column_config.DatetimeColumn("Fin", format="DD/MM/YYYY HH:mm")})
    if st.button("💾 Guardar horarios de etapas", type="primary", key="gr_et_save"):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for i in range(len(ed)):
                        _ide = int(_ev.iloc[i]["id_evento_etapa"])
                        _ini = ed.iloc[i]["inicio"]; _fin = ed.iloc[i]["fin"]
                        cur.execute("UPDATE produccion.fact_etapa_evento "
                                    "SET inicio_ts=(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires'), "
                                    "    fin_ts=(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') "
                                    "WHERE id_evento_etapa=%s",
                                    ((str(_ini) if pd.notna(_ini) else None),
                                     (str(_fin) if pd.notna(_fin) else None), _ide))
                audit.log("U", "fact_etapa_evento", idb, {"n": len(ed)})
            st.success("Horarios de etapas actualizados."); cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def _panel_evals(USR, cat, conectar):
    st.caption("Corregí la **fecha/hora de las evaluaciones internas** cargadas (por si se subieron con hora equivocada).")
    r = _sel_reaccion_mp(cat, "gr_ev_sel", estados=("PLANIFICADO","REACCION","REPOSO","DECANTACION","FINALIZADO"))
    if r is None:
        return
    idb = int(r["id_batch"])
    _ev = cat("SELECT id_eval, etapa, (ts AT TIME ZONE 'America/Argentina/Buenos_Aires') AS hora, "
              "COALESCE((mediciones->>'acidez'),'') AS acidez, COALESCE((mediciones->>'temperatura'),'') AS temperatura, "
              "COALESCE(observaciones,'') AS obs "
              "FROM produccion.fact_evaluacion_interna WHERE id_batch=%s AND NOT COALESCE(anulado,false) ORDER BY ts", (idb,))
    if _ev is None or _ev.empty:
        st.info("Sin evaluaciones internas cargadas para esta reacción.")
        return
    ed = st.data_editor(_ev.drop(columns=["id_eval"]), hide_index=True, use_container_width=True,
                        disabled=["etapa", "acidez", "temperatura", "obs"], key=f"gr_ev_ed_{idb}",
                        column_config={"hora": st.column_config.DatetimeColumn("Fecha/hora", format="DD/MM/YYYY HH:mm")})
    if st.button("💾 Guardar horarios de evaluaciones", type="primary", key="gr_ev_save"):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for i in range(len(ed)):
                        _ide = int(_ev.iloc[i]["id_eval"]); _h = ed.iloc[i]["hora"]
                        if pd.notna(_h):
                            cur.execute("UPDATE produccion.fact_evaluacion_interna "
                                        "SET ts=(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') WHERE id_eval=%s",
                                        (str(_h), _ide))
                audit.log("U", "fact_evaluacion_interna", idb, {"n": len(ed)})
            st.success("Horarios de evaluaciones actualizados."); cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def _crono_dt(sval, now):
    try:
        d, t = str(sval).split()
        dd, mm = (int(x) for x in d.split("/"))
        hh, mi = (int(x) for x in t.split(":"))
        cand = pd.Timestamp(year=now.year, month=mm, day=dd, hour=hh, minute=mi)
        if (now - cand).days > 180:
            cand = pd.Timestamp(year=now.year + 1, month=mm, day=dd, hour=hh, minute=mi)
        elif (cand - now).days > 180:
            cand = pd.Timestamp(year=now.year - 1, month=mm, day=dd, hour=hh, minute=mi)
        return cand
    except Exception:
        return None


_EST_KW = {"PLANIFICADO": "carga", "REACCION": "reacci", "REPOSO": "repos", "DECANTACION": "decant"}


_LIMPIEZA_ITEMS = [
    "Barrido con vapor de todas las cañerías realizado",
    "Cañerías quedaron vacías (sin producto)",
    "Bomba limpia y vacía",
    "Filtros limpios / destapados",
]


def render_checklist_limpieza(USR, cat, conectar, idb, tipo_proceso=None):
    """Checklist de limpieza post-corte de reacción (ARE). Visible/editable para operario y dirección."""
    if tipo_proceso is not None and str(tipo_proceso) != "PRODUCCION_ARE":
        st.caption("La limpieza post-corte aplica a **producción ARE**.")
        return
    _ac = cat("SELECT (NULLIF(mediciones->>'acidez',''))::float AS a "
              "FROM produccion.fact_evaluacion_interna "
              "WHERE id_batch=%s AND mediciones ? 'acidez' AND NOT COALESCE(anulado,false) "
              "ORDER BY ts DESC LIMIT 1", (int(idb),))
    _acv = float(_ac.iloc[0]["a"]) if (_ac is not None and not _ac.empty and pd.notna(_ac.iloc[0]["a"])) else None
    _cut = (_acv is not None and _acv < 13)
    _stt = cat("SELECT item, hecho FROM produccion.fact_limpieza_reactor WHERE id_batch=%s", (int(idb),))
    _done = {r["item"]: bool(r["hecho"]) for _, r in _stt.iterrows()} if (_stt is not None and not _stt.empty) else {}
    _ndone = sum(1 for it in _LIMPIEZA_ITEMS if _done.get(it))
    _total = len(_LIMPIEZA_ITEMS)
    if _cut:
        st.warning(f"🧽 **Reacción cortada (acidez {_acv:g} < 13)** — hay que hacer la **limpieza post-corte**: "
                   "barrido con vapor y que **cañerías, bomba y filtros** queden vacíos/limpios. Evita que se tape todo.")
    elif _acv is not None:
        st.caption(f"Última acidez cargada: {_acv:g} (el corte es < 13).")
    _prog = "✅ completa" if (_ndone == _total and _total > 0) else f"{_ndone}/{_total}"
    st.markdown(f"**🧽 Limpieza post-corte de reacción — {_prog}**")
    _vals = {}
    for i, it in enumerate(_LIMPIEZA_ITEMS):
        _vals[it] = st.checkbox(it, value=_done.get(it, False), key=f"lmp_{idb}_{i}")
    _obs = st.text_input("Observaciones de la limpieza", value="", key=f"lmp_obs_{idb}")
    if st.button("💾 Guardar limpieza", type="primary", key=f"lmp_save_{idb}", use_container_width=True):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for it, v in _vals.items():
                        cur.execute("INSERT INTO produccion.fact_limpieza_reactor (id_batch,item,hecho,id_usuario,ts,obs) "
                                    "VALUES (%s,%s,%s,%s,now(),%s) "
                                    "ON CONFLICT (id_batch,item) DO UPDATE SET "
                                    " hecho=EXCLUDED.hecho, id_usuario=EXCLUDED.id_usuario, ts=now(), obs=EXCLUDED.obs",
                                    (int(idb), it, bool(v), int(USR["id_usuario"]), ((_obs or "").strip() or None)))
                    audit.log("U", "fact_limpieza_reactor", int(idb), {"hechos": sum(1 for v in _vals.values() if v)})
            if all(_vals.values()):
                st.success("✅ Limpieza post-corte completa.")
            else:
                st.success("Limpieza guardada (falta completar algún ítem).")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def _recompute_final(cur, idb):
    cur.execute("UPDATE produccion.fact_batch_proceso SET kg_obtenido=("
                " SELECT COALESCE(sum(kg),0) FROM produccion.fact_batch_ticket_final "
                " WHERE id_batch=%s AND NOT COALESCE(anulado,false)) WHERE id_batch=%s", (int(idb), int(idb)))


def _ficha_final_tickets(USR, cat, conectar, idb, producto_obj):
    st.caption("Asigná los **tickets de balanza (pesadas) ya evaluados por laboratorio** del producto final. "
               "La **suma de estos tickets define los kilos finales** de la reacción (editable por ticket).")
    _pobj = (producto_obj or "").strip()
    if not _pobj:
        st.info("Esta reacción no tiene producto final definido."); return
    asg = cat("SELECT id, ticket, producto, calidad, kg FROM produccion.fact_batch_ticket_final "
              "WHERE id_batch=%s AND NOT COALESCE(anulado,false) ORDER BY ticket", (int(idb),))
    _tot_kg = float(asg["kg"].fillna(0).sum()) if (asg is not None and not asg.empty) else 0.0
    c1, c2 = st.columns(2)
    c1.metric("Producto final", _pobj)
    c2.metric("Total asignado (t)", f"{_tot_kg/1000:.2f}")
    cand = cat("SELECT tx.transaccion::text AS ticket, tx.lab_calidad AS calidad, "
               " round(abs(COALESCE(tx.peso_neto,0))::numeric,0) AS kg, tx.fecha_entrada AS fecha "
               "FROM produccion.v_transacciones_limpias tx "
               "WHERE tx.evaluado='SI' AND tx.peso_neto IS NOT NULL "
               "  AND upper(COALESCE(tx.lab_producto,'')||'-'||COALESCE(tx.lab_calidad,''))=upper(%s) "
               "  AND NOT EXISTS (SELECT 1 FROM produccion.fact_batch_ticket_final f "
               "                  WHERE f.ticket=tx.transaccion::text AND NOT COALESCE(f.anulado,false)) "
               "ORDER BY tx.fecha_entrada DESC NULLS LAST, tx.transaccion DESC LIMIT 200", (_pobj,))
    st.markdown(f"**Tickets pesados disponibles** (evaluados como {_pobj})")
    if cand is not None and not cand.empty:
        _copt = cand.apply(lambda r: f"#{r['ticket']} · {float(r['kg'] or 0)/1000:.2f} t · cal {r['calidad'] or '-'} · {r['fecha']}", axis=1).tolist()
        _selc = st.multiselect("Elegí tickets para asignar", _copt, key=f"pf_sel_{idb}")
        if st.button("➕ Asignar seleccionados", type="primary", key=f"pf_add_{idb}", use_container_width=True) and _selc:
            try:
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        for _sc in _selc:
                            _rc = cand.iloc[_copt.index(_sc)]
                            cur.execute("INSERT INTO produccion.fact_batch_ticket_final "
                                        "(id_batch,ticket,producto,calidad,kg,fecha,id_usuario) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                                        "ON CONFLICT (ticket) WHERE anulado=false DO NOTHING",
                                        (int(idb), str(_rc["ticket"]), _pobj, _rc["calidad"], float(_rc["kg"] or 0),
                                         (str(_rc["fecha"]) if pd.notna(_rc["fecha"]) else None), int(USR["id_usuario"])))
                        _recompute_final(cur, int(idb))
                        audit.log("I", "fact_batch_ticket_final", int(idb), {"asignados": len(_selc)})
                st.success(f"{len(_selc)} ticket(s) asignados."); cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
    else:
        st.caption("No hay tickets pesados sin asignar para este producto. Podés agregar uno manual abajo.")
    with st.expander("➕ Agregar ticket manual"):
        _mt = st.text_input("N° de ticket", key=f"pf_mt_{idb}")
        _mk = st.number_input("Kilos (si lo dejás vacío, se busca de balanza)", min_value=0.0, value=None, step=10.0, format="%g", key=f"pf_mk_{idb}")
        _mc = st.text_input("Calidad", value="", key=f"pf_mc_{idb}")
        if st.button("➕ Asignar manual", key=f"pf_addman_{idb}"):
            _mtv = (_mt or "").strip()
            if not _mtv:
                st.warning("Poné el N° de ticket.")
            else:
                try:
                    _kgv = _mk; _calv = (_mc or "").strip() or None
                    if _kgv is None:
                        _look = cat("SELECT round(abs(COALESCE(peso_neto,0))::numeric,0) AS kg, lab_calidad "
                                    "FROM produccion.v_transacciones_limpias WHERE transaccion::text=%s LIMIT 1", (_mtv,))
                        if _look is not None and not _look.empty:
                            _kgv = float(_look.iloc[0]["kg"] or 0)
                            if not _calv: _calv = _look.iloc[0]["lab_calidad"]
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO produccion.fact_batch_ticket_final (id_batch,ticket,producto,calidad,kg,id_usuario) "
                                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (ticket) WHERE anulado=false DO NOTHING",
                                        (int(idb), _mtv, _pobj, _calv, float(_kgv or 0), int(USR["id_usuario"])))
                            _recompute_final(cur, int(idb))
                    st.success("Ticket asignado."); cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)
    if asg is not None and not asg.empty:
        st.markdown("**Tickets asignados** (editá los kilos o marcá *Quitar*)")
        _disp = asg.copy(); _disp["Quitar"] = False
        _disp = _disp.rename(columns={"ticket": "Ticket", "producto": "Producto", "calidad": "Calidad", "kg": "Kg"})
        edp = st.data_editor(_disp[["Ticket", "Producto", "Calidad", "Kg", "Quitar"]], hide_index=True, use_container_width=True,
                             disabled=["Ticket", "Producto", "Calidad"], key=f"pf_ed_{idb}",
                             column_config={"Kg": st.column_config.NumberColumn(format="%g"),
                                            "Quitar": st.column_config.CheckboxColumn()})
        if st.button("💾 Guardar (definir kilos finales por estos tickets)", type="primary", key=f"pf_save_{idb}", use_container_width=True):
            try:
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        for i in range(len(edp)):
                            _idr = int(asg.iloc[i]["id"])
                            if bool(edp.iloc[i]["Quitar"]):
                                cur.execute("UPDATE produccion.fact_batch_ticket_final SET anulado=true WHERE id=%s", (_idr,))
                            else:
                                cur.execute("UPDATE produccion.fact_batch_ticket_final SET kg=%s WHERE id=%s",
                                            (float(edp.iloc[i]["Kg"] or 0), _idr))
                        _recompute_final(cur, int(idb))
                        audit.log("U", "fact_batch_ticket_final", int(idb), {"n": len(edp)})
                st.success("Kilos finales actualizados por los tickets."); cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
        st.caption(f"⚖️ **Kilos finales de la reacción = {_tot_kg:,.0f} kg ({_tot_kg/1000:.2f} t)** — suma de los tickets asignados.")


@st.dialog("🗂️ Ficha de reacción", width="large")
def _dlg_reaccion(USR, cat, conectar, idb):
    info = cat("SELECT identificador_unidad AS ident, estado, tipo_proceso, "
               " et.etiqueta, bu.nombre_ui AS reactor, dpb.codigo_producto AS producto_obj, b.kg_obtenido, "
               " (b.inicio_ts AT TIME ZONE 'America/Argentina/Buenos_Aires') AS inicio_local, "
               " b.parametros_proceso, "
               " COALESCE(b.tanque_destino,'') AS destino "
               "FROM produccion.fact_batch_proceso b "
               "LEFT JOIN produccion.v_reaccion_etiqueta et ON et.id_batch=b.id_batch "
               "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
               "LEFT JOIN produccion.dim_producto dpb ON dpb.id_producto=b.id_producto_buscado "
               "WHERE b.id_batch=%s", (int(idb),))
    if info is None or info.empty:
        st.error("No se encontró la reacción."); return
    b = info.iloc[0]
    _tp = str(b["tipo_proceso"] or "")
    _tp_lbl = {"PRODUCCION_ARE": "🧴 PRODUCCIÓN ARE", "DESGOMADO_ACUOSO": "🫧 DESGOMADO ACUOSO"}.get(_tp, _tp or "—")
    st.markdown(f"### {b['ident']}  \n{b['etiqueta'] or '—'}")
    st.caption(f"{_tp_lbl} · estado **{b['estado']}**")
    t0, t1, t2, t3, tPF, tLM, t4 = st.tabs(["📄 Resumen", "📝 Nombre & inicio", "🧫 Evaluación interna", "🎯 Destino final", "🏁 Producto final (tickets)", "🧽 Limpieza post-corte", "⏯️ Trabajar"])

    with t0:
        _rp = b.get("parametros_proceso")
        if isinstance(_rp, str):
            try: _rp = _json.loads(_rp)
            except Exception: _rp = {}
        _rp = _rp or {}
        _obj_kg = _rp.get("are_objetivo_kg") or _rp.get("kg_objetivo")
        try: _obj_tn = float(_obj_kg) / 1000.0 if _obj_kg else None
        except (TypeError, ValueError): _obj_tn = None
        _mov = cat("SELECT m.rol, COALESCE(m.producto, m.codigo_insumo, '—') AS item, "
                   " COALESCE(NULLIF(m.tanque_label,''), dt.nombre, "
                   "   CASE WHEN m.ticket_porteria IS NOT NULL THEN 'Ticket portería ' || m.ticket_porteria END, "
                   "   CASE WHEN m.ticket_lab IS NOT NULL THEN 'Ticket lab ' || m.ticket_lab END, "
                   "   CASE m.fuente WHEN 'TANQUE' THEN 'Tanque (sin especificar)' WHEN 'TICKET' THEN 'Ticket de portería' ELSE NULLIF(m.fuente,'') END, '—') AS origen, "
                   " round((abs(COALESCE(m.kg,0))/1000.0)::numeric,2) AS tn, "
                   " round(abs(COALESCE(m.litros,0))::numeric,0) AS litros, "
                   " round(abs(COALESCE(m.cantidad,0))::numeric,1) AS cantidad, COALESCE(m.unidad,'') AS unidad "
                   "FROM produccion.fact_movimiento_stock m "
                   "LEFT JOIN produccion.dim_tanque dt ON dt.id_tanque=m.id_tanque "
                   "WHERE m.id_batch=%s AND COALESCE(m.anulado,false)=false "
                   "ORDER BY array_position(ARRAY['MP','INSUMO','CATALIZADOR','FINAL','SUBPRODUCTO'], m.rol) NULLS LAST, item", (int(idb),))
        _mp_tn = float(_mov[_mov["rol"] == "MP"]["tn"].sum()) if (_mov is not None and not _mov.empty) else 0.0
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Reactor", b.get("reactor") or "—")
        m2.metric("Producto objetivo", b.get("producto_obj") or "—")
        m3.metric("MP inicial (t)", f"{_mp_tn:.2f}")
        _real_kg = b.get("kg_obtenido")
        try: _real_tn = float(_real_kg)/1000.0 if _real_kg else None
        except (TypeError, ValueError): _real_tn = None
        m4.metric("Final (t)", f"{_real_tn:.2f}" if _real_tn else (f"{_obj_tn:.2f}" if _obj_tn else "—"),
                  help="Real por tickets de balanza si hay; si no, la prevista por fórmula.")
        if _real_tn and _obj_tn:
            st.caption(f"⚖️ Final real por tickets: **{_real_tn:.2f} t** · prevista por fórmula: {_obj_tn:.2f} t")
        if _rp.get("formula_nombre"):
            st.caption(f"🧪 Fórmula: **{_rp['formula_nombre']}**")
        if _rp.get("inicio_programado"):
            try:
                st.caption(f"🗓️ Inicio programado: **{pd.to_datetime(_rp['inicio_programado']).strftime('%d/%m/%Y %H:%M')}**")
            except Exception:
                pass
        if _mov is None or _mov.empty:
            st.info("Esta reacción todavía no tiene movimientos de materia prima / insumos cargados.")
        else:
            _mpd = _mov[_mov["rol"] == "MP"]
            if not _mpd.empty:
                st.markdown("**Materia prima — de dónde vino**")
                _tmp = _mpd[["item", "origen", "tn", "litros"]].rename(
                    columns={"item": "Producto", "origen": "De dónde vino", "tn": "t", "litros": "Litros"})
                st.dataframe(_tmp, hide_index=True, use_container_width=True,
                             column_config={"t": st.column_config.NumberColumn(format="%.2f")})
            _ins = _mov[_mov["rol"].isin(["INSUMO", "CATALIZADOR"])].copy()
            if not _ins.empty:
                def _cant(r):
                    if r["cantidad"] and r["cantidad"] > 0: return f"{r['cantidad']:g} {r['unidad']}".strip()
                    if r["litros"] and r["litros"] > 0: return f"{r['litros']:g} L"
                    if r["tn"] and r["tn"] > 0: return f"{r['tn']:g} t"
                    return "—"
                _ins["Cantidad"] = _ins.apply(_cant, axis=1)
                st.markdown("**Insumos y catalizador — de dónde vinieron**")
                _tin = _ins[["item", "origen", "Cantidad"]].rename(columns={"item": "Insumo", "origen": "De dónde vino"})
                st.dataframe(_tin, hide_index=True, use_container_width=True)
        st.caption("Editá nombre/inicio, evaluación interna y destino en las otras solapas.")

    with t1:
        _nid = st.text_input("N° / nombre de la reacción", value=str(b["ident"] or ""), key=f"dlg_nid_{idb}")
        _pp = b.get("parametros_proceso")
        if isinstance(_pp, str):
            try: _pp = _json.loads(_pp)
            except Exception: _pp = {}
        _pp = _pp or {}
        _prog = _pp.get("inicio_programado")
        _ini = b["inicio_local"]
        _ini_ts = pd.to_datetime(_ini) if pd.notna(_ini) else None
        # arranque de referencia: programado > inicio_ts real
        _ref = pd.to_datetime(_prog, errors="coerce") if _prog else None
        if _ref is None or pd.isna(_ref):
            _ref = _ini_ts
        st.caption("Cambiá el inicio para **posponer/adelantar** la reacción. Si dejás tildado *recalcular etapas*, "
                   "se corre todo el cronograma (y la ETA/semáforo del tablero) por la misma diferencia.")
        if _ref is not None:
            st.caption(f"Inicio actual: **{pd.to_datetime(_ref).strftime('%d/%m/%Y %H:%M')}**")
        cA, cB = st.columns(2)
        _dref = pd.to_datetime(_ref) if _ref is not None else None
        _d = cA.date_input("Nueva fecha de inicio", value=(_dref.date() if _dref is not None else None), key=f"dlg_d_{idb}", format="DD/MM/YYYY")
        _t = cB.time_input("Nueva hora de inicio", value=(_dref.time() if _dref is not None else None), key=f"dlg_t_{idb}", step=300)
        _reprog = st.checkbox("Recalcular etapas (posponer todo el cronograma)", value=True, key=f"dlg_reprog_{idb}")
        if st.button("💾 Guardar nombre y horario", type="primary", key=f"dlg_save1_{idb}", use_container_width=True):
            try:
                _new_start = pd.Timestamp(f"{_d.isoformat()} {_t.strftime('%H:%M:%S')}") if (_d is not None and _t is not None) else None
                _delta = (_new_start - pd.to_datetime(_ref)) if (_new_start is not None and _ref is not None and pd.notna(_ref)) else None
                _now_r = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").tz_localize(None)
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        _nv = (_nid or "").strip()
                        if _nv and _nv != str(b["ident"] or "").strip():
                            cur.execute("UPDATE produccion.fact_batch_proceso SET identificador_unidad=%s WHERE id_batch=%s", (_nv, int(idb)))
                        if _new_start is not None:
                            _iso = _new_start.strftime("%Y-%m-%d %H:%M:%S")
                            cur.execute("UPDATE produccion.fact_batch_proceso "
                                        "SET inicio_ts=(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') WHERE id_batch=%s",
                                        (_iso, int(idb)))
                            if _reprog and _delta is not None and abs(_delta.total_seconds()) >= 60:
                                _crono = _pp.get("cronograma") or []
                                for _e in _crono:
                                    for _campo in ("Inicio", "Fin"):
                                        _dt0 = _crono_dt(_e.get(_campo), _now_r)
                                        if _dt0 is not None:
                                            _e[_campo] = (_dt0 + _delta).strftime("%d/%m %H:%M")
                                _pp["cronograma"] = _crono
                                _pp["inicio_programado"] = _new_start.strftime("%Y-%m-%dT%H:%M:%S")
                                cur.execute("UPDATE produccion.fact_batch_proceso SET parametros_proceso=%s::jsonb WHERE id_batch=%s",
                                            (_json.dumps(_pp), int(idb)))
                                _secs = int(_delta.total_seconds())
                                cur.execute("UPDATE produccion.fact_etapa_evento "
                                            "SET inicio_ts = inicio_ts + %s * interval '1 second', "
                                            "    fin_ts = CASE WHEN fin_ts IS NULL THEN NULL ELSE fin_ts + %s * interval '1 second' END "
                                            "WHERE id_batch=%s", (_secs, _secs, int(idb)))
                        audit.log("U", "fact_batch_proceso", int(idb),
                                  {"ficha": "nombre/inicio", "reprogramado": bool(_reprog and _delta is not None),
                                   "delta_h": (round(_delta.total_seconds()/3600.0, 1) if _delta is not None else None)})
                if _delta is not None and abs(_delta.total_seconds()) >= 60 and _reprog:
                    st.success(f"Reacción reprogramada {_delta.total_seconds()/3600.0:+.1f} h (cronograma y etapas corridos).")
                else:
                    st.success("Guardado.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.error("No se pudo guardar (¿N° repetido?)."); st.exception(e)

    with t2:
        _et_opts = ["Carga", "Reacción", "Reposo", "Decantación", "Acopio final"]
        _et_def = {"PLANIFICADO": "Carga", "REACCION": "Reacción", "REPOSO": "Reposo", "DECANTACION": "Decantación"}.get(str(b["estado"]), "Reacción")
        _et = st.selectbox("Etapa", _et_opts, index=_et_opts.index(_et_def) if _et_def in _et_opts else 1, key=f"dlg_et_{idb}")
        _now_ev = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").tz_localize(None)
        cF, cH = st.columns(2)
        _ed = cF.date_input("Fecha de la evaluación", value=_now_ev.date(), key=f"dlg_evd_{idb}", format="DD/MM/YYYY")
        _eh = cH.time_input("Hora de la evaluación", value=_now_ev.time().replace(second=0, microsecond=0), key=f"dlg_evh_{idb}", step=300)
        _ops = cat("SELECT id_usuario, nombre FROM produccion.dim_usuario "
                   "WHERE COALESCE(activo,true) AND rol IN ('OPERADOR','SUPERVISOR','ADMIN') ORDER BY nombre")
        _opnames = _ops["nombre"].tolist() if (_ops is not None and not _ops.empty) else []
        _defop = str(USR.get("nombre") or "")
        if _opnames:
            _oper = st.selectbox("Operario a cargo", _opnames,
                                 index=(_opnames.index(_defop) if _defop in _opnames else 0), key=f"dlg_evop_{idb}")
            _opid = int(_ops.iloc[_opnames.index(_oper)]["id_usuario"])
        else:
            _oper = st.text_input("Operario a cargo", value=_defop, key=f"dlg_evopt_{idb}")
            _opid = None
        c1, c2 = st.columns(2)
        _ac = c1.number_input("Acidez (%)", value=None, step=0.1, format="%g", key=f"dlg_ac_{idb}")
        _tp_c = c2.number_input("Temperatura (°C)", value=None, step=1.0, format="%g", key=f"dlg_tmp_{idb}")
        _obs = st.text_area("Observaciones", key=f"dlg_obs_{idb}")
        if st.button("💾 Guardar evaluación interna", type="primary", key=f"dlg_save2_{idb}", use_container_width=True):
            med = {}
            if _ac is not None: med["acidez"] = float(_ac)
            if _tp_c is not None: med["temperatura"] = float(_tp_c)
            if _oper: med["operario"] = _oper
            if not med and not (_obs or "").strip():
                st.warning("Cargá al menos una medición o una observación.")
            else:
                try:
                    _iso_ev = f"{_ed.isoformat()} {_eh.strftime('%H:%M:%S')}"
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO produccion.fact_evaluacion_interna "
                                        "(id_batch, id_usuario, etapa, ts, mediciones, observaciones) "
                                        "VALUES (%s,%s,%s,(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires'),%s::jsonb,%s)",
                                        (int(idb), int(_opid or USR["id_usuario"]), _et, _iso_ev,
                                         _json.dumps(med), (_obs or "").strip() or None))
                            audit.log("I", "fact_evaluacion_interna", int(idb), {"etapa": _et, "operario": _oper, **med})
                    st.success("Evaluación interna cargada."); cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    with t3:
        _tks = cat("SELECT id_tanque, codigo, nombre FROM produccion.dim_tanque WHERE COALESCE(activo,true) ORDER BY nombre")
        if _tks is None or _tks.empty:
            st.info("No hay tanques.")
        else:
            _opt = _tks.apply(lambda r: f"{r['nombre']} · {r['codigo']}", axis=1).tolist()
            _cur = str(b["destino"] or "")
            _idx = next((i for i, o in enumerate(_opt) if _cur and (_cur in o or o in _cur)), None)
            st.caption(f"Destino actual: **{_cur or '—'}**")
            _seldest = st.selectbox("Tanque de destino final", _opt, index=(_idx if _idx is not None else 0), key=f"dlg_dest_{idb}")
            if st.button("💾 Guardar destino final", type="primary", key=f"dlg_save3_{idb}", use_container_width=True):
                _rr = _tks.iloc[_opt.index(_seldest)]
                try:
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("UPDATE produccion.fact_batch_proceso SET tanque_destino=%s WHERE id_batch=%s",
                                        (f"{_rr['nombre']} · {_rr['codigo']}", int(idb)))
                            if _tp == "DESGOMADO_ACUOSO":
                                cur.execute("UPDATE produccion.fact_batch_proceso SET desg_id_tanque_destino=%s WHERE id_batch=%s",
                                            (int(_rr["id_tanque"]), int(idb)))
                            audit.log("U", "fact_batch_proceso", int(idb), {"destino": _rr["codigo"]})
                    st.success("Destino final guardado."); cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    with tPF:
        _ficha_final_tickets(USR, cat, conectar, int(idb), b.get("producto_obj"))

    with tLM:
        render_checklist_limpieza(USR, cat, conectar, int(idb), b.get("tipo_proceso"))

    with t4:
        st.caption("Para el flujo completo (arrancar, cargar muestras paso a paso, decantar) usá la pestaña "
                   "**Trabajar** del panel. Esta ficha es para ediciones rápidas.")

    if str(USR.get("rol") or "") in ROLES_DIRECCION:
        st.divider()
        with st.expander("🗑️ Eliminar esta reacción"):
            st.caption("Anula la reacción y sus movimientos de stock (soft-delete, reversible en base). "
                       "Desaparece del tablero y deja de contar. No se puede deshacer desde acá.")
            _delck = st.checkbox(f"Confirmo eliminar {b['ident']}", key=f"dlg_del_ck_{idb}")
            if st.button("🗑️ Eliminar definitivamente", disabled=not _delck, key=f"dlg_del_go_{idb}", use_container_width=True):
                try:
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("UPDATE produccion.fact_batch_proceso SET anulado=true WHERE id_batch=%s", (int(idb),))
                            cur.execute("UPDATE produccion.fact_movimiento_stock SET anulado=true WHERE id_batch=%s", (int(idb),))
                            cur.execute("UPDATE produccion.fact_batch_ticket_final SET anulado=true WHERE id_batch=%s", (int(idb),))
                            audit.log("D", "fact_batch_proceso", int(idb), {"eliminada": str(b["ident"])})
                    st.success(f"Reacción {b['ident']} eliminada.")
                    st.session_state.pop("gr_tab_df", None)
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)


def _panel_tablero(USR, cat, conectar):
    st.caption("Centro de mando: cada reacción con su **etiqueta**, MP → producto (t), próxima etapa, ETA y "
               "**semáforo de atraso** (🔴 atrasada · 🟡 por vencer · 🟢 a tiempo), comparando el reloj real con el cronograma.")
    df = cat("SELECT b.id_batch, b.identificador_unidad AS ident, et.etiqueta, "
             " CASE b.tipo_proceso WHEN 'PRODUCCION_ARE' THEN 'ARE' WHEN 'DESGOMADO_ACUOSO' THEN 'DESGOMADO' ELSE b.tipo_proceso END AS tipo, "
             " bu.nombre_ui AS reactor, b.estado, "
             " COALESCE(mp.mp,'—') AS mp, COALESCE(mp.mp_tn,0) AS mp_tn, "
             " COALESCE(dp.codigo_producto,'—') AS producto, "
             " round((COALESCE(NULLIF(b.parametros_proceso->>'are_objetivo_kg','')::numeric, "
             "         NULLIF(b.parametros_proceso->>'kg_objetivo','')::numeric, b.kg_obtenido, 0)/1000.0)::numeric,2) AS obj_tn, "
             " b.parametros_proceso "
             "FROM produccion.fact_batch_proceso b "
             "LEFT JOIN produccion.v_reaccion_etiqueta et ON et.id_batch=b.id_batch "
             "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
             "LEFT JOIN produccion.dim_producto dp ON dp.id_producto=b.id_producto_buscado "
             "LEFT JOIN produccion.v_reaccion_mp mp ON mp.id_batch=b.id_batch "
             "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
             "  AND b.estado IN ('PLANIFICADO','REACCION','REPOSO','DECANTACION') "
             "ORDER BY array_position(ARRAY['REACCION','DECANTACION','REPOSO','PLANIFICADO'], b.estado), b.creado_en DESC")
    if df is None or df.empty:
        st.info("No hay reacciones en marcha.")
        return
    now = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").tz_localize(None)
    rows = []; n_atras = 0; _gantt = []
    for _, r in df.iterrows():
        pp = r["parametros_proceso"]
        if isinstance(pp, str):
            try: pp = _json.loads(pp)
            except Exception: pp = {}
        pp = pp or {}
        crono = pp.get("cronograma") or []
        _stages = []
        for e in crono:
            _s = _crono_dt(e.get("Inicio"), now); _f = _crono_dt(e.get("Fin"), now)
            if _s is not None and _f is not None and _f > _s:
                _nm = str(e.get("Etapa", "")).split(" · ")[0]
                _stages.append((_nm, _s, _f))
        _gantt.append({"reactor": r["reactor"] or "—", "label": (r["ident"] or "") ,
                       "sub": (r["mp"] or "—"), "estado": r["estado"], "stages": _stages})
        kw = _EST_KW.get(str(r["estado"]), "")
        cur_i = None
        for i, e in enumerate(crono):
            if kw and kw in str(e.get("Etapa", "")).lower():
                cur_i = i; break
        eta = prox = "—"; sem = "⚪"; atraso_h = None
        if cur_i is not None:
            fin = _crono_dt(crono[cur_i].get("Fin"), now)
            if cur_i + 1 < len(crono):
                prox = str(crono[cur_i + 1].get("Etapa", "")).split(" · ")[0]
            if fin is not None:
                eta = fin.strftime("%d/%m %H:%M")
                dh = (now - fin).total_seconds() / 3600.0
                if dh > 0.5:
                    sem = "🔴"; atraso_h = round(dh, 1); n_atras += 1
                elif dh > -2:
                    sem = "🟡"
                else:
                    sem = "🟢"
        rows.append({"⚑": sem, "N°": r["ident"], "Reacción": r["etiqueta"], "Estado": r["estado"],
                     "MP": r["mp"], "MP (t)": float(r["mp_tn"] or 0), "→ Producto": r["producto"],
                     "Obj (t)": float(r["obj_tn"] or 0), "Próxima etapa": prox, "ETA": eta,
                     "Atraso (h)": atraso_h})
    disp = pd.DataFrame(rows)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("En marcha", len(disp))
    k2.metric("MP en proceso (t)", f"{disp['MP (t)'].sum():.1f}")
    k3.metric("Objetivo (t)", f"{disp['Obj (t)'].sum():.1f}")
    k4.metric("🔴 Atrasadas", n_atras)
    st.caption("👉 Hacé **clic en una fila** para abrir la ficha (nombre, hora de inicio, evaluación interna, destino final).")
    ids = [int(x) for x in df["id_batch"].tolist()]
    _evt = st.dataframe(disp, hide_index=True, use_container_width=True, on_select="rerun",
                        selection_mode="single-row", key="gr_tab_df",
                        column_config={"MP (t)": st.column_config.NumberColumn(format="%.2f"),
                                       "Obj (t)": st.column_config.NumberColumn(format="%.2f"),
                                       "Atraso (h)": st.column_config.NumberColumn(format="%.1f")})
    try:
        _rowsel = list(_evt.selection["rows"])
    except Exception:
        _rowsel = []
    _render_gantt(_gantt, now)
    if _rowsel:
        _dlg_reaccion(USR, cat, conectar, ids[_rowsel[0]])


_STAGE_COLOR = [("carga", "#64748b"), ("reacci", "#ef4444"), ("repos", "#3b82f6"),
                ("decant", "#a855f7"), ("acopio", "#16a34a")]


def _stage_color(nm):
    n = (nm or "").lower()
    for kw, c in _STAGE_COLOR:
        if kw in n:
            return c
    return "#9ca3af"


def _render_gantt(items, now):
    stages_all = [st_ for it in items for st_ in it["stages"]]
    if not stages_all:
        return
    t0 = min(s[1] for s in stages_all); t1 = max(s[2] for s in stages_all)
    lo = min(t0, now - pd.Timedelta(hours=2)); hi = max(t1, now + pd.Timedelta(hours=2))
    span = (hi - lo).total_seconds()
    if span <= 0:
        return

    def pct(ts):
        return max(0.0, min(100.0, (ts - lo).total_seconds() / span * 100.0))

    st.markdown("##### 📅 Línea de tiempo por reactor")
    # leyenda
    leg = " ".join(f"<span style='display:inline-block;width:11px;height:11px;border-radius:3px;background:{c};"
                   f"vertical-align:middle;margin:0 4px 0 10px'></span>{kw.capitalize()}" for kw, c in _STAGE_COLOR)
    st.markdown(f"<div style='font-size:.8rem;color:#475569;margin:2px 0 8px'>{leg}</div>", unsafe_allow_html=True)
    now_pct = pct(now)
    # agrupar por reactor
    reactores = {}
    for it in items:
        reactores.setdefault(it["reactor"], []).append(it)
    html = ["<div style='border:1px solid #e5e7eb;border-radius:12px;padding:10px 12px;background:#fff'>"]
    html.append(f"<div style='font-size:.72rem;color:#64748b;margin-bottom:2px'>{lo.strftime('%d/%m %H:%M')} "
                f"&rarr; {hi.strftime('%d/%m %H:%M')} &middot; línea roja = ahora</div>")
    for reactor, its in reactores.items():
        html.append(f"<div style='font-weight:800;margin:8px 0 2px;color:#0f172a'>{reactor}</div>")
        for it in its:
            bars = ""
            for nm, sdt, fdt in it["stages"]:
                left = pct(sdt); width = max(0.6, pct(fdt) - left)
                bars += (f"<div title='{nm} {sdt.strftime('%d/%m %H:%M')}→{fdt.strftime('%H:%M')}' "
                         f"style='position:absolute;left:{left:.2f}%;width:{width:.2f}%;top:3px;height:16px;"
                         f"background:{_stage_color(nm)};border-radius:3px'></div>")
            html.append(
                f"<div style='display:flex;align-items:center;gap:8px;margin:3px 0'>"
                f"<div style='flex:0 0 190px;font-size:.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>"
                f"<b>{it['label']}</b> · {it['sub']}</div>"
                f"<div style='position:relative;flex:1;height:22px;background:#f1f5f9;border-radius:4px'>"
                f"{bars}"
                f"<div style='position:absolute;left:{now_pct:.2f}%;top:-2px;height:26px;width:2px;background:#dc2626'></div>"
                f"</div></div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _terminadas_sugerencias(df, cat):
    """Sugerencia de kg real por variación de tanque, prorrateada por fórmula entre reacciones que comparten tanque+día."""
    sug = {}
    _need = df[(df["tickets_kg"].fillna(0) <= 0) & df["id_tanque_destino"].notna() & df["cierre_ts"].notna()].copy()
    if _need.empty:
        return sug
    _need["_d"] = _need["cierre_ts"].dt.date
    _cache = {}
    def _snaps(idt):
        if idt not in _cache:
            _cache[idt] = cat("SELECT medido_en, litros::float AS litros FROM produccion.fact_stock_tanque "
                              "WHERE id_tanque=%s AND litros IS NOT NULL ORDER BY medido_en", (int(idt),))
        return _cache[idt]
    for (idt, _d), grp in _need.groupby(["id_tanque_destino", "_d"]):
        _s = _snaps(idt)
        if _s is None or _s.empty:
            continue
        _s = _s.copy(); _s["medido_en"] = pd.to_datetime(_s["medido_en"])
        cmin = grp["cierre_ts"].min(); cmax = grp["cierre_ts"].max()
        _bef = _s[_s["medido_en"] <= cmin]; _aft = _s[_s["medido_en"] >= cmax]
        if _bef.empty or _aft.empty:
            continue
        net_l = float(_aft.iloc[0]["litros"]) - float(_bef.iloc[-1]["litros"])
        dens = float(grp.iloc[0]["densidad"] or 0.91)
        net_kg = net_l * dens
        _w = grp["formula_kg"].fillna(grp["objetivo_kg"]).fillna(0).astype(float)
        _wsum = float(_w.sum())
        for i in range(len(grp)):
            share = (float(_w.iloc[i]) / _wsum) if _wsum > 0 else (1.0 / len(grp))
            sug[int(grp.iloc[i]["id_batch"])] = max(0.0, net_kg * share)
    return sug


def _reacciones_terminadas(USR, cat, conectar):
    st.subheader("🏁 Reacciones terminadas — objetivo vs real")
    st.caption("Máximo por reactor · objetivo/fórmula · real por tickets de pesada · real por variación de tanque. "
               "Para ARE sin tickets, la variación del tanque se **sugiere** (prorrateada por fórmula si comparten tanque) y es **editable**. "
               "El horario de **Acopio final** (cuando debería variar el tanque) se edita acá abajo o en *Etapas & horarios*.")
    df = cat("SELECT * FROM produccion.v_reaccion_terminada ORDER BY cierre_ts DESC NULLS LAST, creado_en DESC")
    if df is None or df.empty:
        st.info("No hay reacciones terminadas todavía (finalizadas o con kilos finales cargados)."); return
    df = df.copy(); df["cierre_ts"] = pd.to_datetime(df["cierre_ts"])
    sug = _terminadas_sugerencias(df, cat)

    def _real_row(r):
        _idb = int(r["id_batch"]); _tk = float(r["tickets_kg"] or 0)
        _as = r["real_asignado_kg"]
        if pd.notna(_as) and float(_as) > 0:
            return float(_as), (r["real_metodo"] or "manual")
        if _tk > 0:
            return _tk, "tickets"
        _sg = sug.get(_idb)
        return (float(_sg), "tanque") if _sg is not None else (None, None)

    rows = []
    for _, r in df.iterrows():
        _real, _met = _real_row(r)
        _obj = float(r["objetivo_kg"]) if pd.notna(r["objetivo_kg"]) else None
        _desv = ((_real - _obj) / _obj * 100.0) if (_real is not None and _obj) else None
        rows.append({
            "N°": r["ident"], "Reacción": r["etiqueta"], "Reactor": r["reactor"], "Producto": r["producto"],
            "Máx reactor (t)": (float(r["max_kg"]) / 1000 if pd.notna(r["max_kg"]) else None),
            "Objetivo (t)": (_obj / 1000 if _obj else None),
            "Fórmula (t)": (float(r["formula_kg"]) / 1000 if pd.notna(r["formula_kg"]) else None),
            "Real tickets (t)": (float(r["tickets_kg"]) / 1000 if float(r["tickets_kg"] or 0) > 0 else None),
            "Real tanque sug (t)": (sug.get(int(r["id_batch"])) / 1000 if sug.get(int(r["id_batch"])) is not None else None),
            "Real (t)": (_real / 1000 if _real is not None else None),
            "Método": _met or "—",
            "Desvío %": (round(_desv, 1) if _desv is not None else None),
        })
    _disp = pd.DataFrame(rows)
    _numcols = ["Máx reactor (t)", "Objetivo (t)", "Fórmula (t)", "Real tickets (t)", "Real tanque sug (t)", "Real (t)"]
    st.dataframe(_disp, hide_index=True, use_container_width=True,
                 column_config={**{c: st.column_config.NumberColumn(format="%.2f") for c in _numcols},
                                "Desvío %": st.column_config.NumberColumn(format="%.1f%%")})

    st.divider()
    st.markdown("##### Editar una reacción terminada")
    _opt = df.apply(lambda r: f"{r['ident']} · {r['etiqueta']}", axis=1).tolist()
    _sel = st.selectbox("Reacción", _opt, key="term_sel")
    r = df.iloc[_opt.index(_sel)]
    idb = int(r["id_batch"])
    _real0, _met0 = _real_row(r)
    cA, cB, cC = st.columns(3)
    cA.metric("Máx reactor (t)", f"{float(r['max_kg'])/1000:.2f}" if pd.notna(r["max_kg"]) else "—")
    cB.metric("Objetivo (t)", f"{float(r['objetivo_kg'])/1000:.2f}" if pd.notna(r["objetivo_kg"]) else "—")
    cC.metric("Real actual (t)", f"{_real0/1000:.2f}" if _real0 is not None else "—", _met0 or None)

    # editar inicio y fin de la reacción
    _il = pd.to_datetime(r["inicio_local"]) if pd.notna(r["inicio_local"]) else None
    _fl = pd.to_datetime(r["fin_local"]) if pd.notna(r["fin_local"]) else None
    st.markdown("**Inicio y fin de la reacción** (editable)")
    i1, i2, i3, i4 = st.columns(4)
    _id2 = i1.date_input("Fecha inicio", value=(_il.date() if _il is not None else None), key=f"term_id_{idb}", format="DD/MM/YYYY")
    _ih2 = i2.time_input("Hora inicio", value=(_il.time() if _il is not None else None), key=f"term_ih_{idb}", step=300)
    _fd2 = i3.date_input("Fecha fin", value=(_fl.date() if _fl is not None else None), key=f"term_fd_{idb}", format="DD/MM/YYYY")
    _fh2 = i4.time_input("Hora fin", value=(_fl.time() if _fl is not None else None), key=f"term_fh_{idb}", step=300)
    if st.button("💾 Guardar inicio/fin", key=f"term_if_{idb}"):
        try:
            _isoi = (f"{_id2.isoformat()} {_ih2.strftime('%H:%M:%S')}" if (_id2 and _ih2) else None)
            _isof = (f"{_fd2.isoformat()} {_fh2.strftime('%H:%M:%S')}" if (_fd2 and _fh2) else None)
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_batch_proceso SET "
                                " inicio_ts = CASE WHEN %s IS NULL THEN inicio_ts ELSE (%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') END, "
                                " fin_ts = CASE WHEN %s IS NULL THEN fin_ts ELSE (%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') END "
                                "WHERE id_batch=%s", (_isoi, _isoi, _isof, _isof, idb))
                    audit.log("U", "fact_batch_proceso", idb, {"inicio": _isoi, "fin": _isof})
            st.success("Inicio/fin actualizados."); cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)

    # editar horario de Acopio final (cierre) -> mueve la ventana de variación de tanque
    _cts = r["cierre_ts"]
    _cts_ts = pd.to_datetime(_cts) if pd.notna(_cts) else None
    st.markdown("**Horario de Acopio final** (cuando debería variar el tanque)")
    e1, e2 = st.columns(2)
    _cd = e1.date_input("Fecha acopio final", value=(_cts_ts.date() if _cts_ts is not None else None), key=f"term_cd_{idb}", format="DD/MM/YYYY")
    _ch = e2.time_input("Hora acopio final", value=(_cts_ts.time() if _cts_ts is not None else None), key=f"term_ch_{idb}", step=300)
    if st.button("💾 Guardar horario de acopio final", key=f"term_cs_{idb}"):
        if _cd is None or _ch is None:
            st.warning("Poné fecha y hora.")
        else:
            try:
                _iso = f"{_cd.isoformat()} {_ch.strftime('%H:%M:%S')}"
                with conectar(int(USR["id_usuario"])) as (conn, audit):
                    with conn.cursor() as cur:
                        _ex = None
                        cur.execute("SELECT id_evento_etapa FROM produccion.fact_etapa_evento "
                                    "WHERE id_batch=%s AND etapa ILIKE %s ORDER BY inicio_ts DESC NULLS LAST LIMIT 1",
                                    (idb, "%acopio%"))
                        _row = cur.fetchone(); _ex = _row[0] if _row else None
                        if _ex:
                            cur.execute("UPDATE produccion.fact_etapa_evento "
                                        "SET inicio_ts=(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') WHERE id_evento_etapa=%s",
                                        (_iso, int(_ex)))
                        else:
                            cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch, etapa, inicio_ts) "
                                        "VALUES (%s,'ACOPIO FINAL',(%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires'))",
                                        (idb, _iso))
                        audit.log("U", "fact_etapa_evento", idb, {"acopio_final": _iso})
                st.success("Horario de acopio final guardado (recalcula la variación sugerida)."); cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)

    # asignar / editar kg real
    st.markdown("**Producción real de la reacción**")
    _sg = sug.get(idb)
    if float(r["tickets_kg"] or 0) > 0:
        st.caption(f"Tiene tickets de pesada: real por tickets = **{float(r['tickets_kg'])/1000:.2f} t** (autoritativo).")
    if _sg is not None:
        st.caption(f"Sugerido por variación de tanque (prorrateado): **{_sg/1000:.2f} t**.")
    _def_real_t = (_real0/1000.0) if _real0 is not None else 0.0
    _real_t = st.number_input("Real (t) — editable", min_value=0.0, value=round(_def_real_t, 2), step=0.1, format="%.2f", key=f"term_real_{idb}")
    _obs = st.text_input("Observaciones del cierre", value="", key=f"term_obs_{idb}")
    if st.button("💾 Guardar producción real", type="primary", key=f"term_save_{idb}", use_container_width=True):
        try:
            _met = "manual"
            if float(r["tickets_kg"] or 0) > 0 and abs(_real_t*1000 - float(r["tickets_kg"])) < 1:
                _met = "tickets"
            elif _sg is not None and abs(_real_t*1000 - _sg) < 1:
                _met = "tanque"
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO produccion.fact_reaccion_cierre (id_batch, real_kg, metodo, obs, id_usuario, actualizado_en) "
                                "VALUES (%s,%s,%s,%s,%s,now()) "
                                "ON CONFLICT (id_batch) DO UPDATE SET real_kg=EXCLUDED.real_kg, metodo=EXCLUDED.metodo, "
                                " obs=EXCLUDED.obs, id_usuario=EXCLUDED.id_usuario, actualizado_en=now()",
                                (idb, float(_real_t*1000), _met, ((_obs or "").strip() or None), int(USR["id_usuario"])))
                    audit.log("U", "fact_reaccion_cierre", idb, {"real_kg": float(_real_t*1000), "metodo": _met})
            st.success(f"Producción real guardada: {_real_t:.2f} t ({_met})."); cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)

    st.divider()
    st.markdown("**🔎 Chequear si fue real — variaciones de tanque parecidas a lo teórico**")
    _teo = float(r["objetivo_kg"]) if pd.notna(r["objetivo_kg"]) else (float(r["formula_kg"]) if pd.notna(r["formula_kg"]) else None)
    _finref = pd.to_datetime(r["fin_local"]) if pd.notna(r["fin_local"]) else (pd.to_datetime(r["cierre_ts"]).tz_localize(None) if pd.notna(r["cierre_ts"]) else None)
    if _finref is None:
        st.caption("Cargá el **fin** (o el acopio final) para poder buscar la variación en tanques.")
    elif not pd.notna(r["id_producto"]):
        st.caption("La reacción no tiene producto asignado para buscar tanques.")
    else:
        _teo_txt = f"{_teo/1000:.2f} t" if _teo else "—"
        st.caption(f"Busca aumentos de **{r['producto']}** en los tanques alrededor del fin "
                   f"({_finref.strftime('%d/%m %H:%M')}), cercanos a lo teórico ({_teo_txt}).")
        _win = st.number_input("Ventana ± horas alrededor del fin", 1, 240, 24, step=1, key=f"term_win_{idb}")
        if st.button("🔎 Buscar variaciones", key=f"term_scan_{idb}"):
            _lo = (_finref - pd.Timedelta(hours=float(_win))).strftime("%Y-%m-%d %H:%M:%S")
            _hi = (_finref + pd.Timedelta(hours=float(_win))).strftime("%Y-%m-%d %H:%M:%S")
            _dens = float(r["densidad"] or 0.91)
            _tks = cat("SELECT DISTINCT t.id_tanque, t.nombre, t.codigo FROM produccion.dim_tanque t "
                       "LEFT JOIN produccion.dim_tanque_producto tp ON tp.id_tanque=t.id_tanque "
                       "WHERE COALESCE(t.activo,true) AND (t.id_producto_principal=%s OR tp.id_producto=%s) "
                       "ORDER BY t.nombre", (int(r["id_producto"]), int(r["id_producto"])))
            _res = []
            if _tks is not None and not _tks.empty:
                for _, _tk in _tks.iterrows():
                    _m = cat("SELECT medido_en, litros::float AS litros FROM produccion.fact_stock_tanque "
                             "WHERE id_tanque=%s AND litros IS NOT NULL "
                             "AND medido_en BETWEEN (%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') "
                             "AND (%s::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires') ORDER BY medido_en",
                             (int(_tk["id_tanque"]), _lo, _hi))
                    if _m is None or len(_m) < 2:
                        continue
                    _m = _m.copy(); _m["medido_en"] = pd.to_datetime(_m["medido_en"])
                    _net_l = float(_m.iloc[-1]["litros"]) - float(_m.iloc[0]["litros"])
                    _best_l = float(_m["litros"].diff().fillna(0).max())
                    _use_l = max(_net_l, _best_l)
                    _dkg = _use_l * _dens
                    if _dkg <= 0:
                        continue
                    _coinc = (max(0.0, (1 - abs(_dkg - _teo) / _teo)) * 100) if _teo else None
                    _res.append({"id_tanque": int(_tk["id_tanque"]), "tanque": f"{_tk['nombre']} · {_tk['codigo']}",
                                 "delta_kg": _dkg, "delta_t": _dkg / 1000.0,
                                 "desde": _m.iloc[0]["medido_en"].strftime("%d/%m %H:%M"),
                                 "hasta": _m.iloc[-1]["medido_en"].strftime("%d/%m %H:%M"),
                                 "coinc": (f"{_coinc:.0f}%" if _coinc is not None else "—"),
                                 "_abs": (abs(_dkg - _teo) if _teo else 0.0)})
                _res = sorted(_res, key=lambda x: x["_abs"])
            st.session_state[f"term_scan_res_{idb}"] = _res
        _res = st.session_state.get(f"term_scan_res_{idb}")
        if _res is not None:
            if not _res:
                st.warning("No encontré variaciones de tanque de este producto en esa ventana. Ampliá las horas, revisá el fin, o cargá el real manual arriba.")
            else:
                st.dataframe(pd.DataFrame([{"Tanque": x["tanque"], "Δ (t)": x["delta_t"], "Desde": x["desde"],
                                           "Hasta": x["hasta"], "Coincide": x["coinc"]} for x in _res]),
                             hide_index=True, use_container_width=True,
                             column_config={"Δ (t)": st.column_config.NumberColumn(format="%.2f")})
                _ropt = [f"{x['tanque']} · Δ {x['delta_t']:.2f} t · {x['desde']}→{x['hasta']} · coincide {x['coinc']}" for x in _res]
                _rsel = st.selectbox("Asociar esta variación", _ropt, key=f"term_scan_sel_{idb}")
                _rx = _res[_ropt.index(_rsel)]
                if st.button("✅ Asociar como producción real", type="primary", key=f"term_assoc_{idb}", use_container_width=True):
                    try:
                        _ob = f"Asociado tanque {_rx['tanque']} ({_rx['desde']}→{_rx['hasta']}, coincide {_rx['coinc']})"
                        with conectar(int(USR["id_usuario"])) as (conn, audit):
                            with conn.cursor() as cur:
                                cur.execute("INSERT INTO produccion.fact_reaccion_cierre (id_batch, real_kg, metodo, obs, id_usuario, actualizado_en) "
                                            "VALUES (%s,%s,'tanque',%s,%s,now()) "
                                            "ON CONFLICT (id_batch) DO UPDATE SET real_kg=EXCLUDED.real_kg, metodo='tanque', "
                                            " obs=EXCLUDED.obs, id_usuario=EXCLUDED.id_usuario, actualizado_en=now()",
                                            (idb, float(_rx["delta_kg"]), _ob, int(USR["id_usuario"])))
                                audit.log("U", "fact_reaccion_cierre", idb, {"real_kg": float(_rx["delta_kg"]), "metodo": "tanque_asociado", "tanque": _rx["tanque"]})
                        st.success(f"Asociado: {_rx['delta_t']:.2f} t desde {_rx['tanque']}."); cat.clear(); st.rerun()
                    except Exception as e:
                        st.exception(e)


def _gestion_reacciones(USR, cat, conectar):
    st.subheader("🛠️ Gestión de reacciones")
    _g0, _g1, _g2, _g3, _g4 = st.tabs(["🎛️ Tablero", "⏯️ Trabajar (arrancar / cargar muestras / decantar)",
                                       "📋 En marcha & nombres", "🕐 Etapas & horarios", "🧫 Evaluaciones internas"])
    with _g0:
        _panel_tablero(USR, cat, conectar)
    with _g1:
        st.caption("Mismo flujo que **Producción en planta**: arrancar la reacción, cargar muestras de evaluación interna y decantar.")
        try:
            import carga_por_id
            carga_por_id.render(USR, cat, conectar)
        except Exception as e:
            st.error("No se pudo cargar el flujo de producción."); st.exception(e)
    with _g2:
        _panel_en_marcha(USR, cat, conectar)
    with _g3:
        _panel_etapas(USR, cat, conectar)
    with _g4:
        _panel_evals(USR, cat, conectar)


def _avanzar_fase(USR, cat, conectar):
    st.subheader("⏭️ Avanzar de fase (manual · dirección)")
    st.caption("Forzá el pase de una reacción a la **siguiente fase**, más allá del tiempo/umbral que debería tardar "
               "(ej.: acortar reposo, cortar reacción antes). Queda registrado quién y por qué.")
    df = cat("SELECT b.id_batch, b.identificador_unidad AS ident, b.tipo_proceso, b.estado, "
             "       b.etapa_actual, b.id_producto_buscado, b.ticket_producto_final, bu.nombre_ui AS reactor, "
             "       COALESCE(mp.mp,'—') AS mp, COALESCE(mp.mp_tn,0) AS mp_tn "
             "FROM produccion.fact_batch_proceso b "
             "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
             "LEFT JOIN produccion.v_reaccion_mp mp ON mp.id_batch=b.id_batch "
             "WHERE b.sector='REACTORES' AND COALESCE(b.anulado,false)=false "
             "  AND b.estado IN ('REACCION','REPOSO') ORDER BY b.creado_en DESC")
    if df is None or df.empty:
        st.info("No hay reacciones en REACCIÓN o REPOSO para avanzar.")
        return
    _opt = df.apply(lambda r: f"#{r['id_batch']} · {r['ident'] or '—'} · {r['tipo_proceso']} · "
                              f"{r['reactor'] or '—'} · MP: {r.get('mp','—')} ({float(r.get('mp_tn',0) or 0):.1f} t) · {r['estado']}", axis=1).tolist()
    sel = st.selectbox("Reacción", _opt, key="avf_sel")
    r = df.iloc[_opt.index(sel)]
    _tipo_badge(r["tipo_proceso"])
    _next = {"REACCION": "REPOSO", "REPOSO": "DECANTACION"}.get(r["estado"])
    _etapa = {"REPOSO": "REPOSANDO", "DECANTACION": "DECANTACION"}.get(_next)
    _es_are = str(r["tipo_proceso"]) == "PRODUCCION_ARE"
    _es_desg = str(r["tipo_proceso"]) == "DESGOMADO_ACUOSO"
    st.info(f"Estado actual: **{r['estado']}** → siguiente: **{_next}**.")
    if r["estado"] == "REACCION" and _es_are and not r["ticket_producto_final"]:
        st.caption("Al pasar a reposo se generará el **ticket de producto final** (para que laboratorio evalúe), igual que el pase automático.")
    motivo = st.text_input("Motivo (obligatorio)", key="avf_mot",
                           placeholder="Ej.: la reacción ya está lista antes de tiempo / acortar reposo")
    if st.button(f"⏭️ Forzar pase a {_next}", type="primary", use_container_width=True, key="avf_go", disabled=(_next is None)):
        if not (motivo or "").strip():
            st.error("Poné el motivo del pase manual.")
            return
        try:
            uid = int(USR["id_usuario"])
            _mot = "Forzado por planificación: " + motivo.strip()
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_etapa_evento SET fin_ts=now() "
                                "WHERE id_batch=%s AND fin_ts IS NULL", (int(r["id_batch"]),))
                    cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch,etapa,inicio_ts,id_usuario) "
                                "VALUES (%s,%s,now(),%s)", (int(r["id_batch"]), _etapa, uid))
                    # ARE que pasa a REPOSO: crear ticket producto final + validación (como la regla automática)
                    if r["estado"] == "REACCION" and _es_are and not r["ticket_producto_final"]:
                        cur.execute("SELECT ticket_lab FROM produccion.fact_ticket_lab "
                                    "WHERE id_batch=%s AND rol='MP' ORDER BY id_ticket LIMIT 1", (int(r["id_batch"]),))
                        _mp = cur.fetchone(); _mp = _mp[0] if _mp else None
                        cur.execute("SELECT produccion.fn_ticket_lab('FINAL')")
                        _tf = cur.fetchone()[0]
                        cur.execute("INSERT INTO produccion.fact_ticket_lab (ticket_lab,id_batch,rol,id_producto,fuente,estado) "
                                    "VALUES (%s,%s,'FINAL',%s,'PROCESO','PENDIENTE')",
                                    (_tf, int(r["id_batch"]), (int(r["id_producto_buscado"]) if pd.notna(r["id_producto_buscado"]) else None)))
                        cur.execute("UPDATE produccion.fact_batch_proceso SET estado='REPOSO', etapa_actual='REPOSANDO', "
                                    "esperando_validacion_lab=true, ticket_validacion_lab=%s, ticket_producto_final=%s, "
                                    "id_usuario_estado=%s, motivo_estado=%s WHERE id_batch=%s",
                                    (_mp, _tf, uid, _mot, int(r["id_batch"])))
                    elif r["estado"] == "REACCION" and _es_desg:
                        cur.execute("UPDATE produccion.fact_batch_proceso SET estado='REPOSO', etapa_actual='REPOSANDO', "
                                    "desg_reposo_ini_ts=COALESCE(desg_reposo_ini_ts,now()), "
                                    "id_usuario_estado=%s, motivo_estado=%s WHERE id_batch=%s",
                                    (uid, _mot, int(r["id_batch"])))
                    else:
                        cur.execute("UPDATE produccion.fact_batch_proceso SET estado=%s, etapa_actual=%s, "
                                    "id_usuario_estado=%s, motivo_estado=%s WHERE id_batch=%s",
                                    (_next, _etapa, uid, _mot, int(r["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(r["id_batch"]),
                          {"forzar_fase": _next, "motivo": motivo})
            st.success(f"Reacción #{int(r['id_batch'])} pasada a **{_next}** (manual).")
            st.balloons(); cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def _render_cronogramas(USR, cat, conectar):
    st.subheader("⚙️ Editar cronogramas de etapas (por proceso y por reactor)")
    st.caption("Cambiá el **nombre** de cada etapa y su **duración** (horas y minutos). "
               "Esto define los horarios calculados del cronograma de producción. "
               "El **código** de la etapa no se toca (lo usa el sistema); el nombre es global por etapa.")
    _procs = cat("SELECT DISTINCT proceso_key FROM produccion.dic_proceso_etapa ORDER BY proceso_key")
    if _procs is None or _procs.empty:
        st.info("No hay cronogramas cargados.")
        return
    _pk = st.selectbox("Proceso", _procs["proceso_key"].tolist(),
                       format_func=lambda p: str(p).replace("_", " ").title(), key="cr_proc")
    _REACTOR_PROCS = {"PRODUCCION_ARE", "DESGOMADO_ACUOSO"}
    _id_bu = None
    _scope = "BASE"
    if _pk in _REACTOR_PROCS:
        _rx = cat("SELECT id_bien_uso, nombre_ui FROM produccion.dim_bien_uso WHERE tipo='REACTOR' ORDER BY codigo")
        _ropts = ["Base (todos los reactores)"] + (_rx["nombre_ui"].tolist() if (_rx is not None and not _rx.empty) else [])
        _rsel = st.radio("Aplicar a", _ropts, horizontal=True, key=f"cr_scope_{_pk}")
        if _rsel != "Base (todos los reactores)" and _rx is not None and not _rx.empty:
            _id_bu = int(_rx[_rx["nombre_ui"] == _rsel].iloc[0]["id_bien_uso"])
            _scope = "REACTOR"
            st.caption(f"Editás el cronograma **solo de {_rsel}**. Si este reactor no tiene uno propio, se usa el Base.")
    if _scope == "REACTOR":
        _et = cat("SELECT r.orden, r.etapa, COALESCE(e.descripcion, r.etapa) AS nombre, COALESCE(r.duracion_target_min,0) AS dur "
                  "FROM produccion.dic_proceso_etapa_reactor r LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=r.etapa "
                  "WHERE r.proceso_key=%s AND r.id_bien_uso=%s ORDER BY r.orden", (_pk, _id_bu))
        if _et is None or _et.empty:
            st.info("Este reactor todavía no tiene cronograma propio: te cargo el **Base** para que lo edites y lo guardes para este reactor.")
            _et = cat("SELECT pe.orden, pe.etapa, COALESCE(e.descripcion, pe.etapa) AS nombre, COALESCE(pe.duracion_target_min,0) AS dur "
                      "FROM produccion.dic_proceso_etapa pe LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=pe.etapa "
                      "WHERE pe.proceso_key=%s ORDER BY pe.orden", (_pk,))
    else:
        _et = cat("SELECT pe.orden, pe.etapa, COALESCE(e.descripcion, pe.etapa) AS nombre, COALESCE(pe.duracion_target_min,0) AS dur "
                  "FROM produccion.dic_proceso_etapa pe LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=pe.etapa "
                  "WHERE pe.proceso_key=%s ORDER BY pe.orden", (_pk,))
    if _et is None or _et.empty:
        st.info("Este proceso no tiene etapas.")
        return
    _df = pd.DataFrame({
        "Orden": _et["orden"].astype(int),
        "Etapa (código)": _et["etapa"].astype(str),
        "Nombre": _et["nombre"].astype(str),
        "Horas": (_et["dur"].astype(float) // 60).astype(int),
        "Minutos": (_et["dur"].astype(float) % 60).astype(int),
    })
    st.caption("Podés **agregar** etapas (➕ abajo) y **borrar** (seleccioná la fila y 🗑). "
               "Código en MAYÚSCULAS sin espacios; si lo dejás vacío, se genera del nombre.")
    _ed = st.data_editor(
        _df, hide_index=True, use_container_width=True, key=f"cr_ed_{_pk}_{_id_bu or 0}", num_rows="dynamic",
        column_config={
            "Orden": st.column_config.NumberColumn("Orden", min_value=1, step=1),
            "Etapa (código)": st.column_config.TextColumn("Código", help="Identificador interno (sin espacios)."),
            "Nombre": st.column_config.TextColumn("Nombre de la etapa"),
            "Horas": st.column_config.NumberColumn("Horas", min_value=0, max_value=336, step=1),
            "Minutos": st.column_config.NumberColumn("Minutos", min_value=0, max_value=59, step=5),
        })
    if st.button("💾 Guardar cronograma", type="primary", use_container_width=True, key=f"cr_save_{_pk}_{_id_bu or 0}"):
        try:
            import re as _re
            uid = int(USR["id_usuario"])
            _rows = []
            for _, r in _ed.iterrows():
                _nom = (str(r.get("Nombre") or "")).strip()
                _cod = (str(r.get("Etapa (código)") or "")).strip().upper()
                if not _cod:
                    _cod = _re.sub(r"[^A-Z0-9]+", "_", (_nom or "ETAPA").upper()).strip("_") or "ETAPA"
                if not _nom and not _cod:
                    continue
                _h = int(r.get("Horas") or 0); _m = int(r.get("Minutos") or 0)
                _ord = int(r.get("Orden") or (len(_rows) + 1))
                _rows.append((_ord, _cod, (_nom or _cod), _h * 60 + _m))
            if not _rows:
                st.error("Tiene que quedar al menos una etapa.")
            else:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur:
                        if _scope == "REACTOR":
                            cur.execute("DELETE FROM produccion.dic_proceso_etapa_reactor WHERE proceso_key=%s AND id_bien_uso=%s", (_pk, _id_bu))
                            for _ord, _cod, _nom, _dur in _rows:
                                cur.execute("INSERT INTO produccion.dic_proceso_etapa_reactor (proceso_key, id_bien_uso, etapa, orden, duracion_target_min) "
                                            "VALUES (%s,%s,%s,%s,%s)", (_pk, _id_bu, _cod, _ord, _dur))
                                cur.execute("INSERT INTO produccion.dic_etapa_proceso (codigo, descripcion, orden, activo) "
                                            "VALUES (%s,%s,%s,true) ON CONFLICT (codigo) DO UPDATE SET descripcion=EXCLUDED.descripcion", (_cod, _nom, _ord))
                        else:
                            cur.execute("DELETE FROM produccion.dic_proceso_etapa WHERE proceso_key=%s", (_pk,))
                            for _ord, _cod, _nom, _dur in _rows:
                                cur.execute("INSERT INTO produccion.dic_proceso_etapa (proceso_key, etapa, orden, duracion_target_min) "
                                            "VALUES (%s,%s,%s,%s)", (_pk, _cod, _ord, _dur))
                                cur.execute("INSERT INTO produccion.dic_etapa_proceso (codigo, descripcion, orden, activo) "
                                            "VALUES (%s,%s,%s,true) ON CONFLICT (codigo) DO UPDATE SET descripcion=EXCLUDED.descripcion", (_cod, _nom, _ord))
                    audit.log("U", "dic_proceso_etapa", 0, {"proceso": _pk, "scope": _scope, "etapas": len(_rows)})
                st.success(f"Cronograma actualizado ({'Base' if _scope=='BASE' else _rsel}).")
                cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


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
    _borrador_restaurar(cat, USR)
    with st.expander("📋 Ver planificadas y sus movimientos (todo lo cargado)", expanded=False):
        _render_planificadas(cat)
    _render_aprobaciones(USR, cat, conectar)

    _grupo = st.radio("¿Qué querés hacer?",
                      ["➕ Cargar nueva reacción", "⚙️ Administrar en curso", "📅 Cronogramas"],
                      horizontal=True, key="pl_grupo")

    # ----- Administrar procesos en curso (no es carga: se decide sobre reacciones ya arrancadas) -----
    if _grupo.startswith("⚙️"):
        st.caption("Reacciones ya en marcha que esperan una decisión de dirección (reposo, destino, etc.).")
        _admin = st.radio("Proceso a administrar",
                          ["🛠️ Gestión de reacciones", "🏁 Terminadas (objetivo vs real)", "🧴 Decantación ARE", "🫧 Desgomado acuoso", "⏭️ Avanzar fase (manual)"],
                          horizontal=True, key="pl_admin")
        if _admin.startswith("🛠️"):
            _gestion_reacciones(USR, cat, conectar)
        elif _admin.startswith("🏁"):
            _reacciones_terminadas(USR, cat, conectar)
        elif _admin.startswith("🧴"):
            import decantacion
            decantacion.destinos(USR, cat, conectar)
        elif _admin.startswith("⏭️"):
            _avanzar_fase(USR, cat, conectar)
        else:
            import desgomado
            desgomado.planificacion(USR, cat, conectar)
        return

    if _grupo.startswith("📅"):
        _render_cronogramas(USR, cat, conectar)
        return

    # ----- Cargar nueva reacción: reactores o bachas -----
    modo = st.radio("Tipo de carga", ["🏭 Reactores", "🛁 Bachas"], horizontal=True, key="pl_modo")
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

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Proceso", proc or "—")
    b2.metric("Corriente", corr or "—")
    b3.metric("Capacidad", f"{cap:,.0f} L")
    b4.metric("Q MP objetivo", f"{q_ag:,.0f} kg")
    st.caption("Q = capacidad × densidad de la MP (se recalcula).")

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
        _keys = list(fin_opts.keys())
        # PRODUCCION_ARE: ARE-B (id 41) es el predefinido
        _def_i = next((i for i, k in enumerate(_keys) if fin_opts[k] == 41), 0) if proc == "PRODUCCION_ARE" else 0
        pf_lbl = st.selectbox("Producto final / calidad", _keys, index=_def_i, key="pl_pf")
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

    # ---------- PRODUCCION_ARE: glicerina a cargar (fresca + recuperada) ----------
    glicerol_v = None              # % glicerol de referencia (fresca) — compatibilidad
    gli_ticket = None
    catal = "POTASIO"              # ARE: catalizador hidróxido de potasio (KOH), cantidad fija por reactor
    gli_idt = None
    gli_tkp = None
    gli_fresca = {"idt": None, "l": 0.0, "glicerol_kg": 0.0, "kg": 0.0, "dens": None}
    gli_recup = {"idt": None, "l": 0.0, "glicerol_kg": 0.0, "kg": 0.0, "dens": None}
    are_formula_id = None
    are_formula_nombre = None
    _aporte = 10.0
    if proc == "PRODUCCION_ARE":
        PMa = float(K("PMa", 282)); PMg = float(K("PMg", 92)); FE = float(K("factor_exceso_gli", 1.1))
        st.markdown("#### 2 · Fórmula y glicerina a cargar (fresca + recuperada)")
        _Fare = _formulas_sector(cat, "REACTORES")
        _Fare = _Fare[_Fare["tipo_proceso"] == "PRODUCCION_ARE"] if (_Fare is not None and not _Fare.empty) else _Fare
        _are_fx = _selector_formula(_Fare, key="pl_fx_are")
        _are_fi = _ins_de(_are_fx) if _are_fx is not None else {}
        _fresca_def = float((_are_fi.get("GLICERINA_FRESCA") or {}).get("cant") or 0)
        _recup_def = float((_are_fi.get("GLICERINA_RECUP") or {}).get("cant") or 0)
        _are_fp = _params_de(_are_fx) if _are_fx is not None else {}
        _aporte = float(_are_fp.get("aporte_glicerina_pct") or _cond_val(cat, "ARE_APORTE_GLICERINA_PCT", 10.0))
        if _are_fx is not None:
            are_formula_id = int(_are_fx["id_formula"])
            are_formula_nombre = str(_are_fx["nombre"])
        st.caption(f"Fórmula **{are_formula_nombre or '—'}** → carga fresca **{_fresca_def:,.0f} L** + recuperada "
                   f"**{_recup_def:,.0f} L** (editá litros y tanque abajo). Fresca ~100% glicerina (≈80% glicerol); "
                   "recuperada ~20% glicerina (≈60% glicerol). El glicerol de **ambas suma** al objetivo. "
                   "Administrá nombres/valores en la sección 🧪 Fórmulas.")
        _gcf, _gcr = st.columns(2)
        with _gcf:
            st.markdown("**🟢 Glicerina fresca**")
            gli_fresca = _pick_gli(cat, "GLICERINA-PURA", "pl_fresca", densidad_de, default_l=_fresca_def)
        with _gcr:
            st.markdown("**🟡 Glicerina recuperada**")
            gli_recup = _pick_gli(cat, "GLICERINA-RECUP", "pl_recup", densidad_de, default_l=_recup_def)
        glicerol_v = gli_fresca.get("glicerol_pct")
        gli_idt = gli_fresca.get("idt")

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
    _rawac = lab_avg.get("prc_acidez")
    acidez = ((float(_rawac) * 100 if float(_rawac) <= 1 else float(_rawac))
              if _rawac is not None else (acidez_obj or 0.0))  # datos mezclados frac/%: <=1 es fraccion

    # ---------- Llenado del reactor (en LITROS) — incluye MP + glicerina ----------
    litros_mp = (kg_used / dens) if dens else 0.0
    litros_gli = (float(gli_fresca.get("l") or 0) + float(gli_recup.get("l") or 0)) if proc == "PRODUCCION_ARE" else 0.0
    litros_carga = litros_mp + litros_gli
    _pct_llen = (litros_carga / cap * 100.0) if cap else 0.0
    if proc == "PRODUCCION_ARE":
        lc1, lc2, lc3, lc4 = st.columns(4)
        lc1.metric("MP cargada", f"{litros_mp:,.0f} L", f"{kg_used:,.0f} kg · {kg_used/1000:,.1f} TN")
        lc2.metric("Glicerina (fresca+recup.)", f"{litros_gli:,.0f} L")
        lc3.metric("Capacidad reactor", f"{cap:,.0f} L")
        lc4.metric("Llenado del reactor", f"{_pct_llen:.0f}%", help="Incluye MP + glicerina fresca + recuperada")
    else:
        lc1, lc2, lc3 = st.columns(3)
        lc1.metric("MP cargada", f"{litros_mp:,.0f} L", f"{kg_used:,.0f} kg · {kg_used/1000:,.1f} TN")
        lc2.metric("Capacidad reactor", f"{cap:,.0f} L")
        lc3.metric("Llenado del reactor", f"{_pct_llen:.0f}%")
    st.progress(min(1.0, max(0.0, _pct_llen / 100.0)))
    just_carga = ""
    _carga_baja = bool(cap and kg_used > 0 and _pct_llen < 80.0)
    if _carga_baja:
        st.error(f"🚨 **Carga al {_pct_llen:.0f}%** de la capacidad del reactor (mínimo: 80%). "
                 "Cargar de menos es una falta grave (induce pérdidas económicas). "
                 "Abajo, junto al botón Generar, tenés que **justificar el motivo**: "
                 "se genera un ticket que el director debe aprobar antes de poder iniciar.")

    # ---------- Insumos y objetivo ----------
    st.markdown("#### 4 · Insumos y objetivo")
    insumos_calc = []  # (codigo_insumo, rol, kg)
    insumo_tanque = {}  # codigo_insumo -> id_tanque (KOH/fuel salen de tanque, para descontar stock)
    ajustes = {}       # ajustes manuales vs default -> exigen motivo
    gli_mov = None
    gli_recup_kg = None
    dens_gli = float(K("densidad_glicerina", 1.25) or 1.25)
    glol_cargado = glol_req = are_kg = agua_kg = 0.0
    agua_frac = 0.0
    est_pot = 0.0
    _fuel_l = 0.0
    if proc == "PRODUCCION_ARE":
        # Glicerol cargado = fresca + recuperada (ambas SUMAN para el objetivo)
        glol_fresca = float(gli_fresca.get("glicerol_kg") or 0.0)
        glol_recup = float(gli_recup.get("glicerol_kg") or 0.0)
        glol_cargado = glol_fresca + glol_recup
        gli_recup_kg = float(gli_recup.get("kg") or 0.0)
        # Glicerol requerido por la acidez de la MP (referencia estequiométrica)
        if kg_used > 0 and acidez > 0:
            glol_req = kg_used * (acidez / 100.0) * (PMg / (PMa * 2.0)) * FE
        # KOH y fuel: FIJOS por reactor (editables a mano)
        koh_def = float(fila["koh_kg_fijo"]) if ("koh_kg_fijo" in fila.index and pd.notna(fila["koh_kg_fijo"])) else 0.0
        fuel_def = float(fila["fuel_oil_l_fijo"]) if ("fuel_oil_l_fijo" in fila.index and pd.notna(fila["fuel_oil_l_fijo"])) else 0.0
        st.markdown("##### ✏️ Formulación de iniciación (editable)")
        fz1, fz2, fz3, fz4 = st.columns(4)
        fz1.metric("Glicerina fresca", f"{float(gli_fresca.get('l') or 0):,.0f} L")
        fz2.metric("Glicerina recuperada", f"{float(gli_recup.get('l') or 0):,.0f} L")
        _koh = fz3.number_input("KOH (kg)", 0.0, 100_000.0, value=float(round(koh_def, 1)), step=1.0, key="pl_koh")
        _fuel_l = fz4.number_input("Fuel oil (L)", 0.0, 1_000_000.0, value=float(round(fuel_def, 0)), step=25.0, key="pl_fuel")
        st.caption(f"KOH y fuel son **fijos por reactor** ({fila['nombre_ui']}: KOH {koh_def:g} kg · fuel {fuel_def:g} L). "
                   "Los podés ajustar a mano; el cambio queda registrado. La glicerina se define arriba (sección 2).")
        st.markdown("**🛢️ Tanques de origen de KOH y fuel** (obligatorio — para descontar stock)")
        _kt = cat("SELECT id_tanque, nombre, codigo FROM produccion.dim_tanque t "
                  "JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
                  "WHERE p.codigo_producto='POTASA-CAUSTICA' AND COALESCE(t.activo,true) ORDER BY nombre")
        _ftk = cat("SELECT id_tanque, nombre, codigo FROM produccion.dim_tanque t "
                   "JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
                   "WHERE p.codigo_producto='FUEL' AND COALESCE(t.activo,true) ORDER BY nombre")
        _tkc1, _tkc2 = st.columns(2)
        if _kt is not None and not _kt.empty:
            _ko = _kt.apply(lambda r: f"{r['nombre']} · {r['codigo']}", axis=1).tolist()
            _ks = _tkc1.selectbox("Tanque de KOH (potasio)", _ko, key="pl_koh_tk")
            insumo_tanque["POTASIO"] = int(_kt.iloc[_ko.index(_ks)]["id_tanque"])
        else:
            _tkc1.warning("No hay tanque de potasio (POTASA-CAUSTICA) cargado.")
        if _ftk is not None and not _ftk.empty:
            _fo = _ftk.apply(lambda r: f"{r['nombre']} · {r['codigo']}", axis=1).tolist()
            _fs = _tkc2.selectbox("Tanque de fuel oil", _fo, key="pl_fuel_tk")
            insumo_tanque["FUEL_OIL"] = int(_ftk.iloc[_fo.index(_fs)]["id_tanque"])
        else:
            _tkc2.warning("No hay tanque de fuel cargado.")
        if abs(_koh - koh_def) > 0.01:
            ajustes["KOH (kg)"] = {"formula": round(koh_def, 1), "ajustado": round(_koh, 1)}
        if abs(_fuel_l - fuel_def) > 0.5:
            ajustes["fuel (L)"] = {"formula": round(fuel_def), "ajustado": round(_fuel_l)}
        est_pot = _koh
        est_fuel = _fuel_l * DENS_INSUMO["FUEL_OIL"]
        # Objetivo ARE-B = AG-C (kg) − agua del AG-C (lab) + 10% de litros de glicerina (fresca+recup)
        agua_frac = float(lab_avg.get("prc_agua")) if lab_avg.get("prc_agua") is not None else 0.0
        agua_kg = kg_used * agua_frac
        litros_gli_tot = float(gli_fresca.get("l") or 0) + float(gli_recup.get("l") or 0)
        are_kg = max(0.0, kg_used - agua_kg + (_aporte / 100.0) * litros_gli_tot)
        dens_are = 0.88
        g1, g2, g3 = st.columns(3)
        g1.metric("Glicerol cargado", f"{glol_cargado:,.0f} kg",
                  f"fresca {glol_fresca:,.0f} + recup {glol_recup:,.0f}")
        if glol_req > 0:
            _cob = (glol_cargado / glol_req * 100.0)
            g2.metric("Glicerol requerido", f"{glol_req:,.0f} kg", f"cobertura {_cob:.0f}%")
        else:
            g2.metric("Glicerol requerido", "—", "falta acidez de la MP")
        g3.metric("KOH · Fuel", f"{_koh:,.0f} kg · {_fuel_l:,.0f} L")
        st.metric("🎯 ARE-B objetivo", f"{are_kg/dens_are:,.0f} L", f"{are_kg:,.0f} kg")
        st.caption(f"Objetivo ARE-B (fórmula) = AG-C ({kg_used:,.0f} kg) − agua AG-C ({agua_kg:,.0f} kg · {agua_frac*100:.1f}%) "
                   f"+ {_aporte:.0f}% de litros de glicerina ({litros_gli_tot:,.0f} L → +{(_aporte/100.0)*litros_gli_tot:,.0f}). "
                   f"En decantación, la glicerina recuperada = {100-_aporte:.0f}% de los litros cargados (se contrarresta con el aporte).")
        if glol_req > 0 and glol_cargado < glol_req * 0.999:
            st.warning(f"⚠️ Glicerol cargado ({glol_cargado:,.0f} kg) < requerido ({glol_req:,.0f} kg). "
                       "Agregá litros de glicerina fresca o recuperada en la sección 2.")
        insumos_calc.append(("POTASIO", "CATALIZADOR", round(est_pot, 2)))
        insumos_calc.append(("FUEL_OIL", "INSUMO", round(est_fuel, 0)))
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
                _fv = float(v)
                cols[i].metric(lbl, f"{(_fv*100 if _fv <= 1 else _fv):.2f}")
            else:
                cols[i].metric(lbl, f"{float(v):.2f}")

    # ---------- Parámetros de laboratorio POR TANQUE (MP e insumos elegidos) ----------
    _lab_tids = [int(p["id_tanque"]) for p in (ports or [])
                 if p.get("fuente") == "TANQUE" and p.get("id_tanque")]
    if proc == "PRODUCCION_ARE":
        for _s in (gli_fresca, gli_recup):
            _picks = _s.get("tanques") or ([{"idt": _s.get("idt")}] if _s.get("idt") else [])
            for _p in _picks:
                if _p.get("idt"):
                    _lab_tids.append(int(_p["idt"]))
    if _lab_tids:
        try:
            _pl = cat(
                "SELECT t.nombre AS \"Tanque\", p.codigo_producto AS \"Producto\", "
                "       f.acidez_pct AS \"Acidez %%\", f.agua_pct AS \"Agua %%\", f.sedimentos_pct AS \"Sedim. %%\", "
                "       f.densidad_g_ml AS \"Densidad\", "
                "       COALESCE(f.glicerina_pct, (f.parametros_extra->>'glicerina_pct')::numeric) AS \"Glicerina %%\", "
                "       (f.parametros_extra->>'glicerol_pct')::numeric AS \"Glicerol %%\" "
                "FROM produccion.fact_param_tanque f "
                "JOIN produccion.dim_tanque t ON t.id_tanque=f.id_tanque "
                "JOIN produccion.dim_producto p ON p.id_producto=f.id_producto "
                "WHERE f.id_tanque = ANY(%s) AND f.id_producto = t.id_producto_principal "
                "ORDER BY t.nombre", (_lab_tids,))
        except Exception:
            _pl = None
        if _pl is not None and not _pl.empty:
            st.markdown("#### 📋 Parámetros de laboratorio por tanque (MP + insumos)")
            st.dataframe(_pl, use_container_width=True, hide_index=True)
            st.caption("Cada tanque trae sus parámetros medidos en laboratorio (o sembrados dentro de los promedios por producto).")

    # ---------- Cronograma de producción (inicio + horarios calculados por etapa) ----------
    import datetime as _dtm
    st.markdown("#### 🗓️ Cronograma de producción")
    _cc1, _cc2 = st.columns(2)
    _ini_f = _cc1.date_input("Fecha de inicio", key="pl_crono_f")
    _ini_h = _cc2.time_input("Hora de inicio", value=_dtm.time(8, 0), step=1800, key="pl_crono_h")
    _inicio = _dtm.datetime.combine(_ini_f, _ini_h)
    _id_bu_cr = int(fila["id_bien_uso"]) if ("id_bien_uso" in fila.index and pd.notna(fila["id_bien_uso"])) else None
    _et = cat("SELECT r.etapa, COALESCE(e.descripcion, r.etapa) AS nombre, r.duracion_target_min "
              "FROM produccion.dic_proceso_etapa_reactor r "
              "LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=r.etapa "
              "WHERE r.proceso_key=%s AND r.id_bien_uso=%s ORDER BY r.orden", (proc, _id_bu_cr)) if _id_bu_cr else None
    if _et is None or _et.empty:
        _et = cat("SELECT pe.etapa, COALESCE(e.descripcion, pe.etapa) AS nombre, pe.duracion_target_min "
                  "FROM produccion.dic_proceso_etapa pe "
                  "LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=pe.etapa "
                  "WHERE pe.proceso_key=%s ORDER BY pe.orden", (proc,))
    _repo_h = float(fila["reposo_horas"]) if ("reposo_horas" in fila.index and pd.notna(fila["reposo_horas"])) else None
    _crono_rows = []
    _cur = _inicio
    if _et is not None and not _et.empty:
        for _, _e in _et.iterrows():
            _dur = float(_e["duracion_target_min"] or 0)
            if str(_e["etapa"]) == "REPOSANDO" and _repo_h:
                _dur = _repo_h * 60.0
            _fin = _cur + _dtm.timedelta(minutes=_dur)
            _crono_rows.append({"Etapa": _e["nombre"], "Inicio": _cur.strftime("%d/%m %H:%M"),
                                "Fin": _fin.strftime("%d/%m %H:%M"), "Duración (h)": round(_dur / 60.0, 1)})
            _cur = _fin
        st.dataframe(pd.DataFrame(_crono_rows), use_container_width=True, hide_index=True)
        st.caption(f"Inicio **{_inicio.strftime('%d/%m %H:%M')}** → fin estimado **{_cur.strftime('%d/%m %H:%M')}** "
                   f"(reposo del reactor: {(_repo_h or 0):g} h). Las etapas se calculan desde el inicio.")
    _inicio_iso = _inicio.isoformat()

    # ---------- Destino del producto (ARE): se decide desde el inicio ----------
    dest_are_final = None
    dest_gli_recup = None
    if proc == "PRODUCCION_ARE":
        st.markdown("#### 🎯 Destino del producto (acopio final)")
        st.caption("Definí desde ahora a qué tanque va el **ARE final** y la **glicerina recuperada**. "
                   "Queda computado; después, en Decantación, se puede cambiar.")
        _ftq = cat("SELECT t.id_tanque, t.nombre, t.sector, COALESCE(s.litros_actual,0) lt, COALESCE(t.capacidad_litros,0) cap "
                   "FROM produccion.dim_tanque t JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
                   "LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
                   "WHERE COALESCE(t.activo,true) AND (p.codigo_producto='ARE-B' OR t.sector ILIKE 'Exporta%%') "
                   "ORDER BY (t.sector ILIKE 'Exporta%%') DESC, t.nombre")
        _gtq = cat("SELECT t.id_tanque, t.nombre, COALESCE(s.litros_actual,0) lt, COALESCE(t.capacidad_litros,0) cap "
                   "FROM produccion.dim_tanque t LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
                   "WHERE t.id_tanque IN (88,87,81) ORDER BY t.nombre")
        _dc1, _dc2 = st.columns(2)
        with _dc1:
            if _ftq is not None and not _ftq.empty:
                _fop = _ftq.apply(lambda r: f"{r['nombre']} · {r['sector']} · {float(r['lt']):,.0f}/{float(r['cap']):,.0f} L", axis=1).tolist()
                _fs = st.selectbox("Tanque destino ARE final", _fop, key="pl_dest_final")
                dest_are_final = int(_ftq.iloc[_fop.index(_fs)]["id_tanque"])
            else:
                st.warning("No hay tanques destino para ARE-B.")
        with _dc2:
            if _gtq is not None and not _gtq.empty:
                _gop = _gtq.apply(lambda r: f"{r['nombre']} · {float(r['lt']):,.0f}/{float(r['cap']):,.0f} L", axis=1).tolist()
                _gs = st.selectbox("Tanque destino glicerina recuperada", _gop, key="pl_dest_recup")
                dest_gli_recup = int(_gtq.iloc[_gop.index(_gs)]["id_tanque"])
            else:
                st.warning("No hay tanques de glicerina recuperada.")

    motivo_ajuste = ""
    if ajustes:
        st.warning("✏️ Cambiaste a mano: **" + ", ".join(ajustes.keys()) +
                   "** (vs. fórmula). Indicá el motivo — es obligatorio y queda registrado.")
        motivo_ajuste = st.text_input("Motivo del ajuste *", key="pl_aj_motivo", max_chars=200,
                                      placeholder="ej. la MP venía con más agua de lo normal")
    if _carga_baja:
        st.error(f"🚨 Carga al {_pct_llen:.0f}% del reactor (<80%): justificá el motivo — va al ticket de aprobación del director.")
        just_carga = st.text_input("Justificación de carga baja (<80%) *", key="pl_just_carga", max_chars=250,
                                   placeholder="ej. no hay más MP disponible de esta calidad")
    obs = st.text_input("Observaciones", key="pl_obs", placeholder="opcional")
    _nombre_manual = st.text_input("Nombre / N° de la reacción (opcional)", key="pl_nombre_manual",
                                   placeholder="dejalo vacío para que salga automático (ej. RX-2026-0027)")
    _borrador_guardar(conectar, USR)

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
        if proc == "PRODUCCION_ARE" and (insumo_tanque.get("POTASIO") is None or insumo_tanque.get("FUEL_OIL") is None):
            st.error("Elegí el **tanque de KOH** y el **tanque de fuel oil** (sección 4) para descontar stock.")
            return
        mp_id = int(mp_df[mp_df["codigo_producto"] == mp].iloc[0]["id_producto"])
        _nm = (_nombre_manual or "").strip()
        if _nm:
            _dup = cat("SELECT 1 FROM produccion.fact_batch_proceso "
                       "WHERE identificador_unidad=%s AND COALESCE(anulado,false)=false LIMIT 1", (_nm,))
            if _dup is not None and not _dup.empty:
                st.error(f"Ya existe una reacción con el nombre **{_nm}**. Elegí otro o dejalo vacío para que salga automático.")
                return
        ident = _nm if _nm else siguiente_identificador("REACTORES")
        params = {
            "kg_objetivo": round(q_ag, 0), "temp_inicial_c": temp, "tiempo_horas": horas,
            "acidez_pct": round(acidez, 3), "glicerol_pct": glicerol_v, "catalizador": catal,
            "glicerina_kg": gli_mov, "glicerina_recup_kg": gli_recup_kg, "pct_goma": pct_goma,
            "insumos_estimados": {c: k for c, _, k in insumos_calc},
            "glicerina_fresca_l": round(float(gli_fresca.get("l") or 0), 1) if proc == "PRODUCCION_ARE" else None,
            "glicerina_recup_l": round(float(gli_recup.get("l") or 0), 1) if proc == "PRODUCCION_ARE" else None,
            "glicerol_cargado_kg": round(glol_cargado, 1) if proc == "PRODUCCION_ARE" else None,
            "glicerol_requerido_kg": round(glol_req, 1) if (proc == "PRODUCCION_ARE" and glol_req) else None,
            "koh_kg": round(est_pot, 2) if proc == "PRODUCCION_ARE" else None,
            "fuel_l": round(_fuel_l, 0) if proc == "PRODUCCION_ARE" else None,
            "are_objetivo_kg": round(are_kg, 0) if proc == "PRODUCCION_ARE" else None,
            "agua_agc_pct": round(agua_frac * 100, 2) if proc == "PRODUCCION_ARE" else None,
            "aporte_glicerina_pct": _aporte if proc == "PRODUCCION_ARE" else None,
            "litros_glicerina_total": round(litros_gli_tot, 1) if proc == "PRODUCCION_ARE" else None,
            "formula_id": are_formula_id, "formula_nombre": are_formula_nombre,
            "inicio_programado": _inicio_iso, "cronograma": (_crono_rows or None),
            "glicerina_fuente": {"fresca_tanque": gli_fresca.get("idt"),
                                 "recuperada_tanque": gli_recup.get("idt")},
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
                        " tiempo_estimado_horas, parametros_proceso, id_tanque_are_final, id_tanque_gli_recup, "
                        " estado, id_usuario_estado, motivo_estado, observaciones) "
                        "VALUES (CURRENT_DATE,'REACTORES',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,"
                        " 'PLANIFICADO',%s,'Planificado por dirección',%s) RETURNING id_batch",
                        (uid, ident, int(fila["id_bien_uso"]), proc, pf_id, calidad, corr, catal,
                         horas, _json.dumps(params), dest_are_final, dest_gli_recup, uid, (obs or None)))
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

                    # Glicerina: fresca y recuperada, cada una como movimiento desde su tanque
                    if proc == "PRODUCCION_ARE":
                        for _src, _txt, _pcode in ((gli_fresca, "Glicerina fresca", "GLICERINA-PURA"),
                                                   (gli_recup, "Glicerina recuperada", "GLICERINA-RECUP")):
                            _pid = None
                            try:
                                _pr = productos[productos["codigo_producto"] == _pcode]
                                _pid = int(_pr.iloc[0]["id_producto"]) if not _pr.empty else None
                            except Exception:
                                _pid = None
                            _picks = _src.get("tanques") or (
                                [{"idt": _src.get("idt"), "l": float(_src.get("l") or 0),
                                  "dens": float(_src.get("dens") or dens_gli)}]
                                if float(_src.get("l") or 0) > 0 else [])
                            for _p in _picks:
                                _ll = float(_p.get("l") or 0)
                                if _ll <= 0:
                                    continue
                                _dn = float(_p.get("dens") or dens_gli)
                                _mov("INSUMO", _pid, _txt, None, ("TANQUE" if _p.get("idt") else "PORTERIA"),
                                     _p.get("idt"), None, round(_ll * _dn, 1), round(_ll, 1))
                                n_mov += 1

                    # Insumos estimados (glicerina ya arriba; catalizador/fuel) → sólo movimiento
                    # (en la planificación aún no tienen ticket/tanque confirmado; la fuente real
                    #  la define el operario al ejecutar).
                    for cod_ins, rol, kg in insumos_calc:
                        if not kg or kg <= 0:
                            continue
                        _dl_ = DENS_INSUMO.get(cod_ins)
                        _it = insumo_tanque.get(cod_ins)
                        _mov(rol, None, cod_ins, cod_ins, ("TANQUE" if _it else "PORTERIA"), _it, None, kg,
                             (round(kg / _dl_, 1) if _dl_ else None))
                        n_mov += 1
            try:
                cat.clear()
            except Exception:
                pass
            _borrador_limpiar(conectar, USR)
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
        "SELECT m.ticket_mov, m.estado_mov, m.rol, COALESCE(m.producto,m.codigo_insumo) AS item, "
        "       m.fuente, COALESCE(t.nombre, m.tanque_label, m.ticket_porteria) AS origen, "
        "       m.cantidad, m.unidad, m.kg, m.litros "
        "FROM produccion.fact_movimiento_stock m "
        "LEFT JOIN produccion.dim_tanque t ON t.id_tanque=m.id_tanque "
        "WHERE m.id_batch=%s AND m.anulado IS NOT TRUE ORDER BY m.id_mov_stock", (int(id_batch),))


def confirmar_movimientos_plan(cur, id_batch, uid):
    cur.execute(
        "UPDATE produccion.fact_movimiento_stock "
        "SET estado_mov='EJECUTADO', id_usuario_ejecuta=%s, ejecutado_en=now(), momento=now() "
        "WHERE id_batch=%s AND estado_mov='PLANIFICADO' AND anulado IS NOT TRUE",
        (int(uid), int(id_batch)))
    return cur.rowcount
