# -*- coding: utf-8 -*-
"""Indicadores del área Producción (Fase 1) — los 5 que pidió dirección:

    1. Acopio disponible en tanques, sólidos y piletas
    2. Descargas pendientes / en proceso (no sólo los líquidos)
    3. Personal en planta
    4. Sectores activos
    5. Tickets pendientes de análisis

Todo sale de UNA vista (produccion.v_kpi_area_produccion) para que no haya dos
versiones del mismo número, y se dibuja dentro de un st.fragment: marcar
presencia o refrescar redibuja sólo este bloque, no la página.

Lo que todavía no tiene dato real se dice con esas palabras ("sin dato",
"logins") — nunca un número inventado. A validar con Eugenia, Pablo y Fernando
(pedido explícito del Excel).
"""

import json

import pandas as pd
import streamlit as st

from . import state as _st

_TTL = 60  # s · los KPIs se recalculan como mucho cada minuto por proceso

try:
    _FRAGMENT = st.fragment
except AttributeError:            # Streamlit viejo: decorador nulo, funciona igual (con rerun normal)
    def _FRAGMENT(f=None, **kw):
        return f if f else (lambda g: g)


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer_kpis(_cf):
    """Una fila con todos los indicadores. None si la base no responde."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT * FROM produccion.v_kpi_area_produccion", conn)
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        pc = row.get("camiones_por_corriente")
        if isinstance(pc, str):
            try:
                pc = json.loads(pc)
            except Exception:
                pc = {}
        row["camiones_por_corriente"] = pc or {}
        return row
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer_capacidad(_cf):
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                "SELECT producto, tanques, cap_kl, act_kl, libre_kl, pct_ocupado, incluye_piletas "
                "FROM produccion.v_capacidad_ocupada_producto ORDER BY cap_kl DESC", conn)
    except Exception:
        return None


def _presencia_abierta(cf, id_usuario):
    """id_presencia abierta de este usuario (o None). Consulta chica, sin caché: es su propio estado."""
    try:
        with cf() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id_presencia, entrada_ts FROM produccion.v_presencia_actual "
                            "WHERE id_usuario=%s ORDER BY entrada_ts DESC LIMIT 1", (int(id_usuario),))
                r = cur.fetchone()
        return (r[0], r[1]) if r else None
    except Exception:
        return None


def _marcar_presencia(conectar, USR, entrar: bool, sector=None):
    """Entrada / salida en fact_presencia. Pasa por conectar(): auditoría + commit + invalidación."""
    with conectar(int(USR["id_usuario"])) as (conn, _audit):
        with conn.cursor() as cur:
            if entrar:
                cur.execute("UPDATE produccion.fact_presencia SET salida_ts = now(), origen = 'AUTO' "
                            "WHERE id_usuario=%s AND salida_ts IS NULL", (int(USR["id_usuario"]),))
                cur.execute("INSERT INTO produccion.fact_presencia (id_usuario, sector) VALUES (%s, %s)",
                            (int(USR["id_usuario"]), sector))
            else:
                cur.execute("UPDATE produccion.fact_presencia SET salida_ts = now() "
                            "WHERE id_usuario=%s AND salida_ts IS NULL", (int(USR["id_usuario"]),))


# ------------------------------------------------------------------ formato
def _n(x, d=0):
    try:
        return f"{float(x):,.{d}f}"
    except Exception:
        return "—"


def _i(x):
    try:
        return int(x or 0)
    except Exception:
        return 0


_CORRIENTE_UI = {
    "vegetal": "vegetal", "animal": "animal", "efluente_liquido": "líquidos DF", "solido": "sólidos",
    "sin_declarar": "sin declarar",
}


def _kpi(label, valor, sub, cls=""):
    # misma tarjeta que la portada clásica: el color (ok/warn/bad) va en el valor
    return (f'<div class="kpi"><div class="l">{label}</div>'
            f'<div class="v {cls}">{valor}</div><div class="s">{sub}</div></div>')


# ------------------------------------------------------------------ bloque
@_FRAGMENT
def render_kpis_area(ctx):
    """Los 5 indicadores + presencia + capacidad por producto. Corre en su propio fragmento."""
    cf, USR = ctx["conn_factory"], ctx["USR"]
    k = _leer_kpis(cf)
    if not k:
        st.caption("Indicadores del área: sin conexión a la base en este momento.")
        return

    # 1. acopio disponible
    tq_libre, tq_cap = float(k.get("tanques_libre_kl") or 0), float(k.get("tanques_cap_kl") or 0)
    pi_libre, pi_cap = float(k.get("piletas_libre_kl") or 0), float(k.get("piletas_cap_kl") or 0)
    pct_ocup = (100.0 * (1 - (tq_libre + pi_libre) / (tq_cap + pi_cap))) if (tq_cap + pi_cap) > 0 else None
    solidos = ("sólidos: sin dato" if _i(k.get("solidos_n")) == 0
               else f"sólidos: {_n(k.get('solidos_tn'), 1)} TN")
    acopio_cls = "bad" if (pct_ocup or 0) >= 90 else ("warn" if (pct_ocup or 0) >= 75 else "")
    c1 = _kpi("Acopio disponible",
              f"{_n(tq_libre + pi_libre)}<span style='font-size:1rem;font-weight:700;'> kL</span>",
              f"tanques {_n(tq_libre)} kL ({_i(k.get('tanques_con_espacio'))} de {_i(k.get('tanques_n'))} con lugar) · "
              f"piletas {_n(pi_libre)} kL · {solidos}"
              + (f" · <b>{pct_ocup:.0f}% ocupado</b>" if pct_ocup is not None else ""),
              acopio_cls)

    # 2. descargas pendientes / en proceso
    cam = _i(k.get("camiones_adentro"))
    pc = k.get("camiones_por_corriente") or {}
    det = " · ".join(f"{_CORRIENTE_UI.get(c, c)} {n}" for c, n in pc.items()) if pc else "ningún camión adentro"
    afe = _i(k.get("afe_sin_tanque"))
    c2 = _kpi("Descargas pendientes / en proceso",
              str(cam),
              f"camiones en planta: {det}"
              + (f" · <b>{afe} AFE evaluados sin tanque asignado</b>" if afe else ""),
              "warn" if (cam > 0 or afe > 0) else "")

    # 3. personal en planta
    pres, logins = _i(k.get("personal_presente")), _i(k.get("personal_logins_10h"))
    if pres > 0:
        c3 = _kpi("Personal en planta", str(pres), "marcaron “Estoy en planta” · "
                  f"{logins} con sesión en las últimas 10 h", "ok")
    else:
        c3 = _kpi("Personal en planta", f"{logins}<span style='font-size:1rem;font-weight:700;'> *</span>",
                  "* sesiones abiertas en las últimas 10 h — nadie marcó presencia todavía", "")

    # 4. sectores activos
    sa, sd, stot = _i(k.get("sectores_activos")), _i(k.get("sectores_con_datos")), _i(k.get("sectores_total"))
    c4 = _kpi("Sectores activos", f"{sa}<span style='font-size:1rem;font-weight:700;'> / {sd}</span>",
              (k.get("sectores_activos_nombres") or "sin actividad registrada hoy")
              + (f" · {stot - sd} sectores todavía sin datos" if stot > sd else ""),
              "")

    # 5. tickets pendientes de análisis
    tp, ev = _i(k.get("tickets_lab_pend")), _i(k.get("esperando_validacion"))
    c5 = _kpi("Tickets pendientes de análisis", str(tp),
              f"a evaluar en laboratorio · {_i(k.get('lab_evaluados_hoy'))} evaluados hoy"
              + (f" · <b>{ev} reacciones esperando validación</b>" if ev else ""),
              "warn" if tp > 0 else "ok")

    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}{c4}{c5}</div>', unsafe_allow_html=True)

    # ---- acciones: presencia + accesos directos + refresco ----
    b1, b2, b3, b4 = st.columns([1.5, 1.4, 1.4, 0.9])
    conectar = ctx.get("conectar")
    if conectar is not None:
        abierta = _presencia_abierta(cf, USR["id_usuario"])
        if abierta:
            if b1.button("🔴 Me retiro de planta", key="nav_pres_out", use_container_width=True,
                         help="Cierra tu presencia de hoy."):
                try:
                    _marcar_presencia(conectar, USR, entrar=False)
                    _leer_kpis.clear()
                    st.rerun(scope="fragment")
                except Exception as e:
                    st.error(f"No se pudo registrar la salida: {e}")
        else:
            if b1.button("🟢 Estoy en planta", key="nav_pres_in", type="primary", use_container_width=True,
                         help="Marca tu entrada: suma al indicador de personal en planta y de tu sector."):
                try:
                    _marcar_presencia(conectar, USR, entrar=True, sector=USR.get("sector"))
                    _leer_kpis.clear()
                    st.rerun(scope="fragment")
                except Exception as e:
                    st.error(f"No se pudo registrar la entrada: {e}")
    puede = ctx["puede_seccion"]
    if tp > 0 and puede("LAB"):
        if b2.button("🧪 Ver tickets pendientes", key="nav_kpi_lab", use_container_width=True):
            _st.set_nav("PRODUCCION", "LABORATORIO", rerun=False)
            st.session_state.section = "LAB"
            st.rerun()
    if (cam > 0 or afe > 0) and puede("INICIAR"):
        if b3.button("🚛 Disponibilidad de descarga", key="nav_kpi_desc", use_container_width=True):
            _st.set_nav("PRODUCCION", "PORTERIA", rerun=False)
            st.session_state.section = "INICIAR"
            st.rerun()
    if b4.button("↻", key="nav_kpi_refresh", use_container_width=True, help="Recalcular ahora"):
        _leer_kpis.clear()
        _leer_capacidad.clear()
        st.rerun(scope="fragment")

    # ---- Panel de Control: capacidad ocupada por producto (barra horizontal, como pidió Fernando) ----
    with st.expander("🎛️ Capacidad de acopio ocupada por producto", expanded=False):
        _render_capacidad(cf)
    st.caption("Indicadores propuestos por dirección · a validar con Eugenia, Pablo y Fernando. "
               "“Sin dato” = todavía no se carga en el sistema (sólidos, presencia), no un cero.")


def _render_capacidad(cf):
    df = _leer_capacidad(cf)
    if df is None or df.empty:
        st.caption("Sin datos de tanques.")
        return
    tot_cap, tot_act = float(df["cap_kl"].sum()), float(df["act_kl"].sum())
    pct_tot = 100.0 * tot_act / tot_cap if tot_cap else 0.0
    st.markdown(f"**Planta: {pct_tot:.0f}% ocupado** · {_n(tot_act)} de {_n(tot_cap)} kL · "
                f"{_n(tot_cap - tot_act)} kL libres")
    filas = []
    for _, r in df.iterrows():
        pct = float(r["pct_ocupado"] or 0)
        color = "#dc2626" if pct >= 90 else ("#f59e0b" if pct >= 75 else "#6d5cf6")
        pil = " 🌊" if bool(r.get("incluye_piletas")) else ""
        filas.append(
            f'<div style="display:grid;grid-template-columns:150px 1fr 170px;gap:10px;align-items:center;'
            f'font-size:.86rem;margin:3px 0;">'
            f'<div style="font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{r["producto"]}{pil}</div>'
            f'<div style="background:#eef0f4;border-radius:6px;height:14px;position:relative;overflow:hidden;">'
            f'<div style="width:{min(pct,100):.0f}%;background:{color};height:100%;border-radius:6px;"></div>'
            f'<div style="position:absolute;left:90%;top:-2px;bottom:-2px;width:2px;background:#0f172a;opacity:.35;"></div></div>'
            f'<div style="text-align:right;color:#475569;">{pct:.0f}% · {_n(r["libre_kl"])} kL libres · {int(r["tanques"])} tq</div>'
            f'</div>')
    st.markdown("".join(filas), unsafe_allow_html=True)
    st.caption("Barra = % ocupado del acopio de ese producto (todos sus tanques y piletas). Marca = 90%. "
               "🌊 incluye piletas. Fuente: última medición de cada tanque (vw_tanque_panel).")
