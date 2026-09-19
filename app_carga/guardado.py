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

def _hora():
    """Hora de planta. El server de Streamlit Cloud corre en UTC: los recibos salían
    con 3 horas de más y no coincidían con lo que el operario tenía en el reloj."""
    try:
        from datetime import datetime, timezone, timedelta
        return (datetime.now(timezone.utc) + timedelta(hours=-3)).strftime("%H:%M:%S")
    except Exception:
        return time.strftime("%H:%M:%S")


_PREFIJO = "_gdo_"
_MINUTOS = 30          # después de esto el recibo se va solo (es de la sesión anterior)


# ------------------------------------------------------------------ lectura de verificación
_CF = [None]          # fábrica de conexiones de lectura (la pone configurar())
_CTX = {"pantalla": None, "usuario": None, "id_usuario": None}


def configurar(conn_factory, pantalla=None):
    """La app registra acá su pool de lectura (`_lab_conn`).

    ANTES ESTO ESTABA MAL: `_conn()` hacía `import app`. Bajo Streamlit el script
    principal se ejecuta como `__main__`, así que ese import NO devuelve el módulo
    en marcha: vuelve a ejecutar app.py de cero en un módulo nuevo y revienta en
    `st.set_page_config` (ya llamado). Resultado: TODA verificación devolvía None y
    cada recibo decía "no se pudo releer la base para confirmarlo" — que es
    exactamente lo que vio planta. Ahora la conexión se inyecta, no se adivina."""
    if conn_factory is not None:
        _CF[0] = conn_factory
    if pantalla:
        _CTX["pantalla"] = pantalla


def contexto(pantalla=None, usuario=None, id_usuario=None):
    """Quién está y en qué pantalla: se guarda con cada error registrado."""
    if pantalla is not None:
        _CTX["pantalla"] = pantalla
    if usuario is not None:
        _CTX["usuario"] = usuario
    if id_usuario is not None:
        try:
            _CTX["id_usuario"] = int(id_usuario)
        except Exception:
            pass


def _conn():
    """Fábrica de conexiones de lectura. None si la app todavía no la registró."""
    if _CF[0] is not None:
        return _CF[0]
    # Respaldo sin importar nada: el módulo de la app ya está cargado bajo otro
    # nombre (__main__ o el de la página). Se lo busca, no se lo re-importa.
    try:
        import sys as _sys
        for _m in list(_sys.modules.values()):
            _f = getattr(_m, "_lab_conn", None)
            if callable(_f) and getattr(_m, "__name__", "") != __name__:
                _CF[0] = _f
                return _f
    except Exception:
        pass
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


def leer(sql, params=None):
    """DataFrame leído SIN caché. Para lo que se acaba de escribir: la caché de
    `cat()` puede estar vieja y la pantalla mostraría el estado anterior — que fue
    justo lo que pasó con los tickets de exportación. Devuelve None si no pudo."""
    cf = _conn()
    if cf is None:
        return None
    try:
        import pandas as _pd
        with cf() as conn:
            return _pd.read_sql_query(sql, conn, params=params)
    except Exception as e:
        registrar_error("EXCEPCION", "lectura sin caché falló: %s" % e,
                        accion="guardado.leer", detalle={"sql": str(sql)[:300]})
        return None


# ------------------------------------------------------------------ registro de errores
_SQL_ERR = (
    "INSERT INTO produccion.log_error_app "
    "(tipo, pantalla, accion, id_usuario, usuario, mensaje, detalle, traceback) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)")


