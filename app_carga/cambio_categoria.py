# -*- coding: utf-8 -*-
"""worms_supabase / app_carga / cambio_categoria.py

Cambio de categoría AFE-S ↔ AFE-SG (Centro de Planificación, dirección).

Qué resuelve: la directora decide que X TN (o kL) que estaban contadas como
AFE-S pasan a ser AFE-SG (o al revés). Físicamente casi siempre es un camión
interno que carga en un tanque, pesa en portería (ticket MOVIMIENTO INTERNO,
producto "AFE (S)" / "AFE (SG)") y descarga en otro tanque. El ticket es el
comprobante: su peso valida la cantidad que se declara acá.

Cómo impacta el stock (mismo modelo que Asignación AFE / Recuperación AG):
  * SALIDA  en el tanque origen  con el producto ORIGEN   (fact_movimiento_stock, sentido −1)
  * ENTRADA en el tanque destino con el producto DESTINO  (sentido +1)
  * espejo de cada uno en fact_movimiento_tanque (OUT / IN) → vw_stock_tanque_actual
    los suma al ESTIMADO sólo si son posteriores a la última medición física
    (la medición es la verdad; no se duplica).
  * si el ticket ya tenía un movimiento automático (lab_sync/sistema) se ANULA y
    lo reemplaza este par: evita el doble conteo que hoy generan los internos.
  * si el tanque destino no tenía ese producto como principal, se lo re-rotula
    (queda registrado para poder deshacerlo).
Cabecera + trazabilidad en produccion.fact_cambio_categoria (vista v_cambio_categoria).
"""

from datetime import datetime, time

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
PARES = {"AFE-S → AFE-SG": ("AFE-S", "AFE-SG"),
         "AFE-SG → AFE-S": ("AFE-SG", "AFE-S")}
VACIO_KG = 300.0           # por debajo de esto el tanque se considera vacío (re-rotular sin drama)
TOL_TICKET_PCT = 5.0       # desvío tolerado entre lo declarado y el peso del ticket
DIAS_TICKETS = 45          # ventana de tickets internos AFE que se ofrecen
MOTIVOS = ["", "RESULTADO_LAB", "MEZCLA_TANQUE", "REPROCESO", "ERROR_CARGA", "DECISION_DIRECCION", "OTRO"]
MOTIVO_LBL = {"": "— sin motivo —", "RESULTADO_LAB": "🧪 Resultado de laboratorio",
              "MEZCLA_TANQUE": "🌀 Mezcla en tanque", "REPROCESO": "♻️ Reproceso",
              "ERROR_CARGA": "✏️ Error de carga anterior", "DECISION_DIRECCION": "🛂 Decisión de dirección",
              "OTRO": "📍 Otro"}
_ORIG_AUTO = ("lab_sync", "sistema", "porteria_sync")


# ------------------------------------------------------------------ utilidades

