# -*- coding: utf-8 -*-
"""📣 Aviso de actualización — el cartel que le avisa a planta antes de un deploy.

POR QUÉ EXISTE
--------------
Cada push reconstruye la app en Streamlit Cloud (~1 min) y **mata todas las
sesiones abiertas**: se borra lo tipeado y no guardado. Quien estaba a mitad de
una formulación, tildando tickets o cargando el checklist de arranque, lo pierde
y tiene que empezar de nuevo. Con esto se avisa con minutos de anticipación para
que cierren lo que están cargando.

CÓMO SE USA
-----------
    import aviso
    aviso.mostrar()                       # arriba de cada pantalla (app.py)
    aviso.panel(USR, cat, conectar)       # para prenderlo y apagarlo (dirección)

El estado vive en `produccion.app_aviso` (una sola fila), así que lo ven TODOS
los usuarios conectados, no sólo quien lo prendió. Se lee con 15 segundos de
caché: el cartel aparece en la pantalla de cualquiera a los pocos segundos de
prenderlo, sin pegarle a la base en cada dibujado.
"""
from datetime import datetime, timedelta, timezone

import streamlit as st

_TZ = timezone(timedelta(hours=-3))          # hora de planta
_SQL = ("SELECT activo, tipo, titulo, mensaje, hasta_ts, creado_por "
        "FROM produccion.app_aviso WHERE id = 1")
_PRESETS = [("Ahora mismo", 0), ("En 5 minutos", 5), ("En 10 minutos", 10),
            ("En 15 minutos", 15), ("En 30 minutos", 30), ("En 1 hora", 60)]


def _ahora():
    return datetime.now(_TZ)


@st.cache_data(ttl=15, show_spinner=False)
def _leer(_nonce=None):
    """La fila del aviso. 15 s de caché: suficiente para que el cartel llegue
    rápido a todos y no pese en cada dibujado. Devuelve None si no se pudo leer
    (ahí no se muestra nada: el aviso nunca puede romper una pantalla)."""
    try:
        import guardado as _g
        df = _g.leer(_SQL)
        if df is None or df.empty:
            return None
        return df.iloc[0].to_dict()
    except Exception:
        return None


def _minutos_restantes(hasta):
    if hasta is None:
        return None
    try:
        import pandas as pd
        h = pd.to_datetime(hasta)
        if h.tzinfo is None:
            h = h.tz_localize(_TZ)
        return (h - _ahora()).total_seconds() / 60.0
    except Exception:
        return None


def _texto_cuenta(mins):
    if mins is None:
        return ""
    if mins <= 0:
        return "AHORA"
    if mins < 1:
        return "en menos de 1 minuto"
    if mins < 60:
        return "en %d minuto(s)" % int(round(mins))
    return "en %.1f hora(s)" % (mins / 60.0)


# ------------------------------------------------------------------ cartel
def mostrar():
    """Dibuja el cartel si está prendido. Se llama arriba de cada pantalla."""
    r = _leer()
    if not r or not bool(r.get("activo")):
        return
    mins = _minutos_restantes(r.get("hasta_ts"))
    # Ya pasó hace más de 15 minutos: se apaga solo en pantalla (la fila queda,
    # la apaga dirección). Así un aviso olvidado no queda eternamente arriba.
    if mins is not None and mins < -15:
        return

    _urgente = mins is not None and mins <= 5
    _borde = "#b91c1c" if _urgente else "#b45309"
    _fondo = "#fef2f2" if _urgente else "#fffbeb"
    _tit = "#7f1d1d" if _urgente else "#78350f"
    _cuenta = _texto_cuenta(mins)

    _html = [
        "<div style='border:2px solid %s;background:%s;border-radius:12px;"
        "padding:12px 16px;margin:0 0 12px'>" % (_borde, _fondo),
        "<div style='color:%s;font-weight:900;font-size:.95rem;letter-spacing:.02em'>"
        "🛠️ %s%s</div>" % (_tit, str(r.get("titulo") or "Actualización del sistema"),
                           (" · " + _cuenta.upper()) if _cuenta else ""),
        "<div style='color:#1f2937;font-size:.92rem;margin-top:4px'>%s</div>"
        % str(r.get("mensaje") or ""),
        "<div style='color:%s;font-size:.82rem;margin-top:6px;font-weight:700'>"
        "Guardá lo que estés cargando: al actualizarse se cierran todas las sesiones "
        "y lo que no esté guardado se pierde.</div>" % _tit,
        "</div>",
    ]
    st.markdown("".join(_html), unsafe_allow_html=True)


