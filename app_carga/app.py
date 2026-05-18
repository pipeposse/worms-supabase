"""worms_supabase / app_carga / app.py · Streamlit + Supabase + login + admin + anulación."""
from __future__ import annotations
import json, sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.db import (
    conectar, convertir, login as login_db,
    crear_usuario, reset_pin, cambiar_rol, cambiar_sector, set_activo,
    cambiar_mi_pin,
    listar_mis_cargas, anular_registro, puede_anular,
)
from etl.config import DATABASE_URL

st.set_page_config(page_title="WORMS Carga", layout="wide")


# ---------- LOGIN -----------------------------------------------------------
def usuarios_disponibles():
    if not DATABASE_URL: return []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public")
                cur.execute(
                    "SELECT nombre, nombre_full FROM dim_usuario "
                    "WHERE activo ORDER BY nombre_full"
                )
                return cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []


def pantalla_login():
    st.title("🔐 WORMS · Carga Producción")
    st.caption("Iniciá sesión para continuar.")
    usuarios = usuarios_disponibles()
    if not usuarios:
        st.error("No se puede conectar a la base. Verificá `.env` y la conexión.")
        st.stop()
    opciones = {f"{full} ({n})": n for n, full in usuarios}
    sel = st.selectbox("Usuario", list(opciones.keys()))
    pin = st.text_input("PIN (4-6 dígitos)", type="password", max_chars=6)
    if st.button("Ingresar", type="primary", use_container_width=True):
        if not pin:
            st.error("Ingresá el PIN."); return
        u = login_db(opciones[sel], pin)
        if u is None:
            st.error("Usuario o PIN incorrecto, o usuario desactivado."); return
        st.session_state.user = u
        st.rerun()


def cerrar_sesion():
    if "user" in st.session_state: del st.session_state["user"]
    st.rerun()


if "user" not in st.session_state:
    pantalla_login(); st.stop()

USR = st.session_state.user

with st.sidebar:
    st.markdown(f"### 👤 {USR['nombre_full']}")
    st.caption(f"`{USR['nombre']}` · rol **{USR['rol']}**")
    if USR.get("sector"):
        st.caption(f"Sector default: **{USR['sector']}**")
    if st.button("🔑 Cambiar mi PIN", use_container_width=True):
        st.session_state.show_chg_pin = True
    st.button("Cerrar sesión", on_click=cerrar_sesion, use_container_width=True)
    st.divider()
    st.caption("Base: Supabase")

st.title("Carga de datos · WORMS")

if st.session_state.get("show_chg_pin"):
    with st.expander("🔑 Cambiar mi PIN", expanded=True):
        with st.form("chg_pin"):
            p_act = st.text_input("PIN actual", type="password", max_chars=6)
            p_new = st.text_input("PIN nuevo (4-6 dígitos)", type="password", max_chars=6)
            p_new2 = st.text_input("Repetir PIN nuevo", type="password", max_chars=6)
            ok = st.form_submit_button("Confirmar cambio", type="primary")
        if ok:
            if not p_new.isdigit() or not (4 <= len(p_new) <= 6):
                st.error("El PIN debe ser numérico de 4 a 6 dígitos.")
            elif p_new != p_new2:
                st.error("Los PINs no coinciden.")
            else:
                try:
                    cambiar_mi_pin(USR["id_usuario"], p_act, p_new)
                    st.success("✅ PIN actualizado.")
                    st.session_state.show_chg_pin = False
                except Exception as e:
                    st.error(str(e))


@st.cache_data(ttl=300)
def cat(query, params=None):
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


productos = cat(
    "SELECT id_producto, codigo_producto, corriente, tipo_producto, "
    "rango_kg_min, rango_kg_max FROM dim_producto "
    "WHERE activo AND tipo_producto IN ('MP','FINAL') ORDER BY codigo_producto"
)
productos_mp    = productos[productos["tipo_producto"] == "MP"]
productos_obt   = productos  # salida puede ser MP (vuelve al proceso) o FINAL

# Catálogos para REACTORES

tipos_proceso  = cat("SELECT codigo, descripcion FROM dic_tipo_proceso WHERE activo ORDER BY codigo")
etapas_proc    = cat("SELECT codigo, descripcion, orden FROM dic_etapa_proceso WHERE activo ORDER BY orden")
params_proceso = cat("SELECT codigo, descripcion, unidad, aplica_a FROM dic_parametro_proceso WHERE activo ORDER BY codigo")
constantes     = cat("SELECT codigo, valor FROM dic_constante_proceso")
def K(cod, default=None):
    """Lookup de constante química."""
    r = constantes[constantes["codigo"]==cod]
    return float(r.iloc[0]["valor"]) if not r.empty else default
bienes_uso_full = cat("SELECT id_bien_uso, codigo, nombre_ui, capacidad_max_l, consumo_fuel_kg_x_tn, consumo_naoh_kg_x_tn, consumo_potasio_kg_x_tn FROM dim_bien_uso WHERE activo ORDER BY codigo")
sectores = cat("SELECT codigo, nombre_ui FROM dic_sector WHERE activo ORDER BY codigo")
calidades = cat("SELECT codigo, descripcion FROM dic_calidad WHERE activo ORDER BY orden")
turnos = cat("SELECT codigo FROM dic_turno WHERE activo")
insumos_cat = cat("SELECT codigo, descripcion, unidad FROM dic_insumo WHERE activo ORDER BY codigo")


tabs = ["🏭 Producción", "📊 Observación", "✏️ Mis cargas", "🕒 Audit"]
if USR["rol"] == "ADMIN":
    tabs.append("⚙️ Admin")
