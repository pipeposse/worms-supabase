# -*- coding: utf-8 -*-
"""Asignación de Tanques a AFEs.

Cada ticket de AFE evaluado por laboratorio recibe automáticamente 1 a 7 tanques
de acopio sugeridos (SOL-0009: con poco espacio de acopio un camión se reparte
completando varios tanques a tope). El operario (Producción en planta) o la dirección (Centro de
Planificación) confirma o edita tanque y cantidades.

Al confirmar:
  * se anulan los movimientos automáticos previos del ticket (lab_sync / sistema)
    y se insertan 1 a 7 movimientos de stock reales + su espejo de tanque;
  * se propagan los parámetros del ticket al tanque:
      - tanque vacío  -> parámetros del ticket
      - tanque con líquido -> promedio ponderado por kg asignados
    marcando el origen 'MEZCLA_INGRESO' en fact_param_tanque_hist para que la
    trazabilidad distinga lab directo de mezcla por ingreso.
"""

import json
import math

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------- constantes

DIAS_HIST = 30           # ventana de historial de movimientos para la probabilidad
VACIO_KG = 300.0         # por debajo de esto el tanque se considera vacío
DISP_MIN_LTS = 800.0     # tanque sin espacio útil: no se sugiere

# afinidad de parámetros: (col tanque, col ticket, tolerancia, peso)
PARES_PARAM = [
    ("acidez_pct",     "acidez",   1.5,   0.35),
    ("ppm_fosforo",    "fosforo",  150.0, 0.25),
    ("ppm_azufre",     "azufre",   30.0,  0.25),
    ("agua_pct",       "agua",     1.0,   0.075),
    ("sedimentos_pct", "sed",      1.0,   0.075),
]

W_HIST, W_AFIN, W_CAP, W_CONS = 0.25, 0.40, 0.20, 0.15
DEG_TOL = 2.0             # +2,0 puntos de acidez = degradación máxima (1.0)
DEG_FACTOR = 0.85         # la degradación DESCUENTA el score (no resta): casi veto

MOTIVOS = ["", "DISPONIBILIDAD", "PARAMETROS", "MATERIA_PRIMA", "LOGISTICA", "OTRO"]

ORIGEN_LBL = {
    "TICKET_LAB":     "🧪 Laboratorio (medición directa)",
    "MANUAL_LAB":     "✍️ Carga manual de laboratorio",
    "CARGA_INICIAL":  "📦 Carga inicial",
    "MEZCLA_INGRESO": "🚛 Mezcla por ingreso de AFE",
}


# ---------------------------------------------------------------- utilidades

