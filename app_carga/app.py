"""worms_supabase / app_carga / app.py · Streamlit + Supabase + login + admin + anulación."""
from __future__ import annotations
import json, sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st
from datetime import datetime as _dtmod, timezone as _tzmod, timedelta as _tdmod
TZ_AR = _tzmod(_tdmod(hours=-3))  # Argentina (UTC-3, sin horario de verano)
def _ahora_ar():
    return _dtmod.now(TZ_AR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.db import (
    conectar, convertir, login as login_db,
    crear_usuario, reset_pin, cambiar_rol, cambiar_sector, cambiar_sectores, cambiar_secciones_app, set_activo,
    cambiar_mi_pin,
    listar_mis_cargas, anular_registro, puede_anular,
)
from etl.config import DATABASE_URL

import auth_persist as _auth

from contextlib import contextmanager as _lab_cm
@_lab_cm
def _lab_conn():
    """Conexion para la seccion Laboratorio (carga/edicion)."""
    import psycopg2 as _pg
    c = _pg.connect(DATABASE_URL)
    try:
        with c.cursor() as cur:
            cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
        yield c
    finally:
        c.close()

st.set_page_config(page_title="WORMS Carga", layout="wide", page_icon="🏭")


# ===== Design system global (look premium) — login, landing y secciones =====
def inject_global_css():
    st.markdown("""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');
      :root{
        --bg:#f5f6fb; --surface:#ffffff; --ink:#0f172a; --muted:#64748b; --line:#e6e8f0;
        --brand:#4f46e5; --brand2:#7c3aed; --grad:linear-gradient(135deg,#4f46e5 0%,#7c3aed 60%,#9333ea 100%);
        --ok:#059669; --warn:#d97706; --bad:#dc2626;
      }
      html, body, [class*="css"], .stMarkdown, p, span, label, input, button, textarea, select{
        font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
      }
      [data-testid="stAppViewContainer"]{
        background:radial-gradient(1200px 600px at 12% -8%, #eef1ff 0%, transparent 55%), var(--bg);
      }
      .block-container{max-width:1200px; padding-top:1.6rem;}
      h1,h2,h3,h4{font-family:'Plus Jakarta Sans','Inter',sans-serif; letter-spacing:-.01em; color:var(--ink);}
      h1{font-size:1.7rem;} h2{font-size:1.3rem;} h3{font-size:1.12rem;}
      a{color:var(--brand);}
      .stButton>button, .stDownloadButton>button{
        border-radius:12px; font-weight:600; border:1px solid var(--line);
        transition:transform .12s ease, box-shadow .12s ease, border-color .12s; padding:.5rem 1rem;
      }
      .stButton>button:hover, .stDownloadButton>button:hover{
        transform:translateY(-1px); box-shadow:0 6px 16px -8px rgba(79,70,229,.45); border-color:#c7cbf5;
      }
      .stButton>button[kind="primary"], [data-testid="stBaseButton-primary"]{
        background:var(--grad); border:0; color:#fff; box-shadow:0 8px 20px -10px rgba(124,58,237,.7);
      }
      .stButton>button[kind="primary"]:hover{filter:brightness(1.05); transform:translateY(-1px);}
      .stTabs [data-baseweb="tab-list"]{gap:4px; border-bottom:1px solid var(--line);}
      .stTabs [data-baseweb="tab"]{border-radius:10px 10px 0 0; padding:8px 14px; font-weight:600; color:var(--muted);}
      .stTabs [aria-selected="true"]{color:var(--brand); background:rgba(79,70,229,.07);}
      [data-testid="stMetric"]{
        background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:14px 16px;
        box-shadow:0 1px 2px rgba(16,24,40,.05);
      }
      [data-testid="stMetricValue"]{font-size:1.55rem; font-weight:800; font-family:'Plus Jakarta Sans';}
      [data-testid="stMetricLabel"]{opacity:.85; font-weight:600;}
      [data-testid="stVerticalBlockBorderWrapper"]{
        border-radius:16px !important; border-color:var(--line) !important; background:var(--surface);
        box-shadow:0 1px 3px rgba(16,24,40,.05); transition:box-shadow .15s, transform .15s, border-color .15s;
      }
      [data-testid="stVerticalBlockBorderWrapper"]:hover{
        box-shadow:0 14px 30px -18px rgba(79,70,229,.45); border-color:#cdd2f3 !important; transform:translateY(-2px);
      }
      [data-baseweb="input"], [data-baseweb="select"]>div, [data-baseweb="textarea"]{border-radius:11px !important;}
      div[data-testid="stExpander"] details{border-radius:13px; border:1px solid var(--line); overflow:hidden;}
      section[data-testid="stSidebar"]{
        background:linear-gradient(180deg,#ffffff 0%,#f3f3fb 100%); border-right:1px solid var(--line);
      }
      .worms-hero{
        position:relative; overflow:hidden; border-radius:22px; padding:28px 32px; color:#fff;
        background:var(--grad); box-shadow:0 18px 40px -18px rgba(124,58,237,.65); margin-bottom:6px;
      }
      .worms-hero h1{color:#fff; margin:0 0 6px; font-size:2rem; line-height:1.1;}
      .worms-hero p{margin:0; opacity:.94; font-size:.98rem;}
      .worms-hero .glow{position:absolute; right:-50px; top:-60px; width:230px; height:230px;
        background:radial-gradient(circle, rgba(255,255,255,.28), transparent 70%); pointer-events:none;}
      .worms-hero .chip{display:inline-block; margin-top:12px; background:rgba(255,255,255,.18);
        border:1px solid rgba(255,255,255,.35); padding:5px 12px; border-radius:999px; font-size:.8rem; font-weight:600;}
      .kpi-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(178px,1fr)); gap:14px; margin:16px 0 6px;}
      .kpi{background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:15px 18px;
        box-shadow:0 1px 2px rgba(16,24,40,.05);}
      .kpi.brand{background:linear-gradient(135deg,#eef2ff,#faf5ff); border-color:#e0e7ff;}
      .kpi .l{font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:700;}
      .kpi .v{font-size:1.95rem; font-weight:800; color:var(--ink); font-family:'Plus Jakarta Sans'; line-height:1.1; margin-top:5px;}
      .kpi .v.ok{color:var(--ok);} .kpi .v.warn{color:var(--warn);} .kpi .v.bad{color:var(--bad);}
      .kpi .s{font-size:.8rem; color:var(--muted); margin-top:3px;}
      .section-title{font-family:'Plus Jakarta Sans'; font-weight:800; font-size:1.05rem; color:var(--ink); margin:20px 0 8px;}
      .pill{display:inline-block; padding:3px 10px; border-radius:999px; font-size:.72rem; font-weight:700;}
      .pill.ok{background:#d1fae5; color:#065f46;} .pill.warn{background:#fef3c7; color:#92400e;}
      .pill.info{background:#e0e7ff; color:#3730a3;} .pill.bad{background:#fee2e2; color:#991b1b;}
      .tile-h{font-family:'Plus Jakarta Sans'; font-weight:800; font-size:1.15rem; color:var(--ink); margin:0 0 6px; line-height:1.25;}
      .tile-d{color:var(--muted); font-size:.86rem; line-height:1.45; margin:0 0 12px;}
      @media (min-width:741px){ .tile-h{min-height:2.9em;} .tile-d{min-height:4.4em;} }
      /* ---- ocultar chrome de Streamlit (look de app propia) ---- */
      #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
      [data-testid="stStatusWidget"]{display:none !important;}
      header[data-testid="stHeader"]{background:transparent; box-shadow:none;}
      /* ---- pantalla de login ---- */
      .login-brand{text-align:center; margin:5vh 0 14px;}
      .login-brand .logo{font-size:3rem; line-height:1;}
      .login-brand h1{font-size:2.1rem; margin:10px 0 2px;
        background:var(--grad); -webkit-background-clip:text; background-clip:text; color:transparent;}
      .login-brand p{color:var(--muted); margin:0; font-weight:600;}
      .login-title{font-family:'Plus Jakarta Sans'; font-weight:800; font-size:1.15rem; margin-bottom:2px;}
      /* ---- tactil ---- */
      .stButton>button{min-height:46px;}
      /* ---- movil ---- */
      @media (max-width:740px){
        .block-container{padding:.9rem .9rem 4rem;}
        h1{font-size:1.35rem;} h2{font-size:1.15rem;}
        .worms-hero{padding:20px 18px; border-radius:16px;}
        .worms-hero h1{font-size:1.4rem;}
        .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px;}
        .kpi{padding:12px 14px;} .kpi .v{font-size:1.5rem;}
        input, select, textarea{font-size:16px !important;}
        [data-testid="stMetricValue"]{font-size:1.25rem;}
      }
    </style>
    """, unsafe_allow_html=True)

inject_global_css()


# ---------- LOGIN -----------------------------------------------------------
def usuarios_disponibles():
    if not DATABASE_URL: return []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
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
    st.markdown("""
    <div class="login-brand">
      <div class="logo">🏭</div>
      <h1>WORMS</h1>
      <p>Panel de carga · Producción</p>
    </div>
    """, unsafe_allow_html=True)
    usuarios = usuarios_disponibles()
    if not usuarios:
        st.error("No se puede conectar a la base. Verificá `.env` y la conexión.")
        st.stop()
    opciones = {f"{full} ({n})": n for n, full in usuarios}
    _l, _mid, _r = st.columns([1, 1.5, 1])
    with _mid:
        with st.container(border=True):
            st.markdown('<div class="login-title">Iniciar sesión</div>', unsafe_allow_html=True)
            sel = st.selectbox("Usuario", list(opciones.keys()))
            pin = st.text_input("PIN (4-6 dígitos)", type="password", max_chars=6)
            if st.button("Ingresar", type="primary", use_container_width=True):
                if not pin:
                    st.error("Ingresá el PIN."); return
                u = login_db(opciones[sel], pin)
                if u is None:
                    st.error("Usuario o PIN incorrecto, o usuario desactivado."); return
                st.session_state.user = u
                st.session_state._set_cookie = _auth.make_token(u["id_usuario"])
                st.session_state.pop("_logged_out", None)
                st.rerun()
            st.caption(f"🔒 La sesión queda recordada en este dispositivo por {_auth.DIAS_SESION} días.")


def cerrar_sesion():
    st.session_state._logged_out = True       # evita auto-restaurar desde la cookie vieja
    st.session_state._clear_cookie = True     # borra la cookie en el proximo render
    if "user" in st.session_state: del st.session_state["user"]
    st.rerun()


# Logout pendiente: borrar cookie en el navegador
if st.session_state.pop("_clear_cookie", False):
    _auth.clear_cookie()
    _auth.set_section_cookie(None)
    st.session_state._sec_cookie = None

# Restaurar sesion desde cookie firmada (sobrevive bloqueo del celular / recarga)
if "user" not in st.session_state and not st.session_state.get("_logged_out"):
    _u_rest = _auth.restaurar_sesion()
    if _u_rest is not None:
        st.session_state.user = _u_rest
        # volver a la sección donde estaba trabajando (cookie worms_section)
        _sec_rest = _auth.get_section_cookie()
        if _sec_rest and "section" not in st.session_state:
            st.session_state.section = _sec_rest

if "user" not in st.session_state:
    pantalla_login(); st.stop()

USR = st.session_state.user

# ---- Permisos por usuario sobre las secciones de la página ----
SECCIONES_APP = [
    ("INICIAR", "👷 Producción en planta"),
    ("LAB", "🧪 Laboratorio"), ("TANQUES", "🛢️ Tanques"), ("STOCK", "📦 Stock"),
    ("ESTADO", "📈 Estado de planta"),
    ("PLANIFICACION", "🗓️ Centro de Planificación"), ("CONDICIONALES", "🧮 Condicionales"), ("FORMULAS", "🧪 Fórmulas"), ("CHAT", "🤖 Consultas IA"),
    ("CIERRES", "💰 Cierres mensuales"), ("DIRECCION", "🛂 Dirección"), ("ADMIN", "⚙️ Admin"),
]


def _secciones_default(rol):
    base = ["INICIAR", "LAB", "TANQUES", "STOCK", "ESTADO"]
    if rol in ("SUPERVISOR", "ADMIN"):
        base += ["PLANIFICACION", "CONDICIONALES", "FORMULAS", "CHAT", "CIERRES"]
    if rol == "ADMIN":
        base += ["DIRECCION", "ADMIN"]
    return base


def puede_seccion(sec):
    """Acceso a una sección: lista explícita del usuario, o default del rol. Admin SIEMPRE exige rol ADMIN."""
    if sec == "ADMIN" and USR.get("rol") != "ADMIN":
        return False
    _p = USR.get("secciones_app")
    return sec in (_p if _p else _secciones_default(USR.get("rol")))

# Login reciente: escribir cookie de sesion en el navegador
if "_set_cookie" in st.session_state:
    _auth.set_cookie(st.session_state.pop("_set_cookie"))

# ---------- LANDING (post-login): elegir sección ----------
if "section" not in st.session_state:
    st.session_state.section = None

# Usuarios con UNA sola sección habilitada quedan anclados a ella (sin landing ni cambio de sección).
_ALLOWED_SECS = USR.get("secciones_app") or _secciones_default(USR.get("rol"))
_LOCKED_ONE = len(_ALLOWED_SECS) == 1
if _LOCKED_ONE:
    st.session_state.section = _ALLOWED_SECS[0]

def go_to(sec):
    st.session_state.section = sec
    st.rerun()

@st.cache_data(ttl=60)
def _landing_kpis():
    """KPIs del pantallazo inicial. Devuelve dict o None si falla la conexion."""
    if not DATABASE_URL:
        return None
    sql = """
      SELECT
        (SELECT count(*) FROM vw_stock_tanque_actual) AS tanques,
        (SELECT COALESCE(SUM(kg_actual),0)/1000.0 FROM vw_stock_tanque_actual) AS stock_tn,
        (SELECT count(*) FROM fact_batch_proceso WHERE estado IN ('REACCION','REPOSO','DECANTACION') AND NOT anulado) AS en_proceso,
        (SELECT count(*) FROM fact_batch_proceso WHERE estado='REACCION' AND NOT anulado) AS en_reaccion,
        (SELECT count(*) FROM fact_batch_proceso WHERE estado='REPOSO' AND NOT anulado) AS en_reposo,
        (SELECT count(*) FROM fact_ticket_lab WHERE estado='PENDIENTE') AS tickets_pend,
        (SELECT count(*) FROM fact_batch_proceso WHERE esperando_validacion_lab) AS esp_valid,
        (SELECT count(*) FROM fact_batch_proceso WHERE fecha=CURRENT_DATE AND NOT anulado) AS hoy
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
                cur.execute(sql)
                row = cur.fetchone()
                cols = ["tanques","stock_tn","en_proceso","en_reaccion","en_reposo","tickets_pend","esp_valid","hoy"]
                return dict(zip(cols, row))
        finally:
            conn.close()
    except Exception:
        return None


def _home_df(sql, params=None):
    """Query directa para el home (cat() aun no esta definido en este punto del script)."""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
            return pd.DataFrame(rows, columns=cols)
        finally:
            conn.close()
    except Exception:
        return None


if st.session_state.section is None:
    if st.session_state.get("_sec_cookie"):
        _auth.set_section_cookie(None)
        st.session_state._sec_cookie = None
    _hoy_txt = date.today().strftime("%d/%m/%Y")
    st.markdown(f"""
    <div class="worms-hero">
      <div class="glow"></div>
      <h1>🏭 WORMS · Panel de producción</h1>
      <p>Hola <b>{USR['nombre_full']}</b> — todo el proceso de reactores y bachas en un solo lugar.</p>
      <span class="chip">👤 {USR['rol'].title()} · 📅 {_hoy_txt}</span>
    </div>
    """, unsafe_allow_html=True)

    # --- Estado de sincronización de datos (Access → Supabase) ---
    try:
        _sc = _home_df("SELECT source_id, machine_name, last_status, COALESCE(last_error,'') last_error, "
                  "last_successful_sync, rows_last_batch, "
                  "round((extract(epoch from now()-updated_at)/60.0)::numeric,0) AS hace_min "
                  "FROM produccion.sync_control ORDER BY source_id")
        _ultp = _home_df("SELECT max(fecha_entrada) ult, max(transaccion) tk FROM produccion.v_transacciones_limpias")
        _ultl = _home_df("SELECT max(fecha) ult FROM produccion.v_procesos_lab_efectivo")
    except Exception:
        _sc = None; _ultp = None; _ultl = None
    if _sc is not None and not _sc.empty:
        st.markdown('<div class="section-title">Estado de datos · portería y laboratorio</div>', unsafe_allow_html=True)
        _scols = st.columns(len(_sc))
        for _i, (_, _r) in enumerate(_sc.iterrows()):
            _sid = str(_r["source_id"])
            _nom = "🚛 Portería" if _sid.startswith("porteria") else ("🧪 Laboratorio" if _sid.startswith("laboratorio") else _sid)
            _ok = str(_r["last_status"]).upper() == "OK"
            _hace = _r["hace_min"]
            _hn = int(_hace) if pd.notna(_hace) else None
            _viejo = (_hn is not None and _hn > 60)
            _icon = "🟢" if (_ok and not _viejo) else ("🟠" if _ok else "🔴")
            _when = pd.to_datetime(_r["last_successful_sync"]).strftime("%d/%m %H:%M") if pd.notna(_r["last_successful_sync"]) else "—"
            with _scols[_i]:
                st.markdown(f"**{_icon} {_nom}**")
                st.caption(f"PC: **{_r['machine_name'] or '—'}** · último OK: **{_when}**"
                           + (f" (hace {_hn} min)" if _hn is not None else "")
                           + f" · {int(_r['rows_last_batch'] or 0)} filas")
                if not _ok and _r["last_error"]:
                    st.error(f"⚠️ Error de sincronización: {_r['last_error']}")
                elif _viejo:
                    st.warning(f"Sin refrescar hace {_hn} min — revisá la PC de sincronización.")
        if _ultp is not None and not _ultp.empty:
            _up = _ultp.iloc[0]
            _upf = pd.to_datetime(_up["ult"]).strftime("%d/%m/%Y") if pd.notna(_up["ult"]) else "—"
            _tk = f"#{int(_up['tk'])}" if pd.notna(_up["tk"]) else "—"
            _ul = _ultl.iloc[0]["ult"] if (_ultl is not None and not _ultl.empty) else None
            _ulf = pd.to_datetime(_ul).strftime("%d/%m/%Y") if pd.notna(_ul) else "—"
            st.caption(f"📅 Último dato de **portería**: {_upf} (ticket {_tk}) · último dato de **laboratorio**: {_ulf}")

    # --- PCs que intentan subir (heartbeat): cuál sube efectivamente ---
    try:
        _pcs = _home_df("SELECT fuente, machine_name, hace_min, activa, ok, con_error, es_la_que_sube, "
                   "COALESCE(ultimo_error,'') ultimo_error FROM produccion.v_sync_pcs "
                   "ORDER BY fuente, ultimo_latido DESC")
    except Exception:
        _pcs = None
    if _pcs is not None and not _pcs.empty:
        _nact = int(_pcs["activa"].fillna(False).astype(bool).sum())
        with st.expander(f"🖥️ PCs intentando subir ({_nact} activa(s) en 15 min) — cuál sube efectivamente", expanded=False):
            for _fu in _pcs["fuente"].unique():
                st.markdown(f"**{_fu}**")
                for _, _p in _pcs[_pcs["fuente"] == _fu].iterrows():
                    _mark = ("✅ **sube esta**" if _p["es_la_que_sube"]
                             else ("🟢 activa" if _p["activa"] else "⚪ inactiva"))
                    _hn = int(_p["hace_min"]) if pd.notna(_p["hace_min"]) else "—"
                    _err = (f" · último error: {str(_p['ultimo_error'])[:90]}" if _p["ultimo_error"] else "")
                    st.write(f"- {_mark} · **{_p['machine_name']}** · latido hace {_hn} min · "
                             f"{int(_p['ok'] or 0)} OK / {int(_p['con_error'] or 0)} error{_err}")
            st.caption("Varias PCs pueden intentar subir el mismo Access; **sube la del último latido OK**. "
                       "Muchos errores suele ser choque por acceso concurrente al archivo — conviene dejar una sola PC subiendo.")

    k = _landing_kpis()
    if k:
        esp_cls = "bad" if (k['esp_valid'] or 0) > 0 else "ok"
        tic_cls = "warn" if (k['tickets_pend'] or 0) > 0 else "ok"
        st.markdown(f"""
        <div class="kpi-grid">
          <div class="kpi brand"><div class="l">En proceso ahora</div>
            <div class="v">{int(k['en_proceso'] or 0)}</div>
            <div class="s">{int(k['en_reaccion'] or 0)} en reacción · {int(k['en_reposo'] or 0)} en reposo</div></div>
          <div class="kpi"><div class="l">Cargas de hoy</div>
            <div class="v">{int(k['hoy'] or 0)}</div><div class="s">reacciones iniciadas hoy</div></div>
          <div class="kpi"><div class="l">Stock en tanques</div>
            <div class="v">{(k['stock_tn'] or 0):,.0f}<span style="font-size:1rem;font-weight:700;"> TN</span></div>
            <div class="s">{int(k['tanques'] or 0)} tanques activos</div></div>
          <div class="kpi"><div class="l">Tickets lab pendientes</div>
            <div class="v {tic_cls}">{int(k['tickets_pend'] or 0)}</div><div class="s">a evaluar en laboratorio</div></div>
          <div class="kpi"><div class="l">Esperando validación</div>
            <div class="v {esp_cls}">{int(k['esp_valid'] or 0)}</div><div class="s">reacciones que aguardan lab</div></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="section-title">Accesos</div>', unsafe_allow_html=True)

    tiles = [
        ("👷", "Producción en planta", "Elegí una producción planificada por dirección y arrancá la reacción (checklist + caldera).", "INICIAR", "land_iniciar", True),
        ("🧪", "Laboratorio", "Resultados de laboratorio: filtros, estadísticas y descarga CSV.", "LAB", "land_lab", False),
        ("🛢️", "Tanques", "Stock por tanque: contenido, capacidad y última medición cargada.", "TANQUES", "land_tanques", False),
        ("📦", "Stock", "Libro mayor de movimientos, stock estimado en tiempo real y conciliación. Todo descargable.", "STOCK", "land_stock", False),
        ("📈", "Estado de planta", "Tablero de reacciones, bandeja de laboratorio, trazabilidad de lote, mermas y alertas.", "ESTADO", "land_estado", False),
    ]
    tiles.append(("🗓️", "Centro de Planificación", "Dirección: planificá la reacción y generá el ID de producción que el operario ejecuta.", "PLANIFICACION", "land_plan", False))
    tiles.append(("🧪", "Fórmulas", "Fórmulas con nombre por proceso/MP/producto: creá, editá y elegí la default que usa Planificación.", "FORMULAS", "land_formulas", False))
    tiles.append(("🤖", "Consultas IA", "Preguntá en lenguaje natural sobre camiones y lab (solo lectura).", "CHAT", "land_chat", False))
    tiles.append(("💰", "Cierres mensuales", "Rentabilidad: P&L mensual, dónde está el valor, márgenes por segmento, Q1 vs Q2, outliers e insights.", "CIERRES", "land_cierres", False))
    tiles.append(("🛂", "Dirección", "Aprobación de planificaciones fuera de norma (carga menor al 80% del equipo).", "DIRECCION", "land_direccion", False))
    tiles.append(("⚙️", "Admin", "Gestión de usuarios: alta, roles, sectores, reset PIN y accesos a la página.", "ADMIN", "land_admin", False))
    tiles = [t for t in tiles if puede_seccion(t[3])]

    for i in range(0, len(tiles), 3):
        cols = st.columns(3)
        for col, (icon, tit, desc, sec, key, prim) in zip(cols, tiles[i:i+3]):
            with col:
                with st.container(border=True):
                    st.markdown(f'<div class="tile-h">{icon} {tit}</div><div class="tile-d">{desc}</div>',
                                unsafe_allow_html=True)
                    if st.button("Entrar", type="primary", use_container_width=True, key=key):
                        go_to(sec)
    st.stop()

with st.sidebar:
    st.markdown(f"### 👤 {USR['nombre_full']}")
    st.caption(f"`{USR['nombre']}` · rol **{USR['rol']}**")
    if not _LOCKED_ONE:
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

# ---- estilo global: ya inyectado por inject_global_css() al inicio ----

# ---- Guardia de permisos: si no puede entrar a esta sección, afuera ----
if not puede_seccion(st.session_state.section):
    st.error("⛔ No tenés acceso a esta sección. Pedile al administrador que te la habilite (Admin → Accesos a la página).")
    st.session_state.section = None
    st.button("🏠 Volver al inicio", key="no_acc_home")
    st.stop()

# ---- Recordar la sección actual (cookie): si la página se recarga, vuelve acá ----
if st.session_state.get("_sec_cookie") != st.session_state.section:
    _auth.set_section_cookie(st.session_state.section)
    st.session_state._sec_cookie = st.session_state.section

# ---- Botón Home visible en TODAS las secciones (además del de la sidebar) ----
_hcol1, _hcol2 = st.columns([1, 4])
with _hcol1:
    if st.button("🏠 Inicio", key="btn_home_top", use_container_width=True,
                 help="Volver a la pantalla principal"):
        st.session_state.section = None
        st.rerun()

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
            cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
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
def tickets_lab_disponibles_por_codigo(codigo_producto, dias=180, limit=30, solo_evaluados=True):
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
    if solo_evaluados:
        where.append("t.lab_fecha IS NOT NULL")
    sql = (
        "SELECT t.transaccion AS ticket, ABS(t.peso_neto) AS kg, "
        "       LOWER(t.corriente) AS corriente, t.procedencia, "
        "       t.fecha_entrada, t.lab_fecha, t.lab_producto, t.lab_calidad, "
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
    _solo_ev = st.checkbox("Solo tickets evaluados en calidad por laboratorio", value=True,
                           key=f"{key_prefix}_soloev",
                           help="Garantiza que el producto del ticket fue verificado en laboratorio y "
                                "coincide con la materia prima que se busca tratar.")
    _df = tickets_lab_disponibles_por_codigo(codigo_producto, dias=dias, limit=limit, solo_evaluados=_solo_ev)
    _selected_str = ""
    if _df.empty:
        st.caption("Sin tickets evaluados en calidad para este producto en el período. "
                   "Desmarcá el filtro de arriba para ver todos, o usá el campo manual.")
    else:
        def _fmt(r):
            _f = r["fecha_entrada"]
            try:
                _f = pd.to_datetime(_f).strftime("%d/%m/%y")
            except Exception:
                _f = str(_f)
            _ac = r.get("lab_prc_acidez")
            _ac_txt = f" · ac {float(_ac)*100:.2f}%" if pd.notna(_ac) else ""
            _ag = r.get("lab_prc_agua")
            _ag_txt = f" · agua {float(_ag)*100:.2f}%" if pd.notna(_ag) else ""
            _lf = r.get("lab_fecha")
            _ev_txt = (f" · ✅ eval {pd.to_datetime(_lf).strftime('%d/%m/%y')}" if pd.notna(_lf)
                       else " · ⚠️ sin evaluación de calidad")
            _prod = (str(r.get("lab_producto")).strip() if pd.notna(r.get("lab_producto")) else codigo_producto)
            _cal = f"/{str(r.get('lab_calidad')).strip()}" if pd.notna(r.get("lab_calidad")) else ""
            return (f"{_prod}{_cal} · #{int(r['ticket'])} · {float(r['kg']):,.0f} kg neto · "
                    f"{(r['corriente'] or '—')} · {(r['procedencia'] or '—')} · "
                    f"{_f}{_ac_txt}{_ag_txt}{_ev_txt}")
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
                cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
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
            cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
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
# Duraciones por etapa: derivadas de dic_proceso_etapa (la MISMA tabla que se edita en 'Etapas/tiempos')
def _pk_to_sector_proc(pk):
    if pk in ("PRODUCCION_ARE", "DESGOMADO_ACUOSO"):
        return ("REACTORES", pk)
    return (pk, None)
if not proc_etapa.empty:
    duraciones_etapa = proc_etapa.copy()
    duraciones_etapa[["sector", "tipo_proceso"]] = duraciones_etapa["proceso_key"].apply(
        lambda pk: pd.Series(_pk_to_sector_proc(pk)))
    duraciones_etapa = duraciones_etapa[["sector", "tipo_proceso", "etapa",
                                         "duracion_target_min", "duracion_min_min", "duracion_max_min"]]
else:
    duraciones_etapa = pd.DataFrame(columns=["sector", "tipo_proceso", "etapa",
                                             "duracion_target_min", "duracion_min_min", "duracion_max_min"])
consumos_proceso = cat("""
    SELECT tipo_proceso, codigo_insumo, consumo_por_tn, unidad_consumo, base_referencia, nota
    FROM dic_consumo_proceso
""")
constantes     = cat("SELECT codigo, valor FROM dic_constante_proceso")
def K(cod, default=None):
    """Lookup de constante química."""
    r = constantes[constantes["codigo"]==cod]
    return float(r.iloc[0]["valor"]) if not r.empty else default
def _render_porteria(USR, cat, conectar):
        # =================== PORTERIA ===================
        st.subheader("\U0001f69b Ingresos de camiones")
        sub_dia, sub_hist, sub_eflu, sub_labcmp = st.tabs([
            "\U0001f4c5 Entrada diaria", "\U0001f4ca Revision historica",
            "\U0001f4c8 Por producto", "\U0001f9ea Lab por cliente"])

        # ---------------- ENTRADA DIARIA ----------------
        with sub_dia:
            _porteria_entrada_diaria(cat)

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

                df_eval = df_p[df_p.apply(
                    lambda r: _es_evaluable(r["corriente"], r.get("producto_base")), axis=1)].copy()
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
                    lambda r: ("no corresponde" if not _es_evaluable(r["corriente"], r.get("producto_base")) else r["evaluado"]), axis=1)
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


        # ---------------- DISPOSICION FINAL DE LIQUIDOS ----------------
        with sub_eflu:
            st.caption("Apertura por **producto base** (los evaluables con más movimiento): acumulados, "
                       "tendencia, comparación mensual y semanal. Efluentes líquidos es un producto más.")
            try:
                _topb = cat(
                    "SELECT producto_base, SUM(ABS(peso_neto)) kg FROM produccion.v_transacciones_limpias "
                    "WHERE fecha_entrada >= current_date - 365 AND peso_neto IS NOT NULL AND producto_base IS NOT NULL "
                    "  AND corriente IN (SELECT corriente FROM produccion.dic_corriente_config WHERE evaluable) "
                    "  AND upper(producto_base) NOT IN (SELECT upper(producto_base) FROM produccion.dic_producto_base_config WHERE NOT evaluable) "
                    "GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 20")
                _pb_opts = _topb["producto_base"].tolist()
            except Exception:
                _pb_opts = []
            if "DISPOSICION FINAL DE LIQUIDOS" not in _pb_opts:
                _pb_opts = ["DISPOSICION FINAL DE LIQUIDOS"] + _pb_opts
            cE0, cE1, cE2 = st.columns(3)
            pb_sel = cE0.selectbox("Producto base", _pb_opts,
                                   index=_pb_opts.index("DISPOSICION FINAL DE LIQUIDOS"),
                                   key="ef_pb",
                                   help="Productos base evaluables ordenados por kg movidos en los últimos 12 meses.")
            ef_desde = cE1.date_input("Desde", value=date(date.today().year,1,1), key="ef_desde")
            ef_hasta = cE2.date_input("Hasta", value=date.today(), key="ef_hasta")
            sql_ef = """
                SELECT fecha_entrada, hora_e, patente_chasis, cliente, transporte, procedencia,
                       (peso_neto * -1) AS peso_neto, evaluado
                FROM produccion.v_transacciones_limpias
                WHERE producto_base = %s
                  AND fecha_entrada IS NOT NULL
                  AND fecha_entrada >= %s AND fecha_entrada <= %s
                ORDER BY fecha_entrada
            """
            try:
                df_ef = cat(sql_ef, (pb_sel, ef_desde.isoformat(), ef_hasta.isoformat()))
            except Exception as e:
                st.exception(e); df_ef = pd.DataFrame()

            if not df_ef.empty:
                _clis = sorted(df_ef["cliente"].dropna().astype(str).str.strip().unique().tolist())
                cli_sel = st.multiselect("Cliente (vacío = todos)", _clis, key="ef_cli",
                                         help="Filtra todo el análisis (acumulados, comparaciones y CSV) a los clientes elegidos.")
                if cli_sel:
                    df_ef = df_ef[df_ef["cliente"].astype(str).str.strip().isin(cli_sel)]

            if df_ef.empty:
                st.info(f"No hay registros de {pb_sel} en el rango (revisá el filtro de cliente).")
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

                # Comparación semanal: misma semana del mes, entre meses (barras)
                st.markdown("**Comparación semanal — misma semana del mes, entre meses**")
                dsem = df_ef.copy()
                dsem["mes"] = dsem["fecha_entrada"].dt.to_period("M").astype(str)
                dsem["sem_mes"] = ((dsem["fecha_entrada"].dt.day - 1) // 7 + 1).clip(upper=5)
                _sem_hoy = min(5, (date.today().day - 1) // 7 + 1)
                cs1, cs2 = st.columns(2)
                sem_sel = cs1.selectbox("Semana del mes", [1, 2, 3, 4, 5], index=_sem_hoy - 1, key="ef_sem",
                                        help="Semana 1 = días 1-7 · semana 2 = 8-14 · semana 3 = 15-21 · semana 4 = 22-28 · semana 5 = 29-31.")
                meses_sem = cs2.multiselect("Meses a comparar", meses_disp, default=default_meses, key="ef_sem_meses")
                dsem = dsem[(dsem["sem_mes"] == sem_sel) & (dsem["mes"].isin(meses_sem))]
                if dsem.empty:
                    st.info("Sin datos para esa semana en los meses elegidos.")
                else:
                    tot_sem = (dsem.groupby("mes")
                               .agg(kg=("peso_neto", "sum"), viajes=("peso_neto", "size"))
                               .reindex(sorted(meses_sem)).fillna(0).reset_index())
                    tot_sem["TN"] = (tot_sem["kg"] / 1000).round(2)
                    _bar_sem = alt.Chart(tot_sem).mark_bar().encode(
                        x=alt.X("mes:N", title="mes", sort=sorted(meses_sem)),
                        y=alt.Y("TN:Q", title=f"TN netas · semana {sem_sel} del mes"),
                        tooltip=[alt.Tooltip("mes:N"), alt.Tooltip("TN:Q"), alt.Tooltip("viajes:Q")],
                    ).properties(height=300)
                    st.altair_chart(_bar_sem, use_container_width=True)
                    _d1, _d2 = (sem_sel - 1) * 7 + 1, min(sem_sel * 7, 31) if sem_sel < 5 else 31
                    st.caption(f"Compara los días {_d1}–{_d2} de cada mes ({pb_sel}). "
                               "Ojo con el mes en curso si la semana todavía no terminó.")

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

                st.download_button(f"⬇️ Descargar CSV {pb_sel}",
                                   df_ef.to_csv(index=False).encode("utf-8"),
                                   file_name=f"{pb_sel.lower().replace(' ', '_')}_{ef_desde}_{ef_hasta}.csv", mime="text/csv")

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
                      AND corriente IN {CORR_EVAL_SQL}{PROD_BASE_NO_EVAL_SQL}
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
                     f"corriente IN {CORR_EVAL_SQL}" + PROD_BASE_NO_EVAL_SQL,
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


def _porteria_entrada_diaria(cat):
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
                    df_d["_evbl"] = df_d.apply(
                        lambda r: _es_evaluable(r["corriente"], r.get("producto_base")), axis=1)
                    df_d["eval_estado"] = df_d.apply(
                        lambda r: ("no corresponde" if not r["_evbl"] else r["evaluado"]), axis=1)
                    df_evbl = df_d[df_d["_evbl"]]
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


def _render_estado_planta(cat, conectar=None, USR=None):
    st.title("📈 Estado de planta")
    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🏭 Tablero", "🧪 Bandeja lab", "🔗 Trazabilidad", "📉 Mermas", "🔔 Alertas", "💵 Margen por reacción", "🧫 Evaluaciones internas"])
    with t7:
        import pandas as pd
        st.caption("Evaluaciones internas de cada reacción. Si se cargó mal la **hora** o un **parámetro**, corregilo acá.")
        _reac = cat("SELECT DISTINCT b.identificador_unidad, b.id_batch "
                    "FROM produccion.fact_evaluacion_interna ei "
                    "JOIN produccion.fact_batch_proceso b ON b.id_batch=ei.id_batch "
                    "WHERE NOT ei.anulado AND b.identificador_unidad IS NOT NULL "
                    "ORDER BY b.id_batch DESC")
        if _reac is None or _reac.empty:
            st.info("Todavia no hay evaluaciones internas cargadas.")
        else:
            _ro = _reac["identificador_unidad"].tolist()
            _rsel = st.selectbox("Reaccion", _ro, key="ep_ei_reac")
            _bid = int(_reac.iloc[_ro.index(_rsel)]["id_batch"])
            _ev = cat("SELECT id_eval, ts, etapa, (mediciones->>'acidez')::numeric acidez, "
                      "(mediciones->>'temperatura')::numeric temperatura, (mediciones->>'fosforo')::numeric fosforo, "
                      "(mediciones->>'azufre')::numeric azufre, observaciones "
                      "FROM produccion.fact_evaluacion_interna WHERE id_batch=%s AND NOT anulado ORDER BY ts", (_bid,))
            if _ev is None or _ev.empty:
                st.info("Sin evaluaciones para esta reaccion.")
            else:
                st.dataframe(_ev.drop(columns=["id_eval"]).rename(columns={
                    "ts": "Hora", "etapa": "Etapa", "acidez": "Acidez", "temperatura": "Temp",
                    "fosforo": "Fosforo", "azufre": "Azufre", "observaciones": "Obs"}),
                    use_container_width=True, hide_index=True,
                    column_config={"Hora": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})
                if _ev["acidez"].notna().any():
                    st.caption("Caida de acidez en el tiempo")
                    st.line_chart(_ev.dropna(subset=["acidez"]).set_index("ts")["acidez"])
                st.divider()
                st.markdown("**Corregir una evaluacion**")
                _lbls = _ev.apply(lambda r: f"#{int(r['id_eval'])} - {pd.to_datetime(r['ts']).strftime('%d/%m %H:%M')} - "
                                            f"{r['etapa'] or ''} - ac {r['acidez'] if pd.notna(r['acidez']) else '-'}", axis=1).tolist()
                _pick = st.selectbox("Evaluacion a corregir", _lbls, key="ep_ei_pick")
                _row = _ev.iloc[_lbls.index(_pick)]
                _eid = int(_row["id_eval"]); _ts0 = pd.to_datetime(_row["ts"])
                def _vv(c):
                    return float(_row[c]) if pd.notna(_row[c]) else 0.0
                ec1, ec2, ec3 = st.columns(3)
                _f = ec1.date_input("Fecha", value=_ts0.date(), key="ep_ei_f")
                _h = ec2.time_input("Hora", value=_ts0.time(), key="ep_ei_h")
                _ac = ec3.number_input("Acidez %", value=_vv("acidez"), step=0.1, format="%.2f", key="ep_ei_ac")
                ec4, ec5, ec6 = st.columns(3)
                _tp = ec4.number_input("Temp C", value=_vv("temperatura"), step=1.0, key="ep_ei_tp")
                _fo = ec5.number_input("Fosforo (ppm)", value=_vv("fosforo"), step=1.0, key="ep_ei_fo")
                _az = ec6.number_input("Azufre (ppm)", value=_vv("azufre"), step=1.0, key="ep_ei_az")
                _ob = st.text_input("Observaciones", value=(_row["observaciones"] or ""), key="ep_ei_ob")
                if st.button("Guardar correccion", type="primary", key="ep_ei_save", use_container_width=True):
                    if conectar is None:
                        st.error("Sin conexion de escritura disponible.")
                    else:
                        try:
                            import datetime as _dtm
                            _newts = _dtm.datetime.combine(_f, _h)
                            with conectar(USR["id_usuario"]) as (conn, audit):
                                with conn.cursor() as cur:
                                    cur.execute(
                                        "UPDATE produccion.fact_evaluacion_interna SET ts=%s, "
                                        "mediciones = COALESCE(mediciones,'{}'::jsonb) || jsonb_build_object("
                                        "'acidez',%s::numeric,'temperatura',%s::numeric,'fosforo',%s::numeric,'azufre',%s::numeric), "
                                        "observaciones=%s WHERE id_eval=%s",
                                        (_newts, _ac, _tp, _fo, _az, (_ob or None), _eid))
                                audit.log("U", "fact_evaluacion_interna", _eid, {"ts": str(_newts), "acidez": _ac})
                            st.toast("Evaluacion corregida", icon="✅")
                            cat.clear(); st.rerun()
                        except Exception as e:
                            st.exception(e)
    with t1:
        st.caption("Cada reacción activa: en qué estado está y a quién está esperando.")
        df = cat("SELECT identificador_unidad AS \"Reacción\", tipo_proceso AS \"Proceso\", estado AS \"Estado\", "
                 "espera_a AS \"Espera a\", horas_activo AS \"Horas\", are_objetivo_kg AS \"ARE obj. kg\", "
                 "tanque_destino AS \"Tanque destino\" FROM produccion.v_estado_planta ORDER BY horas_activo DESC NULLS LAST")
        if df is None or df.empty:
            st.info("No hay reacciones activas.")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config={"Horas": st.column_config.NumberColumn(format="%.1f"),
                                        "ARE obj. kg": st.column_config.NumberColumn(format="%.0f")})
    with t2:
        st.caption("Reacciones que esperan resultado del laboratorio. Cargalo en Laboratorio → Producciones en marcha.")
        df = cat("SELECT identificador_unidad AS \"Reacción\", estado AS \"Estado\", "
                 "ticket_validacion_lab AS \"Ticket validación\", ticket_producto_final AS \"Ticket final\", "
                 "purga_glicerina_pct AS \"Purga %\", horas_esperando AS \"Horas esperando\" "
                 "FROM produccion.v_bandeja_lab ORDER BY horas_esperando DESC NULLS LAST")
        if df is None or df.empty:
            st.success("✅ Nada pendiente de laboratorio.")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config={"Horas esperando": st.column_config.NumberColumn(format="%.1f")})
    with t3:
        st.caption("La historia de un lote: qué entró, qué salió y a qué tanque.")
        _lotes = cat("SELECT DISTINCT identificador_unidad FROM produccion.v_trazabilidad_lote WHERE identificador_unidad IS NOT NULL ORDER BY 1")
        if _lotes is None or _lotes.empty:
            st.info("Sin movimientos por lote todavía.")
        else:
            _l = st.selectbox("Lote", _lotes["identificador_unidad"].tolist(), key="traz_lote")
            df = cat("SELECT to_char(momento,'DD/MM HH24:MI') AS \"Cuándo\", tipo_movimiento AS \"Mov\", rol AS \"Rol\", "
                     "producto AS \"Producto\", tanque AS \"Tanque\", ticket_porteria AS \"Ticket\", kg AS \"Kg\", litros AS \"Litros\" "
                     "FROM produccion.v_trazabilidad_lote WHERE identificador_unidad=%s ORDER BY momento", (_l,))
            if df is not None and not df.empty:
                st.dataframe(df, hide_index=True, use_container_width=True,
                             column_config={"Kg": st.column_config.NumberColumn(format="%.0f"),
                                            "Litros": st.column_config.NumberColumn(format="%.0f")})
            else:
                st.caption("Ese lote no tiene movimientos cargados.")
    with t4:
        st.caption("Planificado vs real por lote: rendimiento y mermas.")
        df = cat("SELECT identificador_unidad AS \"Reacción\", kg_inicial AS \"MP kg\", are_objetivo_kg AS \"ARE obj.\", "
                 "producido_kg AS \"ARE real\", rendimiento_vs_obj_pct AS \"% vs obj\", rendimiento_vs_mp_pct AS \"% vs MP\" "
                 "FROM produccion.v_mermas_lote ORDER BY fecha DESC NULLS LAST")
        if df is None or df.empty:
            st.info("Sin datos de rendimiento.")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config={k: st.column_config.NumberColumn(format="%.0f") for k in ["MP kg","ARE obj.","ARE real"]})
    with t5:
        st.caption("Cosas que requieren atención ahora.")
        df = cat("SELECT severidad, tipo, mensaje FROM produccion.v_alertas_planta "
                 "ORDER BY CASE severidad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END")
        if df is None or df.empty:
            st.success("✅ Sin alertas.")
        else:
            for _, r in df.iterrows():
                _ic = "🔴" if r["severidad"] == "alta" else "🟠"
                st.warning(f"{_ic} **{r['tipo']}** — {r['mensaje']}")

    with t6:
        import pandas as pd
        st.subheader("💵 Margen de transformación por reacción")
        st.caption("Cuánto vale lo que **sale** (ARE-B, que se exporta como AG-E) menos lo que **entra** "
                   "(materia prima + glicerina + KOH + fuel), por cada reacción. Es el negocio real a nivel de bacha: "
                   "acá se ve si una reacción ganó o perdió plata, y cuánto pesa el **rendimiento** (kg de ARE por kg de MP).")
        if conectar is not None and (USR or {}).get("rol") in ("SUPERVISOR", "ADMIN"):
            with st.expander("⚙️ Precios de referencia (editar)", expanded=False):
                st.caption("Venta del producto final (ARE-B = su valor como **AG-E exportado**), compra de cada MP (USD/TN), "
                           "insumos (glicerina, KOH, fuel en ARS por su unidad) y TC (ARS por USD).")
                _pr = cat("SELECT codigo, rol, precio, unidad, moneda, COALESCE(descripcion,'') descripcion "
                          "FROM produccion.dim_precio_ref ORDER BY rol, codigo")
                if _pr is not None and not _pr.empty:
                    _ped = st.data_editor(_pr.rename(columns={"codigo":"Código","rol":"Rol","precio":"Precio","unidad":"Unidad","moneda":"Moneda","descripcion":"Descripción"}),
                                          hide_index=True, use_container_width=True, key="precio_ref_ed",
                                          disabled=["Código","Rol","Unidad","Moneda"])
                    if st.button("💾 Guardar precios", type="primary", key="precio_ref_save"):
                        try:
                            with conectar(int(USR["id_usuario"])) as (conn, audit):
                                with conn.cursor() as cur:
                                    for _, rr in _ped.iterrows():
                                        cur.execute("UPDATE produccion.dim_precio_ref SET precio=%s, actualizado_en=now() WHERE codigo=%s",
                                                    (float(rr["Precio"]) if pd.notna(rr["Precio"]) else None, rr["Código"]))
                                audit.log("U", "dim_precio_ref", 0, {"n": len(_ped)})
                            st.success("Precios actualizados."); cat.clear(); st.rerun()
                        except Exception as _e:
                            st.exception(_e)
        dfm = cat("SELECT identificador_unidad, mp_codigo, kg_mp, kg_are, rendimiento_pct, rendimiento_obj_pct, "
                  "ingreso_are_usd, costo_mp_usd, costo_insumos_usd, margen_usd, margen_por_tn_mp_usd, margen_pct, impacto_rendimiento_usd "
                  "FROM produccion.v_margen_transformacion ORDER BY fecha DESC NULLS LAST")
        if dfm is None or dfm.empty:
            st.info("No hay reacciones de ARE para calcular margen.")
        else:
            _tm = pd.to_numeric(dfm["margen_usd"], errors="coerce").sum()
            k1, k2, k3 = st.columns(3)
            k1.metric("Reacciones", len(dfm))
            k2.metric("Margen total", f"{_tm:,.0f} USD")
            k3.metric("Margen medio / TN de MP", f"{pd.to_numeric(dfm['margen_por_tn_mp_usd'],errors='coerce').mean():,.0f} USD")
            st.dataframe(dfm.rename(columns={"identificador_unidad":"Reacción","mp_codigo":"MP","kg_mp":"kg MP","kg_are":"kg ARE",
                "rendimiento_pct":"Rend. %","rendimiento_obj_pct":"Rend. obj. %","ingreso_are_usd":"Ingreso USD","costo_mp_usd":"Costo MP USD",
                "costo_insumos_usd":"Insumos USD","margen_usd":"Margen USD","margen_por_tn_mp_usd":"Margen/TN MP","margen_pct":"Margen %",
                "impacto_rendimiento_usd":"Δ rendim. USD"}),
                hide_index=True, use_container_width=True,
                column_config={c: st.column_config.NumberColumn(format="%.0f") for c in
                               ["kg MP","kg ARE","Ingreso USD","Costo MP USD","Insumos USD","Margen USD","Margen/TN MP","Δ rendim. USD"]})
            st.divider()
            st.markdown("**🔎 Desglose por ítem — cantidades y precios (para validar)**")
            _reacs = dfm["identificador_unidad"].tolist()
            _rsel = st.selectbox("Reacción", _reacs, key="mgn_desg_reac")
            _rowm = dfm[dfm["identificador_unidad"] == _rsel].iloc[0]
            mm1, mm2, mm3, mm4 = st.columns(4)
            mm1.metric("Ingreso ARE", f"{float(_rowm['ingreso_are_usd']):,.0f} USD")
            mm2.metric("Costo MP", f"{float(_rowm['costo_mp_usd']):,.0f} USD")
            mm3.metric("Insumos", f"{float(_rowm['costo_insumos_usd']):,.0f} USD")
            mm4.metric("Margen", f"{float(_rowm['margen_usd']):,.0f} USD")
            _dg = cat("SELECT concepto, cantidad, unidad, precio, precio_unidad, usd "
                      "FROM produccion.v_margen_desglose WHERE reaccion=%s ORDER BY orden", (_rsel,))
            if _dg is not None and not _dg.empty:
                st.dataframe(_dg.rename(columns={"concepto": "Concepto", "cantidad": "Cantidad", "unidad": "Unidad",
                    "precio": "Precio", "precio_unidad": "Precio unidad", "usd": "USD"}),
                    hide_index=True, use_container_width=True, column_config={
                        "Cantidad": st.column_config.NumberColumn(format="%.0f"),
                        "Precio": st.column_config.NumberColumn(format="%.2f"),
                        "USD": st.column_config.NumberColumn(format="%.0f")})
                st.caption("Cantidad × Precio = USD. Positivo = ingreso, negativo = costo. Los insumos en ARS se pasan a USD con el TC. "
                           "Los precios se editan arriba (solo dirección).")
                _wf = pd.DataFrame({"Concepto": ["Ingreso ARE", "− Costo MP", "− Insumos", "= Margen"],
                                    "USD": [float(_rowm["ingreso_are_usd"]), -float(_rowm["costo_mp_usd"]),
                                            -float(_rowm["costo_insumos_usd"]), float(_rowm["margen_usd"])]})
                st.bar_chart(_wf.set_index("Concepto"), use_container_width=True)
            st.info("**Cómo leerlo:** el **rendimiento** (kg ARE / kg MP) es la palanca. Si baja (MP con más agua o proceso ineficiente), "
                    "sale menos ARE por la misma materia prima y el margen se achica. **Δ rendim. USD** = lo que se ganó/perdió "
                    "respecto del rendimiento objetivo de la fórmula. Los precios de referencia se editan arriba (solo dirección).")


