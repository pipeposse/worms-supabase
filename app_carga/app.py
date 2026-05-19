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
    crear_usuario, reset_pin, cambiar_rol, cambiar_sector, cambiar_sectores, set_activo,
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
    if USR.get("sectores"):
        st.caption(f"Sectores: {', '.join(USR['sectores'])}")
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
    "rango_kg_min, rango_kg_max, "
    "usa_reactor, usa_bachas, usa_piletas, es_exportacion "
    "FROM dim_producto "
    "WHERE activo AND tipo_producto IN ('MP','FINAL') ORDER BY codigo_producto"
)

def productos_de_sector(sec):
    """Devuelve (productos_mp, productos_obt) filtrados por flag de sector."""
    flag = {
        "REACTORES":    "usa_reactor",
        "BACHAS":       "usa_bachas",
        "RECUPERACION": "usa_piletas",
        "EXPO":         "es_exportacion",
    }.get(sec)
    if flag and flag in productos.columns:
        df = productos[productos[flag] == True]
    else:
        df = productos
    return df[df["tipo_producto"] == "MP"], df

# Catálogos para REACTORES

tipos_proceso  = cat("SELECT codigo, descripcion FROM dic_tipo_proceso WHERE activo ORDER BY codigo")
etapas_proc    = cat("SELECT codigo, descripcion, orden FROM dic_etapa_proceso WHERE activo ORDER BY orden")
params_proceso = cat("SELECT codigo, descripcion, unidad, aplica_a FROM dic_parametro_proceso WHERE activo ORDER BY codigo")
duraciones_etapa = cat("""
    SELECT sector, tipo_proceso, etapa, duracion_target_min, duracion_min_min, duracion_max_min
    FROM dic_etapa_duracion
""")
consumos_proceso = cat("""
    SELECT tipo_proceso, codigo_insumo, consumo_por_tn, unidad_consumo, base_referencia, nota
    FROM dic_consumo_proceso
""")
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
        productos_mp, productos_obt = productos_de_sector(sector)
        if productos_mp.empty:
            st.warning(f"⚠️ No hay productos de tipo MP marcados para el sector {sector}. Revisá `dim_producto.usa_*` en Supabase.")

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
        est_glice_kg = est_naoh_kg = est_potasio_kg = est_fuel_kg = est_are_kg = None
        est_glicerol_puro_kg = None
        q_ag_kg_ref = 0.0
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

            # Duraciones esperadas por etapa para este (sector, proceso)
            dur_filt = duraciones_etapa[
                (duraciones_etapa["sector"]==sector) &
                (duraciones_etapa["tipo_proceso"]==tipo_proceso_sel)
            ]
            if not dur_filt.empty:
                total_target = int(dur_filt["duracion_target_min"].sum())
                etapas_order = etapas_proc.set_index("codigo")["orden"].to_dict()
                dur_filt = dur_filt.copy()
                dur_filt["orden"] = dur_filt["etapa"].map(etapas_order).fillna(99)
                dur_filt = dur_filt.sort_values("orden")
                resumen = " · ".join(
                    f"**{row['etapa']}** {int(row['duracion_target_min'])}m ({int(row['duracion_min_min'])}–{int(row['duracion_max_min'])})"
                    for _, row in dur_filt.iterrows()
                )
                st.caption(f"⏱️ Duraciones esperadas por etapa (min): {resumen}  ·  **Total target: {total_target} min** ({total_target/60:.1f} h)")

            # --- Inputs iniciales para formula de carga (PRODUCCION_ARE) ---
            if tipo_proceso_sel == "PRODUCCION_ARE":
                PMa   = K("PMa", 282)
                PMg   = K("PMg", 92)
                FE    = K("factor_exceso_gli", 1.1)
                D_GLI = K("densidad_glicerina", 1.25)
                D_AG  = K("densidad_aagg", 0.9)
                cap_l = float(fila_bien["capacidad_max_l"] or 0)
                q_ag_max_kg = cap_l * D_AG

                st.markdown("**📐 Fórmulas de carga (PRODUCCION_ARE)**")
                st.code(
                    "Q_glicerina (kg) = Q_AG × (acidez/100) × (PMg / (PMa × 2)) × (1 / (glicerol/100)) × factor_exceso\n"
                    f"                 = Q_AG × (acidez/100) × ({PMg}/({PMa}×2)) × (1/(glicerol/100)) × {FE}\n\n"
                    f"NaOH (kg)        = (Q_AG / 1000) × {fila_bien['consumo_naoh_kg_x_tn']} kg/TN\n"
                    f"Potasio (kg)     = (Q_AG / 1000) × {fila_bien['consumo_potasio_kg_x_tn']} kg/TN\n"
                    f"Fuel (kg)        = (Q_AG / 1000) × {fila_bien['consumo_fuel_kg_x_tn']} kg/TN",
                    language="text"
                )
                st.caption(f"🛢️ Capacidad del reactor: **{int(cap_l):,} L** → hasta **{int(q_ag_max_kg):,} kg** de AG (~{q_ag_max_kg/1000:.1f} TN). Densidad AG = {D_AG} kg/L.")

                st.markdown("**Inputs iniciales (dispara los estimados)**")
                cF1, cF2, cF3 = st.columns(3)
                acidez_oleico_v = cF1.number_input("Acidez oleico (%)", 0.0, 100.0, step=0.1, key="b_acidez_ol")
                glicerol_v      = cF2.number_input("% Glicerol en glicerina", 0.0, 100.0, value=80.0, step=0.1, key="b_glicerol")
                q_ag_kg_ref     = cF3.number_input(
                    "Q AG a procesar (kg)",
                    min_value=0,
                    max_value=int(q_ag_max_kg) if q_ag_max_kg > 0 else 200000,
                    value=int(q_ag_max_kg) if q_ag_max_kg > 0 else 0,
                    step=100, key="b_qag_ref",
                    help=f"Sugerido por capacidad: {int(q_ag_max_kg):,} kg"
                )

                # variables disponibles para comparación posterior
                est_glicerol_puro_kg = None
                if q_ag_kg_ref > 0 and acidez_oleico_v > 0 and glicerol_v > 0:
                    # Glicerol PURO necesario (química pura, sin descontar pureza)
                    est_glicerol_puro_kg = float(q_ag_kg_ref) * (acidez_oleico_v/100) * (PMg/(PMa*2)) * FE
                    # Glicerina total a cargar (con la pureza informada): glicerol_puro / (glicerol/100)
                    est_glice_kg = est_glicerol_puro_kg / (glicerol_v/100)
                    # Cuánto más glicerina por la impureza vs glicerina 100% pura
                    mas_por_impureza = est_glice_kg - est_glicerol_puro_kg

                    tn = float(q_ag_kg_ref) / 1000.0
                    est_naoh_kg    = tn * float(fila_bien["consumo_naoh_kg_x_tn"]    or 0)
                    est_potasio_kg = tn * float(fila_bien["consumo_potasio_kg_x_tn"] or 0)
                    est_fuel_kg    = tn * float(fila_bien["consumo_fuel_kg_x_tn"]    or 0)
                    est_are_kg     = float(q_ag_kg_ref)  # 1:1 aprox

                    st.markdown("**🧮 Insumos estimados a cargar**")
                    cE1, cE2, cE3, cE4 = st.columns(4)
                    cE1.metric(
                        "Glicerina a cargar",
                        f"{est_glice_kg:,.0f} kg",
                        f"+{mas_por_impureza:,.0f} kg por pureza {glicerol_v:.0f}%"
                    )
                    cE2.metric("NaOH",      f"{est_naoh_kg:,.1f} kg")
                    cE3.metric("Potasio",   f"{est_potasio_kg:,.2f} kg")
                    cE4.metric("Fuel",      f"{est_fuel_kg:,.0f} kg")

                    st.caption(
                        f"💡 Glicerol **puro** necesario = **{est_glicerol_puro_kg:,.0f} kg**. "
                        f"Como la glicerina tiene {glicerol_v:.0f}% de glicerol, hay que cargar "
                        f"**{est_glice_kg:,.0f} kg** de glicerina ({mas_por_impureza:,.0f} kg extra para compensar la impureza)."
                    )

                    st.markdown("**🎯 Producto final esperado**")
                    st.metric("ARE estimado", f"{est_are_kg:,.0f} kg", f"~{est_are_kg/1000:.1f} TN")
                    st.caption("⚠️ Aproximación 1:1 sobre la masa de AG. Cuando tengas rendimiento real de planta lo ajustamos.")
                else:
                    st.info("Cargá **acidez oleico**, **% glicerol** y **Q AG** para ver los estimados (glicerina, NaOH, potasio, fuel) y la producción esperada.")

            # Estimación específica DESGOMADO_ACUOSO (fuel por TN AFE-S generado)
            if tipo_proceso_sel == "DESGOMADO_ACUOSO":
                st.markdown("**📐 Estimación DESGOMADO_ACUOSO**")
                cDA1, cDA2 = st.columns(2)
                tn_afe_target = cDA1.number_input(
                    "TN de AFE-S a generar",
                    min_value=0.0, max_value=100.0, step=0.5, value=10.0,
                    key="b_tn_afe", help="Estimación de cuánto AFE-S vas a obtener (≈ AFE-SG procesado)."
                )
                fila_fuel = consumos_proceso[
                    (consumos_proceso["tipo_proceso"]=="DESGOMADO_ACUOSO") &
                    (consumos_proceso["codigo_insumo"]=="FUEL")
                ]
                if not fila_fuel.empty:
                    rate = float(fila_fuel.iloc[0]["consumo_por_tn"])
                    unidad_fuel = fila_fuel.iloc[0]["unidad_consumo"]
                    est_fuel_total = tn_afe_target * rate
                    cDA2.metric(f"Fuel estimado ({unidad_fuel})", f"{est_fuel_total:,.1f}",
                                f"{rate:.1f} {unidad_fuel}/TN AFE-S")
                    # Duración total esperada
                    dur_d = duraciones_etapa[
                        (duraciones_etapa["sector"]==sector) &
                        (duraciones_etapa["tipo_proceso"]=="DESGOMADO_ACUOSO")
                    ]
                    if not dur_d.empty:
                        total_min = int(dur_d["duracion_target_min"].sum())
                        st.caption(f"⏱️ Duración total esperada: **~{total_min} min**")
                else:
                    st.caption("⚠️ Cargá un consumo en `dic_consumo_proceso` para ver fuel estimado.")

            st.markdown("**Horarios**")
            cH1, cH2, cH3, cH4 = st.columns(4)
            f_ini = cH1.date_input("Fecha inicio", date.today(), key="b_fini")
            h_ini = cH2.time_input("Hora inicio",  key="b_hini")
            f_fin = cH3.date_input("Fecha fin",    date.today(), key="b_ffin")
            h_fin = cH4.time_input("Hora fin",     key="b_hfin")
            from datetime import datetime as _dt
            inicio_dt = _dt.combine(f_ini, h_ini)
            fin_dt    = _dt.combine(f_fin, h_fin)
            # T. estimado = (fin - inicio) en horas, calculado en vivo
            delta_horas = (fin_dt - inicio_dt).total_seconds() / 3600 if fin_dt >= inicio_dt else 0
            tiempo_est = round(delta_horas, 2)
            st.caption(f"⏱️ Duración: **{tiempo_est:.2f} h** ({int(delta_horas*60)} min)")
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
            opt_obj = productos_obt["codigo_producto"].tolist()
            if tipo_proceso_sel == "DESGOMADO_ACUOSO":
                # Flujo fijo: AFE-SG → AFE-S
                cTG1, cTG2 = st.columns(2)
                p_buscado = cTG1.text_input("Producto buscado *", value="AFE-S", disabled=True, key="b_pbusc")
                calidad_buscada = cTG2.selectbox("Calidad buscada *", calidades["codigo"].tolist(), key="b_calbusc")
                st.caption("🔒 DESGOMADO_ACUOSO va siempre de **AFE-SG** → **AFE-S**.")
            elif tipo_proceso_sel == "PRODUCCION_ARE":
                # Solo productos que empiezan con ARE (familia biodiesel)
                opt_obj = [c for c in opt_obj if c.startswith("ARE")]
                if not opt_obj:
                    st.error("No hay productos ARE-* activos en dim_producto.")
                cTG1, cTG2 = st.columns(2)
                p_buscado = cTG1.selectbox(
                    "Producto buscado *", opt_obj, index=0, key="b_pbusc",
                    format_func=lambda c: f"{c} {'⭐' if productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL' else ''}"
                )
                calidad_buscada = cTG2.selectbox("Calidad buscada *", calidades["codigo"].tolist(), key="b_calbusc")
                st.caption("🔒 PRODUCCION_ARE solo admite productos de la familia **ARE-***.")
            else:
                cTG1, cTG2 = st.columns(2)
                p_buscado = cTG1.selectbox(
                    "Producto buscado *", opt_obj, index=0, key="b_pbusc",
                    format_func=lambda c: f"{c} {'⭐' if productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL' else ''}"
                )
                calidad_buscada = cTG2.selectbox("Calidad buscada *", calidades["codigo"].tolist(), key="b_calbusc")
            st.caption("ℹ️ El producto **obtenido real** y su calidad se cargan al cerrar la reacción en la etapa EN_TANQUE.")
        else:
            st.markdown("**Producto obtenido**")
            cOB1, cOB2 = st.columns(2)
            opciones_obt = productos_obt["codigo_producto"].tolist()
            p_obt = cOB1.selectbox(
                "Producto obtenido *", opciones_obt, key="b_po",
                format_func=lambda c: f"{c} {'⭐' if productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL' else ''}"
            )
            kg_obt = cOB2.number_input("Kg obtenido *", min_value=0, max_value=1_000_000, step=100, value=0, key="b_ko")
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
                opts_mp = productos_mp["codigo_producto"].tolist()
                # DESGOMADO_ACUOSO siempre arranca de AFE-SG
                if i == 0 and tipo_proceso_sel == "DESGOMADO_ACUOSO":
                    cod = cMP1.text_input(f"Producto inicial #{i+1} *", value="AFE-SG", disabled=True, key=f"b_pi_{i}")
                else:
                    default_idx = 0
                    cod = cMP1.selectbox(
                        f"Producto inicial #{i+1} *", opts_mp, index=default_idx,
                        key=f"b_pi_{i}"
                    )
                kg = cMP2.number_input(f"Kg inicial #{i+1} *", min_value=0, max_value=1_000_000, step=100, value=0, key=f"b_ki_{i}")
                if cod and kg > 0:
                    mps_ingresadas.append((cod, float(kg)))
            if mps_ingresadas:
                p_ini, kg_ini = mps_ingresadas[0]
            else:
                p_ini, kg_ini = "", 0.0
        else:
            p_ini, kg_ini = "", 0.0

        # Bloque GLICERINA (solo PRODUCCION_ARE)
        # Inputs: kg + % glicerol (fresca y recuperada). L se calcula con densidad.
        gli_fl = gli_fk = gli_rl = gli_rk = None
        gli_fresca_pct = gli_pct = None         # gli_pct = % glicerol recuperada (gli_pct_real)
        gli_pura_total = None
        if tipo_proceso_sel == "PRODUCCION_ARE":
            D_GLI = K("densidad_glicerina", 1.25)
            st.markdown("**Glicerina**")
            cG1, cG2, cG3, cG4 = st.columns(4)
            gli_fk         = cG1.number_input("Fresca (kg)",       min_value=0, max_value=100000, step=100, value=0, key="b_glfk")
            gli_fresca_pct = cG2.number_input("% glicerol fresca", 0.0, 100.0, step=0.1, value=99.5, key="b_glfpct")
            gli_rk         = cG3.number_input("Recuperada (kg)",   min_value=0, max_value=100000, step=100, value=0, key="b_glrk")
            gli_pct        = cG4.number_input("% glicerol recup.", 0.0, 100.0, step=0.1, value=80.0, key="b_glpct")

            # Cálculos derivados (en vivo)
            gli_fl = (gli_fk / D_GLI) if gli_fk else 0.0
            gli_rl = (gli_rk / D_GLI) if gli_rk else 0.0
            glicerol_fresca = (gli_fk or 0.0) * (gli_fresca_pct or 0.0) / 100
            glicerol_recup  = (gli_rk or 0.0) * (gli_pct or 0.0) / 100
            gli_pura_total = glicerol_fresca + glicerol_recup   # = glicerol total cargado

            cD1, cD2, cD3 = st.columns(3)
            cD1.metric("Fresca (L calc.)",     f"{gli_fl:,.1f} L")
            cD2.metric("Recuperada (L calc.)", f"{gli_rl:,.1f} L")
            cD3.metric("Glicerol total cargado",
                       f"{gli_pura_total:,.1f} kg",
                       f"fresca {glicerol_fresca:,.0f} + recup {glicerol_recup:,.0f}")
            st.caption(f"ℹ️ Densidad glicerina = {D_GLI} kg/L · L = kg / {D_GLI}. Glicerol = kg × %glicerol.")

            # Comparación con el glicerol PURO necesario según fórmula
            if est_glicerol_puro_kg and gli_pura_total > 0:
                desv_abs = gli_pura_total - est_glicerol_puro_kg
                desv_pct = desv_abs / est_glicerol_puro_kg * 100
                tol = 5.0  # tolerancia ±5%
                txt = f"Glicerol cargado **{gli_pura_total:,.0f} kg** vs requerido **{est_glicerol_puro_kg:,.0f} kg** → desvío **{desv_pct:+.1f}%** ({desv_abs:+,.0f} kg)"
                if abs(desv_pct) <= tol:
                    st.success("✅ " + txt + " · dentro del parámetro recomendado (±5%).")
                elif desv_pct > 0:
                    st.warning("⚠️ " + txt + " · **fuera** del recomendado: estás cargando glicerol de **más**.")
                else:
                    st.warning("⚠️ " + txt + " · **fuera** del recomendado: falta glicerol para la reacción.")
            elif est_glicerol_puro_kg:
                st.caption(f"💡 Para esta corrida se necesitan **{est_glicerol_puro_kg:,.0f} kg de glicerol puro** según la fórmula.")

        # Bloque AGUA (solo DESGOMADO_ACUOSO)
        agua_lts_v = None
        if tipo_proceso_sel == "DESGOMADO_ACUOSO":
            st.markdown("**Agua de proceso**")
            agua_lts_v = st.number_input("Cantidad de agua (L)", min_value=0, max_value=100000, step=100, value=0, key="b_agua")

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
                                "  estimado_are_kg, q_ag_planeado_kg,"
                                "  gli_fresca_lts, gli_fresca_kg, gli_fresca_pct,"
                                "  gli_recup_lts, gli_recup_kg, gli_pct_real,"
                                "  gli_pura_total_kg,"
                                "  agua_lts,"
                                "  observaciones, fuera_de_rango, motivo_fuera_rango"
                                ") VALUES ("
                                "  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,"
                                "  %s,%s,%s,%s,%s,%s,%s::jsonb,"
                                "  %s,%s,"
                                "  %s,%s,"
                                "  %s,%s,%s,%s,"
                                "  %s,%s,"
                                "  %s,%s,%s,"
                                "  %s,%s,%s,"
                                "  %s,"
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
                                 (float(est_glice_kg)  if est_glice_kg  is not None else None),
                                 (float(est_naoh_kg)   if est_naoh_kg   is not None else None),
                                 (float(est_potasio_kg) if est_potasio_kg is not None else None),
                                 (float(est_fuel_kg)   if est_fuel_kg   is not None else None),
                                 (float(est_are_kg)    if est_are_kg    is not None else None),
                                 (float(q_ag_kg_ref) if q_ag_kg_ref else None),
                                 (float(gli_fl) if gli_fl else None),
                                 (float(gli_fk) if gli_fk else None),
                                 (float(gli_fresca_pct) if gli_fresca_pct else None),
                                 (float(gli_rl) if gli_rl else None),
                                 (float(gli_rk) if gli_rk else None),
                                 (float(gli_pct) if gli_pct else None),
                                 (float(gli_pura_total) if gli_pura_total else None),
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
        st.caption("Al decantar pueden salir varios subproductos a la vez: glicerina recuperada, fondo de tanque, agua, etc.")
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
            tipo_actual_dec = rd["tipo_proceso"]

            # Lista de productos plausibles según proceso
            if tipo_actual_dec == "PRODUCCION_ARE":
                opciones_decant = ["GLICERINA","GLICERINA-FE","FONDO-TK","AGUA-PROC"]
            elif tipo_actual_dec == "DESGOMADO_ACUOSO":
                opciones_decant = ["FONDO-TK","AGUA-PROC","BORRA-A","BORRA-B"]
            else:
                opciones_decant = productos["codigo_producto"].tolist()
            # Filtrar a los que realmente existan en dim_producto
            opciones_decant = [c for c in opciones_decant if c in productos["codigo_producto"].tolist()]

            n_sal = st.number_input("Cantidad de subproductos a registrar", 1, 5, value=1, key="d_n")
            salidas = []
            for i in range(int(n_sal)):
                st.markdown(f"**Salida #{i+1}**")
                cD1, cD2 = st.columns(2)
                cod_sal = cD1.selectbox(
                    f"Producto #{i+1}", opciones_decant, key=f"d_prod_{i}"
                )
                destino_i = cD2.text_input(f"Destino (tanque/sector) #{i+1}", max_chars=40, key=f"d_dest_{i}")
                cD3, cD4, cD5 = st.columns(3)
                kg_i  = cD3.number_input(f"kg #{i+1}", min_value=0, max_value=100000, step=100, value=0, key=f"d_kg_{i}")
                # L calculado por densidad del producto si existe; si no, manual
                fila_p = productos[productos["codigo_producto"]==cod_sal].iloc[0] if cod_sal in productos["codigo_producto"].tolist() else None
                dens = float(fila_p["densidad_g_ml"]) if (fila_p is not None and pd.notna(fila_p.get("densidad_g_ml"))) else None
                if dens:
                    lts_i = (kg_i/dens) if kg_i else 0
                    cD4.metric("L (calc)", f"{lts_i:,.0f}")
                else:
                    lts_i = cD4.number_input(f"L #{i+1}", min_value=0, max_value=100000, step=100, value=0, key=f"d_l_{i}")
                gpct_i = cD5.number_input(f"% glicerol #{i+1} (si glicerina)", 0.0, 100.0, step=0.1, value=0.0, key=f"d_gpct_{i}")
                obs_i  = st.text_input(f"Obs. #{i+1}", max_chars=200, key=f"d_obs_{i}")
                if kg_i > 0 or (lts_i and lts_i > 0):
                    salidas.append({
                        "cod": cod_sal, "destino": destino_i,
                        "kg": int(kg_i) if kg_i else None,
                        "lts": float(lts_i) if lts_i else None,
                        "gpct": float(gpct_i) if gpct_i else None,
                        "obs": obs_i or None,
                    })

            if st.button("\U0001f4be Guardar salidas", type="primary", use_container_width=True, key="d_save"):
                if not salidas:
                    st.error("Cargá al menos una salida con kg o L > 0.")
                else:
                    try:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                ids = []
                                for s in salidas:
                                    cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s",(s["cod"],))
                                    pid = cur.fetchone()[0]
                                    cur.execute("""
                                        INSERT INTO fact_salida_decantacion
                                        (id_batch, id_producto, kg, lts, glicerol_pct, destino_tanque, observaciones, id_usuario)
                                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_salida
                                    """, (int(rd["id_batch"]), pid, s["kg"], s["lts"], s["gpct"], s["destino"], s["obs"], int(USR["id_usuario"])))
                                    ids.append(cur.fetchone()[0])
                            audit.log("I","fact_salida_decantacion",str(rd["id_batch"]),
                                      {"salidas": [{"prod": s["cod"], "kg": s["kg"], "destino": s["destino"]} for s in salidas]})
                        st.success(f"✅ {len(ids)} salida(s) registrada(s) (#{', #'.join(map(str,ids))}).")
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

        # ----- Plan vs Real (REACTORES con estimados cargados) -----
        st.markdown("**🎯 Plan vs Real (reactores)**")
        df_pvr = cat(f"""
            SELECT
              b.id_batch,
              b.identificador_unidad AS ticket,
              b.fecha,
              b.q_ag_planeado_kg,
              b.kg_inicial            AS q_ag_real_kg,
              b.estimado_glicerina_kg,
              b.estimado_naoh_kg,
              b.estimado_potasio_kg,
              b.estimado_fuel_kg,
              b.estimado_are_kg,
              b.kg_obtenido           AS are_real_kg,
              (b.insumos->>'GLICERINA')::numeric  AS gli_real_kg,
              (b.insumos->>'SODA')::numeric       AS naoh_real_kg,
              (b.insumos->>'POTASIO')::numeric    AS potasio_real_kg,
              (b.insumos->>'FUEL')::numeric       AS fuel_real_kg
            FROM fact_batch_proceso b
            WHERE NOT b.anulado AND b.sector='REACTORES'
              AND b.estimado_are_kg IS NOT NULL
              AND b.creado_en >= NOW() - INTERVAL %s
            ORDER BY b.fecha DESC, b.id_batch DESC
            LIMIT 50
        """, (f"{int(rango_dias)} days",))

        if df_pvr.empty:
            st.caption("Aún no hay reacciones con estimado cargado en este período.")
        else:
            # Calcular desvíos %
            import numpy as np
            def desvio(real, est):
                if est is None or est == 0 or pd.isna(est) or pd.isna(real): return None
                return round((real - est) / est * 100, 1)
            df_pvr["desv_ARE_%"]      = df_pvr.apply(lambda r: desvio(r["are_real_kg"], r["estimado_are_kg"]), axis=1)
            df_pvr["desv_Glice_%"]    = df_pvr.apply(lambda r: desvio(r["gli_real_kg"], r["estimado_glicerina_kg"]), axis=1)
            df_pvr["desv_NaOH_%"]     = df_pvr.apply(lambda r: desvio(r["naoh_real_kg"], r["estimado_naoh_kg"]), axis=1)
            df_pvr["desv_Potasio_%"]  = df_pvr.apply(lambda r: desvio(r["potasio_real_kg"], r["estimado_potasio_kg"]), axis=1)
            df_pvr["desv_Fuel_%"]     = df_pvr.apply(lambda r: desvio(r["fuel_real_kg"], r["estimado_fuel_kg"]), axis=1)

            st.dataframe(df_pvr[[
                "id_batch","ticket","fecha",
                "q_ag_planeado_kg","q_ag_real_kg",
                "estimado_glicerina_kg","gli_real_kg","desv_Glice_%",
                "estimado_naoh_kg","naoh_real_kg","desv_NaOH_%",
                "estimado_potasio_kg","potasio_real_kg","desv_Potasio_%",
                "estimado_fuel_kg","fuel_real_kg","desv_Fuel_%",
                "estimado_are_kg","are_real_kg","desv_ARE_%",
            ]], use_container_width=True, hide_index=True)

            # KPI de rendimiento promedio
            kP1, kP2, kP3 = st.columns(3)
            kP1.metric("Desv. ARE prom.",      f"{df_pvr['desv_ARE_%'].dropna().mean():+.1f}%"     if df_pvr['desv_ARE_%'].notna().any()    else "—")
            kP2.metric("Desv. Glicerina prom.", f"{df_pvr['desv_Glice_%'].dropna().mean():+.1f}%"   if df_pvr['desv_Glice_%'].notna().any()  else "—")
            kP3.metric("Desv. Fuel prom.",     f"{df_pvr['desv_Fuel_%'].dropna().mean():+.1f}%"    if df_pvr['desv_Fuel_%'].notna().any()   else "—")

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

        # ===== Vista visual de reacciones (tarjetas con estado) =====
        st.divider()
        st.markdown("### 🧪 Reacciones recientes (vista visual)")
        df_cards = cat("""
            SELECT
              b.id_batch, b.identificador_unidad AS ticket,
              b.fecha, b.tipo_proceso, b.etapa_actual,
              bu.nombre_ui AS reactor,
              pb.codigo_producto AS buscado, b.calidad_buscada,
              p.codigo_producto  AS obtenido, b.kg_obtenido, b.calidad_final,
              b.kg_inicial, b.estimado_are_kg,
              b.inicio_ts, b.fin_ts,
              u.nombre AS cargado_por
            FROM fact_batch_proceso b
            LEFT JOIN dim_producto p   ON p.id_producto  = b.id_producto_obtenido
            LEFT JOIN dim_producto pb  ON pb.id_producto = b.id_producto_buscado
            LEFT JOIN dim_bien_uso bu  ON bu.id_bien_uso = b.id_bien_uso
            LEFT JOIN dim_usuario u    ON u.id_usuario   = b.id_usuario_carga
            WHERE NOT b.anulado AND b.sector='REACTORES'
            ORDER BY b.creado_en DESC
            LIMIT 24
        """)
        if df_cards.empty:
            st.caption("No hay reacciones todavía.")
        else:
            # iconos por etapa
            etapa_emoji = {
                "ARMADO":"🧱", "REACCION":"🔥", "REPOSANDO":"⏸️",
                "DECANTACION":"💧", "EN_TANQUE":"🪣"
            }
            ncols = 3
            chunks = [df_cards.iloc[i:i+ncols] for i in range(0, len(df_cards), ncols)]
            for chunk in chunks:
                cols = st.columns(ncols)
                for j, (_, row) in enumerate(chunk.iterrows()):
                    with cols[j]:
                        em = etapa_emoji.get(row["etapa_actual"], "❔")
                        cerrado = (row["etapa_actual"] == "EN_TANQUE")
                        color_bg = "#0f172a" if not cerrado else "#064e3b"
                        st.markdown(
                            f"""
<div style="background:{color_bg};padding:12px;border-radius:10px;border:1px solid #1f2937">
  <div style="font-size:13px;color:#cbd5e1">#{int(row['id_batch'])} · <b>{row['ticket'] or '—'}</b></div>
  <div style="font-size:20px;margin:4px 0">{em} {row['etapa_actual'] or '—'}</div>
  <div style="font-size:13px;color:#e2e8f0">{row['tipo_proceso']} · {row['reactor'] or '—'}</div>
  <hr style="border-color:#1f2937;margin:8px 0">
  <div style="font-size:12px;color:#94a3b8">🎯 {row['buscado'] or '—'} · cal {row['calidad_buscada'] or '—'}</div>
  <div style="font-size:12px;color:#94a3b8">📦 {row['obtenido'] or '—'} · {int(row['kg_obtenido']) if pd.notna(row['kg_obtenido']) else '—'} kg · cal {row['calidad_final'] or '—'}</div>
  <div style="font-size:12px;color:#94a3b8">📅 {row['fecha']}</div>
</div>
""",
                            unsafe_allow_html=True
                        )


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
                if st.button("\U0001f6ab Desactivar usuario", key=f"deact_{u_id}", use_container_width=True):
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
                if st.form_submit_button("\U0001f511 Resetear PIN", use_container_width=True):
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

                # Multi-sector: traer los actuales y permitir seleccionar varios
                df_usr = cat(f"SELECT sectores FROM produccion.dim_usuario WHERE id_usuario={u_id}")
                actuales = list(df_usr.iloc[0]["sectores"]) if not df_usr.empty and df_usr.iloc[0]["sectores"] else []
                todos_secs = sectores["codigo"].tolist()
                sectores_mult = st.multiselect(
                    "Sectores asignados (vacío = todos)",
                    options=todos_secs, default=actuales,
                    format_func=lambda c: sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"],
                    key=f"nss_{u_id}"
                )
                st.caption("ℹ️ Si la lista queda vacía, el usuario tiene acceso a todos los sectores.")

                if st.form_submit_button("\U0001f4be Aplicar cambios", use_container_width=True):
                    try:
                        if nrol != u_row["rol"]: cambiar_rol(USR["id_usuario"], u_id, nrol)
                        if (nsec or None) != u_row["sector"]: cambiar_sector(USR["id_usuario"], u_id, nsec or None)
                        if sorted(sectores_mult) != sorted(actuales):
                            cambiar_sectores(USR["id_usuario"], u_id, sectores_mult)
                        st.success("Cambios aplicados."); cat.clear(); st.rerun()
                    except Exception as e: st.error(str(e))
