# -*- coding: utf-8 -*-
"""worms_supabase / app_carga / recuperacion_section.py

Recuperación de Ácidos Grasos (piletas).

El proceso real: la cuadrilla arranca 10-12 h (barreras + posicionar camiones),
extrae de las piletas con camión de vacío, laboratorio muestrea cada camión
(en general AG-C, a veces AG-D), se pesa en portería, se descarga en la zona de
reactores (Tanque 4 de acopio y tanques de materia prima 3 y 4) y el ticket de
pesada es el comprobante con el que se controla el stock recuperado. Trabajan
hasta las 20 h y las pesadas se cierran ~18 h: al cierre de la jornada tiene
que estar TODO pesado y clasificado.

El problema que resuelve esta sección: en portería la recuperación sale como
MOVIMIENTO INTERNO / PILETAS→PILETAS, igual que cualquier movimiento interno,
así que el stock recuperado no se podía medir. Acá:

1.  La bandeja detecta sola los candidatos (mov. interno + producto AG +
    piletas + pesada cerrada) y los muestra con su análisis de lab precargado.
2.  El operario CONFIRMA cada ticket: calidad final (AG-C/AG-D) y destino real
    (tanque, plataforma u otro). O lo marca "no es recuperación" y no molesta más.
3.  Confirmar con tanque destino impacta el stock del tanque (ponderando los
    parámetros como Asignación AFE) y ANULA el movimiento automático que el
    lab_sync le hubiera acreditado — siempre acredita Tanque 4, aunque el
    camión haya ido a plataforma, que era la causa del stock mal medido.
4.  La jornada diaria con apertura/cierre garantiza que nada quede sin
    clasificar cuando la cuadrilla se va.

Intervienen: Producción en planta (clasifica), Laboratorio (la muestra por
ticket ya llega sola desde procesos_lab) y Centro de Planificación (misma
sección + KPIs, contexto PLANIFICACION).
"""

import json
from datetime import date, datetime

import pandas as pd
import streamlit as st

DIAS_BANDEJA = 21          # cuántos días hacia atrás busca candidatos la bandeja
DENS_DEFAULT = 0.92        # densidad AG si no hay dato de lab
VACIO_KG = 300.0           # menos que esto = tanque vacío: toma los parámetros del ticket
CALIDADES = ("AG-C", "AG-D", "AG-B", "AG-A")   # C/D es lo normal; el lab a veces da B
SIN_TANQUE = (("PLATAFORMA", "🏗️ Plataforma (sin tanque)"),
              ("OTRO", "📍 Otro destino (sin tanque)"))
# orígenes de movimientos automáticos que la confirmación reemplaza
_ORIG_AUTO = ("lab_sync", "sistema", "recuperacion_ag")


