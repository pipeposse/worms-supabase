"""Centro de Planificación (dirección) — versión completa.
Hereda la lógica de cargas/reactores: al elegir sector + proceso se preseleccionan
producto final (y su calidad), materias primas e insumos del proceso, con cantidades
de insumos por fórmula (consumo/TN). Cada MP/insumo tiene un DESPLEGABLE de origen
(Tanque o Portería). Resumen de parámetros de laboratorio de las fuentes elegidas.
Cronograma de etapas editable + cronograma de evaluaciones. Genera el ID PLANIFICADO
y un ticket de movimiento (MS-xxxx) por cada MP/insumo.

render(USR, cat, conectar, siguiente_identificador) recibe helpers de app.py.
"""
import json as _json
import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")


def _kg_litros(cantidad, unidad, dens):
    c = float(cantidad or 0)
    d = float(dens) if dens else None
    if unidad == "LT":
        return (round(c * d, 1) if d else None), c
    if unidad == "TN":
        kg = c * 1000.0
        return kg, (round(kg / d, 1) if d else None)
    return c, (round(c / d, 1) if d else None)


def _productos_proceso(cat, sector, tipo, rol):
    return cat(
        "SELECT DISTINCT p.id_producto, p.codigo_producto, p.nombre_producto, "
        "       COALESCE(p.densidad_g_ml,0.91) dens, COALESCE(p.corriente,'') corriente "
        "FROM produccion.dim_producto p "
        "JOIN produccion.dic_proceso_producto pp "
        "  ON pp.rol=%s AND (pp.tipo_proceso=%s OR pp.tipo_proceso IS NULL) "
        "     AND (pp.sector=%s OR pp.sector IS NULL) "
        "WHERE p.activo AND p.codigo_producto LIKE pp.patron "
        "ORDER BY p.codigo_producto", (rol, tipo, sector))


def _insumos_proceso(cat, tipo):
    return cat(
        "SELECT c.codigo_insumo, COALESCE(i.descripcion,c.codigo_insumo) descripcion, "
        "       c.consumo_por_tn, COALESCE(i.unidad,'KG') unidad "
        "FROM produccion.dic_consumo_proceso c "
        "LEFT JOIN produccion.dic_insumo i ON i.codigo=c.codigo_insumo "
        "WHERE c.tipo_proceso=%s AND upper(c.codigo_insumo) <> 'HORAS' "
        "ORDER BY c.codigo_insumo", (tipo,))


