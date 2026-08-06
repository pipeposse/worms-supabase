# -*- coding: utf-8 -*-
"""Proyecto ISCC — generador de planilla de camiones.

Genera viajes sinteticos consistentes por cliente (kg prorrateados, remitos
correlativos, patentes con separacion horaria minima) y permite exportar la
planilla combinando el bloque generado con el trafico real de porteria.
"""
import io
import json
import random
import calendar
import datetime as _dt

import pandas as pd
import streamlit as st

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

COLS_EXPORT = ["FECHA", "HORARIO ENTRADA", "PROCEDENCIA", "CLIENTE", "DOCUMENTO",
               "NÚMERO", "PRODUCTO", "NETO REMITO", "NETO WORMS", "COSTO", "TOTAL",
               "DIFERENCIA DE PESO", "TRANSPORTE", "PAT. CHASIS/ACOP.", "CHOFER"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fmt_kg(x):
    try:
        v = float(x)
    except Exception:
        return "-"
    if v != v:
        return "-"
    return "{:,.0f}".format(v).replace(",", ".")


def _fmt_money(x):
    try:
        v = float(x)
    except Exception:
        return "-"
    if v != v:
        return "-"
    return "$ " + "{:,.0f}".format(v).replace(",", ".")


def _to_excel(hojas):
    """hojas: lista de (nombre, DataFrame). Devuelve bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nom, df in hojas:
            df.to_excel(xw, sheet_name=str(nom)[:31], index=False)
    return buf.getvalue()


def _clientes(cat):
    return cat("""
        SELECT id_cliente, nombre, producto, documento, costo, prefijo_remito,
               ultimo_remito, peso_prorrateo, neto_min, neto_max, activo
          FROM produccion.iscc_cliente
         ORDER BY nombre
    """, None)


def _camiones(cat):
    return cat("""
        SELECT c.id_camion, c.id_cliente, cl.nombre AS cliente, c.transporte,
               c.patente, c.chofer, c.activo
          FROM produccion.iscc_camion c
          JOIN produccion.iscc_cliente cl ON cl.id_cliente = c.id_cliente
         ORDER BY cl.nombre, c.patente
    """, None)


def _feriados(cat):
    return cat("SELECT fecha, nombre FROM produccion.iscc_feriado ORDER BY fecha", None)


def _corridas(cat):
    return cat("""
        SELECT id_corrida, anio, mes, kg_total, n_viajes, kg_generados, estado,
               nota, creado_por, creado_en
          FROM produccion.iscc_corrida
         ORDER BY id_corrida DESC
    """, None)


def _viajes(cat, id_corrida):
    return cat("""
        SELECT fecha, hora, procedencia, cliente, documento, numero, producto,
               neto_remito, neto_worms, costo, total, diferencia_peso,
               transporte, patente, chofer
          FROM produccion.iscc_viaje
         WHERE id_corrida = %s
         ORDER BY fecha, hora, cliente
    """, (int(id_corrida),))


# --------------------------------------------------------------------------
# generador
# --------------------------------------------------------------------------
def _dias_habiles(anio, mes, feriados, sin_domingos, sin_sabados):
    ndias = calendar.monthrange(anio, mes)[1]
    out = []
    for d in range(1, ndias + 1):
        f = _dt.date(anio, mes, d)
        if sin_domingos and f.weekday() == 6:
            continue
        if sin_sabados and f.weekday() == 5:
            continue
        if f in feriados:
            continue
        out.append(f)
    return out


def _reparto_viajes(n_viajes, dias, cap_dia, rnd, piso=1):
    """Reparte n_viajes entre los dias respetando el tope diario."""
    nd = len(dias)
    if nd == 0:
        return []
    base = [n_viajes // nd] * nd
    for i in range(n_viajes % nd):
        base[i] += 1
    # jitter conservando el total
    for _ in range(nd * 3):
        i = rnd.randrange(nd)
        j = rnd.randrange(nd)
        if i == j:
            continue
        if base[i] > 1 and base[j] + 1 <= cap_dia:
            base[i] -= 1
            base[j] += 1
    # respeta el tope
    exceso = 0
    for i in range(nd):
        if base[i] > cap_dia:
            exceso += base[i] - cap_dia
            base[i] = cap_dia
    i = 0
    while exceso > 0 and i < nd * 5:
        k = i % nd
        if base[k] < cap_dia:
            base[k] += 1
            exceso -= 1
        i += 1
    # evita dias con muy pocos viajes: los sube al piso o los deja vacios
    piso = max(1, min(int(piso), cap_dia))
    for _ in range(nd * 2):
        flojos = [i for i in range(nd) if 0 < base[i] < piso]
        if not flojos:
            break
        i = flojos[0]
        donantes = [j for j in range(nd) if base[j] > piso]
        if donantes:
            j = rnd.choice(donantes)
            base[j] -= 1
            base[i] += 1
        else:
            receptores = [j for j in range(nd) if j != i and 0 < base[j] < cap_dia]
            if not receptores:
                break
            j = rnd.choice(receptores)
            base[j] += 1
            base[i] -= 1
    return base


def _horarios(n, h_ini, h_fin, sep_min, rnd):
    """n horarios distintos dentro del rango, separados >= sep_min minutos."""
    ini = h_ini * 60
    fin = h_fin * 60 + 59
    span = fin - ini
    if n <= 0:
        return []
    if sep_min * (n - 1) > span:
        sep_min = max(1, span // max(1, n - 1))
    for _ in range(60):
        cand = sorted(rnd.sample(range(ini, fin + 1), min(n, span + 1)))
        ok = True
        for i in range(1, len(cand)):
            if cand[i] - cand[i - 1] < sep_min:
                ok = False
                break
        if ok:
            return cand
    # fallback determinista: reparto uniforme con jitter chico
    paso = span / float(max(1, n))
    out = []
    for i in range(n):
        m = int(ini + paso * i + rnd.randint(0, max(0, int(paso) - 1)))
        out.append(min(fin, m))
    return sorted(set(out))


def _asignar_patentes(cam, ult_uso, dia, minutos, gap_h, rnd):
    """Asigna una patente distinta a cada horario del dia.

    Estrategia: se eligen los camiones mas descansados y se los ordena segun la
    hora del dia en que viajaron la ultima vez, de modo que quien salio temprano
    vuelva a salir temprano. Asi la separacion entre usos de la misma patente
    tiende a 24 h en lugar de caer a pocas horas entre el cierre de un dia y la
    apertura del siguiente. Devuelve [(camion, timestamp, gap_horas_o_None)].
    """
    n = len(minutos)
    if n <= 0:
        return []
    cands = []
    for _, c in cam.iterrows():
        cands.append((c, ult_uso.get(c["patente"])))
    lejano = _dt.datetime(1900, 1, 1)
    cands.sort(key=lambda t: t[1] or lejano)
    ventana = min(len(cands), n + 2)
    pool = cands[:ventana]
    rnd.shuffle(pool)
    eleg = pool[:n]

    def _tod(t):
        if t is None:
            return rnd.random() * 1440.0
        return t.hour * 60.0 + t.minute
    eleg.sort(key=lambda t: _tod(t[1]))

    ts = [_dt.datetime.combine(dia, _dt.time(m // 60, m % 60)) for m in minutos]

    def _gap(prev, t):
        if prev is None:
            return None
        return (t - prev).total_seconds() / 3600.0

    def _peor(orden):
        peor = 1e9
        for i in range(n):
            g = _gap(orden[i][1], ts[i])
            if g is not None and g < peor:
                peor = g
        return peor

    # pequenos intercambios al azar para que el orden no se repita todos los dias
    for _ in range(n * 2):
        if n < 2:
            break
        i = rnd.randrange(n)
        j = rnd.randrange(n)
        if i == j:
            continue
        antes = _peor(eleg)
        eleg[i], eleg[j] = eleg[j], eleg[i]
        if _peor(eleg) < min(antes, gap_h):
            eleg[i], eleg[j] = eleg[j], eleg[i]
    return [(eleg[i][0], ts[i], _gap(eleg[i][1], ts[i])) for i in range(n)]


def _netos_para_kg(objetivo, nmin, nmax, rnd, cap=None):
    """Lista de netos multiplo de 100 que suman ~objetivo.

    cap = cantidad maxima de viajes posibles (dias x camiones). Si el objetivo
    no entra en esa cantidad de viajes con el neto maximo, se devuelve el tope
    y el faltante queda expuesto como desvio.
    """
    lo = int(round(nmin / 100.0))
    hi = int(round(nmax / 100.0))
    if hi < lo:
        hi = lo
    prom = (lo + hi) / 2.0 * 100.0
    n = max(1, int(round(objetivo / prom)))
    # la cantidad de viajes tiene que permitir llegar al objetivo dentro del rango
    n_min = max(1, int(objetivo / (hi * 100.0)) + (1 if objetivo % (hi * 100.0) else 0))
    n_max = max(n_min, int(objetivo / (lo * 100.0)) if lo > 0 else n)
    n = max(n_min, min(n, n_max))
    if cap:
        n = min(n, int(cap))
    netos = [rnd.randint(lo, hi) * 100 for _ in range(n)]
    # ajuste iterativo del ultimo tramo para clavar el objetivo
    for _ in range(4000):
        dif = objetivo - sum(netos)
        if abs(dif) < 50:
            break
        i = rnd.randrange(len(netos))
        paso = 100 if dif > 0 else -100
        nuevo = netos[i] + paso
        if lo * 100 <= nuevo <= hi * 100:
            netos[i] = nuevo
    return netos


def generar(clientes, camiones, dias, params, semilla):
    """Devuelve (DataFrame viajes, dict diagnostico)."""
    rnd = random.Random(int(semilla))
    h_ini = int(params.get("hora_ini", 7))
    h_fin = int(params.get("hora_fin", 20))
    sep_min = int(params.get("sep_min", 3))
    gap_h = float(params.get("gap_patente_h", 12))
    vmin = int(params.get("viajes_min", 3))
    vmax = int(params.get("viajes_max", 7))
    tol_pasos = int(params.get("tol_pasos", 5))
    tol_paso = int(params.get("tol_paso", 20))
    salto_max = int(params.get("salto_remito", 3))

    filas = []
    diag = {"relajaciones": 0, "sin_gap": [], "clientes": [], "alertas": []}
    ult_uso = {}  # patente -> datetime del ultimo viaje

    for _, cli in clientes.iterrows():
        nombre = cli["nombre"]
        cam = camiones[(camiones["id_cliente"] == cli["id_cliente"]) &
                       (camiones["activo"] == True)]
        cam = cam.reset_index(drop=True)
        if len(cam) == 0:
            diag["alertas"].append("%s no tiene camiones activos: se omite." % nombre)
            continue
        objetivo = float(cli["_kg_objetivo"])
        cap_dia = min(vmax, len(cam))
        tope = len(dias) * cap_dia
        netos = _netos_para_kg(objetivo, float(cli["neto_min"]), float(cli["neto_max"]),
                               rnd, tope)
        rnd.shuffle(netos)
        n_viajes = len(netos)
        falta = objetivo - sum(netos)
        if abs(falta) > 100:
            diag["alertas"].append(
                "%s: con %d dias y %d camiones el tope es %d viajes y quedan %s kg "
                "sin asignar. Subi el neto maximo, agrega camiones o subi los viajes "
                "maximos por dia." % (nombre, len(dias), len(cam), tope, _fmt_kg(falta)))
        reparto = _reparto_viajes(n_viajes, dias, cap_dia, rnd, vmin)
        # piso de viajes por dia: dias con 0 quedan sin trafico (aceptable)
        numero = int(cli["ultimo_remito"])
        costo = float(cli["costo"])
        k = 0
        for idx_d, dia in enumerate(dias):
            nd = reparto[idx_d] if idx_d < len(reparto) else 0
            if nd <= 0:
                continue
            nd = min(nd, n_viajes - k)
            if nd <= 0:
                break
            horas = _horarios(nd, h_ini, h_fin, sep_min, rnd)
            nd = min(nd, len(horas))
            if nd <= 0:
                continue
            asign = _asignar_patentes(cam, ult_uso, dia, horas[:nd], gap_h, rnd)
            for j in range(len(asign)):
                cam_sel, ts, dh = asign[j]
                if dh is not None and dh < gap_h:
                    diag["relajaciones"] += 1
                    diag["sin_gap"].append({
                        "cliente": nombre, "patente": cam_sel["patente"],
                        "fecha": str(dia), "hora": ts.strftime("%H:%M"),
                        "gap_h": round(dh, 2)})
                p = cam_sel["patente"]
                ult_uso[p] = ts

                neto_r = int(netos[k])
                k += 1
                paso = rnd.randint(1, tol_pasos) * tol_paso
                if rnd.random() < 0.5:
                    paso = -paso
                neto_w = neto_r + paso
                numero += rnd.randint(1, salto_max)
                filas.append({
                    "FECHA": dia,
                    "HORARIO ENTRADA": ts.strftime("%H:%M:%S"),
                    "PROCEDENCIA": nombre,
                    "CLIENTE": nombre,
                    "DOCUMENTO": cli["documento"],
                    "NÚMERO": "%s-%s" % (cli["prefijo_remito"], str(numero).zfill(8)),
                    "PRODUCTO": cli["producto"],
                    "NETO REMITO": float(neto_r),
                    "NETO WORMS": float(neto_w),
                    "COSTO": costo,
                    "TOTAL": round(neto_r * costo, 2),
                    "DIFERENCIA DE PESO": float(neto_r - neto_w),
                    "TRANSPORTE": cam_sel["transporte"],
                    "PAT. CHASIS/ACOP.": p,
                    "CHOFER": cam_sel["chofer"],
                    "_id_cliente": int(cli["id_cliente"]),
                    "_id_camion": int(cam_sel["id_camion"]),
                    "_ultimo_remito": numero,
                })
            if k >= n_viajes:
                break
        diag["clientes"].append({
            "cliente": nombre, "viajes": k,
            "kg_objetivo": objetivo,
            "kg_generados": float(sum(netos[:k])),
            "camiones": len(cam), "ultimo_remito": numero})

    df = pd.DataFrame(filas)
    if len(df):
        df = df.sort_values(["FECHA", "HORARIO ENTRADA", "CLIENTE"]).reset_index(drop=True)
    return df, diag


# --------------------------------------------------------------------------
# validador
# --------------------------------------------------------------------------
def validar(df, params):
    reglas = []

    def add(ok, regla, detalle):
        reglas.append({"OK": "✅" if ok else "❌", "Regla": regla, "Detalle": detalle})

    if df is None or not len(df):
        return pd.DataFrame([{"OK": "❌", "Regla": "Sin datos", "Detalle": "-"}])

    d = df.copy()
    d["dt"] = pd.to_datetime(d["FECHA"].astype(str) + " " + d["HORARIO ENTRADA"].astype(str))

    mult = (d["NETO REMITO"] % 100 == 0).all()
    add(mult, "Neto remito multiplo de 100",
        "%d de %d cumplen" % (int((d["NETO REMITO"] % 100 == 0).sum()), len(d)))

    tol = (d["NETO REMITO"] - d["NETO WORMS"]).abs()
    tmax = params.get("tol_pasos", 5) * params.get("tol_paso", 20)
    add(bool((tol <= tmax).all()), "Tolerancia worms <= %d kg" % tmax,
        "max %d kg" % int(tol.max()))

    dif_ok = (d["DIFERENCIA DE PESO"] == d["NETO REMITO"] - d["NETO WORMS"]).all()
    add(bool(dif_ok), "Diferencia = remito - worms", "exacta" if dif_ok else "hay filas mal")

    tot_ok = ((d["TOTAL"] - d["NETO REMITO"] * d["COSTO"]).abs() < 0.01).all()
    add(bool(tot_ok), "Total = neto remito x costo", "exacto" if tot_ok else "hay filas mal")

    dom = pd.to_datetime(d["FECHA"]).dt.weekday
    add(bool((dom != 6).all()), "Sin domingos", "%d filas en domingo" % int((dom == 6).sum()))

    hh = d["HORARIO ENTRADA"].astype(str).str[:2].astype(int)
    add(bool((hh >= params.get("hora_ini", 7)).all() and (hh <= params.get("hora_fin", 20)).all()),
        "Horario dentro del rango", "%02d:00 a %02d:59" % (hh.min(), hh.max()))

    dup = d.groupby(["FECHA", "CLIENTE", "PAT. CHASIS/ACOP."]).size()
    add(bool((dup <= 1).all()), "Una patente por dia por cliente",
        "%d repeticiones" % int((dup - 1).clip(lower=0).sum()))

    gaps = []
    for p, g in d.groupby("PAT. CHASIS/ACOP."):
        g = g.sort_values("dt")
        gaps += list(g["dt"].diff().dropna().dt.total_seconds() / 3600.0)
    gmin = min(gaps) if gaps else 999.0
    gap_req = params.get("gap_patente_h", 12)
    add(gmin >= gap_req, "Separacion minima entre usos de la misma patente (%.0f h)" % gap_req,
        "minimo real %.2f h" % gmin)

    nu = d["NÚMERO"].duplicated().sum()
    add(nu == 0, "Numeros de remito unicos", "%d duplicados" % int(nu))

    return pd.DataFrame(reglas)


# --------------------------------------------------------------------------
# persistencia
# --------------------------------------------------------------------------
def _guardar_corrida(USR, conectar, anio, mes, kg_total, params, df, nota):
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO produccion.iscc_corrida
                    (anio, mes, kg_total, params, n_viajes, kg_generados, estado, nota, creado_por)
                VALUES (%s,%s,%s,%s,%s,%s,'BORRADOR',%s,%s)
                RETURNING id_corrida
            """, (int(anio), int(mes), float(kg_total), json.dumps(params, default=str),
                  int(len(df)), float(df["NETO REMITO"].sum()), nota or None,
                  str(USR.get("usuario") or USR.get("id_usuario"))))
            id_cor = cur.fetchone()[0]
            datos = []
            for _, r in df.iterrows():
                datos.append((
                    id_cor, int(r["_id_cliente"]), int(r["_id_camion"]),
                    r["FECHA"], r["HORARIO ENTRADA"], r["PROCEDENCIA"], r["CLIENTE"],
                    r["DOCUMENTO"], r["NÚMERO"], r["PRODUCTO"],
                    float(r["NETO REMITO"]), float(r["NETO WORMS"]), float(r["COSTO"]),
                    float(r["TOTAL"]), float(r["DIFERENCIA DE PESO"]),
                    r["TRANSPORTE"], r["PAT. CHASIS/ACOP."], r["CHOFER"]))
            cur.executemany("""
                INSERT INTO produccion.iscc_viaje
                    (id_corrida, id_cliente, id_camion, fecha, hora, procedencia, cliente,
                     documento, numero, producto, neto_remito, neto_worms, costo, total,
                     diferencia_peso, transporte, patente, chofer)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, datos)
            # avanza la numeracion de remitos por cliente
            for idc, sub in df.groupby("_id_cliente"):
                cur.execute("""
                    UPDATE produccion.iscc_cliente
                       SET ultimo_remito = %s, actualizado_en = now()
                     WHERE id_cliente = %s
                """, (int(sub["_ultimo_remito"].max()), int(idc)))
        audit.log("I", "iscc_corrida", str(id_cor),
                  {"anio": anio, "mes": mes, "viajes": int(len(df))})
        conn.commit()
    return id_cor


def _borrar_corrida(USR, conectar, id_cor):
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM produccion.iscc_corrida WHERE id_corrida = %s",
                        (int(id_cor),))
        audit.log("D", "iscc_corrida", str(id_cor), {"borrada": True})
        conn.commit()


def _upsert_cliente(USR, conectar, id_cliente, campos):
    if not campos:
        return
    sets = ", ".join(["%s = %%s" % k for k in campos.keys()])
    vals = list(campos.values()) + [int(id_cliente)]
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.iscc_cliente SET %s, actualizado_en = now() "
                        "WHERE id_cliente = %%s" % sets, vals)
        audit.log("U", "iscc_cliente", str(id_cliente), campos)
        conn.commit()


def _alta_camion(USR, conectar, id_cliente, transporte, patente, chofer):
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO produccion.iscc_camion (id_cliente, transporte, patente, chofer)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (id_cliente, patente)
                DO UPDATE SET transporte = EXCLUDED.transporte,
                              chofer = EXCLUDED.chofer, activo = true
                RETURNING id_camion
            """, (int(id_cliente), transporte.strip(), patente.strip().upper(),
                  (chofer or "").strip() or None))
            idc = cur.fetchone()[0]
        audit.log("I", "iscc_camion", str(idc),
                  {"patente": patente, "transporte": transporte})
        conn.commit()
    return idc