def _f(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return float(v)
    except Exception:
        return None


def _n(v, dec=0):
    try:
        return ("{:,.%df}" % dec).format(float(v)).replace(",", ".")
    except Exception:
        return str(v)


# ------------------------------------------------------------------ datos

def _jornada_hoy(cat):
    df = cat("SELECT id_jornada, fecha, hora_inicio, hora_fin, responsables, estado, "
             "observaciones FROM produccion.fact_recuperacion_jornada WHERE fecha=%s",
             (date.today(),))
    return None if df.empty else df.iloc[0]


def _candidatos(cat):
    """Tickets de portería que 'huelen' a recuperación y todavía no fueron clasificados."""
    return cat(
        "SELECT t.transaccion, t.fecha_entrada, t.hora_e, t.hora_s, t.conductor, "
        "       t.patente_chasis, ABS(t.peso_neto) AS kg, t.producto, t.balanza, "
        "       t.observaciones, t.estado_camion, t.evaluado, t.lab_calidad, "
        "       t.lab_producto, t.lab_num_muestra, t.lab_prc_acidez, t.lab_prc_agua, "
        "       t.lab_ppm_azufre, t.lab_ppm_fosforo, t.lab_densidad "
        "FROM produccion.v_transacciones_limpias t "
        "WHERE upper(coalesce(t.cliente,'')) LIKE '%%MOVIMIENTO%%' "
        "  AND upper(coalesce(t.producto_base,'')) = 'AG' "
        "  AND (upper(coalesce(t.procedencia,'')) LIKE '%%PILETA%%' "
        "       OR upper(coalesce(t.destino_final,'')) LIKE '%%PILETA%%') "
        "  AND t.peso_neto < 0 "
        "  AND t.fecha_entrada >= current_date - %s "
        "  AND NOT EXISTS (SELECT 1 FROM produccion.fact_recuperacion_ticket r "
        "                  WHERE r.ticket = to_char(t.transaccion,'FM999999999999') "
        "                    AND NOT r.anulado) "
        "ORDER BY t.transaccion DESC",
        (DIAS_BANDEJA,))


def _tanques_destino(cat):
    """Tanques donde físicamente se descarga la recuperación (zona reactores)."""
    return cat(
        "SELECT t.id_tanque, t.nombre, t.sector, "
        "       COALESCE(s.kg_estimado, s.kg_actual, 0) AS kg_actual, "
        "       t.capacidad_litros "
        "FROM produccion.dim_tanque t "
        "LEFT JOIN produccion.vw_stock_tanque_actual s ON s.id_tanque = t.id_tanque "
        "WHERE COALESCE(t.activo,true) "
        "  AND t.sector IN ('Reactores (Acopio)','Reactores (Proceso)') "
        "ORDER BY t.sector, t.nombre")


def _producto(cat, codigo):
    df = cat("SELECT id_producto, codigo_producto, COALESCE(densidad_g_ml,%s) AS dens "
             "FROM produccion.dim_producto WHERE codigo_producto=%s",
             (DENS_DEFAULT, codigo))
    return None if df.empty else df.iloc[0]


def _historial(cat, dias=45):
    return cat(
        "SELECT r.ticket, r.fecha_ticket, r.clasificacion, r.producto, r.destino_tipo, "
        "       r.tanque_label, r.kg, r.lab_calidad, r.conductor, u.nombre AS usuario, "
        "       r.confirmado_en, r.observaciones, r.id_rec, r.id_mov_stock "
        "FROM produccion.fact_recuperacion_ticket r "
        "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = r.id_usuario "
        "WHERE NOT r.anulado AND r.fecha_ticket >= current_date - %s "
        "ORDER BY r.ticket::bigint DESC", (dias,))


# ------------------------------------------------------------------ escritura

def _abrir_jornada(conectar, USR, responsables, obs):
    uid = int(USR.get("id_usuario") or 0)
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO produccion.fact_recuperacion_jornada "
                "(fecha, hora_inicio, responsables, estado, observaciones, creado_por) "
                "VALUES (%s, %s, %s, 'ABIERTA', %s, %s) "
                "ON CONFLICT (fecha) DO UPDATE SET estado='ABIERTA', "
                "  responsables=EXCLUDED.responsables, actualizado_en=now() "
                "RETURNING id_jornada",
                (date.today(), datetime.now().time().replace(microsecond=0),
                 (responsables or None), (obs or None), uid))
            idj = int(cur.fetchone()[0])
        audit.log("A", "fact_recuperacion_jornada", idj, {"responsables": responsables})
    return idj


def _cerrar_jornada(conectar, USR, id_jornada, obs, pendientes):
    uid = int(USR.get("id_usuario") or 0)
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE produccion.fact_recuperacion_jornada "
                "SET estado='CERRADA', hora_fin=%s, cerrado_por=%s, cerrado_en=now(), "
                "    observaciones=COALESCE(%s, observaciones), actualizado_en=now() "
                "WHERE id_jornada=%s",
                (datetime.now().time().replace(microsecond=0), uid, (obs or None),
                 int(id_jornada)))
        audit.log("U", "fact_recuperacion_jornada", int(id_jornada),
                  {"cierre": True, "pendientes_al_cierre": int(pendientes)})


def _mezclar(tq, tk, kg_antes, kg_add):
    """Ponderado por kg, mismo criterio que Asignación AFE. Tanque vacío → ticket."""
    mapa = ("acidez_pct", "agua_pct", "densidad_g_ml", "ppm_azufre", "ppm_fosforo")
    antes, despues = {}, {}
    vacio = kg_antes < VACIO_KG
    for col in mapa:
        a, b = _f(tq.get(col)), _f(tk.get(col))
        antes[col] = a
        if vacio:
            despues[col] = b if b is not None else a
        elif b is None:
            despues[col] = a
        elif a is None:
            despues[col] = b
        else:
            despues[col] = round((a * kg_antes + b * kg_add) / (kg_antes + kg_add), 4)
    return antes, despues, vacio


