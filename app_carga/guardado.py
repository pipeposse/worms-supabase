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
    flash_mostrar()
    k = _PREFIJO + str(clave)
    r = st.session_state.get(k)
    if not isinstance(r, dict):
        return
    if time.time() - float(r.get("ts") or 0) > minutos * 60:
        st.session_state.pop(k, None)
        return
    # SOL-0043: el recibo se dibuja donde está la vista, pero el operario suele estar
    # al final de una pantalla larga (el botón Guardar). El toast aparece en la esquina
    # de la ventana esté donde esté el scroll. Una sola vez por recibo.
    if not r.get("toast"):
        r["toast"] = True
        try:
            st.toast(("✅ " if r["ok"] else "❌ ") + r["titulo"])
        except Exception:
            pass

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


# ==================================================================== flash global
# EL ARREGLO DE FONDO
# -------------------
# `st.success("Guardado") ; st.rerun()` está escrito así en 122 lugares de la app.
# En los 122 el cartel dura un parpadeo: el rerun redibuja la página desde cero y
# se lo lleva puesto. Tocar 122 lugares a mano es un riesgo mayor que el bug, así
# que se intercepta una sola vez:
#
#   · se envuelven st.success / st.warning / st.toast: además de dibujar, anotan
#     el texto en un buffer de este dibujado;
#   · se envuelve st.rerun: si en ESTE dibujado hubo un COMMIT contra la base
#     (lo avisa el hook de etl.db) y hay textos en el buffer, los guarda como
#     "flash" en session_state antes de rerunear;
#   · `flash_mostrar()` (arriba de cada pantalla) los dibuja después del rerun,
#     con la hora y qué tablas se escribieron, y ahí sí quedan a la vista.
#
# La condición del commit es la que evita ruido: un st.success informativo de la
# pantalla no se reenvía; sólo se reenvía el que acompañó una escritura real.

_BUF = "_gdo_buf"
_COMMIT = "_gdo_commit"
_FLASH = "_gdo_flash"
_INSTALADO = [False]


def _ss():
    try:
        return st.session_state
    except Exception:
        return None


def _anotar_buffer(tipo, texto):
    ss = _ss()
    if ss is None:
        return
    try:
        buf = ss.get(_BUF)
        if not isinstance(buf, list):
            buf = []
        _t = str(texto)
        if len(_t) > 400:
            _t = _t[:400] + "…"
        buf.append((tipo, _t))
        ss[_BUF] = buf[-6:]
    except Exception:
        pass


def _marcar_commit(stmts):
    """Hook de etl.db: esta transacción escribió. Guarda qué tablas tocó."""
    ss = _ss()
    if ss is None:
        return
    try:
        import re as _re
        _tabs = []
        for _s in (stmts or []):
            m = _re.search(r"(?is)\b(?:insert\s+into|update|delete\s+from)\s+"
                           r"(?:produccion\.)?([a-z_][\w]*)", str(_s))
            if m:
                _t = m.group(1).lower()
                if _t not in _tabs:
                    _tabs.append(_t)
        if not _tabs:
            return                      # transacción de sólo lectura: no es un guardado
        ss[_COMMIT] = {"ts": time.time(), "tablas": _tabs[:6]}
    except Exception:
        pass


def instalar():
    """Se llama UNA vez al arrancar la app (después de configurar etl.db)."""
    if _INSTALADO[0]:
        return
    _INSTALADO[0] = True

    # 1) hook de commit
    try:
        from etl import db as _etl_db
        if _marcar_commit not in _etl_db.ON_COMMIT_HOOKS:
            _etl_db.ON_COMMIT_HOOKS.append(_marcar_commit)
    except Exception:
        pass

    # 2) envolver los carteles
    for _nombre in ("success", "warning", "toast"):
        _orig = getattr(st, _nombre, None)
        if _orig is None or getattr(_orig, "_gdo", False):
            continue

        def _hacer(_o, _tipo):
            def _w(*a, **k):
                if a:
                    _anotar_buffer(_tipo, a[0])
                return _o(*a, **k)
            _w._gdo = True
            _w.__name__ = getattr(_o, "__name__", _tipo)
            return _w
        try:
            setattr(st, _nombre, _hacer(_orig, _nombre))
        except Exception:
            pass

    # 3) envolver el rerun
    _rr = getattr(st, "rerun", None)
    if _rr is not None and not getattr(_rr, "_gdo", False):
        def _rerun(*a, **k):
            ss = _ss()
            try:
                if ss is not None:
                    _c = ss.get(_COMMIT)
                    _b = ss.get(_BUF) or []
                    # sólo se reenvía el cartel que acompañó una escritura real
                    if isinstance(_c, dict) and _b and time.time() - float(_c.get("ts") or 0) < 60:
                        ss[_FLASH] = {"msgs": list(_b), "tablas": list(_c.get("tablas") or []),
                                      "ts": time.time(), "hora": time.strftime("%H:%M:%S")}
                        ss.pop(_COMMIT, None)
                        ss[_BUF] = []
            except Exception:
                pass
            return _rr(*a, **k)
        _rerun._gdo = True
        try:
            st.rerun = _rerun
        except Exception:
            pass


def flash_mostrar(minutos=10, limpiar_buffer=True):
    """Dibuja el cartel que el rerun se había comido. Va arriba de cada pantalla."""
    ss = _ss()
    if ss is None:
        return
    f = ss.get(_FLASH)
    if limpiar_buffer:
        ss[_BUF] = []               # arranca un dibujado nuevo
    if not isinstance(f, dict):
        return
    if time.time() - float(f.get("ts") or 0) > minutos * 60:
        ss.pop(_FLASH, None)
        return
    _msgs = [t for _tp, t in (f.get("msgs") or []) if str(t).strip()]
    if not _msgs:
        ss.pop(_FLASH, None)
        return
    _tabs = ", ".join(f.get("tablas") or [])
    _html = ["<div style='border:2px solid #16a34a;background:#f0fdf4;border-radius:12px;"
             "padding:10px 14px;margin:4px 0 10px'>",
             "<div style='color:#166534;font-weight:900;font-size:.8rem;letter-spacing:.04em'>"
             "✅ GUARDADO EN LA BASE · %s</div>" % f.get("hora", "")]
    for m in _msgs:
        _m = str(m).replace("<", "&lt;").replace(">", "&gt;")
        _html.append("<div style='color:#0f172a;font-weight:700;font-size:1rem;margin-top:2px'>"
                     "%s</div>" % _m)
    if _tabs:
        _html.append("<div style='color:#166534;font-size:.82rem;margin-top:5px'>"
                     "Escrito en: <b>%s</b></div>" % _tabs)
    _html.append("</div>")
    st.markdown("".join(_html), unsafe_allow_html=True)
    ss.pop(_FLASH, None)