# ------------------------------------------------------------------ panel
def panel(USR, cat, conectar):
    st.markdown("##### 📣 Aviso de actualización")
    st.caption("Prendé el cartel unos minutos antes de actualizar: lo ven **todos** los "
               "usuarios conectados, arriba de cualquier pantalla, con la cuenta regresiva. "
               "Acordate de apagarlo después del deploy.")
    r = _leer() or {}
    _act = bool(r.get("activo"))
    mins = _minutos_restantes(r.get("hasta_ts"))

    if _act:
        st.warning("🟠 **El cartel está PRENDIDO** — %s%s"
                   % (_texto_cuenta(mins) or "sin horario",
                      (" · lo prendió %s" % r["creado_por"]) if r.get("creado_por") else ""))
    else:
        st.success("🟢 El cartel está apagado: nadie ve ningún aviso.")

    _tit = st.text_input("Título", value=str(r.get("titulo") or "Actualización del sistema"),
                         key="avi_tit")
    _msg = st.text_area("Mensaje", value=str(r.get("mensaje") or ""), height=90, key="avi_msg")
    _lbl = [p[0] for p in _PRESETS]
    _sel = st.radio("¿Cuándo se actualiza?", _lbl, index=2, horizontal=True, key="avi_cuando")
    _min = dict(_PRESETS)[_sel]

    c1, c2 = st.columns(2)
    if c1.button("📣 Prender el aviso", type="primary", use_container_width=True, key="avi_on"):
        _guardar(USR, conectar, True, _tit, _msg, _ahora() + timedelta(minutes=_min))
    if c2.button("✅ Apagar el aviso", use_container_width=True, key="avi_off", disabled=not _act):
        _guardar(USR, conectar, False, _tit, _msg, None)

    st.caption("Ventana recomendada para actualizar sin molestar: **01:00 a 06:00** "
               "(0,1 a 0,3 escrituras por día). Las horas a evitar son 09, 11 y 17.")


def _guardar(USR, conectar, activo, titulo, mensaje, hasta):
    import guardado as _g
    try:
        with conectar(int(USR["id_usuario"])) as (conn, audit):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE produccion.app_aviso SET activo=%s, titulo=%s, mensaje=%s, "
                    "hasta_ts=%s, creado_por=%s, actualizado_en=now() WHERE id=1",
                    (bool(activo), str(titulo or "")[:120], str(mensaje or "")[:800],
                     hasta, str(USR.get("nombre") or USR["id_usuario"])))
            audit.log("U", "app_aviso", 1, {"activo": bool(activo),
                                            "hasta": (hasta.isoformat() if hasta else None)})
        _leer.clear()
        _n = _g.contar("SELECT activo::int FROM produccion.app_aviso WHERE id=1")
        _g.anotar("avi_panel", True,
                  "Aviso %s" % ("PRENDIDO" if activo else "apagado"),
                  detalle=(str(titulo or "")[:120] if activo else "ya no se muestra"),
                  verificado=("la base dice activo=%s" % bool(_n)) if _n is not None else "")
        st.rerun()
    except Exception as e:
        _g.anotar("avi_panel", False, "No se pudo cambiar el aviso", error=str(e))
        st.rerun()