def _confirmar(conectar, USR, tk, dat, clasif, prod_row, destino_tipo, tanque, obs,
               id_jornada):
    """Clasifica el ticket en una sola transacción.

    RECUPERACION con tanque: anula el movimiento automático del lab_sync (que
    acredita siempre Tanque 4, esté bien o mal), crea el movimiento real al
    tanque elegido y pondera sus parámetros con el análisis del camión.
    RECUPERACION sin tanque (plataforma/otro): anula el automático y NO crea
    ninguno — el AG salió del circuito de tanques, pero cuenta como recuperado.
    NO_RECUPERACION: sólo registra la decisión; el movimiento automático del
    lab_sync queda como está, porque el movimiento interno es genuino.
    """
    uid = int(USR.get("id_usuario") or 0)
    kg = float(dat["kg"])
    dens = _f(dat.get("lab_densidad")) or (float(prod_row["dens"]) if prod_row is not None
                                           else DENS_DEFAULT)
    lts = round(kg / dens, 1)
    id_mov = None
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.param_origen','RECUPERACION_AG',true)")

            if clasif == "RECUPERACION":
                # 1) anular los movimientos automáticos del ticket + su espejo
                cur.execute(
                    "UPDATE produccion.fact_movimiento_stock "
                    "SET anulado = true, "
                    "    observaciones = COALESCE(observaciones,'') || ' | reemplazado por Recuperación AG' "
                    "WHERE regexp_replace(COALESCE(ticket_porteria,''),'\\.0+$','') = %s "
                    "  AND COALESCE(anulado,false) = false "
                    "  AND COALESCE(origen,'') = ANY(%s) "
                    "RETURNING id_mov_stock", (tk, list(_ORIG_AUTO)))
                _viejos = [r[0] for r in cur.fetchall()]
                cur.execute(
                    "DELETE FROM produccion.fact_movimiento_tanque "
                    "WHERE observaciones LIKE %s OR id_mov_stock = ANY(%s)",
                    ("lab_sync ticket %" + tk, _viejos or [0]))
            else:
                _viejos = []

            if clasif == "RECUPERACION" and tanque is not None:
                idt = int(tanque["id_tanque"])
                idp = int(prod_row["id_producto"])

                cur.execute(
                    "SELECT COALESCE(s.kg_estimado, s.kg_actual, 0) "
                    "FROM produccion.vw_stock_tanque_actual s WHERE s.id_tanque=%s", (idt,))
                _r = cur.fetchone()
                kg_antes = float(_r[0]) if _r and _r[0] is not None else 0.0
                cur.execute(
                    "SELECT acidez_pct, agua_pct, densidad_g_ml, ppm_azufre, ppm_fosforo "
                    "FROM produccion.fact_param_tanque WHERE id_tanque=%s AND id_producto=%s",
                    (idt, idp))
                _p = cur.fetchone()
                tq = {}
                if _p:
                    tq = {"acidez_pct": _p[0], "agua_pct": _p[1], "densidad_g_ml": _p[2],
                          "ppm_azufre": _p[3], "ppm_fosforo": _p[4]}
                camion = {"acidez_pct": _f(dat.get("lab_prc_acidez")),
                          "agua_pct": _f(dat.get("lab_prc_agua")),
                          "densidad_g_ml": _f(dat.get("lab_densidad")),
                          "ppm_azufre": _f(dat.get("lab_ppm_azufre")),
                          "ppm_fosforo": _f(dat.get("lab_ppm_fosforo"))}
                antes, despues, vacio = _mezclar(tq, camion, kg_antes, kg)

                # 2) movimiento de stock real (tanque elegido por el operario)
                cur.execute(
                    "INSERT INTO produccion.fact_movimiento_stock "
                    "(momento, tipo_movimiento, rol, sentido, id_producto, producto, fuente, "
                    " id_tanque, tanque_label, ticket_porteria, cantidad, unidad, kg, litros, "
                    " id_usuario, origen, observaciones, estado_mov, id_usuario_ejecuta, ejecutado_en) "
                    "VALUES (%s,'ENTRADA','MP',1,%s,%s,'PORTERIA',%s,%s,%s,%s,'KG',%s,%s,%s,"
                    " 'recuperacion_ag',%s,'EJECUTADO',%s,now()) RETURNING id_mov_stock",
                    (dat.get("fecha_entrada"), idp, str(prod_row["codigo_producto"]),
                     idt, str(tanque["nombre"]), tk, kg, kg, lts, uid,
                     "Recuperación AG ticket %s" % tk, uid))
                id_mov = cur.fetchone()[0]

                # 3) espejo de tanque
                cur.execute(
                    "INSERT INTO produccion.fact_movimiento_tanque "
                    "(id_tanque, id_producto, tipo, litros, kg, ts, id_usuario, origen, "
                    " observaciones, id_mov_stock) "
                    "VALUES (%s,%s,'IN',%s,%s,%s,%s,'RECUPERACION_AG',%s,%s)",
                    (idt, idp, lts, kg, dat.get("fecha_entrada"), uid,
                     "Recuperación AG ticket %s" % tk, id_mov))

                # 4) parámetros del tanque (ponderado con el análisis del camión)
                if any(v is not None for v in camion.values()):
                    extra = json.dumps({"recuperacion_ticket": tk, "recuperacion_kg": kg,
                                        "recuperacion_kg_antes": round(kg_antes, 1),
                                        "recuperacion_vacio": vacio,
                                        "recuperacion_mov": id_mov}, default=str)
                    cur.execute(
                        "INSERT INTO produccion.fact_param_tanque "
                        "(id_tanque, id_producto, evaluado, ultima_evaluacion_ts, "
                        " acidez_pct, agua_pct, densidad_g_ml, ppm_azufre, ppm_fosforo, "
                        " parametros_extra, actualizado_en) "
                        "VALUES (%s,%s,true,%s,%s,%s,%s,%s,%s,%s::jsonb,now()) "
                        "ON CONFLICT (id_tanque, id_producto) DO UPDATE SET "
                        " evaluado=true, ultima_evaluacion_ts=EXCLUDED.ultima_evaluacion_ts, "
                        " acidez_pct=EXCLUDED.acidez_pct, agua_pct=EXCLUDED.agua_pct, "
                        " densidad_g_ml=EXCLUDED.densidad_g_ml, ppm_azufre=EXCLUDED.ppm_azufre, "
                        " ppm_fosforo=EXCLUDED.ppm_fosforo, "
                        " parametros_extra = COALESCE(produccion.fact_param_tanque.parametros_extra,"
                        "'{}'::jsonb) || EXCLUDED.parametros_extra, "
                        " actualizado_en=now()",
                        (idt, idp, dat.get("fecha_entrada"),
                         despues.get("acidez_pct"), despues.get("agua_pct"),
                         despues.get("densidad_g_ml"), despues.get("ppm_azufre"),
                         despues.get("ppm_fosforo"), extra))

            # 5) registro de la clasificación (fuente de verdad del stock recuperado)
            cur.execute(
                "INSERT INTO produccion.fact_recuperacion_ticket "
                "(ticket, id_jornada, fecha_ticket, kg, clasificacion, id_producto, producto, "
                " destino_tipo, id_tanque, tanque_label, id_mov_stock, lab_num_muestra, "
                " lab_calidad, conductor, patente, id_usuario, observaciones) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (ticket) DO UPDATE SET "
                " id_jornada=EXCLUDED.id_jornada, fecha_ticket=EXCLUDED.fecha_ticket, "
                " kg=EXCLUDED.kg, clasificacion=EXCLUDED.clasificacion, "
                " id_producto=EXCLUDED.id_producto, producto=EXCLUDED.producto, "
                " destino_tipo=EXCLUDED.destino_tipo, id_tanque=EXCLUDED.id_tanque, "
                " tanque_label=EXCLUDED.tanque_label, id_mov_stock=EXCLUDED.id_mov_stock, "
                " lab_num_muestra=EXCLUDED.lab_num_muestra, lab_calidad=EXCLUDED.lab_calidad, "
                " id_usuario=EXCLUDED.id_usuario, observaciones=EXCLUDED.observaciones, "
                " anulado=false, actualizado_en=now() "
                "RETURNING id_rec",
                (tk, (int(id_jornada) if id_jornada else None), dat.get("fecha_entrada"),
                 kg, clasif,
                 (int(prod_row["id_producto"]) if (clasif == "RECUPERACION" and prod_row is not None) else None),
                 (str(prod_row["codigo_producto"]) if (clasif == "RECUPERACION" and prod_row is not None) else None),
                 (destino_tipo if clasif == "RECUPERACION" else None),
                 (int(tanque["id_tanque"]) if tanque is not None else None),
                 (str(tanque["nombre"]) if tanque is not None else None),
                 id_mov, str(dat.get("lab_num_muestra") or "") or None,
                 str(dat.get("lab_calidad") or "") or None,
                 str(dat.get("conductor") or "") or None,
                 str(dat.get("patente_chasis") or "") or None, uid, (obs or None)))
            id_rec = int(cur.fetchone()[0])
        audit.log("U", "fact_recuperacion_ticket", id_rec,
                  {"ticket": tk, "clasificacion": clasif, "destino": destino_tipo,
                   "kg": kg, "mov": id_mov, "auto_anulados": _viejos})
    return id_rec


