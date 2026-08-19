# -*- coding: utf-8 -*-
"""📋 Brief semanal de Dirección.

Un informe de 8 páginas sobre la semana ISO cerrada (lunes a domingo), pensado
para leerse de un vistazo: qué exige una decisión, qué entró y con qué calidad,
cuánto stock hay por calidad y cuánto está comprometido, dónde están los desvíos
y cómo estamos posicionados para los próximos despachos.

El mismo HTML que se ve en pantalla es el que se descarga y el que manda el
envío automático de los lunes: una sola fuente, cero versiones paralelas.

    from brief_dir import render
    render(USR, cat, conectar)
"""
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

from . import datos as _datos
from . import metas as _metas
from .render import render as _html

ROLES = ("SUPERVISOR", "ADMIN")


def _fecha_larga(s):
    m = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    d = date.fromisoformat(str(s))
    return f"{d.day} de {m[d.month-1]}"


def construir(cat, semana):
    """Devuelve (html, D). Separado del render de Streamlit para que el
    generador headless del lunes use exactamente este mismo camino."""
    D = _datos.cargar(cat, semana)
    return _html(D), D


def render(USR, cat, conectar=None):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#0f172a,#1d4ed8);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>📋 Brief semanal</div>"
        "<div style='color:#dbeafe;font-size:.88rem;margin-top:3px'>Ocho páginas sobre la "
        "semana cerrada: ingresos, calidad, stock por calidad, compromisos, desvíos, "
        "despachos y proyecciones. Todo comparado con las semanas y meses previos.</div></div>",
        unsafe_allow_html=True)

    if USR.get("rol") not in ROLES and "DIRECCION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return

    sems = _datos.semanas_disponibles(cat)
    if not sems:
        st.info("Todavía no hay ninguna semana cerrada con datos.")
        return

    c1, c2 = st.columns([3, 2])
    sem = c1.selectbox(
        "Semana a informar", sems, index=0, key="brief_sem",
        format_func=lambda s: f"{_fecha_larga(s)} · semana cerrada",
        help="Sólo semanas ISO terminadas (lunes a domingo). El brief del lunes "
             "informa la semana anterior completa.")
    c2.caption("El brief se arma sobre la semana cerrada para que los números no "
               "se muevan si lo abrís dos veces el mismo día.")

    with st.spinner("Armando el brief…"):
        try:
            html, D = construir(cat, sem)
        except Exception as e:
            import traceback
            st.error(f"No se pudo armar el brief: {e}")
            with st.expander("🔧 Detalle técnico"):
                st.code(traceback.format_exc())
            return

    nombre = f"brief_worms_{D['semana_iso']}"
    st.download_button("⬇️ Descargar el brief", html.encode("utf-8"),
                       file_name=f"{nombre}.html", mime="text/html",
                       use_container_width=True, type="primary")
    st.caption(
        "Es **un solo archivo que sirve en los dos lados**: en la computadora se pagina en A4 y con "
        "**Imprimir → Guardar como PDF** sale el informe listo para mandar; en el teléfono se acomoda "
        "solo a una columna, con letra grande, las tablas convertidas en fichas y los gráficos "
        "deslizables. Se comparte por WhatsApp o mail tal cual está y se abre sin internet.")

    _metas.editor(USR, cat, conectar)

    st.divider()
    ver = st.radio("Vista previa", ["🖥️ Como se ve impreso", "📱 Como se ve en el celular"],
                   horizontal=True, key="brief_vista", label_visibility="collapsed")
    if ver.startswith("📱"):
        st.caption("Simulación de un teléfono de 390 px de ancho.")
        _c = st.columns([1, 2, 1])[1]
        with _c:
            components.html(html, height=1200, scrolling=True, width=390)
    else:
        components.html(html, height=1200, scrolling=True)