def _f(v):
    """float o None (tolera '', None, NaN)."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    try:
        s = str(v).strip()
        if s == "" or s.lower() in ("none", "nan"):
            return None
        return float(s)
    except Exception:
        return None


def _n(v, dec=1):
    x = _f(v)
    if x is None:
        return "—"
    return ("{:,.%df}" % dec).format(x).replace(",", "@").replace(".", ",").replace("@", ".")


def _tk_norm(t):
    s = str(t or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


# ---------------------------------------------------------------- lecturas

def _tickets(cat, dias, estado):
    """Tickets de AFE evaluados + su estado de asignación."""
    _f_estado = ""
    if estado == "PEND":
        _f_estado = "AND COALESCE(a.estado,'PENDIENTE') = 'PENDIENTE'"
    elif estado == "CONF":
        _f_estado = "AND a.estado = 'CONFIRMADO'"
    sql = (
        "WITH le AS ("
        "  SELECT DISTINCT ON (regexp_replace(l.ticket,'\\.0+$','')) "
        "         regexp_replace(l.ticket,'\\.0+$','') AS tk, l.id AS id_lab, l.fecha, "
        "         l.calidad_final_lab, l.corriente, l.rechazado, l.conclusion, "
        "         l.id_tanque_1, l.id_tanque_2, "
        "         l.prc_acidez, l.prc_agua, l.prc_sedimentos, l.densidad__g_ml, "
        "         l.ppm_azufre, l.ppm_fosforo "
        "  FROM produccion.lab_evaluaciones l "
        "  WHERE l.fecha >= now() - interval '%d days' "
        "    AND upper(btrim(COALESCE(l.producto_lab,''))) = 'AFE' "
        "    AND COALESCE(l.ticket,'') <> '' "
        "    AND upper(COALESCE(l.rechazado,'')) NOT IN ('RECHAZADO','REMUESTREO') "
        "  ORDER BY regexp_replace(l.ticket,'\\.0+$',''), l.fecha DESC"
        ") "
        "SELECT le.*, "
        "       tx.procedencia, tx.cliente, tx.patente_chasis, tx.fecha_entrada, "
        "       ABS(COALESCE(tx.peso_neto,0)) AS kg_ticket, "
        "       produccion.fn_resolver_producto_lab('AFE', le.calidad_final_lab) AS id_producto, "
        "       COALESCE(a.estado,'PENDIENTE') AS estado, a.id_asig, a.confirmado_en, "
        "       a.origen_confirmacion, a.observaciones AS obs_asig, u.nombre AS confirmo "
        "FROM le "
        "LEFT JOIN LATERAL (SELECT procedencia, cliente, patente_chasis, peso_neto, fecha_entrada "
        "   FROM produccion.v_transacciones_limpias "
        "   WHERE regexp_replace(CAST(transaccion AS text),'\\.0+$','') = le.tk "
        "   ORDER BY fecha_entrada DESC NULLS LAST LIMIT 1) tx ON true "
        "LEFT JOIN produccion.fact_asignacion_afe a ON a.ticket = le.tk "
        "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = a.id_usuario "
        "WHERE 1=1 " + _f_estado + " "
        "ORDER BY le.fecha DESC"
    ) % int(dias)
    return cat(sql)


def _candidatos(cat, id_producto):
    """Tanques de acopio habilitados para el producto, con stock, parámetros e historial."""
    sql = (
        "WITH hist AS ("
        "  SELECT m.id_tanque, COUNT(*) AS n, SUM(COALESCE(m.kg,0)) AS kg "
        "  FROM produccion.fact_movimiento_stock m "
        "  WHERE m.momento >= now() - interval '%d days' "
        "    AND COALESCE(m.anulado,false) = false AND m.sentido = 1 "
        "    AND m.id_producto = %d AND m.id_tanque IS NOT NULL "
        "  GROUP BY 1"
        ") "
        "SELECT t.id_tanque, t.codigo, t.nombre, t.sector, t.condicion, "
        "       COALESCE(t.capacidad_litros,0) AS cap_lts, "
        "       COALESCE(s.litros_estimado, s.litros_actual, 0) AS lts_est, "
        "       COALESCE(s.kg_estimado, s.kg_actual, 0) AS kg_est, "
        "       GREATEST(COALESCE(t.capacidad_litros,0) - COALESCE(s.litros_estimado, s.litros_actual, 0), 0) AS disp_lts, "
        "       COALESCE(pp.es_principal,false) AS es_principal, "
        "       COALESCE(h.n,0) AS hist_n, COALESCE(h.kg,0) AS hist_kg, "
        "       p.acidez_pct, p.agua_pct, p.sedimentos_pct, p.densidad_g_ml, "
        "       p.ppm_azufre, p.ppm_fosforo, p.ultima_evaluacion_ts, "
        "       c.acidez_max, c.agua_max, c.sedimentos_max, c.azufre_max, c.fosforo_max "
        "FROM produccion.dim_tanque t "
        "LEFT JOIN produccion.dim_tanque_producto_permitido pp "
        "       ON pp.id_tanque = t.id_tanque AND pp.id_producto = %d "
        "LEFT JOIN produccion.vw_stock_tanque_actual s ON s.id_tanque = t.id_tanque "
        "LEFT JOIN produccion.fact_param_tanque p ON p.id_tanque = t.id_tanque AND p.id_producto = %d "
        "LEFT JOIN produccion.dic_tanque_condicion c ON c.id_tanque = t.id_tanque AND c.id_producto = %d "
        "LEFT JOIN hist h ON h.id_tanque = t.id_tanque "
        "WHERE COALESCE(t.activo,true) "
        "  AND COALESCE(t.condicion,'EN USO') <> 'FUERA DE USO' "
        "  AND COALESCE(t.uso,'ACOPIO') = 'ACOPIO' "
        "  AND (pp.id_tanque IS NOT NULL OR t.id_producto_principal = %d) "
        "ORDER BY t.nombre"
    ) % (DIAS_HIST, int(id_producto), int(id_producto), int(id_producto), int(id_producto), int(id_producto))
    return cat(sql)


def _densidad(cat, id_producto):
    d = cat("SELECT densidad_g_ml FROM produccion.dim_producto WHERE id_producto = %s",
            (int(id_producto),))
    v = _f(d.iloc[0, 0]) if d is not None and not d.empty else None
    return v if v and v > 0.3 else 0.91


# ---------------------------------------------------------------- motor

def _afinidad(tq, tk):
    """0..1 — qué tan parecido es el ticket al contenido actual del tanque."""
    num = den = 0.0
    for col_tq, col_tk, tol, w in PARES_PARAM:
        a, b = _f(tq.get(col_tq)), _f(tk.get(col_tk))
        if a is None or b is None:
            continue
        num += w * max(0.0, 1.0 - min(1.0, abs(a - b) / tol))
        den += w
    if den <= 0:
        return 0.5, "sin datos comparables"
    v = num / den
    return v, None


def _pasa_condicion(tq, tk):
    """Máximos declarados en dic_tanque_condicion (si no hay, pasa)."""
    chk = [("acidez_max", "acidez"), ("agua_max", "agua"), ("sedimentos_max", "sed"),
           ("azufre_max", "azufre"), ("fosforo_max", "fosforo")]
    for cmax, ctk in chk:
        mx, v = _f(tq.get(cmax)), _f(tk.get(ctk))
        if mx is not None and v is not None and v > mx:
            return False, cmax.replace("_max", "")
    return True, None


def _degradacion(tq, tk, kg_antes, kg_add):
    """0..1 — cuánto EMPEORA la acidez del tanque al mezclar (bajarla no penaliza)."""
    a, b = _f(tq.get("acidez_pct")), _f(tk.get("acidez"))
    if a is None or b is None or kg_add <= 0:
        return 0.0, None
    if kg_antes < VACIO_KG:
        return 0.0, None          # tanque vacío: toma los parámetros del ticket
    post = (a * kg_antes + b * kg_add) / (kg_antes + kg_add)
    delta = post - a
    if delta <= 0:
        return 0.0, None
    return min(1.0, delta / DEG_TOL), "acidez %s → %s" % (_n(a, 2), _n(post, 2))


def _medianas(filas):
    """Mediana de cada parámetro sobre los tanques CON líquido y valor medido.

    Sirve para imputar tanques sin medición: sin esto un tanque sin datos
    puntúa neutro y puede recibir carga que lo degrade sin penalización.
    """
    med = {}
    for col_tq, _ck, _tol, _w in PARES_PARAM:
        vals = []
        for r in filas:
            if (_f(r.get("kg_est")) or 0.0) < VACIO_KG:
                continue                      # tanque vacío: su valor no representa nada
            v = _f(r.get(col_tq))
            if v is not None:
                vals.append(v)
        if vals:
            vals.sort()
            n = len(vals)
            med[col_tq] = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    return med


def _imputar(filas):
    """Rellena parámetros faltantes con la mediana. Marca lo imputado en _imput."""
    med = _medianas(filas)
    for r in filas:
        falt = []
        if (_f(r.get("kg_est")) or 0.0) < VACIO_KG:
            r["_imput"] = []                  # tanque vacío: no se imputa nada
            continue
        for col_tq, _ck, _tol, _w in PARES_PARAM:
            if _f(r.get(col_tq)) is None and col_tq in med:
                r[col_tq] = med[col_tq]
                falt.append(col_tq.replace("_pct", "").replace("ppm_", ""))
        r["_imput"] = falt
    return filas


def _rankear(df_cand, tk, litros, kg=None):
    """Devuelve lista de dicts ordenada por score desc."""
    if df_cand is None or df_cand.empty:
        return []
    if kg is None:
        kg = 0.0
    dens_tk = (kg / litros) if (litros and litros > 0) else 0.91
    filas = _imputar(df_cand.to_dict("records"))
    tot_n = sum(_f(r.get("hist_n")) or 0.0 for r in filas)
    k = len(filas) or 1
    p_max = 0.0
    out = []
    for r in filas:
        ok, motivo = _pasa_condicion(r, tk)
        disp = _f(r.get("disp_lts")) or 0.0
        cap = _f(r.get("cap_lts")) or 0.0
        kg_est = _f(r.get("kg_est")) or 0.0
        lts_est = _f(r.get("lts_est")) or 0.0
        n = _f(r.get("hist_n")) or 0.0
        p = (n + 0.5) / (tot_n + 0.5 * k) if (tot_n + 0.5 * k) > 0 else 0.0
        p_max = max(p_max, p)
        afin, nota = _afinidad(r, tk)
        vacio = kg_est < VACIO_KG
        if vacio:
            afin, nota = 1.0, "tanque vacío"
        cap_sc = 1.0 if (litros <= 0 or disp >= litros) else max(0.0, disp / litros)
        cons = (lts_est / cap) if cap > 0 else 0.0
        cons = min(1.0, max(0.0, cons))
        kg_add = min(kg, disp * dens_tk) if kg > 0 else 0.0
        deg, deg_nota = _degradacion(r, tk, kg_est, kg_add)
        out.append(dict(r, _p=p, _afin=afin, _nota=nota, _cap=cap_sc, _cons=cons,
                        _ok=ok, _bloqueo=motivo, _vacio=vacio, _deg=deg, _deg_nota=deg_nota,
                        _disp=disp, _kg_est=kg_est, _lts_est=lts_est,
                        _cap_kg=disp * dens_tk))
    for r in out:
        r["_hist"] = (r["_p"] / p_max) if p_max > 0 else 0.0
        r["_base"] = (W_HIST * r["_hist"] + W_AFIN * r["_afin"] +
                      W_CAP * r["_cap"] + W_CONS * r["_cons"])
        # la degradación descuenta proporcionalmente: un tanque limpio que se
        # ensucia pierde casi todo el puntaje aunque tenga historial y espacio.
        r["_score"] = max(0.001, r["_base"] * (1.0 - DEG_FACTOR * r["_deg"]))
        if not r["_ok"]:
            r["_score"] = -1.0
        elif r["_disp"] < DISP_MIN_LTS:
            r["_score"] *= 0.15
    out.sort(key=lambda x: (x["_score"], x["_disp"]), reverse=True)
    return out


def _sugerir(rank, kg, dens):
    """Hasta 7 tanques (SOL-0009). Se elige el mejor; si no absorbe todo, se van
    sumando más ponderando el score por cuánto del resto cubre cada uno (cubrir
    el 100% no puede imponerse sobre la calidad). Entre los elegidos se llena
    primero el más cargado (regla de planta).

    El reparto respeta SIEMPRE el espacio disponible de cada tanque: nunca se
    asignan más kg de los que el tanque puede recibir. Lo que no entra queda en
    '_falta' y bloquea la confirmación hasta que el operario lo resuelva.
    """
    viables = [r for r in rank if r["_score"] > 0]
    if not viables:
        return []
    litros = (kg / dens) if dens else 0.0
    eleg = [viables[0]]
    resto_lts = litros - max(0.0, viables[0]["_disp"])
    pool = list(viables[1:])
    while resto_lts > 0.5 and pool and len(eleg) < 7:
        def _sel(x):
            cob = min(1.0, max(0.0, x["_disp"]) / resto_lts) if resto_lts > 0 else 1.0
            return x["_score"] * (0.5 + 0.5 * cob)
        tx = max(pool, key=_sel)
        pool = [x for x in pool if x is not tx]
        if max(0.0, tx["_disp"]) <= 0:
            continue
        eleg.append(tx)
        resto_lts -= max(0.0, tx["_disp"])

    # reparto: el más cargado primero, cada uno hasta el tope de su espacio
    orden = sorted(eleg, key=lambda x: x["_lts_est"], reverse=True)
    out, restante = [], float(kg)
    for t in orden:
        capk = max(0.0, t["_disp"] * dens)
        kgi = round(min(restante, capk), 1)
        if kgi <= 0.5:
            continue
        restante = round(max(0.0, restante - kgi), 1)
        out.append(dict(t, _kg=kgi, _orden=len(out) + 1, _falta=0.0))
    if not out:
        out = [dict(orden[0], _kg=0.0, _orden=1, _falta=0.0)]
    out[0]["_falta"] = round(max(0.0, restante if len(out) else kg), 1)
    return out


def _porque(r):
    return ("hist %d mov (%s) · afinidad %s · espacio %s L%s%s"
            % (int(_f(r.get("hist_n")) or 0),
               "{:.0%}".format(r["_hist"]),
               "{:.0%}".format(r["_afin"]),
               _n(r["_disp"], 0),
               (" · " + r["_nota"]) if r.get("_nota") else "",
               (" · ⚠️ " + r["_deg_nota"]) if r.get("_deg_nota") else "")
            + ((" · ≈ %s por mediana (sin medición)" % ", ".join(r["_imput"]))
               if r.get("_imput") else ""))


# ---------------------------------------------------------------- escritura

def _mezclar(tq, tk, kg_antes, kg_add):
    """Ponderado por kg. Tanque vacío -> parámetros del ticket."""
    mapa = [("acidez_pct", "acidez"), ("agua_pct", "agua"), ("sedimentos_pct", "sed"),
            ("densidad_g_ml", "dens"), ("ppm_azufre", "azufre"), ("ppm_fosforo", "fosforo")]
    antes, aporte, despues = {}, {}, {}
    vacio = kg_antes < VACIO_KG
    for col, ck in mapa:
        a, b = _f(tq.get(col)), _f(tk.get(ck))
        antes[col] = a
        aporte[col] = b
        if vacio:
            despues[col] = b if b is not None else a
        elif b is None:
            despues[col] = a
        elif a is None:
            despues[col] = b
        else:
            despues[col] = round((a * kg_antes + b * kg_add) / (kg_antes + kg_add), 4)
    return antes, aporte, despues, vacio


def _snap_restar(cur, tk, idt, kg_m, lts_m, uid, motivo):
    """Si este ticket dejó un snapshot medido en el tanque, lo corrige restando
    lo que había sumado (nunca por debajo de 0). Sin snapshot previo del ticket
    no toca nada (asignaciones viejas, anteriores a esta mejora)."""
    try:
        _kg = float(kg_m or 0)
        _lt = float(lts_m or 0)
    except Exception:
        return
    if idt is None or (_kg <= 0 and _lt <= 0):
        return
    cur.execute("SELECT count(*) FROM produccion.fact_stock_tanque "
                "WHERE id_tanque=%s AND observaciones LIKE %s",
                (int(idt), "Asignación AFE ticket " + str(tk) + "%"))
    if not cur.fetchone()[0]:
        return
    cur.execute(
        "INSERT INTO produccion.fact_stock_tanque "
        "(id_tanque, id_producto, medido_en, litros, kg, nivel_pct, id_usuario, observaciones) "
        "SELECT s.id_tanque, s.id_producto, now(), GREATEST(COALESCE(s.litros,0)-%s,0), "
        "       GREATEST(COALESCE(s.kg,0)-%s,0), "
        "       CASE WHEN t.capacidad_litros > 0 THEN "
        "            round(GREATEST(COALESCE(s.litros,0)-%s,0)/t.capacidad_litros*100.0, 1) END, "
        "       %s, %s "
        "FROM produccion.vw_stock_snapshot_ultimo s "
        "JOIN produccion.dim_tanque t ON t.id_tanque = s.id_tanque "
        "WHERE s.id_tanque=%s",
        (_lt, _kg, _lt, uid,
         "Asignación AFE ticket %s (%s): se restan %.0f L / %.0f kg" % (tk, motivo, _lt, _kg),
         int(idt)))


def _confirmar(conectar, USR, tk, cab, lineas, contexto, obs, med=None):
    """Escribe todo en una transacción. lineas: [{id_tanque,label,kg,fue_sugerido,motivo}]"""
    uid = int(USR.get("id_usuario") or 0)
    dens = cab["dens_prod"]
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.param_origen','MEZCLA_INGRESO',true)")

            # 1) anular movimientos automáticos previos del ticket + su espejo
            cur.execute(
                "UPDATE produccion.fact_movimiento_stock "
                "SET anulado = true, "
                "    observaciones = COALESCE(observaciones,'') || ' | reemplazado por Asignación AFE' "
                "WHERE regexp_replace(COALESCE(ticket_porteria,''),'\\.0+$','') = %s "
                "  AND COALESCE(anulado,false) = false "
                "  AND COALESCE(origen,'') IN ('lab_sync','sistema','asignacion_afe') "
                "RETURNING id_mov_stock, id_tanque, kg, litros, origen", (tk,))
            _viejos_full = cur.fetchall()
            _viejos = [r[0] for r in _viejos_full]
            cur.execute(
                "DELETE FROM produccion.fact_movimiento_tanque "
                "WHERE observaciones LIKE %s OR id_mov_stock = ANY(%s)",
                ("lab_sync ticket %" + tk, _viejos or [0]))
            # si una asignación previa de este ticket ya había sumado al stock
            # MEDIDO, restarlo antes de volver a sumar (reasignación sin duplicar)
            for _vm in _viejos_full:
                if str(_vm[4] or "") == "asignacion_afe":
                    _snap_restar(cur, tk, _vm[1], _vm[2], _vm[3], uid, "reasignado")

            # 2) cabecera
            cur.execute(
                "INSERT INTO produccion.fact_asignacion_afe "
                "(ticket, fecha_ticket, id_producto, producto, procedencia, kg_total, litros_total, "
                " densidad, acidez_pct, agua_pct, sedimentos_pct, ppm_azufre, ppm_fosforo, "
                " estado, sugerencia, origen_confirmacion, id_usuario, confirmado_en, observaciones, actualizado_en) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'CONFIRMADO',%s::jsonb,%s,%s,now(),%s,now()) "
                "ON CONFLICT (ticket) DO UPDATE SET "
                " fecha_ticket=EXCLUDED.fecha_ticket, id_producto=EXCLUDED.id_producto, "
                " producto=EXCLUDED.producto, procedencia=EXCLUDED.procedencia, "
                " kg_total=EXCLUDED.kg_total, litros_total=EXCLUDED.litros_total, densidad=EXCLUDED.densidad, "
                " acidez_pct=EXCLUDED.acidez_pct, agua_pct=EXCLUDED.agua_pct, "
                " sedimentos_pct=EXCLUDED.sedimentos_pct, ppm_azufre=EXCLUDED.ppm_azufre, "
                " ppm_fosforo=EXCLUDED.ppm_fosforo, estado='CONFIRMADO', sugerencia=EXCLUDED.sugerencia, "
                " origen_confirmacion=EXCLUDED.origen_confirmacion, id_usuario=EXCLUDED.id_usuario, "
                " confirmado_en=now(), observaciones=EXCLUDED.observaciones, actualizado_en=now() "
                "RETURNING id_asig",
                (tk, cab.get("fecha"), int(cab["id_producto"]), cab.get("producto"),
                 cab.get("procedencia"), cab["kg"], round(cab["kg"] / dens, 1), dens,
                 cab.get("acidez"), cab.get("agua"), cab.get("sed"),
                 cab.get("azufre"), cab.get("fosforo"),
                 json.dumps(cab.get("sugerencia") or [], default=str), contexto, uid, (obs or None)))
            id_asig = cur.fetchone()[0]

            cur.execute("DELETE FROM produccion.fact_asignacion_afe_linea WHERE id_asig=%s", (id_asig,))

            detalle = []
            for i, ln in enumerate(lineas):
                idt = int(ln["id_tanque"])
                kg = float(ln["kg"])
                lts = round(kg / dens, 1)

                # stock y parámetros del tanque ANTES de este movimiento — instantáneo al
                # confirmar. Si el operario marcó "vacío en realidad", se ignora el stock
                # del sistema (puede ser una medición vieja) y el ponderado parte de 0:
                # el tanque toma los parámetros del ticket.
                cur.execute(
                    "SELECT COALESCE(s.kg_estimado, s.kg_actual, 0), "
                    "       COALESCE(s.litros_estimado, s.litros_actual, 0), s.capacidad_litros "
                    "FROM produccion.vw_stock_tanque_actual s WHERE s.id_tanque=%s", (idt,))
                _r = cur.fetchone()
                kg_antes = float(_r[0]) if _r and _r[0] is not None else 0.0
                lts_antes = float(_r[1]) if _r and _r[1] is not None else 0.0
                _cap = float(_r[2]) if _r and _r[2] is not None else 0.0
                if ln.get("vacio_real"):
                    kg_antes = 0.0
                    lts_antes = 0.0
                cur.execute(
                    "SELECT acidez_pct, agua_pct, sedimentos_pct, densidad_g_ml, ppm_azufre, ppm_fosforo, "
                    "       COALESCE(parametros_extra,'{}'::jsonb) "
                    "FROM produccion.fact_param_tanque WHERE id_tanque=%s AND id_producto=%s",
                    (idt, int(cab["id_producto"])))
                _p = cur.fetchone()
                tq = {}
                if _p:
                    tq = {"acidez_pct": _p[0], "agua_pct": _p[1], "sedimentos_pct": _p[2],
                          "densidad_g_ml": _p[3], "ppm_azufre": _p[4], "ppm_fosforo": _p[5]}
                # tanque con líquido pero sin medición: se usa la mediana del parque
                # como valor previo, para que el ponderado no ignore la masa existente.
                _imp = []
                if med and kg_antes >= VACIO_KG:
                    for _c, _v in med.items():
                        if _f(tq.get(_c)) is None and _v is not None:
                            tq[_c] = _v
                            _imp.append(_c)

                antes, aporte, despues, vacio = _mezclar(tq, cab, kg_antes, kg)

                # 3) movimiento de stock
                cur.execute(
                    "INSERT INTO produccion.fact_movimiento_stock "
                    "(momento, tipo_movimiento, rol, sentido, id_producto, producto, fuente, "
                    " id_tanque, tanque_label, ticket_porteria, cantidad, unidad, kg, litros, "
                    " id_usuario, origen, observaciones, estado_mov, id_usuario_ejecuta, ejecutado_en) "
                    "VALUES (%s,'ENTRADA','MP',1,%s,%s,'PORTERIA',%s,%s,%s,%s,'KG',%s,%s,%s,"
                    " 'asignacion_afe',%s,'EJECUTADO',%s,now()) RETURNING id_mov_stock",
                    (cab.get("fecha"), int(cab["id_producto"]), cab.get("producto"),
                     idt, ln.get("label"), tk, kg, kg, lts, uid,
                     "Asignación AFE ticket %s (%d/%d)" % (tk, i + 1, len(lineas)), uid))
                id_mov = cur.fetchone()[0]

                # 4) espejo de tanque (los MP no los espeja el trigger)
                cur.execute(
                    "INSERT INTO produccion.fact_movimiento_tanque "
                    "(id_tanque, id_producto, tipo, litros, kg, ts, id_usuario, origen, observaciones, id_mov_stock) "
                    "VALUES (%s,%s,'IN',%s,%s,%s,%s,'ASIGNACION_AFE',%s,%s)",
                    (idt, int(cab["id_producto"]), lts, kg, cab.get("fecha"), uid,
                     "Asignación AFE ticket %s" % tk, id_mov))

                # 4') el stock MEDIDO del tanque se actualiza AL INSTANTE: nuevo
                # snapshot = lo que había + lo que descargó el camión. En tanques
                # con WeDo, la próxima lectura del sensor vuelve a ser la verdad;
                # en tanques sin sensor, éste ES el medido vigente.
                _kg_nuevo = round(kg_antes + kg, 1)
                _lts_nuevo = round(lts_antes + lts, 1)
                _pct_nuevo = round(_lts_nuevo / _cap * 100.0, 1) if _cap > 0 else None
                cur.execute(
                    "INSERT INTO produccion.fact_stock_tanque "
                    "(id_tanque, id_producto, medido_en, litros, kg, nivel_pct, "
                    " id_usuario, observaciones) "
                    "VALUES (%s,%s,now(),%s,%s,%s,%s,%s)",
                    (idt, int(cab["id_producto"]), _lts_nuevo, _kg_nuevo, _pct_nuevo, uid,
                     "Asignación AFE ticket %s: +%.0f L / +%.0f kg (previo %.0f L)"
                     % (tk, lts, kg, lts_antes)))

                # 5) parámetros del tanque (ponderado)
                extra = json.dumps({"mezcla_ticket": tk, "mezcla_kg": kg,
                                    "mezcla_kg_antes": round(kg_antes, 1),
                                    "mezcla_vacio": vacio, "mezcla_mov": id_mov,
                                    "mezcla_vacio_forzado": bool(ln.get("vacio_real")),
                                    "mezcla_imputados": _imp}, default=str)
                cur.execute(
                    "INSERT INTO produccion.fact_param_tanque "
                    "(id_tanque, id_producto, corriente, evaluado, ultima_evaluacion_ts, id_procesos_lab, "
                    " acidez_pct, agua_pct, sedimentos_pct, densidad_g_ml, ppm_azufre, ppm_fosforo, "
                    " parametros_extra, actualizado_en) "
                    "VALUES (%s,%s,%s,true,%s,NULL,%s,%s,%s,%s,%s,%s,%s::jsonb,now()) "
                    "ON CONFLICT (id_tanque, id_producto) DO UPDATE SET "
                    " corriente = COALESCE(EXCLUDED.corriente, produccion.fact_param_tanque.corriente), "
                    " evaluado = true, ultima_evaluacion_ts = EXCLUDED.ultima_evaluacion_ts, "
                    " id_procesos_lab = NULL, acidez_pct = EXCLUDED.acidez_pct, "
                    " agua_pct = EXCLUDED.agua_pct, sedimentos_pct = EXCLUDED.sedimentos_pct, "
                    " densidad_g_ml = EXCLUDED.densidad_g_ml, ppm_azufre = EXCLUDED.ppm_azufre, "
                    " ppm_fosforo = EXCLUDED.ppm_fosforo, "
                    " parametros_extra = COALESCE(produccion.fact_param_tanque.parametros_extra,'{}'::jsonb) || EXCLUDED.parametros_extra, "
                    " actualizado_en = now()",
                    (idt, int(cab["id_producto"]), cab.get("corriente"), cab.get("fecha"),
                     despues.get("acidez_pct"), despues.get("agua_pct"), despues.get("sedimentos_pct"),
                     despues.get("densidad_g_ml"), despues.get("ppm_azufre"), despues.get("ppm_fosforo"),
                     extra))

                # 6) línea
                cur.execute(
                    "INSERT INTO produccion.fact_asignacion_afe_linea "
                    "(id_asig, orden, id_tanque, tanque_label, kg, litros, id_mov_stock, "
                    " fue_sugerido, motivo_desvio, param_aplicado) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                    (id_asig, i + 1, idt, ln.get("label"), kg, lts, id_mov,
                     bool(ln.get("fue_sugerido")), (ln.get("motivo") or None),
                     json.dumps({"kg_antes": round(kg_antes, 1), "kg_aporte": kg,
                                 "vacio": vacio, "antes": antes, "aporte": aporte,
                                 "despues": despues, "imputados": _imp}, default=str)))
                detalle.append({"tanque": idt, "kg": kg, "mov": id_mov})

        audit.log("U", "fact_asignacion_afe", int(id_asig),
                  {"ticket": tk, "lineas": detalle, "contexto": contexto,
                   "anulados": _viejos})
    return id_asig


def _anular(conectar, USR, tk, id_asig):
    uid = int(USR.get("id_usuario") or 0)
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE produccion.fact_movimiento_stock SET anulado=true "
                "WHERE regexp_replace(COALESCE(ticket_porteria,''),'\\.0+$','')=%s "
                "  AND COALESCE(origen,'')='asignacion_afe' AND COALESCE(anulado,false)=false "
                "RETURNING id_mov_stock, id_tanque, kg, litros", (tk,))
            _movs = cur.fetchall()
            _ids = [r[0] for r in _movs] or [0]
            cur.execute("DELETE FROM produccion.fact_movimiento_tanque WHERE id_mov_stock = ANY(%s)", (_ids,))
            for _vm in _movs:
                _snap_restar(cur, tk, _vm[1], _vm[2], _vm[3], uid, "anulado")
            cur.execute("UPDATE produccion.fact_asignacion_afe SET estado='ANULADO', actualizado_en=now() "
                        "WHERE ticket=%s", (tk,))
        audit.log("U", "fact_asignacion_afe", int(id_asig or 0), {"ticket": tk, "accion": "ANULAR"})


# ---------------------------------------------------------------- UI

def _card_ticket(r):
    c = st.columns([1.1, 1.2, 1, 1, 1, 1])
    c[0].metric("Ticket", str(r["tk"]))
    c[1].metric("Procedencia", str(r.get("procedencia") or "—"))
    c[2].metric("Kg", _n(r.get("kg_ticket"), 0))
    c[3].metric("Acidez %", _n(r.get("prc_acidez"), 2))
    c[4].metric("Fósforo ppm", _n(r.get("ppm_fosforo"), 1))
    c[5].metric("Azufre ppm", _n(r.get("ppm_azufre"), 1))
    st.caption("Proveedor **%s** · calidad **%s** · corriente %s · agua %s %% · sedimentos %s %% · densidad %s"
               % (r.get("cliente") or "—", r.get("calidad_final_lab") or "—",
                  r.get("corriente") or "—", _n(r.get("prc_agua"), 2),
                  _n(r.get("prc_sedimentos"), 2), _n(r.get("densidad__g_ml"), 3)))


def _pendientes(USR, cat, conectar, contexto):
    c1, c2 = st.columns([1, 3])
    _dias = c1.number_input("Días hacia atrás", 1, 120, 15, key="asg_dias")
    df = _tickets(cat, int(_dias), "PEND")
    if df is None or df.empty:
        st.success("✅ No hay tickets de AFE pendientes de asignación en los últimos %d días." % int(_dias))
        return
    st.caption("**%d** ticket(s) de AFE esperando confirmación de tanque." % len(df))

    _res = df[["tk", "fecha", "calidad_final_lab", "procedencia", "cliente", "kg_ticket",
               "prc_acidez", "ppm_fosforo", "ppm_azufre"]].copy()
    _res.columns = ["Ticket", "Fecha", "Cal.", "Procedencia", "Proveedor", "Kg",
                    "Acidez %", "Fósforo ppm", "Azufre ppm"]
    st.dataframe(_res, use_container_width=True, hide_index=True, height=min(280, 40 + 35 * len(_res)))

    _opts = ["%s · %s · %s kg" % (r["tk"], r.get("procedencia") or "—", _n(r.get("kg_ticket"), 0))
             for _, r in df.iterrows()]
    _sel = st.selectbox("Ticket a asignar", _opts, key="asg_sel")
    r = df.iloc[_opts.index(_sel)].to_dict()

    st.divider()
    _card_ticket(r)

    _idp = r.get("id_producto")
    if _idp is None or (isinstance(_idp, float) and math.isnan(_idp)):
        st.error("No se pudo resolver el producto del ticket (calidad '%s'). "
                 "Revisá dic_producto_lab / dim_producto." % (r.get("calidad_final_lab") or ""))
        return
    _idp = int(_idp)
    kg = _f(r.get("kg_ticket")) or 0.0
    if kg <= 0:
        st.warning("El ticket todavía no tiene peso neto en portería (falta pesada de salida). "
                   "Podés asignar igual cargando los kg a mano.")
    dens = _densidad(cat, _idp)
    kg = _f(st.number_input("Kg totales a descargar", 0.0, 200000.0, float(round(kg, 1)),
                            step=10.0, key="asg_kg_%s" % r["tk"])) or 0.0
    litros = kg / dens if dens else 0.0

    tk_par = {"acidez": _f(r.get("prc_acidez")), "agua": _f(r.get("prc_agua")),
              "sed": _f(r.get("prc_sedimentos")), "azufre": _f(r.get("ppm_azufre")),
              "fosforo": _f(r.get("ppm_fosforo")), "dens": _f(r.get("densidad__g_ml"))}

    cand = _candidatos(cat, _idp)
    if cand is None or cand.empty:
        st.error("No hay tanques de acopio habilitados para este producto.")
        return
    med = _medianas(cand.to_dict("records"))
    rank = _rankear(cand, tk_par, litros, kg)
    sug = _sugerir(rank, kg, dens)
    if not sug:
        st.error("Ningún tanque cumple las condiciones. Revisá capacidades y dic_tanque_condicion.")
        return

    st.markdown("##### 🎯 Recomendación automática")
    for s in sug:
        st.markdown("**%d. %s** (%s) → **%s kg** · %s"
                    % (s["_orden"], s["nombre"], s["sector"], _n(s["_kg"], 0), _porque(s)))
    if len(sug) >= 2:
        st.caption("%d tanques: el ticket (%s L) no entra completo en el primero. "
                   "Se llena primero el más cargado hasta su capacidad y el resto sigue "
                   "en los otros." % (len(sug), _n(litros, 0)))
    _falta = sum(_f(s.get("_falta")) or 0.0 for s in sug)
    if _falta > 0.5:
        st.warning("⚠️ **%s kg no entran** en los tanques sugeridos: no hay espacio suficiente. "
                   "Elegí otros tanques o bajá los kg a descargar — la confirmación queda "
                   "bloqueada hasta que la suma cierre." % _n(_falta, 0))

    with st.expander("📊 Ranking completo de tanques (por qué se eligió)", expanded=False):
        _rk = pd.DataFrame([{
            "Tanque": x["nombre"], "Sector": x["sector"],
            "Score": round(x["_score"], 3),
            "Hist 30d": int(_f(x.get("hist_n")) or 0),
            "P(hist)": round(x["_hist"], 3),
            "Afinidad": round(x["_afin"], 3),
            "Espacio L": round(x["_disp"], 0),
            "Nivel %": round(x["_cons"] * 100, 1),
            "Degrada": x.get("_deg_nota") or "",
            "Estimado": ", ".join(x.get("_imput") or []),
            "Acidez tq": _f(x.get("acidez_pct")),
            "Fósforo tq": _f(x.get("ppm_fosforo")),
            "Azufre tq": _f(x.get("ppm_azufre")),
            "Bloqueo": x.get("_bloqueo") or "",
        } for x in rank])
        st.dataframe(_rk, use_container_width=True, hide_index=True)

    # ---- edición del operario
    st.markdown("##### ✍️ Confirmación")
    _todos = [x for x in rank]
    _lbl = {}
    for x in _todos:
        _lbl["%d · %s (%s L libres)" % (x["id_tanque"], x["nombre"], _n(x["_disp"], 0))] = x
    _keys = list(_lbl.keys())

    def _key_de(idt):
        for k, v in _lbl.items():
            if int(v["id_tanque"]) == int(idt):
                return k
        return _keys[0]

    _n_tq = st.radio("¿Cuántos tanques?", [1, 2, 3, 4, 5, 6, 7],
                     index=(min(len(sug), 7) - 1 if sug else 0),
                     horizontal=True, key="asg_ntq_%s" % r["tk"],
                     help="Con poco espacio de acopio el camión se reparte completando "
                          "tanques a tope (SOL-0009).")
    lineas = []
    # hasta 4 columnas por fila: con 5-7 tanques una sola fila queda ilegible
    _pf = int(_n_tq) if int(_n_tq) <= 4 else 4
    cols = []
    while len(cols) < int(_n_tq):
        cols.extend(st.columns(_pf))
    # 1º los tanques (hacen falta los DOS elegidos para calcular el reparto por defecto)
    _sel = []
    for i in range(int(_n_tq)):
        with cols[i]:
            _def = sug[i] if i < len(sug) else (sug[0] if sug else _todos[0])
            _k = st.selectbox("Tanque %d" % (i + 1), _keys,
                              index=_keys.index(_key_de(_def["id_tanque"])),
                              key="asg_tq%d_%s" % (i, r["tk"]))
            _sel.append(_lbl[_k])

    # Estado de los tildes "está VACÍO" ANTES de calcular el reparto: si el operario
    # marcó vacío, el espacio libre real de ese tanque es su CAPACIDAD completa y el
    # reparto por defecto se recalcula solo con ese dato (el click dispara un rerun y
    # el key de los inputs cambia, así los litros vuelven al reparto correcto).
    _vacs, _disp_eff = [], []
    for i in range(int(_n_tq)):
        _t = _sel[i]
        _v = bool(st.session_state.get("asg_vac%d_%s" % (i, r["tk"]), False))
        _vacs.append(_v)
        _cap_l = float(_t.get("cap_lts") or 0.0)
        _disp_eff.append(max(0.0, _cap_l if (_v and _cap_l > 0) else float(_t["_disp"])))

    litros_tk = (kg / dens) if dens > 0 else 0.0
    # Reparto por defecto (en LITROS) con 2 tanques: se llena hasta el tope el que
    # MENOS espacio efectivo tiene y el resto va al otro — la regla operativa de
    # planta. Si los elegidos son los sugeridos y no hay tildes de vacío, se respeta
    # el reparto de la sugerencia (considera calidad además de espacio).
    _defs_l = [litros_tk] * int(_n_tq)
    if int(_n_tq) == 1:
        # Un solo tanque: por defecto se carga hasta el TOPE de su espacio efectivo.
        # Si el ticket no entra entero, el control de abajo marca en rojo lo que falta
        # y ahí se pasa a 2 tanques.
        _defs_l = [round(min(litros_tk, _disp_eff[0]), 0)]
        if _disp_eff[0] + 1 < litros_tk:
            st.warning("El ticket trae %s L y en este tanque entran %s L: se precargó el "
                       "tope. Los %s L restantes necesitan un segundo tanque."
                       % (_n(litros_tk, 0), _n(_disp_eff[0], 0),
                          _n(litros_tk - _disp_eff[0], 0)))
    if int(_n_tq) >= 2:
        _ids_sel = {int(t["id_tanque"]) for t in _sel}
        _ids_sug = {int(x["id_tanque"]) for x in sug}
        if (len(sug) == int(_n_tq) and _ids_sel == _ids_sug
                and len(_ids_sel) == int(_n_tq) and not any(_vacs)):
            # los elegidos son exactamente los sugeridos: se respeta el reparto de la
            # sugerencia (considera calidad además de espacio)
            _map = {int(x["id_tanque"]): float(x.get("_kg", 0.0)) for x in sug}
            _defs_l = [(_map.get(int(t["id_tanque"]), 0.0) / dens if dens > 0 else 0.0)
                       for t in _sel]
        else:
            # regla operativa: se llenan A TOPE de menor a mayor espacio efectivo y
            # el de más espacio absorbe el resto
            _orden_i = sorted(range(int(_n_tq)), key=lambda i: _disp_eff[i])
            _defs_l = [0.0] * int(_n_tq)
            _resto = litros_tk
            for _j, _ii in enumerate(_orden_i):
                if _j == len(_orden_i) - 1:
                    _defs_l[_ii] = round(max(_resto, 0.0), 0)
                else:
                    _l1 = round(min(_resto, _disp_eff[_ii]), 0)
                    _defs_l[_ii] = _l1
                    _resto = max(_resto - _l1, 0.0)
    # el key incluye tanques elegidos + tildes de vacío: cambiar cualquiera de los
    # dos rehace el reparto por defecto (si no, se arrastraban valores viejos)
    _sig = ("_".join(str(int(t["id_tanque"])) for t in _sel)
            + "_v" + "".join("1" if v else "0" for v in _vacs))
    for i in range(int(_n_tq)):
        with cols[i]:
            _t = _sel[i]
            _li = st.number_input("Litros a tanque %d" % (i + 1), 0.0, 300000.0,
                                  float(round(_defs_l[i], 0)), step=500.0,
                                  key="asg_lt%d_%s_%s" % (i, r["tk"], _sig))
            _kgi = round(_li * dens, 1)
            st.caption("≈ **%s kg** (densidad %.3f)" % (_n(_kgi, 0), dens))
            _fue = any(int(x["id_tanque"]) == int(_t["id_tanque"]) for x in sug)
            _mot = ""
            if not _fue:
                _mot = st.selectbox("Motivo del desvío", MOTIVOS, key="asg_mot%d_%s" % (i, r["tk"]))
            if _disp_eff[i] < _li - 1:
                st.warning("Excede el espacio libre (%s L máx.)" % _n(_disp_eff[i], 0))
            # transparencia del ponderado: sobre cuántos kg previos va a mezclar. El stock
            # del sistema puede estar viejo — el operario que tiene el tanque adelante
            # es quien lo sabe.
            _kg_prev = float(_t.get("_kg_est") or 0.0)
            if _vacs[i]:
                st.caption("Marcado **VACÍO**: espacio libre = capacidad completa "
                           "(%s L) y el ponderado parte de 0 kg." % _n(_disp_eff[i], 0))
            else:
                st.caption("Pondera sobre **%s kg previos** según el sistema." % _n(_kg_prev, 0))
            _vac = False
            if _kg_prev > VACIO_KG:
                _vac = st.checkbox("⚠️ El tanque está VACÍO en realidad",
                                   key="asg_vac%d_%s" % (i, r["tk"]),
                                   help="El stock del sistema está desactualizado y el tanque "
                                        "está vacío: al marcarlo, el espacio libre pasa a ser la "
                                        "capacidad completa, el reparto se recalcula solo y el "
                                        "tanque toma los parámetros del ticket sin ponderar "
                                        "contra stock fantasma. Queda registrado. Avisá igual "
                                        "que falta la medición.")
            lineas.append({"id_tanque": int(_t["id_tanque"]),
                           "label": "%d · %s" % (int(_t["id_tanque"]), _t["nombre"]),
                           "kg": float(_kgi), "litros": float(_li),
                           "fue_sugerido": _fue, "motivo": _mot,
                           "vacio_real": bool(_vac), "_tq": _t})

    _suma = sum(x["kg"] for x in lineas)
    _suma_l = sum(x.get("litros", 0.0) for x in lineas)
    _dif = round(kg - _suma, 1)
    if abs(_dif) <= max(1.0, kg * 0.002):
        st.success("✅ **Ticket completo:** %s L asignados ≈ %s kg (ticket: %s kg)."
                   % (_n(_suma_l, 0), _n(_suma, 0), _n(kg, 0)))
    elif _dif > 0:
        st.error("Faltan **%s kg** (≈ %s L) para completar el ticket: asignados %s L ≈ %s kg "
                 "de %s kg." % (_n(_dif, 0), _n(_dif / dens if dens > 0 else 0, 0),
                                _n(_suma_l, 0), _n(_suma, 0), _n(kg, 0)))
    else:
        st.error("Se asignó **%s kg de más** (≈ %s L): asignados %s L ≈ %s kg y el ticket "
                 "trae %s kg." % (_n(-_dif, 0), _n(-_dif / dens if dens > 0 else 0, 0),
                                  _n(_suma_l, 0), _n(_suma, 0), _n(kg, 0)))
    _rep = len({x["id_tanque"] for x in lineas}) < len(lineas)
    if _rep:
        st.error("Hay tanques repetidos. Elegí tanques distintos o bajá la cantidad.")

    # ---- previsualización del impacto en la calidad del tanque
    with st.expander("🧪 Impacto en los parámetros del tanque (antes → después)", expanded=True):
        for i, ln in enumerate(lineas):
            _t = ln["_tq"]
            antes, aporte, despues, vacio = _mezclar(_t, tk_par, _f(_t.get("kg_est")) or 0.0, ln["kg"])
            st.markdown("**%s** — %s kg en tanque + %s kg del ticket%s"
                        % (_t["nombre"], _n(_t.get("kg_est"), 0), _n(ln["kg"], 0),
                           "  ·  _tanque vacío: toma los parámetros del ticket_" if vacio else
                           "  ·  _promedio ponderado por kg_"))
            if _t.get("_imput"):
                st.caption("≈ El tanque no tiene medición de %s: se usa la mediana del parque "
                           "como valor previo para el ponderado." % ", ".join(_t["_imput"]))
            _tabla = []
            for _c, _et in [("acidez_pct", "Acidez %"), ("ppm_fosforo", "Fósforo ppm"),
                            ("ppm_azufre", "Azufre ppm"), ("agua_pct", "Agua %"),
                            ("sedimentos_pct", "Sedimentos %"), ("densidad_g_ml", "Densidad")]:
                _tabla.append({"Parámetro": _et, "Tanque antes": antes.get(_c),
                               "Ticket": aporte.get(_c), "Tanque después": despues.get(_c)})
            st.dataframe(pd.DataFrame(_tabla), use_container_width=True, hide_index=True)

    _obs = st.text_input("Observación (opcional)", key="asg_obs_%s" % r["tk"])
    _bloq = (abs(_dif) > 1) or _rep or kg <= 0
    if st.button("✅ Confirmar asignación", type="primary", disabled=_bloq,
                 key="asg_ok_%s" % r["tk"], use_container_width=True):
        cab = {"fecha": r.get("fecha_entrada") or r.get("fecha"), "id_producto": _idp,
               "producto": r.get("calidad_final_lab") and ("AFE-" + str(r.get("calidad_final_lab"))) or "AFE",
               "procedencia": r.get("procedencia"), "kg": kg, "dens_prod": dens,
               "corriente": r.get("corriente"),
               "acidez": tk_par["acidez"], "agua": tk_par["agua"], "sed": tk_par["sed"],
               "azufre": tk_par["azufre"], "fosforo": tk_par["fosforo"], "dens": tk_par["dens"],
               "sugerencia": [{"orden": s["_orden"], "id_tanque": int(s["id_tanque"]),
                               "tanque": s["nombre"], "kg": s["_kg"], "score": round(s["_score"], 3),
                               "hist_n": int(_f(s.get("hist_n")) or 0),
                               "afinidad": round(s["_afin"], 3)} for s in sug]}
        try:
            _limpias = [{k: v for k, v in x.items() if k != "_tq"} for x in lineas]
            _confirmar(conectar, USR, str(r["tk"]), cab, _limpias, contexto, _obs,
                       med)
            st.success("Asignación confirmada para el ticket %s." % r["tk"])
            cat.clear()
            st.rerun()
        except Exception as e:
            st.error("No se pudo confirmar: %s" % e)
            import traceback
            with st.expander("Detalle técnico"):
                st.code(traceback.format_exc())


def _confirmadas(USR, cat, conectar, contexto):
    c1, c2 = st.columns([1, 3])
    _dias = c1.number_input("Días hacia atrás", 1, 180, 30, key="asgc_dias")
    df = cat(
        "SELECT a.ticket AS \"Ticket\", a.fecha_ticket AS \"Fecha\", a.producto AS \"Producto\", "
        "       a.procedencia AS \"Procedencia\", a.kg_total AS \"Kg\", a.estado AS \"Estado\", "
        "       string_agg(l.tanque_label || ' (' || round(l.kg)::text || ' kg)', '  +  ' ORDER BY l.orden) AS \"Tanques\", "
        "       BOOL_AND(COALESCE(l.fue_sugerido,false)) AS \"Fue el sugerido\", "
        "       string_agg(DISTINCT COALESCE(l.motivo_desvio,''), ', ') AS \"Motivo desvío\", "
        "       a.origen_confirmacion AS \"Confirmó desde\", u.nombre AS \"Usuario\", "
        "       a.confirmado_en AS \"Confirmado\", a.observaciones AS \"Obs\" "
        "FROM produccion.fact_asignacion_afe a "
        "LEFT JOIN produccion.fact_asignacion_afe_linea l ON l.id_asig = a.id_asig "
        "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = a.id_usuario "
        "WHERE a.confirmado_en >= now() - interval '%s days' "
        "GROUP BY a.id_asig, u.nombre ORDER BY a.confirmado_en DESC" % int(_dias))
    if df is None or df.empty:
        st.info("Todavía no hay asignaciones confirmadas en el período.")
        return
    _ok = int(df["Fue el sugerido"].fillna(False).sum())
    k1, k2, k3 = st.columns(3)
    k1.metric("Asignaciones", len(df))
    k2.metric("Siguieron la sugerencia", "%d (%.0f%%)" % (_ok, 100.0 * _ok / max(len(df), 1)))
    k3.metric("Kg asignados", _n(df["Kg"].sum(), 0))
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    _tks = [str(t) for t in df["Ticket"].tolist()]
    _t = st.selectbox("Revertir la asignación de un ticket", [""] + _tks, key="asgc_rev")
    if _t and st.button("↩️ Anular asignación del ticket %s" % _t, key="asgc_rev_btn"):
        try:
            _ia = cat("SELECT id_asig FROM produccion.fact_asignacion_afe WHERE ticket=%s", (_t,))
            _anular(conectar, USR, _t, int(_ia.iloc[0, 0]) if _ia is not None and not _ia.empty else 0)
            st.success("Asignación anulada. El ticket vuelve a la bandeja de pendientes.")
            cat.clear()
            st.rerun()
        except Exception as e:
            st.error("No se pudo anular: %s" % e)


def _trazabilidad(USR, cat, conectar):
    """Cómo van cambiando los parámetros de cada tanque y por qué."""
    st.markdown("##### 🧪 Trazabilidad de parámetros de tanques")
    st.caption("Cada cambio de parámetros con su origen: medición directa de laboratorio, "
               "carga manual, o mezcla ponderada al descargar un ingreso de AFE.")
    c1, c2, c3 = st.columns([1.4, 1.4, 1])
    _tqs = cat("SELECT t.id_tanque, t.nombre, t.sector FROM produccion.dim_tanque t "
               "WHERE COALESCE(t.activo,true) AND EXISTS (SELECT 1 FROM produccion.fact_param_tanque_hist h "
               "WHERE h.id_tanque=t.id_tanque) ORDER BY t.sector, t.nombre")
    _opts = ["(todos)"] + ["%d · %s" % (int(x["id_tanque"]), x["nombre"]) for _, x in _tqs.iterrows()]
    _sel = c1.selectbox("Tanque", _opts, key="tzp_tq")
    _org = c2.multiselect("Origen", list(ORIGEN_LBL.keys()),
                          default=list(ORIGEN_LBL.keys()), key="tzp_org")
    _dias = c3.number_input("Días", 1, 365, 45, key="tzp_dias")

    _w = ["h.registrado_en >= now() - interval '%d days'" % int(_dias)]
    if _sel != "(todos)":
        _w.append("h.id_tanque = %d" % int(_sel.split("·")[0].strip()))
    if _org:
        _w.append("COALESCE(h.origen,'MANUAL_LAB') IN (%s)" % ",".join("'%s'" % o for o in _org))
    sql = (
        "SELECT h.registrado_en, t.nombre AS tanque, t.sector, p.codigo_producto AS producto, "
        "       COALESCE(h.origen,'MANUAL_LAB') AS origen, "
        "       h.acidez_pct, h.agua_pct, h.sedimentos_pct, h.ppm_azufre, h.ppm_fosforo, h.densidad_g_ml, "
        "       h.id_procesos_lab, u.nombre AS usuario, "
        "       h.parametros_extra->>'mezcla_ticket' AS ticket_mezcla, "
        "       (h.parametros_extra->>'mezcla_kg')::numeric AS kg_mezcla, "
        "       (h.parametros_extra->>'mezcla_kg_antes')::numeric AS kg_antes, "
        "       lag(h.acidez_pct)  OVER w AS acidez_prev, "
        "       lag(h.ppm_fosforo) OVER w AS fosforo_prev, "
        "       lag(h.ppm_azufre)  OVER w AS azufre_prev "
        "FROM produccion.fact_param_tanque_hist h "
        "JOIN produccion.dim_tanque t ON t.id_tanque = h.id_tanque "
        "LEFT JOIN produccion.dim_producto p ON p.id_producto = h.id_producto "
        "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = h.id_usuario "
        "WHERE " + " AND ".join(_w) + " "
        "WINDOW w AS (PARTITION BY h.id_tanque, h.id_producto ORDER BY h.registrado_en) "
        "ORDER BY h.registrado_en DESC LIMIT 800")
    df = cat(sql)
    if df is None or df.empty:
        st.info("Sin movimientos de parámetros en el período.")
        return

    _v = df.copy()
    _v["Origen"] = _v["origen"].map(lambda o: ORIGEN_LBL.get(o, o))
    _v["Por qué"] = _v.apply(
        lambda x: ("ticket %s · %s kg sobre %s kg previos" %
                   (x["ticket_mezcla"], _n(x["kg_mezcla"], 0), _n(x["kg_antes"], 0)))
        if x["origen"] == "MEZCLA_INGRESO" and x["ticket_mezcla"]
        else ("análisis lab id %s" % int(x["id_procesos_lab"]) if _f(x["id_procesos_lab"]) else ""), axis=1)
    for _c, _p, _et in [("acidez_pct", "acidez_prev", "Δ Acidez"),
                        ("ppm_fosforo", "fosforo_prev", "Δ Fósforo"),
                        ("ppm_azufre", "azufre_prev", "Δ Azufre")]:
        _v[_et] = (pd.to_numeric(_v[_c], errors="coerce") -
                   pd.to_numeric(_v[_p], errors="coerce")).round(2)

    _cols = ["registrado_en", "tanque", "sector", "producto", "Origen", "Por qué",
             "acidez_pct", "Δ Acidez", "ppm_fosforo", "Δ Fósforo", "ppm_azufre", "Δ Azufre",
             "agua_pct", "sedimentos_pct", "densidad_g_ml", "usuario"]
    _v = _v[_cols]
    _v.columns = ["Fecha", "Tanque", "Sector", "Producto", "Origen", "Por qué",
                  "Acidez %", "Δ Acidez", "Fósforo ppm", "Δ Fósforo", "Azufre ppm", "Δ Azufre",
                  "Agua %", "Sedim %", "Densidad", "Usuario"]
    st.dataframe(_v, use_container_width=True, hide_index=True, height=460)

    k = df.groupby("origen").size().to_dict()
    cols = st.columns(len(ORIGEN_LBL))
    for i, (o, lbl) in enumerate(ORIGEN_LBL.items()):
        cols[i].metric(lbl, int(k.get(o, 0)))

    if _sel != "(todos)":
        _g = df.sort_values("registrado_en").copy()
        for _c, _et in [("acidez_pct", "Acidez %"), ("ppm_fosforo", "Fósforo ppm"),
                        ("ppm_azufre", "Azufre ppm")]:
            _g[_et] = pd.to_numeric(_g[_c], errors="coerce")
        _ch = _g.set_index("registrado_en")[["Acidez %", "Fósforo ppm", "Azufre ppm"]]
        st.line_chart(_ch)

    st.download_button("⬇️ Descargar CSV", _v.to_csv(index=False).encode("utf-8-sig"),
                       "trazabilidad_parametros_tanques.csv", "text/csv", key="tzp_dl")


# ---------------------------------------------------------------- entrada

def render(USR, cat, conectar, contexto="PLANTA"):
    st.markdown("### 🛢️ Asignación de tanques a AFEs")
    _opts = ["📥 Pendientes", "✅ Confirmadas"]
    if contexto == "PLANIFICACION":
        _opts.append("🧪 Trazabilidad de parámetros")
    try:
        _v = st.segmented_control("Vista", _opts, default=_opts[0],
                                  key="asg_view_sc_%s" % contexto, label_visibility="collapsed")
    except Exception:
        _v = st.radio("Vista", _opts, horizontal=True, key="asg_view_rd_%s" % contexto)
    _v = _v or _opts[0]
    st.write("")
    if _v.startswith("📥"):
        _pendientes(USR, cat, conectar, contexto)
    elif _v.startswith("✅"):
        _confirmadas(USR, cat, conectar, contexto)
    else:
        _trazabilidad(USR, cat, conectar)