def _anular(conectar, USR, row):
    """Deshace la clasificación: anula el movimiento creado y libera el ticket."""
    uid = int(USR.get("id_usuario") or 0)
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            if row.get("id_mov_stock") is not None and not pd.isna(row.get("id_mov_stock")):
                _im = int(row["id_mov_stock"])
                cur.execute("UPDATE produccion.fact_movimiento_stock SET anulado=true, "
                            "observaciones=COALESCE(observaciones,'') || ' | anulado Recuperación AG' "
                            "WHERE id_mov_stock=%s", (_im,))
                cur.execute("DELETE FROM produccion.fact_movimiento_tanque WHERE id_mov_stock=%s",
                            (_im,))
            cur.execute("UPDATE produccion.fact_recuperacion_ticket SET anulado=true, "
                        "actualizado_en=now() WHERE id_rec=%s", (int(row["id_rec"]),))
        audit.log("X", "fact_recuperacion_ticket", int(row["id_rec"]),
                  {"ticket": str(row.get("ticket"))})


# ------------------------------------------------------------------ UI

def _kpis(cat):
    k = cat(
        "SELECT COALESCE(SUM(kg) FILTER (WHERE fecha_ticket = current_date),0) AS hoy, "
        "       COALESCE(SUM(kg) FILTER (WHERE fecha_ticket >= date_trunc('week', current_date)::date),0) AS semana, "
        "       COALESCE(SUM(kg) FILTER (WHERE fecha_ticket >= date_trunc('month', current_date)::date),0) AS mes, "
        "       COALESCE(SUM(kg) FILTER (WHERE producto='AG-C' AND fecha_ticket >= date_trunc('month', current_date)::date),0) AS mes_c, "
        "       COALESCE(SUM(kg) FILTER (WHERE producto='AG-D' AND fecha_ticket >= date_trunc('month', current_date)::date),0) AS mes_d "
        "FROM produccion.fact_recuperacion_ticket "
        "WHERE clasificacion='RECUPERACION' AND NOT anulado")
    r = k.iloc[0] if not k.empty else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("♻️ Hoy", "%s kg" % _n(r["hoy"] if r is not None else 0))
    c2.metric("Semana", "%s kg" % _n(r["semana"] if r is not None else 0))
    c3.metric("Mes", "%s kg" % _n(r["mes"] if r is not None else 0))
    if r is not None and (float(r["mes_c"]) > 0 or float(r["mes_d"]) > 0):
        c4.metric("Mes C / D", "%s / %s" % (_n(r["mes_c"]), _n(r["mes_d"])))
    else:
        c4.metric("Mes C / D", "—")


