# -*- coding: utf-8 -*-
"""Brief semanal de Dirección · WORMS — renderizador HTML (imprimible A4).

Cinco páginas, en el orden en que el director las lee:
  1. Tablero            — decisiones pendientes, indicadores y stock por calidad
  2. Ingresos de AFE    — cuánto entra y de qué calidad, y quién lo vende
  3. Exportación        — ritmo, despachos, AFE necesario por calidad, proyección
  4. Producción         — desgomado acuoso y ARE por separado, y disposición de líquidos
  5. Stock y desvíos    — stock único (libro) contra medición real de tanque

Regla de la casa: nada se muestra como total sin abrir por producto y calidad.
"""
import calendar
from datetime import date, datetime

from .viz import (sparkline, stack_abs, diverging, barra_stock, acumulado_proy,
                 barras_h, barras_v, barras_agrupadas, microbarra,
                 BANDA_COLOR, BANDA_DESC, ORDEN_BANDA,
                 GOOD, WARN, SERIOUS, CRIT, INK, INK2, MUTED, GRID, AZUL, PROY, _n, _e)

MES_ABR = {"01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may", "06": "jun",
           "07": "jul", "08": "ago", "09": "sep", "10": "oct", "11": "nov", "12": "dic"}
# productos que el director mira sí o sí, en el orden en que los nombra
CLAVE = ["AFE-S", "AFE-SG", "AFE-AL", "AG-C", "AG-E", "ARE-B", "ARE-A-ANIMAL",
         "GLICERINA-PURA", "BORRA-B", "SEBO-C-2DA"]
C_EXPO, C_DESG, C_ARE = "#2a78d6", "#1baf7a", "#eb6834"


def fmes(m):
    return f"{MES_ABR.get(str(m)[5:7], str(m)[5:7])} {str(m)[2:4]}"


def fdate(s):
    d = datetime.strptime(str(s), "%Y-%m-%d").date()
    return f"{d.day} {MES_ABR['%02d' % d.month]}"


def delta(act, prev, mas_es_mejor=True):
    if act is None or prev in (None, 0):
        return "—", MUTED
    d = (act - prev) / abs(prev) * 100
    col = MUTED if abs(d) < 3 else (GOOD if ((d >= 0) == mas_es_mejor) else CRIT)
    return f"{'+' if d > 0 else ''}{d:,.0f}%", col


def kpi(titulo, valor, unidad, sub, extra="", d1=None, d4=None):
    t1, c1 = d1 or ("—", MUTED)
    t4, c4 = d4 or ("—", MUTED)
    return f"""
<div class="kpi">
  <div class="kpi-t">{_e(titulo)}</div>
  <div class="kpi-v">{_e(valor)}<span class="kpi-u">{_e(unidad)}</span></div>
  <div class="kpi-d"><span style="color:{c1}">{_e(t1)}</span> sem. previa
     &nbsp;·&nbsp; <span style="color:{c4}">{_e(t4)}</span> prom. 4 sem.</div>
  <div class="kpi-x">{extra}</div>
  <div class="kpi-n">{sub}</div>
</div>"""


def decision(nivel, titulo, cuerpo, pendiente):
    col = {"critico": CRIT, "grave": SERIOUS, "alerta": WARN, "ok": GOOD}[nivel]
    et = {"critico": "Crítico", "grave": "Importante", "alerta": "A vigilar", "ok": "Bajo control"}[nivel]
    return (f'<div class="dec" style="border-left-color:{col}">'
            f'<div class="dec-e" style="color:{col}">{et}</div>'
            f'<div class="dec-t">{_e(titulo)}</div>'
            f'<div class="dec-b">{cuerpo}</div>'
            f'<div class="dec-p"><b>Decisión pendiente:</b> {pendiente}</div></div>')


def tabla(cols, filas, aligns=None, clase=""):
    a = aligns or ["l"] + ["r"] * (len(cols) - 1)
    m = {"l": "tl", "r": "tr", "c": "tc"}
    th = "".join(f'<th class="{m[a[i]]}">{c}</th>' for i, c in enumerate(cols))
    tb = "".join("<tr>" + "".join(f'<td class="{m[a[i]]}">{c}</td>' for i, c in enumerate(f))
                 + "</tr>" for f in filas)
    return f'<table class="{clase}"><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table>'


def punto(c):
    return f'<span class="dot" style="background:{c}"></span>'