def _baja_camion(USR, conectar, id_camion, activo):
    with conectar(USR["id_usuario"]) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("UPDATE produccion.iscc_camion SET activo = %s WHERE id_camion = %s",
                        (bool(activo), int(id_camion)))
        audit.log("U", "iscc_camion", str(id_camion), {"activo": bool(activo)})
        conn.commit()


# --------------------------------------------------------------------------
# trafico real de porteria
# --------------------------------------------------------------------------
def _trafico_real(cat, anio, mes):
    ndias = calendar.monthrange(anio, mes)[1]
    d1 = "%04d-%02d-01" % (anio, mes)
    d2 = "%04d-%02d-%02d" % (anio, mes, ndias)
    q = """
        SELECT t.fecha, t.hora, t.area, t.procedencia, t.destino, t.producto,
               t.patente, t.patente_acopl, t.pesoneto,
               m.producto_iscc, COALESCE(f.costo, 0) AS costo
          FROM produccion.v_porteria_ticket t
          JOIN produccion.iscc_producto_map m
            ON upper(trim(m.producto_porteria)) = upper(trim(t.producto))
           AND m.incluir = true
          LEFT JOIN produccion.iscc_tarifa f
            ON upper(trim(f.nombre_cliente)) = upper(trim(t.procedencia))
         WHERE t.fecha BETWEEN %s AND %s
         ORDER BY t.fecha, t.hora
    """
    d = cat(q, (d1, d2))
    if d is None or not len(d):
        return pd.DataFrame(columns=COLS_EXPORT)
    out = pd.DataFrame()
    out["FECHA"] = pd.to_datetime(d["fecha"]).dt.date
    out["HORARIO ENTRADA"] = d["hora"].astype(str).str[:8]
    out["PROCEDENCIA"] = d["area"]
    out["CLIENTE"] = d["procedencia"]
    out["DOCUMENTO"] = ""
    out["NÚMERO"] = ""
    out["PRODUCTO"] = d["producto_iscc"]
    neto = pd.to_numeric(d["pesoneto"], errors="coerce").fillna(0).abs()
    out["NETO REMITO"] = float("nan")
    out["NETO WORMS"] = neto
    out["COSTO"] = pd.to_numeric(d["costo"], errors="coerce").fillna(0)
    out["TOTAL"] = (neto * out["COSTO"]).round(2)
    out["DIFERENCIA DE PESO"] = float("nan")
    out["TRANSPORTE"] = d["destino"]
    pat = d["patente"].fillna("").astype(str)
    aco = d["patente_acopl"].fillna("").astype(str)
    out["PAT. CHASIS/ACOP."] = [
        (a + "/" + b) if b.strip() else a for a, b in zip(pat, aco)]
    out["CHOFER"] = ""
    return out[COLS_EXPORT]


