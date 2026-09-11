# -*- coding: utf-8 -*-
"""Home de un sector SIN tanques (Fase 5): Sólidos, Disp. Final Sólidos, NFU, Compost.

Antes eran "Próximamente": no había ninguna tabla donde vivieran. Ahora llevan un
ledger simple (produccion.fact_stock_sector: ENTRADA / SALIDA / AJUSTE en kg por
producto) que alimenta la cuenta corriente, el KPI de sólidos del área y la
actividad del sector. La pantalla es a propósito mínima: saldos, una carga de
tres campos y los últimos movimientos.
"""

from datetime import date

import pandas as pd
import streamlit as st

from . import state as _st
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _i, _leer_kpis, _rerun_fragment
from .sectores import sector_por_codigo
from .stock_cc import invalidar as _inv_cc

TIPOS = {"ENTRADA": "⬇️ Entrada", "SALIDA": "⬆️ Salida", "AJUSTE": "🛠️ Ajuste (± kg)"}
_OTRO = "Otro (escribir)…"


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _saldos(_cf, codigo):
    try:
        with _cf() as conn:
            return pd.read_sql_query("SELECT producto, saldo_kg, movimientos, ultimo_mov FROM produccion.v_stock_sector_saldo "
                                     "WHERE sector_nav = %s ORDER BY saldo_kg DESC", conn, params=(codigo,))
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _ultimos(_cf, codigo, n=30):
    sql = ("SELECT m.id_mov, m.fecha, m.producto, m.tipo, m.kg, m.ticket, m.contraparte, m.observacion, "
           "u.nombre_full AS usuario, m.creado_en FROM produccion.fact_stock_sector m "
           "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = m.id_usuario "
           "WHERE m.sector_nav = %s AND NOT m.anulado ORDER BY m.fecha DESC, m.id_mov DESC LIMIT %s")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(codigo, int(n)))
        df["kg"] = pd.to_numeric(df["kg"], errors="coerce").astype(float)
        return df
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _productos_solidos(_cf):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT codigo_producto FROM produccion.dim_producto WHERE activo "
                                   "AND COALESCE(es_liquido, false) = false ORDER BY codigo_producto", conn)
        return df["codigo_producto"].tolist()
    except Exception:
        return []


@st.cache_data(ttl=_TTL, show_spinner=False)
def _actividad(_cf, codigo):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT eventos_hoy, personal_presente FROM produccion.v_sector_actividad_hoy WHERE codigo = %s",
                                   conn, params=(codigo,))
        return df.iloc[0].to_dict() if not df.empty else {}
    except Exception:
        return {}


def _grabar(conectar, USR, codigo, producto, tipo, kg, fecha, ticket, contraparte, obs):
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO produccion.fact_stock_sector (sector_nav, producto, tipo, kg, fecha, ticket, contraparte, "
                        "observacion, id_usuario) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_mov",
                        (codigo, producto, tipo, kg, fecha, ticket or None, contraparte or None, obs or None, int(USR["id_usuario"])))
            id_mov = cur.fetchone()[0]
            audit.log("I", "fact_stock_sector", int(id_mov),
                      dict(sector=codigo, producto=producto, tipo=tipo, kg=str(kg), fecha=str(fecha)))
    return id_mov


def _anular(conectar, USR, id_mov):
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.fact_stock_sector SET anulado = true WHERE id_mov = %s AND NOT anulado", (int(id_mov),))
        audit.log("U", "fact_stock_sector", int(id_mov), {"anulado": "true"})