def _lab_asignacion(cat, conectar=None, USR=None):
    """Visualización en Laboratorio: ticket → tanque (Portería sugerido / Producción ejecutado) + capacidad antes/después."""
    import pandas as pd
    st.subheader("📦 Asignación a tanque de acopio")
    _src = st.radio("Origen", ["🚛 Portería (ingresos evaluados)", "🏭 Producción (ARE final)"],
                    horizontal=True, key="lab_asig_src", label_visibility="collapsed")
    _es_port = _src.startswith("🚛")
    if _es_port:
        st.caption("Ingresos evaluados por laboratorio. El sistema **sugiere** el tanque de acopio por parámetros + capacidad; "
                   "se confirma y genera el movimiento al cargar el ingreso por la app. El 'después' es proyectado.")
        df = cat("SELECT fecha, ticket, producto, calidad, rechazado, cliente, kg_ticket, "
                 "prc_acidez, prc_agua, prc_sedimentos, ppm_azufre, ppm_fosforo, id_tanque_asignado, "
                 "tanque_asignado, kg_asignados, litros_asignados, capacidad_litros, "
                 "stock_antes_l, stock_despues_l, disponible_antes_l, disponible_despues_l, motivo "
                 "FROM produccion.v_lab_asignacion_porteria ORDER BY fecha DESC NULLS LAST LIMIT 500")
    else:
        st.caption("Producto final ARE: el tanque y el movimiento ya se definen en Planificación/Decantación (kg de producción).")
        df = cat("SELECT fecha, ticket, producto, calidad, cliente, kg_ticket, "
                 "prc_acidez, prc_agua, prc_sedimentos, ppm_azufre, ppm_fosforo, "
                 "tanque_asignado, kg_asignados, litros_asignados, capacidad_litros, "
                 "stock_antes_l, stock_despues_l, disponible_antes_l, disponible_despues_l, motivo "
                 "FROM produccion.v_lab_asignacion_tanque ORDER BY fecha DESC NULLS LAST LIMIT 300")
    if df is None or df.empty:
        st.info("Sin registros para esta vista.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Evaluaciones", len(df))
    c2.metric("Con tanque " + ("sugerido" if _es_port else "asignado"), int(df["tanque_asignado"].notna().sum()))
    c3.metric("Sin tanque (revisar)", int(df["tanque_asignado"].isna().sum()))
    cols = {
        "Fecha": pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%d/%m %H:%M"),
        "Ticket": df["ticket"], "Producto": df["producto"], "Calidad": df["calidad"],
    }
    if _es_port:
        cols["Rechazado"] = df["rechazado"]
    cols.update({
        "Cliente": df["cliente"], "Kg ticket": df["kg_ticket"],
        "Acidez %": df["prc_acidez"], "Agua %": df["prc_agua"], "Sedim %": df["prc_sedimentos"],
        "Azufre ppm": df["ppm_azufre"], "Fósforo ppm": df["ppm_fosforo"],
        "Tanque": df["tanque_asignado"].fillna("— sin tanque —"),
        "Kg asign.": df["kg_asignados"], "Litros asign.": df["litros_asignados"], "Cap. L": df["capacidad_litros"],
        "Disp. antes L": df["disponible_antes_l"], "Disp. después L": df["disponible_despues_l"],
        "Motivo": df["motivo"],
    })
    _confdf = None
    if _es_port:
        try:
            _confdf = cat("SELECT ticket, fue_al_sugerido, id_tanque_real, motivo_desvio, "
                          "(SELECT nombre FROM produccion.dim_tanque dt WHERE dt.id_tanque=c.id_tanque_real) AS tanque_real "
                          "FROM produccion.fact_asignacion_tanque_real c")
        except Exception:
            _confdf = None
        if _confdf is not None and not _confdf.empty:
            _m = _confdf.set_index(_confdf["ticket"].astype(str))
            _tk = df["ticket"].astype(str)
            cols["¿Fue?"] = _tk.map(lambda x: ("✅ Sí" if (x in _m.index and bool(_m.loc[x, "fue_al_sugerido"])) else ("❌ No" if x in _m.index else "—")))
            cols["Tanque real"] = _tk.map(lambda x: (_m.loc[x, "tanque_real"] if x in _m.index else None))
            cols["Motivo desvío"] = _tk.map(lambda x: (_m.loc[x, "motivo_desvio"] if x in _m.index else None))
    _show = pd.DataFrame(cols)
    _nf = st.column_config.NumberColumn(format="%.0f")
    st.dataframe(_show, hide_index=True, use_container_width=True,
                 column_config={**{k: _nf for k in ["Kg ticket","Kg asign.","Litros asign.","Cap. L","Disp. antes L","Disp. después L"]},
                                "Motivo": st.column_config.TextColumn("Motivo", width="large")})
    if _es_port:
        with st.expander("🧠 Aprendizaje de asignación (producto → tanque)", expanded=False):
            st.caption("Score = aciertos − desvíos, aprendido de tus confirmaciones. Entre los tanques válidos "
                       "(materia prima + parámetros + disponibilidad) la sugerencia prioriza el de mayor score.")
            _pref = cat("SELECT p.codigo_producto AS \"Producto\", t.nombre AS \"Tanque\", "
                        "pr.aciertos AS \"Aciertos\", pr.desvios AS \"Desvíos\", pr.score AS \"Score\", "
                        "pr.ultimo_motivo AS \"Último motivo\" "
                        "FROM produccion.dic_tanque_preferencia pr "
                        "JOIN produccion.dim_producto p ON p.id_producto=pr.id_producto "
                        "JOIN produccion.dim_tanque t ON t.id_tanque=pr.id_tanque "
                        "ORDER BY p.codigo_producto, pr.score DESC")
            if _pref is not None and not _pref.empty:
                st.dataframe(_pref, hide_index=True, use_container_width=True)
            else:
                st.info("Todavía no hay aprendizaje. Confirmá tanques reales abajo (fue / no fue + motivo) y la sugerencia se va afinando.")
    _conf = df[df["tanque_asignado"].notna()].reset_index(drop=True)
    if not _conf.empty:
        _opts = (_conf["ticket"].astype(str) + " · " + _conf["producto"].fillna("") + " → " + _conf["tanque_asignado"]).tolist()
        _sel = st.selectbox("Ver capacidad del tanque (antes → después)", _opts, key="lab_asig_sel2")
        r = _conf.iloc[_opts.index(_sel)]
        cap = float(r["capacidad_litros"] or 0); a = float(r["stock_antes_l"] or 0); d = float(r["stock_despues_l"] or 0)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Capacidad tanque", f"{cap:,.0f} L")
        m2.metric("Ocupado antes", f"{a:,.0f} L", help=f"{(a/cap*100 if cap else 0):.0f}% ocupación")
        m3.metric(("Entraría" if _es_port else "Entra") + " (ticket)", f"+{float(r['litros_asignados'] or 0):,.0f} L", f"{float(r['kg_asignados'] or 0):,.0f} kg")
        m4.metric("Ocupado después", f"{d:,.0f} L", help=f"{(d/cap*100 if cap else 0):.0f}% ocupación")
        st.progress(min(d/cap, 1.0) if cap else 0.0,
                    text=f"Disponible {'tras el ingreso' if _es_port else 'después'}: {float(r['disponible_despues_l'] or 0):,.0f} L de {cap:,.0f} L")

    if _es_port and conectar is not None:
        st.divider()
        st.markdown("**✅ ¿Fue efectivamente a ese tanque?** Imputá el tanque real; si no fue el sugerido, justificá.")
        _cf = df[df["tanque_asignado"].notna()].reset_index(drop=True)
        if _cf.empty:
            st.caption("No hay tickets con tanque sugerido para confirmar.")
        else:
            _o = (_cf["ticket"].astype(str) + " · " + _cf["producto"].fillna("") + " → " + _cf["tanque_asignado"]).tolist()
            _sc = st.selectbox("Ticket a confirmar", _o, key="lab_asig_conf_sel")
            _rr = _cf.iloc[_o.index(_sc)]
            _tkc = str(_rr["ticket"])
            _sug_id = int(_rr["id_tanque_asignado"]) if pd.notna(_rr.get("id_tanque_asignado")) else None
            _fue = st.radio("¿Fue al tanque sugerido?", ["Sí", "No"], horizontal=True, key="lab_asig_fue")
            _treal = _sug_id; _mot = None; _obs = ""
            if _fue == "No":
                _tanks = cat("SELECT id_tanque, nombre, codigo FROM produccion.dim_tanque WHERE COALESCE(activo,true) ORDER BY nombre")
                _tmap = {f"{rr2['nombre']} ({rr2['codigo']})": int(rr2['id_tanque']) for _i, rr2 in _tanks.iterrows()} if _tanks is not None and not _tanks.empty else {}
                _tsel = st.selectbox("Tanque real", list(_tmap.keys()), key="lab_asig_treal")
                _treal = _tmap.get(_tsel)
                _mot = st.selectbox("Motivo del desvío", ["DISPONIBILIDAD", "PARAMETROS", "MATERIA_PRIMA", "OTRO"], key="lab_asig_mot")
                _obs = st.text_input("Observación", key="lab_asig_obs")
            if st.button("💾 Guardar confirmación", type="primary", key="lab_asig_save"):
                try:
                    _uid = int((USR or {}).get("id_usuario") or 0)
                    with conectar(_uid) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO produccion.fact_asignacion_tanque_real "
                                "(ticket,id_tanque_sugerido,fue_al_sugerido,id_tanque_real,motivo_desvio,observacion,usuario,actualizado_en) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,now()) "
                                "ON CONFLICT (ticket) DO UPDATE SET id_tanque_sugerido=EXCLUDED.id_tanque_sugerido, "
                                "fue_al_sugerido=EXCLUDED.fue_al_sugerido, id_tanque_real=EXCLUDED.id_tanque_real, "
                                "motivo_desvio=EXCLUDED.motivo_desvio, observacion=EXCLUDED.observacion, "
                                "usuario=EXCLUDED.usuario, actualizado_en=now()",
                                (_tkc, _sug_id, (_fue == "Sí"), _treal, _mot, (_obs or None),
                                 str((USR or {}).get("nombre") or (USR or {}).get("id_usuario") or "")))
                        audit.log("U", "fact_asignacion_tanque_real", 0, {"ticket": _tkc, "fue": _fue})
                    st.success("Confirmación guardada.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)


def _form_param_tanque(cat, conectar, USR):
    if st.session_state.pop("param_tk_celebrar", False):
        st.toast("Parámetros del tanque cargados", icon="✅")
    st.markdown("### 🧪 Cargar parámetros de laboratorio por tanque")
    st.caption("El laboratorio actualiza acá los parámetros del tanque. Queda histórico con fecha y usuario, "
               "y producción los hereda al instante al elegir el tanque como fuente.")
    _lt = cat("SELECT t.id_tanque, t.codigo, t.nombre, t.sector, t.id_producto_principal, "
              "p.codigo_producto AS prod, pp.acidez_pct, pp.agua_pct, pp.sedimentos_pct, "
              "pp.densidad_g_ml, pp.ppm_azufre, pp.ppm_fosforo, pp.glicerina_pct, pp.producto_pct, "
              "pp.corriente, pp.ultima_evaluacion_ts "
              "FROM produccion.dim_tanque t "
              "LEFT JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
              "LEFT JOIN produccion.fact_param_tanque pp ON pp.id_tanque=t.id_tanque AND pp.id_producto=t.id_producto_principal "
              "WHERE COALESCE(t.activo,true) ORDER BY t.sector, t.nombre")
    if _lt.empty:
        st.info("No hay tanques.")
    else:
        _ls1, _ls2 = st.columns(2)
        _lsec = _ls1.selectbox("Sector", ["Todos"] + sorted(_lt["sector"].dropna().unique().tolist()), key="lab_sec")
        _ld = _lt if _lsec == "Todos" else _lt[_lt["sector"] == _lsec]
        def _lab_opt(r):
            flag = "✅" if pd.notna(r.get("ultima_evaluacion_ts")) else "⚠️ s/param"
            return f"{r['nombre']} · {r['codigo']} · {r['prod'] or 'sin producto'} · {flag}"
        _lopts = _ld.apply(_lab_opt, axis=1).tolist()
        _lsel = _ls2.selectbox(f"Tanque ({len(_ld)})", _lopts, key="lab_tk")
        _lr = _ld.iloc[_lopts.index(_lsel)]
        _lidt = int(_lr["id_tanque"]); _lpid = _lr["id_producto_principal"]
        if pd.isna(_lpid):
            st.warning("Este tanque no tiene **producto asignado**. Asigná el producto en la pestaña *Editar tanque* "
                       "antes de cargar parámetros (los parámetros van por tanque + producto).")
        else:
            _ev = _lr.get("ultima_evaluacion_ts")
            st.caption(f"Producto actual: **{_lr['prod']}** · última evaluación: "
                       f"{pd.to_datetime(_ev).strftime('%d/%m/%Y %H:%M') if pd.notna(_ev) else 'sin evaluación'}")
            def _pv(col, d=0.0):
                v = _lr.get(col)
                return float(v) if pd.notna(v) else float(d)
            lc1, lc2, lc3 = st.columns(3)
            _ac = lc1.number_input("Acidez %", min_value=0.0, value=_pv("acidez_pct"), step=0.1, format="%.2f", key="lab_ac")
            _ag = lc2.number_input("Agua %", min_value=0.0, value=_pv("agua_pct"), step=0.1, format="%.2f", key="lab_ag")
            _se = lc3.number_input("Sedimentos %", min_value=0.0, value=_pv("sedimentos_pct"), step=0.1, format="%.2f", key="lab_se")
            lc4, lc5, lc6 = st.columns(3)
            _az = lc4.number_input("Azufre (ppm)", min_value=0.0, value=_pv("ppm_azufre"), step=1.0, format="%.1f", key="lab_az")
            _fo = lc5.number_input("Fósforo (ppm)", min_value=0.0, value=_pv("ppm_fosforo"), step=1.0, format="%.1f", key="lab_fo")
            _de = lc6.number_input("Densidad g/ml", min_value=0.0, value=_pv("densidad_g_ml", 0.91), step=0.01, format="%.3f", key="lab_de")
            lc7, lc8, _lc9 = st.columns(3)
            _gl = lc7.number_input("Glicerina %", min_value=0.0, value=_pv("glicerina_pct"), step=0.1, format="%.2f", key="lab_gl")
            _pr = lc8.number_input("Producto %", min_value=0.0, value=_pv("producto_pct"), step=0.1, format="%.2f", key="lab_pr")
            _corr_opts = ["", "VEGETAL", "ANIMAL", "INSUMO", "MIXTA"]
            _corr_cur = str(_lr.get("corriente")).upper() if pd.notna(_lr.get("corriente")) else ""
            _co = st.selectbox("Corriente", _corr_opts,
                               index=_corr_opts.index(_corr_cur) if _corr_cur in _corr_opts else 0, key="lab_co")
            _cm = st.text_input("Comentario", max_chars=200, key="lab_cm")
            if st.button("💾 Guardar parámetros", type="primary", use_container_width=True, key="lab_save"):
                try:
                    with conectar(USR["id_usuario"]) as (conn, audit):
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO produccion.fact_param_tanque "
                                "(id_tanque,id_producto,corriente,evaluado,ultima_evaluacion_ts,"
                                " acidez_pct,agua_pct,sedimentos_pct,densidad_g_ml,ppm_azufre,ppm_fosforo,"
                                " glicerina_pct,producto_pct,parametros_extra,actualizado_en) "
                                "VALUES (%s,%s,%s,true,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) "
                                "ON CONFLICT (id_tanque,id_producto) DO UPDATE SET "
                                " corriente=EXCLUDED.corriente, evaluado=true, ultima_evaluacion_ts=now(), "
                                " acidez_pct=EXCLUDED.acidez_pct, agua_pct=EXCLUDED.agua_pct, "
                                " sedimentos_pct=EXCLUDED.sedimentos_pct, densidad_g_ml=EXCLUDED.densidad_g_ml, "
                                " ppm_azufre=EXCLUDED.ppm_azufre, ppm_fosforo=EXCLUDED.ppm_fosforo, "
                                " glicerina_pct=EXCLUDED.glicerina_pct, producto_pct=EXCLUDED.producto_pct, "
                                " parametros_extra=COALESCE(produccion.fact_param_tanque.parametros_extra,'{}'::jsonb)||EXCLUDED.parametros_extra, "
                                " actualizado_en=now()",
                                (_lidt, int(_lpid), (_co or None),
                                 float(_ac), float(_ag), float(_se), float(_de), float(_az), float(_fo),
                                 float(_gl), float(_pr),
                                 __import__("json").dumps({"comentario": _cm} if _cm else {})))
                        audit.log("U", "fact_param_tanque", _lidt,
                                  {"acidez_pct": float(_ac), "ppm_azufre": float(_az), "ppm_fosforo": float(_fo)})
                    st.success(f"Parámetros guardados para {_lr['nombre']} · {_lr['prod']}.")
                    st.session_state["param_tk_celebrar"] = True
                    cat.clear()
                    st.rerun()
                except Exception as e:
                    st.exception(e)
        st.divider()
        st.markdown("**Histórico reciente de este tanque**")
        _hist = cat("SELECT registrado_en, origen, acidez_pct, agua_pct, sedimentos_pct, glicerina_pct, producto_pct, ppm_azufre, ppm_fosforo, corriente "
                    "FROM produccion.fact_param_tanque_hist WHERE id_tanque=%s "
                    "ORDER BY registrado_en DESC LIMIT 10", (_lidt,))
        if _hist.empty:
            st.caption("Sin historial todavía.")
        else:
            st.dataframe(_hist.rename(columns={"registrado_en":"Fecha","origen":"Origen","acidez_pct":"Acidez %",
                         "agua_pct":"Agua %","sedimentos_pct":"Sed %","glicerina_pct":"Glicerina %","producto_pct":"Producto %",
                         "ppm_azufre":"Azufre","ppm_fosforo":"Fósforo",
                         "corriente":"Corriente"}), use_container_width=True, hide_index=True,
                         column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})