# --------------------------------------------------------------------------
# vistas
# --------------------------------------------------------------------------
def _vista_generar(USR, cat, conectar):
    cli = _clientes(cat)
    cam = _camiones(cat)
    fer = _feriados(cat)
    if cli is None or not len(cli):
        st.warning("No hay clientes ISCC cargados.")
        return
    cli = cli[cli["activo"] == True].reset_index(drop=True)

    hoy = _dt.date.today()
    c1, c2, c3, c4 = st.columns(4)
    anio = c1.number_input("Año", min_value=2020, max_value=2100,
                           value=int(hoy.year), step=1, key="iscc_anio")
    mes = c2.selectbox("Mes", list(range(1, 13)), index=int(hoy.month) - 1,
                       format_func=lambda m: MESES[m - 1], key="iscc_mes")
    kg_total = c3.number_input("Kg totales del mes", min_value=0.0,
                               value=22712500.0, step=100000.0,
                               format="%.0f", key="iscc_kg")
    semilla = c4.number_input("Semilla", min_value=0, max_value=999999,
                              value=int(anio) * 100 + int(mes), step=1,
                              key="iscc_seed",
                              help="Misma semilla + mismos parametros = misma planilla.")

    with st.expander("⚙️ Parametros del calendario y de los viajes", expanded=False):
        p1, p2, p3, p4 = st.columns(4)
        sin_dom = p1.checkbox("Sin domingos", value=True, key="iscc_sd")
        sin_sab = p1.checkbox("Sin sabados", value=False, key="iscc_ss")
        usar_fer = p1.checkbox("Excluir feriados", value=True, key="iscc_sf")
        h_ini = p2.number_input("Hora desde", 0, 23, 7, key="iscc_hi")
        h_fin = p2.number_input("Hora hasta", 0, 23, 20, key="iscc_hf")
        sep_min = p2.number_input("Separacion minima entre viajes (min)", 1, 120, 3,
                                  key="iscc_sep")
        gap_h = p3.number_input("Horas minimas entre usos de la misma patente", 1.0, 72.0,
                                12.0, step=1.0, key="iscc_gap",
                                help="Una misma patente no puede volver a entrar antes de "
                                     "estas horas. Con 12 h la mediana real queda cerca de "
                                     "24 h. Si lo subis mucho y el mes exige muchos viajes, "
                                     "el generador avisa cuantas veces tuvo que relajarlo.")
        v_min = p3.number_input("Viajes minimos por dia por cliente", 1, 30, 3, key="iscc_vmin")
        v_max = p3.number_input("Viajes maximos por dia por cliente", 1, 30, 7, key="iscc_vmax")
        tol_paso = p4.number_input("Paso de tolerancia worms (kg)", 5, 200, 20, key="iscc_tp")
        tol_pasos = p4.number_input("Cantidad de pasos", 1, 20, 5, key="iscc_tps",
                                    help="5 pasos de 20 kg = tolerancia +/- 100 kg.")
        salto = p4.number_input("Salto maximo de numeracion de remitos", 1, 20, 3,
                                key="iscc_salto")

    feriados = set()
    if usar_fer and fer is not None and len(fer):
        feriados = set(pd.to_datetime(fer["fecha"]).dt.date.tolist())
    dias = _dias_habiles(int(anio), int(mes), feriados, sin_dom, sin_sab)
    st.caption("%d dias habiles en %s %d." % (len(dias), MESES[int(mes) - 1], int(anio)))
    if not dias:
        st.error("No quedan dias habiles con esos filtros.")
        return

    st.markdown("**Prorrateo por cliente**")
    base = cli[["id_cliente", "nombre", "peso_prorrateo", "costo",
                "neto_min", "neto_max", "prefijo_remito", "ultimo_remito"]].copy()
    base["camiones"] = base["id_cliente"].map(
        cam[cam["activo"] == True].groupby("id_cliente").size()).fillna(0).astype(int)
    base["peso_prorrateo"] = pd.to_numeric(base["peso_prorrateo"], errors="coerce").fillna(1.0)
    ed = st.data_editor(
        base, hide_index=True, key="iscc_prorrateo", use_container_width=True,
        column_config={
            "id_cliente": None,
            "nombre": st.column_config.TextColumn("Cliente", disabled=True),
            "peso_prorrateo": st.column_config.NumberColumn("Peso", min_value=0.0, step=0.5),
            "costo": st.column_config.NumberColumn("Costo $/kg", format="%.4f"),
            "neto_min": st.column_config.NumberColumn("Neto min", step=100),
            "neto_max": st.column_config.NumberColumn("Neto max", step=100),
            "prefijo_remito": st.column_config.TextColumn("Prefijo"),
            "ultimo_remito": st.column_config.NumberColumn("Ultimo remito", step=1),
            "camiones": st.column_config.NumberColumn("Camiones", disabled=True),
        })
    peso_tot = float(pd.to_numeric(ed["peso_prorrateo"], errors="coerce").fillna(0).sum())
    if peso_tot <= 0:
        st.error("La suma de pesos de prorrateo es 0.")
        return
    ed = ed.copy()
    ed["_kg_objetivo"] = pd.to_numeric(ed["peso_prorrateo"], errors="coerce").fillna(0) \
        / peso_tot * float(kg_total)
    ed["documento"] = cli["documento"].values
    ed["producto"] = cli["producto"].values
    prev = ed[["nombre", "_kg_objetivo", "camiones"]].copy()
    prev["_kg_objetivo"] = prev["_kg_objetivo"].map(_fmt_kg)
    prev.columns = ["Cliente", "Kg objetivo", "Camiones"]
    st.dataframe(prev, hide_index=True, use_container_width=True)

    params = {"hora_ini": int(h_ini), "hora_fin": int(h_fin), "sep_min": int(sep_min),
              "gap_patente_h": float(gap_h), "viajes_min": int(v_min),
              "viajes_max": int(v_max), "tol_paso": int(tol_paso),
              "tol_pasos": int(tol_pasos), "salto_remito": int(salto),
              "sin_domingos": bool(sin_dom), "sin_sabados": bool(sin_sab),
              "feriados": bool(usar_fer)}

    if st.button("🎲 Generar planilla", type="primary", key="iscc_btn_gen"):
        df, diag = generar(ed, cam, dias, params, int(semilla))
        st.session_state["iscc_df"] = df
        st.session_state["iscc_diag"] = diag
        st.session_state["iscc_params"] = params
        st.session_state["iscc_ctx"] = (int(anio), int(mes), float(kg_total))

    df = st.session_state.get("iscc_df")
    if df is None or not len(df):
        return
    diag = st.session_state.get("iscc_diag", {})
    params = st.session_state.get("iscc_params", params)

    for a in diag.get("alertas", []):
        st.warning(a)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Viajes", "{:,}".format(len(df)).replace(",", "."))
    m2.metric("Kg remito", _fmt_kg(df["NETO REMITO"].sum()))
    m3.metric("Facturado", _fmt_money(df["TOTAL"].sum()))
    m4.metric("Patentes con gap corto", int(diag.get("relajaciones", 0)))
    if diag.get("relajaciones", 0):
        with st.expander("Ver los viajes donde no se pudo respetar la separacion"):
            st.dataframe(pd.DataFrame(diag["sin_gap"]), hide_index=True,
                         use_container_width=True)
            st.caption("Subi los netos, bajá los viajes maximos por dia o cargá mas "
                       "camiones para eliminarlos.")

    res = pd.DataFrame(diag.get("clientes", []))
    if len(res):
        res["desvio_kg"] = res["kg_generados"] - res["kg_objetivo"]
        show = res.copy()
        for c in ("kg_objetivo", "kg_generados", "desvio_kg"):
            show[c] = show[c].map(_fmt_kg)
        st.dataframe(show, hide_index=True, use_container_width=True)

    st.markdown("**Validacion de reglas**")
    st.dataframe(validar(df, params), hide_index=True, use_container_width=True)

    st.markdown("**Vista previa**")
    st.dataframe(df[COLS_EXPORT].head(200), hide_index=True, use_container_width=True)

    anio_c, mes_c, kg_c = st.session_state.get("iscc_ctx", (int(anio), int(mes), float(kg_total)))
    g1, g2 = st.columns([2, 1])
    nota = g1.text_input("Nota de la corrida", key="iscc_nota")
    if g2.button("💾 Guardar corrida", key="iscc_btn_save"):
        try:
            idc = _guardar_corrida(USR, conectar, anio_c, mes_c, kg_c,
                                   params, df, nota)
            cat.clear()
            st.session_state.pop("iscc_df", None)
            st.success("Corrida %d guardada. La numeracion de remitos quedo actualizada." % idc)
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)

    st.download_button(
        "⬇️ Excel (solo ISCC)",
        _to_excel([("DETALLES %s" % MESES[int(mes_c) - 1], df[COLS_EXPORT])]),
        file_name="iscc_%04d_%02d.xlsx" % (int(anio_c), int(mes_c)),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="iscc_dl_gen")


