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

# ---------- LANDING (post-login): elegir sección ----------
if "section" not in st.session_state:
    st.session_state.section = None

def go_to(sec):
    st.session_state.section = sec
    st.rerun()

if st.session_state.section is None:
    st.title("WORMS · Elegí qué querés hacer")
    st.caption(f"Sesión: **{USR['nombre_full']}** (rol {USR['rol']})")
    cA, cB, cC = st.columns(3)
    with cA:
        st.markdown("### 🏭 Cargas")
        st.write("Carga de producción, anulaciones, observación y auditoría.")
        if st.button("Entrar a Cargas", type="primary", use_container_width=True, key="land_cargas"):
            go_to("CARGAS")
    with cB:
        st.markdown("### 🧪 Laboratorio")
        st.write("Vista de procesos_lab: filtros, estadísticas, descarga CSV.")
        if st.button("Entrar a Laboratorio", use_container_width=True, key="land_lab"):
            go_to("LAB")
    with cC:
        st.markdown("### 🚛 Portería")
        st.write("Vista de v_transacciones_limpias: filtros, peso por producto, descarga.")
        if st.button("Entrar a Portería", use_container_width=True, key="land_port"):
            go_to("PORT")
    if USR["rol"] == "ADMIN":
        st.divider()
        cAd, _, _ = st.columns(3)
        with cAd:
            st.markdown("### ⚙️ Admin")
            st.write("Gestión de usuarios: alta, roles, sectores, reset PIN, activar/desactivar.")
            if st.button("Entrar a Admin", use_container_width=True, key="land_admin"):
                go_to("ADMIN")
    st.stop()

with st.sidebar:
    st.markdown(f"### 👤 {USR['nombre_full']}")
    st.caption(f"`{USR['nombre']}` · rol **{USR['rol']}**")
    if st.button("← Cambiar de sección", use_container_width=True, key="sb_back"):
        st.session_state.section = None
        st.rerun()
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

# Corrientes evaluables (editable desde Supabase: dic_corriente_config)
try:
    _ce = cat("SELECT corriente FROM produccion.dic_corriente_config WHERE evaluable")
    CORR_EVAL = _ce["corriente"].tolist() if not _ce.empty else ["vegetal","animal","efluente_liquido","insumo"]
except Exception:
    CORR_EVAL = ["vegetal","animal","efluente_liquido","insumo"]
CORR_EVAL_SQL = "(" + ",".join("'" + c.replace("'", "''") + "'" for c in CORR_EVAL) + ")" if CORR_EVAL else "('')"


# ============================================================================
# Si NO es la sección CARGAS, mostramos LAB o PORT y cortamos acá
# ============================================================================
def _humanize_ago(ts):
    if ts is None or pd.isna(ts): return "—"
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc) if getattr(ts, "tzinfo", None) else _dt.now()
    s = int((now - ts).total_seconds())
    if s < 60:    return f"hace {s} s"
    if s < 3600:  return f"hace {s//60} min"
    if s < 86400: return f"hace {s//3600} h"
    return f"hace {s//86400} d"

def _header_sync():
    """Header con último registro subido a procesos_lab y transacciones."""
    try:
        df_lab = cat("SELECT id, empleado, _synced_at FROM produccion.procesos_lab ORDER BY id DESC LIMIT 1")
        df_port = cat("SELECT id, usuario, _synced_at FROM produccion.transacciones ORDER BY id DESC LIMIT 1")
        df_sync = cat("SELECT source_id, last_status, last_successful_sync, updated_at, left(coalesce(last_error,''),120) AS err FROM produccion.sync_control")
    except Exception as e:
        st.warning(f"No se pudo leer sync_control / tablas raw: {e}")
        return
    cA, cB = st.columns(2)
    def _card(col, titulo, df_last, user_col, source):
        with col:
            if df_last.empty:
                st.error(f"**{titulo}** · sin datos")
                return
            r = df_last.iloc[0]
            synced = r.get("_synced_at")
            uname  = r.get(user_col, "—") or "—"
            sync_row = df_sync[df_sync["source_id"]==source]
            status = sync_row.iloc[0]["last_status"] if not sync_row.empty else "—"
            last_try = sync_row.iloc[0]["updated_at"] if not sync_row.empty else None
            last_ok  = sync_row.iloc[0]["last_successful_sync"] if not sync_row.empty else None
            err = sync_row.iloc[0]["err"] if not sync_row.empty else ""
            es_viejo = False
            try:
                from datetime import datetime as _dt, timezone as _tz
                now = _dt.now(_tz.utc) if getattr(synced,"tzinfo",None) else _dt.now()
                es_viejo = (now - synced).total_seconds() > 300
            except Exception:
                pass
            if status != "OK" or es_viejo:
                st.error(f"**{titulo}**\n\n"
                         f"Último ID: **{r['id']}** · usuario **{uname}** · {_humanize_ago(synced)}\n\n"
                         f"Agente **{status}** · último intento {_humanize_ago(last_try)} · última carga OK {_humanize_ago(last_ok)}"
                         + (f"\n\nError: {err}" if err else ""))
            else:
                st.success(f"**{titulo}**\n\n"
                           f"Último ID: **{r['id']}** · usuario **{uname}** · {_humanize_ago(synced)}\n\n"
                           f"Agente **OK** · último intento {_humanize_ago(last_try)} · última carga OK {_humanize_ago(last_ok)}")
    _card(cA, "🧪 procesos_lab",     df_lab,  "empleado", "laboratorio_pc_1")
    _card(cB, "🚛 transacciones",    df_port, "usuario",  "porteria_pc_1")


