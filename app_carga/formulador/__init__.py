"""Componente de formulación de despachos (HTML/JS propio, sin build).

POR QUÉ EXISTE
--------------
El armador usaba dos `st.data_editor` espejados sobre el mismo estado
(`dsp_lineas`). `st.data_editor` calcula su identidad hasheando LOS DATOS que
recibe (streamlit/elements/widgets/data_editor.py -> compute_and_register_element_id
con data=arrow_bytes), así que cada vez que uno de los dos cambiaba, el otro
recibía datos distintos, Streamlit lo trataba como un widget NUEVO y lo
desmontaba: se perdía el foco, el scroll y lo tipeado entre el click y el
redibujo. Eso es lo que en planta se vive como "toco un tanque y se reinicia
la página / no se guarda lo que puse".

Un componente propio NO tiene ese problema: cuando se le pasa `key`, Streamlit
fija su identidad en `component_name + url + key` y NO vuelve a montar el
iframe aunque cambien todos sus argumentos (streamlit/components/v1/custom_component.py,
rama `if key is None: ... else: ...`). El estado vive en el navegador, se
calcula todo en el acto (litros, TN, ponderados por kg, semáforos) y recién
después de ~400 ms sin tocar nada se manda al servidor UNA vez.

PROTOCOLO (apiVersion 1, verificado contra el bundle de Streamlit 1.44)
    iframe -> app : {isStreamlitMessage:true, type:"streamlit:componentReady", apiVersion:1}
                    {isStreamlitMessage:true, type:"streamlit:setFrameHeight", height:N}
                    {isStreamlitMessage:true, type:"streamlit:setComponentValue", value:V}
    app -> iframe : {type:"streamlit:render", args:{...}, disabled:bool, theme:{...}}

CONTRATO DE SINCRONIZACIÓN (`rev`)
    El servidor manda `rev`. El componente sólo PISA su estado local cuando la
    `rev` que recibe es distinta de la última que aplicó: eso pasa únicamente
    con cambios programáticos (Sugerir, Deshacer, Usar propuesta, restaurar
    borrador, cambio de producto). El eco del propio cambio del usuario llega
    con la misma `rev` y se ignora, así nunca se revierte lo tipeado.
    El valor que devuelve incluye la `rev` sobre la que se editó: el servidor
    descarta lo que venga de una `rev` vieja.
"""
import os

import streamlit as st
import streamlit.components.v1 as _components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

_impl = None
_error = None
try:
    if os.path.isfile(os.path.join(_DIR, "index.html")):
        _impl = _components.declare_component("worms_formulador", path=_DIR)
    else:
        _error = "falta %s" % os.path.join(_DIR, "index.html")
except Exception as _e:            # streamlit sin soporte de componentes
    _error = str(_e)


def disponible():
    return _impl is not None


def motivo():
    return _error


def formulador(*, tanks, lines, spec, rev, objetivo=0.0, tol=0.10,
               min_toma=3000.0, min_tanque=3500.0, permitir_manual=False,
               solo_lectura=False, key="dsp_formulador", height_hint=760):
    """Dibuja el formulador y devuelve el estado que mandó el navegador (o None).

    Devuelve: {"rev": int, "seq": int, "lines": [{"k": clave, "l": litros,
               "ov": {"ac":..,"fos":..,"az":..,"ays":..}}]}
    """
    if _impl is None:
        return None
    return _impl(
        tanks=tanks, lines=lines, spec=spec, rev=int(rev), objetivo=float(objetivo or 0.0),
        tol=float(tol), min_toma=float(min_toma), min_tanque=float(min_tanque),
        permitir_manual=bool(permitir_manual), solo_lectura=bool(solo_lectura),
        key=key, default=None)
