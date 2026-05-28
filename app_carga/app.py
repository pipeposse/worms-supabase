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
    st.markdown("""
    <style>
      .block-container{max-width:1100px;padding-top:2.4rem;}
      [data-testid="stVerticalBlockBorderWrapper"]{transition:border-color .15s;}
    </style>
    """, unsafe_allow_html=True)
    st.markdown("## 🏭 WORMS · Panel de producción")
    st.caption(f"Sesión: **{USR['nombre_full']}** · rol **{USR['rol']}**")
    st.write("")

    tiles = [
        ("🏭", "Cargas", "Carga de producción: armado, etapas, producto final y anulaciones.", "CARGAS", "land_cargas", True),
        ("📊", "Vistas de producción", "Producción, consumos y tiempos por sector + informe mensual (kg/L/TN).", "VISTAS", "land_vistas", True),
        ("🧪", "Laboratorio", "Resultados de laboratorio: filtros, estadísticas y descarga CSV.", "LAB", "land_lab", False),
        ("🚛", "Portería", "Pesajes de portería: filtros, peso por producto y descarga.", "PORT", "land_port", False),
        ("🛢️", "Tanques", "Stock por tanque: contenido, capacidad y última medición cargada.", "TANQUES", "land_tanques", False),
    ]
    if USR["rol"] in ("SUPERVISOR", "ADMIN"):
        tiles.append(("🤖", "Consultas IA", "Preguntá en lenguaje natural sobre camiones y lab (solo lectura).", "CHAT", "land_chat", False))
    if USR["rol"] == "ADMIN":
        tiles.append(("⚙️", "Admin", "Gestión de usuarios: alta, roles, sectores, reset PIN.", "ADMIN", "land_admin", False))

    for i in range(0, len(tiles), 3):
        cols = st.columns(3)
        for col, (icon, tit, desc, sec, key, prim) in zip(cols, tiles[i:i+3]):
            with col:
                with st.container(border=True):
                    st.markdown(f"#### {icon} {tit}")
                    st.caption(desc)
                    if st.button("Entrar", type=("primary" if prim else "secondary"),
                                 use_container_width=True, key=key):
                        go_to(sec)
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

# ---- estilo global (look más profesional) ----
st.markdown("""
<style>
  .block-container{padding-top:2rem; max-width:1180px;}
  /* tarjeta de metrica neutra: funciona en tema claro y oscuro (sin forzar colores de texto) */
  [data-testid="stMetric"]{border:1px solid rgba(130,140,150,.28);border-radius:12px;padding:12px 14px;}
  [data-testid="stMetricValue"]{font-size:1.5rem;font-weight:700;}
  [data-testid="stMetricLabel"]{opacity:.8;}
  section[data-testid="stSidebar"]{border-right:1px solid rgba(130,140,150,.2);}
  div[data-testid="stExpander"] details{border-radius:12px;}
  .stTabs [data-baseweb="tab-list"]{gap:2px;}
  h1{font-size:1.7rem;} h2{font-size:1.3rem;}
</style>
""", unsafe_allow_html=True)

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


# ---- Tickets de portería (NUMÉRICOS) → peso neto desde transacciones ----
def pesos_de_tickets(tx_str):
    """Parsea N° de ticket numéricos y devuelve (kg_total, df_detalle, n_pedidos, faltantes).
    El peso de portería se guarda negativo → uso ABS. Un ticket puede tener varias pesadas."""
    import re as _re
    nums = [int(x) for x in _re.findall(r"\d+", tx_str or "")]
    if not nums:
        return 0.0, pd.DataFrame(columns=["transaccion", "producto_base", "kg"]), [], []
    try:
        df = cat(
            "SELECT transaccion, producto_base, ABS(peso_neto) AS kg, fecha_entrada "
            "FROM produccion.v_transacciones_limpias WHERE transaccion = ANY(%s)",
            (nums,),
        )
    except Exception:
        df = pd.DataFrame(columns=["transaccion", "producto_base", "kg"])
    encontrados = sorted(set(int(t) for t in df["transaccion"].tolist())) if not df.empty else []
    faltantes = [n for n in nums if n not in encontrados]
    total = float(pd.to_numeric(df["kg"], errors="coerce").sum()) if not df.empty else 0.0
    return total, df, nums, faltantes


# ===========================================================================
# params_de_tickets_lab: mira procesos_lab para los tickets dados y calcula
# promedio ponderado por kg de portería para cada parámetro evaluado.
# Mapping codigo_producto → (lab_producto, lab_calidad) vía dic_producto_lab.
# ===========================================================================
# Métricas que extraemos del lab (col nombre real en procesos_lab → alias)
_LAB_METRICS = [
    ("prc_acidez",      "Acidez (%)"),
    ("prc_agua",        "Agua (%)"),
    ("prc_sedimentos",  "Sedimentos (%)"),
    ("prc_producto",    "Producto (%)"),
    ("ppm_azufre",      "Azufre (ppm)"),
    ("ppm_fosforo",     "Fósforo (ppm)"),
    ("densidad__g_ml",  "Densidad (g/ml)"),
]

def params_de_tickets_lab(tx_str, codigo_producto):
    """Para una lista de tickets (números) y un codigo_producto:
       1) Resuelve (lab_producto, lab_calidad) desde dic_producto_lab.
       2) Trae kg de portería (v_transacciones_limpias) por ticket.
       3) Trae params evaluados en produccion.procesos_lab por ticket
          filtrando producto_lab y calidad_final_lab.
       4) Mergea por ticket y calcula promedio PONDERADO por kg de cada métrica
          (ignora NaN por métrica).
       Devuelve: (df_detalle, avg_dict, missing_lab, missing_port, mapping_tuple).
    """
    import re as _re
    nums = sorted(set(int(x) for x in _re.findall(r"\d+", tx_str or "")))
    if not nums:
        return pd.DataFrame(), {}, [], [], (None, None)

    # 1) Mapeo producto → (lab_producto, lab_calidad)
    lab_prod = lab_cal = None
    if codigo_producto:
        try:
            mp = cat(
                "SELECT lab_producto, lab_calidad FROM dic_producto_lab dpl "
                "JOIN dim_producto p ON p.id_producto = dpl.id_producto "
                "WHERE p.codigo_producto = %s",
                (codigo_producto,),
            )
            if not mp.empty:
                lab_prod = mp.iloc[0]["lab_producto"]
                lab_cal  = mp.iloc[0]["lab_calidad"]
        except Exception:
            pass

    # 2) Kg desde portería por ticket
    try:
        df_p = cat(
            "SELECT transaccion AS ticket, ABS(peso_neto) AS kg, fecha_entrada "
            "FROM produccion.v_transacciones_limpias WHERE transaccion = ANY(%s)",
            (nums,),
        )
    except Exception:
        df_p = pd.DataFrame(columns=["ticket", "kg", "fecha_entrada"])

    # 3) Params del lab (último num_muestra por ticket que coincida producto/calidad)
    str_nums = [str(n) for n in nums]
    where = ["TRIM(p.ticket) = ANY(%s)"]
    params = [str_nums]
    if lab_prod:
        where.append("UPPER(TRIM(p.producto_lab)) = UPPER(%s)")
        params.append(lab_prod)
    if lab_cal:
        where.append("UPPER(TRIM(p.calidad_final_lab)) = UPPER(%s)")
        params.append(lab_cal)
    sql_lab = (
        "SELECT DISTINCT ON (TRIM(p.ticket)) "
        "  TRIM(p.ticket)::bigint AS ticket, p.num_muestra, p.fecha AS lab_fecha, "
        "  p.producto_lab, p.calidad_final_lab, "
        "  p.prc_acidez, p.prc_agua, p.prc_sedimentos, p.prc_producto, "
        "  p.ppm_azufre, p.ppm_fosforo, p.densidad__g_ml, "
        "  p.empleado AS lab_empleado, p.rechazado "
        "FROM produccion.procesos_lab p "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY TRIM(p.ticket), p.num_muestra DESC NULLS LAST, p.fecha DESC NULLS LAST"
    )
    try:
        df_l = cat(sql_lab, tuple(params))
    except Exception:
        df_l = pd.DataFrame()

    # 4) Merge por ticket (base = lista pedida) + missing
    det = pd.DataFrame({"ticket": nums})
    if not df_p.empty:
        df_p["ticket"] = pd.to_numeric(df_p["ticket"], errors="coerce").astype("Int64")
        det = det.merge(df_p, on="ticket", how="left")
    else:
        det["kg"] = pd.NA; det["fecha_entrada"] = pd.NaT
    if not df_l.empty:
        df_l["ticket"] = pd.to_numeric(df_l["ticket"], errors="coerce").astype("Int64")
        det = det.merge(df_l, on="ticket", how="left")
    else:
        for c, _ in _LAB_METRICS:
            det[c] = pd.NA
        det["num_muestra"] = pd.NA
        det["lab_fecha"] = pd.NaT
        det["producto_lab"] = pd.NA
        det["calidad_final_lab"] = pd.NA
        det["rechazado"] = pd.NA

    missing_port = sorted(int(t) for t in det.loc[det["kg"].isna(), "ticket"].tolist())
    _lab_cols_present = [c for c, _ in _LAB_METRICS if c in det.columns]
    if _lab_cols_present:
        _todos_nan = det[_lab_cols_present].isna().all(axis=1)
        missing_lab = sorted(int(t) for t in det.loc[_todos_nan, "ticket"].tolist())
    else:
        missing_lab = list(nums)

    # 5) Promedios ponderados por kg (cada métrica ignora sus propios NaN)
    avg = {}
    if "kg" in det.columns:
        w_all = pd.to_numeric(det["kg"], errors="coerce")
        for col, _lbl in _LAB_METRICS:
            if col not in det.columns:
                continue
            v = pd.to_numeric(det[col], errors="coerce")
            mask = v.notna() & w_all.notna() & (w_all > 0)
            if not mask.any():
                continue
            num = float((v[mask] * w_all[mask]).sum())
            den = float(w_all[mask].sum())
            if den > 0:
                avg[col] = num / den

    return det, avg, missing_lab, missing_port, (lab_prod, lab_cal)


def _render_tickets_lab_panel(det, avg, missing_lab, missing_port, mapping, st_container=None):
    """UI helper: muestra detalle por ticket + promedio ponderado + faltantes."""
    sc = st_container or st
    lab_prod, lab_cal = mapping
    if det is None or det.empty:
        sc.info("Ingresá uno o más números de ticket para traer los parámetros de laboratorio.")
        return
    if not lab_prod:
        sc.warning("⚠️ Este producto no tiene mapeo a laboratorio en `dic_producto_lab`. Se buscan tickets sin filtro de producto.")
    else:
        sc.caption(f"🔎 Buscando en laboratorio: **{lab_prod}** · calidad **{lab_cal or '—'}**")

    cols_show = ["ticket", "kg"]
    rename = {"kg": "kg portería"}
    for col, lbl in _LAB_METRICS:
        if col in det.columns:
            cols_show.append(col)
            rename[col] = lbl
    if "num_muestra" in det.columns:
        cols_show.append("num_muestra"); rename["num_muestra"] = "N° muestra"
    if "rechazado" in det.columns:
        cols_show.append("rechazado");   rename["rechazado"]   = "Rechazado"

    df_show = det[cols_show].rename(columns=rename).copy()
    if "kg portería" in df_show.columns:
        df_show["kg portería"] = pd.to_numeric(df_show["kg portería"], errors="coerce").round(0)
    # Mostrar prc_* como % (×100 con 2-3 decimales). ppm y densidad sin cambios.
    for col, lbl in _LAB_METRICS:
        if col.startswith("prc_") and lbl in df_show.columns:
            df_show[lbl] = pd.to_numeric(df_show[lbl], errors="coerce") * 100
            df_show[lbl] = df_show[lbl].round(3)
    sc.dataframe(df_show, hide_index=True, use_container_width=True)

    # Promedios ponderados
    if avg:
        st_msg = "**Promedio ponderado por kg cargados** (ignora NaN por parámetro):\n\n"
        bits = []
        for col, lbl in _LAB_METRICS:
            if col in avg:
                v = avg[col]
                if col.startswith("prc_"):
                    # almacenado como decimal → mostrar en %
                    bits.append(f"{lbl}: **{v*100:.3f}%**")
                elif col == "densidad__g_ml":
                    bits.append(f"{lbl}: **{v:.3f}**")
                else:
                    bits.append(f"{lbl}: **{v:.1f}**")
        st_msg += " · ".join(bits)
        sc.success(st_msg)
        # Fórmula didáctica
        with sc.expander("ℹ️ ¿Cómo se calcula el promedio ponderado?", expanded=False):
            sc.markdown(
                "Para cada parámetro `m` se hace: "
                "`promedio_m = Σ(valor_m × kg_ticket) / Σ(kg_ticket)`. "
                "Si un ticket no tiene el parámetro evaluado, se excluye del cálculo de **ese** parámetro "
                "(no se imputa cero). Los kg son los de portería (pesoneto)."
            )
    else:
        sc.info("Sin parámetros evaluados en laboratorio para estos tickets.")

    if missing_port:
        sc.warning(f"🚪 Sin pesada en portería: {missing_port}")
    if missing_lab:
        sc.warning(f"🧪 Sin muestra de laboratorio: {missing_lab}")


# ===========================================================================
# tickets_lab_disponibles_por_codigo: tickets de portería del producto pedido
# que YA tienen muestra cargada en procesos_lab. Devuelve transacción, kg,
# corriente, procedencia, fecha de entrada y métricas de lab para mostrarlos
# en un multiselect tipo "ticket · 22.280 kg · vegetal · CORDOBA · 25/05".
# ===========================================================================
def tickets_lab_disponibles_por_codigo(codigo_producto, dias=180, limit=30):
    if not codigo_producto:
        return pd.DataFrame()
    try:
        m = cat(
            "SELECT lab_producto, lab_calidad FROM dic_producto_lab dpl "
            "JOIN dim_producto p ON p.id_producto = dpl.id_producto "
            "WHERE p.codigo_producto = %s",
            (codigo_producto,),
        )
    except Exception:
        m = pd.DataFrame()
    if m.empty:
        return pd.DataFrame()
    lp = m.iloc[0]["lab_producto"]
    lc = m.iloc[0]["lab_calidad"]
    where = ["UPPER(TRIM(t.lab_producto)) = UPPER(%s)",
             "t.fecha_entrada >= current_date - %s",
             "t.peso_neto IS NOT NULL"]
    params = [lp, int(dias)]
    if lc:
        where.append("UPPER(TRIM(t.lab_calidad)) = UPPER(%s)")
        params.append(lc)
    sql = (
        "SELECT t.transaccion AS ticket, ABS(t.peso_neto) AS kg, "
        "       LOWER(t.corriente) AS corriente, t.procedencia, "
        "       t.fecha_entrada, t.lab_fecha, "
        "       t.lab_prc_acidez, t.lab_prc_agua "
        "FROM produccion.v_transacciones_limpias t "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY t.fecha_entrada DESC NULLS LAST, t.transaccion DESC LIMIT %s"
    )
    params.append(int(limit))
    try:
        return cat(sql, tuple(params))
    except Exception:
        return pd.DataFrame()


def _ui_multiselect_tickets(codigo_producto, key_prefix, dias=180, limit=30, max_tickets=3):
    """Renderiza multiselect de tickets disponibles + cuadro de tickets manuales
    extra. Devuelve string compuesto de todos los tickets separados por coma.
    Aplica un tope de `max_tickets` (default 3) entre seleccionados + manuales."""
    _df = tickets_lab_disponibles_por_codigo(codigo_producto, dias=dias, limit=limit)
    _selected_str = ""
    if _df.empty:
        st.caption("Sin tickets recientes con lab cargado para este producto. Usá el campo manual.")
    else:
        def _fmt(r):
            _f = r["fecha_entrada"]
            try:
                _f = pd.to_datetime(_f).strftime("%d/%m/%y")
            except Exception:
                _f = str(_f)
            _ac = r.get("lab_prc_acidez")
            _ac_txt = f" · acidez {float(_ac)*100:.2f}%" if pd.notna(_ac) else ""
            return (f"{int(r['ticket'])} · {float(r['kg']):,.0f} kg · "
                    f"{(r['corriente'] or '—')} · {(r['procedencia'] or '—')} · "
                    f"{_f}{_ac_txt}")
        _df = _df.copy()
        _df["_label"] = _df.apply(_fmt, axis=1)
        _opts = _df["_label"].tolist()
        _picked = st.multiselect(
            f"Tickets de portería con lab cargado (máx {max_tickets})",
            _opts, key=f"{key_prefix}_msel",
            max_selections=max_tickets,
            help=f"Últimos {dias} días, producto matching del laboratorio. "
                 f"Filtrado por dic_producto_lab. Tope: {max_tickets} tickets por proceso.",
        )
        _ticks = _df.loc[_df["_label"].isin(_picked), "ticket"].astype(int).tolist()
        _selected_str = ", ".join(str(t) for t in _ticks)
    _manual = st.text_input(
        "Otros tickets (manual, separados por coma)",
        key=f"{key_prefix}_man",
        placeholder="opcional: ej. 4805, 4640",
        help=f"Solo si necesitás tickets más viejos o no listados arriba. "
             f"El total combinado no debería superar {max_tickets}.",
    )
    _full = ", ".join([s for s in [_selected_str, (_manual or "").strip()] if s])
    # Avisar si se pasa del tope
    import re as _re2
    _count = len(set(int(x) for x in _re2.findall(r"\d+", _full or "")))
    if _count > max_tickets:
        st.warning(f"⚠️ Cargaste **{_count}** tickets; el proceso admite hasta **{max_tickets}**. Quitá los sobrantes antes de guardar.")
    return _full


# ===========================================================================
# ultimas_muestras_mp: últimas N muestras de un MP (AG-C, SEBO-*, etc) en
# procesos_lab. Usa dic_producto_lab para resolver (lab_producto, lab_calidad).
# Útil para ARE donde el MP no se pesa: igual queremos saber la acidez.
# ===========================================================================
def ultimas_muestras_mp(codigo_producto, n=3):
    if not codigo_producto:
        return pd.DataFrame()
    try:
        m = cat(
            "SELECT lab_producto, lab_calidad FROM dic_producto_lab dpl "
            "JOIN dim_producto p ON p.id_producto = dpl.id_producto "
            "WHERE p.codigo_producto = %s",
            (codigo_producto,),
        )
    except Exception:
        m = pd.DataFrame()
    if m.empty:
        return pd.DataFrame()
    lp = m.iloc[0]["lab_producto"]
    lc = m.iloc[0]["lab_calidad"]
    where = ["UPPER(TRIM(producto_lab)) = UPPER(%s)"]
    params = [lp]
    if lc:
        where.append("UPPER(TRIM(calidad_final_lab)) = UPPER(%s)")
        params.append(lc)
    sql = (
        "SELECT ticket, num_muestra, fecha::date AS fecha, "
        "       prc_acidez, prc_agua, prc_sedimentos, prc_producto, "
        "       ppm_azufre, ppm_fosforo, densidad__g_ml, "
        "       calidad_final_lab, empleado "
        "FROM produccion.procesos_lab "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY fecha DESC NULLS LAST, num_muestra DESC NULLS LAST LIMIT %s"
    )
    params.append(int(n))
    try:
        return cat(sql, tuple(params))
    except Exception:
        return pd.DataFrame()