def render(USR, cat, conectar, siguiente_identificador):
    st.title("🗓️ Centro de Planificación")
    st.caption("Elegí sector y proceso: se preseleccionan producto final, materias primas e insumos. "
               "Cada MP/insumo tiene su desplegable de origen (tanque o portería).")
    if USR.get("rol") not in ROLES_DIRECCION:
        st.warning("Sección exclusiva de dirección (SUPERVISOR / ADMIN).")
        return

    reactores = cat("SELECT id_bien_uso, codigo, COALESCE(nombre_ui,codigo) nombre_ui, "
                    "COALESCE(capacidad_max_l,0) cap, COALESCE(consumo_fuel_kg_x_tn,0) cfuel, "
                    "COALESCE(consumo_naoh_kg_x_tn,0) cnaoh, COALESCE(consumo_potasio_kg_x_tn,0) cpot "
                    "FROM produccion.dim_bien_uso WHERE activo ORDER BY codigo")
    tipos = cat("SELECT codigo FROM produccion.dic_tipo_proceso WHERE activo ORDER BY codigo")
    tanques = cat("SELECT id_tanque, codigo, COALESCE(producto_principal_txt,'') prod "
                  "FROM produccion.dim_tanque WHERE activo ORDER BY codigo")
    ctes = cat("SELECT codigo, valor FROM produccion.dic_constante_proceso")
    K = {r.codigo: float(r.valor) for r in ctes.itertuples()} if not ctes.empty else {}
    PMa, PMg, FE = K.get("PMa", 282.0), K.get("PMg", 92.0), K.get("factor_exceso_gli", 1.1)
    DENS_AG = K.get("densidad_aagg", 0.9)
    stock = cat("SELECT codigo, litros_estimado FROM reporting.v_tanque_stock_estimado")
    stock_map = {r.codigo: float(r.litros_estimado or 0) for r in stock.itertuples()}
    params_tk = cat("SELECT DISTINCT ON (id_tanque) id_tanque, acidez_pct, agua_pct, sedimentos_pct, "
                    "densidad_g_ml, ppm_azufre, ppm_fosforo FROM produccion.fact_param_tanque "
                    "ORDER BY id_tanque, actualizado_en DESC NULLS LAST")

    if reactores.empty:
        st.error("Faltan reactores en el catálogo."); return

    react_opts = {f"{r.codigo} · {r.nombre_ui}": int(r.id_bien_uso) for r in reactores.itertuples()}
    react_info = {int(r.id_bien_uso): dict(cap=r.cap, cfuel=r.cfuel, cnaoh=r.cnaoh, cpot=r.cpot) for r in reactores.itertuples()}
    tank_by_code = {r.codigo: int(r.id_tanque) for r in tanques.itertuples()}
    tank_codes = [r.codigo for r in tanques.itertuples()]
    tipo_opts = [r.codigo for r in tipos.itertuples()] or ["PRODUCCION_ARE", "DESGOMADO_ACUOSO"]

    # ---------- 1 · Datos de la reacción ----------
    st.markdown("#### 1 · Datos de la reacción")
    c1, c2, c3 = st.columns(3)
    sector = c1.selectbox("Sector", ["REACTORES", "BACHAS", "EXPO", "RECUPERACION"], key="pl_sector")
    reactor_lbl = c2.selectbox("Reactor / bien de uso", list(react_opts.keys()), key="pl_reactor")
    tipo_proc = c3.selectbox("Tipo de proceso", tipo_opts, key="pl_tipo")

    finales = _productos_proceso(cat, sector, tipo_proc, "FINAL")
    if finales.empty:
        finales = cat("SELECT id_producto, codigo_producto, nombre_producto, COALESCE(densidad_g_ml,0.91) dens, COALESCE(corriente,'') corriente "
                      "FROM produccion.dim_producto WHERE activo AND tipo_producto='FINAL' ORDER BY codigo_producto")
    fin_opts = {f"{r.codigo_producto} · {r.nombre_producto}": int(r.id_producto) for r in finales.itertuples()}
    fin_dens = {int(r.id_producto): float(r.dens) for r in finales.itertuples()}
    fin_code = {int(r.id_producto): r.codigo_producto for r in finales.itertuples()}

    c4, c5 = st.columns(2)
    if len(fin_opts) == 1:
        pf_lbl = list(fin_opts.keys())[0]
        c4.info(f"Producto final (único del proceso): **{pf_lbl}**")
    else:
        pf_lbl = c4.selectbox("Producto final / calidad", list(fin_opts.keys()), key="pl_pf",
                              help="Para ARE elegí A o B; para AFE-S es único.")
    pf_id = fin_opts[pf_lbl]
    calidad = (fin_code.get(pf_id, "").split("-")[-1] or None)
    c5.metric("Calidad buscada", calidad or "única")

    info = react_info.get(react_opts[reactor_lbl], {})
    cap = float(info.get("cap", 0) or 0)
    c6, c7, c8, c9 = st.columns(4)
    kg_obj = c6.number_input("Kg objetivo", min_value=0.0, step=100.0,
                             value=float(round(cap * DENS_AG)) if cap else 0.0, key="pl_kg")
    temp = c7.number_input("Temp. inicial (°C)", min_value=0.0, step=5.0, value=80.0, key="pl_temp")
    horas = c8.number_input("Tiempo estimado (h)", min_value=0.0, step=0.5, value=4.0, key="pl_horas")
    acidez_obj = c9.number_input("Acidez objetivo (%)", min_value=0.0, step=0.5, key="pl_acid")

    q_ag = float(kg_obj or (cap * DENS_AG))
    est_fuel = q_ag / 1000.0 * float(info.get("cfuel", 0) or 0)
    est_naoh = q_ag / 1000.0 * float(info.get("cnaoh", 0) or 0)
    est_pot = q_ag / 1000.0 * float(info.get("cpot", 0) or 0)
    est_gli = (q_ag * (float(acidez_obj or 0) / 100.0) * (PMg / (PMa * 2)) * FE) if acidez_obj else 0.0
    with st.container(border=True):
        st.markdown(f"**🔧 {reactor_lbl.split(' · ')[-1]}** — capacidad {cap:,.0f} L · Q estimado {q_ag:,.0f} kg")
        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Glicerina (kg)", f"{est_gli:,.0f}")
        e2.metric("NaOH (kg)", f"{est_naoh:,.0f}")
        e3.metric("Potasio (kg)", f"{est_pot:,.0f}")
        e4.metric("Fuel (kg)", f"{est_fuel:,.0f}")
        e5.metric("ARE est. (kg)", f"{q_ag:,.0f}")

    def _origen_widgets(prefix, key, default_fuente="Tanque"):
        """Dibuja el desplegable de origen + tanque/ticket. Devuelve (fuente, id_tanque, tanque_label, ticket)."""
        oc1, oc2 = st.columns([1, 2])
        fuente = oc1.selectbox("Origen", ["Tanque", "Portería"],
                               index=(0 if default_fuente == "Tanque" else 1), key=f"{key}_f")
        if fuente == "Tanque":
            tcode = oc2.selectbox("Tanque", ["(elegir)"] + tank_codes, key=f"{key}_t")
            if tcode != "(elegir)":
                oc2.caption(f"Stock estimado: {stock_map.get(tcode, 0):,.0f} L")
                return "TANQUE", tank_by_code.get(tcode), tcode, None
            return "TANQUE", None, None, None
        tk = oc2.text_input("Ticket de portería", key=f"{key}_tk")
        return "TICKET", None, None, (tk.strip() or None)

    # ---------- 2 · Materias primas (del proceso) ----------
    st.markdown("#### 2 · Materias primas del proceso — marcá las que usás y elegí el origen")
    mp_cands = _productos_proceso(cat, sector, tipo_proc, "MP")
    if mp_cands.empty:
        st.warning("No hay materias primas definidas para este proceso (dic_proceso_producto).")
    mp_rows = []
    sel_tank_ids = []
    for r in mp_cands.itertuples():
        with st.container(border=True):
            h1, h2 = st.columns([3, 2])
            inc = h1.checkbox(f"**{r.codigo_producto}** · {r.nombre_producto}", key=f"mp_{r.codigo_producto}_i")
            cant = h2.number_input("Cantidad", min_value=0.0, step=100.0, key=f"mp_{r.codigo_producto}_c",
                                   label_visibility="collapsed")
            uni = h2.selectbox("Unidad", ["LT", "KG", "TN"], key=f"mp_{r.codigo_producto}_u", label_visibility="collapsed")
            fuente, idt, tlabel, tkp = _origen_widgets("mp", f"mp_{r.codigo_producto}")
            if inc and float(cant or 0) > 0:
                mp_rows.append(dict(id_producto=int(r.id_producto), nombre=r.nombre_producto, dens=float(r.dens),
                                    fuente=fuente, id_tanque=idt, tanque_label=tlabel, ticket=tkp,
                                    cantidad=float(cant), unidad=uni))
                if idt:
                    sel_tank_ids.append(idt)

    # ---------- 3 · Insumos del proceso (cantidad por fórmula) ----------
    st.markdown("#### 3 · Insumos del proceso — cantidad calculada por fórmula (editable)")
    ins_cands = _insumos_proceso(cat, tipo_proc)
    ins_rows = []
    for r in ins_cands.itertuples():
        cant_def = round(float(r.consumo_por_tn or 0) * q_ag / 1000.0, 1)
        with st.container(border=True):
            h1, h2 = st.columns([3, 2])
            inc = h1.checkbox(f"**{r.codigo_insumo}** · {r.descripcion}  · fórmula: {cant_def:,.1f} {r.unidad}",
                              value=True, key=f"in_{r.codigo_insumo}_i")
            cant = h2.number_input("Cantidad", min_value=0.0, step=1.0, value=float(cant_def),
                                   key=f"in_{r.codigo_insumo}_c", label_visibility="collapsed")
            rol = h2.selectbox("Rol", ["INSUMO", "CATALIZADOR"], key=f"in_{r.codigo_insumo}_r", label_visibility="collapsed")
            fuente, idt, tlabel, tkp = _origen_widgets("in", f"in_{r.codigo_insumo}", default_fuente="Portería")
            if inc and float(cant or 0) > 0:
                ins_rows.append(dict(codigo=r.codigo_insumo, rol=rol, fuente=fuente, id_tanque=idt,
                                     tanque_label=tlabel, ticket=tkp, cantidad=float(cant), unidad=r.unidad))
                if idt:
                    sel_tank_ids.append(idt)

    with st.expander("➕ Agregar insumo fuera de lista (manual)"):
        mc1, mc2, mc3 = st.columns([3, 1, 1])
        m_cod = mc1.text_input("Código / nombre del insumo", key="in_manual_cod")
        m_cant = mc2.number_input("Cantidad", min_value=0.0, step=1.0, key="in_manual_c")
        m_uni = mc3.selectbox("Unidad", ["KG", "LT", "TN"], key="in_manual_u")
        if m_cod and float(m_cant or 0) > 0:
            mf, midt, mtl, mtk = _origen_widgets("inm", "in_manual", default_fuente="Portería")
            ins_rows.append(dict(codigo=m_cod.strip(), rol="INSUMO", fuente=mf, id_tanque=midt,
                                 tanque_label=mtl, ticket=mtk, cantidad=float(m_cant), unidad=m_uni))
            if midt:
                sel_tank_ids.append(midt)

    # ---------- 4 · Resumen de parámetros de laboratorio (fuentes elegidas) ----------
    st.markdown("#### 4 · Parámetros de laboratorio de las fuentes (tanques) elegidas")
    if sel_tank_ids and not params_tk.empty:
        lab = params_tk[params_tk["id_tanque"].isin(set(sel_tank_ids))].copy()
        if not lab.empty:
            lab = lab.merge(tanques[["id_tanque", "codigo"]], on="id_tanque", how="left")
            lab = lab[["codigo", "acidez_pct", "agua_pct", "sedimentos_pct", "densidad_g_ml", "ppm_azufre", "ppm_fosforo"]]
            st.dataframe(lab, use_container_width=True, hide_index=True)
            st.caption("Parámetros fundamentales para las fórmulas. Las muestras de portería se evalúan por su ticket de laboratorio.")
        else:
            st.caption("Los tanques elegidos aún no tienen parámetros de laboratorio cargados.")
    else:
        st.caption("Elegí MP/insumos desde tanque para ver sus parámetros de laboratorio.")

    # ---------- 5 · Cronograma de etapas (editable) ----------
    st.markdown("#### 5 · Cronograma de etapas (editable)")
    crono = cat("SELECT pe.orden, pe.etapa, COALESCE(e.descripcion,'') descripcion, "
                "pe.duracion_target_min FROM produccion.dic_proceso_etapa pe "
                "LEFT JOIN produccion.dic_etapa_proceso e ON e.codigo=pe.etapa "
                "WHERE pe.proceso_key=%s ORDER BY pe.orden", (tipo_proc,))
    crono_ed = crono
    if not crono.empty:
        crono_ed = st.data_editor(
            crono.rename(columns={"orden": "Orden", "etapa": "Etapa", "descripcion": "Descripción",
                                  "duracion_target_min": "Duración (min)"}),
            use_container_width=True, hide_index=True, key="pl_crono",
            column_config={"Duración (min)": st.column_config.NumberColumn(min_value=0, format="%.0f")})
        st.caption(f"Total estimado: {crono_ed['Duración (min)'].fillna(0).sum()/60.0:.1f} h "
                   "(se guarda como override de esta producción).")
    else:
        st.caption("Sin etapas definidas para el proceso.")

    # ---------- 6 · Cronograma de evaluaciones ----------
    st.markdown("#### 6 · Cronograma de evaluaciones internas")
    evcfg = cat("SELECT cadencia, etapa, COALESCE(observaciones,'') observaciones "
                "FROM produccion.dic_cronograma_eval WHERE tipo_proceso=%s AND activo", (tipo_proc,))
    if not evcfg.empty:
        st.dataframe(evcfg, use_container_width=True, hide_index=True)
        st.caption("Las evaluaciones se generan automáticamente al iniciar la reacción (según esta cadencia).")
    else:
        st.caption("Sin esquema de evaluación configurado para el proceso.")

    obs = st.text_input("Observaciones", key="pl_obs", placeholder="opcional")

    st.divider()
    if st.button("✅ Generar ID de producción + tickets de movimiento", type="primary", use_container_width=True):
        if not mp_rows:
            st.error("Marcá al menos una materia prima con cantidad mayor a 0 y su origen.")
            return
        ident = siguiente_identificador(sector)
        crono_payload = []
        if isinstance(crono_ed, pd.DataFrame) and not crono_ed.empty:
            for _, cr in crono_ed.iterrows():
                crono_payload.append({"etapa": cr.get("Etapa"), "min": float(cr.get("Duración (min)") or 0)})
        params = {
            "kg_objetivo": float(kg_obj or 0), "temp_inicial_c": float(temp or 0),
            "tiempo_horas": float(horas or 0), "acidez_objetivo_pct": float(acidez_obj or 0),
            "est_glicerina_kg": round(est_gli, 1), "est_naoh_kg": round(est_naoh, 1),
            "est_potasio_kg": round(est_pot, 1), "est_fuel_kg": round(est_fuel, 1),
            "cronograma_etapas": crono_payload,
        }
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO fact_batch_proceso "
                        "(fecha, sector, id_usuario_carga, identificador_unidad, id_bien_uso, tipo_proceso, "
                        " id_producto_buscado, calidad_buscada, tiempo_estimado_horas, parametros_proceso, "
                        " estado, id_usuario_estado, motivo_estado, observaciones) "
                        "VALUES (CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
                        " 'PLANIFICADO', %s, 'Planificado por dirección', %s) RETURNING id_batch",
                        (sector, uid, ident, react_opts[reactor_lbl], tipo_proc, pf_id,
                         calidad, float(horas or 0), _json.dumps(params), uid, (obs or None)))
                    id_b = cur.fetchone()[0]
                    n_mov = 0

                    def _mov(rol, id_producto, producto_txt, codigo_insumo, fuente, idt, tlabel, tkp, cant, uni, dens):
                        kg, litros = _kg_litros(cant, uni, dens)
                        fmov = "TANQUE" if fuente == "TANQUE" else "PORTERIA"
                        cur.execute(
                            "INSERT INTO fact_movimiento_stock "
                            "(momento, id_batch, identificador_prod, tipo_movimiento, rol, sentido, "
                            " id_producto, producto, codigo_insumo, fuente, id_tanque, tanque_label, ticket_porteria, "
                            " cantidad, unidad, kg, litros, id_usuario, origen, estado_mov, id_usuario_planifica, planificado_en) "
                            "VALUES (now(), %s, %s, 'SALIDA', %s, -1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                            " 'planificacion', 'PLANIFICADO', %s, now())",
                            (id_b, ident, rol, id_producto, producto_txt, codigo_insumo, fmov,
                             idt, tlabel, tkp, float(cant), uni, kg, litros, uid, uid))

                    for m in mp_rows:
                        cur.execute(
                            "INSERT INTO fact_batch_insumo (id_batch, rol, id_producto, cantidad, unidad, fuente, id_tanque, ticket_porteria, id_usuario) "
                            "VALUES (%s,'MP',%s,%s,%s,%s,%s,%s,%s)",
                            (id_b, m["id_producto"], m["cantidad"], m["unidad"], m["fuente"], m["id_tanque"], m["ticket"], uid))
                        _mov("MP", m["id_producto"], m["nombre"], None, m["fuente"], m["id_tanque"],
                             m["tanque_label"], m["ticket"], m["cantidad"], m["unidad"], m["dens"])
                        n_mov += 1

                    for s in ins_rows:
                        cur.execute(
                            "INSERT INTO fact_batch_insumo (id_batch, rol, codigo_insumo, cantidad, unidad, fuente, id_tanque, ticket_porteria, id_usuario) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (id_b, s["rol"], s["codigo"], s["cantidad"], s["unidad"], s["fuente"], s["id_tanque"], s["ticket"], uid))
                        _mov(s["rol"], None, s["codigo"], s["codigo"], s["fuente"], s["id_tanque"],
                             s["tanque_label"], s["ticket"], s["cantidad"], s["unidad"], None)
                        n_mov += 1
            try:
                cat.clear()
            except Exception:
                pass
            st.success(f"Producción **{ident}** (batch #{id_b}) planificada con **{n_mov} movimiento(s)** PLANIFICADO. "
                       "El operario los confirmará al iniciar.")
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
        "       fuente, COALESCE(tanque_label,ticket_porteria) AS origen, cantidad, unidad "
        "FROM produccion.fact_movimiento_stock "
        "WHERE id_batch=%s AND anulado IS NOT TRUE ORDER BY id_mov_stock", (int(id_batch),))


def confirmar_movimientos_plan(cur, id_batch, uid):
    cur.execute(
        "UPDATE produccion.fact_movimiento_stock "
        "SET estado_mov='EJECUTADO', id_usuario_ejecuta=%s, ejecutado_en=now(), momento=now() "
        "WHERE id_batch=%s AND estado_mov='PLANIFICADO' AND anulado IS NOT TRUE",
        (int(uid), int(id_batch)))
    return cur.rowcount
