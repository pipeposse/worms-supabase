# -*- coding: utf-8 -*-
"""Estado de la navegación v2: flag por usuario + (área, sector, vista) en la URL."""

import json

import streamlit as st

AREAS = {
    "PRODUCCION": ("🧪", "PRODUCCIÓN"),
    "ADMIN": ("👷", "ADMINISTRACIÓN"),
}

PREF_KEY = "nav_v2"          # dim_usuario.prefs ->> 'nav_v2'  (true/false)
_SS_KEY = "nav"              # st.session_state["nav"] = {"area":..., "sector":..., "vista":...}
_QP_KEYS = ("area", "sector", "vista")


# ---------------------------------------------------------------- flag por usuario
def nav_activo_pref(USR, conn_factory):
    """Lee prefs.nav_v2 UNA vez por sesión (cacheado en session_state)."""
    k = "_nav_v2_flag"
    if k in st.session_state:
        return bool(st.session_state[k])
    val = False
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE((prefs->>%s)::boolean, false) FROM dim_usuario WHERE id_usuario=%s",
                            (PREF_KEY, USR["id_usuario"]))
                row = cur.fetchone()
                val = bool(row[0]) if row else False
    except Exception:
        val = False
    st.session_state[k] = val
    return val


def set_nav_pref(USR, conn_factory, on: bool):
    """Persiste prefs.nav_v2 (merge jsonb, no pisa otras prefs) y actualiza la copia en sesión."""
    st.session_state["_nav_v2_flag"] = bool(on)
    # mantener coherente la copia de prefs que usa get_pref/set_pref de app.py
    if isinstance(st.session_state.get("_prefs"), dict):
        st.session_state["_prefs"][PREF_KEY] = bool(on)
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE dim_usuario SET prefs = COALESCE(prefs,'{}'::jsonb) || %s::jsonb WHERE id_usuario=%s",
                            (json.dumps({PREF_KEY: bool(on)}), USR["id_usuario"]))
            conn.commit()
    except Exception:
        pass


def activo(USR, conn_factory, locked_one=False):
    """¿Este usuario ve la navegación nueva? Nunca para usuarios anclados a UNA sección."""
    if locked_one:
        return False
    return nav_activo_pref(USR, conn_factory)


# ---------------------------------------------------------------- (área, sector, vista)
def _qp_get(k):
    try:
        v = st.query_params.get(k)
    except Exception:
        return None
    if isinstance(v, list):
        v = v[0] if v else None
    return (v or "").strip().upper() or None


def get_nav():
    """Lugar actual. La URL manda (sobrevive a F5 y reconexiones); session_state es la copia."""
    nav = st.session_state.get(_SS_KEY) or {}
    area = _qp_get("area") or nav.get("area")
    sector = _qp_get("sector") or nav.get("sector")
    vista = _qp_get("vista") or nav.get("vista")
    if area not in AREAS:
        area = None
        sector = None
        vista = None
    nav = {"area": area, "sector": sector, "vista": vista}
    st.session_state[_SS_KEY] = nav
    return nav


def set_nav(area=None, sector=None, vista=None, rerun=True):
    """Fija el lugar (y la URL). ``area=None`` vuelve a la raíz."""
    if area is not None and area not in AREAS:
        area = None
    if area is None:
        sector = None
    if sector is None:
        vista = None
    nav = {"area": area, "sector": sector, "vista": vista}
    st.session_state[_SS_KEY] = nav
    try:
        for k in _QP_KEYS:
            v = nav[k]
            if v:
                st.query_params[k] = v
            elif k in st.query_params:
                del st.query_params[k]
    except Exception:
        pass
    if rerun:
        st.rerun()


def clear_nav_qp():
    """Saca área/sector/vista de la URL sin rerun (para volver a la vista clásica limpio)."""
    st.session_state.pop(_SS_KEY, None)
    try:
        for k in _QP_KEYS:
            if k in st.query_params:
                del st.query_params[k]
    except Exception:
        pass
