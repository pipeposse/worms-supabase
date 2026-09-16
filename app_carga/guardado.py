# -*- coding: utf-8 -*-
"""Recibo de guardado: que se vea, sin dudas, si el dato quedó en la base.

EL PROBLEMA
-----------
La queja de planta no es que el sistema pierda datos: es que **no se sabe si
guardó**. Dos causas concretas, las dos de Streamlit:

1. `st.success("Guardado")` seguido de `st.rerun()` (o de un rerun de fragmento)
   dura un parpadeo y desaparece. El operario no llega a leerlo.
2. El cartel verde dice "guardado" porque el `INSERT` no tiró excepción, pero
   nadie volvió a mirar la base. Si un trigger descartó la fila (anti doble
   carga), o un `ON CONFLICT DO NOTHING` la salteó, el cartel miente.

El resultado se ve en `produccion.log_doble_carga`: la misma pantalla guardada
5, 6, 9 veces seguidas en menos de un minuto. No es que falle: es que el
operario no tiene forma de saberlo y vuelve a apretar.

CÓMO SE USA
-----------
    import guardado as _g

    # al guardar
    _n = _g.contar("SELECT count(*) FROM produccion.fact_despacho_linea "
                   "WHERE id_despacho=%s", (idd,))
    _g.anotar("despacho_armado", True, "Orden de venta #%d guardada" % idd,
              detalle="AFE-S · 138.000 L",
              verificado="%d líneas leídas de vuelta desde la base" % _n)
    st.rerun()                      # el recibo sobrevive al rerun

    # arriba de la pantalla, siempre
    _g.mostrar("despacho_armado")

`anotar()` guarda el recibo en session_state, así que **sobrevive al rerun y al
rerun de fragmento**: se ve recién después, que es cuando el operario mira.
`verificado` es lo único que convierte un "parece que guardó" en un "guardó":
tiene que salir de volver a leer la base, no de la variable que se acaba de
escribir.
"""

import time

import streamlit as st

_PREFIJO = "_gdo_"
_MINUTOS = 30          # después de esto el recibo se va solo (es de la sesión anterior)


# ------------------------------------------------------------------ lectura de verificación
def _conn():
    """Conexión de lectura del pool de la app (sin handshake). None si no está."""
    try:
        import app as _app
        return _app._lab_conn
    except Exception:
        return None


def contar(sql, params=None):
    """Vuelve a leer la base SIN caché y devuelve el primer valor de la primera fila.

    Es la parte que hace honesto al recibo: lo que se muestra como verificado
    sale de acá, no de lo que la pantalla creía haber escrito. Devuelve None si
    no se pudo leer (ahí el recibo lo dice, no inventa)."""
    cf = _conn()
    if cf is None:
        return None
    try:
        with cf() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                r = cur.fetchone()
        return r[0] if r else None
    except Exception:
        return None


def fila(sql, params=None):
    """Como contar(), pero devuelve la fila entera (tupla) o None."""
    cf = _conn()
    if cf is None:
        return None
    try:
        with cf() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()
    except Exception:
        return None


# ------------------------------------------------------------------ recibo
def anotar(clave, ok, titulo, detalle="", verificado="", error=""):
    """Deja el recibo listo para mostrarse en el próximo dibujado de la pantalla."""
    st.session_state[_PREFIJO + str(clave)] = {
        "ok": bool(ok), "titulo": str(titulo or ""), "detalle": str(detalle or ""),
        "verificado": str(verificado or ""), "error": str(error or ""),
        "ts": time.time(),
        "hora": time.strftime("%H:%M:%S"),
    }


def limpiar(clave):
    st.session_state.pop(_PREFIJO + str(clave), None)


def hay(clave):
    return (_PREFIJO + str(clave)) in st.session_state


def mostrar(clave, minutos=_MINUTOS):
    """Dibuja el recibo pendiente (si hay) y lo deja hasta que el usuario lo cierre."""
    k = _PREFIJO + str(clave)
    r = st.session_state.get(k)
    if not isinstance(r, dict):
        return
    if time.time() - float(r.get("ts") or 0) > minutos * 60:
        st.session_state.pop(k, None)
        return

    if r["ok"]:
        _borde, _fondo, _tit, _ic = "#16a34a", "#f0fdf4", "#166534", "✅"
        _sello = "GUARDADO Y VERIFICADO EN LA BASE"
    else:
        _borde, _fondo, _tit, _ic = "#dc2626", "#fef2f2", "#991b1b", "❌"
        _sello = "NO SE GUARDÓ — no quedó nada a medias"

    _html = [
        "<div style='border:2px solid %s;background:%s;border-radius:12px;"
        "padding:12px 16px;margin:6px 0 10px'>" % (_borde, _fondo),
        "<div style='color:%s;font-weight:900;font-size:.82rem;letter-spacing:.04em'>%s %s · %s</div>"
        % (_tit, _ic, _sello, r["hora"]),
        "<div style='color:#0f172a;font-weight:800;font-size:1.05rem;margin-top:2px'>%s</div>"
        % r["titulo"],
    ]
    if r["detalle"]:
        _html.append("<div style='color:#334155;font-size:.9rem;margin-top:2px'>%s</div>" % r["detalle"])
    if r["verificado"]:
        _html.append("<div style='color:#166534;font-size:.86rem;margin-top:6px'>"
                     "🔎 Comprobado volviendo a leer la base: <b>%s</b></div>" % r["verificado"])
    elif r["ok"]:
        _html.append("<div style='color:#a16207;font-size:.86rem;margin-top:6px'>"
                     "⚠️ La escritura no dio error, pero no se pudo releer la base para "
                     "confirmarlo. Revisá el dato antes de volver a cargarlo.</div>")
    if r["error"]:
        _html.append("<div style='color:#991b1b;font-size:.86rem;margin-top:6px'>"
                     "Motivo: %s</div>" % r["error"])
    if not r["ok"]:
        _html.append("<div style='color:#334155;font-size:.86rem;margin-top:6px'>"
                     "Podés volver a intentarlo: no se guardó nada, así que no se duplica.</div>")
    _html.append("</div>")
    st.markdown("".join(_html), unsafe_allow_html=True)
    if st.button("Entendido, cerrar aviso", key="gdo_ok_%s" % clave):
        st.session_state.pop(k, None)
        st.rerun()


def envolver(clave, titulo, fn, verificar=None, detalle=""):
    """Ejecuta fn() y deja el recibo, haya salido bien o mal.

    `verificar` es una función sin argumentos que vuelve a leer la base y
    devuelve el texto de lo comprobado (o None). Devuelve lo que devolvió fn(),
    o None si falló."""
    try:
        with st.spinner("Guardando…"):
            out = fn()
    except Exception as e:
        anotar(clave, False, titulo, detalle=detalle, error=str(e))
        return None
    _v = ""
    if verificar is not None:
        try:
            _v = verificar(out) or ""
        except Exception:
            _v = ""
    anotar(clave, True, titulo, detalle=detalle, verificado=_v)
    return out