def _panel_jornada(cat, conectar, USR, n_pend):
    j = _jornada_hoy(cat)
    if j is None:
        st.info("La jornada de hoy todavía no se abrió.")
        with st.form("rec_abrir"):
            c1, c2 = st.columns([2, 1])
            resp = c1.text_input("Responsables de la cuadrilla",
                                 placeholder="ej. Ulises, Alan, Matías")
            obs = c2.text_input("Observaciones", placeholder="opcional")
            if st.form_submit_button("🟢 Abrir jornada de recuperación", type="primary"):
                _abrir_jornada(conectar, USR, resp, obs)
                cat.clear()
                st.rerun()
        return None
    if str(j["estado"]) == "CERRADA":
        st.success("Jornada de hoy **CERRADA** (%s → %s) · %s"
                   % (j.get("hora_inicio") or "—", j.get("hora_fin") or "—",
                      j.get("responsables") or "sin responsables"))
        if st.button("↩️ Reabrir jornada"):
            _abrir_jornada(conectar, USR, j.get("responsables"), None)
            cat.clear()
            st.rerun()
        return j
    st.success("Jornada **ABIERTA** desde las %s · %s"
               % (j.get("hora_inicio") or "—", j.get("responsables") or "sin responsables"))
    with st.expander("🔴 Cerrar jornada", expanded=False):
        if n_pend:
            st.warning("Quedan **%d ticket(s) sin clasificar** en la bandeja. La regla es "
                       "cerrar con todo pesado y clasificado." % n_pend)
            _ok = st.checkbox("Cerrar igual (los pendientes quedan para mañana)",
                              key="rec_cerrar_igual")
        else:
            st.caption("Bandeja limpia: todo lo pesado está clasificado. ✔")
            _ok = True
        _obs = st.text_input("Observaciones del cierre", key="rec_obs_cierre")
        if st.button("Confirmar cierre", type="primary", disabled=not _ok):
            _cerrar_jornada(conectar, USR, j["id_jornada"], _obs, n_pend)
            cat.clear()
            st.rerun()
    return j