def _f(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return float(v)
    except Exception:
        return None


def _n(v, dec=0):
    x = _f(v)
    if x is None:
        return "—"
    return ("{:,.%df}" % dec).format(x).replace(",", "@").replace(".", ",").replace("@", ".")


def _tn(kg):
    return _n((_f(kg) or 0.0) / 1000.0, 2) + " TN"


# ------------------------------------------------------------------ datos

def _productos(cat):
    df = cat("SELECT id_producto, codigo_producto, densidad_g_ml "
             "FROM produccion.dim_producto WHERE codigo_producto IN ('AFE-S','AFE-SG')")
    return {r["codigo_producto"]: {"id": int(r["id_producto"]),
                                   "dens": _f(r["densidad_g_ml"]) or 0.9}
            for _, r in df.iterrows()}


def _tanques(cat):
    return cat(
        "SELECT t.id_tanque, t.nombre, t.sector, t.capacidad_litros, t.id_producto_principal, "
        "       p.codigo_producto AS prod, "
        "       COALESCE(s.kg_actual,0) AS kg_actual, COALESCE(s.litros_actual,0) AS litros_actual, "
        "       COALESCE(s.kg_estimado, s.kg_actual, 0) AS kg_est, "
        "       COALESCE(s.litros_estimado, s.litros_actual, 0) AS litros_est, "
        "       s.ultima_medicion, COALESCE(s.movs_post_medicion,0) AS movs_post, "
        "       COALESCE((SELECT string_agg(p2.codigo_producto, ',' ORDER BY p2.codigo_producto) "
        "                 FROM produccion.dim_tanque_producto tp "
        "                 JOIN produccion.dim_producto p2 ON p2.id_producto=tp.id_producto "
        "                 WHERE tp.id_tanque=t.id_tanque),'') AS admite "
        "FROM produccion.dim_tanque t "
        "LEFT JOIN produccion.dim_producto p ON p.id_producto=t.id_producto_principal "
        "LEFT JOIN produccion.vw_stock_tanque_actual s ON s.id_tanque=t.id_tanque "
        "WHERE COALESCE(t.activo,true) "
        "ORDER BY t.sector, t.nombre")


def _tickets(cat):
    """Tickets internos de AFE (pesada cerrada) que todavía no respaldan un cambio confirmado."""
    return cat(
        "SELECT t.transaccion, t.fecha_entrada, t.hora_e, t.producto, t.procedencia, t.destino_final, "
        "       ABS(t.peso_neto) AS kg, t.observaciones, t.patente_chasis, t.conductor, "
        "       t.lab_calidad, t.lab_prc_acidez, t.lab_prc_agua, t.lab_ppm_fosforo "
        "FROM produccion.v_transacciones_limpias t "
        "WHERE upper(coalesce(t.cliente,'')) LIKE '%%MOVIMIENTO%%' "
        "  AND upper(coalesce(t.producto_base,'')) = 'AFE' "
        "  AND t.peso_neto IS NOT NULL AND t.peso_neto <> 0 "
        "  AND t.fecha_entrada >= current_date - %s "
        "  AND NOT EXISTS (SELECT 1 FROM produccion.fact_cambio_categoria c "
        "                  WHERE c.ticket_porteria = to_char(t.transaccion,'FM999999999999') "
        "                    AND c.estado = 'CONFIRMADO') "
        "ORDER BY t.transaccion DESC", (DIAS_TICKETS,))


def _movs_ticket(cat, tk):
    return cat(
        "SELECT m.id_mov_stock, m.origen, m.tipo_movimiento, m.sentido, m.kg, m.id_tanque, "
        "       t.nombre AS tanque, m.producto "
        "FROM produccion.fact_movimiento_stock m "
        "LEFT JOIN produccion.dim_tanque t ON t.id_tanque=m.id_tanque "
        "WHERE regexp_replace(COALESCE(m.ticket_porteria,''),'\\.0+$','') = %s "
        "  AND COALESCE(m.anulado,false)=false "
        "ORDER BY m.id_mov_stock", (str(tk),))


def _historial(cat, n=200):
    return cat("SELECT * FROM produccion.v_cambio_categoria ORDER BY momento DESC, id_cambio DESC LIMIT %s", (n,))


# ------------------------------------------------------------------ escritura

def _confirmar(conectar, USR, d):
    """d: dict con todo lo validado en la UI. Una sola transacción."""
    uid = int(USR.get("id_usuario") or 0)
    tk = d.get("ticket")
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            # 1) el ticket ya tenía movimientos automáticos → se reemplazan (evita doble conteo)
            viejos = []
            if tk:
                cur.execute(
                    "UPDATE produccion.fact_movimiento_stock "
                    "SET anulado=true, "
                    "    observaciones = COALESCE(observaciones,'') || ' | reemplazado por Cambio de categoría' "
                    "WHERE regexp_replace(COALESCE(ticket_porteria,''),'\\.0+$','') = %s "
                    "  AND COALESCE(anulado,false)=false AND COALESCE(origen,'') = ANY(%s) "
                    "RETURNING id_mov_stock", (str(tk), list(_ORIG_AUTO)))
                viejos = [int(r[0]) for r in cur.fetchall()]
                cur.execute("DELETE FROM produccion.fact_movimiento_tanque "
                            "WHERE observaciones LIKE %s OR id_mov_stock = ANY(%s)",
                            ("lab_sync ticket %" + str(tk), viejos or [0]))

            obs_mov = "Cambio de categoría %s→%s · %s → %s%s" % (
                d["prod_o"], d["prod_d"], d["tq_o_nombre"], d["tq_d_nombre"],
                (" · ticket %s" % tk) if tk else "")

            # 2) SALIDA del origen (producto origen)
            cur.execute(
                "INSERT INTO produccion.fact_movimiento_stock "
                "(momento, tipo_movimiento, rol, sentido, id_producto, producto, fuente, id_tanque, tanque_label, "
                " ticket_porteria, cantidad, unidad, kg, litros, id_usuario, origen, observaciones, "
                " estado_mov, id_usuario_ejecuta, ejecutado_en) "
                "VALUES (COALESCE(%s::timestamptz, now()),'SALIDA','MP',-1,%s,%s,'TANQUE',%s,%s,%s,%s,'KG',%s,%s,%s,'cambio_categoria',%s,"
                " 'EJECUTADO',%s,now()) RETURNING id_mov_stock",
                (d["momento"], d["pid_o"], d["prod_o"], d["tq_o"], d["tq_o_nombre"], tk,
                 d["kg"], d["kg"], d["litros"], uid, obs_mov, uid))
            id_sal = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO produccion.fact_movimiento_tanque "
                "(id_tanque, id_producto, tipo, litros, kg, ts, id_usuario, origen, observaciones, id_mov_stock) "
                "VALUES (%s,%s,'OUT',%s,%s,COALESCE(%s::timestamptz, now()),%s,'CAMBIO_CATEGORIA',%s,%s)",
                (d["tq_o"], d["pid_o"], d["litros"], d["kg"], d["momento"], uid, obs_mov, id_sal))

            # 3) ENTRADA al destino (producto destino)
            cur.execute(
                "INSERT INTO produccion.fact_movimiento_stock "
                "(momento, tipo_movimiento, rol, sentido, id_producto, producto, fuente, id_tanque, tanque_label, "
                " ticket_porteria, cantidad, unidad, kg, litros, id_usuario, origen, observaciones, "
                " estado_mov, id_usuario_ejecuta, ejecutado_en) "
                "VALUES (COALESCE(%s::timestamptz, now()),'ENTRADA','MP',1,%s,%s,'TANQUE',%s,%s,%s,%s,'KG',%s,%s,%s,'cambio_categoria',%s,"
                " 'EJECUTADO',%s,now()) RETURNING id_mov_stock",
                (d["momento"], d["pid_d"], d["prod_d"], d["tq_d"], d["tq_d_nombre"], tk,
                 d["kg"], d["kg"], d["litros"], uid, obs_mov, uid))
            id_ent = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO produccion.fact_movimiento_tanque "
                "(id_tanque, id_producto, tipo, litros, kg, ts, id_usuario, origen, observaciones, id_mov_stock) "
                "VALUES (%s,%s,'IN',%s,%s,COALESCE(%s::timestamptz, now()),%s,'CAMBIO_CATEGORIA',%s,%s)",
                (d["tq_d"], d["pid_d"], d["litros"], d["kg"], d["momento"], uid, obs_mov, id_ent))

            # 4) re-rotular el tanque destino si hace falta
            if d.get("relabel"):
                cur.execute("UPDATE produccion.dim_tanque SET id_producto_principal=%s WHERE id_tanque=%s",
                            (d["pid_d"], d["tq_d"]))
                cur.execute("INSERT INTO produccion.dim_tanque_producto (id_tanque,id_producto,es_principal) "
                            "VALUES (%s,%s,true) ON CONFLICT (id_tanque,id_producto) DO UPDATE SET es_principal=true",
                            (d["tq_d"], d["pid_d"]))
                cur.execute("UPDATE produccion.dim_tanque_producto SET es_principal=false "
                            "WHERE id_tanque=%s AND id_producto<>%s", (d["tq_d"], d["pid_d"]))

            # 5) cabecera
            cur.execute(
                "INSERT INTO produccion.fact_cambio_categoria "
                "(momento, id_producto_origen, id_producto_dest, id_tanque_origen, id_tanque_dest, "
                " cantidad_ingresada, unidad_ingresada, kg, litros, densidad_usada, ticket_porteria, kg_ticket, "
                " desvio_pct, validado_ticket, relabel_destino, id_producto_dest_anterior, motivo, observaciones, "
                " id_mov_salida, id_mov_entrada, movs_reemplazados, id_usuario) "
                "VALUES (COALESCE(%s::timestamptz, now()),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_cambio",
                (d["momento"], d["pid_o"], d["pid_d"], d["tq_o"], d["tq_d"],
                 d["cantidad"], d["unidad"], d["kg"], d["litros"], d["dens"], tk, d.get("kg_ticket"),
                 d.get("desvio"), bool(d.get("validado")), bool(d.get("relabel")), d.get("pid_d_anterior"),
                 (d.get("motivo") or None), (d.get("obs") or None), id_sal, id_ent, viejos, uid))
            id_cambio = int(cur.fetchone()[0])
        audit.log("I", "fact_cambio_categoria", id_cambio,
                  {"de": d["prod_o"], "a": d["prod_d"], "kg": d["kg"], "tanque_origen": d["tq_o"],
                   "tanque_destino": d["tq_d"], "ticket": tk, "relabel": bool(d.get("relabel")),
                   "movs_reemplazados": viejos})
    return id_cambio