def _invalidar():
    _saldos.clear(); _ultimos.clear(); _actividad.clear(); _leer_kpis.clear(); _inv_cc()


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _panel(ctx, sec):
    cf, USR, conectar = ctx["conn_factory"], ctx["USR"], ctx.get("conectar")
    cod = sec["codigo"]
    msg = st.session_state.pop(f"nav_ss_msg_{cod}", None)
    if msg:
        st.success(msg)
    saldos, act = _saldos(cf, cod), _actividad(cf, cod)
    if saldos is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    total = float(saldos["saldo_kg"].astype(float).sum()) if not saldos.empty else 0.0
    top = saldos.iloc[0] if not saldos.empty else None
    c1 = _kpi("Stock del sector", f"{_n(total / 1000, 1)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              (f"{len(saldos)} productos · mayor: {top['producto']} {_n(top['saldo_kg'])} kg" if top is not None
               else "sin movimientos cargados todavía"), "ok" if total > 0 else "")
    c2 = _kpi("Movimientos hoy", str(_i(act.get("eventos_hoy"))), "cargados en este sector", "ok" if _i(act.get("eventos_hoy")) else "")
    c3 = _kpi("Personas trabajando", str(_i(act.get("personal_presente"))),
              "registraron trabajo en este sector" if _i(act.get("personal_presente")) else "nadie registró trabajo acá todavía", "")
    ult = saldos["ultimo_mov"].max() if not saldos.empty else None
    c4 = _kpi("Último movimiento", (pd.to_datetime(ult).strftime("%d/%m") if ult is not None and not pd.isna(ult) else "—"),
              "fecha del último ingreso / egreso / ajuste", "")
    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}{c4}</div>', unsafe_allow_html=True)

    izq, der = st.columns([1.1, 1.6])
    with izq:
        st.markdown('<div class="section-title">Cargar movimiento</div>', unsafe_allow_html=True)
        if conectar is None or not ctx["puede_seccion"]("STOCK"):
            st.caption("Sin permiso de Stock: sólo consulta.")
        else:
            existentes = saldos["producto"].tolist() if not saldos.empty else []
            base = existentes + [p for p in _productos_solidos(cf) if p not in existentes]
            with st.form(f"nav_ss_form_{cod}", clear_on_submit=True, border=True):
                tipo = st.radio("Tipo", list(TIPOS), format_func=TIPOS.get, horizontal=True, key=f"nav_ss_tipo_{cod}")
                psel = st.selectbox("Producto", base + [_OTRO], key=f"nav_ss_prod_{cod}")
                potro = st.text_input("Producto (si es otro)", key=f"nav_ss_potro_{cod}", placeholder="p. ej. BORRA-SOLIDA")
                kg = st.number_input("Kilos", min_value=-1e7, max_value=1e7, value=0.0, step=100.0, key=f"nav_ss_kg_{cod}",
                                     help="Entrada y salida: siempre positivo. Ajuste: con signo (negativo resta).")
                fecha = st.date_input("Fecha", value=date.today(), key=f"nav_ss_fecha_{cod}")
                ticket = st.text_input("Ticket / remito", key=f"nav_ss_tk_{cod}")
                contra = st.text_input("Cliente / proveedor", key=f"nav_ss_cp_{cod}")
                obs = st.text_input("Observación", key=f"nav_ss_obs_{cod}")
                ok = st.form_submit_button("💾 Guardar movimiento", type="primary", use_container_width=True)
            if ok:
                producto = (potro or "").strip().upper() if psel == _OTRO else psel
                err = None
                if not producto:
                    err = "Falta el producto."
                elif tipo in ("ENTRADA", "SALIDA") and kg <= 0:
                    err = "Los kilos de una entrada o salida tienen que ser mayores a cero."
                elif tipo == "AJUSTE" and kg == 0:
                    err = "Un ajuste de 0 kg no cambia nada."
                elif fecha > date.today():
                    err = "La fecha no puede ser futura."
                if err:
                    st.error(err)
                else:
                    try:
                        _grabar(conectar, USR, cod, producto, tipo, float(kg), fecha, ticket.strip(), contra.strip(), obs.strip())
                        _invalidar()
                        st.session_state[f"nav_ss_msg_{cod}"] = f"{TIPOS[tipo]} de {_n(kg)} kg de {producto} guardada."
                        _rerun_fragment()
                    except Exception as e:
                        st.error(f"No se pudo guardar: {e}")
    with der:
        st.markdown('<div class="section-title">Saldos y últimos movimientos</div>', unsafe_allow_html=True)
        if saldos.empty:
            st.info("Todavía no hay movimientos en este sector. Cargá la primera entrada a la izquierda.")
        else:
            st.dataframe(pd.DataFrame({"PRODUCTO": saldos["producto"], "SALDO KG": saldos["saldo_kg"].astype(float).map(lambda x: f"{x:,.0f}"),
                                       "MOV.": saldos["movimientos"], "ÚLTIMO": saldos["ultimo_mov"].map(lambda d: pd.to_datetime(d).strftime("%d/%m/%Y"))}),
                         hide_index=True, use_container_width=True)
        ult_df = _ultimos(cf, cod)
        if ult_df is not None and not ult_df.empty:
            tabla = pd.DataFrame({
                "FECHA": ult_df["fecha"].map(lambda d: pd.to_datetime(d).strftime("%d/%m/%Y")),
                "TIPO": ult_df["tipo"], "PRODUCTO": ult_df["producto"],
                "KG": ult_df["kg"].map(lambda x: f"{x:,.0f}"),
                "TICKET": ult_df["ticket"].fillna(""), "CLIENTE / PROVEEDOR": ult_df["contraparte"].fillna(""),
                "OBS.": ult_df["observacion"].fillna(""), "USUARIO": ult_df["usuario"].fillna(""),
            })
            st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(420, 60 + 35 * len(tabla)))
            if conectar is not None and USR.get("rol") in ("ADMIN", "SUPERVISOR"):
                with st.expander("Anular un movimiento", expanded=False):
                    opc = {int(r.id_mov): f"#{int(r.id_mov)} · {pd.to_datetime(r.fecha).strftime('%d/%m')} · {r.tipo} · {r.producto} · {r.kg:,.0f} kg"
                           for r in ult_df.itertuples()}
                    sel = st.selectbox("Movimiento", list(opc), format_func=opc.get, key=f"nav_ss_anul_sel_{cod}")
                    if st.button("🗑️ Anular", key=f"nav_ss_anul_btn_{cod}"):
                        try:
                            _anular(conectar, USR, sel); _invalidar(); _rerun_fragment()
                        except Exception as e:
                            st.error(f"No se pudo anular: {e}")


def _ir_cc(sec):
    def _cb():
        _st.set_nav("PRODUCCION", sec["codigo"], "STOCK", rerun=False)
        st.session_state.section = None
    return _cb


def render_sector_simple(ctx, sec):
    from .portada import _hero, _pie_soporte
    USR = ctx["USR"]
    _hero(f"SECTOR {sec['nombre_ui'].upper()}", USR, icono=sec["icono"],
          sub=(sec.get("descripcion") or "") + " Stock del sector en kilos: entradas, salidas y ajustes.")
    _panel(ctx, sec)
    st.button("📈 Cuenta corriente por producto", key=f"nav_ss_cc_{sec['codigo']}", on_click=_ir_cc(sec))
    st.caption("Sector sin tanques: el stock se lleva a mano en este ledger. Cada carga queda auditada con usuario y fecha; "
               "los saldos suman al indicador de sólidos del área.")
    _pie_soporte(ctx)
    return True