tab_objs = st.tabs(tabs)


# =========================================================================
# TAB PRODUCCIÓN  (sin st.form para feedback en vivo + sub-tabs NUEVA/EDITAR/MUESTRAS)
# =========================================================================
with tab_objs[0]:
    st.subheader("🏭 Carga de producción")
    sub_nueva, sub_edit, sub_eval, sub_dec, sub_gasto = st.tabs(["➕ Nueva carga", "✏️ Avanzar etapa", "\U0001f9ea Evaluación interna", "\U0001f4a7 Salida de decantación", "\u26a0\ufe0f Gasto extraordinario"])

    # ---------- SUB-TAB: NUEVA CARGA ----------
    with sub_nueva:
        tipo_op = st.radio(
            "Tipo de operación",
            options=["NORMAL", "RECUPERACION"],
            format_func=lambda x: "🏭 Normal (consume MP)" if x == "NORMAL"
                                  else "♻️ Recuperación (sin MP)",
            horizontal=True, key="b_tipo",
        )
        es_recup = (tipo_op == "RECUPERACION")
        if es_recup:
            st.info("Modo recuperación: no se carga materia prima.")

        c1, c2, c3 = st.columns(3)
        fecha_b = c1.date_input("Fecha *", date.today(), max_value=date.today(), key="b_f")
        sector_codigos = sectores["codigo"].tolist()
        sector_idx = sector_codigos.index(USR["sector"]) if USR.get("sector") and USR["sector"] in sector_codigos else 0
        sector = c2.selectbox(
            "Sector *", sector_codigos, key="b_s", index=sector_idx,
            format_func=lambda c: sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"]
        )
        turno = c3.selectbox("Turno", turnos["codigo"], key="b_t")

        es_reactor = (sector == "REACTORES")

        label_id = {
            "BACHAS":       "N° de bacha *",
            "RECUPERACION": "N° de pileta *",
            "REACTORES":    "N° de ticket *",
            "EXPO":         "N° de ticket *",
        }.get(sector, "Identificador")
        identificador = st.text_input(label_id, max_chars=20, key="b_id",
                                      placeholder="ej. T-2026-04-001 / B-12 / P-3")

        # Bloque REACTORES
        id_bien_sel = None
        tipo_proceso_sel = None
        etapa_sel = None
        inicio_dt = None
        fin_dt = None
        tiempo_est = None
        acidez_oleico_v = None; glicerol_v = None
        est_glice_kg = est_naoh_kg = est_potasio_kg = est_fuel_kg = None
        if es_reactor:
            st.markdown("**Reactor + proceso + etapa**")
            cR1, cR2, cR3 = st.columns(3)
            cod_bien = cR1.selectbox(
                "Bien de uso *", bienes_uso_full["codigo"].tolist(), key="b_bien",
                format_func=lambda c: bienes_uso_full[bienes_uso_full["codigo"]==c].iloc[0]["nombre_ui"]
            )
            fila_bien = bienes_uso_full[bienes_uso_full["codigo"]==cod_bien].iloc[0]
            id_bien_sel = int(fila_bien["id_bien_uso"])
            tipo_proceso_sel = cR2.selectbox(
                "Proceso *", tipos_proceso["codigo"].tolist(), key="b_tproc",
                format_func=lambda c: tipos_proceso[tipos_proceso["codigo"]==c].iloc[0]["descripcion"]
            )
            etapa_sel = cR3.selectbox(
                "Etapa actual *", etapas_proc["codigo"].tolist(), key="b_etapa",
                format_func=lambda c: etapas_proc[etapas_proc["codigo"]==c].iloc[0]["descripcion"]
            )

            st.caption(f"🔧 Capacidad: {int(fila_bien['capacidad_max_l'] or 0):,} L  ·  Fuel {fila_bien['consumo_fuel_kg_x_tn']:.1f} kg/TN  ·  NaOH {fila_bien['consumo_naoh_kg_x_tn']:.1f} kg/TN  ·  K {fila_bien['consumo_potasio_kg_x_tn']:.3f} kg/TN")

            # --- Inputs iniciales para formula de carga (PRODUCCION_ARE) ---
            if tipo_proceso_sel == "PRODUCCION_ARE":
                st.markdown("**Inputs iniciales (dispara la formulación)**")
                cF1, cF2, cF3 = st.columns(3)
                acidez_oleico_v = cF1.number_input("Acidez oleico (%)", 0.0, 100.0, step=0.1, key="b_acidez_ol")
                glicerol_v      = cF2.number_input("% Glicerol en glicerina", 0.0, 100.0, value=80.0, step=0.1, key="b_glicerol")
                q_ag_kg_ref     = cF3.number_input("Q AG a procesar (kg)", 0.0, 100000.0, step=100.0, key="b_qag_ref")

                # Formula del Excel:
                # Q_glice_kg = Q_AG_kg * (acidez/100) * (PMg/(PMa*2)) * (1/(glicerol/100)) * factor_exceso
                PMa = K("PMa", 282); PMg = K("PMg", 92); FE = K("factor_exceso_gli", 1.1)
                D_GLI = K("densidad_glicerina", 1.25)
                if q_ag_kg_ref > 0 and acidez_oleico_v > 0 and glicerol_v > 0:
                    est_glice_kg = q_ag_kg_ref * (acidez_oleico_v/100) * (PMg/(PMa*2)) * (1/(glicerol_v/100)) * FE
                    tn = q_ag_kg_ref / 1000.0
                    est_naoh_kg    = tn * (fila_bien["consumo_naoh_kg_x_tn"] or 0)
                    est_potasio_kg = tn * (fila_bien["consumo_potasio_kg_x_tn"] or 0)
                    est_fuel_kg    = tn * (fila_bien["consumo_fuel_kg_x_tn"] or 0)
                    cE1, cE2, cE3, cE4 = st.columns(4)
                    cE1.metric("Glicerina est.", f"{est_glice_kg:,.0f} kg", f"{est_glice_kg/D_GLI:,.0f} L")
                    cE2.metric("NaOH est.",     f"{est_naoh_kg:,.1f} kg")
                    cE3.metric("Potasio est.",  f"{est_potasio_kg:,.2f} kg")
                    cE4.metric("Fuel est.",     f"{est_fuel_kg:,.0f} kg")
                    st.caption(f"📐 Fórmula: Q_glice = Q_AG × (acidez/100) × (PMg/(PMa×2)) × (1/(glicerol/100)) × {FE}")
            st.markdown("**Horarios**")
            cH1, cH2, cH3, cH4, cH5 = st.columns(5)
            f_ini = cH1.date_input("Fecha inicio", date.today(), key="b_fini")
            h_ini = cH2.time_input("Hora inicio",  key="b_hini")
            f_fin = cH3.date_input("Fecha fin",    date.today(), key="b_ffin")
            h_fin = cH4.time_input("Hora fin",     key="b_hfin")
            tiempo_est = cH5.number_input("T. estimado (h)", 0.0, 48.0, value=6.0, step=0.5, key="b_test")
            from datetime import datetime as _dt
            inicio_dt = _dt.combine(f_ini, h_ini)
            fin_dt    = _dt.combine(f_fin, h_fin)
            if fin_dt < inicio_dt:
                st.error("Fecha/hora de fin anterior al inicio.")

        # Producto obtenido / kg / calidad
        # En REACTORES: solo se completan al llegar a EN_TANQUE. En otros sectores: ahora.
        p_obt = None
        kg_obt = 0.0
        calidad_b = ""
        rmin = rmax = None
        fuera_rango = False
        p_buscado = None
        calidad_buscada = ""
        if es_reactor:
            st.markdown("**Producto buscado (target)** — lo que se quiere obtener con la reacción")
            cTG1, cTG2 = st.columns(2)
            opt_obj = productos_obt["codigo_producto"].tolist()
            sug = None
            if tipo_proceso_sel == "PRODUCCION_ARE": sug = "ARE-A"
            if tipo_proceso_sel == "DESGOMADO_ACUOSO": sug = "AFE-S"
            idx_obj = opt_obj.index(sug) if (sug and sug in opt_obj) else 0
            p_buscado = cTG1.selectbox(
                "Producto buscado *", opt_obj, index=idx_obj, key="b_pbusc",
                format_func=lambda c: f"{c} {'⭐' if productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL' else ''}"
            )
            calidad_buscada = cTG2.selectbox("Calidad buscada *", calidades["codigo"].tolist(), key="b_calbusc")
            st.caption("ℹ️ El producto **obtenido real** y su calidad se cargan al cerrar la reacción en la etapa EN_TANQUE (sub-tab 'Avanzar etapa').")
        else:
            st.markdown("**Producto obtenido**")
            cOB1, cOB2 = st.columns(2)
            opciones_obt = productos_obt["codigo_producto"].tolist()
            p_obt = cOB1.selectbox(
                "Producto obtenido *", opciones_obt, key="b_po",
                format_func=lambda c: f"{c} {'⭐' if productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL' else ''}"
            )
            kg_obt = cOB2.number_input("Kg obtenido *", 0.0, 1_000_000.0, key="b_ko")
            fila_p = productos_obt[productos_obt["codigo_producto"] == p_obt].iloc[0]
            rmin, rmax = fila_p["rango_kg_min"], fila_p["rango_kg_max"]
            if pd.notna(rmin) and pd.notna(rmax):
                st.caption(f"\U0001f4cf Rango habitual: {int(rmin):,} – {int(rmax):,} kg")
            if pd.notna(rmin) and pd.notna(rmax) and kg_obt > 0:
                fuera_rango = bool((kg_obt < rmin) or (kg_obt > rmax))
            calidad_b = st.selectbox("Calidad final", [""] + calidades["codigo"].tolist(), key="b_cal")

        # Materia prima
        mps_ingresadas = []
        if not es_recup:
            st.markdown("**Materia prima**")
            permite_multi = (p_obt == "AG-E") or (sector == "EXPO")
            max_mp = 5 if permite_multi else 1
            n_mp = 1 if not permite_multi else st.number_input(
                "Cantidad de materias primas", 1, max_mp,
                value=2 if permite_multi else 1, key="b_n_mp"
            )
            for i in range(int(n_mp)):
                cMP1, cMP2 = st.columns(2)
                cod = cMP1.selectbox(
                    f"Producto inicial #{i+1} *",
                    productos_mp["codigo_producto"].tolist(),
                    key=f"b_pi_{i}"
                )
                kg = cMP2.number_input(f"Kg inicial #{i+1} *", 0.0, 1_000_000.0, key=f"b_ki_{i}")
                if cod and kg > 0:
                    mps_ingresadas.append((cod, float(kg)))
            if mps_ingresadas:
                p_ini, kg_ini = mps_ingresadas[0]
            else:
                p_ini, kg_ini = "", 0.0
        else:
            p_ini, kg_ini = "", 0.0

        # Bloque GLICERINA (solo PRODUCCION_ARE)
        gli_fl=gli_fk=gli_rl=gli_rk=gli_pct=None
        if tipo_proceso_sel == "PRODUCCION_ARE":
            st.markdown("**Glicerina**")
            cG1, cG2, cG3, cG4, cG5 = st.columns(5)
            gli_fl  = cG1.number_input("Fresca (L)",   0.0, 100000.0, key="b_glfl")
            gli_fk  = cG2.number_input("Fresca (kg)",  0.0, 100000.0, key="b_glfk")
            gli_rl  = cG3.number_input("Recup. (L)",   0.0, 100000.0, key="b_glrl")
            gli_rk  = cG4.number_input("Recup. (kg)",  0.0, 100000.0, key="b_glrk")
            gli_pct = cG5.number_input("% real recup.", 0.0, 100.0, step=0.1, key="b_glpct")
            st.caption("ℹ️ Densidad glicerina ≈ 1.26 kg/L · si solo cargás L, kg se puede calcular.")

        # Bloque AGUA (solo DESGOMADO_ACUOSO)
        agua_lts_v = None
        if tipo_proceso_sel == "DESGOMADO_ACUOSO":
            st.markdown("**Agua de proceso**")
            agua_lts_v = st.number_input("Cantidad de agua (L)", 0.0, 100000.0, step=10.0, key="b_agua")

        # Insumos
        st.markdown("**Insumos**")
        n_ins = st.number_input("Cantidad de insumos", 0, 10, value=0, key="b_n_ins")
        insumos_dict = {}
        for i in range(int(n_ins)):
            ic1, ic2 = st.columns([2, 1])
            ins_cod = ic1.selectbox(
                f"Insumo #{i+1}", insumos_cat["codigo"].tolist(), key=f"b_ins_{i}",
                format_func=lambda c: f"{insumos_cat[insumos_cat['codigo']==c].iloc[0]['descripcion']} ({c})",
            )
            ins_unidad = insumos_cat[insumos_cat["codigo"] == ins_cod].iloc[0]["unidad"]
            ins_cant = ic2.number_input(f"Cantidad ({ins_unidad})", 0.0, 100000.0, key=f"b_cant_{i}")
            if ins_cant > 0:
                insumos_dict[ins_cod] = float(ins_cant)

        # Parámetros de proceso (aplicables al tipo seleccionado)
        parametros_dict = {}
        if es_reactor and tipo_proceso_sel:
            st.markdown("**Parámetros iniciales/finales del proceso**")
            aplicables = params_proceso[params_proceso["aplica_a"].apply(
                lambda lst: tipo_proceso_sel in (lst if isinstance(lst, list) else [])
            )]
            if not aplicables.empty:
                cols_per_row = 3
                rows = [aplicables.iloc[i:i+cols_per_row] for i in range(0, len(aplicables), cols_per_row)]
                for row in rows:
                    cs = st.columns(cols_per_row)
                    for j, (_, p) in enumerate(row.iterrows()):
                        val = cs[j].number_input(
                            f"{p['descripcion']} ({p['unidad']})",
                            min_value=0.0, max_value=1_000_000.0, step=0.1,
                            key=f"b_par_{p['codigo']}"
                        )
                        if val and val > 0:
                            parametros_dict[p["codigo"]] = float(val)

        motivo_rango = ""
        if fuera_rango:
            st.warning(f"⚠️ {kg_obt:,.0f} kg fuera del rango ({int(rmin):,}–{int(rmax):,}).")
            motivo_rango = st.text_input("Motivo fuera de rango * (≥5 chars)", max_chars=200, key="b_motivo_rng")

        obs = st.text_input("Observaciones", max_chars=200, key="b_obs")
        submit_b = st.button("✅ Guardar carga", type="primary", use_container_width=True, key="b_submit")

        if submit_b:
            errs = []
            if not es_reactor and kg_obt <= 0:
                errs.append("Kg obtenido > 0.")
            if not es_recup and (not p_ini or kg_ini <= 0):
                errs.append("En NORMAL la materia prima es obligatoria.")
            if fuera_rango and len(motivo_rango.strip()) < 5:
                errs.append("Motivo fuera de rango obligatorio (≥5).")
            if es_reactor and (not tipo_proceso_sel or not etapa_sel):
                errs.append("REACTORES requiere proceso y etapa.")
            if errs:
                for e in errs: st.error(e)
            else:
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            pid_ini = None
                            if p_ini:
                                cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s",(p_ini,))
                                pid_ini = cur.fetchone()[0]
                            pid_buscado = None
                            if p_buscado:
                                cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s",(p_buscado,))
                                pid_buscado = cur.fetchone()[0]
                            pid_obt = None
                            if p_obt:
                                cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s",(p_obt,))
                                pid_obt = cur.fetchone()[0]
                            mp_extras = [{"producto": c, "kg": k} for c, k in mps_ingresadas[1:]] if not es_recup else []
                            cur.execute(
                                "INSERT INTO fact_batch_proceso ("
                                "  fecha, sector, turno, id_usuario_carga, tipo_operacion,"
                                "  identificador_unidad,"
                                "  id_producto_inicial, kg_inicial, id_producto_obtenido, kg_obtenido,"
                                "  horas_trabajadas, calidad_final, insumos, materias_primas_extras,"
                                "  id_bien_uso, tipo_proceso, etapa_actual, inicio_ts, fin_ts, tiempo_estimado_horas,"
                                "  parametros_proceso,"
                                "  id_producto_buscado, calidad_buscada,"
                                "  acidez_oleico_pct, glicerol_pct,"
                                "  estimado_glicerina_kg, estimado_naoh_kg, estimado_potasio_kg, estimado_fuel_kg,"
                                "  gli_fresca_lts, gli_fresca_kg, gli_recup_lts, gli_recup_kg, gli_pct_real,"
                                "  agua_lts,"
                                "  observaciones, fuera_de_rango, motivo_fuera_rango"
                                ") VALUES ("
                                "  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,"
                                "  %s,%s,%s,%s,%s,%s,%s::jsonb,"
                                "  %s,%s,%s,%s,%s,%s,"
                                "  %s,%s,%s,%s,%s,"
                                "  %s,"
                                "  %s,%s,%s"
                                ") RETURNING id_batch",
                                (fecha_b.isoformat(), sector, turno, int(USR["id_usuario"]), tipo_op,
                                 (identificador or None),
                                 pid_ini, float(kg_ini) if kg_ini else None, pid_obt, float(kg_obt) if kg_obt else None,
                                 None, calidad_b or None,
                                 json.dumps(insumos_dict), json.dumps(mp_extras),
                                 id_bien_sel, tipo_proceso_sel, etapa_sel,
                                 inicio_dt.isoformat() if inicio_dt else None,
                                 fin_dt.isoformat() if fin_dt else None,
                                 float(tiempo_est) if tiempo_est else None,
                                 json.dumps(parametros_dict),
                                 pid_buscado, calidad_buscada or None,
                                 acidez_oleico_v or None, glicerol_v or None,
                                 est_glice_kg, est_naoh_kg, est_potasio_kg, est_fuel_kg,
                                 gli_fl or None, gli_fk or None, gli_rl or None, gli_rk or None, gli_pct or None,
                                 agua_lts_v or None,
                                 obs or None, bool(fuera_rango), motivo_rango or None)
                            )
                            id_b = cur.fetchone()[0]
                        audit.insert("fact_batch_proceso", id_b,
                                     {"sector": sector, "proceso": tipo_proceso_sel,
                                      "producto": p_obt, "kg": kg_obt, "fuera_rango": bool(fuera_rango)})
                    st.success(f"✅ Carga #{id_b} guardada. Ticket: {identificador or '-'}")
                    cat.clear()
                except Exception as e:
                    st.exception(e)

    # ---------- SUB-TAB: EDITAR POR TICKET ----------
    with sub_edit:
        st.caption("Buscá un ticket reciente y actualizá etapa / parámetros sin recargar todo.")
        df_rec = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha, b.sector,
                   b.tipo_proceso, b.etapa_actual,
                   pb.codigo_producto AS buscado, b.calidad_buscada,
                   p.codigo_producto AS obtenido, b.kg_obtenido
            FROM fact_batch_proceso b
            LEFT JOIN dim_producto p  ON p.id_producto  = b.id_producto_obtenido
            LEFT JOIN dim_producto pb ON pb.id_producto = b.id_producto_buscado
            WHERE NOT b.anulado AND b.sector='REACTORES'
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        if df_rec.empty:
            st.info("Sin cargas en REACTORES todavía.")
        else:
            opt = df_rec.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['fecha']} · {r['tipo_proceso']} · etapa {r['etapa_actual']}", axis=1).tolist()
            sel = st.selectbox("Seleccionar ticket", opt, key="e_sel")
            r = df_rec.iloc[opt.index(sel)]
            id_batch_edit = int(r["id_batch"])

            cE1, cE2 = st.columns(2)
            nueva_etapa = cE1.selectbox(
                "Avanzar etapa a", etapas_proc["codigo"].tolist(),
                index=etapas_proc["codigo"].tolist().index(r["etapa_actual"]) if r["etapa_actual"] in etapas_proc["codigo"].tolist() else 0,
                format_func=lambda c: etapas_proc[etapas_proc["codigo"]==c].iloc[0]["descripcion"],
                key="e_etapa"
            )
            if cE2.button("💾 Actualizar etapa", use_container_width=True, key="e_save"):
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("UPDATE fact_batch_proceso SET etapa_actual=%s WHERE id_batch=%s",
                                        (nueva_etapa, id_batch_edit))
                        audit.log("U","fact_batch_proceso",id_batch_edit,{"etapa_actual": nueva_etapa})
                    st.success(f"Etapa actualizada a {nueva_etapa}.")
                    cat.clear()
                except Exception as e:
                    st.exception(e)

    # ---------- SUB-TAB: CARGAR MUESTRA INTERMEDIA ----------
    with sub_eval:
        st.caption("Durante la reacción podés tomar muestras y cargar las mediciones (acidez, ppm, % goma).")
        df_rec2 = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha,
                   b.tipo_proceso, b.etapa_actual
            FROM fact_batch_proceso b
            WHERE NOT b.anulado AND b.sector='REACTORES'
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        if df_rec2.empty:
            st.info("Sin cargas en REACTORES todavía.")
        else:
            opt2 = df_rec2.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['tipo_proceso']}", axis=1).tolist()
            sel2 = st.selectbox("Reacción / ticket", opt2, key="m_sel")
            r2 = df_rec2.iloc[opt2.index(sel2)]
            tipo_actual = r2["tipo_proceso"]

            etapa_m = st.selectbox(
                "Etapa de la muestra", etapas_proc["codigo"].tolist(),
                format_func=lambda c: etapas_proc[etapas_proc["codigo"]==c].iloc[0]["descripcion"],
                key="m_etapa"
            )
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
                            audit.insert("fact_evaluacion_interna", id_m, med)
                        st.success(f"Evaluación interna #{id_m} guardada.")
                    except Exception as e:
                        st.exception(e)




    # ---------- SUB-TAB: SALIDA DE DECANTACIÓN ----------
    with sub_dec:
        st.caption("Al decantar salen productos paralelos: glicerina (con su % glicerol) o fondo de tanque, etc.")
        df_dec = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha, b.tipo_proceso
            FROM fact_batch_proceso b
            WHERE NOT b.anulado AND b.sector='REACTORES'
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        if df_dec.empty:
            st.info("Sin cargas en REACTORES.")
        else:
            optd = df_dec.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['tipo_proceso']}", axis=1).tolist()
            seld = st.selectbox("Reacción", optd, key="d_sel")
            rd = df_dec.iloc[optd.index(seld)]
            cD1, cD2 = st.columns(2)
            prod_sal = cD1.selectbox(
                "Producto que sale",
                productos["codigo_producto"].tolist(), key="d_prod",
                format_func=lambda c: c
            )
            destino = cD2.text_input("Destino (tanque/sector)", max_chars=40, key="d_dest")
            cD3, cD4, cD5 = st.columns(3)
            kg_d  = cD3.number_input("kg",  0.0, 100000.0, key="d_kg")
            lts_d = cD4.number_input("L",   0.0, 100000.0, key="d_l")
            gpct  = cD5.number_input("% glicerol (si glicerina)", 0.0, 100.0, key="d_gpct")
            obs_d = st.text_input("Obs.", max_chars=200, key="d_obs")
            if st.button("\U0001f4be Guardar salida", type="primary", use_container_width=True, key="d_save"):
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s",(prod_sal,))
                            pid = cur.fetchone()[0]
                            cur.execute("""
                                INSERT INTO fact_salida_decantacion
                                (id_batch, id_producto, kg, lts, glicerol_pct, destino_tanque, observaciones, id_usuario)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_salida
                            """, (int(rd["id_batch"]), pid, kg_d or None, lts_d or None,
                                  gpct or None, destino or None, obs_d or None, int(USR["id_usuario"])))
                            id_s = cur.fetchone()[0]
                        audit.insert("fact_salida_decantacion", id_s,
                                     {"producto": prod_sal, "kg": kg_d, "destino": destino})
                    st.success(f"Salida #{id_s} guardada.")
                except Exception as e:
                    st.exception(e)

    # ---------- SUB-TAB: GASTO EXTRAORDINARIO ----------
    with sub_gasto:
        st.caption("Cuando se gastó MÁS de lo formulado: fuel, glicerina, potasio, soda, etc. Con motivo.")
        df_g = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha, b.tipo_proceso
            FROM fact_batch_proceso b
            WHERE NOT b.anulado AND b.sector='REACTORES'
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        if df_g.empty:
            st.info("Sin cargas en REACTORES.")
        else:
            optg = df_g.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['tipo_proceso']}", axis=1).tolist()
            selg = st.selectbox("Reacción", optg, key="g_sel")
            rg = df_g.iloc[optg.index(selg)]
            cG1, cG2 = st.columns([2,1])
            ins_g = cG1.selectbox(
                "Insumo gastado de más",
                insumos_cat["codigo"].tolist(), key="g_ins",
                format_func=lambda c: f"{insumos_cat[insumos_cat['codigo']==c].iloc[0]['descripcion']} ({c})"
            )
            unidad_g = insumos_cat[insumos_cat["codigo"]==ins_g].iloc[0]["unidad"]
            cant_g = cG2.number_input(f"Cantidad ({unidad_g})", 0.0, 100000.0, key="g_cant")
            motivo_g = st.text_input("Motivo * (mín 5 chars)", max_chars=200, key="g_mot",
                                     placeholder="ej. perdida por fuga, recarga adicional por baja conversión")
            if st.button("\u26a0\ufe0f Registrar gasto extra", type="primary", use_container_width=True, key="g_save"):
                if cant_g <= 0:
                    st.error("Cantidad > 0.")
                elif len(motivo_g.strip()) < 5:
                    st.error("Motivo obligatorio (mín 5 chars).")
                else:
                    try:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                cur.execute("""
                                    INSERT INTO fact_gasto_extra
                                    (id_batch, codigo_insumo, cantidad, motivo, id_usuario)
                                    VALUES (%s,%s,%s,%s,%s) RETURNING id_gasto_extra
                                """, (int(rg["id_batch"]), ins_g, float(cant_g), motivo_g.strip(), int(USR["id_usuario"])))
                                id_g = cur.fetchone()[0]
                            audit.insert("fact_gasto_extra", id_g,
                                         {"insumo": ins_g, "cantidad": cant_g, "motivo": motivo_g})
                        st.success(f"Gasto extra #{id_g} registrado.")
                    except Exception as e:
                        st.exception(e)