def _anular(conectar, USR, row, motivo):
    uid = int(USR.get("id_usuario") or 0)
    idc = int(row["id_cambio"])
    ids = [int(x) for x in (row.get("id_mov_salida"), row.get("id_mov_entrada")) if _f(x) is not None]
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.fact_movimiento_stock SET anulado=true, "
                        "observaciones = COALESCE(observaciones,'') || ' | ANULADO cambio de categoría' "
                        "WHERE id_mov_stock = ANY(%s)", (ids or [0],))
            cur.execute("DELETE FROM produccion.fact_movimiento_tanque WHERE id_mov_stock = ANY(%s)", (ids or [0],))
            # los movimientos automáticos que este cambio había reemplazado vuelven a valer
            reemp = row.get("movs_reemplazados")
            reemp = [int(x) for x in (reemp if isinstance(reemp, (list, tuple)) else [])]
            if reemp:
                cur.execute("UPDATE produccion.fact_movimiento_stock SET anulado=false, "
                            "observaciones = COALESCE(observaciones,'') || ' | restaurado (cambio anulado)' "
                            "WHERE id_mov_stock = ANY(%s)", (reemp,))
            # deshacer el re-rotulado sólo si el tanque sigue con el producto que pusimos
            if bool(row.get("relabel_destino")):
                cur.execute("SELECT id_producto_dest_anterior, id_producto_dest FROM produccion.fact_cambio_categoria "
                            "WHERE id_cambio=%s", (idc,))
                _r = cur.fetchone()
                if _r and _r[0] is not None:
                    cur.execute("UPDATE produccion.dim_tanque SET id_producto_principal=%s "
                                "WHERE id_tanque=%s AND id_producto_principal=%s",
                                (int(_r[0]), int(row["id_tanque_dest"]), int(_r[1])))
            cur.execute("UPDATE produccion.fact_cambio_categoria SET estado='ANULADO', anulado_en=now(), "
                        "id_usuario_anula=%s, motivo_anulacion=%s WHERE id_cambio=%s", (uid, motivo or None, idc))
        audit.log("U", "fact_cambio_categoria", idc, {"accion": "ANULAR", "motivo": motivo, "movs": ids,
                                                     "restaurados": reemp})