def _panel_bandeja(cat, conectar, USR, cand, j):
    if cand.empty:
        st.success("No hay tickets pendientes de clasificar. 🎉")
        return
    tqs = _tanques_destino(cat)
    _abiertos = cand[cand["estado_camion"] != "SALIO"]
    cand = cand[cand["estado_camion"] == "SALIO"]
    if not _abiertos.empty:
        st.warning("🚛 **%d camión(es) en balanza sin cerrar la pesada** (ticket %s). "
                   "Se clasifican cuando portería cierre."
                   % (len(_abiertos),
                      ", ".join(str(int(t)) for t in _abiertos["transaccion"])))
    id_j = int(j["id_jornada"]) if j is not None else None
    for _, r in cand.iterrows():
        tk = str(int(r["transaccion"]))
        _lab = ("🧪 %s %s · ac %s%% · az %s · fós %s" %
                (r.get("lab_producto") or "AG", r.get("lab_calidad") or "?",
                 r.get("lab_prc_acidez") if pd.notna(r.get("lab_prc_acidez")) else "—",
                 r.get("lab_ppm_azufre") if pd.notna(r.get("lab_ppm_azufre")) else "—",
                 r.get("lab_ppm_fosforo") if pd.notna(r.get("lab_ppm_fosforo")) else "—")
                ) if str(r.get("evaluado")) == "SI" else "🧪 SIN evaluar por laboratorio"
        with st.expander("🎫 **Ticket %s** · %s · %s kg · %s · %s" %
                         (tk, r["fecha_entrada"], _n(r["kg"]),
                          r.get("conductor") or "s/conductor", _lab),
                         expanded=False):
            c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
            c1.caption("Pesada %s → %s · balanza %s · patente %s"
                       % (r.get("hora_e") or "—", r.get("hora_s") or "—",
                          r.get("balanza") or "—", r.get("patente_chasis") or "—"))
            if str(r.get("observaciones") or "").strip():
                c1.caption("Obs. portería: %s" % r["observaciones"])
            _cal_lab = str(r.get("lab_calidad") or "").strip().upper()
            _cal_def = "AG-%s" % _cal_lab if _cal_lab in ("A", "B", "C", "D") else None
            cal = c2.selectbox("Calidad final", list(CALIDADES),
                               index=(list(CALIDADES).index(_cal_def) if _cal_def in CALIDADES else 0),
                               key="rec_cal_%s" % tk,
                               help="Precargada con lo que evaluó laboratorio para este ticket.")
            if _cal_def is None:
                c2.caption("⚠️ Sin muestra de lab: calidad a criterio del responsable.")
            _ops = ["🛢 %s (%s · %s kg)" % (t["nombre"], t["sector"], _n(t["kg_actual"]))
                    for _, t in tqs.iterrows()] + [lbl for _c, lbl in SIN_TANQUE]
            dst = c3.selectbox("Destino REAL de la descarga", _ops, key="rec_dst_%s" % tk,
                               help="Adónde fue el camión de verdad. Si fue a plataforma, "
                                    "elegí Plataforma: NO suma a ningún tanque (y se anula "
                                    "el crédito automático que el sistema le daba al Tanque 4).")
            obs = st.text_input("Observaciones", key="rec_obs_%s" % tk,
                                placeholder="opcional — ej. pileta terciaria 3")
            b1, b2, _sp = st.columns([1.1, 1.3, 2])
            if b1.button("✅ Confirmar recuperación", key="rec_ok_%s" % tk, type="primary",
                         use_container_width=True):
                _idx = _ops.index(dst)
                if _idx < len(tqs):
                    tanque = tqs.iloc[_idx]
                    destino_tipo = "TANQUE"
                else:
                    tanque = None
                    destino_tipo = SIN_TANQUE[_idx - len(tqs)][0]
                prod = _producto(cat, cal)
                if prod is None:
                    st.error("No existe el producto %s en dim_producto." % cal)
                else:
                    _confirmar(conectar, USR, tk, r.to_dict(), "RECUPERACION", prod,
                               destino_tipo, tanque, obs, id_j)
                    cat.clear()
                    st.rerun()
            if b2.button("🚫 NO es recuperación", key="rec_no_%s" % tk,
                         use_container_width=True,
                         help="Movimiento interno común: queda registrado para que no vuelva "
                              "a aparecer acá, y el stock automático no se toca."):
                _confirmar(conectar, USR, tk, r.to_dict(), "NO_RECUPERACION", None,
                           None, None, obs, id_j)
                cat.clear()
                st.rerun()