bienes_uso_full = cat("SELECT id_bien_uso, codigo, nombre_ui, capacidad_max_l, consumo_fuel_kg_x_tn, consumo_naoh_kg_x_tn, consumo_potasio_kg_x_tn, koh_kg_fijo, fuel_oil_l_fijo, reposo_horas FROM dim_bien_uso WHERE activo ORDER BY codigo")
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


def selector_fuente_mp(cod, key_prefix):
    """Selector opcional de fuente de la materia prima: ticket de porteria o tanque.
    Si es tanque, muestra el stock vivo (vw_stock_tanque_actual) y descuenta al guardar.
    Devuelve dict {'fuente','id_tanque','kg','ticket','stock_kg'}."""
    op = st.radio(
        "Fuente de la materia prima",
        ["🎟️ Ticket de portería", "🛢️ Tanque"],
        horizontal=True, key=f"{key_prefix}_fte",
        help="Pesada por ticket de portería, o descontar del stock de un tanque que contenga este producto.",
    )
    if "Tanque" not in str(op):
        return {"fuente": "TICKET", "id_tanque": None, "kg": 0.0, "ticket": None, "stock_kg": None}
    try:
        df = cat(
            "SELECT v.id_tanque, v.codigo, v.nombre, COALESCE(v.kg_actual,0) kg, "
            "COALESCE(v.litros_actual,0) lt, v.capacidad_litros cap, "
            "(pt.id_param IS NOT NULL) tiene_param, pt.acidez_pct, pt.ultima_evaluacion_ts "
            "FROM produccion.vw_stock_tanque_actual v "
            "JOIN produccion.dim_tanque t ON t.id_tanque=v.id_tanque "
            "JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal AND p.codigo_producto=%s "
            "LEFT JOIN produccion.fact_param_tanque pt ON pt.id_tanque=v.id_tanque AND pt.id_producto=t.id_producto_principal "
            "WHERE COALESCE(v.litros_actual,0) > 0 "
            "ORDER BY kg DESC NULLS LAST", (cod,))
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        st.warning(f"No hay tanques **con stock** de **{cod}**. Usá ticket de portería.")
        return {"fuente": "TICKET", "id_tanque": None, "kg": 0.0, "ticket": None, "stock_kg": None}
    def _lbl_fte(r):
        flag = "✅ con parámetros" if r.get("tiene_param") else "⚠️ SIN parámetros"
        return f"{r['codigo']} · {r['nombre']} · {float(r['kg'])/1000:,.1f} TN · {flag}"
    opts = df.apply(_lbl_fte, axis=1).tolist()
    sel = st.selectbox(f"Tanque con {cod}", opts, key=f"{key_prefix}_tk")
    row = df.iloc[opts.index(sel)]
    _stock_kg = float(row["kg"] or 0)
    _stock_lt = float(row["lt"] or 0)
    _dens = (_stock_kg / _stock_lt) if _stock_lt > 0 else (densidad_de(cod) or 0.92)
    if not row.get("tiene_param"):
        st.warning(f"⚠️ **{row['codigo']}** no tiene parámetros de laboratorio cargados. "
                   "Cargalos en *Tanques → 🧪 Laboratorio* para que la receta herede acidez/agua/azufre.")
    st.markdown(
        f"<div class='kpi' style='margin:6px 0'><div class='l'>Stock disponible en tanque</div>"
        f"<div class='v'>{_stock_lt:,.0f}<span style='font-size:1rem;font-weight:700'> L</span></div>"
        f"<div class='s'>{_stock_kg:,.0f} kg · {_stock_kg/1000:,.1f} TN · capacidad {int(row['cap'] or 0):,} L</div></div>",
        unsafe_allow_html=True)
    lt = float(st.number_input(
        f"Litros a usar de {cod}", min_value=0.0,
        value=float(round(_stock_lt)) if _stock_lt else 0.0, step=100.0, key=f"{key_prefix}_lt"))
    kg = lt * _dens
    st.caption(f"≈ {kg:,.0f} kg · {kg/1000:,.2f} TN  ·  densidad {_dens:.3f} kg/L")
    if lt > _stock_lt:
        st.warning("⚠️ La cantidad supera el stock actual del tanque (igual se registrará el movimiento).")
    return {"fuente": "TANQUE", "id_tanque": int(row["id_tanque"]), "kg": kg, "ticket": None, "stock_kg": _stock_kg}


def fuente_mp_combinada(cod, key_prefix, target_kg=None, permite_multiselect=False):
    """Fuente de la MP combinando PORTERÍA (tickets) + TANQUE. Los parámetros de
    laboratorio resultan del PROMEDIO PONDERADO POR KG (toneladas) de las fuentes.
    Devuelve (kg_total, portions, lab_avg)."""
    st.markdown("**📦 Fuente de la materia prima** — combiná portería y/o tanque hasta la cantidad")
    portions = []
    parts_lab = []   # [(kg, params_dict)] para promedio ponderado por kg
    parts_corr = []  # [(kg, corriente)] -> la corriente la define la fuente (no el producto)
    kg_port = 0.0
    kg_tk = 0.0
    cP, cT = st.columns(2)
    with cP:
        up = st.checkbox("🎟️ Portería (tickets)", value=True, key=f"{key_prefix}_up")
        if up:
            tkstr = _ui_multiselect_tickets(cod, key_prefix=f"{key_prefix}_ms", dias=365, limit=20, max_tickets=3)
            _det, _avg, _ml, _mp, _mapp = params_de_tickets_lab(tkstr, cod)
            kg_port = float(pd.to_numeric(_det["kg"], errors="coerce").sum()) if (not _det.empty and "kg" in _det.columns) else 0.0
            if kg_port > 0:
                _dpc = densidad_de(cod) or 0.92
                st.caption(f"Portería: **{kg_port/_dpc:,.0f} L** · {kg_port:,.0f} kg · {kg_port/1000:,.2f} TN")
                portions.append({"fuente": "TICKET", "ticket": (tkstr or None), "id_tanque": None, "kg": kg_port})
                parts_lab.append((kg_port, _avg or {}))
                try:
                    import re as _rec
                    _tn = [int(x) for x in _rec.findall(r"\d+", tkstr or "")]
                    if _tn:
                        _dfc = cat("SELECT UPPER(corriente) corr, ABS(peso_neto) kg "
                                   "FROM produccion.v_transacciones_limpias "
                                   "WHERE transaccion = ANY(%s) AND corriente IS NOT NULL", (_tn,))
                        if not _dfc.empty:
                            parts_corr.append((kg_port, _dfc.groupby("corr")["kg"].sum().idxmax()))
                except Exception:
                    pass
    with cT:
        ut = st.checkbox("🛢️ Tanque", key=f"{key_prefix}_ut")
        if ut:
            try:
                df = cat(
                    "SELECT v.id_tanque, v.codigo, v.nombre, COALESCE(v.kg_actual,0) kg, COALESCE(v.litros_actual,0) lt, "
                    "p.codigo_producto prod_cod, p.nombre_producto prod_nombre, "
                    "pt.acidez_pct, pt.agua_pct, pt.sedimentos_pct, pt.densidad_g_ml, pt.ppm_azufre, pt.ppm_fosforo, "
                    "pt.ultima_evaluacion_ts, pt.corriente, (pt.id_param IS NOT NULL) tiene_param "
                    "FROM produccion.vw_stock_tanque_actual v "
                    "JOIN produccion.dim_tanque t ON t.id_tanque=v.id_tanque "
                    "JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal AND p.codigo_producto=%s "
                    "LEFT JOIN produccion.fact_param_tanque pt ON pt.id_tanque=v.id_tanque AND pt.id_producto=t.id_producto_principal "
                    "WHERE COALESCE(v.litros_actual,0) > 0 "
                    "ORDER BY kg DESC NULLS LAST", (cod,))
            except Exception:
                df = pd.DataFrame()
            if df is None or df.empty:
                st.caption(f"Sin tanques **con stock** de {cod}.")
            else:
                def _tlab(r):
                    s = f"{r['prod_cod']} · {r['codigo']} ({r['nombre']}) · {float(r['lt']):,.0f} L"
                    if pd.notna(r.get('corriente')):
                        s += f" · {str(r['corriente']).lower()}"
                    s += f" · ac {float(r['acidez_pct']):.2f}%" if pd.notna(r.get('acidez_pct')) else " · ac s/d"
                    s += " · ✅ parámetros" if r.get('tiene_param') else " · ⚠️ SIN parámetros"
                    return s
                opts = df.apply(_tlab, axis=1).tolist()
                sels = st.multiselect(f"Tanques con {cod} (hasta 2)", opts, key=f"{key_prefix}_tksel",
                                      help="Combiná hasta 2 tanques. El producto del tanque se ve al inicio de cada opción.")
                if len(sels) > 2:
                    st.warning("Máximo 2 tanques: se toman los primeros 2.")
                    sels = sels[:2]
                for _i, _s in enumerate(sels):
                    row = df.iloc[opts.index(_s)]
                    _stock = float(row["kg"] or 0)
                    _stock_lt = float(row.get("lt") or 0)
                    _denst = (_stock / _stock_lt) if _stock_lt > 0 else (float(row["densidad_g_ml"]) if pd.notna(row.get("densidad_g_ml")) else (densidad_de(cod) or 0.92))
                    if not row.get("tiene_param"):
                        st.warning(f"⚠️ **{row['codigo']}** no tiene parámetros de laboratorio cargados. "
                                   "La receta no podrá heredar acidez/agua/azufre. Cargalos en *Tanques → 🧪 Laboratorio*.")
                    _tank_avg = {}
                    for _k, _dst, _div in [("acidez_pct", "prc_acidez", 100.0), ("agua_pct", "prc_agua", 100.0),
                                           ("sedimentos_pct", "prc_sedimentos", 100.0), ("densidad_g_ml", "densidad__g_ml", 1.0),
                                           ("ppm_azufre", "ppm_azufre", 1.0), ("ppm_fosforo", "ppm_fosforo", 1.0)]:
                        _v = row.get(_k)
                        if pd.notna(_v):
                            _tank_avg[_dst] = float(_v) / _div
                    _ev = row.get("ultima_evaluacion_ts")
                    _ev_txt = pd.to_datetime(_ev).strftime("%d/%m/%Y") if pd.notna(_ev) else "sin evaluación"
                    _ac_txt = f"{float(row['acidez_pct']):.2f}%" if pd.notna(row.get("acidez_pct")) else "s/d"
                    st.caption(f"**{row['codigo']}** — Disponible: {_stock_lt:,.0f} L · {_stock:,.0f} kg ({_stock/1000:,.1f} TN) · acidez {_ac_txt} · última eval: {_ev_txt}")
                    _falta_kg = (target_kg - kg_port - kg_tk) if target_kg else _stock
                    _falta_lt = (_falta_kg / _denst) if _denst else 0.0
                    lt_tk = float(st.number_input(
                        f"Litros desde {row['codigo']}", min_value=0.0,
                        value=float(max(0.0, round(_falta_lt))) if (_falta_lt and _falta_lt > 0) else 0.0,
                        step=100.0, key=f"{key_prefix}_tklt_{_i}"))
                    _kg_this = lt_tk * _denst
                    if _kg_this > 0:
                        st.caption(f"≈ {_kg_this:,.0f} kg · densidad {_denst:.3f} kg/L")
                        portions.append({"fuente": "TANQUE", "ticket": None, "id_tanque": int(row["id_tanque"]), "kg": _kg_this})
                        parts_lab.append((_kg_this, _tank_avg))
                        _tcorr = str(row.get("corriente")).upper() if pd.notna(row.get("corriente")) else None
                        if _tcorr:
                            parts_corr.append((_kg_this, _tcorr))
                        kg_tk += _kg_this
                    if _kg_this > _stock:
                        st.warning(f"⚠️ {row['codigo']}: supera el stock del tanque (se registra igual).")
    total = kg_port + kg_tk
    # Promedio ponderado por kg de cada parámetro entre todas las fuentes
    lab_avg = {}
    if parts_lab:
        _keys = set()
        for _kg, _p in parts_lab:
            _keys |= set(_p.keys())
        for _k in _keys:
            _num = 0.0
            _den = 0.0
            for _kg, _p in parts_lab:
                if _p.get(_k) is not None and _kg:
                    _num += float(_p[_k]) * float(_kg)
                    _den += float(_kg)
            if _den > 0:
                lab_avg[_k] = _num / _den
    if not lab_avg:
        _ms = ultimas_muestras_mp(cod, n=1)
        if not _ms.empty:
            _r0 = _ms.iloc[0]
            for _c in ("prc_acidez", "prc_agua", "prc_sedimentos", "prc_producto", "ppm_azufre", "ppm_fosforo", "densidad__g_ml"):
                _v = _r0.get(_c)
                if pd.notna(_v):
                    lab_avg[_c] = float(_v)
    _ac_pond = lab_avg.get("prc_acidez")
    _ac_pond_txt = f" · acidez ponderada {_ac_pond*100:.2f}%" if _ac_pond is not None else ""
    if target_kg:
        _f = target_kg - total
        _msg = "✅ completo" if abs(_f) <= max(1.0, target_kg * 0.01) else (f"faltan {_f:,.0f} kg" if _f > 0 else f"sobran {-_f:,.0f} kg")
        st.markdown(
            f"<div class='kpi' style='margin:6px 0'><div class='l'>Total cargado / objetivo</div>"
            f"<div class='v'>{total/1000:,.2f}<span style='font-size:1rem;font-weight:700'> / {target_kg/1000:,.2f} TN</span></div>"
            f"<div class='s'>{_msg}{_ac_pond_txt}</div></div>", unsafe_allow_html=True)
    elif total > 0:
        st.caption(f"Total cargado: **{total:,.0f} kg · {total/1000:,.2f} TN**{_ac_pond_txt}")
    _distinct_corr = set(c for _kg, c in parts_corr if c)
    st.session_state["mp_corr_conflict"] = (len(_distinct_corr) > 1)
    src_corr = None
    if parts_corr:
        _cg = {}
        for _kg, _c in parts_corr:
            if _c:
                _cg[_c] = _cg.get(_c, 0.0) + float(_kg or 0)
        if _cg:
            src_corr = max(_cg, key=_cg.get)
    if len(_distinct_corr) > 1:
        st.error("⛔ La materia prima de **portería** y **tanque** tienen distinta corriente ("
                 + " vs ".join(sorted(_distinct_corr))
                 + "). No se puede mezclar: elegí fuentes de la **misma corriente**. La carga queda bloqueada.")
    elif src_corr:
        st.session_state["mp_corr"] = src_corr
        st.caption("Corriente de la fuente: **"
                   + ("🌱 Vegetal" if src_corr == "VEGETAL" else ("🐄 Animal" if src_corr == "ANIMAL" else src_corr))
                   + "**")
    return total, portions, lab_avg, src_corr


def proceso_desde_mp(cod):
    """El tipo de reacción se deriva de la materia prima elegida (AFE -> desgomado, AG/SEBO -> ARE)."""
    if not cod:
        return None
    c = str(cod).upper()
    if c.startswith("AFE"):
        return "DESGOMADO_ACUOSO"
    return "PRODUCCION_ARE"


def corriente_de_mp_lab(cod):
    """Corriente (VEGETAL/ANIMAL) de la MP. Toma la clasificación del producto asignada
    por laboratorio (AG=vegetal, SEBO=animal, ...). El campo `corriente` crudo de
    procesos_lab es inconsistente, así que se usa solo como respaldo."""
    if not cod:
        return None
    try:
        d2 = cat("SELECT corriente FROM produccion.dim_producto WHERE codigo_producto=%s", (cod,))
        if not d2.empty and d2.iloc[0, 0]:
            _c = str(d2.iloc[0, 0]).upper()
            if _c in ("ANIMAL", "VEGETAL"):
                return _c
    except Exception:
        pass
    try:
        df = cat(
            "SELECT pl.corriente FROM produccion.procesos_lab pl "
            "JOIN produccion.dic_producto_lab dpl ON dpl.lab_producto = pl.producto_lab "
            "JOIN produccion.dim_producto p ON p.id_producto = dpl.id_producto "
            "WHERE p.codigo_producto=%s AND pl.corriente IS NOT NULL "
            "ORDER BY pl.fecha DESC NULLS LAST LIMIT 1", (cod,))
        if not df.empty and df.iloc[0, 0]:
            return str(df.iloc[0, 0]).upper()
    except Exception:
        pass
    return None


def siguiente_identificador(sector):
    """Identificador de carga auto-incremental y relacionado con el sector: PREFIJO-AAAA-NNNN."""
    pref = {"REACTORES": "RX", "BACHAS": "BA", "EXPO": "EX", "RECUPERACION": "RP"}.get(sector, "ID")
    anio = date.today().year
    n = 1
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
                cur.execute(
                    "SELECT identificador_unidad FROM fact_batch_proceso "
                    "WHERE identificador_unidad LIKE %s ORDER BY identificador_unidad DESC LIMIT 1",
                    (f"{pref}-{anio}-%",))
                row = cur.fetchone()
                if row and row[0]:
                    try:
                        n = int(str(row[0]).split("-")[-1]) + 1
                    except Exception:
                        n = 1
        finally:
            conn.close()
    except Exception:
        n = 1
    return f"{pref}-{anio}-{n:04d}"


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