if st.session_state.section != "CARGAS":
    _header_sync()
    st.divider()
    from datetime import timedelta as _td
    if st.session_state.section == "LAB":
        # =================== LABORATORIO ===================
        st.title("🧪 Laboratorio")
        with st.expander("Filtros", expanded=True):
            c1, c2, c3 = st.columns(3)
            fmin = c1.date_input("Fecha desde", value=(date.today()-_td(days=30)), key="lab_fmin")
            fmax = c2.date_input("Fecha hasta", value=date.today(), key="lab_fmax")
            limit_lab = c3.number_input("Límite filas", 100, 100000, 5000, step=500, key="lab_lim")
            try:
                prods_lab = cat("SELECT DISTINCT producto_lab FROM produccion.procesos_lab WHERE producto_lab IS NOT NULL ORDER BY 1")["producto_lab"].tolist()
            except Exception: prods_lab = []
            try:
                emps_lab = cat("SELECT DISTINCT empleado FROM produccion.procesos_lab WHERE empleado IS NOT NULL ORDER BY 1")["empleado"].tolist()
            except Exception: emps_lab = []
            c4, c5 = st.columns(2)
            sel_prod = c4.multiselect("Producto", prods_lab, key="lab_prods")
            sel_emp  = c5.multiselect("Empleado", emps_lab, key="lab_emps")

        where = ["fecha >= %s", "fecha < %s"]
        params = [fmin.isoformat(), (fmax + _td(days=1)).isoformat()]
        if sel_prod:
            where.append("producto_lab = ANY(%s)"); params.append(sel_prod)
        if sel_emp:
            where.append("empleado = ANY(%s)"); params.append(sel_emp)
        sql_lab = f"""
            SELECT id, fecha, ticket, producto_lab, calidad_final_lab, color,
                   prc_acidez, prc_agua, prc_producto, ppm_azufre, ppm_fosforo,
                   densidad__g_ml, temp_celcius, empleado, rechazado,
                   patente_chasis, _synced_at
            FROM produccion.procesos_lab
            WHERE {' AND '.join(where)}
            ORDER BY fecha DESC NULLS LAST
            LIMIT {int(limit_lab)}
        """
        try:
            df_l = cat(sql_lab, tuple(params))
        except Exception as e:
            st.exception(e); df_l = pd.DataFrame()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Filas", len(df_l))
        k2.metric("Productos distintos", df_l["producto_lab"].nunique() if not df_l.empty else 0)
        k3.metric("Aceptados", int((df_l["rechazado"]=="ACEPTADO").sum()) if not df_l.empty else 0)
        k4.metric("Rechazados", int((df_l["rechazado"]=="RECHAZADO").sum()) if not df_l.empty else 0)

        if not df_l.empty:
            st.markdown("**Procesos por día**")
            by_day = df_l.assign(dia=pd.to_datetime(df_l["fecha"]).dt.date).groupby("dia").size().reset_index(name="cantidad")
            st.line_chart(by_day, x="dia", y="cantidad", use_container_width=True)
            st.markdown("**Distribución por producto**")
            by_prod = df_l["producto_lab"].value_counts().reset_index()
            by_prod.columns = ["producto_lab","cantidad"]
            st.bar_chart(by_prod, x="producto_lab", y="cantidad", use_container_width=True)
            st.dataframe(df_l, use_container_width=True, hide_index=True, height=380)
            st.download_button("⬇️ Descargar CSV", df_l.to_csv(index=False).encode("utf-8"),
                               file_name=f"procesos_lab_{fmin}_{fmax}.csv", mime="text/csv")
        else:
            st.info("Sin datos en el rango.")
    elif st.session_state.section == "PORT":
        # =================== PORTERIA ===================
        st.title("\U0001f69b Porteria")
        sub_dia, sub_hist, sub_eflu, sub_labcmp = st.tabs([
            "\U0001f4c5 Entrada diaria", "\U0001f4ca Revision historica",
            "\U0001f4a7 Efluentes liquidos", "\U0001f9ea Lab por cliente"])

        # ---------------- ENTRADA DIARIA ----------------
        with sub_dia:
            cD1, cD2 = st.columns([1,3])
            dia_sel = cD1.date_input("Dia", value=date.today(), key="pd_dia")
            cD2.caption("Camiones que entraron en el dia, ordenados por hora (lo mas reciente arriba). "
                        "Toca 'Refrescar datos' en la barra lateral para ver llegadas nuevas.")
            sqld = """
                SELECT transaccion, hora_e, patente_chasis, conductor,
                       producto, producto_base, corriente,
                       cliente, transporte, procedencia,
                       (peso_neto * -1) AS peso_neto, evaluado, lab_calidad, _synced_at
                FROM produccion.v_transacciones_limpias
                WHERE fecha_entrada = %s
                ORDER BY hora_e DESC NULLS LAST, transaccion DESC
            """
            try:
                df_d = cat(sqld, (dia_sel.isoformat(),))
            except Exception as e:
                st.exception(e); df_d = pd.DataFrame()

            kd1, kd2, kd3, kd4 = st.columns(4)
            kd1.metric("Camiones hoy", len(df_d))
            if not df_d.empty:
                kg_tot = pd.to_numeric(df_d["peso_neto"], errors="coerce").sum()
                kd2.metric("Kg netos del dia", f"{int(kg_tot):,}".replace(",", "."))
                df_d["eval_estado"] = df_d.apply(
                    lambda r: ("no corresponde" if r["corriente"] not in CORR_EVAL else r["evaluado"]), axis=1)
                df_evbl = df_d[df_d["corriente"].isin(CORR_EVAL)]
                base_evbl = len(df_evbl)
                n_eval = int((df_evbl["eval_estado"]=="SI").sum())
                kd3.metric("Evaluados (evaluables)", f"{n_eval}/{base_evbl}")
                kd4.metric("% evaluado", f"{(n_eval/base_evbl*100):.0f}%" if base_evbl else "—")

                # Linea por hora (cantidad por franja horaria)
                st.markdown("**Llegadas por hora**")
                hr = df_d.copy()
                hr["hh"] = hr["hora_e"].astype(str).str.slice(0,2)
                by_hr = hr.groupby("hh").size().reset_index(name="camiones").sort_values("hh")
                st.bar_chart(by_hr, x="hh", y="camiones", use_container_width=True)

                # Tabla "permeable": cada camion con su estado evaluado
                st.markdown("**Detalle de llegadas**")
                df_show = df_d.copy()
                df_show["evaluado"] = df_show["eval_estado"].map({"SI":"\u2705 SI","NO":"\u26a0\ufe0f NO","no corresponde":"\u2014 no corresponde"}).fillna(df_show["eval_estado"])
                st.dataframe(
                    df_show[["transaccion","hora_e","patente_chasis","conductor","producto_base","corriente",
                             "peso_neto","evaluado","lab_calidad","cliente","transporte","procedencia"]],
                    use_container_width=True, hide_index=True, height=460
                )
                st.download_button("\u2b07\ufe0f Descargar CSV del dia",
                                   df_d.to_csv(index=False).encode("utf-8"),
                                   file_name=f"porteria_{dia_sel}.csv", mime="text/csv")

                # ----- Comprobante de pesaje por transaccion -----
                st.divider()
                st.markdown("**\U0001f9fe Comprobante de pesaje**")
                tickets = df_d["transaccion"].dropna().astype(int).tolist()
                if tickets:
                    tk = st.selectbox("Ver comprobante de transaccion N\u00b0", tickets, key="cp_tk")
                    rowc = cat("SELECT * FROM produccion.transacciones WHERE transaccion=%s ORDER BY id DESC LIMIT 1", (tk,))
                    if not rowc.empty:
                        rr = rowc.iloc[0]
                        def g(c):
                            v = rr.get(c)
                            return "" if (v is None or (isinstance(v,float) and pd.isna(v))) else str(v)
                        def gnum(c):
                            v = rr.get(c)
                            if v is None or (isinstance(v,float) and pd.isna(v)): return ""
                            try:
                                f = float(v)
                                return str(int(f)) if f == int(f) else f"{f:g}"
                            except Exception:
                                return str(v)
                        peso_e = gnum("pesoentr"); peso_s = gnum("pesosal"); peso_n = gnum("pesoneto")
                        pendiente = str(rr.get("pendiente") or "").lower() == "si"
                        comp_html = f"""
<div id="comprob" style="font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff;padding:24px;max-width:760px;border:1px solid #ccc">
  <div style="font-style:italic;font-weight:bold;font-size:18px;margin-bottom:20px">EMPRESA {g('empresa')}</div>
  <div style="text-align:center;font-style:italic;font-weight:bold;font-size:16px;margin-bottom:18px">COMPROBANTE DE PESAJE</div>
  <table style="font-size:13px;width:100%;border-collapse:collapse">
    <tr>
      <td style="padding:2px 8px"><b>Entrada:</b></td><td>{g('fecha_e')} {g('hora_e')}</td>
      <td style="padding:2px 8px"><b>Operador:</b></td><td>{g('usuario')}</td>
      <td style="padding:2px 8px"><b>TICKET NRO:</b></td><td style="font-size:16px"><b>{gnum('transaccion')}</b></td>
    </tr>
    <tr>
      <td style="padding:2px 8px"><b>Salida:</b></td><td>{g('fecha_s')} {g('hora_s')}</td>
      <td style="padding:2px 8px"><b>Balanza:</b></td><td>{g('vacio24')}</td>
      <td></td><td></td>
    </tr>
    <tr><td style="padding:2px 8px"><b>Producto:</b></td><td><b>{g('producto')}</b></td>
        <td style="padding:2px 8px"><b>Conductor:</b></td><td>{g('conductor')}</td><td></td><td></td></tr>
    <tr><td style="padding:2px 8px"><b>Cliente:</b></td><td><b>{g('procedencia')}</b></td>
        <td style="padding:2px 8px"><b>Documento:</b></td><td>{g('nrodoc')}</td><td></td><td></td></tr>
    <tr><td style="padding:2px 8px"><b>Transporte:</b></td><td><b>{g('destino')}</b></td>
        <td style="padding:2px 8px"><b>Patente Chasis:</b></td><td>{g('patcha')}</td><td></td><td></td></tr>
    <tr><td style="padding:2px 8px"><b>Procedencia:</b></td><td><b>{g('chofer')}</b></td>
        <td style="padding:2px 8px"><b>Patente Acoplado:</b></td><td>{g('patacopl')}</td><td></td><td></td></tr>
  </table>
  <table style="font-size:13px;width:100%;margin-top:14px;border-collapse:collapse">
    <tr><td style="padding:2px 8px"><b>Tipo y Nro. de Comprobante:</b></td><td>{g('tipodoc')} {g('comprnum1')}</td></tr>
    <tr><td style="padding:2px 8px"><b>Procedencia/Destino:</b></td><td>{g('procdest')}</td></tr>
    <tr><td style="padding:2px 8px"><b>Contenedor N\u00b0:</b></td><td>{g('proc_contenedor')}</td></tr>
    <tr><td style="padding:2px 8px"><b>Observaciones:</b></td><td>{g('observaciones')}</td></tr>
  </table>
  <table style="font-size:18px;width:100%;margin-top:18px;border-collapse:collapse">
    <tr><td style="padding:4px 8px;text-align:right;width:60%"><b>PESO ENTRADA:</b></td><td><b>{peso_e}</b> Kg</td></tr>
    <tr><td style="padding:4px 8px;text-align:right"><b>PESO SALIDA:</b></td><td><b>{peso_s or ('PENDIENTE' if pendiente else '')}</b> {'' if (not peso_s and pendiente) else 'Kg'}</td></tr>
    <tr><td style="padding:4px 8px;text-align:right"><b>PESO NETO:</b></td><td><b>{peso_n or ('PENDIENTE' if pendiente else '')}</b> {'' if (not peso_n and pendiente) else 'Kg'}</td></tr>
  </table>
  {f'<div style="margin-top:10px;color:#b45309;font-size:13px"><b>⚠ Camion pendiente de salida</b> — peso de salida y neto se completan cuando se pesa al salir.</div>' if pendiente else ''}
</div>
"""
                        st.markdown(comp_html, unsafe_allow_html=True)
                        st.download_button(
                            "\u2b07\ufe0f Descargar comprobante (HTML para imprimir)",
                            ("<html><head><meta charset='utf-8'><title>Comprobante "
                             + g('transaccion') + "</title></head><body>" + comp_html + "</body></html>").encode("utf-8"),
                            file_name=f"comprobante_{tk}.html", mime="text/html", key="cp_dl")
                        st.caption("Abrilo y us\u00e1 Ctrl+P para imprimir o guardar como PDF.")
            else:
                st.info("Todavia no entro ningun camion en la fecha elegida.")

        # ---------------- REVISION HISTORICA ----------------
        with sub_hist:
            with st.expander("Filtros", expanded=True):
                c1, c2, c3 = st.columns(3)
                fmin = c1.date_input("Desde", value=(date.today()-_td(days=30)), key="ph_fmin")
                fmax = c2.date_input("Hasta", value=date.today(), key="ph_fmax")
                limit_p = c3.number_input("Limite filas", 100, 200000, 20000, step=1000, key="ph_lim")
                try:
                    prods_base = cat("SELECT DISTINCT producto_base FROM produccion.v_transacciones_limpias WHERE producto_base IS NOT NULL ORDER BY 1 LIMIT 500")["producto_base"].tolist()
                except Exception: prods_base = []
                try:
                    corrientes_p = cat("SELECT DISTINCT corriente FROM produccion.v_transacciones_limpias WHERE corriente IS NOT NULL ORDER BY 1")["corriente"].tolist()
                except Exception: corrientes_p = []
                try:
                    cli_p = cat("SELECT DISTINCT cliente FROM produccion.v_transacciones_limpias WHERE cliente IS NOT NULL ORDER BY 1 LIMIT 500")["cliente"].tolist()
                except Exception: proc_p = []
                c4, c5, c6 = st.columns(3)
                sel_pb = c4.multiselect("Producto base", prods_base, key="ph_pb")
                sel_co = c5.multiselect("Corriente", corrientes_p, key="ph_co")
                sel_pr = c6.multiselect("Cliente", cli_p, key="ph_pr")
                c7, c8 = st.columns(2)
                eval_filt = c7.radio("Evaluado", ["Todos","SI","NO"], horizontal=True, key="ph_eval")
                pat = c8.text_input("Patente chasis contiene", key="ph_pat")

            where = ["fecha_entrada IS NOT NULL", "fecha_entrada >= %s", "fecha_entrada <= %s"]
            params = [fmin.isoformat(), fmax.isoformat()]
            if sel_pb: where.append("producto_base = ANY(%s)"); params.append(sel_pb)
            if sel_co: where.append("corriente = ANY(%s)"); params.append(sel_co)
            if sel_pr: where.append("cliente = ANY(%s)"); params.append(sel_pr)
            if eval_filt != "Todos": where.append("evaluado = %s"); params.append(eval_filt)
            if pat.strip(): where.append("patente_chasis ILIKE %s"); params.append(f"%{pat.strip()}%")
            wsql = " AND ".join(where)

            sql_p = f"""
                SELECT id, transaccion, fecha_entrada, hora_e,
                       operador, conductor, patente_chasis,
                       producto, producto_base, corriente, evaluado,
                       cliente, transporte, procedencia,
                       (peso_neto * -1) AS peso_neto,
                       lab_calidad, lab_color, lab_prc_acidez, lab_prc_agua,
                       lab_ppm_azufre, lab_ppm_fosforo, lab_densidad,
                       lab_empleado, lab_rechazado, lab_num_muestra, lab_fecha,
                       observaciones, _synced_at
                FROM produccion.v_transacciones_limpias
                WHERE {wsql}
                ORDER BY fecha_entrada DESC NULLS LAST, id DESC
                LIMIT {int(limit_p)}
            """
            try:
                df_p = cat(sql_p, tuple(params))
            except Exception as e:
                st.exception(e); df_p = pd.DataFrame()

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Transacciones", len(df_p))
            k2.metric("Patentes distintas", df_p["patente_chasis"].nunique() if not df_p.empty else 0)
            if not df_p.empty:
                tot = pd.to_numeric(df_p["peso_neto"], errors="coerce").sum()
                n_ev = int((df_p["evaluado"]=="SI").sum())
                k3.metric("Kg netos total", f"{int(tot):,}".replace(",", "."))
                k4.metric("% evaluado", f"{(n_ev/len(df_p)*100):.0f}%")

                st.markdown("**Transacciones por dia**")
                by_day = df_p.dropna(subset=["fecha_entrada"]).groupby("fecha_entrada").size().reset_index(name="cantidad")
                st.line_chart(by_day, x="fecha_entrada", y="cantidad", use_container_width=True)

                st.markdown("**Kg netos por corriente**")
                corr_sum = (df_p.dropna(subset=["corriente"])
                                .assign(peso=pd.to_numeric(df_p["peso_neto"], errors="coerce"))
                                .groupby("corriente")["peso"].sum()
                                .sort_values(ascending=False).reset_index())
                st.bar_chart(corr_sum, x="corriente", y="peso", use_container_width=True)

                # ----- Evaluado vs no evaluado -----
                st.markdown("### Cobertura de evaluacion (lab)")
                st.caption("Cuanto de lo EVALUABLE esta pasando por laboratorio. "
                           "Solo corrientes vegetal / animal / efluente_liquido / insumo "
                           "(el resto -solido, sin_declarar- no se evalua).")

                df_eval = df_p[df_p["corriente"].isin(CORR_EVAL)].copy()
                if df_eval.empty:
                    st.info("No hay llegadas de corrientes evaluables en el rango.")
                else:
                    n_ev2 = int((df_eval["evaluado"]=="SI").sum())
                    st.metric("% evaluado (solo corrientes evaluables)",
                              f"{(n_ev2/len(df_eval)*100):.0f}%",
                              help=f"{n_ev2} de {len(df_eval)} llegadas evaluables")

                    ev_corr = (df_eval.groupby(["corriente","evaluado"]).size()
                                   .reset_index(name="cant")
                                   .pivot(index="corriente", columns="evaluado", values="cant")
                                   .fillna(0))
                    for col in ("SI","NO"):
                        if col not in ev_corr.columns: ev_corr[col] = 0
                    ev_corr["total"] = ev_corr["SI"] + ev_corr["NO"]
                    ev_corr["% evaluado"] = (ev_corr["SI"]/ev_corr["total"]*100).round(1)
                    st.markdown("**Por corriente (vegetal / animal / efluente_liquido / insumo)**")
                    st.bar_chart(ev_corr[["SI","NO"]], use_container_width=True)
                    st.dataframe(ev_corr.reset_index()[["corriente","SI","NO","total","% evaluado"]],
                                 use_container_width=True, hide_index=True)

                    ev_prod = (df_eval.groupby(["producto_base","evaluado"]).size()
                                   .reset_index(name="cant")
                                   .pivot(index="producto_base", columns="evaluado", values="cant")
                                   .fillna(0))
                    for col in ("SI","NO"):
                        if col not in ev_prod.columns: ev_prod[col] = 0
                    ev_prod["total"] = ev_prod["SI"] + ev_prod["NO"]
                    ev_prod["% evaluado"] = (ev_prod["SI"]/ev_prod["total"]*100).round(1)
                    ev_prod = ev_prod.sort_values("total", ascending=False).head(20)
                    st.markdown("**Por producto base (top 20 por volumen de llegadas evaluables)**")
                    st.bar_chart(ev_prod[["SI","NO"]], use_container_width=True)
                    st.dataframe(ev_prod.reset_index()[["producto_base","SI","NO","total","% evaluado"]],
                                 use_container_width=True, hide_index=True)

                st.markdown("### Detalle")
                df_pd = df_p.copy()
                df_pd["eval_estado"] = df_pd.apply(
                    lambda r: ("no corresponde" if r["corriente"] not in CORR_EVAL else r["evaluado"]), axis=1)
                _front = ["transaccion","fecha_entrada","eval_estado","producto_base","corriente","peso_neto","cliente"]
                _rest = [c for c in df_pd.columns if c not in _front]
                st.dataframe(df_pd[_front + _rest], use_container_width=True, hide_index=True, height=420)
                st.download_button("\u2b07\ufe0f Descargar CSV", df_p.to_csv(index=False).encode("utf-8"),
                                   file_name=f"porteria_hist_{fmin}_{fmax}.csv", mime="text/csv")
            else:
                st.info("Sin datos en el rango.")


        # ---------------- EFLUENTES LIQUIDOS ----------------
        with sub_eflu:
            st.caption("Solo producto_base = EFLUENTES LIQUIDOS. Acumulados, tendencia y comparacion mensual.")
            cE1, cE2 = st.columns(2)
            ef_desde = cE1.date_input("Desde", value=date(date.today().year,1,1), key="ef_desde")
            ef_hasta = cE2.date_input("Hasta", value=date.today(), key="ef_hasta")
            sql_ef = """
                SELECT fecha_entrada, hora_e, patente_chasis, cliente, transporte, procedencia,
                       (peso_neto * -1) AS peso_neto, evaluado
                FROM produccion.v_transacciones_limpias
                WHERE producto_base = 'EFLUENTES LIQUIDOS'
                  AND fecha_entrada IS NOT NULL
                  AND fecha_entrada >= %s AND fecha_entrada <= %s
                ORDER BY fecha_entrada
            """
            try:
                df_ef = cat(sql_ef, (ef_desde.isoformat(), ef_hasta.isoformat()))
            except Exception as e:
                st.exception(e); df_ef = pd.DataFrame()

            if df_ef.empty:
                st.info("No hay registros de EFLUENTES LIQUIDOS en el rango.")
            else:
                df_ef["peso_neto"] = pd.to_numeric(df_ef["peso_neto"], errors="coerce")
                df_ef["fecha_entrada"] = pd.to_datetime(df_ef["fecha_entrada"])
                total_kg = df_ef["peso_neto"].sum()
                n_via = len(df_ef)
                prom = df_ef["peso_neto"].mean()
                ke1, ke2, ke3 = st.columns(3)
                ke1.metric("Kg netos acumulados", f"{int(total_kg):,}".replace(",", "."))
                ke2.metric("Viajes", n_via)
                ke3.metric("Promedio por viaje", f"{int(prom or 0):,}".replace(",", "."))

                # Total por mes (barras)
                dm = df_ef.copy()
                dm["mes"] = dm["fecha_entrada"].dt.to_period("M").astype(str)
                tot_mes = dm.groupby("mes")["peso_neto"].sum().reset_index()
                tot_mes.columns = ["mes", "kg_netos"]
                st.markdown("**Total de kg netos por mes**")
                st.bar_chart(tot_mes, x="mes", y="kg_netos", use_container_width=True)

                # Comparacion mensual: acumulado por dia-del-mes, una linea por mes
                st.markdown("**Comparacion entre meses (acumulado dia 1 -> fin de mes)**")
                import calendar as _cal
                import altair as alt
                d = df_ef.copy()
                d["mes"] = d["fecha_entrada"].dt.to_period("M").astype(str)
                d["dia"] = d["fecha_entrada"].dt.day
                meses_disp = sorted(d["mes"].unique())
                hoy = date.today()
                mes_actual = pd.Period(hoy, freq="M").strftime("%Y-%m")
                default_meses = meses_disp[-4:] if len(meses_disp) > 4 else meses_disp
                meses_sel = st.multiselect("Meses a comparar (año-mes)", meses_disp,
                                           default=default_meses, key="ef_meses")
                if not meses_sel:
                    st.info("Elegí al menos un mes.")
                else:
                    d2 = d[d["mes"].isin(meses_sel)]
                    diario = d2.groupby(["mes","dia"])["peso_neto"].sum().reset_index()
                    diario["acum"] = diario.groupby("mes")["peso_neto"].cumsum()
                    diario["tipo"] = "real"

                    # Proyeccion del mes actual (si está seleccionado): linea punteada
                    proy_rows = []
                    if mes_actual in meses_sel:
                        dm = diario[diario["mes"]==mes_actual].sort_values("dia")
                        if not dm.empty:
                            acum_hoy = float(dm["acum"].iloc[-1])
                            dia_hoy  = int(dm["dia"].iloc[-1])
                            dias_mes = _cal.monthrange(hoy.year, hoy.month)[1]
                            ritmo = acum_hoy / dia_hoy if dia_hoy else 0
                            # punto de arranque de la proyeccion = ultimo real
                            proy_rows.append({"mes": f"{mes_actual} (proy)", "dia": dia_hoy, "acum": acum_hoy, "tipo": "proyeccion"})
                            for dd in range(dia_hoy+1, dias_mes+1):
                                proy_rows.append({"mes": f"{mes_actual} (proy)", "dia": dd,
                                                  "acum": ritmo*dd, "tipo": "proyeccion"})

                    plot_df = pd.concat([diario, pd.DataFrame(proy_rows)], ignore_index=True) if proy_rows else diario

                    chart = alt.Chart(plot_df).mark_line(point=False).encode(
                        x=alt.X("dia:Q", title="día del mes"),
                        y=alt.Y("acum:Q", title="kg netos acumulados"),
                        color=alt.Color("mes:N", title="mes"),
                        strokeDash=alt.StrokeDash("tipo:N", title="",
                                   scale=alt.Scale(domain=["real","proyeccion"], range=[[1,0],[6,4]])),
                    ).properties(height=380)
                    st.altair_chart(chart, use_container_width=True)
                    st.caption("Línea sólida = real. Línea punteada = proyección del mes corriente según el ritmo diario actual.")

                    if mes_actual in meses_sel and proy_rows:
                        proy_total = proy_rows[-1]["acum"]
                        cp1, cp2 = st.columns(2)
                        cp1.metric(f"Acumulado {mes_actual} a hoy", f"{int(acum_hoy):,}".replace(",", "."))
                        cp2.metric("Proyección fin de mes", f"{int(proy_total):,}".replace(",", "."),
                                   help="Ritmo diario actual × días del mes")

                # Estadisticas por procedencia
                st.markdown("**Por cliente**")
                by_proc = (df_ef.dropna(subset=["cliente"])
                                .groupby("cliente")
                                .agg(viajes=("peso_neto","size"),
                                     kg_total=("peso_neto","sum"),
                                     kg_promedio=("peso_neto","mean"))
                                .sort_values("kg_total", ascending=False).reset_index())
                by_proc["kg_total"] = by_proc["kg_total"].round(0)
                by_proc["kg_promedio"] = by_proc["kg_promedio"].round(0)
                st.bar_chart(by_proc.head(15), x="cliente", y="kg_total", use_container_width=True)
                st.dataframe(by_proc, use_container_width=True, hide_index=True)

                st.download_button("\u2b07\ufe0f Descargar CSV efluentes",
                                   df_ef.to_csv(index=False).encode("utf-8"),
                                   file_name=f"efluentes_{ef_desde}_{ef_hasta}.csv", mime="text/csv")

        # ---------------- LAB POR CLIENTE (procedencia) ----------------
        with sub_labcmp:
            st.caption("Compara parametros de laboratorio entre clientes (procedencia), "
                       "**dentro de cada producto_base** (comparar acidez de AFE-S vs ARE no tiene sentido). Ignora nulos.")
            PARAMS = {
                "lab_prc_acidez":  "% Acidez",
                "lab_prc_agua":    "% Agua",
                "lab_ppm_azufre":  "ppm Azufre",
                "lab_ppm_fosforo": "ppm Fosforo",
                "lab_densidad":    "Densidad",
            }
            cL1, cL2, cL3 = st.columns(3)
            lab_desde = cL1.date_input("Desde", value=(date.today()-_td(days=90)), key="lc_desde")
            lab_hasta = cL2.date_input("Hasta", value=date.today(), key="lc_hasta")
            param_sel = cL3.selectbox("Parametro", list(PARAMS.keys()),
                                      format_func=lambda c: PARAMS[c], key="lc_param")
            # productos disponibles para ese parametro
            try:
                pbs = cat(f"""
                    SELECT DISTINCT producto_base FROM produccion.v_transacciones_limpias
                    WHERE evaluado='SI' AND {param_sel} IS NOT NULL AND producto_base IS NOT NULL
                      AND corriente IN {CORR_EVAL_SQL}
                    ORDER BY 1
                """)["producto_base"].tolist()
            except Exception: pbs = []
            try:
                cals = cat("""
                    SELECT DISTINCT lab_calidad FROM produccion.v_transacciones_limpias
                    WHERE lab_calidad IS NOT NULL ORDER BY 1
                """)["lab_calidad"].tolist()
            except Exception: cals = []
            cF1, cF2, cF3 = st.columns(3)
            sel_pbs = cF1.multiselect("Producto base (vacio = todos)", pbs, key="lc_pbs")
            sel_cal = cF2.multiselect("Calidad final (vacio = todas)", cals, key="lc_cal")
            min_n = cF3.number_input("Minimo de mediciones por grupo", 1, 100, 1, key="lc_minn")

            where = ["evaluado = 'SI'", f"{param_sel} IS NOT NULL", "procedencia IS NOT NULL",
                     "producto_base IS NOT NULL",
                     f"corriente IN {CORR_EVAL_SQL}",
                     "fecha_entrada IS NOT NULL", "fecha_entrada >= %s", "fecha_entrada <= %s"]
            params = [lab_desde.isoformat(), lab_hasta.isoformat()]
            if sel_pbs:
                where.append("producto_base = ANY(%s)"); params.append(sel_pbs)
            if sel_cal:
                where.append("lab_calidad = ANY(%s)"); params.append(sel_cal)
            sql_lc = f"""
                SELECT producto_base, cliente, corriente, lab_calidad, {param_sel} AS valor
                FROM produccion.v_transacciones_limpias
                WHERE {' AND '.join(where)}
            """
            try:
                df_lc = cat(sql_lc, tuple(params))
            except Exception as e:
                st.exception(e); df_lc = pd.DataFrame()

            if df_lc.empty:
                st.info("Sin mediciones no-nulas de ese parametro en el rango.")
            else:
                df_lc["valor"] = pd.to_numeric(df_lc["valor"], errors="coerce")
                df_lc = df_lc.dropna(subset=["valor"])
                # Agrupado por producto_base + procedencia
                resumen = (df_lc.groupby(["producto_base","cliente"])["valor"]
                               .agg(n="size", promedio="mean", minimo="min", maximo="max", desvio="std")
                               .reset_index())
                resumen = resumen[resumen["n"] >= int(min_n)]
                for c in ("promedio","minimo","maximo","desvio"):
                    resumen[c] = resumen[c].round(2)
                resumen = resumen.sort_values(["producto_base","promedio"], ascending=[True, False])

                st.markdown(f"### {PARAMS[param_sel]} por producto base y cliente")

                # Si eligio 1 solo producto: chart limpio por procedencia
                if len(sel_pbs) == 1:
                    sub = resumen[resumen["producto_base"]==sel_pbs[0]]
                    st.markdown(f"**{sel_pbs[0]} \u2014 promedio por cliente**")
                    st.bar_chart(sub, x="procedencia", y="promedio", use_container_width=True)
                else:
                    # vista por producto: tabla pivote (filas producto_base, columnas procedencia)
                    piv = resumen.pivot_table(index="producto_base", columns="cliente",
                                              values="promedio", aggfunc="mean")
                    st.markdown("**Promedio por producto_base (filas) x cliente (columnas)**")
                    st.dataframe(piv, use_container_width=True)

                st.markdown("**Detalle (producto_base + cliente)**")
                st.dataframe(resumen, use_container_width=True, hide_index=True, height=420)
                st.caption("n = mediciones validas \u00b7 desvio = desviacion estandar (consistencia del cliente).")
                st.download_button("\u2b07\ufe0f Descargar CSV",
                                   resumen.to_csv(index=False).encode("utf-8"),
                                   file_name=f"lab_por_cliente_{param_sel}.csv", mime="text/csv")

    elif st.session_state.section == "ADMIN":
        # =================== ADMIN ===================
        st.title("\u2699\ufe0f Gestion de usuarios")
        if USR["rol"] != "ADMIN":
            st.error("Solo ADMIN puede entrar a esta seccion.")
        else:
            with st.expander("\u2795 Crear nuevo usuario", expanded=False):
                with st.form("form_user_new"):
                    c1, c2 = st.columns(2)
                    n_nombre = c1.text_input("Usuario (login) *", max_chars=30, placeholder="ej. sosa")
                    n_full = c2.text_input("Nombre completo *", max_chars=80, placeholder="ej. Jose Sosa")
                    c3, c4 = st.columns(2)
                    n_pin = c3.text_input("PIN (4-6 digitos) *", type="password", max_chars=6)
                    n_rol = c4.selectbox("Rol *", ["OPERADOR", "SUPERVISOR", "ADMIN"])
                    n_sector = st.selectbox(
                        "Sector default", [""] + sectores["codigo"].tolist(),
                        format_func=lambda c: "(ninguno)" if c=="" else sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"]
                    )
                    n_sectores = st.multiselect(
                        "Sectores asignados (vacio = todos)",
                        options=sectores["codigo"].tolist(),
                        format_func=lambda c: sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"]
                    )
                    crear = st.form_submit_button("Crear usuario", type="primary")
                if crear:
                    if not n_nombre or not n_full or not n_pin:
                        st.error("Completa los campos obligatorios.")
                    elif not n_pin.isdigit() or not (4 <= len(n_pin) <= 6):
                        st.error("El PIN debe ser numerico de 4 a 6 digitos.")
                    else:
                        try:
                            nid = crear_usuario(USR["id_usuario"], n_nombre.lower().strip(),
                                                 n_full, n_pin, n_rol, n_sector or None)
                            if n_sectores:
                                cambiar_sectores(USR["id_usuario"], nid, n_sectores)
                            st.success(f"Usuario '{n_nombre}' creado (id #{nid}).")
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
                    if st.button("\u2705 Reactivar usuario", key=f"act_{u_id}", use_container_width=True):
                        try: set_activo(USR["id_usuario"], u_id, True); st.success("Reactivado."); cat.clear(); st.rerun()
                        except Exception as e: st.error(str(e))
            with ac2:
                st.markdown("**Reset PIN**")
                with st.form(f"form_resetpin_{u_id}"):
                    npin = st.text_input("PIN nuevo (4-6 digitos)", type="password", max_chars=6, key=f"npin_{u_id}")
                    if st.form_submit_button("\U0001f511 Resetear PIN", use_container_width=True):
                        if not npin.isdigit() or not (4 <= len(npin) <= 6):
                            st.error("PIN invalido.")
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
                    df_usr = cat(f"SELECT sectores FROM produccion.dim_usuario WHERE id_usuario={u_id}")
                    actuales = list(df_usr.iloc[0]["sectores"]) if not df_usr.empty and df_usr.iloc[0]["sectores"] else []
                    sectores_mult = st.multiselect(
                        "Sectores asignados (vacio = todos)",
                        options=sectores["codigo"].tolist(), default=actuales,
                        format_func=lambda c: sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"],
                        key=f"nss_{u_id}"
                    )
                    if st.form_submit_button("\U0001f4be Aplicar cambios", use_container_width=True):
                        try:
                            if nrol != u_row["rol"]: cambiar_rol(USR["id_usuario"], u_id, nrol)
                            if (nsec or None) != u_row["sector"]: cambiar_sector(USR["id_usuario"], u_id, nsec or None)
                            if sorted(sectores_mult) != sorted(actuales):
                                cambiar_sectores(USR["id_usuario"], u_id, sectores_mult)
                            st.success("Cambios aplicados."); cat.clear(); st.rerun()
                        except Exception as e: st.error(str(e))

    st.stop()