# ------------------------------------------------------------------ UI

def _kpis(tq, prods):
    c = st.columns(4)
    for i, cod in enumerate(("AFE-S", "AFE-SG")):
        sub = tq[tq["prod"] == cod]
        kg = float(sub["kg_est"].sum()) if not sub.empty else 0.0
        c[i].metric("Stock %s (estimado)" % cod, _tn(kg), "%d tanques" % len(sub))
    tot = float(tq[tq["prod"].isin(["AFE-S", "AFE-SG"])]["kg_est"].sum())
    c[2].metric("AFE-S + AFE-SG", _tn(tot))
    pend = int((tq[tq["prod"].isin(["AFE-S", "AFE-SG"])]["movs_post"] > 0).sum())
    c[3].metric("Tanques c/ movs sin medir", str(pend),
                help="Tanques con movimientos posteriores a su última medición física: el estimado difiere del medido.")


def _label_tq(r):
    return "%s · %s · %s (%s L)" % (r["nombre"], r["sector"], _tn(r["kg_est"]), _n(r["litros_est"], 0))


def _nuevo(USR, cat, conectar, tq, prods):
    st.markdown("#### 1 · Sentido del cambio")
    _opts = list(PARES.keys())
    try:
        sentido = st.segmented_control("Sentido", _opts, default=_opts[0], key="cc_sentido",
                                       label_visibility="collapsed")
    except Exception:
        sentido = st.radio("Sentido", _opts, horizontal=True, key="cc_sentido_r")
    sentido = sentido or _opts[0]
    if sentido != st.session_state.get("cc_sentido_last"):
        st.session_state["cc_sentido_last"] = sentido
        for _k in ("cc_tq_o", "cc_tq_d"):
            st.session_state.pop(_k, None)
    prod_o, prod_d = PARES[sentido]
    po, pdst = prods[prod_o], prods[prod_d]

    # ---------- tanques ----------
    st.markdown("#### 2 · De qué tanque sale y a cuál entra")
    cA, cB = st.columns(2)
    orig = tq[(tq["prod"] == prod_o) & (tq["kg_est"].astype(float) > 0)].copy()
    if orig.empty:
        st.warning("No hay tanques con stock de %s." % prod_o)
        return
    with cA:
        st.caption("**Origen** — tanques rotulados %s con stock" % prod_o)
        id_o = st.selectbox("Tanque origen", orig["id_tanque"].tolist(),
                            format_func=lambda i: _label_tq(orig[orig["id_tanque"] == i].iloc[0]),
                            key="cc_tq_o", label_visibility="collapsed")
        ro = orig[orig["id_tanque"] == id_o].iloc[0]
        if int(ro["movs_post"] or 0) > 0:
            st.caption("⚠️ medido %s L el %s · estimado c/movs %s L" % (
                _n(ro["litros_actual"]), pd.to_datetime(ro["ultima_medicion"]).strftime("%d/%m %H:%M")
                if pd.notna(ro["ultima_medicion"]) else "—", _n(ro["litros_est"])))
    with cB:
        todos = st.toggle("Mostrar todos los tanques", key="cc_todos",
                          help="Por defecto se ofrecen los tanques rotulados %s y los vacíos que lo admiten. "
                               "Activá esto para elegir cualquier otro (se re-rotula al confirmar)." % prod_d)
        admite = tq["admite"].fillna("").str.split(",").apply(lambda l: prod_d in l)
        vacio = tq["kg_est"].astype(float) < VACIO_KG
        dest = tq[(tq["id_tanque"] != id_o) & (todos | (tq["prod"] == prod_d) | (admite & vacio))].copy()
        # los del producto destino primero, después vacíos, después resto
        dest["_rk"] = [0 if p == prod_d else (1 if v else 2) for p, v in zip(dest["prod"], vacio.loc[dest.index])]
        dest = dest.sort_values(["_rk", "sector", "nombre"])
        st.caption("**Destino** — rotulados %s o vacíos que lo admiten" % prod_d)
        if dest.empty:
            st.warning("No hay tanques destino candidatos. Activá «Mostrar todos los tanques».")
            return
        id_d = st.selectbox("Tanque destino", dest["id_tanque"].tolist(),
                            format_func=lambda i: ("%s · %s" % (
                                dest[dest["id_tanque"] == i].iloc[0]["prod"] or "sin producto",
                                _label_tq(dest[dest["id_tanque"] == i].iloc[0]))),
                            key="cc_tq_d", label_visibility="collapsed")
        rd = dest[dest["id_tanque"] == id_d].iloc[0]
    relabel = (rd["prod"] != prod_d)
    kg_d_antes = float(rd["kg_est"] or 0)
    if relabel:
        if kg_d_antes >= VACIO_KG:
            st.error("**%s** está rotulado **%s** y tiene %s. Al confirmar pasa a contarse TODO como **%s** "
                     "(se mezcla). Si no es lo que querés, elegí otro tanque." % (
                         rd["nombre"], rd["prod"] or "sin producto", _tn(kg_d_antes), prod_d))
        else:
            st.info("**%s** está vacío: al confirmar queda rotulado **%s**." % (rd["nombre"], prod_d))

    # ---------- ticket ----------
    st.markdown("#### 3 · Ticket de portería (validación del peso)")
    tks = _tickets(cat)
    _tk_opts = [None] + tks["transaccion"].tolist()

    def _tk_lbl(t):
        if t is None:
            return "— sin ticket —"
        r = tks[tks["transaccion"] == t].iloc[0]
        return "%s · %s %s · %s kg · %s · %s→%s · %s" % (
            int(t), r["fecha_entrada"], str(r["hora_e"])[:5], _n(r["kg"]), r["producto"],
            r["procedencia"] or "?", r["destino_final"] or "?", (r["observaciones"] or "")[:28])

    c1, c2 = st.columns([3, 1])
    tk_sel = c1.selectbox("Ticket (movimientos internos AFE, últimos %d días)" % DIAS_TICKETS, _tk_opts,
                          format_func=_tk_lbl, key="cc_tk")
    tk_manual = c2.text_input("Otro ticket (n°)", key="cc_tk_manual", placeholder="ej. 6417")
    tk = None
    kg_ticket = None
    tk_row = None
    if tk_sel is not None:
        tk = str(int(tk_sel))
        tk_row = tks[tks["transaccion"] == tk_sel].iloc[0]
        kg_ticket = _f(tk_row["kg"])
    elif tk_manual.strip():
        _m = cat("SELECT transaccion, fecha_entrada, hora_e, producto, procedencia, destino_final, "
                 "       ABS(peso_neto) AS kg, observaciones, patente_chasis, conductor, lab_calidad, "
                 "       lab_prc_acidez, lab_prc_agua, lab_ppm_fosforo "
                 "FROM produccion.v_transacciones_limpias WHERE transaccion::text = %s", (tk_manual.strip(),))
        if _m.empty:
            st.warning("No encuentro el ticket %s en portería." % tk_manual.strip())
        else:
            tk_row = _m.iloc[0]
            tk = str(int(tk_row["transaccion"]))
            kg_ticket = _f(tk_row["kg"])
            if kg_ticket is None or kg_ticket == 0:
                st.warning("El ticket %s no tiene peso neto todavía (pesada abierta)." % tk)
                kg_ticket = None
    if tk_row is not None:
        cc = st.columns([1, 1, 1, 1, 2])
        cc[0].metric("Peso ticket", (_n(kg_ticket) + " kg") if kg_ticket else "—")
        cc[1].metric("Producto", str(tk_row["producto"] or "—"))
        cc[2].metric("Lab", str(tk_row.get("lab_calidad") or "—"),
                     help="Acidez %s%% · Agua %s%% · P %s ppm" % (
                         _n((_f(tk_row.get("lab_prc_acidez")) or 0) * 100, 2),
                         _n((_f(tk_row.get("lab_prc_agua")) or 0) * 100, 2), _n(tk_row.get("lab_ppm_fosforo"))))
        cc[3].metric("Fecha", "%s %s" % (tk_row["fecha_entrada"], str(tk_row["hora_e"])[:5]))
        cc[4].caption("**Obs. portería:** %s · %s" % (tk_row.get("observaciones") or "—",
                                                     tk_row.get("patente_chasis") or ""))
        prev = _movs_ticket(cat, tk)
        if not prev.empty:
            st.warning("Este ticket ya generó **%d movimiento(s) automático(s)** (%s). Al confirmar se ANULAN y los "
                       "reemplaza este cambio, así no se cuenta dos veces." % (
                           len(prev), "; ".join("%s %s %s kg → %s" % (
                               r["origen"], r["tipo_movimiento"], _n(r["kg"]), r["tanque"] or "?")
                               for _, r in prev.iterrows())))
        usar_fecha_tk = st.checkbox("Registrar el movimiento con la fecha/hora del ticket", value=True, key="cc_fecha_tk",
                                    help="Si el tanque se midió DESPUÉS del ticket, la medición ya contiene este "
                                         "movimiento y el estimado no cambia (correcto). Desmarcá para fecharlo ahora.")
    else:
        usar_fecha_tk = False

    # ---------- cantidad ----------
    st.markdown("#### 4 · Cantidad")
    c1, c2, c3 = st.columns([1, 1.4, 2])
    unidad = c1.radio("Unidad", ["TN", "kL"], horizontal=True, key="cc_unidad")
    dens = po["dens"]

    def _from_kg(k):
        return (k / 1000.0) if unidad == "TN" else (k / dens / 1000.0)

    # ticket nuevo → precarga su peso; unidad nueva → convierte lo que había
    if tk != st.session_state.get("cc_tk_last"):
        st.session_state["cc_tk_last"] = tk
        st.session_state.pop("cc_cant", None)
        if kg_ticket:
            st.session_state["cc_cant_val"] = _from_kg(kg_ticket)
    _u_prev = st.session_state.get("cc_unidad_last")
    if unidad != _u_prev:
        if _u_prev is not None and _f(st.session_state.get("cc_cant_val")):
            _v = float(st.session_state["cc_cant_val"])
            _kgv = _v * 1000.0 if _u_prev == "TN" else _v * 1000.0 * dens
            st.session_state["cc_cant_val"] = _from_kg(_kgv)
            st.session_state.pop("cc_cant", None)
        st.session_state["cc_unidad_last"] = unidad
    _default = float(st.session_state.get("cc_cant_val") or 0.0)
    cant = c2.number_input("Cantidad (%s)" % unidad, min_value=0.0, value=round(_default, 3), step=0.5,
                           format="%.3f", key="cc_cant",
                           help="Con ticket se precarga su peso. TN = kg/1000 · kL = m³ (litros/1000).")
    st.session_state["cc_cant_val"] = float(cant or 0.0)
    if c3.button("Usar TODO el stock del tanque origen (%s)" % _tn(ro["kg_est"]), key="cc_todo"):
        st.session_state["cc_cant_val"] = _from_kg(float(ro["kg_est"] or 0.0))
        st.session_state.pop("cc_cant", None)
        st.rerun()
    if unidad == "TN":
        kg = cant * 1000.0
        litros = kg / dens
    else:
        litros = cant * 1000.0
        kg = litros * dens
    kg_o_antes = float(ro["kg_est"] or 0)
    cap_d = _f(rd["capacidad_litros"])
    lit_d_antes = float(rd["litros_est"] or 0)

    m = st.columns(5)
    m[0].metric("Kg a mover", _n(kg) + " kg", help="Densidad %s usada: %.3f" % (prod_o, dens))
    m[1].metric("Litros", _n(litros) + " L")
    m[2].metric("%s queda con" % ro["nombre"], _tn(kg_o_antes - kg), "-" + _tn(kg))
    m[3].metric("%s queda con" % rd["nombre"], _tn(kg_d_antes + kg), "+" + _tn(kg))
    desvio = None
    validado = False
    if kg_ticket:
        desvio = (kg - kg_ticket) / kg_ticket * 100.0
        validado = abs(desvio) <= TOL_TICKET_PCT
        m[4].metric("Desvío vs ticket", "%+.1f %%" % desvio, "validado ✅" if validado else "revisar ⚠️",
                    delta_color="normal" if validado else "inverse")
    else:
        m[4].metric("Desvío vs ticket", "sin ticket", help="Sin comprobante de portería el cambio queda como NO validado.")

    problemas, avisos = [], []
    if kg <= 0:
        problemas.append("La cantidad tiene que ser mayor a 0.")
    if kg > kg_o_antes * 1.02 + 1:
        avisos.append("Sacás %s de un tanque que tiene %s estimados: quedaría en negativo hasta la próxima medición."
                      % (_tn(kg), _tn(kg_o_antes)))
    if cap_d and (lit_d_antes + litros) > cap_d * 1.02:
        avisos.append("El destino supera su capacidad (%s L + %s L > %s L)." % (
            _n(lit_d_antes), _n(litros), _n(cap_d)))
    if kg_ticket and not validado:
        avisos.append("Lo declarado difiere %+.1f %% del peso del ticket (tolerancia ±%.0f %%)." % (desvio, TOL_TICKET_PCT))
    if relabel and kg_d_antes >= VACIO_KG:
        avisos.append("El tanque destino tiene %s de %s que pasarán a contarse como %s." % (
            _tn(kg_d_antes), rd["prod"] or "otro producto", prod_d))
    if not tk:
        avisos.append("Sin ticket de portería: el cambio queda registrado como NO validado.")

    # ---------- motivo ----------
    st.markdown("#### 5 · Motivo y confirmación")
    c1, c2 = st.columns([1, 2])
    motivo = c1.selectbox("Motivo", MOTIVOS, format_func=lambda k: MOTIVO_LBL.get(k, k), key="cc_motivo")
    obs = c2.text_input("Observaciones", key="cc_obs", placeholder="ej. lab dio goma > 1% en BPN 5")
    for p in problemas:
        st.error(p)
    for a in avisos:
        st.warning(a)
    forzar = True
    if avisos:
        forzar = st.checkbox("Entiendo los avisos y confirmo igual", key="cc_forzar")
    if not motivo:
        st.caption("Elegí un motivo para habilitar la confirmación.")

    if usar_fecha_tk and tk_row is not None:
        try:
            _h = tk_row["hora_e"]
            if isinstance(_h, str):
                _h = time.fromisoformat(_h[:8])
            momento = datetime.combine(pd.to_datetime(tk_row["fecha_entrada"]).date(), _h or time(12, 0))
        except Exception:
            momento = None
    else:
        momento = None   # now() de la base (zona Argentina fijada por conectar)

    ok = not problemas and forzar and bool(motivo)
    if st.button("✅ Confirmar cambio %s → %s de %s" % (prod_o, prod_d, _tn(kg)), type="primary",
                 disabled=not ok, key="cc_confirmar", use_container_width=True):
        d = {"prod_o": prod_o, "prod_d": prod_d, "pid_o": po["id"], "pid_d": pdst["id"],
             "tq_o": int(id_o), "tq_o_nombre": str(ro["nombre"]), "tq_d": int(id_d), "tq_d_nombre": str(rd["nombre"]),
             "cantidad": float(cant), "unidad": "TN" if unidad == "TN" else "KL",
             "kg": round(kg, 1), "litros": round(litros, 1), "dens": dens,
             "ticket": tk, "kg_ticket": kg_ticket, "desvio": (round(desvio, 2) if desvio is not None else None),
             "validado": validado, "relabel": bool(relabel),
             "pid_d_anterior": (int(rd["id_producto_principal"]) if pd.notna(rd["id_producto_principal"]) else None),
             "motivo": motivo, "obs": obs, "momento": momento}
        try:
            idc = _confirmar(conectar, USR, d)
        except Exception as e:
            st.error("No se pudo registrar el cambio: %s" % e)
            return
        for k in ("cc_cant", "cc_cant_val", "cc_tk", "cc_tk_last", "cc_tk_manual", "cc_obs", "cc_forzar"):
            st.session_state.pop(k, None)
        try:
            cat.clear()
        except Exception:
            pass
        st.success("Cambio #%d registrado: %s → %s, %s (%s L)%s." % (
            idc, prod_o, prod_d, _tn(kg), _n(litros),
            (" · ticket %s %s" % (tk, "validado" if validado else "sin validar")) if tk else " · sin ticket"))
        st.rerun()