# ===========================================================================
def render(D):
    sem, sem_fin, iso = D["semana_ini"], D["semana_fin"], D["semana_iso"]

    ent = {r["semana"]: r for r in D["flujo"] if r["flujo"] == "ENTRADA"}
    sal = {r["semana"]: r for r in D["flujo"] if r["flujo"] == "SALIDA"}
    semanas = sorted(ent.keys() | sal.keys())
    ix = semanas.index(sem) if sem in semanas else len(semanas) - 1
    prev = semanas[ix - 1] if ix > 0 else None
    ult4 = [s for s in semanas if s < sem][-4:]

    def prom(dic, k):
        v = [dic[s][k] for s in ult4 if s in dic and dic[s].get(k) is not None]
        return sum(v) / len(v) if v else None

    banda_sem = {}
    for r in D["afe_banda"]:
        banda_sem.setdefault(r["semana"], {})[r["banda"]] = r["tn"]
    rt = {}
    for r in D["reacciones_tipo"]:
        rt.setdefault(r["semana"], {})[r["tipo"]] = r
    pool = {r["semana"]: r for r in D["desvio_pool"]}

    e_now, s_now = ent.get(sem, {}), sal.get(sem, {})
    e_prev, s_prev = ent.get(prev, {}), sal.get(prev, {})
    b_now = banda_sem.get(sem, {})
    afe_in = sum(b_now.values())
    afe_in_prev = sum(banda_sem.get(prev, {}).values()) if prev else None
    afe_in_p4 = ([sum(banda_sem.get(s, {}).values()) for s in ult4] or [None])
    afe_in_p4 = sum(afe_in_p4) / len(afe_in_p4) if afe_in_p4 and afe_in_p4[0] is not None else None

    desg = rt.get(sem, {}).get("DESGOMADO_ACUOSO", {})
    are = rt.get(sem, {}).get("PRODUCCION_ARE", {})
    desg_p = rt.get(prev, {}).get("DESGOMADO_ACUOSO", {}) if prev else {}
    are_p = rt.get(prev, {}).get("PRODUCCION_ARE", {}) if prev else {}

    # ---- stock por producto y calidad ----
    stock = D["stock"]
    afe_s = {r["banda"]: r for r in stock if r["producto"] == "AFE-S"}
    for b in ("A", "B", "C", "D"):
        afe_s.setdefault(b, {"banda": b, "tanques": 0, "tn": 0.0, "c_desp": 0.0,
                             "c_venc": 0.0, "libre": 0.0, "h": None, "s": None, "p": None})
    afe_s_tot = sum(afe_s[b]["tn"] for b in ("A", "B", "C", "D"))
    ab = afe_s["A"]["tn"] + afe_s["B"]["tn"]
    ab_libre = afe_s["A"]["libre"] + afe_s["B"]["libre"]
    cd_libre = afe_s["C"]["libre"] + afe_s["D"]["libre"]
    libre_total = sum(afe_s[b]["libre"] for b in ("A", "B", "C", "D"))
    ag_c = sum(r["tn"] for r in stock if r["producto"] == "AG-C")

    # ---- exportación comprometida y AFE-S que exige ----
    parte_afe = next((m["parte"] for m in D["mezcla"] if m["producto"] == "AFE-S"), 0.94)
    dsem = [d for d in D["despachos"] if sem <= d["fecha"] <= sem_fin]
    dfut = [d for d in D["despachos"] if d["fecha"] > sem_fin]
    dfut_tn = sum(d["tn"] for d in dfut)
    afe_necesario = dfut_tn * parte_afe
    cobertura_afe = libre_total / afe_necesario * 100 if afe_necesario else None
    fs_14 = [d for d in D["despachos"] if d["fs"]]
    fs_sin_aprob = [d for d in fs_14 if not d.get("aprob")]

    ritmo_expo = prom(sal, "tn") or 0
    consumo_semanal_afe = ritmo_expo * parte_afe
    dias_autonomia = (libre_total / consumo_semanal_afe * 7) if consumo_semanal_afe else None

    sin_a = 0
    for s in reversed(semanas):
        if (banda_sem.get(s, {}).get("A") or 0) > 0:
            break
        sin_a += 1

    # ======================= DECISIONES =======================
    decs = []
    pct_ab_in = (b_now.get("A", 0) + b_now.get("B", 0)) / (afe_in or 1) * 100
    decs.append(decision(
        "critico",
        "Calidad del AFE-S: la banda A está agotada y la mezcla de exportación quedó sin margen",
        "El AG-E que se exporta se arma mezclando AFE-S con AG-C. Cuanto más limpio el AFE-S "
        "(bandas A y B), más AG-C admite la mezcla sin superar la especificación de venta "
        "(azufre ≤ 50 ppm, fósforo ≤ 150 ppm). "
        f"Hoy <b>no queda AFE-S de banda A en tanque</b> y hace <b>{sin_a} semanas que no ingresa</b>. "
        f"De las {_n(afe_s['B']['tn'],1)} TN de banda B, {_n(afe_s['B']['c_desp'],1)} TN ya están "
        "comprometidas a despachos confirmados. "
        f"Consecuencia medible: los últimos despachos se armaron con {_n(parte_afe*100,1)}% de AFE-S "
        f"y sólo {_n((1-parte_afe)*100,1)}% de AG-C, hay <b>{_n(ag_c,1)} TN de AG-C sin salida</b> "
        f"y la semana cerró con {_n(pct_ab_in,0)}% de los ingresos de AFE en bandas A+B.",
        "comprar AFE-S de banda A o B (ver el detalle por proveedor en la página 2), o "
        "renegociar la especificación de venta del AG-E."))

    if fs_14:
        decs.append(decision(
            "grave",
            f"{len(fs_14)} despachos fuera de especificación en los últimos 14 días, "
            f"{len(fs_sin_aprob)} sin aprobación de dirección",
            "Un despacho queda fuera de especificación cuando la mezcla ponderada de sus tanques "
            "supera 50 ppm de azufre o 150 ppm de fósforo. La app calcula esto antes de confirmar "
            "y pide el visto de dirección, pero el circuito no bloquea la confirmación: "
            f"{len(fs_sin_aprob)} de los {len(fs_14)} se confirmaron igual. "
            "El detalle despacho por despacho está en la página 3.",
            "definir si la confirmación se bloquea sin aprobación de dirección, o si la "
            "especificación pactada con el cliente se actualiza."))

    p_now = pool.get(sem, {})
    dv = p_now.get("desvio")
    if dv is not None:
        pctd = abs(dv) / (p_now.get("real_t") or 1) * 100
        decs.append(decision(
            "ok" if pctd < 10 else ("alerta" if pctd < 25 else "grave"),
            f"Desvío entre el stock único y la medición de tanques: {_n(dv,1)} TN "
            f"({_n(pctd,0)}% del stock medido del pool de exportación)",
            "El <b>stock único</b> resulta del libro: stock inicial más lo producido y lo ingresado, "
            "menos lo despachado y lo consumido. La <b>medición de tanques</b> es el dato físico de "
            "los radares. Tomado por familia el número engaña, porque el AFE-S que se mezcla y sale "
            "como AG-E no genera movimiento en el libro: AFE y AG se compensan casi exactamente. "
            "La cifra de control es el consolidado AFE + AG. Detalle por producto en la página 2.",
            "cerrar el registro del consumo de AFE-S en los despachos; hasta entonces el desvío por "
            "familia no es concluyente."))

    # ======================= PÁGINA 1 =======================
    kpis = []
    kpis.append(kpi("AFE-S ingresado", _n(afe_in, 1), " TN",
                    f"{_n(b_now.get('A',0)+b_now.get('B',0),1)} TN en bandas A+B "
                    f"({_n(pct_ab_in,0)}% del ingreso)",
                    microbarra(b_now),
                    delta(afe_in, afe_in_prev), delta(afe_in, afe_in_p4)))
    kpis.append(kpi("Exportado", _n(s_now.get("tn"), 1), " TN",
                    f"{s_now.get('tk','—')} camiones · {len(dsem)} despachos cerrados",
                    sparkline([sal[s]["tn"] for s in semanas if s in sal], 150, 26, C_EXPO),
                    delta(s_now.get("tn"), s_prev.get("tn")), delta(s_now.get("tn"), prom(sal, "tn"))))
    kpis.append(kpi("Desgomado acuoso", str(desg.get("n", 0) or 0), " reacc.",
                    f"{_n(desg.get('tn'),1)} TN de AFE-S · utilización {_n(desg.get('uti'),0)}%",
                    sparkline([rt.get(s, {}).get("DESGOMADO_ACUOSO", {}).get("tn")
                               for s in sorted(rt)], 150, 26, C_DESG),
                    delta(desg.get("n"), desg_p.get("n"))))
    kpis.append(kpi("Producción de ARE", str(are.get("n", 0) or 0), " reacc.",
                    f"{_n(are.get('tn'),1)} TN de ARE · utilización {_n(are.get('uti'),0)}%",
                    sparkline([rt.get(s, {}).get("PRODUCCION_ARE", {}).get("tn")
                               for s in sorted(rt)], 150, 26, C_ARE),
                    delta(are.get("n"), are_p.get("n"))))
    kpis.append(kpi("AFE-S libre en tanque", _n(libre_total, 1), " TN",
                    f"de los cuales <b>{_n(ab_libre,1)} TN</b> son de bandas A+B "
                    f"({_n(ab_libre/(libre_total or 1)*100,0)}%)",
                    microbarra({b: afe_s[b]["libre"] for b in ("A", "B", "C", "D")})))
    kpis.append(kpi("AG-C sin salida", _n(ag_c, 1), " TN",
                    f"la mezcla de exportación sólo absorbe {_n((1-parte_afe)*100,1)}% de AG-C"))
    kpis.append(kpi("AFE-S para despachos comprometidos", _n(afe_necesario, 1), " TN",
                    f"{len(dfut)} despachos por {_n(dfut_tn,1)} TN · cobertura "
                    f"{_n(cobertura_afe,0)}% con el AFE-S libre"))
    kpis.append(kpi("Desvío stock único vs medición", _n(dv, 1), " TN",
                    "AFE + AG consolidados · pool de exportación",
                    sparkline([pool[s]["desvio"] for s in sorted(pool)], 150, 26, AZUL[2])))

    # stock por producto clave y calidad
    fil_clave = []
    for p in CLAVE:
        filas_p = [r for r in stock if r["producto"] == p]
        if not filas_p:
            continue
        for r in sorted(filas_p, key=lambda x: ORDEN_BANDA.index(x["banda"])
                        if x["banda"] in ORDEN_BANDA else 9):
            et = (punto(BANDA_COLOR[r["banda"]]) + f'<b>{_e(p)}</b> · banda {r["banda"]}'
                  if r["banda"] in BANDA_COLOR else f'<b>{_e(p)}</b>')
            comp = (r["c_desp"] or 0)
            fil_clave.append([et, str(r["tanques"]), _n(r["tn"], 1), _n(comp, 1),
                              _n(r["libre"], 1), _n(r["s"], 0), _n(r["p"], 0)])
    t_clave = tabla(["Producto y calidad", "Tanques", "Stock TN", "Comprometido TN",
                     "Libre TN", "S ppm", "P ppm"], fil_clave)

    g_afe_stock = barra_stock(
        [(f"AFE-S {b} · {BANDA_DESC[b]}", BANDA_COLOR[b],
          [("comprometido", afe_s[b]["c_desp"], BANDA_COLOR[b]),
           ("libre", afe_s[b]["libre"], "#d3dae3")], afe_s[b]["tn"]) for b in ("A", "B", "C", "D")],
        alto_fila=24)

    # ======================= PÁGINA 2 =======================
    sem12 = semanas[-12:]
    g_banda_abs = stack_abs([(fdate(s), banda_sem.get(s, {})) for s in sem12], h=152)
    fil_b = []
    for b in ORDEN_BANDA:
        v = b_now.get(b, 0) or 0
        p4 = [banda_sem.get(s, {}).get(b, 0) or 0 for s in ult4]
        p4v = sum(p4) / len(p4) if p4 else 0
        t4 = sum(sum(banda_sem.get(s, {}).values()) for s in ult4) or 1
        r = next((x for x in D["afe_banda"] if x["semana"] == sem and x["banda"] == b), {})
        fil_b.append([punto(BANDA_COLOR[b]) + f"<b>{b}</b> · {BANDA_DESC[b]}",
                      _n(v, 1), f'<b>{_n(v/(afe_in or 1)*100,1)}%</b>',
                      _n(p4v, 1), _n(sum(p4) / t4 * 100, 1) + "%",
                      _n(afe_s[b]["tn"], 1) if b in ("A", "B", "C", "D") else "—",
                      _n(r.get("s"), 0), _n(r.get("p"), 0)])
    t_banda = tabla(["Banda de calidad", "TN semana", "% semana", "TN prom. 4 sem.",
                     "% prom. 4 sem.", "TN en tanque", "S ppm", "P ppm"], fil_b)

    banda_mes = {}
    for r in D.get("afe_banda_mes", []):
        banda_mes.setdefault(r["mes"], {})[r["banda"]] = r["tn"]
    g_banda_mes = stack_abs([(fmes(m), banda_mes[m]) for m in sorted(banda_mes)], h=140)
    _m_ult = sorted(banda_mes)[-1] if banda_mes else None
    _m_pico = max(banda_mes, key=lambda m: banda_mes[m].get("A", 0)) if banda_mes else None

    fil_prov = []
    for p in D.get("proveedores", []):
        c3 = GOOD if (p["pct_ab3"] or 0) >= 40 else (WARN if (p["pct_ab3"] or 0) >= 25 else CRIT)
        flecha = ""
        if p["pct_ab"] is not None and p["pct_ab3"] is not None:
            d3 = p["pct_ab3"] - p["pct_ab"]
            flecha = (f' <span style="color:{CRIT}">▼</span>' if d3 <= -5 else
                      f' <span style="color:{GOOD}">▲</span>' if d3 >= 5 else "")
        fil_prov.append([_e(p["prov"]), _n(p["tn_tot"], 0), _n(p["tn_sem"], 1),
                         _n(p["pct_ab"], 0) + "%", _n(p["pct_d"], 0) + "%",
                         f'<span style="color:{c3};font-weight:700">{_n(p["pct_ab3"],0)}%</span>{flecha}'])
    t_prov = tabla(["Proveedor", "TN 9 sem.", "TN semana", "% A+B histórico", "% D histórico",
                    "% A+B últimas 3 sem."], fil_prov)

    # ======================= PÁGINA 3 =======================
    g_expo = barras_v([(fdate(s), sal.get(s, {}).get("tn")) for s in sem12], color=C_EXPO)
    _y, _m = int(D["exportacion"][-1]["mes"][:4]), int(D["exportacion"][-1]["mes"][5:7])
    g_expo_proy, proy_expo = acumulado_proy(D["exportacion"], h=152,
                                            dias_mes=calendar.monthrange(_y, _m)[1],
                                            etiqueta=fmes)
    ex_ult = D["exportacion"][-1]
    ex_prev = D["exportacion"][-2] if len(D["exportacion"]) > 1 else None

    _desp = sorted(D["despachos"], key=lambda x: x["fecha"])
    _desp_ocultos = max(0, len(_desp) - 14)
    fil_desp = []
    for d in _desp[-14:]:
        fs = (f'<span style="color:{CRIT};font-weight:700">fuera de spec</span>' if d["fs"]
              else f'<span style="color:{GOOD}">en spec</span>')
        ap = ("aprobado" if d.get("aprob") else
              (f'<span style="color:{CRIT}">sin aprobar</span>' if d["fs"] else "—"))
        fil_desp.append([fdate(d["fecha"]), _e(d["titulo"]), _e(d["destino"]), str(d["cont"]),
                         _n(d["tn"], 1), _n(d["s"], 0), _n(d["p"], 0), fs, ap, _e(d["estado"])])
    t_desp = tabla(["Fecha", "Despacho", "Destino", "Cont.", "TN", "S ppm", "P ppm",
                    "Especificación", "Dirección", "Estado"], fil_desp)
    if _desp_ocultos:
        t_desp += (f'<p class="lead">Se muestran los últimos 14 despachos; hay '
                   f'{_desp_ocultos} anteriores en la sección Despachos de la app.</p>')

    fil_nec = []
    for b in ("A", "B", "C", "D"):
        libre = afe_s[b]["libre"]
        fil_nec.append([punto(BANDA_COLOR[b]) + f"<b>banda {b}</b> · {BANDA_DESC[b]}",
                        _n(afe_s[b]["tn"], 1), _n(afe_s[b]["c_desp"], 1), _n(libre, 1),
                        _n(libre / (afe_necesario or 1) * 100, 1) + "%"])
    fil_nec.append([f"<b>Total AFE-S</b>", f"<b>{_n(afe_s_tot,1)}</b>",
                    f"<b>{_n(sum(afe_s[b]['c_desp'] for b in 'ABCD'),1)}</b>",
                    f"<b>{_n(libre_total,1)}</b>",
                    f'<b style="color:{GOOD if (cobertura_afe or 0) >= 100 else CRIT}">'
                    f'{_n(cobertura_afe,1)}%</b>'])
    t_nec = tabla(["Calidad disponible", "Stock TN", "Comprometido TN", "Libre TN",
                   "% del AFE-S que exigen los despachos"], fil_nec)

    # ======================= PÁGINA 4 =======================
    labels_r = [fdate(s) for s in sorted(rt)]
    g_prod = barras_agrupadas(
        labels_r,
        [("Desgomado acuoso", C_DESG, [rt[s].get("DESGOMADO_ACUOSO", {}).get("tn", 0) or 0 for s in sorted(rt)]),
         ("Producción de ARE", C_ARE, [rt[s].get("PRODUCCION_ARE", {}).get("tn", 0) or 0 for s in sorted(rt)])],
        h=122, decimales=0)
    g_prod_n = barras_agrupadas(
        labels_r,
        [("Desgomado acuoso", C_DESG, [rt[s].get("DESGOMADO_ACUOSO", {}).get("n", 0) or 0 for s in sorted(rt)]),
         ("Producción de ARE", C_ARE, [rt[s].get("PRODUCCION_ARE", {}).get("n", 0) or 0 for s in sorted(rt)])],
        h=110, decimales=0)

    fil_rt = []
    for s in sorted(rt, reverse=True)[:3]:
        for tp, nom, col in (("DESGOMADO_ACUOSO", "Desgomado acuoso", C_DESG),
                             ("PRODUCCION_ARE", "Producción de ARE", C_ARE)):
            r = rt[s].get(tp)
            if not r:
                continue
            fil_rt.append([fdate(s), punto(col) + nom, str(r["n"]), _n(r["tn"], 1),
                           _n(r["rend"], 0) + "%", _n(r["uti"], 0) + "%"])
    t_rt = tabla(["Semana", "Proceso", "Reacciones", "TN producidas", "Rendimiento",
                  "Utilización"], fil_rt)

    liq = D["liquidos"]
    _ly, _lm = int(liq[-1]["mes"][:4]), int(liq[-1]["mes"][5:7])
    g_liq, proy_liq = acumulado_proy(liq, h=142, dias_mes=calendar.monthrange(_ly, _lm)[1],
                                     etiqueta=fmes)
    liq_ult, liq_prev = liq[-1], (liq[-2] if len(liq) > 1 else None)

    # ======================= PÁGINA 5 =======================
    _dp = sorted(D["desvio_producto"], key=lambda x: -abs(x["desvio"] or 0))
    _dp_top, _dp_resto = _dp[:12], _dp[12:]
    fil_dp = []
    for r in _dp_top:
        base = max(abs(r["medido"] or 0), abs(r["unico"] or 0), 1)
        pc = abs(r["desvio"] or 0) / base * 100
        col = GOOD if pc < 10 else (WARN if pc < 25 else CRIT)
        fil_dp.append([f'<b>{_e(r["cod"])}</b>', _n(r["ini"], 1), _n(r["prod"], 1),
                       _n(r["e_in"], 1), _n(r["e_out"], 1), _n(r["intr"], 1),
                       f'<b>{_n(r["unico"],1)}</b>', _n(r["medido"], 1),
                       f'<span style="color:{col};font-weight:700">{_n(r["desvio"],1)}</span>'])
    if _dp_resto:
        fil_dp.append([f'<i>otros {len(_dp_resto)} productos</i>', "—", "—", "—", "—", "—",
                       _n(sum(x["unico"] or 0 for x in _dp_resto), 1),
                       _n(sum(x["medido"] or 0 for x in _dp_resto), 1),
                       _n(sum(x["desvio"] or 0 for x in _dp_resto), 1)])
    t_dp = tabla(["Producto", "Stock inicial", "Producido", "Ingresos", "Salidas",
                  "Consumo interno", "Stock único", "Medición real", "Desvío TN"], fil_dp)

    g_pool = diverging([(fdate(s), pool[s]["desvio"]) for s in sorted(pool)])

    def _ccol(v):
        if v is None:
            return MUTED
        if 80 <= v <= 120:
            return GOOD
        if 50 <= v < 80 or 120 < v <= 160:
            return WARN
        return CRIT
    g_cob = barras_h([(c["sector"], c["cob"], _ccol(c["cob"]))
                      for c in sorted(D["cobertura_libro"], key=lambda x: -x["fis"])[:6]],
                     alto=18, maxv=100)

    _cf = sorted(D["confianza"], key=lambda x: -x["kl"])[:6]
    t_conf = tabla(["Sector", "Tanques", "Volumen kL", "Medición más vieja"],
                   [[_e(c["sector"]), str(c["tanques"]), _n(c["kl"], 1),
                     f'<span style="color:{GOOD if c["h"]<=12 else WARN}">{c["h"]} h</span>']
                    for c in _cf])

    fil_cp = [[_e(x["producto"]), _e(x["rol"]), _e(x["estado"]), _n(x["tn"], 1)]
              for x in D["comp_prod"] if not x["vencido"]]
    _venc = [x for x in D["comp_prod"] if x["vencido"]]
    if _venc:
        fil_cp.append([f'<i>{len(_venc)} movimientos de batches ya cerrados</i>', "—",
                       "vencido", f'<span style="color:{CRIT};font-weight:700">'
                       f'{_n(sum(x["tn"] for x in _venc),1)}</span>'])
    t_cp = tabla(["Producto", "Rol", "Estado del batch", "TN"], fil_cp)

    leg_banda = ('<div class="leg">' + "".join(
        f'<span>{punto(BANDA_COLOR[b])}{b} · {BANDA_DESC[b]}</span>' for b in ORDEN_BANDA) +
        '<span class="leg-n">A: S ≤ 40 y P ≤ 120 · B: S ≤ 45 y P ≤ 135 · '
        'C: S ≤ 50 y P ≤ 150 · D: fuera de spec</span></div>')
    leg_prod = (f'<div class="leg"><span>{punto(C_DESG)}Desgomado acuoso</span>'
                f'<span>{punto(C_ARE)}Producción de ARE</span></div>')

    css = """
@page { size: A4; margin: 11mm 12mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Inter, Roboto, Arial, sans-serif;
       color:#0b0b0b; margin:0; background:#f9f9f7; font-size:9.5px; line-height:1.45; }
.page { width:186mm; min-height:271mm; background:#fff; margin:0 auto 6mm; padding:0 0 7mm;
        page-break-after:always; position:relative; }
.page:last-child { page-break-after:auto; }
@media print { body{background:#fff} .page{margin:0;width:auto;min-height:0} }
.hd { display:flex; justify-content:space-between; align-items:flex-end;
      border-bottom:2.5px solid #0b0b0b; padding-bottom:6px; margin-bottom:10px; }
.hd h1 { font-size:17px; margin:0; letter-spacing:-.3px; }
.hd .sub { font-size:9px; color:#52514e; margin-top:2px; }
.hd .rt { text-align:right; font-size:8.5px; color:#898781; }
.hd .rt b { display:block; font-size:10.5px; color:#0b0b0b; white-space:nowrap; }
h2 { font-size:11.5px; margin:10px 0 4px; padding-bottom:3px; border-bottom:1px solid #e1e0d9;
     letter-spacing:-.2px; }
h2 .n { color:#898781; font-weight:400; margin-right:5px; }
h3 { font-size:9.3px; margin:7px 0 3px; color:#52514e; text-transform:uppercase;
     letter-spacing:.5px; font-weight:700; }
p.lead { font-size:8.6px; color:#52514e; margin:2px 0 5px; }
.dec { background:#fcfcfb; border:1px solid #e1e0d9; border-left-width:4px; border-radius:3px;
       padding:5px 10px; margin-bottom:4px; }
.dec-e { font-size:7.5px; text-transform:uppercase; letter-spacing:.7px; font-weight:800; }
.dec-t { font-weight:700; font-size:10.2px; margin-top:1px; }
.dec-b { font-size:8.4px; color:#52514e; margin-top:2px; }
.dec-p { font-size:8.4px; color:#0b0b0b; margin-top:2px; }
.grid { display:grid; grid-template-columns:repeat(4,1fr); gap:5px; margin:7px 0; }
.kpi { border:1px solid #e1e0d9; border-radius:4px; padding:6px 7px; background:#fcfcfb; }
.kpi-t { font-size:7.8px; color:#898781; text-transform:uppercase; letter-spacing:.4px;
         font-weight:700; min-height:19px; }
.kpi-v { font-size:19px; font-weight:800; letter-spacing:-.6px; line-height:1.1; }
.kpi-u { font-size:9px; font-weight:600; color:#52514e; }
.kpi-d { font-size:7.5px; color:#898781; }
.kpi-x { margin:3px 0 1px; min-height:14px; }
.kpi-n { font-size:7.8px; color:#52514e; line-height:1.35; }
table { width:100%; border-collapse:collapse; font-size:8.2px; margin:3px 0 7px; }
th { background:#f4f4f1; font-weight:700; font-size:7.4px; text-transform:uppercase;
     letter-spacing:.3px; color:#52514e; padding:4px 5px; border-bottom:1.5px solid #c3c2b7; }
td { padding:2.6px 5px; border-bottom:1px solid #ececE6; }
tr:last-child td { border-bottom:none; }
.tl{text-align:left} .tr{text-align:right; font-variant-numeric:tabular-nums} .tc{text-align:center}
.dot { display:inline-block; width:7px; height:7px; border-radius:2px; margin-right:4px; }
.box { border:1px solid #e1e0d9; border-radius:4px; padding:6px 9px; background:#fcfcfb;
       font-size:8.4px; color:#52514e; margin:5px 0; }
.box b { color:#0b0b0b; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:11px; }
.foot { position:absolute; bottom:0; left:0; right:0; font-size:7.5px; color:#898781;
        border-top:1px solid #e1e0d9; padding-top:3px; display:flex; justify-content:space-between; }
.leg { font-size:8px; color:#52514e; margin:2px 0 4px; }
.leg span { margin-right:10px; white-space:nowrap; }
.leg .leg-n { color:#898781; white-space:normal; }
.nota { font-size:7.9px; color:#898781; line-height:1.4; margin:6px 0 0;
        border-top:1px solid #e1e0d9; padding-top:5px; }
.nota b { color:#52514e; }
"""

    def head(p):
        return f"""<div class="hd">
  <div><h1>WORMS · Brief de Dirección</h1>
    <div class="sub">Semana {iso} · {fdate(sem)} al {fdate(sem_fin)} de {sem[:4]} ·
    comparada con las 4 semanas previas y los meses anteriores</div></div>
  <div class="rt"><b>{p}</b>emitido {fdate(D['emitido'])}</div></div>"""

    def foot(p, t):
        return (f'<div class="foot"><span>Portería, laboratorio, radares de tanque, despachos y '
                f'batches (Supabase). Semana ISO cerrada, de lunes a domingo.</span>'
                f'<span>{t} · pág. {p}/5</span></div>')

    H = []
    # ---------------- 1 ----------------
    H.append(f"""<div class="page">{head("Tablero")}
<h2><span class="n">1</span>Situaciones que requieren una decisión</h2>
{''.join(decs)}
<h2><span class="n">2</span>Indicadores de la semana</h2>
<div class="grid">{''.join(kpis)}</div>
{foot(1, "Tablero")}</div>""")

    # ---------------- 2 · STOCK ----------------
    H.append(f"""<div class="page">{head("Stock")}
<h2><span class="n">3</span>Stock por producto y calidad</h2>
<p class="lead">Medición física de tanque al {fdate(D['emitido'])}. "Comprometido" son las toneladas
ya asignadas a un despacho confirmado; "libre" es lo que queda disponible.</p>
{g_afe_stock}
<div class="leg"><span><span class="dot" style="background:#2a78d6"></span>color pleno = comprometido</span>
<span><span class="dot" style="background:#d3dae3"></span>gris = libre</span></div>
{t_clave}

<h2><span class="n">4</span>Stock único contra medición real</h2>
<p class="lead"><b>Stock único</b> = stock inicial + producido + ingresos − salidas − consumo interno:
es lo que dice el libro. <b>Medición real</b> = lo que miden los radares y las varillas. El desvío es
la diferencia; el color mide su tamaño relativo (verde por debajo de 10%, ámbar por debajo de 25%,
rojo por encima), no su signo.</p>
{t_dp}

<div class="cols">
 <div>
  <h3>Antigüedad de la medición física</h3>
  <p class="lead">Mientras esto se mida en horas, el stock medido es dato duro y el desvío apunta
  al registro, no a la balanza.</p>
  {t_conf}
 </div>
 <div>
  <h3>Comprometido para producción</h3>
  <p class="lead">Movimientos planificados que todavía no se ejecutaron. "Vencido" es el batch ya
  cerrado cuyo movimiento nunca pasó a ejecutado: deuda de datos, no compromiso real.</p>
  {t_cp}
 </div>
</div>
{foot(2, "Stock")}</div>""")

    # ---------------- 3 · INGRESOS DE AFE ----------------
    H.append(f"""<div class="page">{head("Ingresos de AFE")}
<h2><span class="n">6</span>AFE-S que ingresa, por calidad</h2>
<p class="lead">Toneladas por semana, con la participación de cada banda dentro de la barra.
La banda sale del análisis de laboratorio del ticket: se toma el peor de los dos parámetros
contra la especificación de venta del AG-E (azufre sobre 50, fósforo sobre 150).</p>
{g_banda_abs}
{leg_banda}

<h3>Detalle de la semana {iso}, contra el promedio de las 4 semanas previas</h3>
{t_banda}

<div class="box"><b>Lectura.</b> Las bandas A y B representaron el <b>{_n(pct_ab_in,1)}%</b> del AFE-S
que ingresó esta semana. Hace <b>{sin_a} semanas que no ingresa banda A</b> y no queda nada en tanque.
El fósforo promedio de la banda D fue
{_n(next((x['p'] for x in D['afe_banda'] if x['semana']==sem and x['banda']=='D'), None),0)} ppm,
contra un máximo de venta de 150 ppm. Menos A y B significa menos AG-C por contenedor:
la mezcla de los últimos despachos absorbió apenas {_n((1-parte_afe)*100,1)}% de AG-C.</div>

<h3>Mismo corte, mes a mes</h3>
{g_banda_mes}
<p class="lead">La banda A pasó de <b>{_n(banda_mes.get(_m_pico,{}).get('A'),0)} TN</b> en
{fmes(_m_pico)} a <b>{_n(banda_mes.get(_m_ult,{}).get('A',0),0)} TN</b> en {fmes(_m_ult)}.
{fmes(_m_ult)} está en curso, así que el volumen todavía no es comparable; la participación sí.</p>

<h2><span class="n">7</span>Qué calidad vende cada proveedor</h2>
<p class="lead">Porcentaje de las toneladas de cada proveedor que llegó en banda A o B. La última
columna es el mismo dato limitado a las últimas 3 semanas: sirve para ver quién se está degradando
(▼) y quién mejora (▲).</p>
{t_prov}
{foot(3, "Ingresos de AFE")}</div>""")

    # ---------------- 4 · EXPORTACIÓN ----------------
    H.append(f"""<div class="page">{head("Exportación")}
<h2><span class="n">8</span>Ritmo de exportación</h2>
<h3>Toneladas despachadas a terminal, por semana</h3>
{barras_v([(fdate(s), sal.get(s, {}).get("tn")) for s in sem12], color=C_EXPO, meta=ritmo_expo, h=116)}
<p class="lead">La línea punteada es el promedio de las últimas 4 semanas
({_n(ritmo_expo,1)} TN por semana).</p>

<h2><span class="n">9</span>AFE-S necesario para los despachos comprometidos</h2>
<p class="lead">Los despachos de los últimos 45 días se armaron con {_n(parte_afe*100,1)}% de AFE-S y
{_n((1-parte_afe)*100,1)}% de AG-C. Aplicando esa mezcla, los {len(dfut)} despachos pendientes
({_n(dfut_tn,1)} TN) exigen <b>{_n(afe_necesario,1)} TN de AFE-S</b>.</p>
{t_nec}
<div class="box"><b>Posición.</b> El AFE-S libre cubre <b>{_n(cobertura_afe,1)}%</b> de lo que exigen
los despachos ya comprometidos, pero sólo <b>{_n(ab_libre,1)} TN</b> son de bandas A+B: el resto
({_n(cd_libre,1)} TN) es C y D, que no admite AG-C sin salirse de especificación.
Al ritmo de las últimas 4 semanas la exportación consume <b>{_n(consumo_semanal_afe,1)} TN de AFE-S
por semana</b>, contra <b>{_n(afe_in,1)} TN</b> que ingresaron: el AFE-S libre equivale a
<b>{_n(dias_autonomia,1)} días</b>. La planta trabaja con reposición continua y sin stock de
respaldo, así que un corte de recepción se siente en días, no en semanas.</div>

<h2><span class="n">10</span>Despachos desde el inicio de la semana informada</h2>
{t_desp}

<h2><span class="n">11</span>Proyección de exportación</h2>
<p class="lead">Toneladas acumuladas día a día, un mes por línea. La línea naranja punteada proyecta
el cierre de {fmes(ex_ult['mes'])} al ritmo diario de los primeros {ex_ult['ult']} días.</p>
{g_expo_proy}
<div class="box">Acumulado {fmes(ex_ult['mes'])} al día {ex_ult['ult']}: <b>{_n(ex_ult['tn'],0)} TN</b>
· proyección de cierre: <b>{_n(proy_expo,0)} TN</b>
· {fmes(ex_prev['mes']) if ex_prev else '—'} cerró en
<b>{_n(ex_prev['tn'],0) if ex_prev else '—'} TN</b>
→ <b>{_n((proy_expo/(ex_prev['tn'] or 1)-1)*100,0) if ex_prev else '—'}%</b>.</div>
{foot(4, "Exportación")}</div>""")

    # ---------------- 5 · PRODUCCIÓN ----------------
    H.append(f"""<div class="page">{head("Producción y control")}
<h2><span class="n">12</span>Desgomado acuoso y producción de ARE</h2>
<h3>Toneladas producidas por semana</h3>
{g_prod}
{leg_prod}
<h3>Detalle por proceso · últimas 3 semanas</h3>
{t_rt}
<p class="lead">Rendimiento = toneladas reales sobre toneladas de fórmula. Utilización = cuánto se
llenó el reactor respecto de su capacidad nominal.</p>

<h2><span class="n">13</span>Proyección de disposición final de líquidos</h2>
<p class="lead">Toneladas acumuladas día a día, un mes por línea. La línea naranja punteada proyecta
el cierre de {fmes(liq_ult['mes'])} al ritmo diario de los primeros {liq_ult['ult']} días.</p>
{g_liq}
<div class="cols">
  <div class="box">Acumulado {fmes(liq_ult['mes'])} al día {liq_ult['ult']}:
    <b>{_n(liq_ult['tn'],0)} TN</b><br>
    Proyección de cierre de mes: <b>{_n(proy_liq,0)} TN</b><br>
    {fmes(liq_prev['mes']) if liq_prev else '—'} cerró en
    <b>{_n(liq_prev['tn'],0) if liq_prev else '—'} TN</b>
    → <b>{_n((proy_liq/(liq_prev['tn'] or 1)-1)*100,0) if liq_prev else '—'}%</b></div>
  <div class="box"><b>Qué mirar.</b> La pendiente del mes en curso contra las anteriores. Si se
    aplana a mitad de mes es caída de recepción; si se empina, es riesgo de capacidad en piletas.</div>
</div>
<h2><span class="n">14</span>Desvío consolidado del pool de exportación</h2>
<p class="lead">AFE y AG tomados juntos, semana a semana. Por separado se compensan, porque el AFE-S
que se mezcla y sale como AG-E no genera movimiento en el libro.</p>
{g_pool}
<h3>Cobertura del libro por sector</h3>
<p class="lead">Porcentaje del movimiento físico medido que tiene un movimiento registrado que lo
explique. Por debajo de 50% el desvío de ese sector no es concluyente.</p>
{g_cob}
<p class="nota"><b>Nota metodológica.</b> Ingresos y salidas salen de los tickets de portería.
La calidad de cada ticket sale de su último análisis de laboratorio; los tickets sin análisis se
cuentan en toneladas pero no en banda. El stock medido es medición física de tanque (radares WeDo y
aforo por centímetros). Las reacciones salen de los batches cerrados. La mezcla de exportación se
calcula sobre las líneas reales de los despachos de los últimos 45 días. Ningún número de este
informe se carga a mano.</p>
{foot(5, "Producción y control")}</div>""")

    return (f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            f'<title>WORMS · Brief de Dirección · {iso}</title><style>{css}</style></head>'
            f'<body>{"".join(H)}</body></html>')
