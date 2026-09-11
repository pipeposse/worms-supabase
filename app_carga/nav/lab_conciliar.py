# -*- coding: utf-8 -*-
"""Conciliación de laboratorio (Fase 7) — lo pedido contra lo entregado.

El laboratorio carga cientos de análisis por mes en ``lab_evaluaciones`` y
producción pide muestras en ``fact_ticket_lab``. Nunca se miraban: la cola de
pendientes sólo crecía y llegó a 102 pedidos, de los que 40 ya tenían respuesta.

``produccion.v_ticket_lab_conciliado`` ata cada pedido con el análisis que lo
responde y dice con qué confianza:

    ALTA   el lab escribió el código del ticket (F40) o es el mismo ticket de balanza
    MEDIA  el lab midió ese tanque en la ventana del pedido, y el producto coincide
    BAJA   midió el tanque, pero el producto no coincide  → lo decide una persona

El cron cierra ALTA y MEDIA cada 15 minutos. Esta pantalla es para lo demás: las
BAJA, que alguien confirma o descarta, y las que no tienen ningún respaldo, que son
las muestras que de verdad faltan.
"""

import pandas as pd
import streamlit as st

from .kpis import _FRAGMENT, _TTL, _kpi, _rerun_fragment

_COLS = ("id_ticket, ticket_lab, op, rol, fuente, producto, tanque, creado_en, dias_desde_pedido, "
         "id_lab, via, fecha_lab, producto_lab, calidad_final_lab, confianza, horas_respuesta")


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _propuestas(_cf):
    """Pedidos con un análisis probable pero de confianza BAJA: los confirma una persona."""
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                f"SELECT {_COLS} FROM produccion.v_ticket_lab_conciliado "
                "WHERE estado_guardado = 'PENDIENTE' AND tiene_respaldo AND confianza = 'BAJA' "
                "ORDER BY creado_en DESC", conn)
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _faltantes(_cf):
    """Pedidos sin ningún análisis que los respalde: las muestras que realmente faltan."""
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                f"SELECT {_COLS} FROM produccion.v_ticket_lab_conciliado "
                "WHERE estado_guardado = 'PENDIENTE' AND NOT tiene_respaldo "
                "ORDER BY dias_desde_pedido DESC", conn)
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _resumen(_cf):
    try:
        with _cf() as conn:
            df = pd.read_sql_query(
                "SELECT count(*) FILTER (WHERE estado_guardado = 'EVALUADO') AS cerrados, "
                "       count(*) FILTER (WHERE estado_guardado = 'PENDIENTE' AND NOT tiene_respaldo) AS faltan, "
                "       count(*) FILTER (WHERE estado_guardado = 'PENDIENTE' AND tiene_respaldo AND confianza = 'BAJA') AS proponer, "
                "       round(avg(horas_respuesta) FILTER (WHERE horas_respuesta > 0)::numeric, 1) AS horas_prom, "
                "       max(dias_desde_pedido) FILTER (WHERE estado_guardado = 'PENDIENTE' AND NOT tiene_respaldo) AS mas_vieja "
                "FROM produccion.v_ticket_lab_conciliado", conn)
        return df.iloc[0].to_dict() if not df.empty else {}
    except Exception:
        return {}


def _confirmar(conectar, USR, id_ticket, id_lab, fecha_lab):
    """Esta evaluación sí es de esta muestra: cierra el pedido."""
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.fact_ticket_lab "
                        "SET estado = 'EVALUADO', evaluado_en = %s, id_lab_evaluacion = %s, "
                        "    conciliado_via = 'MANUAL', conciliado_en = now(), id_usuario_lab = %s "
                        "WHERE id_ticket = %s AND estado = 'PENDIENTE'",
                        (fecha_lab, int(id_lab), int(USR["id_usuario"]), int(id_ticket)))
        audit.log("U", "fact_ticket_lab", int(id_ticket),
                  {"estado": "EVALUADO", "via": "MANUAL", "id_lab_evaluacion": str(id_lab)})


def _descartar(conectar, USR, id_ticket):
    """No corresponde: el pedido pasa a contarse entre las muestras que faltan."""
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.fact_ticket_lab SET conciliacion_descartada = true "
                        "WHERE id_ticket = %s", (int(id_ticket),))
        audit.log("U", "fact_ticket_lab", int(id_ticket), {"conciliacion_descartada": "true"})


def invalidar():
    _propuestas.clear(); _faltantes.clear(); _resumen.clear()
    try:
        from .hoy import invalidar as _inv_hoy
        _inv_hoy()
    except Exception:
        pass


# ------------------------------------------------------------------ pantalla
def _fecha(x, fmt="%d/%m %H:%M"):
    return "" if x is None or pd.isna(x) else pd.to_datetime(x).strftime(fmt)