def _vista_corridas(USR, cat, conectar):
    cor = _corridas(cat)
    if cor is None or not len(cor):
        st.info("Todavia no hay corridas guardadas.")
        return
    show = cor.copy()
    show["kg_total"] = show["kg_total"].map(_fmt_kg)
    show["kg_generados"] = show["kg_generados"].map(_fmt_kg)
    st.dataframe(show, hide_index=True, use_container_width=True)

    ids = cor["id_corrida"].tolist()
    sel = st.selectbox("Corrida", ids, key="iscc_sel_cor",
                       format_func=lambda i: "#%d — %s %d (%d viajes)" % (
                           i,
                           MESES[int(cor[cor["id_corrida"] == i]["mes"].iloc[0]) - 1],
                           int(cor[cor["id_corrida"] == i]["anio"].iloc[0]),
                           int(cor[cor["id_corrida"] == i]["n_viajes"].iloc[0])))
    fila = cor[cor["id_corrida"] == sel].iloc[0]
    v = _viajes(cat, sel)
    if v is None or not len(v):
        st.warning("La corrida no tiene viajes.")
        return
    d = v.copy()
    d.columns = COLS_EXPORT
    d["FECHA"] = pd.to_datetime(d["FECHA"]).dt.date
    d["HORARIO ENTRADA"] = d["HORARIO ENTRADA"].astype(str).str[:8]
    for c in ("NETO REMITO", "NETO WORMS", "COSTO", "TOTAL", "DIFERENCIA DE PESO"):
        d[c] = pd.to_numeric(d[c], errors="coerce")

    m1, m2, m3 = st.columns(3)
    m1.metric("Viajes", "{:,}".format(len(d)).replace(",", "."))
    m2.metric("Kg remito", _fmt_kg(d["NETO REMITO"].sum()))
    m3.metric("Facturado", _fmt_money(d["TOTAL"].sum()))

    modo = st.radio("Contenido del Excel",
                    ["Solo bloque ISCC", "ISCC + trafico real de porteria"],
                    horizontal=True, key="iscc_modo_exp")
    final = d[COLS_EXPORT]
    if modo.startswith("ISCC +"):
        real = _trafico_real(cat, int(fila["anio"]), int(fila["mes"]))
        st.caption("%d filas de porteria mapeadas a productos ISCC." % len(real))
        if len(real):
            final = pd.concat([d[COLS_EXPORT], real], ignore_index=True)
            final = final.sort_values(["FECHA", "HORARIO ENTRADA"]).reset_index(drop=True)
        st.info("El bloque real no tiene remito asociado en la base: DOCUMENTO, NÚMERO, "
                "NETO REMITO y DIFERENCIA DE PESO van vacios.")

    st.dataframe(final.head(300), hide_index=True, use_container_width=True)
    st.download_button(
        "⬇️ Excel",
        _to_excel([("DETALLES %s" % MESES[int(fila["mes"]) - 1], final)]),
        file_name="iscc_%04d_%02d_corrida%d.xlsx" % (
            int(fila["anio"]), int(fila["mes"]), int(sel)),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="iscc_dl_cor")

    st.markdown("**Validacion**")
    try:
        prm = json.loads(fila["params"]) if isinstance(fila.get("params"), str) else {}
    except Exception:
        prm = {}
    st.dataframe(validar(d, prm or {}), hide_index=True, use_container_width=True)

    with st.expander("🗑️ Eliminar corrida"):
        st.caption("Borra la corrida y sus viajes. No revierte la numeracion de remitos.")
        if st.checkbox("Confirmo que quiero eliminar la corrida #%d" % int(sel),
                       key="iscc_ok_del"):
            if st.button("Eliminar", key="iscc_btn_del"):
                _borrar_corrida(USR, conectar, int(sel))
                cat.clear()
                st.success("Corrida eliminada.")
                st.rerun()


