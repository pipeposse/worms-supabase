# -*- coding: utf-8 -*-
"""Selector de período común a las pantallas de sector (pedido de dirección, 14/09/2026).

Dirección mira el negocio por AÑO y por SEMANA; "últimos 30 / 90 días" no le dice nada
porque no cierra contra ninguna planilla. Cuando necesita algo puntual, elige las fechas.

    selector("stk_EXPORTACION")  ->  (desde, hasta, etiqueta)

La elección queda en session_state, así que la pantalla la recuerda al volver.
"""

from datetime import date, timedelta

import streamlit as st

MODOS = ["Semana", "Año", "Fechas"]


def _semana_de(d: date):
    y, w, _ = d.isocalendar()
    return y, w


def _lunes(anio: int, semana: int) -> date:
    try:
        return date.fromisocalendar(anio, semana, 1)
    except ValueError:
        return date.fromisocalendar(anio, 1, 1)


def _semanas_del_anio(anio: int) -> int:
    return date(anio, 12, 28).isocalendar()[1]


def selector(key: str, modo_default: str = "Semana"):
    """Dibuja el selector y devuelve (desde, hasta, etiqueta)."""
    hoy = date.today()
    a_hoy, s_hoy = _semana_de(hoy)
    k_modo = f"per_modo_{key}"
    st.session_state.setdefault(k_modo, modo_default)

    c0, c1 = st.columns([1.2, 3])
    modo = c0.radio("Período", MODOS, horizontal=True, key=k_modo, label_visibility="collapsed")

    if modo == "Año":
        k_a = f"per_anio_{key}"
        anios = list(range(a_hoy, a_hoy - 6, -1))
        st.session_state.setdefault(k_a, a_hoy)
        anio = c1.selectbox("Año", anios, key=k_a, label_visibility="collapsed")
        return date(anio, 1, 1), (hoy if anio == a_hoy else date(anio, 12, 31)), f"año {anio}"

    if modo == "Fechas":
        k_r = f"per_rango_{key}"
        st.session_state.setdefault(k_r, (hoy - timedelta(days=7), hoy))
        r = c1.date_input("Fechas", key=k_r, format="DD/MM/YYYY", label_visibility="collapsed")
        if isinstance(r, (list, tuple)):
            desde = r[0] if len(r) > 0 else hoy
            hasta = r[1] if len(r) > 1 else desde
        else:
            desde = hasta = r
        return desde, hasta, f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"

    # ---- Semana ----
    k_sem = f"per_sem_{key}"
    st.session_state.setdefault(k_sem, (a_hoy, s_hoy))
    anio, semana = st.session_state[k_sem]
    b1, b2, b3, b4 = c1.columns([0.5, 2.4, 0.5, 0.8])
    if b1.button("◀", key=f"{key}_sem_prev", use_container_width=True):
        st.session_state[k_sem] = _semana_de(_lunes(anio, semana) - timedelta(days=7)); st.rerun()
    lun = _lunes(anio, semana)
    b2.markdown(f"<div style='text-align:center;padding-top:6px'><b>Semana {semana} / {anio}</b> · "
                f"{lun:%d/%m} al {lun + timedelta(days=6):%d/%m}</div>", unsafe_allow_html=True)
    if b3.button("▶", key=f"{key}_sem_next", use_container_width=True):
        st.session_state[k_sem] = _semana_de(_lunes(anio, semana) + timedelta(days=7)); st.rerun()
    if b4.button("Esta semana", key=f"{key}_sem_hoy", use_container_width=True):
        st.session_state[k_sem] = (a_hoy, s_hoy); st.rerun()
    return lun, lun + timedelta(days=6), f"semana {semana} / {anio}"