# Productos base NO evaluables aunque su corriente lo sea (editable: dic_producto_base_config)
try:
    _pbne = cat("SELECT producto_base FROM produccion.dic_producto_base_config WHERE NOT evaluable")
    PROD_BASE_NO_EVAL = set(_pbne["producto_base"].str.upper().tolist()) if not _pbne.empty else set()
except Exception:
    PROD_BASE_NO_EVAL = {"GANADO"}

def _es_evaluable(corriente, producto_base):
    if corriente not in CORR_EVAL:
        return False
    if producto_base is not None and str(producto_base).upper() in PROD_BASE_NO_EVAL:
        return False
    return True

# Cláusula SQL para excluir productos base no evaluables (ej. GANADO)
PROD_BASE_NO_EVAL_SQL = (
    " AND upper(producto_base) NOT IN (" +
    ",".join("'" + p.replace("'", "''") + "'" for p in PROD_BASE_NO_EVAL) + ")"
) if PROD_BASE_NO_EVAL else ""


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
        _lab_view = st.radio("Vista", ["➕ Carga / Edición", "🛢️ Parámetros por tanque", "🚛 Entrada diaria", "📦 Asignación a tanque", "📊 Resultados", "🔬 Producciones en marcha"],
                             horizontal=True, key="lab_view_sel", label_visibility="collapsed")
        if _lab_view.startswith("🔬"):
            _pm_tipo = st.radio("Tipo de proceso", ["🧴 ARE (decantación)", "🫧 Desgomado acuoso"],
                                horizontal=True, key="lab_prodmarcha_tipo", label_visibility="collapsed")
            if _pm_tipo.startswith("🫧"):
                import desgomado
                desgomado.laboratorio(USR, cat, conectar)
            else:
                import decantacion
                decantacion.laboratorio(USR, cat, conectar)
        elif _lab_view.startswith("🛢️"):
            _form_param_tanque(cat, conectar, USR)
        elif _lab_view.startswith("🚛"):
            _porteria_entrada_diaria(cat)
        elif _lab_view.startswith("📦"):
            _lab_asignacion(cat, conectar, USR)
        elif _lab_view.startswith("➕"):
            from lab_carga import render_laboratorio
            render_laboratorio(get_conn=_lab_conn, usr=USR)
        else:
            with st.expander("Filtros", expanded=True):
                c1, c2, c3 = st.columns(3)
                fmin = c1.date_input("Fecha desde", value=(date.today()-_td(days=30)), key="lab_fmin")
                fmax = c2.date_input("Fecha hasta", value=date.today(), key="lab_fmax")
                limit_lab = c3.number_input("Límite filas", 100, 100000, 5000, step=500, key="lab_lim")
                try:
                    prods_lab = cat("SELECT DISTINCT produccion.fn_rotulo(producto_lab) AS producto_lab FROM produccion.procesos_lab WHERE producto_lab IS NOT NULL ORDER BY 1")["producto_lab"].tolist()
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
                where.append("produccion.fn_rotulo(pl.producto_lab) = ANY(%s)"); params.append(sel_prod)
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
                         WHEN 'EFLUENTE'           THEN 'DISPOSICION FINAL DE LIQUIDOS'
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
            if df_l is not None and not df_l.empty and "producto_lab" in df_l.columns:
                df_l["producto_lab"] = df_l["producto_lab"].map(
                    lambda v: "DISPOSICION FINAL DE LIQUIDOS"
                    if isinstance(v, str) and (v.strip().upper() == "EFLUENTE" or ("EFLU" in v.upper() and "LIQU" in v.upper()))
                    else v)
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
        st.markdown('<div class="section-title" style="font-size:1.4rem">🛢️ Tanques y stock</div>', unsafe_allow_html=True)
        try:
            import tanques_panel as _tqp
            _tab_sec, _tab_res, _tab_vol = st.tabs(["📊 Por sector", "🔎 Resumen y filtros", "🌪️ Volatilidad"])
            # ---------- Volatilidad: escaneo histórico de cambios por tanque ----------
            with _tab_vol:
                st.caption("Escaneo completo de `fact_stock_tanque`: **WeDo** = cuántos cambios de nivel por día registró el sensor; "
                           "**manuales** = cuánto varió entre una medición y la siguiente. Para entender qué tanques se mueven más.")
                v1, v2, v3 = st.columns(3)
                _vdias = v1.selectbox("Ventana de análisis", [30, 60, 90, 180, 365], index=2, key="vol_dias",
                                      format_func=lambda d: f"últimos {d} días")
                _vumb = v2.number_input("Umbral de cambio (L)", 10.0, 50_000.0, value=100.0, step=50.0, key="vol_umb",
                                        help="Variaciones menores a esto se consideran ruido (no cuentan como cambio).")
                _vfue = v3.selectbox("Fuente", ["Todas", "WeDo", "Manual"], key="vol_fue")
                _vol = cat("""
                    WITH d AS (
                      SELECT s.id_tanque, s.medido_en, s.litros::float AS litros,
                             s.litros::float - LAG(s.litros::float) OVER (PARTITION BY s.id_tanque ORDER BY s.medido_en) AS delta
                      FROM produccion.fact_stock_tanque s
                      WHERE s.litros IS NOT NULL AND s.medido_en >= now() - make_interval(days => %s)
                    )
                    SELECT t.id_tanque, t.codigo, t.nombre, t.sector, t.capacidad_litros::float AS cap,
                           CASE WHEN w.id_tanque IS NOT NULL THEN 'WeDo' ELSE 'Manual' END AS fuente,
                           count(d.litros) AS n_med,
                           GREATEST(1, (max(d.medido_en)::date - min(d.medido_en)::date) + 1) AS dias,
                           count(*) FILTER (WHERE abs(d.delta) >= %s) AS n_cambios,
                           COALESCE(avg(abs(d.delta)) FILTER (WHERE abs(d.delta) >= %s), 0) AS prom_cambio,
                           COALESCE(max(abs(d.delta)), 0) AS max_cambio,
                           COALESCE(stddev_samp(d.delta), 0) AS std_delta,
                           COALESCE(sum(abs(d.delta)) FILTER (WHERE abs(d.delta) >= %s), 0) AS suma_abs
                    FROM d
                    JOIN produccion.dim_tanque t USING (id_tanque)
                    LEFT JOIN produccion.dim_tanque_wedo w ON w.id_tanque = t.id_tanque
                    WHERE t.activo
                    GROUP BY 1,2,3,4,5,6
                """, (int(_vdias), float(_vumb), float(_vumb), float(_vumb)))
                if _vol.empty:
                    st.info("No hay mediciones en la ventana elegida.")
                else:
                    _v = _vol.copy()
                    if _vfue != "Todas":
                        _v = _v[_v["fuente"] == _vfue]
                    for c in ("n_med", "dias", "n_cambios"):
                        _v[c] = pd.to_numeric(_v[c], errors="coerce").fillna(0)
                    for c in ("prom_cambio", "max_cambio", "std_delta", "suma_abs", "cap"):
                        _v[c] = pd.to_numeric(_v[c], errors="coerce")
                    _v["cambios_dia"] = (_v["n_cambios"] / _v["dias"]).round(2)
                    _v["rotacion_dia_pct"] = (_v["suma_abs"] / _v["dias"] / _v["cap"] * 100).round(1)

                    def _clase(r):
                        rp = r["rotacion_dia_pct"]
                        if pd.notna(rp) and rp > 0:
                            if rp >= 30: return "🌪️ Muy volátil"
                            if rp >= 10: return "🔁 Activo"
                            if rp >= 2:  return "🌊 Moderado"
                            return "🧊 Quieto"
                        cd = r["cambios_dia"]
                        if cd >= 3:   return "🌪️ Muy volátil"
                        if cd >= 1:   return "🔁 Activo"
                        if cd >= 0.2: return "🌊 Moderado"
                        return "🧊 Quieto"
                    _v["Clasificación"] = _v.apply(_clase, axis=1)
                    _v = _v.sort_values(["cambios_dia", "rotacion_dia_pct"], ascending=False)

                    _vc = _v["Clasificación"].value_counts()
                    _cls_all = ["🌪️ Muy volátil", "🔁 Activo", "🌊 Moderado", "🧊 Quieto"]
                    _bcols = st.columns(4)
                    for _bc, _lbl in zip(_bcols, _cls_all):
                        _activo_b = (st.session_state.get("vol_cls") == _lbl)
                        if _bc.button(f"{_lbl} · {int(_vc.get(_lbl, 0))}", key=f"vol_cls_{_lbl}",
                                      use_container_width=True,
                                      type=("primary" if _activo_b else "secondary"),
                                      help="Click para ver cuáles son y sus últimas mediciones. Click de nuevo para cerrar."):
                            st.session_state["vol_cls"] = (None if _activo_b else _lbl)
                            st.rerun()
                    _cls_sel = st.session_state.get("vol_cls")
                    if _cls_sel:
                        _lv = _v[_v["Clasificación"] == _cls_sel].sort_values("cambios_dia", ascending=False)
                        if _lv.empty:
                            st.info(f"No hay tanques {_cls_sel} con los filtros actuales.")
                        else:
                            st.markdown(f"**{_cls_sel} — {len(_lv)} tanque(s):**")
                            st.dataframe(_lv[["nombre", "fuente", "sector", "n_med", "cambios_dia",
                                              "prom_cambio", "max_cambio", "rotacion_dia_pct"]].rename(columns={
                                "nombre": "Tanque", "fuente": "Fuente", "sector": "Sector", "n_med": "Mediciones",
                                "cambios_dia": "Cambios/día", "prom_cambio": "Variación prom. (L)",
                                "max_cambio": "Variación máx. (L)", "rotacion_dia_pct": "Rotación diaria (% cap.)"}),
                                use_container_width=True, hide_index=True, column_config={
                                    "Variación prom. (L)": st.column_config.NumberColumn(format="%.0f"),
                                    "Variación máx. (L)": st.column_config.NumberColumn(format="%.0f"),
                                    "Rotación diaria (% cap.)": st.column_config.NumberColumn(format="%.1f%%"),
                                })
                            _lop = _lv.apply(lambda r: f"{r['nombre']} · {r['fuente']} · {r['sector']}", axis=1).tolist()
                            _lsel = st.selectbox("🔬 Últimas mediciones de", _lop, key="vol_cls_tq")
                            _lid = int(_lv.iloc[_lop.index(_lsel)]["id_tanque"])
                            _u10 = cat("""
                                WITH d AS (
                                  SELECT s.medido_en, s.litros::float AS litros, s.observaciones,
                                         s.litros::float - LAG(s.litros::float) OVER (ORDER BY s.medido_en) AS delta
                                  FROM produccion.fact_stock_tanque s
                                  WHERE s.id_tanque = %s AND s.litros IS NOT NULL
                                ) SELECT * FROM d ORDER BY medido_en DESC LIMIT 12
                            """, (_lid,))
                            if _u10.empty:
                                st.info("Sin mediciones registradas.")
                            else:
                                _u10 = _u10.copy()
                                _u10["Δ vs anterior (L)"] = pd.to_numeric(_u10["delta"], errors="coerce").round(0)
                                st.dataframe(_u10[["medido_en", "litros", "Δ vs anterior (L)", "observaciones"]].rename(
                                    columns={"medido_en": "Medición", "litros": "Litros", "observaciones": "Obs."}),
                                    use_container_width=True, hide_index=True, column_config={
                                        "Medición": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                        "Litros": st.column_config.NumberColumn(format="%.0f"),
                                    })
                        st.divider()

                    import altair as _alt
                    _top = _v.head(15).copy()
                    _top["tanque"] = _top["nombre"] + " (" + _top["fuente"] + ")"
                    st.markdown("**Ranking: cambios significativos por día (top 15)**")
                    st.altair_chart(
                        _alt.Chart(_top).mark_bar().encode(
                            x=_alt.X("cambios_dia:Q", title=f"cambios/día (>{_vumb:.0f} L)"),
                            y=_alt.Y("tanque:N", sort="-x", title=None),
                            color=_alt.Color("fuente:N", title="fuente"),
                            tooltip=["tanque", "cambios_dia", "rotacion_dia_pct", "prom_cambio", "n_med"],
                        ).properties(height=380), use_container_width=True)

                    st.markdown("**Escaneo completo**")
                    _vt = _v[["nombre", "fuente", "sector", "n_med", "dias", "cambios_dia",
                              "prom_cambio", "max_cambio", "std_delta", "rotacion_dia_pct", "Clasificación"]].rename(columns={
                        "nombre": "Tanque", "fuente": "Fuente", "sector": "Sector", "n_med": "Mediciones",
                        "dias": "Días c/datos", "cambios_dia": "Cambios/día",
                        "prom_cambio": "Variación prom. (L)", "max_cambio": "Variación máx. (L)",
                        "std_delta": "Desvío (L)", "rotacion_dia_pct": "Rotación diaria (% cap.)"})
                    st.dataframe(_vt, use_container_width=True, hide_index=True, height=420, column_config={
                        "Variación prom. (L)": st.column_config.NumberColumn(format="%.0f"),
                        "Variación máx. (L)": st.column_config.NumberColumn(format="%.0f"),
                        "Desvío (L)": st.column_config.NumberColumn(format="%.0f"),
                        "Rotación diaria (% cap.)": st.column_config.NumberColumn(format="%.1f%%"),
                    })
                    st.caption("**Cambios/día** = variaciones mayores al umbral por día con datos. "
                               "**Rotación diaria** = litros movidos por día ÷ capacidad (mejor medida de volatilidad real). "
                               "🌪️ ≥30% · 🔁 ≥10% · 🌊 ≥2% · 🧊 <2% de rotación diaria.")

                    # ---- Drill-down por tanque ----
                    st.divider()
                    st.markdown("**🔎 Detalle por tanque**")
                    _vop = _v.apply(lambda r: f"{r['nombre']} · {r['fuente']} · {r['Clasificación']}", axis=1).tolist()
                    _vsel = st.selectbox("Tanque", _vop, key="vol_sel")
                    _vr = _v.iloc[_vop.index(_vsel)]
                    _idv = int(_vr["id_tanque"])
                    _det = cat("""
                        WITH d AS (
                          SELECT s.medido_en, s.litros::float AS litros, s.observaciones, s.id_usuario,
                                 s.litros::float - LAG(s.litros::float) OVER (ORDER BY s.medido_en) AS delta
                          FROM produccion.fact_stock_tanque s
                          WHERE s.id_tanque = %s AND s.litros IS NOT NULL
                            AND s.medido_en >= now() - make_interval(days => %s)
                        ) SELECT * FROM d ORDER BY medido_en
                    """, (_idv, int(_vdias)))
                    if _det.empty:
                        st.info("Sin mediciones en la ventana.")
                    else:
                        _det["medido_en"] = pd.to_datetime(_det["medido_en"])
                        _det["fecha"] = _det["medido_en"].dt.date.astype(str)
                        _dd = _det.dropna(subset=["delta"])
                        _dd = _dd[_dd["delta"].abs() >= float(_vumb)]
                        _por_dia = (_dd.assign(abs_delta=_dd["delta"].abs())
                                    .groupby("fecha").agg(cambios=("delta", "size"), litros_movidos=("abs_delta", "sum"))
                                    .reset_index())
                        dk1, dk2, dk3 = st.columns(3)
                        dk1.metric("Cambios en la ventana", int(len(_dd)))
                        dk2.metric("Litros movidos", f"{_dd['delta'].abs().sum():,.0f} L")
                        dk3.metric("Mayor variación", f"{_det['delta'].abs().max():,.0f} L" if _det["delta"].notna().any() else "—")
                        c_izq, c_der = st.columns(2)
                        with c_izq:
                            st.markdown("**Cambios por día**")
                            if _por_dia.empty:
                                st.info("Sin cambios sobre el umbral.")
                            else:
                                st.altair_chart(
                                    _alt.Chart(_por_dia).mark_bar().encode(
                                        x=_alt.X("fecha:N", title=None),
                                        y=_alt.Y("cambios:Q", title="cambios/día"),
                                        tooltip=["fecha", "cambios", _alt.Tooltip("litros_movidos:Q", format=",.0f")],
                                    ).properties(height=260), use_container_width=True)
                        with c_der:
                            st.markdown("**Nivel del tanque (L)**")
                            st.altair_chart(
                                _alt.Chart(_det).mark_line(point=(_vr["fuente"] == "Manual")).encode(
                                    x=_alt.X("medido_en:T", title=None),
                                    y=_alt.Y("litros:Q", title="litros"),
                                    tooltip=[_alt.Tooltip("medido_en:T", format="%d/%m %H:%M"),
                                             _alt.Tooltip("litros:Q", format=",.0f"),
                                             _alt.Tooltip("delta:Q", format="+,.0f")],
                                ).properties(height=260), use_container_width=True)
                        if _vr["fuente"] == "Manual":
                            st.markdown("**Variación entre mediciones (manuales)**")
                            _tm = _det.sort_values("medido_en", ascending=False).copy()
                            _tm["Δ vs anterior (L)"] = _tm["delta"].round(0)
                            st.dataframe(_tm[["medido_en", "litros", "Δ vs anterior (L)", "observaciones"]].rename(
                                columns={"medido_en": "Medición", "litros": "Litros", "observaciones": "Obs."}),
                                use_container_width=True, hide_index=True, height=300, column_config={
                                    "Medición": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                    "Litros": st.column_config.NumberColumn(format="%.0f"),
                                })

            with _tab_sec:
                _tqp.vista_por_sector(cat)
            with _tab_res:
                _tqp.resumen_filtrado(cat)
        except Exception as _e_tqp:
            st.warning(f"No se pudo cargar la vista por sector/resumen: {_e_tqp}")
        st.divider()
        st.markdown('#### 🛠️ Carga manual, aforo y detalle por tanque')
        _panel = cat("SELECT * FROM produccion.vw_tanque_panel ORDER BY sector, nombre")
        _prods = cat("SELECT id_producto, codigo_producto, COALESCE(densidad_g_ml,0.91) AS dens "
                     "FROM produccion.dim_producto WHERE activo ORDER BY codigo_producto")
        if _panel.empty:
            st.info("No hay tanques cargados.")
        else:
            # ---------- Filtros ----------
            fc1, fc2, fc3, fc4 = st.columns(4)
            f_sec = fc1.multiselect("Sector", sorted(_panel["sector"].dropna().unique().tolist()), key="tqp_sec")
            f_tip = fc2.selectbox("Tipo de tanque", ["Todos"] + sorted(_panel["tipo_tanque"].dropna().unique().tolist()), key="tqp_tip")
            f_med = fc3.selectbox("Medidor", ["Todos", "WeDo", "Manual"], key="tqp_med")
            f_prod = fc4.selectbox("Producto asignado", ["Todos"] + sorted([x for x in _panel["producto_principal"].dropna().unique().tolist()]), key="tqp_prod")

            d = _panel.copy()
            if f_sec:
                d = d[d["sector"].isin(f_sec)]
            if f_tip != "Todos":
                d = d[d["tipo_tanque"] == f_tip]
            if f_med != "Todos":
                d = d[d["fuente_medicion"] == f_med]
            if f_prod != "Todos":
                d = d[d["producto_principal"] == f_prod]

            # Stock: LITROS de base; kg/TN por fórmula de densidad
            d["_litros"] = pd.to_numeric(d["litros_actual"], errors="coerce")
            d["_dens"] = pd.to_numeric(d["densidad"], errors="coerce").fillna(0.91)
            d["_kg"] = d["_litros"] * d["_dens"]
            d["_tn"] = d["_kg"] / 1000.0

            # ---------- Estado de medición + validación (aforo/cubicaje) ----------
            try:
                _afo = cat("SELECT id_tanque, tipo_curva, capacidad_litros AS cap_aforo, medible FROM produccion.dim_tanque_aforo")
                d = d.merge(_afo, on="id_tanque", how="left")
            except Exception:
                d["cap_aforo"] = pd.NA; d["medible"] = pd.NA; d["tipo_curva"] = pd.NA
            _now = pd.Timestamp.now(tz="UTC")
            def _antig_h(x):
                try:
                    return (_now - pd.to_datetime(x, utc=True)).total_seconds() / 3600.0
                except Exception:
                    return None
            d["_antig_h"] = d["ultima_medicion"].map(_antig_h)
            def _estado(r):
                if pd.notna(r.get("medible")) and not bool(r["medible"]):
                    return "⛔ No medible"
                if pd.isna(r["_litros"]):
                    return "❔ Sin medición"
                ah = r["_antig_h"]
                if r["fuente_medicion"] == "WeDo":
                    return "📡 Sensor al día" if (ah is not None and ah <= 2) else "📡 Sensor atrasado"
                if ah is None:
                    return "✍️ Manual"
                if ah <= 24:
                    return "✍️ Manual (hoy)"
                if ah <= 72:
                    return "✍️ Manual (días)"
                return "⏰ Manual (vieja)"
            d["Estado"] = d.apply(_estado, axis=1)

            # ---------- KPIs ----------
            _tot = len(d)
            _wd = int((d["fuente_medicion"] == "WeDo").sum())
            _lt = float(d["_litros"].sum())
            _tn = float(d["_tn"].sum())
            st.markdown(
                "<div class='kpi-grid'>"
                f"<div class='kpi brand'><div class='l'>Tanques</div><div class='v'>{_tot}</div></div>"
                f"<div class='kpi'><div class='l'>📡 WeDo (radar)</div><div class='v'>{_wd}</div></div>"
                f"<div class='kpi'><div class='l'>✍️ Manual</div><div class='v'>{_tot-_wd}</div></div>"
                f"<div class='kpi'><div class='l'>Stock total (litros)</div><div class='v'>{_lt:,.0f}</div></div>"
                f"<div class='kpi'><div class='l'>Stock total (TN)</div><div class='v'>{_tn:,.1f}</div></div>"
                "</div>", unsafe_allow_html=True)

            # ---------- Alertas de medición ----------
            _n_sin = int((d["Estado"] == "❔ Sin medición").sum())
            _n_vieja = int(d["Estado"].isin(["⏰ Manual (vieja)", "📡 Sensor atrasado"]).sum())
            _n_nom = int((d["Estado"] == "⛔ No medible").sum())
            if (_n_sin + _n_vieja + _n_nom) > 0:
                _bits = []
                if _n_sin:   _bits.append(f"**{_n_sin}** sin medición")
                if _n_vieja: _bits.append(f"**{_n_vieja}** con medición atrasada")
                if _n_nom:   _bits.append(f"**{_n_nom}** no medibles")
                st.warning("🔎 Revisar: " + " · ".join(_bits))

            # ---------- Tabla ----------
            _t = d.copy()
            _t["Medidor"] = _t["fuente_medicion"].map({"WeDo": "📡 WeDo", "Manual": "✍️ Manual"})
            _t = _t[["codigo", "nombre", "tipo_tanque", "sector", "producto_principal", "Medidor", "wedo_label",
                     "intervalo_real_min", "nivel_pct_actual", "_litros", "_tn", "capacidad_litros", "ultima_medicion", "Estado"]].rename(columns={
                "codigo": "Código", "nombre": "Tanque", "tipo_tanque": "Tipo", "sector": "Sector",
                "producto_principal": "Producto", "wedo_label": "Sensor", "intervalo_real_min": "Intervalo (min)",
                "nivel_pct_actual": "Nivel %",
                "_litros": "Litros", "_tn": "TN", "capacidad_litros": "Capac. (L)", "ultima_medicion": "Última medición"})
            try:
                _t["Última medición"] = pd.to_datetime(_t["Última medición"], errors="coerce", utc=True)\
                    .dt.tz_convert("America/Argentina/Buenos_Aires").dt.tz_localize(None)
            except Exception:
                pass
            try:
                _cfg = {
                    "Nivel %": st.column_config.ProgressColumn("Nivel %", min_value=0, max_value=100, format="%.0f%%"),
                    "Intervalo (min)": st.column_config.NumberColumn("Intervalo (min)", format="%.0f", help="Cada cuántos minutos reporta el sensor WeDo (intervalo real observado)."),
                    "Litros": st.column_config.NumberColumn(format="%d"),
                    "TN": st.column_config.NumberColumn(format="%.2f"),
                    "Capac. (L)": st.column_config.NumberColumn(format="%d"),
                    "Última medición": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                }
                st.dataframe(_t, use_container_width=True, hide_index=True, height=470, column_config=_cfg)
            except Exception:
                st.dataframe(_t, use_container_width=True, hide_index=True, height=470)
            st.caption("Stock en **litros** (medición real). El **kg/TN** se calcula por densidad del producto del tanque. "
                       "📡 WeDo = automático por sensor · ✍️ Manual = última medición cargada.")
            st.caption("**Estado** = frescura de la medición (sensor al día / manual hoy-días-vieja / sin medición / no medible).")

            _byp = d.dropna(subset=["_tn"]).groupby("producto_principal", as_index=False)["_tn"].sum()
            if not _byp.empty:
                st.markdown('<div class="section-title">Stock por material (TN)</div>', unsafe_allow_html=True)
                st.bar_chart(_byp.sort_values("_tn", ascending=False), x="producto_principal", y="_tn", use_container_width=True)

            st.divider()
            _TQV = ["⏰ Última carga", "✍️ Cargar medición (manual)", "📏 Medir por cm (aforo)", "✏️ Editar tanque", "➕ Alta / baja", "📈 Histórico / variación"]
            _vtab = st.radio("Vista de tanque", _TQV, horizontal=True, key="tq_vtab", label_visibility="collapsed")

            # ---------- Última carga: tanques MANUALES por antigüedad de la medición ----------
            if _vtab == "⏰ Última carga":
                _um = _panel[_panel["fuente_medicion"] == "Manual"].copy()
                _um = _um[_um["activo"] == True] if "activo" in _um.columns else _um
                if _um.empty:
                    st.info("No hay tanques de carga manual.")
                else:
                    _now_ar = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires")
                    _ts = pd.to_datetime(_um["ultima_medicion"], errors="coerce")
                    try:
                        _ts = _ts.dt.tz_convert("America/Argentina/Buenos_Aires")
                    except Exception:
                        try:
                            _ts = _ts.dt.tz_localize("America/Argentina/Buenos_Aires")
                        except Exception:
                            pass
                    _um["_h"] = (_now_ar - _ts).dt.total_seconds() / 3600.0

                    def _bucket(h):
                        if pd.isna(h):
                            return "SIN"
                        if h <= 24:
                            return "HOY"
                        if h <= 72:
                            return "D3"
                        if h <= 168:
                            return "D7"
                        return "VIEJO"
                    _um["_b"] = _um["_h"].map(_bucket)
                    _B = {
                        "VIEJO": ("🔴", "#dc2626", "Más de 7 días"),
                        "SIN":   ("⚫", "#475569", "Sin medición"),
                        "D7":    ("🟠", "#d97706", "3 a 7 días"),
                        "D3":    ("🟡", "#ca8a04", "1 a 3 días"),
                        "HOY":   ("🟢", "#059669", "Últimas 24 h"),
                    }
                    _cts = _um["_b"].value_counts()
                    st.markdown(
                        "<div class='kpi-grid'>" + "".join(
                            f"<div class='kpi'><div class='l'>{e} {lbl}</div>"
                            f"<div class='v' style='color:{col};'>{int(_cts.get(b, 0))}</div>"
                            f"<div class='s'>tanques manuales</div></div>"
                            for b, (e, col, lbl) in _B.items()) + "</div>",
                        unsafe_allow_html=True)

                    uf1, uf2 = st.columns(2)
                    _usec = uf1.selectbox("Sector", ["Todos"] + sorted(_um["sector"].dropna().unique().tolist()), key="ult_sec")
                    _usolo = uf2.multiselect("Mostrar solo", [f"{e} {lbl}" for e, _, lbl in _B.values()], key="ult_solo",
                                             help="Vacío = todos. Ej: elegí 🔴 y ⚫ para ver lo urgente.")
                    _d = _um if _usec == "Todos" else _um[_um["sector"] == _usec]
                    if _usolo:
                        _keep = [b for b, (e, _, lbl) in _B.items() if f"{e} {lbl}" in _usolo]
                        _d = _d[_d["_b"].isin(_keep)]
                    _d = _d.sort_values("_h", ascending=False, na_position="first")

                    def _hace(h):
                        if pd.isna(h):
                            return "nunca medido"
                        if h < 1:
                            return f"hace {int(h*60)} min"
                        if h < 24:
                            return f"hace {h:.0f} h"
                        return f"hace {h/24:.0f} día(s)"

                    _cards = []
                    for _, r in _d.iterrows():
                        e, col, _lbl = _B[r["_b"]]
                        _lt = pd.to_numeric(pd.Series([r.get("litros_actual")]), errors="coerce").iloc[0]
                        _lt_txt = f"{_lt:,.0f} L" if pd.notna(_lt) else "—"
                        _prod = r.get("producto_principal") or "sin producto"
                        _cards.append(
                            f"<div style='background:var(--surface); border:1px solid var(--line); "
                            f"border-left:6px solid {col}; border-radius:12px; padding:10px 12px;'>"
                            f"<div style='font-weight:800; color:var(--ink); font-size:.95rem;'>{r['nombre']}</div>"
                            f"<div style='color:var(--muted); font-size:.75rem;'>{r['codigo']} · {r['sector']}</div>"
                            f"<div style='font-size:.82rem; margin-top:4px;'>{_prod} · <b>{_lt_txt}</b></div>"
                            f"<div style='color:{col}; font-weight:800; font-size:1.02rem; margin-top:4px;'>{e} {_hace(r['_h'])}</div>"
                            f"</div>")
                    st.markdown(
                        "<div style='display:grid; grid-template-columns:repeat(auto-fill,minmax(215px,1fr)); "
                        "gap:10px; margin-top:8px;'>" + "".join(_cards) + "</div>",
                        unsafe_allow_html=True)
                    st.caption("Ordenado de lo más viejo a lo más reciente (lo urgente arriba). "
                               "🔴 +7 días · 🟠 3-7 días · 🟡 1-3 días · 🟢 últimas 24 h · ⚫ nunca medido. "
                               "Cargá la medición en la pestaña ✍️ o 📏.")


            # ---------- Cargar medición: SOLO tanques manuales, con filtros ----------
            if _vtab == "✍️ Cargar medición (manual)":
                _inc_wedo = st.checkbox("Incluir tanques WeDo (corrección / override manual del sensor)",
                                        value=False, key="tqc_incwedo")
                _man = _panel.copy() if _inc_wedo else _panel[_panel["fuente_medicion"] == "Manual"]
                if _man.empty:
                    st.info("No hay tanques para cargar con ese criterio.")
                else:
                    if _inc_wedo:
                        st.caption("Incluye **tanques WeDo**: lo que cargues acá **reemplaza el valor del sensor** "
                                   "hasta la próxima sincronización del radar. Filtrá para encontrar el tanque.")
                    else:
                        st.caption("Solo **tanques manuales**. Filtrá para encontrar el tanque rápido.")
                    ff1, ff2, ff3 = st.columns(3)
                    _csec = ff1.selectbox("Sector", ["Todos"] + sorted(_man["sector"].dropna().unique().tolist()), key="tqc_sec")
                    _ctip = ff2.selectbox("Tipo", ["Todos"] + sorted(_man["tipo_tanque"].dropna().unique().tolist()), key="tqc_tip")
                    _cpr = ff3.selectbox("Producto", ["Todos"] + sorted([x for x in _man["producto_principal"].dropna().unique().tolist()]), key="tqc_pr")
                    _mm = _man.copy()
                    if _csec != "Todos":
                        _mm = _mm[_mm["sector"] == _csec]
                    if _ctip != "Todos":
                        _mm = _mm[_mm["tipo_tanque"] == _ctip]
                    if _cpr != "Todos":
                        _mm = _mm[_mm["producto_principal"] == _cpr]
                    if _mm.empty:
                        st.warning("No hay tanques manuales con esos filtros.")
                    else:
                        _opt = _mm.apply(lambda r: f"{r['nombre']} · {r['codigo']} · {r['sector']}", axis=1).tolist()
                        _selt = st.selectbox(f"Tanque ({len(_mm)})", _opt, key="tq_sel_c")
                        _row = _mm.iloc[_opt.index(_selt)]
                        _idt = int(_row["id_tanque"])
                        if str(_row.get("fuente_medicion")) == "WeDo":
                            st.warning("🛰️ Tanque **WeDo**: esta carga es un **override manual**; el sensor radar "
                                       "lo sobreescribe en su próxima medición.")
                        _cap = float(_row["capacidad_litros"]) if pd.notna(_row["capacidad_litros"]) else 0.0
                        _perm = cat("SELECT p.codigo_producto FROM produccion.dim_tanque_producto tp "
                                    "JOIN produccion.dim_producto p ON p.id_producto=tp.id_producto "
                                    "WHERE tp.id_tanque=%s ORDER BY tp.es_principal DESC, p.codigo_producto", (_idt,))
                        _plist = _perm["codigo_producto"].tolist() or _prods["codigo_producto"].tolist()
                        _ppal = _prods[_prods["id_producto"] == _row["id_producto_principal"]]["codigo_producto"].tolist()
                        _defp = _ppal[0] if (_ppal and _ppal[0] in _plist) else _plist[0]
                        KG_BOLSA = 25.0
                        _es_bolsa = str(_row["tipo_tanque"] or "").strip().upper() == "BOLSA"
                        cc1, cc2 = st.columns(2)
                        _defprod = _cpr if (_cpr != "Todos" and _cpr in _plist) else _defp
                        _pcod = cc1.selectbox("Producto medido", _plist, index=_plist.index(_defprod), key="tq_prod_c")
                        _cambiar_prod = False
                        if _ppal and _pcod != _ppal[0]:
                            _cambiar_prod = st.checkbox(
                                f"🔄 Cambiar el PRODUCTO del tanque de {_ppal[0]} a {_pcod}", value=False, key="tq_cambprod",
                                help="Por defecto NO se cambia el producto del tanque: solo se registra la medición. "
                                     "Marcá esto SOLO si el tanque ahora contiene otro producto.")
                        _unidades = ["Bolsas (25 kg)", "Kilos", "Litros"] if _es_bolsa else ["Litros", "Kilos", "Bolsas (25 kg)"]
                        _unid = cc2.selectbox("Unidad de carga", _unidades, key=f"tq_unid_c_{_idt}")
                        _densp = float(_prods[_prods["codigo_producto"] == _pcod]["dens"].iloc[0])
                        _last_lts = float(_row.get("litros_actual")) if pd.notna(_row.get("litros_actual")) else 0.0
                        _last_kg = float(_row.get("kg_actual")) if pd.notna(_row.get("kg_actual")) else 0.0
                        if _last_lts > 0 or _last_kg > 0:
                            st.caption(f"📌 Predefinido con el **último valor cargado** del tanque "
                                       f"({_last_lts:,.0f} L · {_last_kg/1000:,.2f} TN). Si no cambió, guardá igual.")
                        _nbol = None
                        if _unid.startswith("Bolsas"):
                            _nbol = st.number_input("Bolsas medidas (25 kg c/u)", 0.0, 200_000.0, step=1.0,
                                                    value=float(round(_last_kg / KG_BOLSA, 0)), key=f"tq_bol_c_{_idt}")
                            _kg = _nbol * KG_BOLSA
                            _lts = (_kg / _densp) if _densp else None  # litros equivalentes: el panel y las vistas calculan TN desde litros
                        elif _unid == "Kilos":
                            _kg = st.number_input("Kilos medidos", 0.0, 5_000_000.0, step=25.0,
                                                  value=float(round(_last_kg, 0)), key=f"tq_kg_c_{_idt}")
                            _lts = (_kg / _densp) if _densp else None
                        else:
                            _lts = st.number_input("Litros medidos", 0.0, 5_000_000.0, step=100.0,
                                                   value=float(round(_last_lts, 0)), key=f"tq_lts_c_{_idt}")
                            _kg = _lts * _densp
                        _ocup = (_lts / _cap * 100) if (_cap and _lts) else None
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Equivale a", f"{_kg/1000:,.2f} TN")
                        m2.metric("En kg", f"{_kg:,.0f} kg")
                        m3.metric("Ocupación", f"{_ocup:.0f}%" if _ocup is not None else "—")
                        _cap_txt = f"Densidad {_densp:g} kg/L · capacidad {int(_cap):,} L"
                        if _unid.startswith("Bolsas"):
                            _cap_txt = f"{KG_BOLSA:g} kg por bolsa · " + _cap_txt
                        st.caption(_cap_txt)
                        cf, ch = st.columns(2)
                        _now_ar = _dtmod.now(_tzmod(_tdmod(hours=-3)))
                        _fch = cf.date_input("Fecha medición", _now_ar.date(), key="tq_fch_c")
                        _hr = ch.time_input("Hora medición", value=_now_ar.time().replace(microsecond=0), key="tq_hr_c")
                        from datetime import datetime as _dtq
                        _medido = _dtq.combine(_fch, _hr)
                        _obs = st.text_input("Observaciones", max_chars=200, key="tq_obs_c")
                        _vacio = st.checkbox("El tanque está vacío (registrar 0)", key="tq_vacio_c")
                        if st.button("💾 Guardar medición", type="primary", use_container_width=True, key="tq_save_c"):
                            if _vacio and _kg > 0:
                                st.error("Marcaste 'tanque vacío' pero cargaste una cantidad. Corregí una de las dos.")
                            elif not _vacio and _kg <= 0:
                                st.error("Cargá una cantidad mayor a 0, o marcá 'El tanque está vacío' para registrar 0.")
                            else:
                                if _vacio:
                                    _kg = 0.0
                                    _lts = 0.0
                                    _nbol = 0.0 if _nbol is not None else None
                                _obs_full = _obs or ""
                                if _nbol is not None:
                                    _obs_full = f"{_nbol:g} bolsas x {KG_BOLSA:g} kg" + (f" · {_obs_full}" if _obs_full else "")
                                try:
                                    with conectar(USR["id_usuario"]) as (conn, audit):
                                        with conn.cursor() as cur:
                                            cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto=%s", (_pcod,))
                                            _pid = cur.fetchone()[0]
                                            cur.execute("INSERT INTO produccion.fact_stock_tanque "
                                                        "(id_tanque,id_producto,medido_en,litros,kg,id_usuario,observaciones) "
                                                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                                        (_idt, _pid, _medido.isoformat(),
                                                         (float(_lts) if _lts is not None else None), float(_kg),
                                                         int(USR["id_usuario"]), _obs_full or None))
                                            # Solo si el operario marcó "cambiar producto del tanque"
                                            _ppid = _row.get("id_producto_principal")
                                            if _cambiar_prod and (pd.isna(_ppid) or int(_ppid) != int(_pid)):
                                                cur.execute("UPDATE produccion.dim_tanque SET id_producto_principal=%s WHERE id_tanque=%s",
                                                            (int(_pid), _idt))
                                                cur.execute("INSERT INTO produccion.dim_tanque_producto (id_tanque,id_producto,es_principal) "
                                                            "VALUES (%s,%s,true) ON CONFLICT (id_tanque,id_producto) DO UPDATE SET es_principal=true",
                                                            (_idt, int(_pid)))
                                                cur.execute("UPDATE produccion.dim_tanque_producto SET es_principal=false "
                                                            "WHERE id_tanque=%s AND id_producto<>%s", (_idt, int(_pid)))
                                        audit.log("I", "fact_stock_tanque", _idt,
                                                  {"producto": _pcod, "kg": float(_kg),
                                                   "litros": (float(_lts) if _lts is not None else None),
                                                   "bolsas": (float(_nbol) if _nbol is not None else None)})
                                    if _nbol is not None:
                                        _det = f"{_nbol:g} bolsas · {_kg:,.0f} kg"
                                    elif _lts is not None:
                                        _det = f"{_lts:,.0f} L · {_kg/1000:,.2f} TN"
                                    else:
                                        _det = f"{_kg:,.0f} kg"
                                    st.success(f"Medición guardada: {_row['nombre']} · {_pcod} · {_det}.")
                                    cat.clear()
                                except Exception as e:
                                    st.exception(e)

            # ---------- Medir por cm (aforo / cubicaje) ----------
            if _vtab == "📏 Medir por cm (aforo)":
                _af = cat("SELECT t.id_tanque, t.codigo, t.nombre, t.sector, a.tipo_curva, a.altura_total_cm, "
                          "a.capacidad_litros, a.medible, a.observacion, t.id_producto_principal "
                          "FROM produccion.dim_tanque_aforo a JOIN produccion.dim_tanque t USING(id_tanque) "
                          "WHERE t.activo ORDER BY t.sector, t.codigo")
                if _af.empty:
                    st.info("No hay tanques con cubicaje cargado todavía.")
                else:
                    st.caption("El operario mide el **vacío** (cm desde el tope del tanque al líquido, con hilo o metro). "
                               "La app calcula el volumen y el % de llenado al instante.")
                    fa1, fa2 = st.columns(2)
                    _asec = fa1.selectbox("Sector", ["Todos"] + sorted(_af["sector"].dropna().unique().tolist()), key="afo_sec")
                    _ad = _af if _asec == "Todos" else _af[_af["sector"] == _asec]
                    _aopt = _ad.apply(lambda r: f"{r['nombre']} · {r['codigo']}" + ("" if r["medible"] else " · ⛔ no medible"), axis=1).tolist()
                    _asel = fa2.selectbox(f"Tanque ({len(_ad)})", _aopt, key="afo_sel")
                    _ar = _ad.iloc[_aopt.index(_asel)]
                    _aid = int(_ar["id_tanque"]); _acap = float(_ar["capacidad_litros"] or 0)
                    if not bool(_ar["medible"]):
                        st.warning(f"Este tanque está marcado **NO SE PUEDE MEDIR** ({_ar['observacion'] or ''}). "
                                   "Cargá la medición por litros en la pestaña anterior.")
                    else:
                        _altcm = float(_ar["altura_total_cm"]) if pd.notna(_ar["altura_total_cm"]) else None
                        _maxcm = _altcm if _altcm else float(cat("SELECT max(cm_vacio) m FROM produccion.dim_tanque_aforo_cm WHERE id_tanque=%s", (_aid,)).iloc[0]["m"] or 500)
                        _cm = st.number_input("Vacío medido (cm desde el tope)", 0.0, float(_maxcm), step=1.0, value=0.0, key="afo_cm")
                        _volr = cat("SELECT produccion.fn_volumen_por_vacio(%s,%s) v", (_aid, float(_cm))).iloc[0]["v"]
                        _vol = float(_volr) if _volr is not None else 0.0
                        _pct = (_vol / _acap * 100) if _acap else 0.0
                        _aperm = cat("SELECT p.codigo_producto FROM produccion.dim_tanque_producto tp "
                                     "JOIN produccion.dim_producto p ON p.id_producto=tp.id_producto "
                                     "WHERE tp.id_tanque=%s ORDER BY tp.es_principal DESC, p.codigo_producto", (_aid,))
                        _aplist = _aperm["codigo_producto"].tolist() or _prods["codigo_producto"].tolist()
                        _apcod = st.selectbox("Producto", _aplist, key="afo_prod")
                        _adens = float(_prods[_prods["codigo_producto"] == _apcod]["dens"].iloc[0])
                        _akg = _vol * _adens
                        ma1, ma2, ma3, ma4 = st.columns(4)
                        ma1.metric("Volumen", f"{_vol:,.0f} L")
                        ma2.metric("Llenado", f"{_pct:.0f}%")
                        ma3.metric("En kg", f"{_akg:,.0f} kg")
                        ma4.metric("En TN", f"{_akg/1000:,.2f}")
                        st.progress(min(1.0, max(0.0, _pct/100)))
                        st.caption(f"Capacidad {int(_acap):,} L" + (f" · altura {int(_altcm)} cm" if _altcm else "") +
                                   f" · densidad {_adens:g} kg/L · curva {_ar['tipo_curva']}")
                        if st.button("💾 Guardar al stock", type="primary", use_container_width=True, key="afo_save"):
                            if _vol <= 0:
                                st.error("El volumen calculado es 0. Revisá el vacío medido.")
                            else:
                                try:
                                    with conectar(USR["id_usuario"]) as (conn, audit):
                                        with conn.cursor() as cur:
                                            cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto=%s", (_apcod,))
                                            _apid = cur.fetchone()[0]
                                            cur.execute("INSERT INTO produccion.fact_stock_tanque "
                                                        "(id_tanque,id_producto,medido_en,litros,kg,id_usuario,observaciones) "
                                                        "VALUES (%s,%s,now(),%s,%s,%s,%s)",
                                                        (_aid, _apid, float(_vol), float(_akg), int(USR["id_usuario"]),
                                                         f"Aforo: vacío {_cm:.0f} cm"))
                                        audit.log("I", "fact_stock_tanque", _aid, {"aforo_cm": float(_cm), "litros": float(_vol)})
                                    st.success(f"Stock guardado: {_ar['nombre']} · {_apcod} · {_vol:,.0f} L "
                                               f"({_akg/1000:,.2f} TN) por aforo ({_cm:.0f} cm de vacío).")
                                    cat.clear()
                                except Exception as e:
                                    st.exception(e)

            # ---------- Editar tanque (WeDo: solo capacidad) ----------
            if _vtab == "✏️ Editar tanque":
                if USR["rol"] not in ("SUPERVISOR", "ADMIN"):
                    st.info("Solo supervisor o admin pueden editar tanques.")
                else:
                    with st.expander("➕ Dar de alta un producto nuevo (no registrado en la base)", expanded=False):
                        st.caption("Creá un producto que todavía no existe para poder asignarlo a un tanque. "
                                   "Una vez creado, aparece en los selectores de producto.")
                        _allp = cat("SELECT codigo_producto AS \"Código\", nombre_producto AS \"Nombre\", "
                                    "COALESCE(corriente,'') AS \"Corriente\", tipo_producto AS \"Tipo\" "
                                    "FROM produccion.dim_producto WHERE COALESCE(activo,true) ORDER BY codigo_producto")
                        if _allp is not None and not _allp.empty:
                            st.markdown(f"**Productos ya creados ({len(_allp)})** — revisá antes de crear uno nuevo:")
                            st.dataframe(_allp, use_container_width=True, hide_index=True, height=240)
                            _del_sel = st.selectbox("🗑️ Borrar un producto cargado", ["—"] + _allp["Código"].tolist(), key="np_del_sel")
                            if _del_sel != "—":
                                _del_ok = st.checkbox(f"Confirmo borrar **{_del_sel}**", key="np_del_ok")
                                if st.button("🗑️ Borrar producto", disabled=not _del_ok, key="np_del_btn"):
                                    try:
                                        with conectar(USR["id_usuario"]) as (conn, audit):
                                            with conn.cursor() as cur:
                                                cur.execute("DELETE FROM produccion.dim_producto WHERE codigo_producto=%s", (_del_sel,))
                                            audit.log("D", "dim_producto", 0, {"codigo": _del_sel})
                                        st.success(f"Producto {_del_sel} borrado.")
                                        cat.clear(); st.rerun()
                                    except Exception:
                                        try:
                                            with conectar(USR["id_usuario"]) as (conn, audit):
                                                with conn.cursor() as cur:
                                                    cur.execute("UPDATE produccion.dim_producto SET activo=false WHERE codigo_producto=%s", (_del_sel,))
                                                audit.log("U", "dim_producto", 0, {"codigo": _del_sel, "desactivado": True})
                                            st.warning(f"**{_del_sel}** está en uso (tanques o movimientos): no se puede borrar del todo, así que lo **desactivé** (deja de aparecer).")
                                            cat.clear(); st.rerun()
                                        except Exception as e:
                                            st.exception(e)
                        _npc1, _npc2 = st.columns(2)
                        _np_cod = (_npc1.text_input("Código *", key="np_cod", placeholder="ej. ACEITE-X") or "").strip().upper()
                        _np_nom = (_npc2.text_input("Nombre *", key="np_nom", placeholder="ej. Aceite X") or "").strip()
                        _npc3, _npc4, _npc5 = st.columns(3)
                        _np_tipo = _npc3.selectbox("Tipo", ["MP", "INSUMO", "FINAL", "SUBPRODUCTO"], key="np_tipo")
                        _np_corr = _npc4.selectbox("Corriente", ["", "VEGETAL", "ANIMAL"], key="np_corr")
                        _np_dens = _npc5.number_input("Densidad (kg/L)", 0.0, 5.0, value=0.0, step=0.01, key="np_dens")
                        if st.button("➕ Crear producto", key="np_crear"):
                            if not _np_cod or not _np_nom:
                                st.error("Código y nombre son obligatorios.")
                            else:
                                try:
                                    with conectar(USR["id_usuario"]) as (conn, audit):
                                        with conn.cursor() as cur:
                                            cur.execute("SELECT 1 FROM produccion.dim_producto WHERE UPPER(codigo_producto)=%s", (_np_cod,))
                                            if cur.fetchone():
                                                raise RuntimeError(f"Ya existe un producto con código {_np_cod}.")
                                            cur.execute(
                                                "INSERT INTO produccion.dim_producto "
                                                "(codigo_producto,nombre_producto,tipo_producto,corriente,densidad_g_ml,activo,creado_en,actualizado_en) "
                                                "VALUES (%s,%s,%s,%s,%s,true,now(),now()) RETURNING id_producto",
                                                (_np_cod, _np_nom, _np_tipo, (_np_corr or ""), (float(_np_dens) if _np_dens else None)))
                                            _npid = cur.fetchone()[0]
                                        audit.log("I", "dim_producto", int(_npid), {"codigo": _np_cod, "nombre": _np_nom})
                                    st.success(f"Producto **{_np_cod}** creado. Ya podés asignarlo al tanque abajo.")
                                    cat.clear(); st.rerun()
                                except Exception as e:
                                    st.exception(e)
                    _fe1, _fe2 = st.columns(2)
                    _esec = _fe1.selectbox("Sector", ["Todos"] + sorted(_panel["sector"].dropna().unique().tolist()), key="tqe_sec")
                    _emed = _fe2.selectbox("Tipo de medición", ["Todos", "Manual", "WeDo"], key="tqe_med")
                    _pe = _panel.copy()
                    if _esec != "Todos":
                        _pe = _pe[_pe["sector"] == _esec]
                    if _emed != "Todos":
                        _pe = _pe[_pe["fuente_medicion"] == _emed]
                    if _pe.empty:
                        st.warning("No hay tanques con esos filtros; se muestran todos.")
                        _pe = _panel
                    _o2 = _pe.apply(lambda r: f"{r['nombre']} · {r['codigo']}" + (" · 📡 WeDo" if r["fuente_medicion"] == "WeDo" else ""), axis=1).tolist()
                    _s2 = st.selectbox(f"Tanque a editar ({len(_pe)})", _o2, key="tq_sel_e")
                    _r2 = _pe.iloc[_o2.index(_s2)]
                    _idt2 = int(_r2["id_tanque"])
                    _es_wedo = (_r2["fuente_medicion"] == "WeDo")
                    _cap = st.number_input("Capacidad (litros)", 0.0, 5_000_000.0, step=100.0,
                                           value=float(_r2["capacidad_litros"]) if pd.notna(_r2["capacidad_litros"]) else 0.0, key="tq_cap_e")
                    if _es_wedo:
                        st.info("🛰️ Tanque **WeDo**: el **stock** lo maneja el sensor radar "
                                "(se corrige en *Cargar medición → incluir WeDo*). Acá podés editar "
                                "**producto, capacidad y estado**.")
                    _codes = _prods["codigo_producto"].tolist()
                    _pp2 = _prods[_prods["id_producto"] == _r2["id_producto_principal"]]["codigo_producto"].tolist()
                    _ppal_sel = st.selectbox("Producto que contiene (principal)", ["(sin asignar)"] + _codes,
                                             index=(_codes.index(_pp2[0]) + 1 if _pp2 else 0), key="tq_ppal_e")
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

            # ---------- Alta / baja de tanques ----------
            if _vtab == "➕ Alta / baja":
                if USR["rol"] not in ("SUPERVISOR", "ADMIN"):
                    st.info("Solo supervisor o admin pueden dar de alta o baja tanques.")
                else:
                    st.markdown('<div class="section-title">➕ Nuevo tanque</div>', unsafe_allow_html=True)
                    _secs_ex = sorted(_panel["sector"].dropna().unique().tolist())
                    _tipos_ex = sorted(_panel["tipo_tanque"].dropna().unique().tolist()) or ["Cilíndrico"]
                    _codes_a = _prods["codigo_producto"].tolist()
                    with st.form("tq_alta_form"):
                        a1, a2 = st.columns(2)
                        _a_nom = a1.text_input("Nombre *", max_chars=80, placeholder="ej. Potasio cáustico 2")
                        _a_cod = a2.text_input("Código único *", max_chars=60, placeholder="ej. CR-POTASIO-2")
                        a3, a4 = st.columns(2)
                        _a_sec = a3.selectbox("Sector *", _secs_ex + ["➕ Otro (escribirlo abajo)"])
                        _a_sec_n = a4.text_input("Nuevo sector (solo si elegiste ➕ Otro)", max_chars=60)
                        a5, a6 = st.columns(2)
                        _a_tip = a5.selectbox("Tipo de tanque", _tipos_ex)
                        _a_cap = a6.number_input("Capacidad (litros)", 0.0, 5_000_000.0, step=1000.0, value=0.0)
                        a7, a8 = st.columns(2)
                        _a_ppal = a7.selectbox("Producto principal", ["(sin asignar)"] + _codes_a)
                        _a_perm = a8.multiselect("Otros productos que puede almacenar", _codes_a)
                        _a_ok = st.form_submit_button("➕ Crear tanque", type="primary", use_container_width=True)
                    if _a_ok:
                        _sec_final = (_a_sec_n or "").strip() if _a_sec.startswith("➕") else _a_sec
                        if not (_a_nom or "").strip() or not (_a_cod or "").strip():
                            st.error("Completá nombre y código.")
                        elif not _sec_final:
                            st.error("Elegiste ➕ Otro: escribí el nombre del nuevo sector.")
                        else:
                            try:
                                with conectar(USR["id_usuario"]) as (conn, audit):
                                    with conn.cursor() as cur:
                                        cur.execute("SELECT 1 FROM produccion.dim_tanque WHERE upper(codigo)=upper(%s)", (_a_cod.strip(),))
                                        if cur.fetchone():
                                            raise ValueError(f"Ya existe un tanque con código {_a_cod.strip()}.")
                                        _pidn = None
                                        if _a_ppal != "(sin asignar)":
                                            cur.execute("SELECT id_producto FROM produccion.dim_producto WHERE codigo_producto=%s", (_a_ppal,))
                                            _pidn = cur.fetchone()[0]
                                        cur.execute(
                                            "INSERT INTO produccion.dim_tanque "
                                            "(codigo,nombre,sector,tipo_tanque,capacidad_litros,id_producto_principal,metodo_medicion,activo) "
                                            "VALUES (%s,%s,%s,%s,%s,%s,'Manual',TRUE) RETURNING id_tanque",
                                            (_a_cod.strip(), _a_nom.strip(), _sec_final, _a_tip,
                                             (float(_a_cap) if _a_cap else None), _pidn))
                                        _idn = cur.fetchone()[0]
                                        _todos = set(_a_perm) | ({_a_ppal} if _a_ppal != "(sin asignar)" else set())
                                        for c in _todos:
                                            cur.execute("INSERT INTO produccion.dim_tanque_producto (id_tanque,id_producto,es_principal) "
                                                        "SELECT %s, id_producto, %s FROM produccion.dim_producto WHERE codigo_producto=%s "
                                                        "ON CONFLICT (id_tanque,id_producto) DO NOTHING",
                                                        (_idn, c == _a_ppal, c))
                                    audit.log("I", "dim_tanque", _idn, {"codigo": _a_cod.strip(), "sector": _sec_final, "tipo": _a_tip})
                                st.success(f"Tanque creado: {_a_nom.strip()} · {_a_cod.strip()} · {_sec_final}.")
                                cat.clear(); st.rerun()
                            except ValueError as _ve:
                                st.error(str(_ve))
                            except Exception as e:
                                st.exception(e)

                    st.divider()
                    st.markdown('<div class="section-title">🗑️ Borrar / desactivar tanque</div>', unsafe_allow_html=True)
                    _ob = _panel.apply(lambda r: f"{r['nombre']} · {r['codigo']} · {r['sector']}" + ("" if bool(r["activo"]) else " · ⛔ inactivo"), axis=1).tolist()
                    _sb = st.selectbox("Tanque", _ob, key="tq_sel_b")
                    _rb = _panel.iloc[_ob.index(_sb)]
                    _idb = int(_rb["id_tanque"])
                    _nref = cat("SELECT (SELECT count(*) FROM produccion.fact_stock_tanque WHERE id_tanque=%s) med, "
                                "(SELECT count(*) FROM produccion.fact_movimiento_tanque WHERE id_tanque=%s) mov", (_idb, _idb))
                    _nmed = int(_nref.iloc[0]["med"]); _nmov = int(_nref.iloc[0]["mov"])
                    st.caption(f"Historial: **{_nmed}** mediciones · **{_nmov}** movimientos de stock.")
                    if bool(_rb["es_wedo"]):
                        st.warning("🛰️ Tanque con sensor WeDo: solo se puede **desactivar** (para eliminarlo hay que desvincular el sensor primero).")
                    _conf = st.checkbox("Confirmo que quiero dar de baja este tanque", key="tq_conf_b")
                    b1, b2 = st.columns(2)
                    if b1.button("⛔ Desactivar (recomendado)", use_container_width=True, key="tq_des_b", disabled=not _conf):
                        try:
                            with conectar(USR["id_usuario"]) as (conn, audit):
                                with conn.cursor() as cur:
                                    cur.execute("UPDATE produccion.dim_tanque SET activo=FALSE WHERE id_tanque=%s", (_idb,))
                                audit.log("U", "dim_tanque", _idb, {"activo": False, "motivo": "baja"})
                            st.success(f"Tanque desactivado: {_rb['nombre']}. Conserva todo su historial; se reactiva desde Editar tanque.")
                            cat.clear(); st.rerun()
                        except Exception as e:
                            st.exception(e)
                    if b2.button("🗑️ Eliminar definitivamente", type="primary", use_container_width=True, key="tq_del_b",
                                 disabled=(not _conf) or bool(_rb["es_wedo"])):
                        try:
                            with conectar(USR["id_usuario"]) as (conn, audit):
                                with conn.cursor() as cur:
                                    cur.execute("DELETE FROM produccion.dim_tanque WHERE id_tanque=%s", (_idb,))
                                audit.log("D", "dim_tanque", _idb, {"codigo": _rb["codigo"]})
                            st.success(f"Tanque eliminado: {_rb['nombre']} · {_rb['codigo']}.")
                            cat.clear(); st.rerun()
                        except Exception as e:
                            import psycopg2 as _pg2
                            if isinstance(e, _pg2.Error) and getattr(e, "pgcode", None) == "23503":
                                st.error("No se puede eliminar: el tanque tiene historial asociado (mediciones, movimientos, aforo o parámetros de lab). "
                                         "Usá **Desactivar** para sacarlo de uso conservando los datos.")
                            else:
                                st.exception(e)

            # ---------- Histórico / variación diaria (manual + WeDo) ----------
            if _vtab == "📈 Histórico / variación":
                _oh = _panel.apply(lambda r: f"{r['nombre']} · {r['codigo']} · {r['fuente_medicion']}", axis=1).tolist()
                _selh = st.selectbox("Tanque", _oh, key="tq_hist_sel")
                _rh = _panel.iloc[_oh.index(_selh)]
                _idh = int(_rh["id_tanque"])
                _dias = st.slider("Últimos días", 1, 90, 14, key="tq_hist_dias")
                _serie = cat("SELECT medido_en, litros, nivel_pct, observaciones "
                             "FROM produccion.fact_stock_tanque WHERE id_tanque=%s "
                             "AND medido_en >= now() - make_interval(days => %s) "
                             "AND litros IS NOT NULL ORDER BY medido_en", (_idh, int(_dias)))
                if _serie.empty:
                    st.info("Sin lecturas en el rango elegido.")
                else:
                    _hc1, _hc2, _hc3 = st.columns(3)
                    _hc1.metric("Lecturas", len(_serie))
                    _hc2.metric("Último (L)", f"{pd.to_numeric(_serie['litros'],errors='coerce').iloc[-1]:,.0f}")
                    _hc3.metric("Fuente", _rh["fuente_medicion"])
                    st.markdown("**Evolución del stock (litros)**")
                    st.line_chart(_serie[["medido_en", "litros"]].dropna().set_index("medido_en"), use_container_width=True)
                    _vd = cat("SELECT fecha, fuente, lecturas, litros_apertura, litros_cierre, "
                              "variacion_intradia, variacion_vs_dia_anterior, min_litros, max_litros "
                              "FROM produccion.vw_tanque_variacion_diaria WHERE id_tanque=%s "
                              "ORDER BY fecha DESC LIMIT %s", (_idh, int(_dias)))
                    st.markdown("**Variación diaria** — litros (positivo = ingreso · negativo = salida)")
                    try:
                        st.dataframe(_vd, use_container_width=True, hide_index=True,
                                     column_config={
                                         "fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                         "litros_apertura": st.column_config.NumberColumn(format="%d"),
                                         "litros_cierre": st.column_config.NumberColumn(format="%d"),
                                         "variacion_intradia": st.column_config.NumberColumn(format="%d"),
                                         "variacion_vs_dia_anterior": st.column_config.NumberColumn(format="%d"),
                                     })
                    except Exception:
                        st.dataframe(_vd, use_container_width=True, hide_index=True)
                    st.caption("Incluye **WeDo (sensor)** y **manuales** — todo en `fact_stock_tanque`. "
                               "La columna **fuente** indica si el día fue WeDo, Manual o Mixto.")

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

            st.markdown("**🔐 Accesos a la página** — qué secciones ve este usuario")
            with st.form(f"form_secc_{u_id}"):
                _df_sa = cat("SELECT secciones_app FROM produccion.dim_usuario WHERE id_usuario=%s", (u_id,))
                _sa_act = list(_df_sa.iloc[0]["secciones_app"]) if (not _df_sa.empty and _df_sa.iloc[0]["secciones_app"]) else None
                st.caption("**Vacío = usa el default del rol** (" + ", ".join(_secciones_default(u_row["rol"])) + "). "
                           "Elegí una o más secciones para **restringir** exactamente a esas. "
                           "Si dejás **una sola**, el usuario entra directo a esa sección y no puede salir.")
                _sa_sel = st.multiselect(
                    "Secciones permitidas",
                    [sc for sc, _ in SECCIONES_APP],
                    default=(_sa_act or []),
                    format_func=lambda sc: dict(SECCIONES_APP)[sc], key=f"sasel_{u_id}")
                _estado_sa = ("✅ Restringido a: " + ", ".join(dict(SECCIONES_APP)[x] for x in _sa_sel)) if _sa_sel else "↩️ Usará el default del rol"
                st.caption(_estado_sa)
                if st.form_submit_button("💾 Guardar accesos", use_container_width=True):
                    try:
                        cambiar_secciones_app(USR["id_usuario"], u_id, (_sa_sel or None))
                        st.success("Accesos actualizados. Aplican en el próximo ingreso del usuario.")
                        cat.clear(); st.rerun()
                    except Exception as e:
                        st.error(str(e))
            st.caption("⚠️ La sección Admin siempre exige rol ADMIN, aunque esté marcada. "
                       "Los cambios aplican cuando el usuario vuelve a entrar (o recarga la página).")

            st.divider()
            st.markdown("**🤖 Consultas IA — RAG semántico**")
            st.caption(
                "Sincroniza los ejemplos pregunta→SQL como embeddings (pgvector) para que "
                "el chat recupere los más parecidos a cada pregunta. Idempotente: solo embebe "
                "los ejemplos nuevos. Corrélo cuando agregues ejemplos a training_examples.json."
            )
            if st.button("🔄 Sincronizar ejemplos (RAG)", key="rag_sync", use_container_width=True):
                try:
                    from chat.engine import sync_embeddings as _sync_rag
                    with st.spinner("Generando embeddings…"):
                        _n = _sync_rag(verbose=False)
                    if _n == 0:
                        st.info("Todos los ejemplos ya estaban embebidos. Nada que hacer.")
                    else:
                        st.success(f"Listo: {_n} ejemplo(s) embebido(s). El chat ya usa RAG semántico.")
                except Exception as _e:
                    st.error(f"No se pudo sincronizar: {_e}")

    elif st.session_state.section == "STOCK":
        # =================== STOCK (incluye ingresos de camiones) ===================
        _stk_top = st.radio("Vista", ["📦 Stock y movimientos", "🚛 Ingresos diarios"],
                            horizontal=True, key="stk_top_view", label_visibility="collapsed")
        if _stk_top.startswith("📦"):
            try:
                from stock_section import render as _render_stock
                _render_stock(USR, cat)
            except Exception as _e:
                st.error(f"No se pudo cargar Stock: {_e}")
        else:
            try:
                _render_porteria(USR, cat, conectar)
            except Exception as _e:
                import traceback as _tbp
                st.error(f"No se pudo cargar Ingresos: {_e}")
                with st.expander("Detalle"):
                    st.code(_tbp.format_exc())

    elif st.session_state.section == "CONDICIONALES":
        try:
            from condicionales import render as _render_cond
            _render_cond(USR, cat, conectar)
        except Exception as _e:
            import traceback as _tbc
            st.error(f"No se pudo cargar Condicionales: {_e}")
            with st.expander("Detalle"):
                st.code(_tbc.format_exc())

    elif st.session_state.section == "ESTADO":
        try:
            _render_estado_planta(cat, conectar, USR)
        except Exception as _e:
            import traceback as _tbe
            st.error(f"No se pudo cargar Estado de planta: {_e}")
            with st.expander("Detalle"):
                st.code(_tbe.format_exc())

    elif st.session_state.section == "CIERRES":
        try:
            from cierres_section import render as _render_cierres
            _render_cierres(USR, cat, conectar)
        except Exception as _e:
            import traceback as _tbc2
            st.error(f"No se pudo cargar Cierres mensuales: {_e}")
            with st.expander("Detalle"):
                st.code(_tbc2.format_exc())

    elif st.session_state.section == "INICIAR":
        # =================== PRODUCCIÓN EN PLANTA ===================
        _ip_view = st.radio("Vista", ["👷 Iniciar producción", "🧪 Laboratorio", "🚛 Ingresos", "🛢️ Tanques"],
                            horizontal=True, key="iniciar_view", label_visibility="collapsed")
        if _ip_view.startswith("👷"):
            try:
                from carga_por_id import render as _render_iniciar
                _render_iniciar(USR, cat, conectar, etapas_de_proceso, params_proceso)
            except Exception as _e:
                st.error(f"No se pudo cargar Producción en planta: {_e}")
        elif _ip_view.startswith("🧪"):
            st.markdown("#### 🧪 Evaluaciones de laboratorio (consulta)")
            _lc1, _lc2 = st.columns([2, 1])
            _lprod = _lc1.text_input("Filtrar producto / ticket / calidad contiene", key="ip_lab_q")
            _llim = _lc2.number_input("Límite filas", 50, 5000, 300, step=50, key="ip_lab_lim")
            _w = ""
            _p = []
            if _lprod.strip():
                _w = "WHERE (producto_lab ILIKE %s OR ticket ILIKE %s OR calidad_final_lab ILIKE %s)"
                _p = [f"%{_lprod.strip()}%"] * 3
            _base = "SELECT * FROM produccion.v_procesos_lab_efectivo " + _w + " ORDER BY fecha DESC NULLS LAST LIMIT " + str(int(_llim))
            _sql = ("SELECT pl.fecha AS \"Fecha\", pl.ticket AS \"Ticket\", "
                    "CASE WHEN tx.transaccion IS NOT NULL THEN '🚛 Portería' "
                    "WHEN bp.id_batch IS NOT NULL THEN '🏭 Producción' ELSE '— otro' END AS \"Origen\", "
                    "COALESCE(bp.identificador_unidad,'') AS \"Reacción\", "
                    "pl.producto_lab AS \"Producto\", pl.calidad_final_lab AS \"Calidad\", pl.rechazado AS \"Estado\", "
                    "tx.cliente AS \"Proveedor\", tx.procedencia AS \"Procedencia\", "
                    "COALESCE(NULLIF(pl.patente_chasis,''), tx.patente_chasis) AS \"Patente\", "
                    "pl.num_cisterna AS \"Cisterna\", "
                    "pl.prc_acidez AS \"Acidez\", pl.prc_agua AS \"Agua\", pl.prc_sedimentos AS \"Sedim\", "
                    "pl.ppm_azufre AS \"Azufre ppm\", pl.ppm_fosforo AS \"Fosforo ppm\", pl.empleado AS \"Analista\" "
                    "FROM (" + _base + ") pl "
                    "LEFT JOIN LATERAL (SELECT cliente, procedencia, patente_chasis, transaccion "
                    "FROM produccion.v_transacciones_limpias WHERE CAST(transaccion AS text)=regexp_replace(pl.ticket,'\\.0+$','') "
                    "ORDER BY fecha_entrada DESC NULLS LAST LIMIT 1) tx ON true "
                    "LEFT JOIN LATERAL (SELECT id_batch, identificador_unidad FROM produccion.fact_batch_proceso "
                    "WHERE ticket_producto_final=pl.ticket OR ticket_validacion_lab=pl.ticket LIMIT 1) bp ON true "
                    "ORDER BY pl.fecha DESC NULLS LAST")
            try:
                _ld = cat(_sql, tuple(_p) if _p else None)
                if _ld is not None and not _ld.empty:
                    _oc1, _oc2, _oc3 = st.columns(3)
                    _oc1.metric("Evaluaciones", len(_ld))
                    _oc2.metric("De portería", int((_ld["Origen"].astype(str).str.contains("Portería")).sum()))
                    _oc3.metric("De producción", int((_ld["Origen"].astype(str).str.contains("Producción")).sum()))
                    _orig = st.multiselect("Origen", sorted(_ld["Origen"].dropna().unique().tolist()),
                                           default=sorted(_ld["Origen"].dropna().unique().tolist()), key="ip_lab_orig")
                    _lv = _ld[_ld["Origen"].isin(_orig)] if _orig else _ld
                    st.dataframe(_lv, hide_index=True, use_container_width=True, height=520)
                    st.download_button("⬇️ CSV", _lv.to_csv(index=False).encode("utf-8"),
                                       file_name="evaluaciones_lab.csv", mime="text/csv", key="ip_lab_dl")
                else:
                    st.info("Sin evaluaciones para ese filtro.")
            except Exception as _e:
                st.exception(_e)
        elif _ip_view.startswith("🚛"):
            st.markdown("#### 🚛 Ingresos de camiones (portería)")
            _porteria_entrada_diaria(cat)
        else:
            st.markdown("#### 🛢️ Tanques · vista de planta")
            try:
                _tq = cat("SELECT t.codigo AS \"Codigo\", t.nombre AS \"Tanque\", t.sector AS \"Sector\", "
                          "p.codigo_producto AS \"Producto\", COALESCE(s.litros_actual,0) AS \"Stock L\", "
                          "t.capacidad_litros AS \"Capacidad L\", "
                          "GREATEST(COALESCE(t.capacidad_litros,0)-COALESCE(s.litros_actual,0),0) AS \"Disponible L\", "
                          "LEAST(round((COALESCE(s.litros_actual,0)/NULLIF(t.capacidad_litros,0)*100)::numeric,0),100) AS \"Ocupacion\", "
                          "pp.acidez_pct AS \"Acidez\", pp.agua_pct AS \"Agua\", pp.sedimentos_pct AS \"Sedim\", "
                          "pp.ppm_azufre AS \"Azufre ppm\", pp.ppm_fosforo AS \"Fosforo ppm\", "
                          "pp.ultima_evaluacion_ts AS \"Ult. lab\", "
                          "to_char(s.ultima_medicion AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS \"Medicion\", "
                          "med.fuente AS \"Fuente\" "
                          "FROM produccion.dim_tanque t "
                          "LEFT JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
                          "LEFT JOIN produccion.vw_stock_tanque_actual s ON s.id_tanque=t.id_tanque "
                          "LEFT JOIN produccion.fact_param_tanque pp ON pp.id_tanque=t.id_tanque AND pp.id_producto=t.id_producto_principal "
                          "LEFT JOIN LATERAL (SELECT CASE WHEN fs.id_usuario IS NULL THEN 'WeDo' ELSE 'Manual' END AS fuente "
                          "FROM produccion.fact_stock_tanque fs "
                          "WHERE fs.id_tanque=t.id_tanque ORDER BY fs.medido_en DESC NULLS LAST LIMIT 1) med ON true "
                          "WHERE COALESCE(t.activo,true) ORDER BY t.sector, t.nombre")
                if _tq is None or _tq.empty:
                    st.info("Sin tanques cargados.")
                else:
                    import pandas as _pd, html as _html
                    _tq = _tq.copy()
                    for _c in ["Stock L","Capacidad L","Disponible L","Ocupacion","Acidez","Agua","Sedim","Azufre ppm","Fosforo ppm"]:
                        _tq[_c] = _pd.to_numeric(_tq[_c], errors="coerce")
                    # paleta estable por producto
                    _pal = ["#4f46e5","#0ea5e9","#16a34a","#f59e0b","#db2777","#7c3aed","#0891b2","#65a30d",
                            "#dc2626","#ca8a04","#2563eb","#9333ea","#059669","#e11d48","#0d9488","#92400e"]
                    _prod_all = sorted([x for x in _tq["Producto"].dropna().unique().tolist()])
                    _color = {p: _pal[i % len(_pal)] for i, p in enumerate(_prod_all)}
                    # filtros
                    fc1, fc2, fc3 = st.columns([1.4, 2, 1.2])
                    _secs = ["(todos)"] + sorted([x for x in _tq["Sector"].dropna().unique().tolist()])
                    _ssel = fc1.selectbox("Sector", _secs, key="ip_tq_sec")
                    _psel = fc2.multiselect("Producto", _prod_all, default=[], key="ip_tq_prod",
                                            help="Vacío = todos")
                    _q = fc3.text_input("Buscar tanque", key="ip_tq_q")
                    cc1, cc2 = st.columns([1, 1])
                    _vista = cc1.radio("Vista", ["🎨 Gráfico", "📋 Tabla"], horizontal=True, key="ip_tq_vista", label_visibility="collapsed")
                    _verp = cc2.toggle("Ver parámetros", value=True, key="ip_tq_params")
                    _tv = _tq.copy()
                    if _ssel != "(todos)": _tv = _tv[_tv["Sector"] == _ssel]
                    if _psel: _tv = _tv[_tv["Producto"].isin(_psel)]
                    if _q.strip():
                        _ql = _q.strip().lower()
                        _tv = _tv[_tv["Tanque"].astype(str).str.lower().str.contains(_ql) | _tv["Codigo"].astype(str).str.lower().str.contains(_ql)]
                    # resumen que se actualiza por filtro
                    _sk = _tv["Stock L"].sum()/1000.0; _ck = _tv["Capacidad L"].sum()/1000.0
                    k1,k2,k3,k4 = st.columns(4)
                    k1.metric("Tanques", len(_tv))
                    k2.metric("Stock", f"{_sk:,.1f} kL")
                    k3.metric("Capacidad", f"{_ck:,.0f} kL")
                    k4.metric("Ocupación media", f"{(_sk/_ck*100 if _ck else 0):.0f}%")
                    def _chips(series_df, by, color_by_prod):
                        g = series_df.groupby(by)["Stock L"].sum().sort_values(ascending=False)
                        out = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 8px">'
                        for name, val in g.items():
                            col = _color.get(name, "#64748b") if color_by_prod else "#334155"
                            out += (f'<span style="display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid #e2e8f0;'
                                    f'border-radius:999px;padding:3px 10px;font-size:.82rem">'
                                    f'<span style="width:10px;height:10px;border-radius:50%;background:{col}"></span>'
                                    f'<b>{_html.escape(str(name))}</b> {val/1000:,.1f} kL</span>')
                        return out + '</div>'
                    st.markdown("**Stock por producto** (según filtro)")
                    st.markdown(_chips(_tv, "Producto", True), unsafe_allow_html=True)
                    st.markdown("**Stock por sector** (según filtro)")
                    st.markdown(_chips(_tv, "Sector", False), unsafe_allow_html=True)

                    if _vista.startswith("📋"):
                        _cols = ["Codigo","Tanque","Sector","Producto","Stock L","Capacidad L","Disponible L","Ocupacion","Medicion","Fuente","Ult. lab"]
                        if _verp: _cols += ["Acidez","Agua","Sedim","Azufre ppm","Fosforo ppm"]
                        st.dataframe(_tv[_cols], hide_index=True, use_container_width=True, height=520,
                                     column_config={"Stock L": st.column_config.NumberColumn(format="%.0f"),
                                                    "Capacidad L": st.column_config.NumberColumn(format="%.0f"),
                                                    "Disponible L": st.column_config.NumberColumn(format="%.0f"),
                                                    "Ocupacion": st.column_config.ProgressColumn("Ocupación", format="%.0f%%", min_value=0, max_value=100)})
                        st.download_button("⬇️ CSV", _tv.to_csv(index=False).encode("utf-8"), file_name="tanques_stock.csv", mime="text/csv", key="ip_tq_dl")
                    else:
                        _css = """<style>
                        .tkwrap{display:flex;flex-wrap:wrap;gap:14px;margin:6px 0 18px}
                        .tkc{width:128px}
                        .tkbody{position:relative;height:118px;border:2px solid #cbd5e1;border-radius:9px 9px 16px 16px;
                          overflow:hidden;background:repeating-linear-gradient(0deg,#f8fafc,#f8fafc 9px,#eef2f7 9px,#eef2f7 18px)}
                        .tkfill{position:absolute;left:0;right:0;bottom:0;transition:height .3s;
                          box-shadow:inset 0 3px 6px rgba(255,255,255,.4)}
                        .tkpct{position:absolute;top:5px;left:0;right:0;text-align:center;font-size:.82rem;font-weight:800;
                          color:#0f172a;text-shadow:0 1px 2px #fff}
                        .tkn{font-weight:700;font-size:.84rem;margin-top:5px;line-height:1.1}
                        .tks{font-size:.72rem;color:#475569;display:flex;align-items:center;gap:5px}
                        .tkdot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
                        .tkv{font-size:.7rem;color:#64748b;margin-top:1px}
                        .tkp{font-size:.66rem;color:#334155;margin-top:3px;background:#f1f5f9;border-radius:6px;padding:2px 5px}
                        .sech{font-weight:800;font-size:1rem;margin:14px 0 2px;padding:4px 10px;border-left:5px solid #4f46e5;background:#eef1fe;border-radius:0 8px 8px 0}
                        </style>"""
                        def _fnum(v, suf="", dec=1):
                            return "—" if _pd.isna(v) else (f"{v:,.{dec}f}{suf}")
                        html_out = _css
                        _secs_list = [x for x in _tv["Sector"].fillna("(sin sector)").unique().tolist()]
                        for sec in sorted(_secs_list):
                            _sub = _tv[_tv["Sector"].fillna("(sin sector)") == sec]
                            html_out += f'<div class="sech">{_html.escape(str(sec))} · {len(_sub)} tanques · {_sub["Stock L"].sum()/1000:,.1f} kL</div>'
                            html_out += '<div class="tkwrap">'
                            for _, r in _sub.iterrows():
                                prod = r["Producto"] if _pd.notna(r["Producto"]) else "—"
                                col = _color.get(prod, "#94a3b8")
                                oc = 0 if _pd.isna(r["Ocupacion"]) else float(r["Ocupacion"])
                                libre = max(0, 100 - oc)
                                grad = f"linear-gradient(180deg,{col}cc,{col})"
                                params = ""
                                if _verp:
                                    params = (f'<div class="tkp">Ac {_fnum(r["Acidez"],"%")} · Ag {_fnum(r["Agua"],"%")} · '
                                              f'Az {_fnum(r["Azufre ppm"],"",0)} · P {_fnum(r["Fosforo ppm"],"",0)}</div>')
                                html_out += (
                                    f'<div class="tkc">'
                                    f'<div class="tkbody"><div class="tkfill" style="height:{oc:.0f}%;background:{grad}"></div>'
                                    f'<div class="tkpct">{oc:.0f}%</div></div>'
                                    f'<div class="tkn">{_html.escape(str(r["Tanque"]))}</div>'
                                    f'<div class="tks"><span class="tkdot" style="background:{col}"></span>{_html.escape(str(prod))}</div>'
                                    f'<div class="tkv">{r["Stock L"]/1000:,.1f} / {r["Capacidad L"]/1000:,.0f} kL · libre {libre:.0f}%</div>'
                                    f'<div class="tkv">🕒 {_html.escape(str(r["Medicion"])) if _pd.notna(r["Medicion"]) else "sin medición"}'
                                    + (f' · <span style="color:#0891b2">🛰️ WeDo</span>' if str(r.get("Fuente"))=="WeDo" else (f' · <span style="color:#7c3aed">✋ Manual</span>' if str(r.get("Fuente"))=="Manual" else "")) + '</div>'
                                    f'{params}</div>')
                            html_out += '</div>'
                        st.markdown(html_out, unsafe_allow_html=True)
                        st.caption("Cada tanque muestra su **nivel de llenado** (color por producto), ocupación %, stock/capacidad y % libre. "
                                   "Filtrá por sector o producto y el resumen de arriba se actualiza.")
            except Exception as _e:
                st.exception(_e)

    elif st.session_state.section == "PLANIFICACION":
        # =================== CENTRO DE PLANIFICACIÓN (dirección) ===================
        try:
            from planificacion import render as _render_plan
            st.session_state["_plan_helpers"] = {
                "proceso_desde_mp": proceso_desde_mp,
                "fuente_mp_combinada": fuente_mp_combinada,
                "corriente_de_mp_lab": corriente_de_mp_lab,
                "densidad_de": densidad_de,
                "K": K,
                "ultimas_muestras_glicerina": ultimas_muestras_glicerina,
                "productos": productos,
                "bienes_uso_full": bienes_uso_full,
            }
            _render_plan(USR, cat, conectar, siguiente_identificador)
        except Exception as _e:
            import traceback as _tb
            st.error(f"No se pudo cargar el Centro de Planificación: {_e}")
            with st.expander("🔧 Detalle técnico (para diagnóstico)"):
                st.code(_tb.format_exc())

    elif st.session_state.section == "DIRECCION":
        # =================== DIRECCIÓN (aprobaciones fuera de norma) ===================
        try:
            from planificacion import _render_aprobaciones
            st.title("🛂 Dirección")
            st.caption("Aprobación de planificaciones **fuera de norma**: cargas menores al 80% de la capacidad "
                       "del reactor o bacha. Mientras el ticket esté pendiente, el operario no puede iniciar la producción.")
            _render_aprobaciones(USR, cat, conectar, compacto=False)
        except Exception as _e:
            st.error(f"No se pudo cargar Dirección: {_e}")

    elif st.session_state.section == "FORMULAS":
        # =================== FÓRMULAS (dirección) ===================
        try:
            from formulas_section import render as _render_formulas
            _render_formulas(USR, cat, conectar)
        except Exception as _e:
            st.error(f"No se pudo cargar Fórmulas: {_e}")

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
    sub_nueva, sub_edit, sub_pfinal, sub_gasto, sub_etapas, sub_evins = st.tabs(["➕ Nueva carga", "\U0001F4CA Dashboard de reacciones", "\U0001f3c1 Acopio final", "⚠️ Gasto extraordinario", "\U0001f6e0️ Etapas/tiempos", "\U0001f9f4 Evaluar insumo"])

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
        import datetime as _dtt
        _h_now = _dtt.datetime.now().hour
        turno = "mañana" if _h_now < 14 else ("tarde" if _h_now < 22 else "noche")
        c3.text_input("Turno · automático (por horario)", value=turno, disabled=True, key="b_t",
                      help="El turno se define solo según la hora de carga; no se elige a mano.")

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
        identificador = siguiente_identificador(sector)
        st.text_input(label_id + " · automático por sector", value=identificador, disabled=True, key="b_id",
                      help="Numeración automática e incremental, con prefijo del sector (RX/BA/EX/RP).")

        # Corriente (Vegetal/Animal) — se define al inicio del armado. Obligatoria en REACTORES/BACHAS.
        corriente_v = None
        if sector == "BACHAS":
            corriente_v = st.radio(
                "Corriente *", ["VEGETAL", "ANIMAL"], horizontal=True, key="b_corriente",
                format_func=lambda c: "🌱 Vegetal" if c == "VEGETAL" else "🐄 Animal",
                help="Origen del material. Define si la producción es vegetal o animal."
            )
        elif sector == "REACTORES":
            corriente_v = None  # la corriente se deriva de la MP y se muestra en el banner del reactor

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
            st.markdown('<div class="section-title">🏭 Reactor y materia prima</div>', unsafe_allow_html=True)
            cR1, cR2 = st.columns(2)
            cod_bien = cR1.selectbox(
                "Reactor (bien de uso) *", bienes_uso_full["codigo"].tolist(), key="b_bien",
                format_func=lambda c: bienes_uso_full[bienes_uso_full["codigo"]==c].iloc[0]["nombre_ui"]
            )
            fila_bien = bienes_uso_full[bienes_uso_full["codigo"]==cod_bien].iloc[0]
            id_bien_sel = int(fila_bien["id_bien_uso"])
            _mp_reactor_opts = [c for c in productos_mp["codigo_producto"].tolist()
                                if str(c).startswith(("AG-", "AFE", "SEBO", "BORRA"))] or productos_mp["codigo_producto"].tolist()
            if not _mp_reactor_opts:
                _mp_reactor_opts = ["AG-C"]
            mp_pre = cR2.selectbox(
                "Materia prima a tratar *", _mp_reactor_opts, key="b_mp_pre",
                help="El tipo de reacción y la corriente se derivan automáticamente de la MP.")
            tipo_proceso_sel = proceso_desde_mp(mp_pre)
            if st.session_state.get("mp_pre_last") != mp_pre:
                st.session_state["mp_pre_last"] = mp_pre
                st.session_state.pop("mp_corr", None)
            corriente_v = st.session_state.get("mp_corr") or corriente_de_mp_lab(mp_pre)
            _proc_desc = (tipos_proceso[tipos_proceso["codigo"] == tipo_proceso_sel].iloc[0]["descripcion"]
                          if tipo_proceso_sel in tipos_proceso["codigo"].tolist() else (tipo_proceso_sel or "—"))
            _et_proc = etapas_de_proceso(proceso_key_de(sector, tipo_proceso_sel))
            _et_codes = _et_proc["etapa"].tolist()
            etapa_sel = "ARMADO" if "ARMADO" in _et_codes else (_et_codes[0] if _et_codes else "ARMADO")
            _cap_l0 = int(fila_bien['capacidad_max_l'] or 0)
            _dft = duraciones_etapa[(duraciones_etapa["sector"] == sector) & (duraciones_etapa["tipo_proceso"] == tipo_proceso_sel)]
            _tot_t = int(_dft["duracion_target_min"].sum()) if not _dft.empty else 0
            _corr_em = "🌱" if corriente_v == "VEGETAL" else ("🐄" if corriente_v == "ANIMAL" else "•")
            def _cell(lbl, val):
                return ("<div style='min-width:92px'>"
                        f"<div style='font-size:10.5px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;font-weight:700'>{lbl}</div>"
                        f"<div style='font-size:15px;font-weight:700;color:#0f172a;margin-top:2px'>{val}</div></div>")
            st.markdown(
                "<div style='background:linear-gradient(135deg,#eef2ff,#faf5ff);border:1px solid #e0e7ff;"
                "border-radius:14px;padding:12px 18px;margin:8px 0 12px;display:flex;flex-wrap:wrap;gap:22px;align-items:center'>"
                + _cell("Proceso", _proc_desc)
                + _cell("Corriente", f"{_corr_em} {corriente_v or '—'}")
                + _cell("Capacidad", f"{_cap_l0:,} L")
                + _cell("Duración objetivo", (f"{_tot_t/60:.1f} h" if _tot_t else "—"))
                + _cell("Etapa inicial", "Armado")
                + "</div>", unsafe_allow_html=True)

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

            inicio_dt = _ahora_ar()
            fin_dt = None
            tiempo_est = None
            st.caption("🕒 El inicio de la reacción se registra automáticamente al guardar (timestamp).")

        elif sector == "BACHAS":
            # BACHAS también usa el flujo de etapas: la carga arranca en ARMADO.
            etapa_sel = "ARMADO"
            st.text_input("Etapa actual *", value="ARMADO (carga de borra + mezcla)", disabled=True, key="b_etapa_disp_b")
            inicio_dt = _ahora_ar()
            st.caption("🕒 El inicio se registra automáticamente al guardar. Avanzás las etapas desde **Avanzar etapa**.")

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
            st.markdown('<div class="section-title">🎯 Producto buscado</div>', unsafe_allow_html=True)
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
        mp_fuentes = {}               # idx en mps_ingresadas -> {'fuente','id_tanque','kg','ticket'}
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
                # PRODUCCION_ARE: la MP (AG-C/SEBO) ya se eligió arriba (define el proceso).
                cod = mp_pre
                _dens_mp = densidad_de(cod) or (0.92 if cod == "AG-C" else 0.91)
                _cap_l = float(fila_bien["capacidad_max_l"] or 0)
                _kg_planeado = _cap_l * _dens_mp
                _aM1, _aM2, _aM3 = st.columns(3)
                _aM1.metric("Capacidad reactor", f"{int(_cap_l):,} L")
                _aM2.metric(f"Densidad {cod}", f"{_dens_mp:.2f} kg/L")
                _aM3.metric("Q MP objetivo", f"{_kg_planeado:,.0f} kg", f"{_kg_planeado/1000:,.2f} TN")
                st.caption(f"ℹ️ Elegí la fuente del **{cod}** (portería y/o tanque). **Los parámetros de laboratorio vienen con la fuente.** El Q AG se asume = capacidad × densidad.")
                _kg_src, _ports_src, _avg_src, _corr_src = fuente_mp_combinada(cod, key_prefix="b_mpf_are", target_kg=float(_kg_planeado))
                _kg_used = float(_kg_src) if (_kg_src and _kg_src > 0) else float(_kg_planeado)
                mps_ingresadas.append((cod, _kg_used))
                litros_ini = round(_kg_used / _dens_mp, 1) if _dens_mp else None
                if _ports_src:
                    mp_fuentes[len(mps_ingresadas)-1] = _ports_src
                _lab_avg_mp0 = _avg_src or {}
                if _lab_avg_mp0:
                    _bm1, _bm2, _bm3 = st.columns(3)
                    _bm1.metric("Acidez (fuente)", f"{_lab_avg_mp0['prc_acidez']*100:.3f}%" if _lab_avg_mp0.get('prc_acidez') is not None else "—")
                    _bm2.metric("% Agua (fuente)", f"{_lab_avg_mp0['prc_agua']*100:.3f}%" if _lab_avg_mp0.get('prc_agua') is not None else "—")
                    _bm3.metric("Azufre (fuente)", f"{_lab_avg_mp0['ppm_azufre']:.0f} ppm" if _lab_avg_mp0.get('ppm_azufre') is not None else "—")
                else:
                    st.warning(f"Elegí una fuente (portería o tanque) para traer los parámetros de laboratorio de {cod}.")
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

                        # --- Fuente combinable: portería (tickets) + tanque ---
                        _kg, _ports, _avg, _corr_src = fuente_mp_combinada(cod, key_prefix=f"b_mpf_{i}", permite_multiselect=_usa_multiselect_mp)
                        if cod and _kg > 0:
                            mps_ingresadas.append((cod, float(_kg)))
                            mp_fuentes[len(mps_ingresadas)-1] = _ports
                            if i == 0:
                                _lab_avg_mp0 = _avg or {}
                                _dens0 = densidad_de(cod)
                                litros_ini = round(_kg / _dens0, 1) if (_kg and _dens0) else None
                                _tickets_entrada_des = "; ".join(p.get("ticket") for p in _ports if p.get("ticket")) or None
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
            st.markdown("**Glicerina a cargar** _(% glicerol viene del lab; los litros pre-cargan la fórmula y son editables)_")
            # gli_fresca_pct sale del mismo ticket de lab elegido (= glicerol_v)
            gli_fresca_pct = float(glicerol_v) if glicerol_v else 0.0
            # Default fresca (L) = glicerina estimada por fórmula / densidad
            _gli_lts_sug = int(round(float(est_glice_kg) / D_GLI)) if (est_glice_kg and D_GLI) else 0
            cG1, cG2, cG3 = st.columns(3)
            gli_fl = cG1.number_input(
                "Fresca (L)",
                min_value=0, max_value=100000, step=50,
                value=_gli_lts_sug, key="b_glfl",
                help=f"Pre-cargado con la cantidad sugerida por fórmula ({_gli_lts_sug:,} L). Ajustá si vas a cargar distinto.",
            )
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
                                   (consumos_proceso["codigo_insumo"] == "FUEL_OIL")]
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

        # 1) Insumos TÍPICOS del proceso/sector (FUEL_OIL siempre en REACTORES).
        #    Cantidad sugerida = estimado por la fórmula; el operario solo confirma/corrige.
        tipicos = []   # (codigo, cantidad_sugerida, unidad_label)
        if tipo_proceso_sel == "PRODUCCION_ARE":
            # En REACTORES el combustible es siempre FUEL OIL.
            tipicos.append(("FUEL_OIL", float(est_fuel_kg or 0.0), "kg"))
            if catalizador_tipo == "POTASIO":
                tipicos.append(("POTASIO", float(est_potasio_kg or 0.0), "kg"))
            # NaOH (soda) se carga aparte en su bloque dedicado (L/kg) → no se duplica acá.
        elif tipo_proceso_sel == "DESGOMADO_ACUOSO":
            # Fuel oil es ESTIMADO automático (no se carga a mano) → se guarda solo bajo la key FUEL_OIL.
            if est_fuel_kg:
                insumos_dict["FUEL_OIL"] = float(est_fuel_kg)
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
                    real_fuel    = float(insumos_dict.get("FUEL_OIL", 0.0) or 0)
                    real_naoh    = float(naoh_kg_v or 0)   # del bloque NaOH dedicado (kg)
                    real_potasio = float(insumos_dict.get("POTASIO", 0.0) or 0)
                    _alarma_consumo("Fuel Oil", real_fuel, est_fuel_kg, unidad="kg")
                    if catalizador_tipo == "NAOH":
                        _alarma_consumo("NaOH", real_naoh, est_naoh_kg, unidad="kg")
                        if real_potasio > 0:
                            st.warning(f"⚠️ Cargaste {real_potasio:.2f} kg de Potasio pero el catalizador elegido era NaOH.")
                    elif catalizador_tipo == "POTASIO":
                        _alarma_consumo("Potasio", real_potasio, est_potasio_kg, unidad="kg")
                        if real_naoh > 0:
                            st.warning(f"⚠️ Cargaste {real_naoh:.2f} kg de NaOH pero el catalizador elegido era Potasio.")
                elif tipo_proceso_sel == "DESGOMADO_ACUOSO":
                    real_fuel = float(insumos_dict.get("FUEL_OIL", 0.0) or 0)
                    # est_fuel_kg para DESGOMADO se computó en L (8.7 L/TN)
                    _alarma_consumo("Fuel Oil", real_fuel, est_fuel_kg, unidad="L")

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

            # Glicerina y glicerol (solo PRODUCCION_ARE)
            if tipo_proceso_sel == "PRODUCCION_ARE":
                st.markdown("**🧪 Glicerina y glicerol a guardar**")
                _g1, _g2, _g3 = st.columns(3)
                _g1.caption(f"**Glicerina fresca:** {(gli_fl or 0):,.0f} L · {(gli_fk or 0):,.1f} kg (densidad {D_GLI} kg/L)")
                _g2.caption(f"**% Glicerol fresca (lab):** {(gli_fresca_pct or 0):.2f}%"
                            + (f" · ticket {gli_ticket_sel}" if gli_ticket_sel else ""))
                _g3.caption(f"**Glicerina recuperada:** {(gli_rl or 0):,.0f} L · {(gli_rk or 0):,.1f} kg")
                _h1, _h2 = st.columns(2)
                _h1.caption(f"**% Glicerol recuperada:** {(gli_pct or 0):.1f}%")
                _h2.caption(f"**Glicerol total cargado:** {(gli_pura_total or 0):,.1f} kg"
                            + (f" · vs requerido {est_glicerol_puro_kg:,.0f} kg" if est_glicerol_puro_kg else ""))

        # ===== Cronograma de trabajo + checklist (planificación de la reacción) =====
        import datetime as _dtk
        _check_ok = True
        caldera_dt = None
        if es_reactor and not es_recup:
            st.markdown('<div class="section-title">🗓️ Cronograma de trabajo</div>', unsafe_allow_html=True)
            _pp = {}
            try:
                _dfp = cat("SELECT temp_inicial_c, tiempo_total_horas, acidez_objetivo_pct "
                           "FROM produccion.dic_proceso_parametros WHERE tipo_proceso=%s", (tipo_proceso_sel,))
                if not _dfp.empty:
                    _pp = _dfp.iloc[0].to_dict()
            except Exception:
                _pp = {}
            _temp_obj = _pp.get("temp_inicial_c") or 80.0
            _tot_h = _pp.get("tiempo_total_horas")
            if _tot_h is None and tiempo_est:
                _tot_h = float(tiempo_est)
            if tipo_proceso_sel == "PRODUCCION_ARE":
                _tot_h = float(st.number_input(
                    "⏱️ Duración estimada de la reacción (horas)", 1.0, 24.0,
                    value=float(_tot_h or 4.0), step=1.0, key="b_reac_h",
                    help="Cada hora de reacción se programa una evaluación interna; más una en decantación."))
                tiempo_est = _tot_h
            _ini = inicio_dt
            _fin_est = (_ini + _dtk.timedelta(hours=float(_tot_h))) if (_ini and _tot_h) else None
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("🌡️ Temp. inicial objetivo", f"{float(_temp_obj):.0f} °C")
            cc2.metric("⏱️ Tiempo total estimado", f"{float(_tot_h):.1f} h" if _tot_h else "—")
            cc3.metric("🏁 Fin estimado", _fin_est.strftime("%H:%M") if _fin_est else "—")

            # Control de capacidad: la carga (MP + insumos) no debe superar el reactor; idea = llenarlo al máximo
            _cap_l = float(fila_bien["capacidad_max_l"] or 0)
            _dens_mp_ref = densidad_de(mp_pre) or 0.92
            _mp_kg_tot = sum(float(k) for _, k in mps_ingresadas) if mps_ingresadas else 0.0
            _ins_kg_tot = sum(float(v) for v in insumos_dict.values()) if insumos_dict else 0.0
            _mp_l = _mp_kg_tot / _dens_mp_ref if _dens_mp_ref else _mp_kg_tot
            _ins_l = 0.0
            for _ik, _iv in (insumos_dict or {}).items():
                try:
                    _di = densidad_insumo(_ik, 1.0) or 1.0
                except Exception:
                    _di = 1.0
                _ins_l += float(_iv) / _di
            _carga_l = _mp_l + _ins_l
            _ocup = (_carga_l / _cap_l * 100) if _cap_l else 0.0
            _cc1, _cc2, _cc3 = st.columns(3)
            _cc1.metric("🛢️ Carga total (MP+insumos)", f"{_carga_l:,.0f} L")
            _cc2.metric("📦 Capacidad reactor", f"{int(_cap_l):,} L")
            _cc3.metric("Ocupación", f"{_ocup:.0f}%")
            if _cap_l and _carga_l > _cap_l * 1.001:
                st.error(f"⛔ La carga ({_carga_l:,.0f} L) supera la capacidad del reactor ({int(_cap_l):,} L). Reducí la cantidad.")
            elif _cap_l and _ocup < 95:
                st.warning(f"⚠️ El reactor no se llena al máximo (ocupación {_ocup:.0f}%). La idea es usarlo a capacidad plena.")
            elif _cap_l:
                st.success(f"✅ Reactor al {_ocup:.0f}% de su capacidad.")

            # Cronograma de etapas con horarios estimados desde el inicio
            try:
                _de = duraciones_etapa[(duraciones_etapa["sector"] == sector) &
                                       (duraciones_etapa["tipo_proceso"] == tipo_proceso_sel)].copy()
            except Exception:
                _de = pd.DataFrame()
            if not _de.empty and _ini is not None:
                _orden = ["ARMADO", "REACCION", "REPOSANDO", "DECANTACION", "EN_TANQUE"]
                _de["_o"] = _de["etapa"].apply(lambda e: _orden.index(e) if e in _orden else 99)
                _rows = []
                _t = _ini
                for _, _r in _de.sort_values("_o").iterrows():
                    _dur = float(_r.get("duracion_target_min") or 0)
                    _fin = _t + _dtk.timedelta(minutes=_dur)
                    _rows.append({"Etapa": _r["etapa"], "Desde": _t.strftime("%H:%M"),
                                  "Hasta": _fin.strftime("%H:%M"), "Duración (min)": int(_dur)})
                    _t = _fin
                st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

            # Prendido de caldera (debe ser >= 1h antes para llegar a 80°C)
            st.markdown("**🔥 Prendido de caldera**")
            _cal_def = (_ini - _dtk.timedelta(hours=1)) if _ini else None
            _kc1, _kc2 = st.columns(2)
            _cal_f = _kc1.date_input("Fecha de prendido",
                                     (_cal_def.date() if _cal_def else date.today()), key="b_cal_f")
            _cal_h = _kc2.time_input("Hora de prendido",
                                     (_cal_def.time() if _cal_def else _dtk.time(6, 0)), key="b_cal_h")
            caldera_dt = _dtk.datetime.combine(_cal_f, _cal_h).replace(tzinfo=(_ini.tzinfo if _ini is not None else TZ_AR))
            if _ini is not None:
                _antic = int((_ini - caldera_dt).total_seconds() / 60)
                if _antic >= 60:
                    st.success(f"✅ Caldera encendida {_antic} min antes del inicio (≥60 para llegar a 80 °C).")
                else:
                    st.warning(f"⚠️ Caldera solo {_antic} min antes; se recomienda ≥60 min para llegar a 80 °C.")

            # Cronograma de evaluaciones internas (preview de lo que se programará al iniciar)
            st.markdown('<div class="section-title">🧪 Esquema de evaluaciones internas</div>', unsafe_allow_html=True)
            _evrows = []
            if _ini is not None:
                if tipo_proceso_sel == "PRODUCCION_ARE":
                    _nh = max(1, int(round(float(_tot_h or 4))))
                    for _kk in range(_nh + 1):
                        _evrows.append({"#": len(_evrows) + 1, "Etapa": "Reacción",
                                        "Hora": (_ini + _dtk.timedelta(hours=_kk)).strftime("%H:%M"),
                                        "Qué se mide": "Acidez · temperatura · fósforo · azufre"})
                    _rep_h = 0.0
                    try:
                        _rep = duraciones_etapa[(duraciones_etapa["sector"] == sector) &
                                                (duraciones_etapa["tipo_proceso"] == tipo_proceso_sel) &
                                                (duraciones_etapa["etapa"] == "REPOSANDO")]
                        _rep_h = float(_rep.iloc[0]["duracion_target_min"]) / 60.0 if not _rep.empty else 0.0
                    except Exception:
                        _rep_h = 0.0
                    _dec_t = _ini + _dtk.timedelta(hours=float(_tot_h or 4) + _rep_h)
                    _evrows.append({"#": len(_evrows) + 1, "Etapa": "Decantación",
                                    "Hora": _dec_t.strftime("%H:%M"), "Qué se mide": "Acidez final · densidad"})
                else:
                    _evrows.append({"#": 1, "Etapa": "Reacción", "Hora": _ini.strftime("%H:%M"),
                                    "Qué se mide": "Medición única al inicio"})
            if _evrows:
                st.dataframe(pd.DataFrame(_evrows), hide_index=True, use_container_width=True)
                st.caption(f"**{len(_evrows)} evaluaciones**: una por hora durante la reacción + una en decantación. "
                           "Se reprograman solas al iniciar según la duración real.")
            else:
                st.caption("Se programa automáticamente al iniciar la reacción.")

            # Verificación rápida: cantidades, insumos y parámetros que se van a usar
            st.markdown('<div class="section-title">📋 Cantidades, insumos y parámetros</div>', unsafe_allow_html=True)
            _vt1, _vt2 = st.columns(2)
            _mp_txt = ", ".join(f"{c} · {k/1000:,.2f} TN" for c, k in mps_ingresadas) if mps_ingresadas else "—"
            _ins_txt = ", ".join(f"{k}: {v:,.0f} kg" for k, v in insumos_dict.items()) if insumos_dict else "—"
            _vt1.markdown(f"**Materia prima:** {_mp_txt}")
            _vt1.markdown(f"**Insumos a usar:** {_ins_txt}")
            if est_are_kg:
                _vt2.markdown(f"**Resultado estimado:** {est_are_kg/1000:,.2f} TN")
            _par_bits = []
            if acidez_oleico_v is not None:
                _par_bits.append(f"acidez **{acidez_oleico_v:.2f}%**")
            if pct_agua_ini_v is not None:
                _par_bits.append(f"agua **{pct_agua_ini_v:.2f}%**")
            if azufre_ppm_v is not None:
                _par_bits.append(f"azufre **{azufre_ppm_v:.0f} ppm**")
            _vt2.markdown("**Parámetros (de la fuente):** " + (" · ".join(_par_bits) if _par_bits else "—"))

            # Checklist obligatorio para iniciar la reacción
            st.markdown('<div class="section-title">✅ Checklist para iniciar la reacción</div>', unsafe_allow_html=True)
            _ck1 = st.checkbox(
                f"MP {_mp_kg_tot/1000:,.1f} TN + insumos {_ins_kg_tot/1000:,.2f} TN · ocupación {_ocup:.0f}% del reactor",
                key="b_ck_mp")
            _ck2 = st.checkbox(
                f"Caldera encendida a las {caldera_dt.strftime('%H:%M')}" + (f" · {_antic} min antes del inicio" if _ini is not None else ""),
                key="b_ck_cal")
            _ck3 = st.checkbox(
                (f"Temp. objetivo {float(_temp_obj):.0f} °C · acidez {acidez_oleico_v:.2f}%" if acidez_oleico_v is not None
                 else f"Temp. objetivo {float(_temp_obj):.0f} °C · parámetros verificados"),
                key="b_ck_temp")
            st.checkbox(f"Corriente confirmada: {corriente_v or '—'}", value=True, disabled=True, key="b_ck_corr")
            _check_ok = bool(_ck1 and _ck2 and _ck3)
            if not _check_ok:
                st.info("Marcá los ítems obligatorios para habilitar el guardado e iniciar la reacción.")

        _btn_label = "🚀 Guardar planificación e iniciar reacción" if (es_reactor and not es_recup) else "✅ Guardar carga"
        submit_b = st.button(_btn_label, type="primary", use_container_width=True, key="b_submit",
                             disabled=((es_reactor and not es_recup and not _check_ok)
                                       or bool(st.session_state.get("mp_corr_conflict"))))

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
            if st.session_state.get("mp_corr_conflict"):
                errs.append("La materia prima de portería y de tanque tienen distinta corriente: usá una sola corriente.")
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
                            # MP -> fact_batch_insumo (idempotente): genera el ticket de lab de la MP y,
                            # si la fuente es un tanque, descuenta stock. Aislado en savepoint para que
                            # cualquier error NO afecte el guardado del batch.
                            try:
                                cur.execute("SAVEPOINT sp_mpins")
                                cur.execute("SELECT 1 FROM fact_batch_insumo WHERE id_batch=%s AND rol='MP' LIMIT 1", (id_b,))
                                if not cur.fetchone():
                                    for _ix, (_cmp, _kmp) in enumerate(mps_ingresadas):
                                        cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s", (_cmp,))
                                        _rp = cur.fetchone()
                                        if not _rp:
                                            continue
                                        _pidmp = _rp[0]
                                        _ports = mp_fuentes.get(_ix)
                                        if isinstance(_ports, dict):
                                            _ports = [_ports]
                                        if not _ports:
                                            _ports = [{"fuente": "TICKET", "ticket": ticket_porteria_v, "id_tanque": None, "kg": _kmp}]
                                        for _po in _ports:
                                            _pk = float(_po.get("kg") or 0)
                                            if _po.get("fuente") == "TANQUE" and _po.get("id_tanque"):
                                                cur.execute(
                                                    "INSERT INTO fact_batch_insumo (id_batch,rol,id_producto,cantidad,fuente,id_tanque,id_usuario) "
                                                    "VALUES (%s,'MP',%s,%s,'TANQUE',%s,%s)",
                                                    (id_b, _pidmp, _pk, int(_po["id_tanque"]), int(USR["id_usuario"])))
                                            else:
                                                _tkv = (_po.get("ticket") or ticket_porteria_v or "s/ticket")
                                                cur.execute(
                                                    "INSERT INTO fact_batch_insumo (id_batch,rol,id_producto,cantidad,fuente,ticket_porteria,id_usuario) "
                                                    "VALUES (%s,'MP',%s,%s,'TICKET',%s,%s)",
                                                    (id_b, _pidmp, _pk, str(_tkv)[:120], int(USR["id_usuario"])))
                                cur.execute("RELEASE SAVEPOINT sp_mpins")
                            except Exception as _e_mp:
                                try:
                                    cur.execute("ROLLBACK TO SAVEPOINT sp_mpins")
                                except Exception:
                                    pass
                                st.warning(f"La MP quedó registrada en el batch, pero no se generó el detalle de fuente/ticket de lab: {_e_mp}")
                            # Checklist + prendido de caldera (dispara estado->REACCION e inicia la reaccion).
                            if es_reactor and not es_recup:
                                try:
                                    cur.execute("SAVEPOINT sp_chk")
                                    if caldera_dt is not None:
                                        cur.execute("UPDATE fact_batch_proceso SET caldera_encendida_ts=%s WHERE id_batch=%s",
                                                    (caldera_dt.isoformat(), id_b))
                                    cur.execute(
                                        "INSERT INTO fact_batch_checklist "
                                        "(id_batch, mp_ok, insumos_ok, temperatura_inicial_ok, parametros_ok, corriente_ok, caldera_encendida_ok, id_usuario) "
                                        "VALUES (%s,true,true,true,true,true,true,%s) ON CONFLICT (id_batch) DO NOTHING",
                                        (id_b, int(USR["id_usuario"])))
                                    cur.execute("RELEASE SAVEPOINT sp_chk")
                                except Exception as _e_ck:
                                    try:
                                        cur.execute("ROLLBACK TO SAVEPOINT sp_chk")
                                    except Exception:
                                        pass
                                    st.warning(f"No se pudo registrar checklist/caldera: {_e_ck}")
                            # Primer evento de etapa (abre el ARMADO). NOT EXISTS evita duplicar en re-upsert.
                            if es_reactor and etapa_sel:
                                cur.execute("""
                                    INSERT INTO fact_etapa_evento (id_batch, etapa, inicio_ts, id_usuario)
                                    SELECT %s, %s, COALESCE(%s, NOW()), %s
                                    WHERE NOT EXISTS (SELECT 1 FROM fact_etapa_evento WHERE id_batch=%s AND etapa=%s)
                                """, (id_b, etapa_sel,
                                      inicio_dt.isoformat() if inicio_dt else None,
                                      int(USR["id_usuario"]), id_b, etapa_sel))
                                # Guardar la planificación = arrancar la reacción: ARMADO -> REACCION
                                if sector == "REACTORES" and not es_recup:
                                    cur.execute("UPDATE fact_etapa_evento SET fin_ts=NOW() "
                                                "WHERE id_batch=%s AND etapa='ARMADO' AND fin_ts IS NULL", (id_b,))
                                    cur.execute("INSERT INTO fact_etapa_evento (id_batch, etapa, inicio_ts, id_usuario) "
                                                "SELECT %s,'REACCION',NOW(),%s "
                                                "WHERE NOT EXISTS (SELECT 1 FROM fact_etapa_evento WHERE id_batch=%s AND etapa='REACCION')",
                                                (id_b, int(USR["id_usuario"]), id_b))
                                    cur.execute("UPDATE fact_batch_proceso SET etapa_actual='REACCION' "
                                                "WHERE id_batch=%s AND etapa_actual='ARMADO'", (id_b,))
                        audit.insert("fact_batch_proceso", id_b,
                                     {"sector": sector, "proceso": tipo_proceso_sel,
                                      "producto": p_obt, "kg": kg_obt, "fuera_rango": bool(fuera_rango)})
                    st.success(f"✅ Carga #{id_b} guardada. Ticket: {identificador or '-'}")
                    if es_reactor and not es_recup:
                        try:
                            cat.clear()
                            _evdf = cat(
                                "SELECT secuencia AS \"#\", to_char(programado_ts,'DD/MM HH24:MI') AS \"Hora\", "
                                "estado AS \"Estado\" FROM produccion.fact_eval_programada "
                                "WHERE id_batch=%s ORDER BY secuencia", (id_b,))
                        except Exception:
                            _evdf = pd.DataFrame()
                        with st.expander("🗓️ Cronograma de la reacción — monitoreo", expanded=True):
                            if _evdf is not None and not _evdf.empty:
                                st.markdown("**Evaluaciones internas programadas**")
                                st.dataframe(_evdf, hide_index=True, use_container_width=True)
                            st.caption("Avanzá y monitoreá las etapas desde **Avanzar etapa**. "
                                       "Cuando la acidez medida llegue a ≤10, la reacción pasa a la siguiente etapa "
                                       "y se genera el ticket de producto final para evaluar.")
                    cat.clear()
                except Exception as e:
                    st.exception(e)

    # ===========================================================================
    # SUB-TAB: AVANZAR ETAPA — vista de tarjetas tipo "panel de planta"
    # ===========================================================================
    with sub_edit:
        _STAGE_LBL = {"ARMADO": "Armado", "CARGA": "Carga", "REACCION": "Reacción",
                      "CALENTAMIENTO": "Calentamiento", "REPOSANDO": "Reposo",
                      "DECANTACION": "Decantación", "EN_TANQUE": "Acopio final"}
        _STAGE_EMOJI = {"ARMADO": "🧱", "CARGA": "📥", "REACCION": "🔥",
                        "CALENTAMIENTO": "🌡️", "REPOSANDO": "⏸️",
                        "DECANTACION": "💧", "EN_TANQUE": "🪣"}
        _EST = {"CARGA": ("#ece9e3", "#5a564f", "📝", "En carga"),
                "REACCION": ("#fde2c8", "#8a4b12", "🔥", "Reacción"),
                "REPOSO": ("#d8e8f7", "#1d5a91", "⏸️", "Reposo"),
                "DECANTACION": ("#e3dbf3", "#5a3b9a", "💧", "Decantación"),
                "FINALIZADO": ("#d6efd9", "#256b31", "✅", "Finalizada"),
                "FRENADA": ("#fee2e2", "#9a2727", "⛔", "Frenada"),
                "ANULADA": ("#eeeeee", "#888888", "🚫", "Anulada")}

        if "e_open_detail" not in st.session_state:
            st.session_state["e_open_detail"] = None

        df_open = cat("""
            SELECT b.id_batch, b.identificador_unidad AS ticket, b.fecha, b.sector,
                   b.tipo_proceso, b.etapa_actual, b.inicio_ts, b.estado,
                   b.esperando_validacion_lab, b.validado_lab,
                   b.ticket_producto_final, b.ticket_validacion_lab,
                   pb.codigo_producto AS buscado, b.calidad_buscada,
                   pi.codigo_producto AS mp, b.kg_inicial,
                   bu.nombre_ui AS reactor, b.corriente,
                   (SELECT (ei.mediciones->>'acidez')::numeric FROM produccion.fact_evaluacion_interna ei
                     WHERE ei.id_batch=b.id_batch AND NOT ei.anulado AND ei.mediciones ? 'acidez'
                     ORDER BY ei.ts DESC LIMIT 1) AS acidez_ult,
                   (SELECT count(*) FROM produccion.fact_evaluacion_interna ei
                     WHERE ei.id_batch=b.id_batch AND NOT ei.anulado) AS n_eval
              FROM fact_batch_proceso b
              LEFT JOIN dim_producto pi ON pi.id_producto = b.id_producto_inicial
              LEFT JOIN dim_producto pb ON pb.id_producto = b.id_producto_buscado
              LEFT JOIN dim_bien_uso bu ON bu.id_bien_uso = b.id_bien_uso
             WHERE NOT b.anulado AND b.sector IN ('REACTORES','BACHAS')
               AND COALESCE(b.etapa_actual,'') <> 'EN_TANQUE'
             ORDER BY b.inicio_ts DESC NULLS LAST, b.creado_en DESC
             LIMIT 60
        """)

        st.markdown('<div class="section-title" style="font-size:1.3rem">📊 Dashboard de reacciones</div>', unsafe_allow_html=True)

        if df_open.empty:
            st.success("✅ No hay reacciones abiertas. Las nuevas se arman en **Nueva carga** y las completas se cierran en **Acopio final**.")
        else:
            # ---- KPIs por estado ----
            _by = df_open["estado"].fillna("CARGA").value_counts().to_dict()
            _esp = int(df_open["esperando_validacion_lab"].fillna(False).sum())
            _kp = "".join(
                f"<div class='kpi'><div class='l'>{_EST.get(_e,('','','','?'))[3]}</div>"
                f"<div class='v'>{_n}</div></div>"
                for _e, _n in _by.items())
            _kp += (f"<div class='kpi'><div class='l'>Esperando lab</div>"
                    f"<div class='v {'bad' if _esp else 'ok'}'>{_esp}</div></div>")
            st.markdown(f"<div class='kpi-grid'>{_kp}</div>", unsafe_allow_html=True)
            st.caption(f"**{len(df_open)} reacción(es) abiertas.** ▶ avanza de etapa · **Abrir** ve evaluaciones, insumos y tickets.")

            _ids = [int(x) for x in df_open["id_batch"].tolist()]
            _ids_str = ",".join(str(x) for x in _ids) if _ids else "NULL"
            df_evts_open = cat(f"""
                SELECT id_batch, etapa, inicio_ts, fin_ts, duracion_real_min
                FROM produccion.fact_etapa_evento
                WHERE id_batch IN ({_ids_str})
                ORDER BY id_batch, inicio_ts
            """) if _ids else pd.DataFrame()

            def _elapsed_min(row_batch, df_evts):
                ev = df_evts[(df_evts["id_batch"] == int(row_batch["id_batch"])) &
                             (df_evts["etapa"] == row_batch["etapa_actual"]) &
                             (df_evts["fin_ts"].isna())]
                if ev.empty or pd.isna(ev.iloc[-1]["inicio_ts"]):
                    return None
                _ini = pd.to_datetime(ev.iloc[-1]["inicio_ts"], utc=True)
                _now = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None else pd.Timestamp.utcnow()
                try:
                    return max(0, int((_now - _ini).total_seconds() / 60))
                except Exception:
                    return None

            def _target_min(sector, tipo_proceso, etapa):
                _t = duraciones_etapa[(duraciones_etapa["sector"] == sector) &
                                      (duraciones_etapa["tipo_proceso"] == tipo_proceso) &
                                      (duraciones_etapa["etapa"] == etapa)]
                return int(_t.iloc[0]["duracion_target_min"]) if not _t.empty else None

            def _fmt_hm(mins):
                if mins is None:
                    return "—"
                return f"{int(mins)//60}h {int(mins)%60:02d}m"

            def _render_stepper(etapas_codigos, idx_actual):
                segs = []
                labels = []
                for j, c in enumerate(etapas_codigos):
                    if j < idx_actual:
                        _bg = "#10b981"; _tc = "#475569"
                    elif j == idx_actual:
                        _bg = "#4f46e5"; _tc = "#4f46e5"
                    else:
                        _bg = "#e2e8f0"; _tc = "#94a3b8"
                    segs.append(f'<div style="flex:1;height:6px;background:{_bg};border-radius:3px;margin-right:2px"></div>')
                    _wt = "700" if j == idx_actual else "500"
                    labels.append(f'<div style="flex:1;font-size:10px;color:{_tc};margin-right:2px;text-align:center;font-weight:{_wt}">{_STAGE_LBL.get(c,c)[:8]}</div>')
                return ('<div style="display:flex;margin-top:10px">' + "".join(segs) + "</div>"
                        '<div style="display:flex;margin-top:3px">' + "".join(labels) + "</div>")

            ncols = 3
            for row_start in range(0, len(df_open), ncols):
                cols = st.columns(ncols, gap="small")
                for j in range(ncols):
                    idx = row_start + j
                    if idx >= len(df_open):
                        break
                    r = df_open.iloc[idx]
                    et_act = r["etapa_actual"] or "ARMADO"
                    _est = r["estado"] or "CARGA"
                    _ebg, _etc, _eem, _elbl = _EST.get(_est, ("#ece9e3", "#5a564f", "❔", _est))
                    _et_proc = etapas_de_proceso(proceso_key_de(r["sector"], r["tipo_proceso"]))
                    etapas_codigos = _et_proc["etapa"].tolist() if not _et_proc.empty else [et_act]
                    idx_actual = etapas_codigos.index(et_act) if et_act in etapas_codigos else 0
                    idx_next = min(idx_actual + 1, len(etapas_codigos) - 1)
                    es_ultima = (idx_actual >= len(etapas_codigos) - 1)
                    nueva_et_def = etapas_codigos[idx_next] if etapas_codigos else et_act
                    elapsed = _elapsed_min(r, df_evts_open)
                    target = _target_min(r["sector"], r["tipo_proceso"], et_act)
                    emoji = _STAGE_EMOJI.get(et_act, "❔")
                    et_lbl = _STAGE_LBL.get(et_act, et_act)
                    proc_short = (r["tipo_proceso"] or "").replace("PRODUCCION_ARE", "ARE").replace("DESGOMADO_ACUOSO", "DESGOMADO")
                    mp_buscado = f"{r['mp'] or '—'} → {r['buscado'] or '—'}"
                    _ac = r.get("acidez_ult")
                    _ac_chip = (f"<span style='background:#eef2ff;color:#3730a3;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700'>acidez {float(_ac):.1f}</span>"
                                if pd.notna(_ac) else "")
                    _tpf_chip = (f"<span style='background:#fef3c7;color:#92400e;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700'>🎫 {r['ticket_producto_final']}</span>"
                                 if r.get("ticket_producto_final") else "")
                    with cols[j]:
                        st.markdown(
                            f"""
<div style="background:#fff;border:1px solid #e6e8f0;border-left:6px solid {_etc};
            border-radius:14px;padding:14px 16px;margin-bottom:6px;min-height:170px;box-shadow:0 1px 3px rgba(16,24,40,.05)">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div style="font-size:11px;color:#94a3b8">#{int(r['id_batch'])} · {r['ticket'] or '—'} · {proc_short}</div>
      <div style="font-size:17px;font-weight:700;color:#0f172a;margin-top:2px">{emoji} {et_lbl}</div>
      <div style="font-size:11px;color:#64748b;margin-top:2px">{r['reactor'] or '—'} · {mp_buscado}</div>
    </div>
    <div style="text-align:right">
      <span style="background:{_ebg};color:{_etc};border-radius:999px;padding:3px 10px;font-size:11px;font-weight:700">{_eem} {_elbl}</span>
      <div style="font-size:18px;font-weight:800;color:#0f172a;margin-top:6px">{_fmt_hm(elapsed)}</div>
      <div style="font-size:10px;color:#94a3b8">target {_fmt_hm(target)}</div>
    </div>
  </div>
  <div style="margin-top:8px">{_ac_chip} {_tpf_chip}</div>
  {_render_stepper(etapas_codigos, idx_actual)}
</div>
""",
                            unsafe_allow_html=True,
                        )
                        bc1, bc2 = st.columns([1.4, 1])
                        if es_ultima:
                            bc1.button("🏁 Ir a Acopio final", key=f"e_acopio_{int(r['id_batch'])}",
                                       use_container_width=True, disabled=True,
                                       help="Última etapa. Cerrala desde 'Acopio final'.")
                        else:
                            if bc1.button(f"▶ Avanzar a {_STAGE_LBL.get(nueva_et_def, nueva_et_def)}",
                                          key=f"e_adv_{int(r['id_batch'])}", use_container_width=True, type="primary"):
                                _reposo_min = int((K("reposo_min_horas_reactor", 4) or 4) * 60)
                                if et_act == "REPOSANDO" and elapsed is not None and elapsed < _reposo_min:
                                    st.error(f"Reposo mínimo {_reposo_min//60} h. Llevás {_fmt_hm(elapsed)}; abrí el detalle para forzar.")
                                else:
                                    try:
                                        with conectar(USR["id_usuario"]) as (conn, audit):
                                            with conn.cursor() as cur:
                                                cur.execute("""
                                                    UPDATE produccion.fact_etapa_evento
                                                       SET fin_ts = NOW(), duracion_real_min = COALESCE(%s, duracion_real_min)
                                                     WHERE id_batch=%s AND fin_ts IS NULL
                                                """, (int(elapsed) if elapsed else None, int(r['id_batch'])))
                                                cur.execute("""
                                                    INSERT INTO produccion.fact_etapa_evento (id_batch, etapa, inicio_ts, id_usuario)
                                                    VALUES (%s, %s, NOW(), %s)
                                                """, (int(r['id_batch']), nueva_et_def, int(USR["id_usuario"])))
                                                cur.execute("UPDATE produccion.fact_batch_proceso SET etapa_actual=%s WHERE id_batch=%s",
                                                            (nueva_et_def, int(r['id_batch'])))
                                            audit.log("U", "fact_batch_proceso", int(r['id_batch']),
                                                      {"avance_rapido": et_act, "duracion_min": elapsed, "nueva_etapa": nueva_et_def})
                                        st.success(f"#{int(r['id_batch'])} · pasó a {_STAGE_LBL.get(nueva_et_def, nueva_et_def)}.")
                                        cat.clear(); st.rerun()
                                    except Exception as e:
                                        st.exception(e)
                        if bc2.button("🔍 Abrir", key=f"e_det_{int(r['id_batch'])}", use_container_width=True):
                            st.session_state["e_open_detail"] = int(r['id_batch'])
                            st.rerun()

            # ---------- Detalle de una reacción ----------
            _id_det = st.session_state.get("e_open_detail")
            if _id_det:
                _row_det = df_open[df_open["id_batch"] == _id_det]
                if not _row_det.empty:
                    r = _row_det.iloc[0]
                    id_batch_edit = int(r["id_batch"])
                    _est = r["estado"] or "CARGA"
                    _ebg, _etc, _eem, _elbl = _EST.get(_est, ("#ece9e3", "#5a564f", "❔", _est))
                    st.divider()
                    _tc1, _tc2 = st.columns([4, 1])
                    _tc1.markdown(
                        f"### 🔬 Reacción #{id_batch_edit} · {r['ticket'] or '—'} "
                        f"<span style='background:{_ebg};color:{_etc};border-radius:999px;padding:3px 12px;font-size:13px;font-weight:700'>{_eem} {_elbl}</span>",
                        unsafe_allow_html=True)
                    if _tc2.button("✖ Cerrar", key="e_close_det", use_container_width=True):
                        st.session_state["e_open_detail"] = None
                        st.rerun()
                    _di1, _di2, _di3, _di4 = st.columns(4)
                    _di1.metric("Reactor", r["reactor"] or "—")
                    _di2.metric("MP → buscado", f"{r['mp'] or '—'} → {r['buscado'] or '—'}")
                    _di3.metric("Corriente", r["corriente"] or "—")
                    _di4.metric("Acidez última", f"{float(r['acidez_ult']):.1f}" if pd.notna(r.get("acidez_ult")) else "—")
                    if r.get("ticket_producto_final"):
                        st.warning(f"🎫 **Ticket de producto final:** {r['ticket_producto_final']} — a evaluar en laboratorio."
                                   + (f" · validación interna con ticket MP **{r['ticket_validacion_lab']}**" if r.get("ticket_validacion_lab") else ""))

                    dtabs = st.tabs(["🔄 Etapas", "🧪 Evaluaciones internas", "📦 Insumos / MP", "🎫 Tickets de lab"])

                    # --- Etapas: historial + avance manual ---
                    with dtabs[0]:
                        df_eve = cat("""
                            SELECT e.etapa, e.inicio_ts, e.fin_ts, e.duracion_real_min, e.observaciones,
                                   u.nombre AS usuario, d.duracion_target_min
                            FROM produccion.fact_etapa_evento e
                            JOIN produccion.dim_usuario u ON u.id_usuario = e.id_usuario
                            LEFT JOIN produccion.dic_proceso_etapa d
                              ON d.proceso_key=%s AND d.etapa=e.etapa
                            WHERE e.id_batch = %s ORDER BY e.inicio_ts
                        """, (proceso_key_de(r["sector"], r["tipo_proceso"]), id_batch_edit))
                        if not df_eve.empty:
                            df_eve = df_eve.copy()
                            def _dur(x):
                                if pd.notna(x.get("duracion_real_min")):
                                    return float(x["duracion_real_min"])
                                if pd.notna(x["inicio_ts"]):
                                    fin = x["fin_ts"] if pd.notna(x["fin_ts"]) else pd.Timestamp.now(tz="UTC")
                                    return round((fin - x["inicio_ts"]).total_seconds() / 60, 1)
                                return None
                            df_eve["min_real"] = df_eve.apply(_dur, axis=1)
                            df_eve["estado"] = df_eve["fin_ts"].apply(lambda v: "✅ cerrada" if pd.notna(v) else "🟢 abierta")
                            st.dataframe(df_eve[["etapa", "estado", "min_real", "duracion_target_min", "inicio_ts", "fin_ts", "usuario"]],
                                         use_container_width=True, hide_index=True)
                        _et_proc_av = etapas_de_proceso(proceso_key_de(r["sector"], r["tipo_proceso"]))
                        etapas_codigos = _et_proc_av["etapa"].tolist()
                        etapa_actual_cod = r["etapa_actual"]
                        idx_actual = etapas_codigos.index(etapa_actual_cod) if etapa_actual_cod in etapas_codigos else 0
                        idx_nueva = min(idx_actual + 1, len(etapas_codigos) - 1) if etapas_codigos else 0
                        tgt_min = _target_min(r["sector"], r["tipo_proceso"], etapa_actual_cod)
                        elapsed_now = _elapsed_min(r, df_evts_open)
                        _def_h = (elapsed_now // 60) if elapsed_now is not None else ((tgt_min or 0) // 60)
                        _def_m = ((elapsed_now % 60) if elapsed_now is not None else ((tgt_min or 0) % 60)) // 5 * 5
                        st.caption(f"Etapa actual: {_STAGE_EMOJI.get(etapa_actual_cod,'')} {_STAGE_LBL.get(etapa_actual_cod, etapa_actual_cod)} · transcurrido {_fmt_hm(elapsed_now)} · target {_fmt_hm(tgt_min)}")
                        cE1, cE2, cE3 = st.columns([1, 1, 1.4])
                        dur_h = cE1.number_input("Duró (h)", 0, 1000, value=int(_def_h), step=1, key=f"e_dur_h_{id_batch_edit}")
                        dur_m = cE2.number_input("y min", 0, 59, value=int(_def_m), step=5, key=f"e_dur_m_{id_batch_edit}")
                        dur_min_in = int(dur_h) * 60 + int(dur_m)
                        nueva_etapa = cE3.selectbox("Pasar a", etapas_codigos, index=idx_nueva,
                                                    format_func=lambda c: _STAGE_LBL.get(c, c), key=f"e_etapa_{id_batch_edit}")
                        temp_et = st.number_input("Temperatura al cerrar la etapa (°C, opcional)", 0.0, 300.0, step=1.0, value=0.0, key=f"e_temp_{id_batch_edit}")
                        obs_etapa = st.text_input("Observaciones (opcional)", max_chars=200, key=f"e_obs_{id_batch_edit}")
                        _reposo_min = int((K("reposo_min_horas_reactor", 4) or 4) * 60)
                        if etapa_actual_cod == "REPOSANDO" and dur_min_in and dur_min_in < _reposo_min:
                            st.error(f"⚠️ Reposo mínimo {_reposo_min//60} h. Llevás {dur_min_in} min.")
                        if st.button(f"💾 Cerrar {_STAGE_LBL.get(etapa_actual_cod, etapa_actual_cod)} → {_STAGE_LBL.get(nueva_etapa, nueva_etapa)}",
                                     type="primary", use_container_width=True, key=f"e_save_{id_batch_edit}"):
                            if etapa_actual_cod == "REPOSANDO" and dur_min_in and dur_min_in < _reposo_min:
                                st.error(f"No se puede cerrar el reposo con menos de {_reposo_min//60} h.")
                            else:
                                try:
                                    with conectar(USR["id_usuario"]) as (conn, audit):
                                        with conn.cursor() as cur:
                                            cur.execute("""
                                                UPDATE produccion.fact_etapa_evento
                                                   SET fin_ts = NOW(), duracion_real_min = COALESCE(%s, duracion_real_min),
                                                       observaciones = COALESCE(NULLIF(%s,''), observaciones)
                                                 WHERE id_batch=%s AND fin_ts IS NULL
                                            """, (int(dur_min_in) if dur_min_in else None, obs_etapa, id_batch_edit))
                                            cur.execute("""
                                                INSERT INTO produccion.fact_etapa_evento (id_batch, etapa, inicio_ts, id_usuario)
                                                VALUES (%s, %s, NOW(), %s)
                                            """, (id_batch_edit, nueva_etapa, int(USR["id_usuario"])))
                                            _tp = {f"temp_{etapa_actual_cod.lower()}_c": float(temp_et)} if (temp_et and temp_et > 0) else {}
                                            cur.execute("UPDATE produccion.fact_batch_proceso SET etapa_actual=%s, "
                                                        "parametros_proceso = COALESCE(parametros_proceso,'{}'::jsonb) || %s::jsonb WHERE id_batch=%s",
                                                        (nueva_etapa, json.dumps(_tp), id_batch_edit))
                                        audit.log("U", "fact_batch_proceso", id_batch_edit,
                                                  {"cerro_etapa": etapa_actual_cod, "duracion_min": int(dur_min_in) if dur_min_in else None, "nueva_etapa": nueva_etapa})
                                    st.success(f"#{id_batch_edit} · pasó a {_STAGE_LBL.get(nueva_etapa, nueva_etapa)}.")
                                    st.session_state["e_open_detail"] = None
                                    cat.clear(); st.rerun()
                                except Exception as e:
                                    st.exception(e)

                    # --- Evaluaciones internas ---
                    with dtabs[1]:
                        _ev = cat("""
                            SELECT to_char(ei.ts,'DD/MM HH24:MI') AS hora, ei.etapa,
                                   (ei.mediciones->>'acidez')::numeric AS acidez,
                                   (ei.mediciones->>'temperatura')::numeric AS temperatura,
                                   (ei.mediciones->>'fosforo')::numeric AS fosforo,
                                   (ei.mediciones->>'azufre')::numeric AS azufre,
                                   ei.observaciones, u.nombre AS usuario
                            FROM produccion.fact_evaluacion_interna ei
                            LEFT JOIN produccion.dim_usuario u ON u.id_usuario = ei.id_usuario
                            WHERE ei.id_batch=%s AND NOT ei.anulado ORDER BY ei.ts
                        """, (id_batch_edit,))
                        if _ev.empty:
                            st.info("Todavía no hay evaluaciones internas. Se cargan en la pestaña **Evaluación interna**.")
                        else:
                            st.dataframe(_ev, use_container_width=True, hide_index=True)
                            if _ev["acidez"].notna().any():
                                st.caption("Caída de acidez en el tiempo")
                                st.line_chart(_ev.dropna(subset=["acidez"]).set_index("hora")["acidez"])

                    # --- Insumos / MP cargados con su ticket ---
                    with dtabs[2]:
                        _ins = cat("""
                            SELECT bi.rol,
                                   COALESCE(bi.codigo_insumo, p.codigo_producto) AS item,
                                   bi.cantidad, bi.unidad, bi.fuente,
                                   COALESCE(bi.ticket_porteria, 'TK '||bi.id_tanque::text) AS origen,
                                   bi.ticket_lab
                            FROM produccion.fact_batch_insumo bi
                            LEFT JOIN produccion.dim_producto p ON p.id_producto = bi.id_producto
                            WHERE bi.id_batch=%s AND NOT bi.anulado ORDER BY bi.id_batch_insumo
                        """, (id_batch_edit,))
                        if _ins.empty:
                            st.info("Sin insumos/MP registrados en detalle para esta reacción.")
                        else:
                            st.dataframe(_ins, use_container_width=True, hide_index=True)

                    # --- Tickets de laboratorio generados ---
                    with dtabs[3]:
                        _tk = cat("""
                            SELECT t.ticket_lab, t.rol,
                                   COALESCE(t.codigo_insumo, p.codigo_producto) AS producto,
                                   t.fuente, t.estado, to_char(t.creado_en,'DD/MM HH24:MI') AS generado,
                                   to_char(t.evaluado_en,'DD/MM HH24:MI') AS evaluado
                            FROM produccion.fact_ticket_lab t
                            LEFT JOIN produccion.dim_producto p ON p.id_producto = t.id_producto
                            WHERE t.id_batch=%s ORDER BY t.id_ticket
                        """, (id_batch_edit,))
                        if _tk.empty:
                            st.info("Sin tickets de laboratorio generados todavía.")
                        else:
                            st.dataframe(_tk, use_container_width=True, hide_index=True)
                            st.caption("Los tickets PENDIENTE se evalúan en laboratorio. El ticket FINAL aparece cuando la acidez llega a ≤10.")

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
            _cands_pf = set(c for c in (_finales or []) if isinstance(c, str) and c)
            if isinstance(rpf["buscado"], str) and rpf["buscado"]:
                _cands_pf.add(rpf["buscado"])
            _opts_pf = sorted(_cands_pf)
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
            if "GLICERINA_RECUP" in _tipos_pf: _sug_pf += ["GLICERINA-PURA", "GLICERINA-FE"]
            if "AGUA_PROCESO" in _tipos_pf: _sug_pf += ["AGUA-PROC"]
            _opt_dec_pf = [c for c in dict.fromkeys(_sug_pf) if c in productos["codigo_producto"].tolist()]
            # mapa codigo_producto -> tipo_salida (para etiquetar el movimiento)
            _tipo_por_cod = {row["codigo_producto"]: row["tipo_salida"]
                             for _, row in _dec_pf.iterrows() if pd.notna(row["codigo_producto"])}
            # muestras de glicerina evaluadas en lab (para la glicerina recuperada)
            _gli_lab = ultimas_muestras_glicerina(8) if callable(ultimas_muestras_glicerina) else pd.DataFrame()
            st.caption("La decantación genera **tickets de movimiento de stock** (entrada de subproducto al tanque destino). "
                       "Para la **glicerina recuperada**, elegí la muestra de laboratorio que la representa.")
            # estimación de glicerina recuperada calculada en la planificación (default editable)
            _gli_recup_est = 0
            try:
                _pp = cat("SELECT parametros_proceso FROM produccion.fact_batch_proceso WHERE id_batch=%s", (id_pf,))
                if not _pp.empty and _pp.iloc[0]["parametros_proceso"]:
                    _ppd = _pp.iloc[0]["parametros_proceso"]
                    if isinstance(_ppd, str):
                        _ppd = json.loads(_ppd)
                    _gli_recup_est = int(round(float(_ppd.get("glicerina_recup_kg") or 0)))
            except Exception:
                _gli_recup_est = 0
            if _gli_recup_est:
                st.caption(f"💧 Glicerina recuperada estimada por fórmula: **{_gli_recup_est:,} kg** "
                           "(se pre-carga; ajustá con lo medido).")
            if _opt_dec_pf:
                n_sal_pf = st.number_input("Salidas a registrar", 0, 5, value=0, key="pf_ndec")
                sal_pf = []
                for i in range(int(n_sal_pf)):
                    d1, d2, d3 = st.columns(3)
                    cd = d1.selectbox(f"Producto #{i+1}", _opt_dec_pf, key=f"pf_dprod_{i}")
                    _kg_def = _gli_recup_est if ("GLICERINA" in str(cd).upper() and _gli_recup_est) else 0
                    kgd = d2.number_input(f"kg #{i+1}", min_value=0, max_value=200000, step=50, value=_kg_def, key=f"pf_dkg_{i}")
                    destd = d3.text_input(f"Destino (tanque) #{i+1}", max_chars=40, key=f"pf_ddst_{i}")
                    _gli_pct = None; _gli_tk = None
                    _es_gli = "GLICERINA" in str(cd).upper()
                    if _es_gli and _gli_lab is not None and not _gli_lab.empty:
                        _go = ["(sin muestra)"] + _gli_lab.apply(
                            lambda r: f"ticket {r['ticket']} · glicerol {float(r['gli_glicerol'])*100:.2f}%", axis=1).tolist()
                        _gs = st.selectbox(f"Muestra lab glicerina recuperada #{i+1}", _go, key=f"pf_dgli_{i}")
                        if _gs != "(sin muestra)":
                            _grow = _gli_lab.iloc[_go.index(_gs) - 1]
                            _gli_pct = float(_grow["gli_glicerol"]) * 100
                            _gli_tk = str(_grow["ticket"])
                    if kgd > 0:
                        sal_pf.append((cd, float(kgd), destd or None, _tipo_por_cod.get(cd), _gli_pct, _gli_tk))
                if sal_pf and st.button("💾 Guardar decantación", key="pf_dsave", use_container_width=True):
                    try:
                        with conectar(USR["id_usuario"]) as (conn, audit):
                            with conn.cursor() as cur:
                                for cd, kgd, destd, tsal, glipct, glitk in sal_pf:
                                    cur.execute("SELECT id_producto, densidad_g_ml FROM dim_producto WHERE codigo_producto=%s", (cd,))
                                    _r = cur.fetchone()
                                    if not _r:
                                        continue
                                    _ltsd = (kgd / float(_r[1])) if _r[1] else None
                                    cur.execute("""
                                        INSERT INTO fact_salida_decantacion
                                        (id_batch, id_producto, kg, lts, glicerol_pct, destino_tanque,
                                         tipo_salida, ticket_lab, id_usuario)
                                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                    """, (id_pf, _r[0], kgd, _ltsd, glipct, destd, tsal, glitk, int(USR["id_usuario"])))
                            audit.log("I", "fact_salida_decantacion", id_pf, {"n": len(sal_pf)})
                        st.success("Decantación registrada · se generaron los tickets de movimiento de stock.")
                    except Exception as e:
                        st.exception(e)
            else:
                st.caption("Este proceso no tiene decantaciones configuradas.")

    # ---------- SUB-TAB: CARGAR MUESTRA INTERMEDIA ----------

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
              (b.insumos->>'FUEL_OIL')::numeric    AS fuel_real_kg
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
              (b.insumos->>'FUEL_OIL')::numeric    AS fuel_real_kg
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