def _vista_maestro(USR, cat, conectar):
    cli = _clientes(cat)
    cam = _camiones(cat)
    if cli is None or not len(cli):
        st.warning("No hay clientes ISCC.")
        return

    st.markdown("**Clientes**")
    campos = ["nombre", "producto", "documento", "costo", "prefijo_remito",
              "ultimo_remito", "peso_prorrateo", "neto_min", "neto_max", "activo"]
    ed = st.data_editor(
        cli[["id_cliente"] + campos], hide_index=True, key="iscc_ed_cli",
        use_container_width=True,
        column_config={"id_cliente": None,
                       "costo": st.column_config.NumberColumn("costo $/kg", format="%.4f")})
    if st.button("💾 Guardar clientes", key="iscc_btn_cli"):
        n = 0
        orig = cli.set_index("id_cliente")
        for _, r in ed.iterrows():
            idc = int(r["id_cliente"])
            o = orig.loc[idc]
            ch = {}
            for c in campos:
                a, b = o[c], r[c]
                if pd.isna(a) and pd.isna(b):
                    continue
                if str(a) != str(b):
                    ch[c] = None if pd.isna(b) else b
            if ch:
                _upsert_cliente(USR, conectar, idc, ch)
                n += 1
        cat.clear()
        st.success("%d cliente(s) actualizado(s)." % n)
        st.rerun()

    st.divider()
    st.markdown("**Camiones**")
    if cam is not None and len(cam):
        vista = cam[["cliente", "transporte", "patente", "chofer", "activo"]]
        st.dataframe(vista, hide_index=True, use_container_width=True)
        res = cam[cam["activo"] == True].groupby("cliente").size().reset_index()
        res.columns = ["Cliente", "Camiones activos"]
        st.dataframe(res, hide_index=True, use_container_width=True)

    with st.expander("➕ Alta / edicion de camion"):
        c1, c2 = st.columns(2)
        nom = c1.selectbox("Cliente", cli["nombre"].tolist(), key="iscc_cam_cli")
        idc = int(cli[cli["nombre"] == nom]["id_cliente"].iloc[0])
        tr = c1.text_input("Transporte", key="iscc_cam_tr")
        pa = c2.text_input("Patente", key="iscc_cam_pa")
        ch = c2.text_input("Chofer", key="iscc_cam_ch")
        if st.button("Guardar camion", key="iscc_btn_cam"):
            if not tr.strip() or not pa.strip():
                st.error("Transporte y patente son obligatorios.")
            else:
                _alta_camion(USR, conectar, idc, tr, pa, ch)
                cat.clear()
                st.success("Camion guardado.")
                st.rerun()

    if cam is not None and len(cam):
        with st.expander("🚫 Activar / desactivar camion"):
            cam2 = cam.copy()
            cam2["lbl"] = cam2["patente"] + " — " + cam2["cliente"] + \
                cam2["activo"].map({True: "", False: "  (inactivo)"}).fillna("")
            sel = st.selectbox("Camion", cam2["id_camion"].tolist(), key="iscc_cam_sel",
                               format_func=lambda i: cam2[cam2["id_camion"] == i]["lbl"].iloc[0])
            act = bool(cam2[cam2["id_camion"] == sel]["activo"].iloc[0])
            if st.button("Desactivar" if act else "Activar", key="iscc_btn_act"):
                _baja_camion(USR, conectar, int(sel), not act)
                cat.clear()
                st.rerun()

    with st.expander("📥 Importar camiones desde Excel"):
        st.caption("Columnas esperadas: CLIENTE, TRANSPORTE, PATENTE, CHOFER.")
        up = st.file_uploader("Archivo", type=["xlsx", "xls"], key="iscc_up_cam")
        if up is not None:
            try:
                d = pd.read_excel(up)
                d.columns = [str(c).strip().upper() for c in d.columns]
                falta = [c for c in ("CLIENTE", "TRANSPORTE", "PATENTE") if c not in d.columns]
                if falta:
                    st.error("Faltan columnas: %s" % ", ".join(falta))
                else:
                    st.dataframe(d.head(30), hide_index=True, use_container_width=True)
                    if st.button("Importar", key="iscc_btn_imp"):
                        mapa = dict(zip(cli["nombre"].astype(str).str.strip().str.upper(),
                                        cli["id_cliente"]))
                        ok, mal = 0, []
                        for _, r in d.iterrows():
                            k = str(r["CLIENTE"]).strip().upper()
                            if k not in mapa:
                                mal.append(str(r["CLIENTE"]))
                                continue
                            _alta_camion(USR, conectar, int(mapa[k]),
                                         str(r["TRANSPORTE"]), str(r["PATENTE"]),
                                         str(r.get("CHOFER") or ""))
                            ok += 1
                        cat.clear()
                        st.success("%d camion(es) importado(s)." % ok)
                        if mal:
                            st.warning("Clientes no encontrados: %s" % ", ".join(sorted(set(mal))))
            except Exception as e:
                st.error("No se pudo leer el archivo: %s" % e)