# =========================================================================
# TAB OBSERVACIÓN · resumen visual de cargas
# =========================================================================
with tab_objs[1]:
    st.subheader("📊 Observación de producción")
    cF1, cF2, cF3 = st.columns(3)
    rango_dias = cF1.slider("Días hacia atrás", 1, 90, 30, key="o_dias")
    sector_filt = cF2.selectbox(
        "Sector", ["(todos)"] + sectores["codigo"].tolist(), key="o_sec",
        format_func=lambda c: "(todos)" if c=="(todos)" else sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"]
    )
    ticket_q = cF3.text_input("Buscar ticket / identificador", key="o_tq")

    where = ["NOT b.anulado", "b.creado_en >= NOW() - INTERVAL %s"]
    params_q = [f"{int(rango_dias)} days"]
    if sector_filt != "(todos)":
        where.append("b.sector=%s"); params_q.append(sector_filt)
    if ticket_q.strip():
        where.append("b.identificador_unidad ILIKE %s"); params_q.append(f"%{ticket_q.strip()}%")
    sql = f"""
        SELECT b.id_batch, b.fecha, b.sector, b.tipo_proceso, b.etapa_actual,
               b.identificador_unidad AS ticket,
               p.codigo_producto AS obtenido, b.kg_obtenido,
               p_ini.codigo_producto AS mp, b.kg_inicial,
               u.nombre AS cargado_por, bu.codigo AS reactor,
               b.fuera_de_rango
        FROM fact_batch_proceso b
        JOIN dim_producto p ON p.id_producto = b.id_producto_obtenido
        LEFT JOIN dim_producto p_ini ON p_ini.id_producto = b.id_producto_inicial
        LEFT JOIN dim_bien_uso bu ON bu.id_bien_uso = b.id_bien_uso
        LEFT JOIN dim_usuario u ON u.id_usuario = b.id_usuario_carga
        WHERE {' AND '.join(where)}
        ORDER BY b.creado_en DESC
    """
    df_obs = cat(sql, tuple(params_q))

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Cargas", len(df_obs))
    k2.metric("Kg obtenidos", f"{df_obs['kg_obtenido'].sum():,.0f}" if not df_obs.empty else "0")
    k3.metric("Kg MP", f"{df_obs['kg_inicial'].fillna(0).sum():,.0f}" if not df_obs.empty else "0")
    k4.metric("Fuera de rango", int(df_obs["fuera_de_rango"].sum()) if not df_obs.empty else 0)

    st.markdown("**Cargas en el rango seleccionado**")
    if df_obs.empty:
        st.info("Sin cargas para estos filtros.")
    else:
        st.dataframe(df_obs, use_container_width=True, hide_index=True)

        # Producción final por producto
        st.markdown("**Producción por producto (kg)**")
        prod_x_prod = df_obs.groupby("obtenido", as_index=False)["kg_obtenido"].sum().sort_values("kg_obtenido", ascending=False)
        st.bar_chart(prod_x_prod, x="obtenido", y="kg_obtenido")

        # Gasto de insumos (consolida JSONB)
        st.markdown("**Gasto de insumos (período)**")
        df_ins = cat(f"""
            SELECT key AS insumo, SUM((value)::numeric) AS total
            FROM fact_batch_proceso b, jsonb_each_text(b.insumos)
            WHERE NOT b.anulado
              AND b.creado_en >= NOW() - INTERVAL %s
              { "AND b.sector=%s" if sector_filt != "(todos)" else "" }
            GROUP BY key ORDER BY total DESC
        """, tuple([f"{int(rango_dias)} days"] + ([sector_filt] if sector_filt != "(todos)" else [])))
        if df_ins.empty:
            st.caption("Sin insumos cargados en el período.")
        else:
            st.dataframe(df_ins, use_container_width=True, hide_index=True)