# ===========================================================================
# ultimas_muestras_glicerina: devuelve las últimas N muestras del producto
# GLICERINA en procesos_lab con gli_glicerol no nulo. La UI permite elegir
# por ticket (default = última); el % glicerol pasa a la fórmula sin input
# manual.
# ===========================================================================
def ultimas_muestras_glicerina(n=3):
    try:
        df = cat(
            "SELECT ticket, num_muestra, fecha::date AS fecha, "
            "       gli_glicerol, gli_humedad, gli_ays, gli_ceniza, gli_mong, "
            "       calidad_final_lab, empleado "
            "FROM produccion.procesos_lab "
            "WHERE producto_lab = 'GLICERINA' AND gli_glicerol IS NOT NULL "
            "ORDER BY fecha DESC NULLS LAST, num_muestra DESC NULLS LAST "
            "LIMIT %s",
            (int(n),),
        )
        return df
    except Exception:
        return pd.DataFrame()


# ---- Preferencias de UI por usuario (persisten en dim_usuario.prefs JSONB) ----
def _load_prefs():
    """Lee las prefs del usuario una vez por sesión y las cachea en session_state."""
    if "_prefs" not in st.session_state:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public")
                cur.execute("SELECT COALESCE(prefs,'{}'::jsonb) FROM dim_usuario WHERE id_usuario=%s",
                            (USR["id_usuario"],))
                row = cur.fetchone()
            conn.close()
            st.session_state["_prefs"] = (row[0] if row and row[0] else {}) or {}
        except Exception:
            st.session_state["_prefs"] = {}
    return st.session_state["_prefs"]

def get_pref(key, default=None):
    return _load_prefs().get(key, default)

def set_pref(key, value):
    """Persiste una preferencia (merge en el JSONB) y actualiza la copia en sesión."""
    prefs = _load_prefs()
    if prefs.get(key) == value:
        return
    prefs[key] = value
    st.session_state["_prefs"] = prefs
    try:
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            cur.execute("UPDATE dim_usuario SET prefs = COALESCE(prefs,'{}'::jsonb) || %s::jsonb WHERE id_usuario=%s",
                        (json.dumps({key: value}), USR["id_usuario"]))
        conn.commit(); conn.close()
    except Exception:
        pass


productos = cat(
    "SELECT id_producto, codigo_producto, corriente, tipo_producto, "
    "rango_kg_min, rango_kg_max, COALESCE(densidad_g_ml, 0.91) AS densidad_g_ml, "
    "usa_reactor, usa_bachas, usa_piletas, es_exportacion "
    "FROM dim_producto "
    "WHERE activo AND tipo_producto IN ('MP','FINAL') ORDER BY codigo_producto"
)

def densidad_de(cod):
    """kg/L del producto (g/ml = kg/L). Default 0.91 si falta."""
    r = productos[productos["codigo_producto"] == cod]
    try:
        d = float(r.iloc[0]["densidad_g_ml"]) if not r.empty else 0.91
        return d if d and d > 0 else 0.91
    except Exception:
        return 0.91

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
try:
    proc_etapa = cat("""
        SELECT pe.proceso_key, pe.etapa, pe.orden,
               pe.duracion_target_min, pe.duracion_min_min, pe.duracion_max_min,
               e.descripcion
        FROM dic_proceso_etapa pe
        JOIN dic_etapa_proceso e ON e.codigo = pe.etapa
        ORDER BY pe.proceso_key, pe.orden
    """)
except Exception:
    proc_etapa = pd.DataFrame(columns=["proceso_key","etapa","orden","duracion_target_min","duracion_min_min","duracion_max_min","descripcion"])

def proceso_key_de(sector, tipo_proceso):
    """clave de proceso: tipo_proceso si es reactores, si no el sector."""
    return tipo_proceso if (sector == "REACTORES" and tipo_proceso) else sector

def etapas_de_proceso(pkey):
    """DataFrame de etapas (etapa, descripcion, orden, duraciones) para ese proceso, ordenadas."""
    df = proc_etapa[proc_etapa["proceso_key"] == pkey].sort_values("orden")
    if df.empty:
        # fallback: lista plana
        return etapas_proc.rename(columns={"codigo":"etapa"})[["etapa","descripcion","orden"]]
    return df
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
insumos_cat = cat("SELECT codigo, descripcion, unidad, COALESCE(evaluable,FALSE) AS evaluable, densidad_g_ml FROM dic_insumo WHERE activo ORDER BY codigo")
def densidad_insumo(cod, default=None):
    """Densidad kg/L (=g/ml) de un insumo para convertir litros<->kg. Editable en dic_insumo."""
    r = insumos_cat[insumos_cat["codigo"] == cod]
    if not r.empty and pd.notna(r.iloc[0]["densidad_g_ml"]):
        return float(r.iloc[0]["densidad_g_ml"])
    return default

# Catalizadores: genera_glicerina_recup / reduce_glicerina (editable en dic_catalizador)
try:
    catalizadores = cat("SELECT codigo, descripcion, genera_glicerina_recup, reduce_glicerina, nota FROM dic_catalizador")
except Exception:
    catalizadores = pd.DataFrame(columns=["codigo","descripcion","genera_glicerina_recup","reduce_glicerina","nota"])
def catalizador_genera_glicerina(cod):
    r = catalizadores[catalizadores["codigo"]==cod]
    return bool(r.iloc[0]["genera_glicerina_recup"]) if not r.empty else True
# Decantaciones permitidas por proceso (dic_decantacion_proceso)
try:
    decant_proc = cat("SELECT proceso_key, tipo_salida, label, codigo_producto FROM dic_decantacion_proceso")
except Exception:
    decant_proc = pd.DataFrame(columns=["proceso_key","tipo_salida","label","codigo_producto"])
def decantaciones_de(pkey):
    return decant_proc[decant_proc["proceso_key"]==pkey]

# Reglas de carga (editables desde Supabase)
try:
    sector_cfg = cat("SELECT sector, permite_normal, permite_recuperacion FROM dic_sector_config")
except Exception:
    sector_cfg = pd.DataFrame(columns=["sector","permite_normal","permite_recuperacion"])
try:
    proc_prod = cat("SELECT sector, tipo_proceso, tipo_operacion, rol, patron FROM dic_proceso_producto")
except Exception:
    proc_prod = pd.DataFrame(columns=["sector","tipo_proceso","tipo_operacion","rol","patron"])
try:
    consumo_sector = cat("SELECT sector, codigo_insumo, consumo_por_tn, unidad_consumo FROM dic_consumo_sector")
except Exception:
    consumo_sector = pd.DataFrame(columns=["sector","codigo_insumo","consumo_por_tn","unidad_consumo"])

def _match_patron(codigo, patron):
    """LIKE simple: % es comodín. Escapa cada parte literal y une con .* (robusto a re.escape)."""
    import re as _re2
    rgx = "^" + ".*".join(_re2.escape(p) for p in (patron or "").split("%")) + "$"
    return bool(_re2.match(rgx, codigo or ""))

def productos_permitidos(sector, tipo_proceso, tipo_operacion, rol, universo=None):
    """Devuelve lista de codigo_producto permitidos según las reglas. Si no hay regla, None (sin restriccion).
    universo: lista de códigos a filtrar; si es None usa el catálogo completo de productos."""
    if proc_prod.empty:
        return None
    f = proc_prod[(proc_prod["sector"]==sector) & (proc_prod["rol"]==rol)]
    if tipo_proceso is not None:
        f = f[(f["tipo_proceso"]==tipo_proceso) | (f["tipo_proceso"].isna())]
    if tipo_operacion is not None:
        f = f[(f["tipo_operacion"]==tipo_operacion) | (f["tipo_operacion"].isna())]
    if f.empty:
        return None
    patrones = f["patron"].tolist()
    todos = universo if universo is not None else productos["codigo_producto"].tolist()
    return [c for c in todos if any(_match_patron(c, p) for p in patrones)]