def _vista_tarifas(USR, cat, conectar):
    st.caption("Costo por kg aplicado al trafico real de porteria y mapeo de productos.")
    tar = cat("SELECT nombre_cliente, costo, nota FROM produccion.iscc_tarifa "
              "ORDER BY nombre_cliente", None)
    mapa = cat("SELECT producto_porteria, producto_iscc, incluir "
               "FROM produccion.iscc_producto_map ORDER BY producto_porteria", None)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Tarifas**")
        st.dataframe(tar, hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**Mapeo de productos**")
        st.dataframe(mapa, hide_index=True, use_container_width=True)

    with st.expander("✏️ Cargar o actualizar tarifa"):
        t1, t2 = st.columns(2)
        nom = t1.text_input("Cliente (como figura en procedencia de porteria)",
                            key="iscc_tar_nom")
        cos = t2.number_input("Costo $/kg", min_value=0.0, value=0.0, step=0.1,
                              format="%.4f", key="iscc_tar_cos")
        if st.button("Guardar tarifa", key="iscc_btn_tar"):
            if not nom.strip():
                st.error("Falta el nombre.")
            else:
                with conectar(USR["id_usuario"]) as (conn, audit):
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO produccion.iscc_tarifa (nombre_cliente, costo)
                            VALUES (%s,%s)
                            ON CONFLICT (nombre_cliente) DO UPDATE SET costo = EXCLUDED.costo
                        """, (nom.strip().upper(), float(cos)))
                    audit.log("U", "iscc_tarifa", nom.strip().upper(), {"costo": float(cos)})
                    conn.commit()
                cat.clear()
                st.success("Tarifa guardada.")
                st.rerun()

    with st.expander("🔍 Productos de porteria sin mapear"):
        falt = cat("""
            SELECT t.producto, count(*) AS tickets, max(t.fecha) AS ultimo
              FROM produccion.v_porteria_ticket t
         LEFT JOIN produccion.iscc_producto_map m
                ON upper(trim(m.producto_porteria)) = upper(trim(t.producto))
             WHERE m.producto_porteria IS NULL
             GROUP BY t.producto
             ORDER BY 2 DESC
             LIMIT 100
        """, None)
        st.dataframe(falt, hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------
# entrada
# --------------------------------------------------------------------------
def render(USR, cat, conectar):
    st.title("📑 Proyecto ISCC")
    st.caption("Los viajes de los clientes ISCC son datos simulados: sirven para armar "
               "la planilla, no son un registro de descargas reales.")
    vista = st.segmented_control(
        "Vista",
        ["🎲 Generar", "📋 Corridas", "🚚 Maestro", "💲 Tarifas"],
        default="🎲 Generar", key="iscc_view", label_visibility="collapsed")
    if vista == "📋 Corridas":
        _vista_corridas(USR, cat, conectar)
    elif vista == "🚚 Maestro":
        _vista_maestro(USR, cat, conectar)
    elif vista == "💲 Tarifas":
        _vista_tarifas(USR, cat, conectar)
    else:
        _vista_generar(USR, cat, conectar)