@_FRAGMENT
def _panel(ctx):
    cf, USR, conectar = ctx["conn_factory"], ctx["USR"], ctx.get("conectar")
    r = _resumen(cf)
    if not r:
        st.caption("Sin conexión a la base en este momento.")
        return

    faltan, proponer = int(r.get("faltan") or 0), int(r.get("proponer") or 0)
    k1 = _kpi("Pedidos cerrados", str(int(r.get("cerrados") or 0)), "atados a su análisis", "ok")
    k2 = _kpi("Muestras que faltan", str(faltan),
              (f"la más vieja hace {int(r['mas_vieja'])} días" if r.get("mas_vieja") else "ninguna"),
              "bad" if faltan else "ok")
    k3 = _kpi("Para confirmar", str(proponer), "análisis probables, los decide una persona", "warn" if proponer else "")
    hp = r.get("horas_prom")
    k4 = _kpi("Respuesta del lab", (f"{float(hp):.0f}<span style='font-size:1rem;font-weight:700;'> h</span>" if hp else "—"),
              "promedio entre el pedido y el análisis", "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    msg = st.session_state.pop("nav_lc_msg", None)
    if msg:
        st.success(msg)

    # ---- propuestas por confirmar
    st.markdown('<div class="section-title">Análisis probables · confirmar o descartar</div>', unsafe_allow_html=True)
    prop = _propuestas(cf)
    if prop is None:
        st.caption("Sin conexión a la base en este momento.")
    elif prop.empty:
        st.success("No queda ninguna propuesta por revisar. 👌")
    else:
        st.caption("El laboratorio midió ese tanque cerca del pedido, pero informó otro producto. "
                   "Si el análisis corresponde a la muestra, confirmalo; si no, descartalo y el pedido "
                   "pasa a contarse entre las muestras que faltan.")
        puede = conectar is not None and ctx["puede_seccion"]("LAB")
        for _, t in prop.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([5, 1.1, 1.1])
                with c1:
                    st.markdown(
                        f"<div style='font-weight:700'>{t['ticket_lab']} · {t['producto'] or '—'}"
                        f"{' · ' + str(t['op']) if t['op'] else ''}</div>"
                        f"<div style='opacity:.75;font-size:.87rem;margin-top:2px'>"
                        f"Pedido {_fecha(t['creado_en'])} · {t['fuente']}"
                        f"{' · ' + str(t['tanque']) if t['tanque'] else ''} — "
                        f"el lab informó <b>{t['producto_lab'] or '—'}</b>"
                        f"{' (' + str(t['calidad_final_lab']) + ')' if t['calidad_final_lab'] else ''} "
                        f"el {_fecha(t['fecha_lab'])}</div>", unsafe_allow_html=True)
                if puede:
                    if c2.button("Es esta", key=f"nav_lc_ok_{t['id_ticket']}", type="primary", use_container_width=True):
                        try:
                            _confirmar(conectar, USR, t["id_ticket"], t["id_lab"], t["fecha_lab"])
                            invalidar()
                            st.session_state["nav_lc_msg"] = f"{t['ticket_lab']} cerrado con el análisis del {_fecha(t['fecha_lab'])}."
                            _rerun_fragment()
                        except Exception as e:
                            st.error(f"No se pudo confirmar: {e}")
                    if c3.button("No corresponde", key=f"nav_lc_no_{t['id_ticket']}", use_container_width=True):
                        try:
                            _descartar(conectar, USR, t["id_ticket"])
                            invalidar()
                            st.session_state["nav_lc_msg"] = f"{t['ticket_lab']} queda como muestra pendiente."
                            _rerun_fragment()
                        except Exception as e:
                            st.error(f"No se pudo descartar: {e}")
                else:
                    c2.caption("Sin permiso de Laboratorio")

    # ---- lo que realmente falta
    st.markdown('<div class="section-title">Muestras sin ningún análisis</div>', unsafe_allow_html=True)
    falt = _faltantes(cf)
    if falt is None:
        st.caption("Sin conexión a la base en este momento.")
    elif falt.empty:
        st.success("Todos los pedidos tienen su análisis. 👌")
    else:
        tabla = pd.DataFrame({
            "TICKET": falt["ticket_lab"],
            "OP": falt["op"].fillna(""),
            "QUÉ": falt["rol"].fillna("") + " · " + falt["producto"].fillna("—"),
            "DE DÓNDE": falt["fuente"].fillna("") + falt["tanque"].map(lambda t: f" · {t}" if isinstance(t, str) and t else ""),
            "PEDIDO": falt["creado_en"].map(lambda d: _fecha(d, "%d/%m/%Y")),
            "ESPERANDO": falt["dias_desde_pedido"].map(lambda d: f"{float(d):.0f} días"),
        })
        st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(460, 60 + 35 * len(tabla)))
        st.caption("Esta es la cola real del laboratorio. Un pedido con muchos días acá es una muestra que "
                   "nunca se tomó o que se analizó sin dejar rastro: los dos casos hay que hablarlos, no esperarlos.")


def render_lab_conciliar(ctx):
    from .portada import _hero, _pie_soporte
    _hero("LABORATORIO · PEDIDOS Y RESULTADOS", ctx["USR"], icono="🧪",
          sub="Lo que producción pidió contra lo que el laboratorio entregó. "
              "Lo que se puede atar sin ambigüedad se cierra solo cada 15 minutos.")
    _panel(ctx)
    _pie_soporte(ctx)
