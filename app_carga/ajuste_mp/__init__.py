"""Grilla de ajuste de kg reales por materia prima (componente propio, sin build).

POR QUÉ NO ES UN st.data_editor
-------------------------------
Es la misma historia que el armador de despachos (ver formulador/): un
`st.data_editor` calcula su identidad hasheando LOS DATOS que recibe, así que
cualquier cosa que cambie esos datos lo desmonta y se pierde el foco; y cada
edición vuelve al servidor, que redibuja la sección entera. En una grilla de
despachos × materias primas eso se siente como "se cuelga y se reinicia".

Acá el estado vive en el navegador y **no se manda NADA al servidor mientras se
edita**: los totales de cada fila, la diferencia contra la balanza y los totales
de la semana se recalculan en el acto, y recién al tocar *Guardar* sale un único
mensaje con los cambios. Cero reruns tipeando.

Como con `key` Streamlit fija la identidad del componente en
`component_name + url + key` y no vuelve a montar el iframe
(streamlit/components/v1/custom_component.py), la grilla nunca se reinicia.

Lo que se está editando se respalda en `localStorage` del navegador, así que si
alguien cierra la pestaña con cambios sin guardar los recupera al volver.

CONTRATO
--------
args  : rev (int), mps [str], rows [{id, desp, fecha, cont, bal, aj, v{}, f{}}],
        titulo (str)
valor : None mientras se edita; al guardar
        {"action":"save","rev":N,"seq":N,"cambios":[{"id":..,"mp":..,"tn":num|None}]}
        (tn None = esa materia prima vuelve a valer lo formulado)
"""
import os

import streamlit.components.v1 as _components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

_impl = None
_error = None
try:
    if os.path.isfile(os.path.join(_DIR, "index.html")):
        _impl = _components.declare_component("worms_ajuste_mp", path=_DIR)
    else:
        _error = "falta %s" % os.path.join(_DIR, "index.html")
except Exception as _e:
    _error = str(_e)


def disponible():
    return _impl is not None


def motivo():
    return _error


def grilla(*, rows, mps, rev, titulo="", key="dsw_ajuste"):
    if _impl is None:
        return None
    return _impl(rows=rows, mps=list(mps), rev=int(rev), titulo=str(titulo),
                 key=key, default=None)