def _historial_ui(USR, cat, conectar):
    h = _historial(cat)
    if h.empty:
        st.info("Todavía no hay cambios de categoría registrados.")
        return
    conf = h[h["estado"] == "CONFIRMADO"]
    c = st.columns(4)
    c[0].metric("Cambios confirmados", str(len(conf)))
    c[1].metric("AFE-S → AFE-SG", _tn(conf[conf["prod_origen"] == "AFE-S"]["kg"].astype(float).sum()))
    c[2].metric("AFE-SG → AFE-S", _tn(conf[conf["prod_origen"] == "AFE-SG"]["kg"].astype(float).sum()))
    c[3].metric("Con ticket validado", "%d / %d" % (int(conf["validado_ticket"].astype(bool).sum()), len(conf)))

    v = h.copy()
    v["momento"] = pd.to_datetime(v["momento"]).dt.strftime("%d/%m/%Y %H:%M")
    v["cambio"] = v["prod_origen"] + " → " + v["prod_destino"]
    v["ticket"] = v.apply(lambda r: ("%s (%s kg%s)" % (r["ticket_porteria"], _n(r["kg_ticket"]),
                                                       "" if _f(r["desvio_pct"]) is None else ", %+.1f%%" % float(r["desvio_pct"])))
                          if r["ticket_porteria"] else "—", axis=1)
    v["ok"] = v.apply(lambda r: "❌ anulado" if r["estado"] == "ANULADO" else ("✅" if r["validado_ticket"] else "⚠️ sin validar"), axis=1)
    cols = ["id_cambio", "momento", "cambio", "tanque_origen", "tanque_destino", "tn", "litros", "ticket", "ok",
            "motivo", "usuario", "observaciones"]
    st.dataframe(v[cols].rename(columns={"id_cambio": "#", "tn": "TN", "litros": "L"}),
                 use_container_width=True, hide_index=True)
    st.download_button("⬇️ CSV", v[cols].to_csv(index=False).encode("utf-8"), "cambios_categoria.csv", "text/csv",
                       key="cc_csv")

    if USR.get("rol") in ROLES_DIRECCION and not conf.empty:
        with st.expander("↩️ Anular un cambio", expanded=False):
            idc = st.selectbox("Cambio a anular", conf["id_cambio"].tolist(),
                               format_func=lambda i: "#%d · %s · %s → %s · %s" % (
                                   i, pd.to_datetime(conf[conf["id_cambio"] == i].iloc[0]["momento"]).strftime("%d/%m %H:%M"),
                                   conf[conf["id_cambio"] == i].iloc[0]["prod_origen"],
                                   conf[conf["id_cambio"] == i].iloc[0]["prod_destino"],
                                   _tn(conf[conf["id_cambio"] == i].iloc[0]["kg"])), key="cc_anul_id")
            mot = st.text_input("Motivo de la anulación", key="cc_anul_mot")
            st.caption("Se anulan los dos movimientos de stock, se restauran los automáticos que había reemplazado "
                       "y se deshace el re-rotulado del tanque destino si todavía lo tiene.")
            if st.button("Anular", key="cc_anul_btn", disabled=not mot.strip()):
                try:
                    _anular(conectar, USR, conf[conf["id_cambio"] == idc].iloc[0], mot.strip())
                    try:
                        cat.clear()
                    except Exception:
                        pass
                    st.success("Cambio #%d anulado." % idc)
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo anular: %s" % e)