def _panel_historial(cat, conectar, USR):
    h = _historial(cat)
    if h.empty:
        st.info("Todavía no hay tickets clasificados.")
        return
    v = h.rename(columns={"ticket": "Ticket", "fecha_ticket": "Fecha",
                          "clasificacion": "Clasificación", "producto": "Producto",
                          "destino_tipo": "Destino", "tanque_label": "Tanque", "kg": "Kg",
                          "lab_calidad": "Lab", "conductor": "Conductor",
                          "usuario": "Confirmó", "observaciones": "Obs."})
    st.dataframe(v[["Ticket", "Fecha", "Clasificación", "Producto", "Kg", "Destino",
                    "Tanque", "Lab", "Conductor", "Confirmó", "Obs."]],
                 hide_index=True, use_container_width=True,
                 column_config={"Kg": st.column_config.NumberColumn(format="%.0f")})
    st.download_button("⬇️ CSV", v.to_csv(index=False).encode("utf-8"),
                       file_name="recuperacion_ag.csv", mime="text/csv")
    with st.expander("↩️ Anular una clasificación", expanded=False):
        st.caption("Anula el registro y el movimiento de stock que generó (si tenía tanque). "
                   "El ticket vuelve a la bandeja para clasificarlo de nuevo.")
        _tk = st.selectbox("Ticket", h["ticket"].tolist(), key="rec_anular_tk")
        if st.button("Anular", key="rec_anular_btn"):
            _row = h[h["ticket"] == _tk].iloc[0].to_dict()
            _anular(conectar, USR, _row)
            cat.clear()
            st.rerun()


def render(USR, cat, conectar, contexto="PLANTA"):
    st.markdown("### ♻️ Recuperación de Ácidos Grasos")
    st.caption("Piletas → camión de vacío → muestra de lab → pesada → descarga en reactores. "
               "Cada ticket de portería se clasifica acá: eso es lo que separa una "
               "recuperación real de un movimiento interno y mantiene el stock bien medido.")
    try:
        cand = _candidatos(cat)
    except Exception as e:
        st.error("No se pudo leer portería: %s" % e)
        return
    n_pend = int((cand["estado_camion"] == "SALIO").sum()) if not cand.empty else 0

    _kpis(cat)
    st.markdown("---")
    st.markdown("#### 1 · Jornada del día")
    j = _panel_jornada(cat, conectar, USR, n_pend)
    st.markdown("#### 2 · Bandeja de tickets a clasificar")
    st.caption("Detectados solos desde portería: movimiento interno + producto AG + piletas. "
               "Confirmá el destino real de cada camión, o marcá los que no son recuperación.")
    _panel_bandeja(cat, conectar, USR, cand, j)
    st.markdown("#### 3 · Historial y control")
    _panel_historial(cat, conectar, USR)