# =========================================================================
# TAB MIS CARGAS  (anular registros mal cargados)
# =========================================================================
with tab_objs[2]:
    st.subheader("✏️ Mis cargas · anular registros")
    rol = USR["rol"]
    if rol == "OPERADOR":
        st.caption(f"Ves SOLO tus cargas. Podés anular dentro de las **24 h**.")
        dias = 7
    elif rol == "SUPERVISOR":
        st.caption(f"Ves cargas de TODOS. Podés anular dentro de **7 días**.")
        dias = 30
    else:
        st.caption("Ves TODAS las cargas. Podés anular sin límite de tiempo.")
        dias = 60

    dias = st.slider("Días hacia atrás a mostrar", 1, 60, dias)

    try:
        rows = listar_mis_cargas(USR["id_usuario"], rol, dias)
    except Exception as e:
        st.exception(e); rows = []

    if not rows:
        st.info("No hay cargas en el rango seleccionado.")
    else:
        df = pd.DataFrame(rows, columns=[
            "tipo","id","fecha","sector","detalle","valor",
            "anulado","creado_en","cargado_por"
        ])
        df["estado"] = df["anulado"].apply(lambda x: "🚫 ANULADO" if x else "✅ activo")
        st.dataframe(
            df[["tipo","id","fecha","cargado_por","sector","detalle","valor","creado_en","estado"]],
            use_container_width=True, hide_index=True
        )

        st.divider()
        st.markdown("**Seleccionar registro para anular:**")
        activos = [r for r in rows if not r[6]]  # no anulados
        if not activos:
            st.info("No hay registros activos para anular.")
        else:
            opciones = {
                f"#{r[1]} · {r[0]} · {r[2]} · {r[8]} · {r[4] or '—'}": r
                for r in activos
            }
            sel = st.selectbox("Registro", list(opciones.keys()))
            r_sel = opciones[sel]
            tabla_sel = "fact_batch_proceso"  # única tabla anulable hoy
            propio = (r_sel[8] == USR["nombre"])
            ok, motivo_check = puede_anular(rol, propio, r_sel[7])

            cinfo = st.columns([2,1])
            with cinfo[0]:
                if ok:
                    st.success(f"✅ Podés anular: {motivo_check}")
                else:
                    st.error(f"❌ No podés anular: {motivo_check}")
            with cinfo[1]:
                st.metric("Cargado por", r_sel[8])

            with st.form("form_anular"):
                motivo = st.text_input("Motivo de la anulación * (obligatorio, min 5 caracteres)",
                                        max_chars=200,
                                        placeholder="ej. error de carga, valor mal tipeado")
                conf = st.checkbox("Confirmo que quiero anular este registro")
                submit_a = st.form_submit_button("🚫 Anular registro",
                                                  type="primary", disabled=not ok)
            if submit_a:
                if not conf:
                    st.error("Marcá la casilla de confirmación.")
                elif len(motivo.strip()) < 5:
                    st.error("Motivo demasiado corto.")
                else:
                    try:
                        anular_registro(USR["id_usuario"], tabla_sel, r_sel[1], motivo)
                        st.success(f"✅ Registro #{r_sel[1]} anulado.")
                        st.info("Si el dato anulado era erróneo, ahora podés cargar el correcto desde la pestaña correspondiente.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


# =========================================================================
# TAB AUDIT
# =========================================================================
with tab_objs[3]:
    st.subheader("Auditoría · últimos 100 eventos")
    df = cat(
        "SELECT e.ts, u.nombre AS usuario, u.nombre_full, e.operacion, e.tabla, e.pk_valor, e.cambios "
        "FROM produccion.aud_eventos e "
        "JOIN produccion.dim_usuario u ON u.id_usuario = e.id_usuario "
        "ORDER BY e.ts DESC LIMIT 100"
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


# =========================================================================
# TAB ADMIN (solo rol ADMIN)
# =========================================================================
if USR["rol"] == "ADMIN":
    with tab_objs[4]:
        st.subheader("⚙️ Gestión de usuarios")
        with st.expander("➕ Crear nuevo usuario", expanded=False):
            with st.form("form_user_new"):
                c1, c2 = st.columns(2)
                n_nombre = c1.text_input("Usuario (login) *", max_chars=30, placeholder="ej. sosa")
                n_full = c2.text_input("Nombre completo *", max_chars=80, placeholder="ej. José Sosa")
                c3, c4 = st.columns(2)
                n_pin = c3.text_input("PIN (4-6 dígitos) *", type="password", max_chars=6)
                n_rol = c4.selectbox("Rol *", ["OPERADOR", "SUPERVISOR", "ADMIN"])
                n_sector = st.selectbox("Sector default", [""] + sectores["codigo"].tolist())
                crear = st.form_submit_button("Crear usuario", type="primary")
            if crear:
                if not n_nombre or not n_full or not n_pin:
                    st.error("Completá los campos obligatorios.")
                elif not n_pin.isdigit() or not (4 <= len(n_pin) <= 6):
                    st.error("El PIN debe ser numérico de 4 a 6 dígitos.")
                else:
                    try:
                        nid = crear_usuario(USR["id_usuario"], n_nombre.lower().strip(),
                                             n_full, n_pin, n_rol, n_sector or None)
                        st.success(f"✅ Usuario '{n_nombre}' creado (id #{nid}).")
                        cat.clear()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        df_u = cat("SELECT id_usuario, nombre, nombre_full, rol, sector, activo, ultimo_login "
                   "FROM produccion.dim_usuario ORDER BY activo DESC, nombre")
        st.dataframe(df_u, use_container_width=True, hide_index=True)

        st.markdown("**Acciones por usuario:**")
        sel_user = st.selectbox(
            "Seleccionar usuario",
            df_u.apply(lambda r: f"{r['nombre_full']} ({r['nombre']}) [{'activo' if r['activo'] else 'inactivo'}]", axis=1).tolist()
        )
        u_idx = df_u.apply(lambda r: f"{r['nombre_full']} ({r['nombre']}) [{'activo' if r['activo'] else 'inactivo'}]", axis=1).tolist().index(sel_user)
        u_row = df_u.iloc[u_idx]; u_id = int(u_row["id_usuario"])
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            st.markdown("**Estado**")
            if u_row["activo"]:
                if st.button("🚫 Desactivar usuario", key=f"deact_{u_id}", use_container_width=True):
                    try: set_activo(USR["id_usuario"], u_id, False); st.success("Desactivado."); cat.clear(); st.rerun()
                    except Exception as e: st.error(str(e))
            else:
                if st.button("✅ Reactivar usuario", key=f"act_{u_id}", use_container_width=True):
                    try: set_activo(USR["id_usuario"], u_id, True); st.success("Reactivado."); cat.clear(); st.rerun()
                    except Exception as e: st.error(str(e))
        with ac2:
            st.markdown("**Reset PIN**")
            with st.form(f"form_resetpin_{u_id}"):
                npin = st.text_input("PIN nuevo (4-6 dígitos)", type="password", max_chars=6, key=f"npin_{u_id}")
                if st.form_submit_button("🔑 Resetear PIN", use_container_width=True):
                    if not npin.isdigit() or not (4 <= len(npin) <= 6):
                        st.error("PIN inválido.")
                    else:
                        try: reset_pin(USR["id_usuario"], u_id, npin); st.success(f"PIN reseteado para {u_row['nombre']}.")
                        except Exception as e: st.error(str(e))
        with ac3:
            st.markdown("**Rol / Sector**")
            with st.form(f"form_rol_{u_id}"):
                nrol = st.selectbox("Rol", ["OPERADOR","SUPERVISOR","ADMIN"],
                                     index=["OPERADOR","SUPERVISOR","ADMIN"].index(u_row["rol"]),
                                     key=f"nr_{u_id}")
                opciones_sec = [""] + sectores["codigo"].tolist()
                idx_sec = opciones_sec.index(u_row["sector"]) if u_row["sector"] in opciones_sec else 0
                nsec = st.selectbox("Sector default", opciones_sec, index=idx_sec, key=f"ns_{u_id}")
                if st.form_submit_button("💾 Aplicar cambios", use_container_width=True):
                    try:
                        if nrol != u_row["rol"]: cambiar_rol(USR["id_usuario"], u_id, nrol)
                        if (nsec or None) != u_row["sector"]: cambiar_sector(USR["id_usuario"], u_id, nsec or None)
                        st.success("Cambios aplicados."); cat.clear(); st.rerun()
                    except Exception as e: st.error(str(e))