def render(USR, cat, conectar, contexto="PLANIFICACION"):
    st.markdown("### 🔁 Cambio de categoría AFE-S ↔ AFE-SG")
    st.caption("Pasá toneladas o kilolitros de una categoría a la otra moviéndolas de tanque. "
               "Si hay ticket de portería, su peso valida la cantidad; el stock se actualiza en el acto.")
    # En Producción en planta (contexto PLANTA) lo usa el operario que hace el movimiento;
    # el acceso ya lo controla la sección. En Planificación queda para dirección.
    if contexto != "PLANTA" and USR.get("rol") not in ROLES_DIRECCION \
       and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return
    prods = _productos(cat)
    if not all(k in prods for k in ("AFE-S", "AFE-SG")):
        st.error("Faltan AFE-S / AFE-SG en dim_producto.")
        return
    tq = _tanques(cat)
    _kpis(tq, prods)
    st.write("")
    _opts = ["🔁 Nuevo cambio", "🕒 Historial"]
    try:
        sub = st.segmented_control("Vista", _opts, default=_opts[0], key="cc_sub", label_visibility="collapsed")
    except Exception:
        sub = st.radio("Vista", _opts, horizontal=True, key="cc_sub_r")
    sub = sub or _opts[0]
    st.write("")
    if sub.startswith("🕒"):
        _historial_ui(USR, cat, conectar)
    else:
        _nuevo(USR, cat, conectar, tq, prods)