def registrar_error(tipo, mensaje, accion=None, pantalla=None, detalle=None,
                    con_traceback=False):
    """Deja el error en produccion.log_error_app. NUNCA levanta ni frena al usuario.

    Usa una conexión propia con autocommit: tiene que poder escribir aunque la
    transacción del usuario se haya caído (si compartiera la transacción, el
    rollback se llevaría también el registro del error — es lo que pasa con
    log_doble_carga)."""
    try:
        import json as _json
        import traceback as _tb
        from etl.db import db_connect as _dbc
        _tbtxt = _tb.format_exc() if con_traceback else None
        if _tbtxt and "NoneType: None" in _tbtxt:
            _tbtxt = None
        _det = _json.dumps(detalle or {}, default=str)[:20000]
        conn = _dbc()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(_SQL_ERR, (
                    str(tipo)[:40],
                    (pantalla or _CTX.get("pantalla") or None),
                    (accion or None),
                    _CTX.get("id_usuario"),
                    (_CTX.get("usuario") or None),
                    str(mensaje)[:4000],
                    _det,
                    _tbtxt))
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ recibo
def anotar(clave, ok, titulo, detalle="", verificado="", error=""):
    """Deja el recibo listo para mostrarse en el próximo dibujado de la pantalla."""
    st.session_state[_PREFIJO + str(clave)] = {
        "ok": bool(ok), "titulo": str(titulo or ""), "detalle": str(detalle or ""),
        "verificado": str(verificado or ""), "error": str(error or ""),
        "ts": time.time(),
        "hora": _hora(),
    }
    # Todo recibo en rojo es una traba que vio un usuario: queda registrada sola.
    if not ok:
        registrar_error("TRABA", str(titulo or "")[:400], accion=str(clave),
                        detalle={"detalle": str(detalle or ""), "error": str(error or "")},
                        con_traceback=True)


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

    # 1b) cada st.error / st.exception que ve un usuario queda registrado solo
    _err = getattr(st, "error", None)
    if _err is not None and not getattr(_err, "_gdo", False):
        def _w_error(*a, **k):
            try:
                if a:
                    registrar_error("EXCEPCION", str(a[0])[:2000], accion="st.error",
                                    con_traceback=True)
            except Exception:
                pass
            return _err(*a, **k)
        _w_error._gdo = True
        try:
            st.error = _w_error
        except Exception:
            pass

    _exc = getattr(st, "exception", None)
    if _exc is not None and not getattr(_exc, "_gdo", False):
        def _w_exc(*a, **k):
            try:
                if a:
                    registrar_error("EXCEPCION", "%s: %s" % (type(a[0]).__name__, a[0]),
                                    accion="st.exception", con_traceback=True)
            except Exception:
                pass
            return _exc(*a, **k)
        _w_exc._gdo = True
        try:
            st.exception = _w_exc
        except Exception:
            pass

    # 1c) excepciones NO atrapadas (el traceback rojo de Streamlit). Hasta ahora
    # sólo se registraban los st.error / st.exception explícitos; un botón sin
    # try/except que reventaba (recuperación, SOL-0053) mostraba el rojo de
    # Streamlit y no dejaba rastro en log_error_app. Se envuelve el handler que
    # usan el script principal y los fragments: registra y después muestra igual.
    try:
        from streamlit import error_util as _eu
        _orig_h = getattr(_eu, "handle_uncaught_app_exception", None)
        if _orig_h is not None and not getattr(_orig_h, "_gdo", False):
            def _w_uncaught(ex):
                try:
                    import traceback as _tb
                    _tbtxt = "".join(_tb.format_exception(type(ex), ex, ex.__traceback__))[-8000:]
                    registrar_error("EXCEPCION", "%s: %s" % (type(ex).__name__, ex),
                                    accion="uncaught", detalle={"traceback": _tbtxt})
                except Exception:
                    pass
                return _orig_h(ex)
            _w_uncaught._gdo = True
            _eu.handle_uncaught_app_exception = _w_uncaught
            # los módulos que importaron el nombre directamente
            for _modname in ("streamlit.runtime.scriptrunner.exec_code",
                             "streamlit.runtime.scriptrunner.script_runner",
                             "streamlit.runtime.fragment"):
                try:
                    import importlib as _il
                    _m = _il.import_module(_modname)
                    if getattr(_m, "handle_uncaught_app_exception", None) is _orig_h:
                        _m.handle_uncaught_app_exception = _w_uncaught
                except Exception:
                    pass
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
                                      "ts": time.time(), "hora": _hora()}
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


# ------------------------------------------------------------------ aviso de etapa
def aviso_etapa(id_batch, desde, hasta, extra=""):
    """Texto Único para todo cambio de etapa de una reacción, verificado contra la base.

    Planta pidió que SIEMPRE se avise el fin de una etapa y el pase a la siguiente.
    Se relee fact_batch_proceso sin caché: si la base quedó en otro estado, el
    cartel lo dice en vez de festejar. Va dentro de st.success(): guardado.instalar()
    lo reenvía después del rerun, así que el operario lo ve."""
    r = fila("SELECT identificador_unidad, estado FROM produccion.fact_batch_proceso "
             "WHERE id_batch=%s", (int(id_batch),))
    ident = (r[0] if r and r[0] else None) or ("#%d" % int(id_batch))
    est = str(r[1]) if r and r[1] is not None else None
    txt = "✅ **%s** · etapa **%s** TERMINADA → ahora en **%s** (%s hs)" % (ident, desde, hasta, _hora()[:5])
    if est is None:
        txt += " · no se pudo releer la base para confirmarlo"
    elif est.upper() == str(hasta).upper():
        txt += " · confirmado en la base"
    else:
        txt += " · ⚠️ la base quedó en **%s**: avisá a sistemas" % est
    if extra:
        txt += " · " + extra
    return txt