# A partir de acá: SECCIÓN CARGAS (todo el flujo histórico)
_header_sync()
st.divider()

tabs = ["🏭 Producción", "📊 Observación", "✏️ Mis cargas", "🕒 Audit"]
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
        catalizador_tipo = None
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
                catalizador_tipo = st.radio(
                    "Catalizador a usar",
                    options=["NAOH","POTASIO"],
                    format_func=lambda x: "🧪 Soda cáustica (NaOH)" if x=="NAOH" else "🧪 Potasio (KOH)",
                    horizontal=True, key="b_catalizador"
                )

                # variables disponibles para comparación posterior
                est_glicerol_puro_kg = None
                if q_ag_kg_ref > 0 and acidez_oleico_v > 0 and glicerol_v > 0:
                    # Glicerol PURO necesario (química pura, sin descontar pureza)
                    est_glicerol_puro_kg = float(q_ag_kg_ref) * (acidez_oleico_v/100) * (PMg/(PMa*2)) * FE
                    # Glicerina total a cargar (con la pureza informada): glicerol_puro / (glicerol/100)
                    est_glice_kg = est_glicerol_puro_kg / (glicerol_v/100)
                    mas_por_impureza = est_glice_kg - est_glicerol_puro_kg

                    tn = float(q_ag_kg_ref) / 1000.0
                    rate_naoh    = float(fila_bien["consumo_naoh_kg_x_tn"]    or 0)
                    rate_potasio = float(fila_bien["consumo_potasio_kg_x_tn"] or 0)
                    rate_fuel    = float(fila_bien["consumo_fuel_kg_x_tn"]    or 0)
                    # Solo aplica el catalizador elegido
                    est_naoh_kg    = (tn * rate_naoh)    if catalizador_tipo == "NAOH"    else 0.0
                    est_potasio_kg = (tn * rate_potasio) if catalizador_tipo == "POTASIO" else 0.0
                    est_fuel_kg    = tn * rate_fuel
                    est_are_kg     = float(q_ag_kg_ref)  # 1:1 aprox

                    st.markdown("**🧮 Insumos estimados a cargar**")
                    cE1, cE2, cE3, cE4 = st.columns(4)
                    cE1.metric(
                        "Glicerina a cargar",
                        f"{est_glice_kg:,.0f} kg",
                        f"+{mas_por_impureza:,.0f} kg por pureza {glicerol_v:.0f}%"
                    )
                    if catalizador_tipo == "NAOH":
                        cE2.metric("NaOH (catalizador)", f"{est_naoh_kg:,.1f} kg",
                                   f"alternativa: {tn*rate_potasio:.2f} kg potasio")
                        cE3.metric("Potasio", "—", "no aplica")
                    else:
                        cE2.metric("NaOH", "—", "no aplica")
                        cE3.metric("Potasio (catalizador)", f"{est_potasio_kg:,.2f} kg",
                                   f"alternativa: {tn*rate_naoh:.1f} kg NaOH")
                    cE4.metric("Fuel", f"{est_fuel_kg:,.0f} kg")

                    st.caption(
                        f"💡 Glicerol **puro** necesario = **{est_glicerol_puro_kg:,.0f} kg**. "
                        f"Como la glicerina tiene {glicerol_v:.0f}% de glicerol, hay que cargar "
                        f"**{est_glice_kg:,.0f} kg** de glicerina ({mas_por_impureza:,.0f} kg extra por la impureza)."
                    )
                    st.caption(
                        f"🧪 Catalizador elegido: **{('NaOH' if catalizador_tipo=='NAOH' else 'Potasio (KOH)')}**. "
                        f"Si cambiaras al otro: {('NaOH' if catalizador_tipo=='POTASIO' else 'Potasio')} → "
                        f"{(tn*rate_naoh) if catalizador_tipo=='POTASIO' else (tn*rate_potasio):,.2f} kg."
                    )

                    st.markdown("**🎯 Producto final esperado**")
                    st.metric("ARE estimado", f"{est_are_kg:,.0f} kg", f"~{est_are_kg/1000:.1f} TN")
                    st.caption("⚠️ Aproximación 1:1 sobre la masa de AG. Cuando tengas rendimiento real de planta lo ajustamos.")
                else:
                    st.info("Cargá **acidez oleico**, **% glicerol** y **Q AG** para ver los estimados (glicerina, NaOH, potasio, fuel) y la producción esperada.")

            # Estimación específica DESGOMADO_ACUOSO (fuel + horas por TN AFE-S generado)
            if tipo_proceso_sel == "DESGOMADO_ACUOSO":
                st.markdown("**📐 Estimación DESGOMADO_ACUOSO**")
                cDA1, cDA2, cDA3 = st.columns(3)
                tn_afe_target = cDA1.number_input(
                    "TN de AFE-S a generar",
                    min_value=0.0, max_value=100.0, step=0.5, value=10.0,
                    key="b_tn_afe", help="Estimación de cuánto AFE-S vas a obtener (≈ AFE-SG procesado)."
                )
                def _rate(insumo):
                    f = consumos_proceso[
                        (consumos_proceso["tipo_proceso"]=="DESGOMADO_ACUOSO") &
                        (consumos_proceso["codigo_insumo"]==insumo)
                    ]
                    if f.empty: return None, None
                    return float(f.iloc[0]["consumo_por_tn"]), f.iloc[0]["unidad_consumo"]

                rate_fuel, u_fuel = _rate("FUEL")
                rate_h,    u_h    = _rate("HORAS")

                if rate_fuel is not None:
                    est_fuel_kg = tn_afe_target * rate_fuel   # se guarda en estimado_fuel_kg (valor en su unidad)
                    cDA2.metric(f"Fuel estimado ({u_fuel})", f"{est_fuel_kg:,.1f}",
                                f"{rate_fuel:.1f} {u_fuel}/TN AFE-S")
                if rate_h is not None:
                    est_horas_total = tn_afe_target * rate_h
                    tiempo_est = est_horas_total              # se guarda en tiempo_estimado_horas
                    cDA3.metric("Horas hombre est.", f"{est_horas_total:,.2f} h",
                                f"{rate_h:.2f} h/TN AFE-S")

                # ARE estimated lo reusamos como kg de AFE-S (interpretación: producto final esperado)
                est_are_kg = tn_afe_target * 1000.0
                # Q AG planeado igual al output (1:1 aprox para desgomado)
                q_ag_kg_ref = est_are_kg

                # Duración total esperada por suma de etapas (alternativa)
                dur_d = duraciones_etapa[
                    (duraciones_etapa["sector"]==sector) &
                    (duraciones_etapa["tipo_proceso"]=="DESGOMADO_ACUOSO")
                ]
                if not dur_d.empty:
                    total_min = int(dur_d["duracion_target_min"].sum())
                    st.caption(f"⏱️ Duración total esperada por etapas: **~{total_min} min** "
                               f"({total_min/60:.2f} h)")

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

        # ----- Alarmas plan-vs-real para insumos cargados -----
        def _alarma_consumo(label, real_kg, est_kg, tol=5.0, unidad="kg"):
            if est_kg is None or est_kg <= 0:
                return
            if real_kg is None or real_kg <= 0:
                st.caption(f"⏳ {label}: estimado {est_kg:,.1f} {unidad} · sin cargar real todavía.")
                return
            desv_abs = real_kg - est_kg
            desv_pct = (desv_abs / est_kg) * 100
            txt = (f"{label}: real **{real_kg:,.1f} {unidad}** vs estimado **{est_kg:,.1f} {unidad}** "
                   f"→ desvío **{desv_pct:+.1f}%** ({desv_abs:+,.1f} {unidad})")
            if abs(desv_pct) <= tol:
                st.success("✅ " + txt + " · dentro de ±5%.")
            elif desv_pct > 0:
                st.warning("⚠️ " + txt + " · **fuera** del estándar (cargaste de **más**).")
            else:
                st.warning("⚠️ " + txt + " · **fuera** del estándar (falta para llegar al estimado).")

        if tipo_proceso_sel == "PRODUCCION_ARE" and insumos_dict:
            st.markdown("**🚨 Plan vs real (insumos)**")
            real_fuel    = float(insumos_dict.get("FUEL", 0.0) or 0)
            real_naoh    = float(insumos_dict.get("soda_kg", 0.0) or 0)
            real_potasio = float(insumos_dict.get("POTASIO", 0.0) or 0)
            _alarma_consumo("Fuel", real_fuel, est_fuel_kg, unidad="kg")
            if catalizador_tipo == "NAOH":
                _alarma_consumo("NaOH", real_naoh, est_naoh_kg, unidad="kg")
                if real_potasio > 0:
                    st.warning(f"⚠️ Cargaste {real_potasio:.2f} kg de Potasio pero el catalizador elegido era NaOH.")
            elif catalizador_tipo == "POTASIO":
                _alarma_consumo("Potasio", real_potasio, est_potasio_kg, unidad="kg")
                if real_naoh > 0:
                    st.warning(f"⚠️ Cargaste {real_naoh:.2f} kg de NaOH pero el catalizador elegido era Potasio.")

        if tipo_proceso_sel == "DESGOMADO_ACUOSO" and insumos_dict:
            st.markdown("**🚨 Plan vs real (insumos)**")
            real_fuel = float(insumos_dict.get("FUEL", 0.0) or 0)
            # est_fuel_kg para DESGOMADO se computó en L (8.7 L/TN)
            _alarma_consumo("Fuel", real_fuel, est_fuel_kg, unidad="L")

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
                                "  catalizador_tipo,"
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
                                "  %s,"
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
                                 catalizador_tipo or None,
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
                            # Insertar primer evento de etapa (abre el ARMADO o etapa seleccionada)
                            if es_reactor and etapa_sel:
                                cur.execute("""
                                    INSERT INTO fact_etapa_evento
                                    (id_batch, etapa, inicio_ts, id_usuario)
                                    VALUES (%s, %s, COALESCE(%s, NOW()), %s)
                                """, (id_b, etapa_sel,
                                      inicio_dt.isoformat() if inicio_dt else None,
                                      int(USR["id_usuario"])))
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

            # Historial de eventos de etapa para esta reacción
            df_eve = cat(f"""
                SELECT e.id_evento_etapa, e.etapa, e.inicio_ts, e.fin_ts,
                       e.duracion_real_min, e.observaciones,
                       u.nombre AS usuario,
                       d.duracion_target_min, d.duracion_min_min, d.duracion_max_min
                FROM produccion.fact_etapa_evento e
                JOIN produccion.dim_usuario u ON u.id_usuario = e.id_usuario
                LEFT JOIN produccion.dic_etapa_duracion d
                  ON d.sector='REACTORES' AND d.tipo_proceso='{r["tipo_proceso"]}' AND d.etapa=e.etapa
                WHERE e.id_batch = {id_batch_edit}
                ORDER BY e.inicio_ts
            """)
            if not df_eve.empty:
                df_eve = df_eve.copy()
                # duración: la cargada manualmente; si falta, la calculada por timestamps
                def _dur(x):
                    if pd.notna(x.get("duracion_real_min")):
                        return float(x["duracion_real_min"])
                    if pd.notna(x["inicio_ts"]):
                        fin = x["fin_ts"] if pd.notna(x["fin_ts"]) else pd.Timestamp.now(tz="UTC")
                        return round((fin - x["inicio_ts"]).total_seconds()/60, 1)
                    return None
                df_eve["duracion_min"] = df_eve.apply(_dur, axis=1)
                df_eve["estado"] = df_eve["fin_ts"].apply(lambda v: "✅ cerrada" if pd.notna(v) else "🟢 abierta")
                df_eve["desv_vs_target"] = df_eve.apply(
                    lambda x: None if pd.isna(x.get("duracion_target_min")) or pd.isna(x["duracion_min"])
                              else round((x["duracion_min"] - x["duracion_target_min"])/x["duracion_target_min"]*100, 1),
                    axis=1)
                st.markdown("**Historial de etapas (real vs target, en minutos)**")
                st.dataframe(
                    df_eve[["etapa","estado","duracion_min","duracion_target_min","desv_vs_target","inicio_ts","fin_ts","usuario","observaciones"]],
                    use_container_width=True, hide_index=True
                )
                # KPIs
                total_real = df_eve["duracion_min"].fillna(0).sum()
                total_target = df_eve["duracion_target_min"].fillna(0).sum()
                kK1, kK2, kK3 = st.columns(3)
                kK1.metric("Tiempo real (min)", f"{total_real:,.0f}")
                kK2.metric("Tiempo target (min)", f"{total_target:,.0f}")
                if total_target > 0 and pd.notna(r.get("kg_obtenido")) and r["kg_obtenido"]:
                    kg_h = (r["kg_obtenido"] / (total_real/60)) if total_real > 0 else None
                    kK3.metric("Productividad (kg/h)", f"{kg_h:,.0f}" if kg_h else "—")
                elif total_target > 0:
                    kK3.metric("Desvío total", f"{((total_real-total_target)/total_target*100):+.1f}%" if total_real>0 else "—")
            else:
                st.caption("No hay eventos de etapa registrados para esta reacción todavía.")

            st.divider()
            etapas_codigos = etapas_proc["codigo"].tolist()
            etapa_actual_cod = r["etapa_actual"]
            etapa_actual_desc = (etapas_proc[etapas_proc["codigo"]==etapa_actual_cod].iloc[0]["descripcion"]
                                 if etapa_actual_cod in etapas_codigos else (etapa_actual_cod or "—"))
            # target de duración de la etapa actual (si existe)
            dur_tgt = duraciones_etapa[
                (duraciones_etapa["sector"]=="REACTORES") &
                (duraciones_etapa["tipo_proceso"]==r["tipo_proceso"]) &
                (duraciones_etapa["etapa"]==etapa_actual_cod)
            ]
            tgt_min = int(dur_tgt.iloc[0]["duracion_target_min"]) if not dur_tgt.empty else None

            st.markdown(f"### Cerrar etapa actual: **{etapa_actual_desc}**")
            st.caption(f"Estás cerrando la etapa **{etapa_actual_cod}**. Indicá cuántos minutos duró y a qué etapa pasás.")

            cE1, cE2 = st.columns(2)
            dur_help = f"Target sugerido: {tgt_min} min" if tgt_min else "Sin target definido"
            dur_min_in = cE1.number_input(
                f"Duración de '{etapa_actual_desc}' (minutos)",
                min_value=0, max_value=100000,
                value=(tgt_min or 0), step=1, key="e_durmin", help=dur_help
            )
            idx_actual = etapas_codigos.index(etapa_actual_cod) if etapa_actual_cod in etapas_codigos else 0
            idx_nueva = min(idx_actual + 1, len(etapas_codigos)-1)
            nueva_etapa = cE2.selectbox(
                "Pasar a la etapa", etapas_codigos, index=idx_nueva,
                format_func=lambda c: etapas_proc[etapas_proc["codigo"]==c].iloc[0]["descripcion"],
                key="e_etapa"
            )
            # feedback de desvío vs target en vivo
            if tgt_min and dur_min_in > 0:
                desv = (dur_min_in - tgt_min) / tgt_min * 100
                if abs(desv) <= 20:
                    st.success(f"✅ {dur_min_in} min vs target {tgt_min} min ({desv:+.0f}%) · dentro de lo esperado.")
                else:
                    st.warning(f"⚠️ {dur_min_in} min vs target {tgt_min} min ({desv:+.0f}%) · fuera de lo esperado.")

            obs_etapa = st.text_input("Observaciones (opcional)", max_chars=200, key="e_obs_etapa")
            if st.button(f"💾 Cerrar '{etapa_actual_desc}' y pasar a la nueva", use_container_width=True, type="primary", key="e_save"):
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            # Cerrar evento abierto: guarda duración manual en minutos
                            cur.execute("""
                                UPDATE fact_etapa_evento
                                   SET fin_ts = NOW(),
                                       duracion_real_min = COALESCE(%s, duracion_real_min),
                                       observaciones = COALESCE(NULLIF(%s,''), observaciones)
                                 WHERE id_batch=%s AND fin_ts IS NULL
                            """, (int(dur_min_in) if dur_min_in else None,
                                  obs_etapa, id_batch_edit))
                            # Abrir el nuevo evento
                            cur.execute("""
                                INSERT INTO fact_etapa_evento
                                (id_batch, etapa, inicio_ts, id_usuario)
                                VALUES (%s, %s, NOW(), %s)
                            """, (id_batch_edit, nueva_etapa, int(USR["id_usuario"])))
                            cur.execute("UPDATE fact_batch_proceso SET etapa_actual=%s WHERE id_batch=%s",
                                        (nueva_etapa, id_batch_edit))
                        audit.log("U","fact_batch_proceso",id_batch_edit,
                                  {"cerro_etapa": etapa_actual_cod, "duracion_min": int(dur_min_in) if dur_min_in else None,
                                   "nueva_etapa": nueva_etapa})
                    st.success(f"Cerraste **{etapa_actual_desc}** ({dur_min_in} min). Ahora en **{nueva_etapa}**.")
                    cat.clear(); st.rerun()
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

        # ===== Plan vs Real (REACTORES con estimados cargados) =====
        st.markdown("**🎯 Plan vs Real (reactores)**")
        df_pvr = cat(f"""
            SELECT
              b.id_batch, b.identificador_unidad AS ticket, b.fecha,
              b.q_ag_planeado_kg, b.kg_inicial AS q_ag_real_kg,
              b.estimado_glicerina_kg, b.estimado_naoh_kg, b.estimado_potasio_kg,
              b.estimado_fuel_kg, b.estimado_are_kg, b.kg_obtenido AS are_real_kg,
              (b.insumos->>'GLICERINA')::numeric  AS gli_real_kg,
              (b.insumos->>'soda_kg')::numeric    AS naoh_real_kg,
              (b.insumos->>'POTASIO')::numeric    AS potasio_real_kg,
              (b.insumos->>'FUEL')::numeric       AS fuel_real_kg
            FROM fact_batch_proceso b
            WHERE NOT b.anulado AND b.sector='REACTORES'
              AND b.estimado_are_kg IS NOT NULL
              AND b.creado_en >= NOW() - INTERVAL %s
            ORDER BY b.fecha DESC, b.id_batch DESC LIMIT 50
        """, (f"{int(rango_dias)} days",))
        if df_pvr.empty:
            st.caption("Aún no hay reacciones con estimado cargado en este período.")
        else:
            def _desv(real, est):
                if est is None or est == 0 or pd.isna(est) or pd.isna(real): return None
                return round((real - est)/est*100, 1)
            df_pvr["desv_ARE_%"]     = df_pvr.apply(lambda r: _desv(r["are_real_kg"], r["estimado_are_kg"]), axis=1)
            df_pvr["desv_Glice_%"]   = df_pvr.apply(lambda r: _desv(r["gli_real_kg"], r["estimado_glicerina_kg"]), axis=1)
            df_pvr["desv_NaOH_%"]    = df_pvr.apply(lambda r: _desv(r["naoh_real_kg"], r["estimado_naoh_kg"]), axis=1)
            df_pvr["desv_Fuel_%"]    = df_pvr.apply(lambda r: _desv(r["fuel_real_kg"], r["estimado_fuel_kg"]), axis=1)
            st.dataframe(df_pvr, use_container_width=True, hide_index=True)

        # ===== Vista visual de reacciones (tarjetas) =====
        st.divider()
        st.markdown("### 🧪 Reacciones recientes (vista visual)")

        df_cards = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha,
                   b.tipo_proceso, b.etapa_actual, bu.nombre_ui AS reactor,
                   pb.codigo_producto AS buscado, b.calidad_buscada,
                   p.codigo_producto  AS obtenido, b.kg_obtenido, b.calidad_final
            FROM fact_batch_proceso b
            LEFT JOIN dim_producto p   ON p.id_producto  = b.id_producto_obtenido
            LEFT JOIN dim_producto pb  ON pb.id_producto = b.id_producto_buscado
            LEFT JOIN dim_bien_uso bu  ON bu.id_bien_uso = b.id_bien_uso
            WHERE NOT b.anulado AND b.sector='REACTORES'
            ORDER BY b.creado_en DESC LIMIT 24
        """)
        if df_cards.empty:
            st.caption("No hay reacciones todavía.")
        else:
            etapa_emoji = {"ARMADO":"🧱","REACCION":"🔥","REPOSANDO":"⏸️","DECANTACION":"💧","EN_TANQUE":"🪣"}
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
# TAB MIS CARGAS (anular registros)  ·  tab_objs[2]
# =========================================================================
with tab_objs[2]:
    st.subheader("✏️ Mis cargas · anular registros")
    rol = USR["rol"]
    if rol == "OPERADOR":
        st.caption("Ves SOLO tus cargas. Podés anular dentro de las **24 h**.")
        dias = 7
    elif rol == "SUPERVISOR":
        st.caption("Ves cargas de TODOS. Podés anular dentro de **7 días**.")
        dias = 30
    else:
        st.caption("Ves TODAS las cargas. Podés anular sin límite.")
        dias = 60
    dias = st.slider("Días hacia atrás a mostrar", 1, 60, dias, key="mc_dias")
    try:
        rows = listar_mis_cargas(USR["id_usuario"], rol, dias)
    except Exception as e:
        st.exception(e); rows = []
    if not rows:
        st.info("No hay cargas en el rango seleccionado.")
    else:
        df = pd.DataFrame(rows, columns=["tipo","id","fecha","sector","detalle","valor","anulado","creado_en","cargado_por"])
        df["estado"] = df["anulado"].apply(lambda x: "🚫 ANULADO" if x else "✅ activo")
        st.dataframe(df[["tipo","id","fecha","cargado_por","sector","detalle","valor","creado_en","estado"]],
                     use_container_width=True, hide_index=True)
        st.divider()
        activos = [r for r in rows if not r[6]]
        if not activos:
            st.info("No hay registros activos para anular.")
        else:
            opciones = {f"#{r[1]} · {r[0]} · {r[2]} · {r[8]} · {r[4] or '—'}": r for r in activos}
            sel = st.selectbox("Registro a anular", list(opciones.keys()), key="mc_sel")
            r_sel = opciones[sel]
            tabla_sel = "fact_batch_proceso"
            propio = (r_sel[8] == USR["nombre"])
            ok, motivo_check = puede_anular(rol, propio, r_sel[7])
            (st.success if ok else st.error)(("✅ Podés anular: " if ok else "❌ No podés: ") + motivo_check)
            with st.form("form_anular"):
                motivo = st.text_input("Motivo (min 5 caracteres)", max_chars=200)
                conf = st.checkbox("Confirmo que quiero anular este registro")
                submit_a = st.form_submit_button("🚫 Anular registro", type="primary", disabled=not ok)
            if submit_a:
                if not conf:
                    st.error("Marcá la confirmación.")
                elif len(motivo.strip()) < 5:
                    st.error("Motivo demasiado corto.")
                else:
                    try:
                        anular_registro(USR["id_usuario"], tabla_sel, r_sel[1], motivo)
                        st.success(f"Registro #{r_sel[1]} anulado."); st.rerun()
                    except Exception as e:
                        st.error(str(e))

# =========================================================================
# TAB AUDIT  ·  tab_objs[3]
# =========================================================================
with tab_objs[3]:
    st.subheader("🕒 Auditoría · últimos 100 eventos")
    try:
        df_aud = cat(
            "SELECT e.ts, u.nombre AS usuario, u.nombre_full, e.operacion, e.tabla, e.pk_valor, e.cambios "
            "FROM produccion.aud_eventos e "
            "JOIN produccion.dim_usuario u ON u.id_usuario = e.id_usuario "
            "ORDER BY e.ts DESC LIMIT 100"
        )
        if df_aud.empty:
            st.info("Sin eventos de auditoría todavía.")
        else:
            st.dataframe(df_aud, use_container_width=True, hide_index=True)
    except Exception as e:
        st.exception(e)
