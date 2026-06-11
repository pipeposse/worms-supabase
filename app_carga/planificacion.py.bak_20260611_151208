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
    if USR.get("rol") not in ROLES_DIRECCION:
        st.warning("Sección exclusiva de dirección (SUPERVISOR / ADMIN).")
        return
    if not all([callable(proceso_desde_mp), callable(fuente_mp_combinada), callable(densidad_de), callable(K)]) \
       or productos is None or bienes is None or getattr(productos, "empty", True) or getattr(bienes, "empty", True):
        st.error("No se pudieron cargar los catálogos/funciones de Cargas. Reintentá.")
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

    # ---------- Estimados por fórmula ----------
    st.markdown("#### 4 · Insumos estimados por fórmula")
    insumos_calc = []  # (codigo_insumo, rol, kg, fuente_default)
    gli_mov = None     # glicerina como movimiento (sin codigo_insumo)
    gli_recup_kg = None  # glicerina recuperada estimada (kg) — vuelve en decantación
    if proc == "PRODUCCION_ARE":
        if q_ag > 0 and acidez > 0 and glicerol_v:
            gli_consumido = q_ag * (acidez / 100) * (PMg / (PMa * 2))   # glicerol puro que reacciona (estequiométrico)
            gli_puro = gli_consumido * FE                               # glicerol cargado (con exceso)
            est_gli = gli_puro / (glicerol_v / 100)                     # glicerina total a cargar (según pureza)
            # Glicerina recuperada = (cargada - glicerol consumido) x eficiencia de decantación (ajustable POR REACTOR)
            f_recup = float(K("factor_recuperacion_gli", 0.9) or 0.9)
            try:
                _fr = cat("SELECT factor FROM produccion.dic_factor_recup_gli WHERE id_bien_uso=%s",
                          (int(fila["id_bien_uso"]),))
                if not _fr.empty and _fr.iloc[0]["factor"] is not None:
                    f_recup = float(_fr.iloc[0]["factor"])
            except Exception:
                pass
            gli_recup_kg = max(0.0, (est_gli - gli_consumido) * f_recup)
            dens_gli = float(K("densidad_glicerina", 1.25) or 1.25)
            tn = q_ag / 1000.0
            est_naoh = tn * float(fila["consumo_naoh_kg_x_tn"] or 0) if catal == "NAOH" else 0.0
            est_pot = tn * float(fila["consumo_potasio_kg_x_tn"] or 0) if catal == "POTASIO" else 0.0
            est_fuel = tn * float(fila["consumo_fuel_kg_x_tn"] or 0)
            e1, e2, e3, e4 = st.columns(4)
            _gli_l = (est_gli / dens_gli)
            e1.metric("Glicerina a cargar", f"{_gli_l:,.0f} L", f"{est_gli:,.0f} kg · glicerol {glicerol_v:.0f}%")
            if catal == "NAOH":
                e2.metric("NaOH (catalizador)", f"{est_naoh:,.1f} kg")
            else:
                e2.metric("KOH (catalizador)", f"{est_pot:,.2f} kg")
            e3.metric("Glicerina recuperada", f"{gli_recup_kg/dens_gli:,.0f} L", f"{gli_recup_kg:,.0f} kg · factor {f_recup:.2f}")
            e4.metric("Fuel oil", f"{est_fuel:,.0f} kg")
            st.metric("ARE estimado", f"{q_ag/0.88:,.0f} L", f"{q_ag:,.0f} kg · {q_ag/1000:.1f} TN")
            st.caption(f"Recuperada = (glicerina cargada {est_gli:,.0f} − glicerol consumido {gli_consumido:,.0f}) × {f_recup:.2f} "
                       f"(factor de **{fila['nombre_ui']}**). Editá por reactor en `dic_factor_recup_gli`.")
            gli_mov = round(est_gli, 0)
            if catal == "NAOH":
                insumos_calc.append(("soda_kg", "CATALIZADOR", round(est_naoh, 1)))
            else:
                insumos_calc.append(("POTASIO", "CATALIZADOR", round(est_pot, 2)))
            insumos_calc.append(("FUEL_OIL", "INSUMO", round(est_fuel, 0)))
        else:
            st.info("Elegí la fuente de MP (para la acidez) y la muestra de glicerina (para el % glicerol) para ver los estimados.")
    else:  # DESGOMADO_ACUOSO
        pct_agua = float(K("desgomado_pct_agua", 5) or 5)
        merma = float(K("desgomado_merma_pct_esperada", 5) or 5)
        cons = cat("SELECT codigo_insumo, consumo_por_tn FROM produccion.dic_consumo_proceso "
                   "WHERE tipo_proceso=%s AND codigo_insumo='FUEL_OIL'", (proc,))
        fuel_rate = float(cons.iloc[0]["consumo_por_tn"]) if not cons.empty else 8.7
        # % goma desde el laboratorio (procesos_lab) de los tickets de AFE-SG elegidos
        _goma_def = 0.0
        _gtxt = "—"
        _tok = []
        for _p in (ports or []):
            if _p.get("fuente") == "TICKET" and _p.get("ticket"):
                _tok += [t.strip() for t in _re.split(r"[;,\s]+", str(_p["ticket"])) if t.strip()]
        # En desgomado (AFE-SG) la GOMA = SEDIMENTOS reportados en laboratorio (conclusión "SED = GOMA").
        # Fuente primaria: prc_sedimentos de los tickets elegidos; luego prc_goma_*; luego sedimentos del promedio.
        if _tok:
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
                                   help=f"Goma del laboratorio del AFE-SG ({_gtxt}). En AFE-SG la goma se mide como sedimentos. Ajustable.")
        if _tok and _goma_def == 0.0:
            st.caption("ℹ️ Los tickets elegidos no tienen % goma cargado en laboratorio (o está en 0).")
        agua_kg = round(kg_used * pct_agua / 100.0, 1)          # agua de proceso = 5% del peso de la MP
        fuel_kg = round(kg_used / 1000.0 * fuel_rate, 1)
        afe_s = round(kg_used * (1 - merma / 100.0), 0)         # AFE-S esperado (merma 5%)
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("% Goma", f"{pct_goma:.2f}%")
        d2.metric(f"Agua proceso ({pct_agua:.0f}%)", f"{agua_kg:,.0f} kg")
        d3.metric("Fuel", f"{fuel_kg:,.0f} kg")
        d4.metric("AFE-S esperado", f"{afe_s:,.0f} kg")
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

    obs = st.text_input("Observaciones", key="pl_obs", placeholder="opcional")

    st.divider()
    if st.button("✅ Generar ID de producción + tickets de movimiento", type="primary", use_container_width=True):
        mp_ports = [p for p in (ports or []) if float(p.get("kg", 0) or 0) > 0]
        if not mp_ports:
            st.error("Elegí una fuente de materia prima (portería o tanque) con cantidad > 0.")
            return
        mp_id = int(mp_df[mp_df["codigo_producto"] == mp].iloc[0]["id_producto"])
        ident = siguiente_identificador("REACTORES")
        params = {
            "kg_objetivo": round(q_ag, 0), "temp_inicial_c": temp, "tiempo_horas": horas,
            "acidez_pct": round(acidez, 3), "glicerol_pct": glicerol_v, "catalizador": catal,
            "glicerina_kg": gli_mov, "glicerina_recup_kg": gli_recup_kg, "pct_goma": pct_goma,
            "insumos_estimados": {c: k for c, _, k in insumos_calc},
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

                    # Glicerina (movimiento, sin codigo_insumo) desde su ticket de lab
                    if gli_mov and gli_mov > 0:
                        _mov("INSUMO", None, "Glicerina", None, "TICKET", None, gli_ticket, gli_mov, None)
                        n_mov += 1

                    # Insumos estimados (glicerina ya arriba; catalizador/fuel) → sólo movimiento
                    # (en la planificación aún no tienen ticket/tanque confirmado; la fuente real
                    #  la define el operario al ejecutar).
                    for cod_ins, rol, kg in insumos_calc:
                        if not kg or kg <= 0:
                            continue
                        _mov(rol, None, cod_ins, cod_ins, "PORTERIA", None, None, kg, None)
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