def modos_permitidos(sector):
    """(permite_normal, permite_recuperacion) para el sector."""
    r = sector_cfg[sector_cfg["sector"]==sector]
    if r.empty:
        return True, False  # default: solo normal
    return bool(r.iloc[0]["permite_normal"]), bool(r.iloc[0]["permite_recuperacion"])

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
    if st.session_state.section in ("LAB", "PORT"):
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
            c4, c5, c6 = st.columns(3)
            sel_prod = c4.multiselect("Producto", prods_lab, key="lab_prods")
            sel_emp  = c5.multiselect("Empleado", emps_lab, key="lab_emps")
            sel_corr = c6.multiselect("Corriente", CORR_EVAL, default=CORR_EVAL, key="lab_corr",
                                      help="Solo corrientes que se evalúan (vegetal, animal, insumo, efluente).")

        where = ["pl.fecha >= %s", "pl.fecha < %s"]
        params = [fmin.isoformat(), (fmax + _td(days=1)).isoformat()]
        if sel_prod:
            where.append("pl.producto_lab = ANY(%s)"); params.append(sel_prod)
        if sel_emp:
            where.append("pl.empleado = ANY(%s)"); params.append(sel_emp)
        # corriente derivada de producto_lab (vía porteria_limpieza), fallback a la propia
        sql_lab = f"""
            SELECT pl.*,
                   COALESCE(NULLIF(lower(pl.corriente),''), m.corriente) AS corriente_eval
            FROM produccion.procesos_lab pl
            LEFT JOIN (
                SELECT UPPER(TRIM(producto_base)) AS base,
                       MODE() WITHIN GROUP (ORDER BY corriente) AS corriente
                FROM produccion.porteria_limpieza WHERE corriente IS NOT NULL GROUP BY 1
            ) m ON m.base = CASE UPPER(TRIM(pl.producto_lab))
                     WHEN 'EFLUENTE'           THEN 'EFLUENTES LIQUIDOS'
                     WHEN 'ACIDO SULFURICO'    THEN 'ACIDO_KG'
                     WHEN 'HIDROXIDO DE SODIO' THEN 'SODA_KG'
                     WHEN 'FONDO DE TK'        THEN 'FONDO_TK'
                     ELSE UPPER(TRIM(pl.producto_lab)) END
            WHERE {' AND '.join(where)}
            ORDER BY pl.fecha DESC NULLS LAST
            LIMIT {int(limit_lab)}
        """
        try:
            df_l = cat(sql_lab, tuple(params))
        except Exception as e:
            st.exception(e); df_l = pd.DataFrame()
        # corriente final (derivada) + filtro por corriente evaluable
        if not df_l.empty and "corriente_eval" in df_l.columns:
            df_l["corriente"] = df_l["corriente_eval"]
            df_l = df_l.drop(columns=["corriente_eval"])
            if sel_corr:
                df_l = df_l[df_l["corriente"].isin(sel_corr)]

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
            df_show = df_l.dropna(axis=1, how="all")
            st.caption(f"Mostrando {df_show.shape[1]} columnas con datos (se ocultan {df_l.shape[1]-df_show.shape[1]} columnas 100% vacías).")
            st.dataframe(df_show, use_container_width=True, hide_index=True, height=380)
            st.download_button("⬇️ Descargar CSV", df_show.to_csv(index=False).encode("utf-8"),
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
                SELECT id, transaccion, hora_e, patente_chasis, conductor,
                       producto, producto_base, corriente,
                       cliente, transporte, procedencia,
                       peso_entrada, peso_salida,
                       (peso_neto * -1) AS peso_neto, evaluado, lab_calidad,
                       lab_prc_acidez, lab_prc_agua, lab_prc_producto,
                       lab_ppm_azufre, lab_ppm_fosforo, lab_densidad,
                       lab_color, lab_empleado, lab_rechazado, lab_fecha, lab_num_muestra,
                       _synced_at
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
                kd2.metric("TN netas del día", f"{kg_tot/1000:,.2f}")
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
                df_show["evaluado"] = df_show["eval_estado"].map({"SI":"✅ SI","NO":"⚠️ NO","no corresponde":"— no corresponde"}).fillna(df_show["eval_estado"])
                # Orden preestablecido: producto_base -> lab_calidad -> corriente juntas y al frente.
                _orden = ["transaccion","hora_e","producto_base","lab_calidad","corriente","evaluado",
                          "peso_neto","peso_entrada","peso_salida","patente_chasis","conductor",
                          "cliente","transporte","procedencia","lab_prc_acidez","lab_prc_agua",
                          "lab_ppm_fosforo","lab_densidad"]
                _orden = [c for c in _orden if c in df_show.columns]
                _def = [c for c in ["transaccion","hora_e","producto_base","lab_calidad","corriente",
                                    "evaluado","peso_neto","cliente"] if c in df_show.columns]
                _saved = get_pref("porteria_dia_cols", None)
                _default = [c for c in _saved if c in _orden] if _saved else _def
                _sel = st.multiselect("Columnas a mostrar (se reordenan automáticamente · se guardan por usuario)", _orden, default=_default, key="pd_cols")
                _cols = [c for c in _orden if c in _sel] or _orden
                if _cols != _saved:
                    set_pref("porteria_dia_cols", _cols)
                st.dataframe(df_show[_cols], use_container_width=True, hide_index=True, height=460)
                st.caption("Clic en el encabezado de una columna para ordenar (▲/▼). Elegí o quitá columnas arriba.")
                st.download_button("⬇️ Descargar CSV del dia",
                                   df_d.dropna(axis=1, how="all").to_csv(index=False).encode("utf-8"),
                                   file_name=f"porteria_{dia_sel}.csv", mime="text/csv")

                # ----- Ver qué evaluó laboratorio, por ticket -----
                ev = df_d[df_d["evaluado"] == "SI"] if "evaluado" in df_d.columns else df_d.iloc[0:0]
                if not ev.empty:
                    with st.expander("Ver evaluación de laboratorio por ticket", expanded=False):
                        def _lv(x, dec=2):
                            return f"{float(x):,.{dec}f}" if pd.notna(x) else "—"
                        _tk = st.selectbox("Ticket evaluado", ev["transaccion"].tolist(),
                                           format_func=lambda x: f"Ticket {int(x)}", key="pd_lab_tk")
                        _r = ev[ev["transaccion"] == _tk].iloc[0]
                        lc = st.columns(4)
                        lc[0].metric("Calidad", _r.get("lab_calidad") or "—")
                        lc[1].metric("Acidez %", _lv(_r.get("lab_prc_acidez")))
                        lc[2].metric("Agua %", _lv(_r.get("lab_prc_agua")))
                        lc[3].metric("Producto %", _lv(_r.get("lab_prc_producto")))
                        lc2 = st.columns(4)
                        lc2[0].metric("Azufre ppm", _lv(_r.get("lab_ppm_azufre")))
                        lc2[1].metric("Fósforo ppm", _lv(_r.get("lab_ppm_fosforo")))
                        lc2[2].metric("Densidad g/ml", _lv(_r.get("lab_densidad"), 3))
                        lc2[3].metric("Rechazado", str(_r.get("lab_rechazado") or "—"))
                        _pb = _r.get("producto_base") or "—"
                        _col = _r.get("lab_color") or "—"
                        _mu = _r.get("lab_num_muestra")
                        _mu = int(_mu) if pd.notna(_mu) else "—"
                        _emp = _r.get("lab_empleado") or "—"
                        _flab = _r.get("lab_fecha") or "—"
                        st.caption(f"Producto: {_pb} · Color: {_col} · Muestra #{_mu} · Analista: {_emp} · Fecha lab: {_flab}")

                # ----- Comprobante de pesaje (por id unico; transaccion puede repetirse) -----
                st.divider()
                st.markdown("**\U0001f9fe Comprobante de pesaje**")
                opts_cp = df_d.dropna(subset=["id"]).copy()
                if not opts_cp.empty:
                    opts_cp["lbl"] = opts_cp.apply(
                        lambda r: f"Ticket {int(r['transaccion'])} · {r['hora_e']} · {r['patente_chasis'] or ''} · {r['cliente'] or ''}", axis=1)
                    lbl = st.selectbox("Ver comprobante", opts_cp["lbl"].tolist(), key="cp_tk")
                    id_sel = int(opts_cp[opts_cp["lbl"]==lbl].iloc[0]["id"])
                    rowc = cat("SELECT * FROM produccion.transacciones WHERE id=%s LIMIT 1", (id_sel,))
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
    <tr><td style="padding:2px 8px"><b>Contenedor N°:</b></td><td>{g('proc_contenedor')}</td></tr>
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
                            "⬇️ Descargar comprobante (HTML para imprimir)",
                            ("<html><head><meta charset='utf-8'><title>Comprobante "
                             + g('transaccion') + "</title></head><body>" + comp_html + "</body></html>").encode("utf-8"),
                            file_name=f"comprobante_{g('transaccion')}_{id_sel}.html", mime="text/html", key="cp_dl")
                        st.caption("Abrilo y usá Ctrl+P para imprimir o guardar como PDF.")
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
                tx_raw = st.text_area(
                    "Buscar N° de transacción (uno por línea o separados por coma/espacio) — ignora el rango de fechas",
                    key="ph_tx", height=80, placeholder="69596\\n69597\\n4676 ...")

            # parsear lista de transacciones
            import re as _re
            tx_list = [int(x) for x in _re.findall(r"\\d+", tx_raw or "")]

            params = []
            if tx_list:
                # busca SOLO esas transacciones, sin filtro de fecha
                where = ["transaccion = ANY(%s)"]
                params.append(tx_list)
            else:
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
                       peso_entrada, peso_salida,
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
                k3.metric("TN netas total", f"{tot/1000:,.2f}")
                k4.metric("% evaluado", f"{(n_ev/len(df_p)*100):.0f}%")

                st.markdown("**Transacciones por dia**")
                by_day = df_p.dropna(subset=["fecha_entrada"]).groupby("fecha_entrada").size().reset_index(name="cantidad")
                st.line_chart(by_day, x="fecha_entrada", y="cantidad", use_container_width=True)

                st.markdown("**TN netas por corriente**")
                corr_sum = (df_p.dropna(subset=["corriente"])
                                .assign(peso=pd.to_numeric(df_p["peso_neto"], errors="coerce"))
                                .groupby("corriente")["peso"].sum()
                                .sort_values(ascending=False).reset_index())
                corr_sum["TN"] = (corr_sum["peso"] / 1000).round(2)
                st.bar_chart(corr_sum, x="corriente", y="TN", use_container_width=True)

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
                # ocultar columnas 100% vacías
                df_pd = df_pd.dropna(axis=1, how="all")
                _front = [c for c in ["transaccion","fecha_entrada","producto_base","lab_calidad","corriente",
                                      "eval_estado","peso_neto","cliente"] if c in df_pd.columns]
                _rest = [c for c in df_pd.columns if c not in _front]
                _orden_h = _front + _rest
                df_pd = df_pd[_orden_h]
                _saved_h = get_pref("porteria_hist_cols", None)
                _default_h = [c for c in _saved_h if c in _orden_h] if _saved_h else _front
                _sel_h = st.multiselect("Columnas a mostrar (se reordenan automáticamente · se guardan por usuario)", _orden_h,
                                        default=_default_h, key="ph_cols")
                _cols_h = [c for c in _orden_h if c in _sel_h] or _orden_h
                if _cols_h != _saved_h:
                    set_pref("porteria_hist_cols", _cols_h)
                st.caption(f"{len(df_pd)} filas · {len(_cols_h)} columnas. Clic en el encabezado para ordenar (▲/▼); elegí/quitá columnas arriba.")
                st.dataframe(df_pd[_cols_h], use_container_width=True, hide_index=True, height=420)
                st.download_button("⬇️ Descargar CSV", df_pd.to_csv(index=False).encode("utf-8"),
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
                ke1.metric("TN netas acumuladas", f"{total_kg/1000:,.2f}")
                ke2.metric("Viajes", n_via)
                ke3.metric("TN promedio por viaje", f"{(prom or 0)/1000:,.2f}")

                # Total por mes (barras)
                dm = df_ef.copy()
                dm["mes"] = dm["fecha_entrada"].dt.to_period("M").astype(str)
                tot_mes = dm.groupby("mes")["peso_neto"].sum().reset_index()
                tot_mes.columns = ["mes", "kg_netos"]
                tot_mes["TN"] = (tot_mes["kg_netos"] / 1000).round(2)
                st.markdown("**Total de TN netas por mes**")
                st.bar_chart(tot_mes, x="mes", y="TN", use_container_width=True)

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
                    plot_df = plot_df.copy()
                    plot_df["acum_tn"] = plot_df["acum"] / 1000.0

                    chart = alt.Chart(plot_df).mark_line(point=False).encode(
                        x=alt.X("dia:Q", title="día del mes"),
                        y=alt.Y("acum_tn:Q", title="TN netas acumuladas"),
                        color=alt.Color("mes:N", title="mes"),
                        strokeDash=alt.StrokeDash("tipo:N", title="",
                                   scale=alt.Scale(domain=["real","proyeccion"], range=[[1,0],[6,4]])),
                    ).properties(height=380)
                    st.altair_chart(chart, use_container_width=True)
                    st.caption("Línea sólida = real. Línea punteada = proyección del mes corriente según el ritmo diario actual.")

                    if mes_actual in meses_sel and proy_rows:
                        proy_total = proy_rows[-1]["acum"]
                        cp1, cp2 = st.columns(2)
                        cp1.metric(f"Acumulado {mes_actual} a hoy (TN)", f"{acum_hoy/1000:,.2f}")
                        cp2.metric("Proyección fin de mes (TN)", f"{proy_total/1000:,.2f}",
                                   help="Ritmo diario actual × días del mes")

                # Estadisticas por procedencia
                st.markdown("**Por cliente**")
                by_proc = (df_ef.dropna(subset=["cliente"])
                                .groupby("cliente")
                                .agg(viajes=("peso_neto","size"),
                                     kg_total=("peso_neto","sum"),
                                     kg_promedio=("peso_neto","mean"))
                                .sort_values("kg_total", ascending=False).reset_index())
                by_proc["TN_total"] = (by_proc["kg_total"] / 1000).round(2)
                by_proc["TN_promedio"] = (by_proc["kg_promedio"] / 1000).round(2)
                by_proc = by_proc.drop(columns=["kg_total", "kg_promedio"])
                st.bar_chart(by_proc.head(15), x="cliente", y="TN_total", use_container_width=True)
                st.dataframe(by_proc, use_container_width=True, hide_index=True)

                st.download_button("⬇️ Descargar CSV efluentes",
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
                    st.markdown(f"**{sel_pbs[0]} — promedio por cliente**")
                    st.bar_chart(sub, x="procedencia", y="promedio", use_container_width=True)
                else:
                    # vista por producto: tabla pivote (filas producto_base, columnas procedencia)
                    piv = resumen.pivot_table(index="producto_base", columns="cliente",
                                              values="promedio", aggfunc="mean")
                    st.markdown("**Promedio por producto_base (filas) x cliente (columnas)**")
                    st.dataframe(piv, use_container_width=True)

                st.markdown("**Detalle (producto_base + cliente)**")
                st.dataframe(resumen, use_container_width=True, hide_index=True, height=420)
                st.caption("n = mediciones validas · desvio = desviacion estandar (consistencia del cliente).")
                st.download_button("⬇️ Descargar CSV",
                                   resumen.to_csv(index=False).encode("utf-8"),
                                   file_name=f"lab_por_cliente_{param_sel}.csv", mime="text/csv")

    elif st.session_state.section == "VISTAS":
        # =================== VISTAS DE PRODUCCIÓN ===================
        st.title("\U0001F4CA Vistas de producción")
        try:
            secs_v = cat("SELECT DISTINCT sector FROM produccion.v_reacciones_lkg WHERE sector IS NOT NULL ORDER BY 1")["sector"].tolist()
        except Exception as e:
            st.exception(e); secs_v = []
        if not secs_v:
            st.info("Todavía no hay producción cargada para mostrar.")
        else:
            with st.expander("Filtros", expanded=True):
                cf1, cf2, cf3, cf4, cf5 = st.columns([1.2, 1.2, 1, 1, 1.2])
                sector_v = cf1.selectbox("Sector", secs_v, key="vp_sector")
                try:
                    procs_v = cat("SELECT DISTINCT tipo_proceso FROM produccion.v_reacciones_lkg WHERE sector=%s AND tipo_proceso IS NOT NULL ORDER BY 1", (sector_v,))["tipo_proceso"].tolist()
                except Exception:
                    procs_v = []
                proceso_v = cf2.selectbox("Proceso", ["Todos"] + procs_v, key="vp_proc")
                fmin_v = cf3.date_input("Desde", date.today().replace(day=1), key="vp_fmin")
                fmax_v = cf4.date_input("Hasta", date.today(), key="vp_fmax")
                unidad_v = cf5.radio("Unidad", ["TN", "kg", "litros"], horizontal=True, key="vp_unidad")

            _params = [sector_v, fmin_v.isoformat(), fmax_v.isoformat()]
            _wproc = ""
            if proceso_v != "Todos":
                _wproc = " AND tipo_proceso=%s"; _params.append(proceso_v)
            dfv = cat(f"""
                SELECT * FROM produccion.v_reacciones_lkg
                WHERE sector=%s AND fecha BETWEEN %s AND %s{_wproc}
                ORDER BY fecha
            """, tuple(_params))

            # Aclaración de cobertura (qué proceso se está viendo)
            if sector_v == "REACTORES":
                _txt = "Reactores: estás viendo **PRODUCCIÓN ARE**."
                if "DESGOMADO_ACUOSO" not in procs_v:
                    _txt += " Todavía **no se cargó Desgomado acuoso**."
                st.caption("Nota — " + _txt + " El **AG-C es la materia prima (insumo)**, no un producto.")

            if dfv.empty:
                st.info("Sin reacciones en el sector/rango elegido.")
            else:
                u = unidad_v
                def _conv(col_kg, col_lts):
                    if u == "litros":
                        return pd.to_numeric(dfv[col_lts], errors="coerce")
                    v = pd.to_numeric(dfv[col_kg], errors="coerce")
                    return (v / 1000.0) if u == "TN" else v
                dfv["_ag"]   = _conv("ag_kg", "ag_lts")
                dfv["_are"]  = _conv("are_kg", "are_lts")
                dfv["_fuel"] = _conv("fuel_kg", "fuel_lts")
                dfv["_naoh"] = _conv("naoh_kg", "naoh_lts")
                dfv["_gli"]  = _conv("gli_fresca_kg", "gli_fresca_lts").fillna(0) + _conv("gli_recup_kg", "gli_recup_lts").fillna(0)
                dfv["_dia"]  = pd.to_datetime(dfv["fecha"]).dt.date
                _hrs = pd.to_numeric(dfv["horas"], errors="coerce")
                _ag_kg_tot = pd.to_numeric(dfv["ag_kg"], errors="coerce").sum()
                _are_kg_tot = pd.to_numeric(dfv["are_kg"], errors="coerce").sum()

                # ---- KPIs ----
                st.markdown("#### Resumen del período")
                k = st.columns(5)
                k[0].metric("Reacciones", f"{len(dfv)}")
                k[1].metric(f"AG-C procesado · insumo ({u})", f"{dfv['_ag'].sum():,.2f}")
                k[2].metric(f"ARE producido ({u})", f"{dfv['_are'].sum():,.2f}")
                k[3].metric("Rendimiento", f"{(_are_kg_tot/_ag_kg_tot*100):,.1f}%" if _ag_kg_tot else "—")
                k[4].metric("Horas prom.", f"{_hrs.mean():,.1f} h" if _hrs.notna().any() else "—")

                # ---- Producción de ARE por día (producto obtenido) ----
                st.markdown(f"#### Producción de ARE por día · {u}")
                prod_dia = dfv.groupby("_dia").agg(ARE=("_are", "sum")).reset_index()
                st.bar_chart(prod_dia, x="_dia", y="ARE", color="#2dd4bf", use_container_width=True)

                # ---- Materia prima (AG-C) procesada por día (insumo, no producción) ----
                st.markdown(f"#### Materia prima procesada · AG-C (insumo) · {u}")
                mp_dia = dfv.groupby("_dia").agg(AG=("_ag", "sum")).reset_index()
                st.bar_chart(mp_dia, x="_dia", y="AG", color="#60a5fa", use_container_width=True)

                # ---- Consumos por día ----
                st.markdown(f"#### Consumos por día · {u}")
                cons_dia = dfv.groupby("_dia").agg(Fuel=("_fuel", "sum"), NaOH=("_naoh", "sum"), Glicerina=("_gli", "sum")).reset_index()
                st.bar_chart(cons_dia, x="_dia", y=["Fuel", "NaOH", "Glicerina"], color=["#f5b94a", "#c084fc", "#34d399"], use_container_width=True)

                # ---- Tiempos ----
                if _hrs.notna().any():
                    st.markdown("#### Tiempos por reacción (horas)")
                    t = dfv.loc[_hrs.notna(), ["ticket", "horas"]].copy()
                    st.bar_chart(t, x="ticket", y="horas", color="#fbbf24", use_container_width=True)

                # ---- Informe mensual ----
                st.markdown("#### Informe mensual (todo en kg, litros y TN)")
                dfv["_mes"] = pd.to_datetime(dfv["fecha"]).dt.to_period("M").astype(str)
                g = dfv.groupby("_mes")
                rep = g.agg(
                    reacciones=("id_batch", "count"),
                    AG_kg=("ag_kg", "sum"), AG_lts=("ag_lts", "sum"),
                    ARE_kg=("are_kg", "sum"), ARE_lts=("are_lts", "sum"),
                    Fuel_lts=("fuel_lts", "sum"), NaOH_kg=("naoh_kg", "sum"),
                    NaOH_lts=("naoh_lts", "sum"), horas=("horas", "sum"),
                ).reset_index().rename(columns={"_mes": "mes"})
                rep["rinde_%"] = (rep["ARE_kg"] / rep["AG_kg"] * 100).round(1)
                rep["AG_TN"] = (rep["AG_kg"] / 1000).round(2)
                rep["ARE_TN"] = (rep["ARE_kg"] / 1000).round(2)
                rep = rep.round(2)
                st.dataframe(rep, use_container_width=True, hide_index=True)
                st.download_button("⬇️ Descargar informe (CSV)", rep.to_csv(index=False).encode("utf-8"),
                                   file_name=f"informe_{sector_v}_{fmin_v}_{fmax_v}.csv", mime="text/csv")

                # ---- Detalle reacción por reacción ----
                with st.expander("Detalle reacción por reacción (litros y kg)"):
                    cols_show = ["fecha", "ticket", "reactor", "corriente",
                                 "ag_kg", "ag_lts", "are_kg", "are_lts",
                                 "naoh_kg", "naoh_lts", "fuel_lts",
                                 "gli_fresca_kg", "gli_recup_kg",
                                 "acidez_inicial", "acidez_final_pct", "densidad_final", "porc_ays",
                                 "horas", "etapa_actual"]
                    cols_show = [c for c in cols_show if c in dfv.columns]
                    _det = dfv[cols_show].dropna(axis=1, how="all")
                    st.dataframe(_det, use_container_width=True, hide_index=True, height=420)
                    st.download_button("⬇️ Descargar detalle (CSV)", _det.to_csv(index=False).encode("utf-8"),
                                       file_name=f"detalle_{sector_v}_{fmin_v}_{fmax_v}.csv", mime="text/csv",
                                       key="vp_det_csv")

    elif st.session_state.section == "TANQUES":
        # =================== TANQUES / STOCK ===================
        st.title("Tanques y stock")
        _tq = cat("SELECT id_tanque, codigo, nombre, sector, capacidad_litros, id_producto_principal, activo "
                  "FROM produccion.dim_tanque ORDER BY sector, nombre")
        _prods = cat("SELECT id_producto, codigo_producto, COALESCE(densidad_g_ml,0.91) AS dens "
                     "FROM produccion.dim_producto WHERE activo ORDER BY codigo_producto")
        if _tq.empty:
            st.info("No hay tanques cargados.")
        else:
            t_estado, t_cargar, t_editar = st.tabs(["Stock actual", "Cargar medición", "Editar tanque"])

            # ---------- STOCK ACTUAL (último medido por tanque) ----------
            with t_estado:
                _u = st.radio("Unidad", ["TN", "kg", "litros"], horizontal=True, key="tq_u")
                _secs = sorted(_tq["sector"].dropna().unique().tolist())
                _selsec = st.multiselect("Sector", _secs, key="tq_sec_f")
                df = cat("SELECT sector, nombre, capacidad_litros, producto_principal, producto_medido, "
                         "litros, kg, medido_en, cargado_por, observaciones FROM produccion.v_stock_tanque_ultimo "
                         "ORDER BY sector, nombre")
                if _selsec:
                    df = df[df["sector"].isin(_selsec)]
                def _stk(r):
                    if pd.isna(r["medido_en"]):
                        return None
                    if _u == "litros":
                        return pd.to_numeric(r["litros"], errors="coerce")
                    kg = pd.to_numeric(r["kg"], errors="coerce")
                    return (kg / 1000.0) if _u == "TN" else kg
                df["stock"] = df.apply(_stk, axis=1)
                k1, k2, k3 = st.columns(3)
                k1.metric("Tanques", len(df))
                k2.metric("Con medición", int(df["medido_en"].notna().sum()))
                k3.metric(f"Stock total ({_u})", f"{pd.to_numeric(df['stock'], errors='coerce').sum():,.2f}")
                _show = df[["sector", "nombre", "producto_medido", "producto_principal", "stock",
                            "medido_en", "cargado_por", "observaciones"]].rename(
                    columns={"producto_medido": "producto", "stock": f"stock_{_u}"})
                st.dataframe(_show, use_container_width=True, hide_index=True, height=440)
                st.caption("Cada fila = última medición cargada por tanque (lo vigente). "
                           "'producto' = lo medido; 'producto_principal' = lo que el tanque suele contener.")
                _m = df.dropna(subset=["medido_en"]).groupby("producto_medido", as_index=False)["stock"].sum()
                if not _m.empty:
                    st.markdown(f"#### Stock por material ({_u})")
                    st.bar_chart(_m.sort_values("stock", ascending=False), x="producto_medido", y="stock", use_container_width=True)

            # ---------- CARGAR MEDICIÓN (manual, con timestamp) ----------
            with t_cargar:
                _opt = _tq.apply(lambda r: f"{r['nombre']} · {r['sector']}", axis=1).tolist()
                _selt = st.selectbox("Tanque", _opt, key="tq_sel_c")
                _row = _tq.iloc[_opt.index(_selt)]
                _idt = int(_row["id_tanque"])
                _perm = cat("SELECT p.codigo_producto FROM produccion.dim_tanque_producto tp "
                            "JOIN produccion.dim_producto p ON p.id_producto=tp.id_producto "
                            "WHERE tp.id_tanque=%s ORDER BY tp.es_principal DESC, p.codigo_producto", (_idt,))
                _plist = _perm["codigo_producto"].tolist() or _prods["codigo_producto"].tolist()
                _ppal = _prods[_prods["id_producto"] == _row["id_producto_principal"]]["codigo_producto"].tolist()
                _defp = _ppal[0] if (_ppal and _ppal[0] in _plist) else _plist[0]
                c1, c2, c3 = st.columns(3)
                _pcod = c1.selectbox("Producto medido", _plist, index=_plist.index(_defp), key="tq_prod_c")
                _modo = c2.radio("Unidad", ["Litros", "Kg"], horizontal=True, key="tq_modo_c")
                _dens = float(_prods[_prods["codigo_producto"] == _pcod]["dens"].iloc[0])
                if _modo == "Litros":
                    _lts = c3.number_input("Litros medidos", 0.0, 5_000_000.0, step=100.0, value=0.0, key="tq_lts_c")
                    _kg = _lts * _dens
                else:
                    _kg = c3.number_input("Kg medidos", 0.0, 5_000_000.0, step=100.0, value=0.0, key="tq_kg_c")
                    _lts = (_kg / _dens) if _dens else None
                cf, ch = st.columns(2)
                _fch = cf.date_input("Fecha medición", date.today(), key="tq_fch_c")
                _hr = ch.time_input("Hora medición", key="tq_hr_c")
                from datetime import datetime as _dtq
                _medido = _dtq.combine(_fch, _hr)
                _obs = st.text_input("Observaciones", max_chars=200, key="tq_obs_c")
                st.caption(f"= {(_kg or 0)/1000:,.2f} TN · {(_lts or 0):,.0f} L · densidad {_dens:g} kg/L")
                _ult = cat("SELECT medido_en, kg FROM produccion.fact_stock_tanque WHERE id_tanque=%s ORDER BY medido_en DESC LIMIT 1", (_idt,))
                if not _ult.empty:
                    _ru = _ult.iloc[0]
                    st.caption(f"Última medición previa: {_ru['medido_en']} · {(_ru['kg'] or 0)/1000:,.2f} TN")
                if st.button("Guardar medición", type="primary", use_container_width=True, key="tq_save_c"):
                    if (_kg or 0) <= 0:
                        st.error("Cargá una cantidad mayor a 0.")
                    else:
                        try:
                            with conectar(USR["id_usuario"]) as (conn, audit):
                                with conn.cursor() as cur:
                                    cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto=%s", (_pcod,))
                                    _pid = cur.fetchone()[0]
                                    cur.execute("INSERT INTO produccion.fact_stock_tanque "
                                                "(id_tanque,id_producto,medido_en,litros,kg,id_usuario,observaciones) "
                                                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                                (_idt, _pid, _medido.isoformat(),
                                                 (float(_lts) if _lts else None), float(_kg),
                                                 int(USR["id_usuario"]), _obs or None))
                                audit.log("I", "fact_stock_tanque", _idt, {"producto": _pcod, "kg": float(_kg)})
                            st.success(f"Medición guardada: {_row['nombre']} · {_pcod} · {_kg/1000:,.2f} TN.")
                            cat.clear()
                        except Exception as e:
                            st.exception(e)

            # ---------- EDITAR TANQUE (contenido / capacidad / productos) ----------
            with t_editar:
                if USR["rol"] not in ("SUPERVISOR", "ADMIN"):
                    st.info("Solo supervisor o admin pueden editar tanques.")
                else:
                    _o2 = _tq.apply(lambda r: f"{r['nombre']} · {r['sector']}", axis=1).tolist()
                    _s2 = st.selectbox("Tanque a editar", _o2, key="tq_sel_e")
                    _r2 = _tq.iloc[_o2.index(_s2)]
                    _idt2 = int(_r2["id_tanque"])
                    _codes = _prods["codigo_producto"].tolist()
                    _pp2 = _prods[_prods["id_producto"] == _r2["id_producto_principal"]]["codigo_producto"].tolist()
                    ce1, ce2 = st.columns(2)
                    _ppal_sel = ce1.selectbox("Producto que contiene (principal)", ["(sin asignar)"] + _codes,
                                              index=(_codes.index(_pp2[0]) + 1 if _pp2 else 0), key="tq_ppal_e")
                    _cap = ce2.number_input("Capacidad (litros)", 0.0, 5_000_000.0, step=100.0,
                                            value=float(_r2["capacidad_litros"]) if pd.notna(_r2["capacidad_litros"]) else 0.0, key="tq_cap_e")
                    _curp = cat("SELECT p.codigo_producto FROM produccion.dim_tanque_producto tp "
                                "JOIN produccion.dim_producto p ON p.id_producto=tp.id_producto WHERE tp.id_tanque=%s", (_idt2,))["codigo_producto"].tolist()
                    _puede = st.multiselect("Productos que puede almacenar", _codes, default=_curp, key="tq_puede_e")
                    _act = st.checkbox("Tanque activo (en uso)", value=bool(_r2["activo"]), key="tq_act_e")
                    if st.button("Guardar tanque", type="primary", use_container_width=True, key="tq_save_e"):
                        try:
                            with conectar(USR["id_usuario"]) as (conn, audit):
                                with conn.cursor() as cur:
                                    _pidp = None
                                    if _ppal_sel != "(sin asignar)":
                                        cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto=%s", (_ppal_sel,))
                                        _pidp = cur.fetchone()[0]
                                    cur.execute("UPDATE produccion.dim_tanque SET id_producto_principal=%s, capacidad_litros=%s, activo=%s WHERE id_tanque=%s",
                                                (_pidp, (float(_cap) if _cap else None), bool(_act), _idt2))
                                    cur.execute("DELETE FROM produccion.dim_tanque_producto WHERE id_tanque=%s", (_idt2,))
                                    for c in _puede:
                                        cur.execute("INSERT INTO produccion.dim_tanque_producto (id_tanque,id_producto,es_principal) "
                                                    "SELECT %s, id_producto, %s FROM produccion.dim_producto WHERE codigo_producto=%s "
                                                    "ON CONFLICT (id_tanque,id_producto) DO NOTHING",
                                                    (_idt2, (c == _ppal_sel), c))
                                audit.log("U", "dim_tanque", _idt2, {"principal": _ppal_sel, "puede": len(_puede)})
                            st.success("Tanque actualizado.")
                            cat.clear(); st.rerun()
                        except Exception as e:
                            st.exception(e)

    elif st.session_state.section == "ADMIN":
        # =================== ADMIN ===================
        st.title("⚙️ Gestion de usuarios")
        if USR["rol"] != "ADMIN":
            st.error("Solo ADMIN puede entrar a esta seccion.")
        else:
            with st.expander("➕ Crear nuevo usuario", expanded=False):
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
                    if st.button("✅ Reactivar usuario", key=f"act_{u_id}", use_container_width=True):
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

    elif st.session_state.section == "CHAT":
        # =================== CONSULTAS IA (chat, solo lectura) ===================
        # Import lazy y aislado: si el módulo chat o sus deps fallan, el resto
        # de la app no se ve afectado.
        try:
            from chat import render as _render_chat
            _render_chat(USR)
        except Exception as _e:
            st.error(f"No se pudo cargar Consultas IA: {_e}")

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
    sub_nueva, sub_edit, sub_pfinal, sub_eval, sub_gasto, sub_etapas, sub_evins = st.tabs(["➕ Nueva carga", "✏️ Avanzar etapa", "\U0001f3c1 Acopio final", "\U0001f9ea Evaluación interna", "⚠️ Gasto extraordinario", "\U0001f6e0️ Etapas/tiempos", "\U0001f9f4 Evaluar insumo"])

    # ---------- SUB-TAB: NUEVA CARGA ----------
    with sub_nueva:
        c1, c2, c3 = st.columns(3)
        fecha_b = c1.date_input("Fecha *", date.today(), max_value=date.today(), key="b_f")
        sector_codigos = sectores["codigo"].tolist()
        sector_idx = sector_codigos.index(USR["sector"]) if USR.get("sector") and USR["sector"] in sector_codigos else 0
        sector = c2.selectbox(
            "Sector *", sector_codigos, key="b_s", index=sector_idx,
            format_func=lambda c: sectores[sectores["codigo"]==c].iloc[0]["nombre_ui"]
        )
        turno = c3.selectbox("Turno", turnos["codigo"], key="b_t")

        # Modo de operación LIMITADO por reglas del sector
        permite_norm, permite_recup = modos_permitidos(sector)
        modos = ([ "NORMAL"] if permite_norm else []) + (["RECUPERACION"] if permite_recup else [])
        if not modos:
            modos = ["NORMAL"]
        _fmt_modo = lambda x: "🏭 Normal (consume MP)" if x == "NORMAL" else "♻️ Recuperación (sin MP)"
        if len(modos) == 1:
            tipo_op = modos[0]
            st.caption(f"Modo: **{_fmt_modo(tipo_op)}** (único permitido para {sector})")
        else:
            tipo_op = st.radio("Tipo de operación", modos, format_func=_fmt_modo, horizontal=True, key="b_tipo")
        es_recup = (tipo_op == "RECUPERACION")
        if es_recup:
            st.info("Modo recuperación: no se carga materia prima.")

        es_reactor = (sector == "REACTORES")
        # REACTORES y BACHAS se cargan en LITROS (kg derivado por densidad).
        usa_litros = sector in ("REACTORES", "BACHAS")
        ver_kg = False
        if usa_litros:
            ver_kg = st.toggle("⚖️ Mostrar también el equivalente en kg", value=False, key="b_ver_kg",
                               help="Cargás en litros; activá esto para ver el mismo número convertido a kg (litros × densidad).")
        productos_mp, productos_obt = productos_de_sector(sector)
        if (not es_recup) and productos_mp.empty:
            st.warning(f"⚠️ No hay productos de tipo MP marcados para el sector {sector}. Revisá `dim_producto.usa_*` en Supabase.")

        label_id = {
            "BACHAS":       "N° de bacha *",
            "RECUPERACION": "N° de pileta *",
            "REACTORES":    "N° de ticket *",
            "EXPO":         "N° de ticket *",
        }.get(sector, "Identificador")
        identificador = st.text_input(label_id, max_chars=20, key="b_id",
                                      placeholder="ej. T-2026-04-001 / B-12 / P-3")

        # Corriente (Vegetal/Animal) — se define al inicio del armado. Obligatoria en REACTORES/BACHAS.
        corriente_v = None
        if sector in ("REACTORES", "BACHAS"):
            corriente_v = st.radio(
                "Corriente *", ["VEGETAL", "ANIMAL"], horizontal=True, key="b_corriente",
                format_func=lambda c: "🌱 Vegetal" if c == "VEGETAL" else "🐄 Animal",
                help="Origen del material. Define si la producción es vegetal o animal."
            )

        # Bloque REACTORES
        id_bien_sel = None
        tipo_proceso_sel = None
        etapa_sel = None
        inicio_dt = None
        fin_dt = None
        tiempo_est = None
        acidez_oleico_v = None; glicerol_v = None
        azufre_ppm_v = None; pct_agua_ini_v = None; temp_ini_v = None
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
            # Una carga nueva SIEMPRE arranca en ARMADO; las demás etapas se avanzan en "Avanzar etapa".
            _et_proc = etapas_de_proceso(proceso_key_de(sector, tipo_proceso_sel))
            _et_codes = _et_proc["etapa"].tolist()
            etapa_sel = "ARMADO" if "ARMADO" in _et_codes else (_et_codes[0] if _et_codes else "ARMADO")
            cR3.text_input("Etapa actual *", value="ARMADO (mezcla de insumos)", disabled=True, key="b_etapa_disp")

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
            gli_ticket_sel = None         # ticket de la muestra GLICERINA elegida (lab)
            if tipo_proceso_sel == "PRODUCCION_ARE":
                PMa   = K("PMa", 282)
                PMg   = K("PMg", 92)
                FE    = K("factor_exceso_gli", 1.1)
                D_GLI = K("densidad_glicerina", 1.25)
                cap_l = float(fila_bien["capacidad_max_l"] or 0)
                # Densidades por MP desde dim_producto (AG-C=0.92, SEBO=0.91)
                _d_ag   = densidad_de("AG-C") or 0.92
                _d_sebo = densidad_de("SEBO-A-1RA") or 0.91
                _kg_max_ag   = cap_l * _d_ag
                _kg_max_sebo = cap_l * _d_sebo

                with st.expander("📐 Fórmulas de carga y capacidad (referencia)", expanded=False):
                    st.code(
                        "Q_glicerina (kg) = Q_AG × (acidez/100) × (PMg / (PMa × 2)) × (1 / (glicerol/100)) × factor_exceso\n"
                        f"                 = Q_AG × (acidez/100) × ({PMg}/({PMa}×2)) × (1/(glicerol/100)) × {FE}\n\n"
                        f"NaOH (kg)        = (Q_AG / 1000) × {fila_bien['consumo_naoh_kg_x_tn']} kg/TN\n"
                        f"Potasio (kg)     = (Q_AG / 1000) × {fila_bien['consumo_potasio_kg_x_tn']} kg/TN\n"
                        f"Fuel (kg)        = (Q_AG / 1000) × {fila_bien['consumo_fuel_kg_x_tn']} kg/TN",
                        language="text"
                    )
                    st.caption(
                        f"🛢️ Capacidad del reactor: **{int(cap_l):,} L** → "
                        f"hasta **{int(_kg_max_ag):,} kg de AG** (dens {_d_ag} kg/L) "
                        f"o **{int(_kg_max_sebo):,} kg de SEBO** (dens {_d_sebo} kg/L). "
                        "El Q AG se asume = capacidad × densidad del MP elegido (se recalcula tras seleccionar el MP)."
                    )

                # Muestras de GLICERINA (últimas 3) → el % glicerol sale del lab
                _df_gli = ultimas_muestras_glicerina(3)
                st.markdown("**Glicerina (lab)** — el % glicerol viene de la muestra elegida")
                if not _df_gli.empty:
                    _opts_gli = _df_gli.apply(
                        lambda r: f"ticket {r['ticket']} · {r['fecha']} · glicerol {float(r['gli_glicerol'])*100:.2f}%",
                        axis=1,
                    ).tolist()
                    _sel_gli = st.selectbox(
                        "Muestra de laboratorio",
                        _opts_gli,
                        index=0,
                        key="b_gli_lab_sel",
                        help="Las últimas 3 muestras analizadas del producto GLICERINA. La más reciente queda preseleccionada.",
                    )
                    _row_gli = _df_gli.iloc[_opts_gli.index(_sel_gli)]
                    glicerol_v = float(_row_gli["gli_glicerol"]) * 100   # → %
                    gli_ticket_sel = str(_row_gli["ticket"])
                    _cg1, _cg2, _cg3 = st.columns(3)
                    _cg1.metric("% Glicerol",      f"{glicerol_v:.2f}%")
                    _cg2.metric("% Humedad",       f"{float(_row_gli['gli_humedad'])*100:.2f}%" if pd.notna(_row_gli['gli_humedad']) else "—")
                    _cg3.metric("% A y S",         f"{float(_row_gli['gli_ays'])*100:.3f}%"     if pd.notna(_row_gli['gli_ays'])     else "—")
                    st.caption(f"Muestra del **{_row_gli['fecha']}** · analista {_row_gli['empleado'] or '—'} · calidad **{_row_gli['calidad_final_lab'] or '—'}**.")
                else:
                    st.warning("No hay muestras de GLICERINA con `gli_glicerol` en procesos_lab. Cargá una desde laboratorio.")
                    glicerol_v = None

                st.markdown("**Inputs operativos**")
                cF1, cF2 = st.columns(2)
                temp_ini_v       = cF1.number_input("Temperatura inicial (C)", 0.0, 300.0, step=1.0, value=0.0, key="b_tini_are")
                catalizador_tipo = cF2.radio(
                    "Catalizador a usar",
                    options=["NAOH","POTASIO"],
                    index=1,  # default Potasio (KOH)
                    format_func=lambda x: "🧪 Soda cáustica (NaOH)" if x=="NAOH" else "🧪 Potasio (KOH)",
                    horizontal=True, key="b_catalizador",
                )
                # q_ag_kg_ref se calculará después del bloque MP (necesita el producto inicial elegido).
                q_ag_kg_ref = 0
                st.caption("ℹ️ Acidez/% agua/azufre/sedimentos/fósforo/densidad vienen del laboratorio de los tickets de MP (abajo). Q AG = capacidad reactor × densidad del MP seleccionado.")

            # Estimación específica DESGOMADO_ACUOSO (fuel + horas por TN AFE-S generado)
            if tipo_proceso_sel == "DESGOMADO_ACUOSO":
                _merma_esp = K("desgomado_merma_pct_esperada", 5) or 5
                _pa_des = K("desgomado_pct_agua", 5) or 5
                _t_des = K("desgomado_temp_c", 85) or 85
                st.markdown("**Desgomado acuoso** — se calcula sobre el AFE-SG cargado más abajo (en kg)")
                st.caption(
                    f"Merma esperada ~{_merma_esp:g}% · agua de proceso {_pa_des:g}% del AFE-SG · "
                    f"calentar a ~{_t_des:g} C · el fuel oil es estimado por fórmula (no se carga). "
                    "Las TN reales de AFE-S se confirman al cerrar (Acopio final)."
                )

            st.markdown("**Horario de inicio**")
            cH1, cH2 = st.columns(2)
            f_ini = cH1.date_input("Fecha inicio", date.today(), key="b_fini")
            h_ini = cH2.time_input("Hora inicio",  key="b_hini")
            from datetime import datetime as _dt
            inicio_dt = _dt.combine(f_ini, h_ini)
            fin_dt    = None
            tiempo_est = None
            st.caption("El fin y la duración se cargan al cerrar (Avanzar etapa / Acopio final).")

        elif sector == "BACHAS":
            # BACHAS también usa el flujo de etapas: la carga arranca en ARMADO.
            etapa_sel = "ARMADO"
            st.markdown("**Etapa + inicio**")
            cBe1, cBe2, cBe3 = st.columns(3)
            cBe1.text_input("Etapa actual *", value="ARMADO (carga de borra + mezcla)", disabled=True, key="b_etapa_disp_b")
            f_ini = cBe2.date_input("Fecha inicio", date.today(), key="b_fini")
            h_ini = cBe3.time_input("Hora inicio", key="b_hini")
            from datetime import datetime as _dtb
            inicio_dt = _dtb.combine(f_ini, h_ini)
            st.caption("ℹ️ Avanzás las etapas (calentamiento → decantación → tanque) desde **Avanzar etapa**.")

        # Producto obtenido / kg / calidad
        # En REACTORES: solo se completan al llegar a EN_TANQUE. En otros sectores: ahora.
        p_obt = None
        kg_obt = 0.0
        litros_obt = None
        litros_ini = None
        ticket_porteria_v = None
        calidad_b = ""
        rmin = rmax = None
        fuera_rango = False
        p_buscado = None
        calidad_buscada = ""
        if es_reactor:
            st.markdown("**Producto buscado (target)** — lo que se quiere obtener con la reacción")
            opt_obj = productos_obt["codigo_producto"].tolist()
            if tipo_proceso_sel == "DESGOMADO_ACUOSO":
                # Flujo fijo AFE-SG -> AFE-S. AFE es calidad ÚNICA (no A/B/C).
                p_buscado = "AFE-S"
                calidad_buscada = "UNICA"
                st.text_input("Producto buscado *", value="AFE-S (calidad única)", disabled=True, key="b_pbusc_des")
                st.caption("DESGOMADO_ACUOSO va siempre de AFE-SG -> AFE-S. El AFE es de calidad única.")
            elif tipo_proceso_sel == "PRODUCCION_ARE":
                # Producto = ARE. La calidad la define el operario (A/B). El "animal" lo define la CORRIENTE.
                cTG1, cTG2 = st.columns(2)
                cTG1.text_input("Producto buscado *", value="ARE", disabled=True, key="b_pbusc_disp")
                if corriente_v == "ANIMAL":
                    cTG2.text_input("Calidad buscada *", value="A · animal", disabled=True, key="b_calbusc_are_an")
                    p_buscado = "ARE-A-ANIMAL"
                    calidad_buscada = "A"
                    st.caption("PRODUCCIÓN ARE corriente ANIMAL -> se busca ARE-A-ANIMAL (calidad A).")
                else:
                    _cal_sel = cTG2.selectbox("Calidad buscada *", ["A", "B"], key="b_calbusc_are")
                    p_buscado = f"ARE-{_cal_sel}"
                    calidad_buscada = _cal_sel
                    st.caption(f"PRODUCCIÓN ARE (vegetal): producto ARE, calidad {_cal_sel} -> {p_buscado}.")
            else:
                cTG1, cTG2 = st.columns(2)
                p_buscado = cTG1.selectbox(
                    "Producto buscado *", opt_obj, index=0, key="b_pbusc_sel",
                    format_func=lambda c: f"{c} {'⭐' if productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL' else ''}"
                )
                calidad_buscada = cTG2.selectbox("Calidad buscada *", calidades["codigo"].tolist(), key="b_calbusc_sel")
            st.caption("ℹ️ El producto **obtenido real** y su calidad se cargan al cerrar la reacción en la etapa EN_TANQUE.")
        elif sector == "BACHAS":
            st.markdown("**Producto buscado (target)** — qué se espera obtener (el real va en 'Producto final')")
            _permb = productos_permitidos(sector, None, tipo_op, "FINAL")
            opt_b = productos_obt["codigo_producto"].tolist()
            if _permb is not None:
                opt_b = [c for c in opt_b if c in _permb] or _permb
            cBb1, cBb2 = st.columns(2)
            p_buscado = cBb1.selectbox("Producto buscado *", opt_b, key="b_pbusc")
            calidad_buscada = cBb2.selectbox("Calidad buscada", [""] + calidades["codigo"].tolist(), key="b_calbusc")
            st.caption("ℹ️ El producto final real (cuánto se obtuvo + a qué tanque) se carga al cerrar, en la pestaña **Producto final**.")
        else:
            st.markdown("**Producto obtenido**")
            cOB1, cOB2 = st.columns(2)
            opciones_obt = productos_obt["codigo_producto"].tolist()
            # Restringir según reglas (dic_proceso_producto · rol FINAL).
            # Ej. RECUPERACION: solo AG-* y EMULSION; nunca AFE-*.
            _perm_obt = productos_permitidos(sector, tipo_proceso_sel, tipo_op, "FINAL",
                                             universo=opciones_obt)
            if _perm_obt is not None:
                opciones_obt = _perm_obt
            if not opciones_obt:
                st.error("No hay productos permitidos para este sector/modo. Revisá `dic_proceso_producto`.")
                opciones_obt = [""]
            p_obt = cOB1.selectbox(
                "Producto obtenido *", opciones_obt, key="b_po",
                format_func=lambda c: f"{c} {'⭐' if (not productos_obt[productos_obt['codigo_producto']==c].empty and productos_obt[productos_obt['codigo_producto']==c].iloc[0]['tipo_producto']=='FINAL') else ''}"
            )
            if usa_litros:
                _dens_o = densidad_de(p_obt)
                litros_obt = cOB2.number_input("Litros obtenido *", min_value=0, max_value=2_000_000, step=100, value=0, key="b_lo")
                kg_obt = (litros_obt or 0) * _dens_o
                if ver_kg:
                    cOB2.caption(f"⚖️ = {kg_obt:,.0f} kg  ·  {kg_obt/1000:,.2f} TN  (densidad {_dens_o:g} kg/L)")
                else:
                    cOB2.caption(f"densidad {_dens_o:g} kg/L → {kg_obt/1000:,.2f} TN")
            else:
                kg_obt = cOB2.number_input("Kg obtenido *", min_value=0, max_value=1_000_000, step=100, value=0, key="b_ko")
            _fp = productos_obt[productos_obt["codigo_producto"] == p_obt]
            rmin = rmax = None
            if not _fp.empty:
                rmin, rmax = _fp.iloc[0]["rango_kg_min"], _fp.iloc[0]["rango_kg_max"]
            if pd.notna(rmin) and pd.notna(rmax):
                if es_recup:
                    # En recuperación lo extraído varía mucho → rango mucho más permisivo.
                    # Factor editable en Supabase: dic_constante_proceso.recup_rango_factor
                    _f = K("recup_rango_factor", 4.0) or 4.0
                    rmin, rmax = rmin / _f, rmax * _f
                    st.caption(f"\U0001f4cf Rango recuperación (permisivo ×{_f:g}): {int(rmin):,} – {int(rmax):,} kg")
                else:
                    st.caption(f"\U0001f4cf Rango habitual: {int(rmin):,} – {int(rmax):,} kg")
            if pd.notna(rmin) and pd.notna(rmax) and kg_obt > 0:
                fuera_rango = bool((kg_obt < rmin) or (kg_obt > rmax))
            calidad_b = st.selectbox("Calidad final", [""] + calidades["codigo"].tolist(), key="b_cal")

            # Consumos recomendados por sector (ej. BACHAS: fuel 30/TN, cloruro_sodio 2/TN)
            cs = consumo_sector[consumo_sector["sector"]==sector]
            if not cs.empty and kg_obt > 0:
                tn_obt = kg_obt / 1000.0
                st.markdown("**🧮 Consumos estimados (por TN producida)**")
                ccols = st.columns(len(cs))
                for j, (_, cr) in enumerate(cs.iterrows()):
                    desc = insumos_cat[insumos_cat["codigo"]==cr["codigo_insumo"]]
                    nom = desc.iloc[0]["descripcion"] if not desc.empty else cr["codigo_insumo"]
                    est = tn_obt * float(cr["consumo_por_tn"])
                    ccols[j].metric(f"{nom}", f"{est:,.1f} {cr['unidad_consumo']}",
                                    f"{cr['consumo_por_tn']:g} {cr['unidad_consumo']}/TN")

        # ============================================================
        # Materia prima
        # REACTORES y BACHAS → tickets de portería + parámetros desde
        # laboratorio (promedio ponderado por kg). Para el resto de los
        # sectores se mantiene el flujo manual (litros / kg / etc).
        # ============================================================
        mps_ingresadas = []
        _tickets_entrada_des = None   # tickets de portería (string) para auditar
        _lab_avg_mp0 = {}             # promedios ponderados del primer MP

        if not es_recup:
            st.markdown("**Materia prima** — se carga en el **ARMADO** (en el resto de las etapas no se agrega MP ni insumos)")
            opts_mp = productos_mp["codigo_producto"].tolist()
            _perm_mp = productos_permitidos(sector, tipo_proceso_sel, tipo_op, "MP")
            if _perm_mp is not None:
                opts_mp = [c for c in productos["codigo_producto"].tolist() if c in _perm_mp]

            usa_tickets_lab = sector in ("REACTORES", "BACHAS")
            es_are_mp = (sector == "REACTORES" and tipo_proceso_sel == "PRODUCCION_ARE")

            if es_are_mp:
                # PRODUCCION_ARE: MP NO se pesa. Es AG-C o SEBO; los kg se asumen =
                # capacidad reactor × densidad. La acidez sale del último análisis del lab.
                _opts_are_mp = [c for c in opts_mp if c == "AG-C" or str(c).startswith("SEBO-")] or ["AG-C"]
                cod = st.selectbox(
                    "Producto inicial (AG-C o SEBO) *",
                    _opts_are_mp,
                    index=(_opts_are_mp.index("AG-C") if "AG-C" in _opts_are_mp else 0),
                    key="b_pi_are_select",
                )
                _dens_mp = densidad_de(cod) or (0.92 if cod == "AG-C" else 0.91)
                _cap_l = float(fila_bien["capacidad_max_l"] or 0)
                _kg_planeado = _cap_l * _dens_mp
                mps_ingresadas.append((cod, float(_kg_planeado)))
                litros_ini = round(_kg_planeado / _dens_mp, 1) if _dens_mp else None
                # Métricas
                _aM1, _aM2, _aM3 = st.columns(3)
                _aM1.metric("Capacidad reactor", f"{int(_cap_l):,} L")
                _aM2.metric(f"Densidad {cod}",    f"{_dens_mp:.2f} kg/L")
                _aM3.metric("Q MP a procesar",   f"{_kg_planeado:,.0f} kg", f"{_kg_planeado/1000:,.2f} TN")
                st.caption("ℹ️ El MP NO se pesa; se asume reactor lleno (capacidad × densidad). Los insumos (glicerina, NaOH/Potasio, fuel) se calculan automáticamente por fórmula.")
                # Acidez/azufre/agua: último análisis del producto MP en procesos_lab
                _df_mp_lab = ultimas_muestras_mp(cod, n=3)
                if not _df_mp_lab.empty:
                    _opts_lab = _df_mp_lab.apply(
                        lambda r: f"ticket {r['ticket']} · {r['fecha']} · acidez {float(r['prc_acidez'])*100:.3f}%" if pd.notna(r['prc_acidez']) else f"ticket {r['ticket']} · {r['fecha']}",
                        axis=1,
                    ).tolist()
                    _sel_mp = st.selectbox(
                        f"Análisis de laboratorio del {cod} (últimas 3 muestras)",
                        _opts_lab, index=0, key="b_are_mp_lab_sel",
                        help="La más reciente queda preseleccionada. El acidez de esta muestra alimenta la fórmula de glicerina.",
                    )
                    _row_mp = _df_mp_lab.iloc[_opts_lab.index(_sel_mp)]
                    # Promedio ponderado degenera en valor único (1 ticket); usamos el avg dict de la API existente.
                    _lab_avg_mp0 = {}
                    for _col in ("prc_acidez", "prc_agua", "prc_sedimentos", "prc_producto",
                                 "ppm_azufre", "ppm_fosforo", "densidad__g_ml"):
                        _val = _row_mp.get(_col)
                        if pd.notna(_val):
                            _lab_avg_mp0[_col] = float(_val)
                    _bm1, _bm2, _bm3 = st.columns(3)
                    _bm1.metric("Acidez (lab)",   f"{float(_row_mp['prc_acidez'])*100:.3f}%"     if pd.notna(_row_mp['prc_acidez'])    else "—")
                    _bm2.metric("% Agua (lab)",   f"{float(_row_mp['prc_agua'])*100:.3f}%"       if pd.notna(_row_mp['prc_agua'])      else "—")
                    _bm3.metric("Densidad (lab)", f"{float(_row_mp['densidad__g_ml']):.3f} g/ml" if pd.notna(_row_mp['densidad__g_ml']) else "—")
                else:
                    st.warning(f"No hay análisis de laboratorio recientes para **{cod}**. La fórmula de glicerina no podrá calcularse hasta que cargues uno.")
            elif usa_tickets_lab:
                # Opciones según proceso/sector
                if sector == "REACTORES" and tipo_proceso_sel == "DESGOMADO_ACUOSO":
                    _opts_mp_tl = ["AFE-SG"]
                    _multi_mp = False
                elif sector == "BACHAS":
                    _opts_mp_tl = [c for c in opts_mp if str(c).startswith("BORRA")] or opts_mp or ["BORRA-A"]
                    _multi_mp = True
                else:
                    _opts_mp_tl = opts_mp
                    _multi_mp = False

                n_mp = 1
                if _multi_mp:
                    n_mp = int(st.number_input("Cantidad de materias primas", 1, 5, value=1, key="b_n_mp"))

                # DESGOMADO: AFE-SG con multiselect (todo se pesa y se mide en lab → tickets reales)
                # BACHAS: text input (las MP pueden venir de stock interno sin portería)
                _usa_multiselect_mp = (sector == "REACTORES" and tipo_proceso_sel == "DESGOMADO_ACUOSO")
                if _usa_multiselect_mp:
                    st.caption("📥 Elegí los tickets desde el desplegable (ya filtrados por **AFE-SG** con lab cargado). Máximo 3 por proceso. La app suma kg y trae los parámetros del laboratorio.")
                else:
                    st.caption("📥 Ingresá **N° de ticket** de portería (máx 3 por proceso). La app suma kg y trae los parámetros del laboratorio.")

                for i in range(n_mp):
                    with st.container(border=True):
                        st.markdown(f"**MP #{i+1}**")
                        if len(_opts_mp_tl) == 1:
                            cod = _opts_mp_tl[0]
                            st.text_input(f"Producto inicial #{i+1}", value=cod, disabled=True, key=f"b_pi_lab_fx_{i}")
                        else:
                            cod = st.selectbox(f"Producto inicial #{i+1} *", _opts_mp_tl, key=f"b_pi_lab_{i}")
                        if _usa_multiselect_mp:
                            _tkmp = _ui_multiselect_tickets(cod, key_prefix=f"b_tkmp_lab_{i}", dias=180, limit=30, max_tickets=3)
                        else:
                            _tkmp = st.text_input(
                                f"Tickets de portería #{i+1} (n°, coma · máx 3)",
                                key=f"b_tkmp_lab_{i}",
                                placeholder="ej. 5063, 5048, 5028",
                                help="Cada ticket es una pesada en portería. La app suma kg y busca los análisis en procesos_lab. Tope 3 por proceso.",
                            )
                            import re as _re3
                            _nct = len(set(int(x) for x in _re3.findall(r"\d+", _tkmp or "")))
                            if _nct > 3:
                                st.warning(f"⚠️ Cargaste {_nct} tickets; el proceso admite hasta 3.")
                        # Lookup combinado portería + lab (promedio ponderado por kg)
                        _det, _avg, _mlab, _mport, _mapping = params_de_tickets_lab(_tkmp, cod)
                        _kg = float(pd.to_numeric(_det["kg"], errors="coerce").sum()) if (not _det.empty and "kg" in _det.columns) else 0.0
                        if _tkmp and _tkmp.strip():
                            st.caption(f"Total cargado: **{_kg:,.0f} kg · {_kg/1000:,.2f} TN**")
                            _render_tickets_lab_panel(_det, _avg, _mlab, _mport, _mapping, st_container=st)
                        if cod and _kg > 0:
                            mps_ingresadas.append((cod, float(_kg)))
                            if i == 0:
                                _lab_avg_mp0 = _avg or {}
                                _dens0 = densidad_de(cod)
                                litros_ini = round(_kg / _dens0, 1) if (_kg and _dens0) else None
                                _tickets_entrada_des = _tkmp or None
            else:
                # Sectores no-REACTORES/BACHAS: flujo manual original
                permite_multi = (p_obt == "AG-E") or (sector == "EXPO")
                max_mp = 5 if permite_multi else 1
                n_mp = 1 if not permite_multi else st.number_input(
                    "Cantidad de materias primas", 1, max_mp,
                    value=2 if permite_multi else 1, key="b_n_mp"
                )
                for i in range(int(n_mp)):
                    cMP1, cMP2 = st.columns(2)
                    cod = cMP1.selectbox(
                        f"Producto inicial #{i+1} *", opts_mp, index=0,
                        key=f"b_pi_sel_{i}"
                    )
                    if usa_litros:
                        _dens_i = densidad_de(cod)
                        lts_i = cMP2.number_input(f"Litros inicial #{i+1} *", min_value=0, max_value=2_000_000, step=100, value=0, key=f"b_li_{i}")
                        kg = (lts_i or 0) * _dens_i
                        cMP2.caption(f"= {kg:,.0f} kg · {kg/1000:,.2f} TN (dens {_dens_i:g} kg/L)")
                        if i == 0:
                            litros_ini = lts_i or 0
                    else:
                        kg = cMP2.number_input(f"Kg inicial #{i+1} *", min_value=0, max_value=1_000_000, step=100, value=0, key=f"b_ki_{i}")
                        cMP2.caption(f"= {kg/1000:,.2f} TN")
                    if cod and kg > 0:
                        mps_ingresadas.append((cod, float(kg)))

            if mps_ingresadas:
                p_ini, kg_ini = mps_ingresadas[0]
            else:
                p_ini, kg_ini = "", 0.0
        else:
            p_ini, kg_ini = "", 0.0

        # ============================================================
        # Override de parámetros iniciales desde el laboratorio (lab→variables)
        # Solo se aplica si tenemos averages del primer MP (REACTORES/BACHAS).
        # ============================================================
        if _lab_avg_mp0:
            # prc_* del lab están en DECIMAL (0.058 = 5.8%). Las variables que usan las
            # fórmulas y los displays trabajan en % (0-100), así que multiplicamos por 100.
            if _lab_avg_mp0.get("prc_acidez") is not None:
                acidez_oleico_v = float(_lab_avg_mp0["prc_acidez"]) * 100
            if _lab_avg_mp0.get("ppm_azufre") is not None:
                azufre_ppm_v = float(_lab_avg_mp0["ppm_azufre"])  # ppm queda igual
            if _lab_avg_mp0.get("prc_agua") is not None:
                pct_agua_ini_v = float(_lab_avg_mp0["prc_agua"]) * 100
            _bits_lab = []
            if acidez_oleico_v is not None: _bits_lab.append(f"acidez **{acidez_oleico_v:.3f}%**")
            if pct_agua_ini_v is not None:  _bits_lab.append(f"agua **{pct_agua_ini_v:.3f}%**")
            if azufre_ppm_v is not None:    _bits_lab.append(f"azufre **{azufre_ppm_v:.1f} ppm**")
            if _bits_lab:
                st.success("🧪 Parámetros iniciales tomados del laboratorio (promedio ponderado por kg): " + " · ".join(_bits_lab))

        # ============================================================
        # Q AG planeado: capacidad del reactor × densidad del MP elegido
        # (asume que se usa el reactor a su máxima capacidad).
        # Aplica solo a PRODUCCION_ARE. Las métricas ya las mostró el bloque
        # MP arriba; acá solo dejamos la variable lista para la fórmula.
        # ============================================================
        if es_reactor and tipo_proceso_sel == "PRODUCCION_ARE" and p_ini:
            try:
                _cap = float(fila_bien["capacidad_max_l"] or 0)
                _dens_mp = densidad_de(p_ini) or 0.92
                q_ag_kg_ref = float(_cap * _dens_mp)
            except Exception:
                pass

        # ============================================================
        # Estimados ARE (glicerina, NaOH/Potasio, Fuel, ARE estimado)
        # Se renderizan DESPUÉS del bloque MP para que acidez_oleico_v
        # ya esté actualizada desde el laboratorio.
        # ============================================================
        if es_reactor and tipo_proceso_sel == "PRODUCCION_ARE":
            est_glicerol_puro_kg = None
            if q_ag_kg_ref and q_ag_kg_ref > 0 and acidez_oleico_v and acidez_oleico_v > 0 and glicerol_v and glicerol_v > 0:
                est_glicerol_puro_kg = float(q_ag_kg_ref) * (acidez_oleico_v/100) * (PMg/(PMa*2)) * FE
                est_glice_kg = est_glicerol_puro_kg / (glicerol_v/100)
                mas_por_impureza = est_glice_kg - est_glicerol_puro_kg
                tn = float(q_ag_kg_ref) / 1000.0
                rate_naoh    = float(fila_bien["consumo_naoh_kg_x_tn"]    or 0)
                rate_potasio = float(fila_bien["consumo_potasio_kg_x_tn"] or 0)
                rate_fuel    = float(fila_bien["consumo_fuel_kg_x_tn"]    or 0)
                est_naoh_kg    = (tn * rate_naoh)    if catalizador_tipo == "NAOH"    else 0.0
                est_potasio_kg = (tn * rate_potasio) if catalizador_tipo == "POTASIO" else 0.0
                est_fuel_kg    = tn * rate_fuel
                est_are_kg     = float(q_ag_kg_ref)
                st.markdown("**🧮 Insumos estimados a cargar** (usan la acidez del laboratorio)")
                cE1, cE2, cE3, cE4 = st.columns(4)
                cE1.metric("Glicerina a cargar", f"{est_glice_kg:,.0f} kg",
                           f"+{mas_por_impureza:,.0f} kg por pureza {glicerol_v:.0f}%")
                if catalizador_tipo == "NAOH":
                    cE2.metric("NaOH (catalizador)", f"{est_naoh_kg:,.1f} kg",
                               f"alternativa: {tn*rate_potasio:.2f} kg potasio")
                    cE3.metric("Potasio", "—", "no aplica")
                else:
                    cE2.metric("NaOH", "—", "no aplica")
                    cE3.metric("Potasio (catalizador)", f"{est_potasio_kg:,.2f} kg",
                               f"alternativa: {tn*rate_naoh:.1f} kg NaOH")
                cE4.metric("Fuel", f"{est_fuel_kg:,.0f} kg")
                with st.expander("💡 Detalle del cálculo (glicerol y catalizador)", expanded=False):
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
                st.info("Cargá los **tickets de MP** (para acidez) y elegí **% glicerol** y **Q AG** para ver los estimados.")

        # Bachas: ~70% de la borra es agua de descarte → efluentes líquidos.
        # Estimado de producto final (lo no-agua) se calcula acá, en el ARMADO.
        if sector == "BACHAS" and mps_ingresadas:
            _pct_w = K("bachas_pct_agua", 70) or 70
            _kg_in = sum(k for _, k in mps_ingresadas)
            _agua_tn = _kg_in * _pct_w / 100 / 1000
            est_are_kg = _kg_in * (1 - _pct_w/100)   # estimado producto final
            q_ag_kg_ref = _kg_in
            st.info(f"💧 ~{_pct_w:g}% de la borra es agua → **{_agua_tn:,.2f} TN** a efluentes. "
                    f"Producto final **estimado ≈ {est_are_kg/1000:,.2f} TN** (de {_kg_in/1000:,.2f} TN cargadas). "
                    f"El real se carga en 'Producto final'.")

        # Bloque GLICERINA (solo PRODUCCION_ARE)
        # Inputs: kg + % glicerol (fresca y recuperada). L se calcula con densidad.
        gli_fl = gli_fk = gli_rl = gli_rk = None
        gli_fresca_pct = gli_pct = None         # gli_pct = % glicerol recuperada (gli_pct_real)
        gli_pura_total = None
        if tipo_proceso_sel == "PRODUCCION_ARE":
            D_GLI = K("densidad_glicerina", 1.25)
            st.markdown("**Glicerina a cargar** _(% glicerol viene del lab, ticket seleccionado arriba)_")
            # gli_fresca_pct sale del mismo ticket de lab elegido (= glicerol_v)
            gli_fresca_pct = float(glicerol_v) if glicerol_v else 0.0
            cG1, cG2, cG3 = st.columns(3)
            gli_fl = cG1.number_input("Fresca (L)", min_value=0, max_value=100000, step=50, value=0, key="b_glfl")
            cG2.metric("% glicerol fresca (lab)", f"{gli_fresca_pct:.2f}%" if gli_fresca_pct else "—",
                       f"ticket {gli_ticket_sel}" if gli_ticket_sel else None)
            # Con potasio (KOH) NO se genera glicerina recuperada (regla dic_catalizador)
            _genera_recup = catalizador_genera_glicerina(catalizador_tipo) if catalizador_tipo else True
            if _genera_recup:
                gli_rl  = cG3.number_input("Recuperada (L)",    min_value=0, max_value=100000, step=50, value=0, key="b_glrl")
                gli_pct = st.number_input("% glicerol recuperada",
                                          0.0, 100.0, step=0.1, value=80.0, key="b_glpct",
                                          help="La glicerina recuperada de etapas previas suele tener menor pureza; ajustá si conocés el valor real.")
            else:
                gli_rl = 0; gli_pct = 0.0
                cG3.metric("Recuperada", "no aplica", "potasio (KOH) no genera recuperada")

            # kg derivados desde litros (densidad glicerina)
            gli_fk = (gli_fl or 0.0) * D_GLI
            gli_rk = (gli_rl or 0.0) * D_GLI
            glicerol_fresca = gli_fk * (gli_fresca_pct or 0.0) / 100
            glicerol_recup  = gli_rk * (gli_pct or 0.0) / 100
            gli_pura_total = glicerol_fresca + glicerol_recup   # = glicerol total cargado

            cD1, cD2, cD3 = st.columns(3)
            cD1.metric("Fresca (kg calc.)",     f"{gli_fk:,.1f} kg")
            cD2.metric("Recuperada (kg calc.)", f"{gli_rk:,.1f} kg")
            cD3.metric("Glicerol total cargado",
                       f"{gli_pura_total:,.1f} kg",
                       f"fresca {glicerol_fresca:,.0f} + recup {glicerol_recup:,.0f}")
            st.caption(f"Densidad glicerina = {D_GLI} kg/L · kg = L x {D_GLI}. Glicerol = kg x %glicerol.")

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

        # Bloque NaOH (catalizador en PRODUCCION_ARE) — se carga en L o kg; se guardan SIEMPRE ambos.
        naoh_lts_v = naoh_kg_v = None
        if tipo_proceso_sel == "PRODUCCION_ARE" and catalizador_tipo == "NAOH":
            _d_soda = densidad_insumo("soda_kg", 1.33)
            st.markdown("**NaOH (catalizador)** — cargá en litros **o** kg; guardamos los dos")
            cN1, cN2 = st.columns([1, 2])
            _modo_naoh = cN1.radio("Unidad de carga", ["Litros", "Kg"], horizontal=True, key="b_naoh_modo")
            if _modo_naoh == "Litros":
                _def_l = round(float(est_naoh_kg / _d_soda), 1) if (est_naoh_kg and _d_soda) else 0.0
                naoh_lts_v = cN2.number_input("NaOH (L) *", min_value=0.0, max_value=100000.0, step=1.0,
                                              value=_def_l, key="b_naoh_l")
                naoh_kg_v = round((naoh_lts_v or 0.0) * _d_soda, 2)
                cN2.caption(f"⚖️ = **{naoh_kg_v:,.1f} kg** (densidad {_d_soda:g} kg/L)" +
                            (f" · estimado {est_naoh_kg:,.1f} kg" if est_naoh_kg else ""))
            else:
                _def_k = round(float(est_naoh_kg), 1) if est_naoh_kg else 0.0
                naoh_kg_v = cN2.number_input("NaOH (kg) *", min_value=0.0, max_value=100000.0, step=1.0,
                                             value=_def_k, key="b_naoh_k")
                naoh_lts_v = round((naoh_kg_v or 0.0) / _d_soda, 2) if _d_soda else None
                cN2.caption(f"⚖️ = **{naoh_lts_v:,.1f} L** (densidad {_d_soda:g} kg/L)" +
                            (f" · estimado {est_naoh_kg:,.1f} kg" if est_naoh_kg else ""))

        # Bloque AGUA + fuel estimado + ticket (solo DESGOMADO_ACUOSO).
        # Agua de proceso = 5% sobre los kg iniciales de AFE-SG (auto, no input manual).
        agua_lts_v = None
        if tipo_proceso_sel == "DESGOMADO_ACUOSO":
            _pct_agua = K("desgomado_pct_agua", 5) or 5
            _temp = K("desgomado_temp_c", 85) or 85
            _merma_esp = K("desgomado_merma_pct_esperada", 5) or 5
            _kg_afesg = float(kg_ini or 0)
            agua_lts_v = round(_kg_afesg * _pct_agua / 100, 0)  # 5% del AFE-SG (kg agua ≈ L)
            _rf = consumos_proceso[(consumos_proceso["tipo_proceso"] == "DESGOMADO_ACUOSO") &
                                   (consumos_proceso["codigo_insumo"] == "FUEL")]
            _rate_fuel = float(_rf.iloc[0]["consumo_por_tn"]) if not _rf.empty else 8.7
            est_fuel_kg = round((_kg_afesg / 1000.0) * _rate_fuel, 1)        # fuel estimado (L)
            est_are_kg = _kg_afesg * (1 - _merma_esp / 100.0)               # AFE-S esperado (merma esperada)
            q_ag_kg_ref = _kg_afesg
            st.markdown(f"**Agua de proceso + estimados** _(agua = {_pct_agua:g}% sobre AFE-SG, automático)_")
            cAg1, cAg2, cAg3 = st.columns(3)
            cAg1.metric("Agua de proceso (L)", f"{agua_lts_v:,.0f}",
                        f"{_pct_agua:g}% × {_kg_afesg/1000:,.2f} TN AFE-SG")
            cAg2.metric("Fuel oil estimado (L)", f"{est_fuel_kg:,.1f}", "automático · no se carga")
            cAg3.metric("AFE-S esperado", f"{est_are_kg/1000:,.2f} TN", f"merma esp. {_merma_esp:g}%")
            temp_ini_v = st.number_input("Temperatura inicial (C)", 0.0, 300.0, step=1.0, value=float(_temp), key="b_tini_des")
            ticket_porteria_v = _tickets_entrada_des
            if ticket_porteria_v:
                st.caption(f"Peso del AFE-SG calculado desde portería · tickets de entrada: {ticket_porteria_v}")

        # Insumos — los típicos del proceso vienen precargados; se pueden agregar otros.
        st.markdown("**Insumos** — los típicos del proceso ya vienen cargados (ajustá la cantidad). Solo se usan en el **ARMADO**.")
        insumos_dict = {}

        def _desc_ins(c):
            f = insumos_cat[insumos_cat["codigo"] == c]
            return f.iloc[0]["descripcion"] if not f.empty else c
        def _unidad_ins(c):
            f = insumos_cat[insumos_cat["codigo"] == c]
            return f.iloc[0]["unidad"] if not f.empty else ""

        # 1) Insumos TÍPICOS del proceso/sector (FUEL siempre en REACTORES y BACHAS).
        #    Cantidad sugerida = estimado por la fórmula; el operario solo confirma/corrige.
        tipicos = []   # (codigo, cantidad_sugerida, unidad_label)
        if tipo_proceso_sel == "PRODUCCION_ARE":
            tipicos.append(("FUEL", float(est_fuel_kg or 0.0), "kg"))
            if catalizador_tipo == "POTASIO":
                tipicos.append(("POTASIO", float(est_potasio_kg or 0.0), "kg"))
            # NaOH (soda) se carga aparte en su bloque dedicado (L/kg) → no se duplica acá.
        elif tipo_proceso_sel == "DESGOMADO_ACUOSO":
            # Fuel oil es ESTIMADO automático (no se carga a mano) → se guarda solo.
            if est_fuel_kg:
                insumos_dict["fuel_l"] = float(est_fuel_kg)
        elif sector == "BACHAS":
            _base_tn = float(est_are_kg or 0.0) / 1000.0
            for _, _cr in consumo_sector[consumo_sector["sector"] == "BACHAS"].iterrows():
                tipicos.append((_cr["codigo_insumo"], _base_tn * float(_cr["consumo_por_tn"]), _cr["unidad_consumo"]))

        codigos_tipicos = [c for c, _, _ in tipicos]
        if tipicos:
            st.caption("🔧 Insumos típicos de este proceso — sugeridos por la fórmula. Ajustá si hace falta.")
            for c, sug, ulbl in tipicos:
                _u = ulbl or _unidad_ins(c)
                cc1, cc2 = st.columns([2, 1])
                cc1.text_input("Insumo", value=f"{_desc_ins(c)} ({c})", disabled=True, key=f"b_inst_lbl_{c}")
                # La clave incluye el sugerido para que el campo siga el estimado en vivo (si no lo editaron).
                val = cc2.number_input(
                    f"Cantidad ({_u})",
                    min_value=0.0, max_value=1_000_000.0,
                    value=round(float(sug), 2), step=1.0,
                    key=f"b_inst_q_{c}_{round(float(sug),1)}"
                )
                if val and val > 0:
                    insumos_dict[c] = float(val)
                # Submensaje debajo de la celda: estimado por parámetros + desvío en vivo.
                if sug > 0:
                    if val and val > 0:
                        _d = val - sug
                        _dp = (_d / sug * 100) if sug else 0.0
                        _ico = "✅" if abs(_dp) <= 5 else "⚠️"
                        cc2.caption(f"{_ico} estimado **{sug:,.1f} {_u}** · cargás {val:,.1f} ({_dp:+.0f}%)")
                    else:
                        cc2.caption(f"📐 estimado por parámetros: **{sug:,.1f} {_u}**")
                else:
                    cc2.caption("📐 cargá acidez / Q AG / litros para ver el estimado")
        else:
            st.caption("Este proceso no tiene insumos típicos precargados. Agregá los que correspondan abajo.")

        # 2) Insumos EXTRA (no listados arriba) — opción siempre disponible.
        opts_extra = [c for c in insumos_cat["codigo"].tolist() if c not in codigos_tipicos]
        with st.expander("➕ Agregar otro insumo (no listado arriba)", expanded=False):
            n_extra = st.number_input("¿Cuántos insumos extra?", 0, 10, value=0, key="b_n_ins_extra")
            for i in range(int(n_extra)):
                ie1, ie2 = st.columns([2, 1])
                ins_cod = ie1.selectbox(
                    f"Insumo extra #{i+1}", opts_extra, key=f"b_insx_{i}",
                    format_func=lambda c: f"{_desc_ins(c)} ({c})",
                )
                ins_unidad = _unidad_ins(ins_cod)
                ins_cant = ie2.number_input(f"Cantidad ({ins_unidad})", 0.0, 1_000_000.0, key=f"b_cantx_{i}")
                if ins_cod and ins_cant > 0:
                    insumos_dict[ins_cod] = float(ins_cant)

        # Parámetros del proceso → todos vienen del laboratorio (tickets MP) salvo temp inicial (manual).
        # No hay inputs manuales: el resumen de abajo muestra qué se va a subir.
        parametros_dict = {}
        if temp_ini_v and temp_ini_v > 0:
            parametros_dict["temp_inicial_c"] = float(temp_ini_v)
        if azufre_ppm_v and azufre_ppm_v > 0:
            parametros_dict["azufre_ppm"] = float(azufre_ppm_v)
        if pct_agua_ini_v and pct_agua_ini_v > 0:
            parametros_dict["pct_agua_inicial"] = float(pct_agua_ini_v)
        if acidez_oleico_v and acidez_oleico_v > 0:
            parametros_dict.setdefault("acidez", float(acidez_oleico_v))
        # Resto de métricas evaluadas en el laboratorio del primer MP (sedimentos, fósforo, densidad, producto)
        # prc_* se guardan en % (×100); ppm y densidad sin tocar.
        if _lab_avg_mp0:
            if _lab_avg_mp0.get("prc_sedimentos") is not None:
                parametros_dict["sedimentos_pct"] = float(_lab_avg_mp0["prc_sedimentos"]) * 100
            if _lab_avg_mp0.get("ppm_fosforo") is not None:
                parametros_dict["fosforo_ppm"] = float(_lab_avg_mp0["ppm_fosforo"])
            if _lab_avg_mp0.get("densidad__g_ml") is not None:
                parametros_dict["densidad_g_ml"] = float(_lab_avg_mp0["densidad__g_ml"])
            if _lab_avg_mp0.get("prc_producto") is not None:
                parametros_dict["producto_pct"] = float(_lab_avg_mp0["prc_producto"]) * 100

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

        # Plan vs real agrupado como info agregada (colapsado, por si lo quieren ver).
        if tipo_proceso_sel in ("PRODUCCION_ARE", "DESGOMADO_ACUOSO") and (insumos_dict or naoh_kg_v):
            with st.expander("📊 Plan vs real (insumos) — info agregada", expanded=False):
                if tipo_proceso_sel == "PRODUCCION_ARE":
                    real_fuel    = float(insumos_dict.get("FUEL", 0.0) or 0)
                    real_naoh    = float(naoh_kg_v or 0)   # del bloque NaOH dedicado (kg)
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
                elif tipo_proceso_sel == "DESGOMADO_ACUOSO":
                    real_fuel = float(insumos_dict.get("FUEL", 0.0) or 0)
                    # est_fuel_kg para DESGOMADO se computó en L (8.7 L/TN)
                    _alarma_consumo("Fuel", real_fuel, est_fuel_kg, unidad="L")

        motivo_rango = ""
        if fuera_rango:
            st.warning(f"⚠️ {kg_obt:,.0f} kg fuera del rango ({int(rmin):,}–{int(rmax):,}).")
            motivo_rango = st.text_input("Motivo fuera de rango * (≥5 chars)", max_chars=200, key="b_motivo_rng")

        obs = st.text_input("Observaciones", max_chars=200, key="b_obs")

        # Resumen compacto antes de guardar (reduce errores de carga).
        with st.container(border=True):
            st.markdown("**📋 Revisá antes de guardar**")
            _mp_txt = ", ".join(f"{c} {k/1000:,.2f} TN" for c, k in mps_ingresadas) if mps_ingresadas else ("— (recuperación)" if es_recup else "—")
            _obj_txt = (f"{p_buscado or '—'}" + (f" · {calidad_buscada}" if calidad_buscada else "")) \
                       if (es_reactor or sector == "BACHAS") else f"{p_obt or '—'} · {kg_obt/1000:,.2f} TN"
            _ins_txt = ", ".join(f"{k}: {v:g}" for k, v in insumos_dict.items()) if insumos_dict else "—"
            rs1, rs2, rs3 = st.columns(3)
            rs1.caption(f"**Sector / Proceso**\n\n{sectores[sectores['codigo']==sector].iloc[0]['nombre_ui']}"
                        + (f" · {tipo_proceso_sel}" if tipo_proceso_sel else ""))
            rs1.caption(f"**Ticket / ID:** {identificador or '—'}")
            rs2.caption(f"**Materia prima**\n\n{_mp_txt}")
            rs2.caption(f"**Insumos:** {_ins_txt}")
            rs3.caption(f"**Objetivo**\n\n{_obj_txt}")
            if est_are_kg:
                rs3.caption(f"**Estimado final:** {est_are_kg/1000:,.2f} TN")

            # Parámetros que se van a subir (de laboratorio + manual de temp inicial)
            if parametros_dict:
                _pretty_par = {
                    "acidez":            ("Acidez",            "%",   ".3f"),
                    "pct_agua_inicial":  ("% Agua inicial",    "%",   ".3f"),
                    "azufre_ppm":        ("Azufre",            "ppm", ".1f"),
                    "fosforo_ppm":       ("Fósforo",           "ppm", ".1f"),
                    "sedimentos_pct":    ("Sedimentos",        "%",   ".3f"),
                    "densidad_g_ml":     ("Densidad",          "g/ml",".3f"),
                    "producto_pct":      ("Producto",          "%",   ".3f"),
                    "temp_inicial_c":    ("Temperatura inicial","°C", ".1f"),
                }
                st.markdown("**🧪 Parámetros a guardar** _(promedio ponderado del laboratorio)_")
                _items = []
                for _k, _v in parametros_dict.items():
                    _lbl, _u, _fmt = _pretty_par.get(_k, (_k, "", ".3f"))
                    _items.append(f"{_lbl}: **{_v:{_fmt}} {_u}**".rstrip())
                # Distribuye en 3 columnas
                _ncols = 3
                _rcols = st.columns(_ncols)
                for _i, _it in enumerate(_items):
                    _rcols[_i % _ncols].caption(_it)
            else:
                if sector in ("REACTORES", "BACHAS"):
                    st.caption("🧪 _Sin parámetros de laboratorio (cargá tickets de MP para traerlos)._")

        submit_b = st.button("✅ Guardar carga", type="primary", use_container_width=True, key="b_submit")

        if submit_b:
            errs = []
            # REACTORES y BACHAS no cargan producto final al crear (va en 'Producto final')
            if sector not in ("REACTORES", "BACHAS") and kg_obt <= 0:
                errs.append("Kg obtenido > 0.")
            if not es_recup and (not p_ini or kg_ini <= 0):
                errs.append("En NORMAL la materia prima es obligatoria.")
            if fuera_rango and len(motivo_rango.strip()) < 5:
                errs.append("Motivo fuera de rango obligatorio (≥5).")
            if es_reactor and (not tipo_proceso_sel or not etapa_sel):
                errs.append("REACTORES requiere proceso y etapa.")
            if sector in ("REACTORES", "BACHAS") and not corriente_v:
                errs.append("Definí la corriente (Vegetal/Animal).")
            if tipo_proceso_sel == "PRODUCCION_ARE" and catalizador_tipo == "NAOH" and not (naoh_kg_v and naoh_kg_v > 0):
                errs.append("Cargá el NaOH (litros o kg).")
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
                                "  agua_lts, litros_inicial, litros_obtenido, ticket_porteria,"
                                "  observaciones, fuera_de_rango, motivo_fuera_rango,"
                                "  corriente, naoh_lts, naoh_kg"
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
                                "  %s,%s,%s,%s,"
                                "  %s,%s,%s,"
                                "  %s,%s,%s"
                                ") ON CONFLICT (identificador_unidad, tipo_proceso) WHERE (NOT anulado AND identificador_unidad IS NOT NULL) DO UPDATE SET "
                                "  fecha=EXCLUDED.fecha, sector=EXCLUDED.sector, turno=EXCLUDED.turno, tipo_operacion=EXCLUDED.tipo_operacion,"
                                "  id_producto_inicial=EXCLUDED.id_producto_inicial, kg_inicial=EXCLUDED.kg_inicial,"
                                "  id_producto_obtenido=EXCLUDED.id_producto_obtenido, kg_obtenido=EXCLUDED.kg_obtenido,"
                                "  horas_trabajadas=EXCLUDED.horas_trabajadas, calidad_final=EXCLUDED.calidad_final,"
                                "  insumos=EXCLUDED.insumos, materias_primas_extras=EXCLUDED.materias_primas_extras, id_bien_uso=EXCLUDED.id_bien_uso,"
                                "  inicio_ts=EXCLUDED.inicio_ts, fin_ts=EXCLUDED.fin_ts, tiempo_estimado_horas=EXCLUDED.tiempo_estimado_horas,"
                                "  parametros_proceso=EXCLUDED.parametros_proceso, id_producto_buscado=EXCLUDED.id_producto_buscado,"
                                "  calidad_buscada=EXCLUDED.calidad_buscada, catalizador_tipo=EXCLUDED.catalizador_tipo,"
                                "  acidez_oleico_pct=EXCLUDED.acidez_oleico_pct, glicerol_pct=EXCLUDED.glicerol_pct,"
                                "  estimado_glicerina_kg=EXCLUDED.estimado_glicerina_kg, estimado_naoh_kg=EXCLUDED.estimado_naoh_kg,"
                                "  estimado_potasio_kg=EXCLUDED.estimado_potasio_kg, estimado_fuel_kg=EXCLUDED.estimado_fuel_kg,"
                                "  estimado_are_kg=EXCLUDED.estimado_are_kg, q_ag_planeado_kg=EXCLUDED.q_ag_planeado_kg,"
                                "  gli_fresca_lts=EXCLUDED.gli_fresca_lts, gli_fresca_kg=EXCLUDED.gli_fresca_kg, gli_fresca_pct=EXCLUDED.gli_fresca_pct,"
                                "  gli_recup_lts=EXCLUDED.gli_recup_lts, gli_recup_kg=EXCLUDED.gli_recup_kg, gli_pct_real=EXCLUDED.gli_pct_real,"
                                "  gli_pura_total_kg=EXCLUDED.gli_pura_total_kg, agua_lts=EXCLUDED.agua_lts,"
                                "  litros_inicial=EXCLUDED.litros_inicial, litros_obtenido=EXCLUDED.litros_obtenido, ticket_porteria=EXCLUDED.ticket_porteria,"
                                "  observaciones=EXCLUDED.observaciones, fuera_de_rango=EXCLUDED.fuera_de_rango, motivo_fuera_rango=EXCLUDED.motivo_fuera_rango,"
                                "  corriente=EXCLUDED.corriente, naoh_lts=EXCLUDED.naoh_lts, naoh_kg=EXCLUDED.naoh_kg"
                                " RETURNING id_batch",
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
                                 (float(litros_ini) if litros_ini else None),
                                 (float(litros_obt) if litros_obt else None),
                                 (ticket_porteria_v or None),
                                 obs or None, bool(fuera_rango), motivo_rango or None,
                                 (corriente_v or None),
                                 (float(naoh_lts_v) if naoh_lts_v else None),
                                 (float(naoh_kg_v) if naoh_kg_v else None))
                            )
                            id_b = cur.fetchone()[0]
                            # Primer evento de etapa (abre el ARMADO). NOT EXISTS evita duplicar en re-upsert.
                            if es_reactor and etapa_sel:
                                cur.execute("""
                                    INSERT INTO fact_etapa_evento (id_batch, etapa, inicio_ts, id_usuario)
                                    SELECT %s, %s, COALESCE(%s, NOW()), %s
                                    WHERE NOT EXISTS (SELECT 1 FROM fact_etapa_evento WHERE id_batch=%s AND etapa=%s)
                                """, (id_b, etapa_sel,
                                      inicio_dt.isoformat() if inicio_dt else None,
                                      int(USR["id_usuario"]), id_b, etapa_sel))
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
            WHERE NOT b.anulado AND b.sector IN ('REACTORES','BACHAS')
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        if df_rec.empty:
            st.info("Sin cargas en REACTORES/BACHAS todavía.")
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
            # etapas atadas al proceso de esta reacción (no la lista plana)
            _et_proc_av = etapas_de_proceso(proceso_key_de(r["sector"], r["tipo_proceso"]))
            etapas_codigos = _et_proc_av["etapa"].tolist()
            def _desc_et(c):
                _m = _et_proc_av[_et_proc_av["etapa"]==c]
                return _m.iloc[0]["descripcion"] if not _m.empty else (c or "—")
            etapa_actual_cod = r["etapa_actual"]
            etapa_actual_desc = _desc_et(etapa_actual_cod) if etapa_actual_cod in etapas_codigos else (etapa_actual_cod or "—")
            # target de duración de la etapa actual: 1° la dimensión etapas-por-proceso, 2° dic_etapa_duracion
            tgt_min = None
            _row_tgt = _et_proc_av[_et_proc_av["etapa"]==etapa_actual_cod]
            if (not _row_tgt.empty and "duracion_target_min" in _row_tgt.columns
                    and pd.notna(_row_tgt.iloc[0].get("duracion_target_min"))):
                tgt_min = int(_row_tgt.iloc[0]["duracion_target_min"])
            else:
                dur_tgt = duraciones_etapa[
                    (duraciones_etapa["sector"]=="REACTORES") &
                    (duraciones_etapa["tipo_proceso"]==r["tipo_proceso"]) &
                    (duraciones_etapa["etapa"]==etapa_actual_cod)
                ]
                tgt_min = int(dur_tgt.iloc[0]["duracion_target_min"]) if not dur_tgt.empty else None

            # ---- Stepper visual: hechas / actual / pendientes ----
            _LBL = {"ARMADO": "Armado", "CARGA": "Carga", "REACCION": "Reacción",
                    "CALENTAMIENTO": "Calentamiento", "REPOSANDO": "Reposo",
                    "DECANTACION": "Decantación", "EN_TANQUE": "Acopio final"}
            def _et_lbl(c): return _LBL.get(c, _desc_et(c))
            idx_actual = etapas_codigos.index(etapa_actual_cod) if etapa_actual_cod in etapas_codigos else 0
            _chips = []
            for j, c in enumerate(etapas_codigos):
                if j < idx_actual:    _chips.append(f"✓ {_et_lbl(c)}")
                elif j == idx_actual: _chips.append(f"► **{_et_lbl(c)}**")
                else:                 _chips.append(f"○ {_et_lbl(c)}")
            st.markdown("#### ¿En qué etapa está la reacción?")
            st.markdown("  ·  ".join(_chips))
            idx_nueva = min(idx_actual + 1, len(etapas_codigos) - 1) if etapas_codigos else 0
            _siguiente = _et_lbl(etapas_codigos[idx_nueva]) if etapas_codigos else "—"
            if idx_actual >= len(etapas_codigos) - 1:
                st.info(f"Está en la última etapa (**{_et_lbl(etapa_actual_cod)}**). El cierre real se hace en **Acopio final**.")
            else:
                st.markdown(f"Estás en **{_et_lbl(etapa_actual_cod)}** y vas a pasar a **{_siguiente}**.")

            # ¿Cuánto duró esta etapa? en HORAS + MINUTOS
            _tgt_h, _tgt_m = ((tgt_min or 0) // 60, (tgt_min or 0) % 60)
            cE1, cE2, cE3 = st.columns([1, 1, 1.4])
            dur_h = cE1.number_input("¿Cuántas horas duró?", 0, 1000, value=int(_tgt_h), step=1, key="e_dur_h")
            dur_m = cE2.number_input("y minutos", 0, 59, value=int(_tgt_m), step=5, key="e_dur_m")
            dur_min_in = int(dur_h) * 60 + int(dur_m)
            nueva_etapa = cE3.selectbox("Pasar a la etapa", etapas_codigos, index=idx_nueva, format_func=_et_lbl, key="e_etapa")
            _cap = f"Duración: {int(dur_h)} h {int(dur_m)} min ({dur_min_in} min)"
            if tgt_min:
                _cap += f" · esperado ~{tgt_min//60} h {tgt_min%60} min"
            st.caption(_cap)
            temp_et = st.number_input("Temperatura al cerrar esta etapa (C) — opcional", 0.0, 300.0, step=1.0, value=0.0, key="e_temp")

            # Reposo mínimo (constante editable: reposo_min_horas_reactor)
            _reposo_min = int((K("reposo_min_horas_reactor", 4) or 4) * 60)
            if etapa_actual_cod == "REPOSANDO":
                if dur_min_in and dur_min_in < _reposo_min:
                    st.error(f"Reposo mínimo {_reposo_min//60} h. No se puede cerrar con menos.")
                else:
                    st.caption(f"Reposo mínimo requerido: {_reposo_min//60} h.")

            obs_etapa = st.text_input("Observaciones (opcional)", max_chars=200, key="e_obs_etapa")
            if st.button(f"Cerrar '{_et_lbl(etapa_actual_cod)}' y pasar a '{_et_lbl(nueva_etapa)}'",
                         use_container_width=True, type="primary", key="e_save"):
                if etapa_actual_cod == "REPOSANDO" and dur_min_in and dur_min_in < _reposo_min:
                    st.error(f"No se puede cerrar el reposo con menos de {_reposo_min//60} h.")
                    st.stop()
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE fact_etapa_evento
                                   SET fin_ts = NOW(),
                                       duracion_real_min = COALESCE(%s, duracion_real_min),
                                       observaciones = COALESCE(NULLIF(%s,''), observaciones)
                                 WHERE id_batch=%s AND fin_ts IS NULL
                            """, (int(dur_min_in) if dur_min_in else None, obs_etapa, id_batch_edit))
                            cur.execute("""
                                INSERT INTO fact_etapa_evento (id_batch, etapa, inicio_ts, id_usuario)
                                VALUES (%s, %s, NOW(), %s)
                            """, (id_batch_edit, nueva_etapa, int(USR["id_usuario"])))
                            _tp = {f"temp_{etapa_actual_cod.lower()}_c": float(temp_et)} if (temp_et and temp_et > 0) else {}
                            cur.execute("UPDATE fact_batch_proceso SET etapa_actual=%s, "
                                        "parametros_proceso = COALESCE(parametros_proceso,'{}'::jsonb) || %s::jsonb WHERE id_batch=%s",
                                        (nueva_etapa, json.dumps(_tp), id_batch_edit))
                        audit.log("U", "fact_batch_proceso", id_batch_edit,
                                  {"cerro_etapa": etapa_actual_cod, "duracion_min": int(dur_min_in) if dur_min_in else None,
                                   "nueva_etapa": nueva_etapa})
                    st.success(f"Cerraste {_et_lbl(etapa_actual_cod)} ({int(dur_h)} h {int(dur_m)} min). Ahora en {_et_lbl(nueva_etapa)}.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    # ---------- SUB-TAB: PRODUCTO FINAL (real + tanque destino + estimado vs real + decantación) ----------
    with sub_pfinal:
        st.caption("Al cerrar la reacción/bacha: cuánto se obtuvo realmente, a qué tanque fue, y la decantación. Se compara con lo estimado en el armado.")
        df_pf = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha, b.sector,
                   b.tipo_proceso, b.etapa_actual,
                   pb.codigo_producto AS buscado, b.calidad_buscada,
                   b.estimado_are_kg,
                   p.codigo_producto AS obtenido, b.kg_obtenido, b.litros_obtenido,
                   b.calidad_final, b.tanque_destino
            FROM fact_batch_proceso b
            LEFT JOIN dim_producto p  ON p.id_producto  = b.id_producto_obtenido
            LEFT JOIN dim_producto pb ON pb.id_producto = b.id_producto_buscado
            WHERE NOT b.anulado AND b.sector IN ('REACTORES','BACHAS')
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        # Anti-huérfanos: reacciones/bachas abiertas (sin producto final) que hay que cerrar.
        if not df_pf.empty:
            _abiertas = df_pf[df_pf["etapa_actual"].fillna("") != "EN_TANQUE"]
            if not _abiertas.empty:
                st.warning(
                    f"⏳ Hay **{len(_abiertas)}** reacción/es abierta/s sin producto final (etapa ≠ EN_TANQUE). "
                    "Cerralas para que no queden cargas incompletas: "
                    + ", ".join(f"#{int(r['id_batch'])}·{r['ticket'] or '—'}" for _, r in _abiertas.head(12).iterrows())
                )
        if df_pf.empty:
            st.info("Sin reacciones/bachas para cerrar.")
        else:
            optpf = df_pf.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['sector']} · busca {r['buscado'] or '—'} · etapa {r['etapa_actual'] or '—'}", axis=1).tolist()
            selpf = st.selectbox("Reacción / bacha", optpf, key="pf_sel")
            rpf = df_pf.iloc[optpf.index(selpf)]
            id_pf = int(rpf["id_batch"])
            _sector_pf = rpf["sector"]
            _usa_litros_pf = _sector_pf in ("REACTORES", "BACHAS")

            est_kg = float(rpf["estimado_are_kg"]) if pd.notna(rpf["estimado_are_kg"]) else None
            if est_kg:
                st.caption(f"🎯 Estimado en armado: **{est_kg/1000:,.2f} TN** ({est_kg:,.0f} kg) · buscado {rpf['buscado'] or '—'}")

            st.markdown("**Producto final real**")
            cF1, cF2, cF3 = st.columns(3)
            _finales = productos_permitidos(_sector_pf, rpf["tipo_proceso"], None, "FINAL") or productos[productos["tipo_producto"]=="FINAL"]["codigo_producto"].tolist()
            _opts_pf = sorted(set(_finales) | ({rpf["buscado"]} if rpf["buscado"] else set()))
            _idx_def = _opts_pf.index(rpf["buscado"]) if (rpf["buscado"] in _opts_pf) else 0
            p_obt_pf = cF1.selectbox("Producto obtenido *", _opts_pf, index=_idx_def, key="pf_prod")
            _sal_tickets = None
            # Para REACTORES y BACHAS el producto final SIEMPRE se carga por tickets de portería,
            # y los parámetros finales (acidez/densidad/AyS) salen del laboratorio.
            _usa_tickets_pf = _sector_pf in ("REACTORES", "BACHAS")
            _lab_avg_pf = {}
            if _usa_tickets_pf:
                with cF2:
                    st.caption("Tickets de portería de salida (filtrados por producto + lab):")
                    _tk_sal = _ui_multiselect_tickets(p_obt_pf, key_prefix=f"pf_tksal_{id_pf}", dias=180, limit=30)
                _sal_tickets = _tk_sal or None
                _det_pf, _avg_pf, _mlab_pf, _mport_pf, _mapping_pf = params_de_tickets_lab(_tk_sal, p_obt_pf)
                kg_pf = float(pd.to_numeric(_det_pf["kg"], errors="coerce").sum()) if (not _det_pf.empty and "kg" in _det_pf.columns) else 0.0
                lts_pf = None
                if _tk_sal and _tk_sal.strip():
                    cF2.caption(f"= **{kg_pf:,.0f} kg · {kg_pf/1000:,.2f} TN**")
                    _render_tickets_lab_panel(_det_pf, _avg_pf, _mlab_pf, _mport_pf, _mapping_pf, st_container=st)
                _lab_avg_pf = _avg_pf or {}
            elif _usa_litros_pf:
                _dpf = densidad_de(p_obt_pf)
                _def_lts = int(rpf["litros_obtenido"]) if pd.notna(rpf["litros_obtenido"]) else (int(round(est_kg/_dpf)) if est_kg else 0)
                lts_pf = cF2.number_input("Litros obtenido *", min_value=0, max_value=2_000_000, step=100,
                                          value=_def_lts, key=f"pf_lts_{id_pf}",
                                          help="Pre-cargado con el estimado del armado; ajustá si difiere.")
                kg_pf = (lts_pf or 0) * _dpf
                cF2.caption(f"= {kg_pf:,.0f} kg · {kg_pf/1000:,.2f} TN" + (f" · estimado armado {est_kg/_dpf:,.0f} L" if est_kg else ""))
            else:
                _def_kg = int(rpf["kg_obtenido"]) if pd.notna(rpf["kg_obtenido"]) else (int(round(est_kg)) if est_kg else 0)
                kg_pf = cF2.number_input("Kg obtenido *", min_value=0, max_value=2_000_000, step=100,
                                         value=_def_kg, key=f"pf_kg_{id_pf}",
                                         help="Pre-cargado con el estimado del armado; ajustá si difiere.")
                lts_pf = None
                if est_kg:
                    cF2.caption(f"estimado armado {est_kg:,.0f} kg")
            cal_pf = cF3.selectbox("Calidad final", [""] + calidades["codigo"].tolist(), key="pf_cal")
            tanque_pf = st.text_input("Tanque destino", value=(rpf["tanque_destino"] or ""), max_chars=40, key="pf_tk",
                                      placeholder="ej. TK-12")

            # Parámetros finales.
            # REACTORES/BACHAS: salen del laboratorio (promedio ponderado por kg de los tickets de salida).
            # Resto: se editan manualmente (los carga laboratorio).
            if _usa_tickets_pf:
                # Los prc_* del lab están en decimal (0.058 = 5.8%); convertimos a % para
                # guardar consistente con el resto de los parámetros.
                _acidez_lab = _lab_avg_pf.get("prc_acidez")
                _dens_lab   = _lab_avg_pf.get("densidad__g_ml")
                _agua_lab   = _lab_avg_pf.get("prc_agua")
                _sed_lab    = _lab_avg_pf.get("prc_sedimentos")
                _ays_lab = None
                if _agua_lab is not None and _sed_lab is not None:
                    _ays_lab = (float(_agua_lab) + float(_sed_lab)) * 100
                elif _agua_lab is not None:
                    _ays_lab = float(_agua_lab) * 100
                elif _sed_lab is not None:
                    _ays_lab = float(_sed_lab) * 100
                acidez_fin_pf = float(_acidez_lab) * 100 if _acidez_lab is not None else 0.0
                dens_fin_pf   = float(_dens_lab)         if _dens_lab   is not None else 0.0
                ays_pf        = float(_ays_lab)          if _ays_lab    is not None else 0.0
                st.markdown("**Parámetros finales** · desde laboratorio (promedio ponderado por kg)")
                _cP1, _cP2, _cP3 = st.columns(3)
                _cP1.metric("Acidez final",   f"{acidez_fin_pf:.3f}%" if acidez_fin_pf else "—")
                _cP2.metric("Densidad (g/ml)", f"{dens_fin_pf:.3f}"   if dens_fin_pf   else "—")
                _cP3.metric("% A y S",         f"{ays_pf:.3f}%"       if ays_pf        else "—",
                            help="A y S = % agua + % sedimentos del laboratorio.")
                if not _lab_avg_pf:
                    st.caption("Sin muestras de laboratorio aún para los tickets de salida. Se guarda con 0.")
            else:
                st.markdown("**Parámetros finales** · los define laboratorio (opcionales, 0 = no cargar)")
                cP1, cP2, cP3 = st.columns(3)
                acidez_fin_pf = cP1.number_input("Acidez final (%)", 0.0, 100.0, step=0.1, value=0.0, key=f"pf_acidez_{id_pf}")
                dens_fin_pf   = cP2.number_input("Densidad final (gr/cm³)", 0.0, 2.0, step=0.01, value=0.0, key=f"pf_dens_{id_pf}")
                ays_pf        = cP3.number_input("% A y S", 0.0, 100.0, step=0.1, value=0.0, key=f"pf_ays_{id_pf}")
            obs_pf = st.text_input("Observaciones / comentarios", max_chars=300, key=f"pf_obs_{id_pf}")

            if est_kg and kg_pf and kg_pf > 0:
                desv = (kg_pf - est_kg) / est_kg * 100
                msg = f"Real **{kg_pf/1000:,.2f} TN** vs estimado **{est_kg/1000:,.2f} TN** → desvío **{desv:+.1f}%**"
                (st.success if abs(desv) <= 10 else st.warning)(("✅ " if abs(desv) <= 10 else "⚠️ ") + msg)

            if st.button("💾 Guardar producto final", type="primary", use_container_width=True, key="pf_save"):
                if kg_pf <= 0:
                    st.error("Cargá cuánto se obtuvo (litros/kg).")
                else:
                    try:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s", (p_obt_pf,))
                                _row = cur.fetchone(); pid_pf = _row[0] if _row else None
                                _obs_final = (obs_pf + (f" · salida tickets: {_sal_tickets}" if _sal_tickets else "")).strip()
                                cur.execute("""
                                    UPDATE fact_batch_proceso
                                       SET id_producto_obtenido=%s, kg_obtenido=%s, litros_obtenido=%s,
                                           calidad_final=COALESCE(NULLIF(%s,''), calidad_final),
                                           tanque_destino=COALESCE(NULLIF(%s,''), tanque_destino),
                                           acidez_final_pct=COALESCE(NULLIF(%s,0), acidez_final_pct),
                                           densidad_final=COALESCE(NULLIF(%s,0), densidad_final),
                                           porc_ays=COALESCE(NULLIF(%s,0), porc_ays),
                                           observaciones=CASE WHEN %s <> '' THEN COALESCE(observaciones||' | ','') || %s ELSE observaciones END,
                                           etapa_actual='EN_TANQUE'
                                     WHERE id_batch=%s
                                """, (pid_pf, float(kg_pf), (float(lts_pf) if lts_pf else None),
                                      cal_pf, tanque_pf,
                                      float(acidez_fin_pf), float(dens_fin_pf), float(ays_pf),
                                      _obs_final, _obs_final, id_pf))
                            audit.log("U", "fact_batch_proceso", id_pf,
                                      {"producto_final": p_obt_pf, "kg": kg_pf, "tanque": tanque_pf})
                        st.success(f"Producto final de #{id_pf} guardado."); cat.clear(); st.rerun()
                    except Exception as e:
                        st.exception(e)

            # ----- Decantación (debajo) -----
            st.divider()
            st.markdown("### 💧 Decantación")
            pkey_pf = proceso_key_de(_sector_pf, rpf["tipo_proceso"])
            _dec_pf = decantaciones_de(pkey_pf)
            if not _dec_pf.empty:
                st.caption("Salidas esperadas para este proceso: " + ", ".join(_dec_pf["label"].tolist()))
            _tipos_pf = _dec_pf["tipo_salida"].tolist()
            _sug_pf = [c for c in _dec_pf["codigo_producto"].tolist() if pd.notna(c) and c]
            if "GLICERINA_RECUP" in _tipos_pf: _sug_pf += ["GLICERINA", "GLICERINA-FE"]
            if "AGUA_PROCESO" in _tipos_pf: _sug_pf += ["AGUA-PROC"]
            _opt_dec_pf = [c for c in dict.fromkeys(_sug_pf) if c in productos["codigo_producto"].tolist()]
            if _opt_dec_pf:
                n_sal_pf = st.number_input("Salidas a registrar", 0, 5, value=0, key="pf_ndec")
                sal_pf = []
                for i in range(int(n_sal_pf)):
                    d1, d2, d3 = st.columns(3)
                    cd = d1.selectbox(f"Producto #{i+1}", _opt_dec_pf, key=f"pf_dprod_{i}")
                    kgd = d2.number_input(f"kg #{i+1}", min_value=0, max_value=200000, step=50, value=0, key=f"pf_dkg_{i}")
                    destd = d3.text_input(f"Destino #{i+1}", max_chars=40, key=f"pf_ddst_{i}")
                    if kgd > 0:
                        sal_pf.append((cd, float(kgd), destd or None))
                if sal_pf and st.button("💾 Guardar decantación", key="pf_dsave", use_container_width=True):
                    try:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                for cd, kgd, destd in sal_pf:
                                    cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s", (cd,))
                                    _r = cur.fetchone()
                                    if not _r:
                                        continue
                                    cur.execute("""
                                        INSERT INTO fact_salida_decantacion
                                        (id_batch, id_producto, kg, destino_tanque, id_usuario)
                                        VALUES (%s,%s,%s,%s,%s)
                                    """, (id_pf, _r[0], kgd, destd, int(USR["id_usuario"])))
                            audit.log("I", "fact_salida_decantacion", id_pf, {"n": len(sal_pf)})
                        st.success("Decantación registrada.")
                    except Exception as e:
                        st.exception(e)
            else:
                st.caption("Este proceso no tiene decantaciones configuradas.")

    # ---------- SUB-TAB: CARGAR MUESTRA INTERMEDIA ----------
    with sub_eval:
        st.caption("Evaluaciones internas **solo en Producción de ARE**: medís en distintas etapas para bajar la acidez de ~60 a 10 (especificación comercial). Parámetros: acidez, temperatura, fósforo.")
        df_rec2 = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha,
                   b.tipo_proceso, b.etapa_actual
            FROM fact_batch_proceso b
            WHERE NOT b.anulado AND b.sector='REACTORES' AND b.tipo_proceso='PRODUCCION_ARE'
            ORDER BY b.creado_en DESC LIMIT 100
        """)
        if df_rec2.empty:
            st.info("Sin reacciones de Producción ARE todavía. Las evaluaciones internas solo aplican a ARE.")
        else:
            opt2 = df_rec2.apply(lambda r: f"#{r['id_batch']} · {r['ticket'] or '—'} · {r['tipo_proceso']}", axis=1).tolist()
            sel2 = st.selectbox("Reacción / ticket", opt2, key="m_sel")
            r2 = df_rec2.iloc[opt2.index(sel2)]
            tipo_actual = r2["tipo_proceso"]

            _et_eval = etapas_de_proceso("PRODUCCION_ARE")
            _et_eval_codes = _et_eval["etapa"].tolist()
            etapa_m = st.selectbox(
                "Etapa de la muestra", _et_eval_codes,
                format_func=lambda c: (_et_eval[_et_eval["etapa"]==c].iloc[0]["descripcion"] if not _et_eval[_et_eval["etapa"]==c].empty else c),
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
            if st.button("⚠️ Registrar gasto extra", type="primary", use_container_width=True, key="g_save"):
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

    # ---------- SUB-TAB: EDITOR DE ETAPAS / TIEMPOS POR PROCESO ----------
    with sub_etapas:
        st.caption("Editá las etapas y los tiempos estimados (minutos) de cada proceso. Se guarda en `dic_proceso_etapa`.")
        if USR["rol"] not in ("ADMIN", "SUPERVISOR"):
            st.info("Solo ADMIN o SUPERVISOR pueden editar las etapas.")
        else:
            _procs = sorted(set(proc_etapa["proceso_key"].tolist()) |
                            {"PRODUCCION_ARE", "DESGOMADO_ACUOSO", "RECUPERACION", "BACHAS"})
            pk_sel = st.selectbox("Proceso", _procs, key="ed_pk")
            _cur = (proc_etapa[proc_etapa["proceso_key"] == pk_sel]
                    .sort_values("orden")[["etapa", "orden", "duracion_target_min", "duracion_min_min", "duracion_max_min"]]
                    .reset_index(drop=True))
            st.markdown("**Etapas del proceso** — podés agregar/quitar filas y cambiar tiempos.")
            edited = st.data_editor(
                _cur, num_rows="dynamic", use_container_width=True, key="ed_tab",
                column_config={
                    "etapa": st.column_config.SelectboxColumn("Etapa", options=etapas_proc["codigo"].tolist(), required=True),
                    "orden": st.column_config.NumberColumn("Orden", min_value=1, step=1, required=True),
                    "duracion_target_min": st.column_config.NumberColumn("Target (min)", min_value=0, step=1),
                    "duracion_min_min": st.column_config.NumberColumn("Mín (min)", min_value=0, step=1),
                    "duracion_max_min": st.column_config.NumberColumn("Máx (min)", min_value=0, step=1),
                },
            )
            if st.button(f"💾 Guardar etapas de {pk_sel}", type="primary", key="ed_save"):
                try:
                    rows_e, seen = [], set()
                    for _, er in edited.iterrows():
                        et = er.get("etapa")
                        et = et.strip() if isinstance(et, str) else et
                        if not et or et in seen:
                            continue
                        seen.add(et)
                        rows_e.append((
                            pk_sel, et,
                            int(er["orden"]) if pd.notna(er.get("orden")) else 1,
                            int(er["duracion_target_min"]) if pd.notna(er.get("duracion_target_min")) else None,
                            int(er["duracion_min_min"]) if pd.notna(er.get("duracion_min_min")) else None,
                            int(er["duracion_max_min"]) if pd.notna(er.get("duracion_max_min")) else None,
                        ))
                    if not rows_e:
                        st.error("Definí al menos una etapa válida.")
                    else:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                cur.execute("DELETE FROM dic_proceso_etapa WHERE proceso_key=%s", (pk_sel,))
                                for re_ in rows_e:
                                    cur.execute(
                                        "INSERT INTO dic_proceso_etapa (proceso_key, etapa, orden, "
                                        "duracion_target_min, duracion_min_min, duracion_max_min) "
                                        "VALUES (%s,%s,%s,%s,%s,%s)", re_)
                            audit.log("U", "dic_proceso_etapa", pk_sel, {"n_etapas": len(rows_e)})
                        st.success(f"Etapas de {pk_sel} guardadas ({len(rows_e)}).")
                        cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    # ---------- SUB-TAB: EVALUAR INSUMO ----------
    with sub_evins:
        st.caption("Cargá evaluaciones de laboratorio de insumos (ácido sulfúrico, soda cáustica, gasoil, etc.).")
        _ins_eval = insumos_cat[insumos_cat["evaluable"] == True]
        if _ins_eval.empty:
            st.info("No hay insumos marcados como evaluables. Marcá `dic_insumo.evaluable=TRUE` en Supabase.")
        else:
            cI1, cI2 = st.columns(2)
            ins_e = cI1.selectbox(
                "Insumo", _ins_eval["codigo"].tolist(), key="ei_ins",
                format_func=lambda c: f"{_ins_eval[_ins_eval['codigo']==c].iloc[0]['descripcion']} ({c})"
            )
            fecha_ei = cI2.date_input("Fecha", date.today(), key="ei_fecha")
            st.markdown("**Mediciones** (dejá en 0 lo que no midas)")
            cM1, cM2, cM3 = st.columns(3)
            m_conc = cM1.number_input("Concentración / pureza (%)", 0.0, 100.0, step=0.1, value=0.0, key="ei_conc")
            m_dens = cM2.number_input("Densidad (kg/L)", 0.0, 5.0, step=0.001, value=0.0, key="ei_dens")
            m_ph   = cM3.number_input("pH", 0.0, 14.0, step=0.1, value=0.0, key="ei_ph")
            obs_ei = st.text_input("Observaciones", max_chars=200, key="ei_obs")
            if st.button("🧪 Guardar evaluación de insumo", type="primary", use_container_width=True, key="ei_save"):
                med_e = {}
                if m_conc > 0: med_e["concentracion_pct"] = float(m_conc)
                if m_dens > 0: med_e["densidad_kg_l"] = float(m_dens)
                if m_ph   > 0: med_e["ph"] = float(m_ph)
                if not med_e:
                    st.error("Ingresá al menos una medición.")
                else:
                    try:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                cur.execute("""
                                    INSERT INTO fact_evaluacion_insumo
                                    (codigo_insumo, fecha, mediciones, observaciones, id_usuario)
                                    VALUES (%s,%s,%s::jsonb,%s,%s) RETURNING id_eval_insumo
                                """, (ins_e, fecha_ei.isoformat(), json.dumps(med_e), obs_ei or None, int(USR["id_usuario"])))
                                id_ei = cur.fetchone()[0]
                            audit.insert("fact_evaluacion_insumo", id_ei, {"insumo": ins_e, "med": med_e})
                        st.success(f"Evaluación de insumo #{id_ei} guardada.")
                    except Exception as e:
                        st.exception(e)
            st.divider()
            st.markdown("**Últimas evaluaciones de insumos**")
            df_ei = cat("""
                SELECT ei.fecha, ei.codigo_insumo, i.descripcion, ei.mediciones, ei.observaciones, u.nombre AS usuario
                FROM produccion.fact_evaluacion_insumo ei
                JOIN produccion.dic_insumo i ON i.codigo = ei.codigo_insumo
                LEFT JOIN produccion.dim_usuario u ON u.id_usuario = ei.id_usuario
                WHERE NOT ei.anulado
                ORDER BY ei.fecha DESC, ei.id_eval_insumo DESC LIMIT 50
            """)
            if df_ei.empty:
                st.caption("Sin evaluaciones todavía.")
            else:
                st.dataframe(df_ei, use_container_width=True, hide_index=True)


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
    k2.metric("TN obtenidas", f"{df_obs['kg_obtenido'].sum()/1000:,.2f}" if not df_obs.empty else "0,00")
    k3.metric("TN MP", f"{df_obs['kg_inicial'].fillna(0).sum()/1000:,.2f}" if not df_obs.empty else "0,00")
    k4.metric("Fuera de rango", int(df_obs["fuera_de_rango"].sum()) if not df_obs.empty else 0)

    st.markdown("**Cargas en el rango seleccionado**")
    if df_obs.empty:
        st.info("Sin cargas para estos filtros.")
    else:
        st.dataframe(df_obs, use_container_width=True, hide_index=True)

        # Producción final por producto
        st.markdown("**Producción por producto (TN)**")
        prod_x_prod = df_obs.groupby("obtenido", as_index=False)["kg_obtenido"].sum().sort_values("kg_obtenido", ascending=False)
        prod_x_prod["TN"] = (prod_x_prod["kg_obtenido"] / 1000).round(2)
        st.bar_chart(prod_x_prod, x="obtenido", y="TN")

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
            WHERE NOT b.anulado AND b.sector IN ('REACTORES','BACHAS')
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
