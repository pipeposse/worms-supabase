# -*- coding: utf-8 -*-
"""Brief semanal de Dirección · WORMS — renderizador HTML (imprimible A4)."""
import json
from datetime import date, datetime
from .viz import (sparkline, stack100, diverging, barra_stock, acumulado_proy,
                 barras_h, BANDA_COLOR, BANDA_DESC, ORDEN_BANDA,
                 GOOD, WARN, SERIOUS, CRIT, INK, INK2, MUTED, GRID, AZUL, PROY, _n, _e)

MES_ABR = {"01":"ene","02":"feb","03":"mar","04":"abr","05":"may","06":"jun",
           "07":"jul","08":"ago","09":"sep","10":"oct","11":"nov","12":"dic"}


def fmes(m):
    """2026-08 -> ago 26"""
    return f"{MES_ABR.get(m[5:7], m[5:7])} {m[2:4]}"


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fdate(s):
    d = datetime.strptime(s, "%Y-%m-%d").date()
    return f"{d.day} {MESES[d.month-1]}"


def delta(act, prev, mas_es_mejor=True, pct=True):
    """Devuelve (texto, color) del cambio contra un valor previo."""
    if act is None or prev in (None, 0):
        return "—", MUTED
    d = (act - prev) / abs(prev) * 100 if pct else (act - prev)
    bueno = (d >= 0) if mas_es_mejor else (d <= 0)
    col = GOOD if abs(d) < 3 else (GOOD if bueno else CRIT)
    sig = "+" if d > 0 else ""
    return (f"{sig}{d:,.0f}%" if pct else f"{sig}{d:,.1f}"), col


def kpi(titulo, valor, unidad, sub, spark, d1, d4, nota=""):
    t1, c1 = d1
    t4, c4 = d4
    return f"""
<div class="kpi">
  <div class="kpi-t">{_e(titulo)}</div>
  <div class="kpi-v">{_e(valor)}<span class="kpi-u">{_e(unidad)}</span></div>
  <div class="kpi-d"><span style="color:{c1}">{_e(t1)}</span> vs sem. previa
     &nbsp;·&nbsp; <span style="color:{c4}">{_e(t4)}</span> vs prom. 4 sem.</div>
  <div class="kpi-s">{spark}</div>
  <div class="kpi-n">{_e(sub)}{(' · ' + nota) if nota else ''}</div>
</div>"""


def semaforo(estado, texto, detalle):
    col = {"ok": GOOD, "alerta": WARN, "grave": SERIOUS, "critico": CRIT}[estado]
    ico = {"ok": "●", "alerta": "▲", "grave": "▲", "critico": "■"}[estado]
    return (f'<div class="alerta" style="border-left-color:{col}">'
            f'<div class="alerta-h"><span style="color:{col}">{ico}</span> {_e(texto)}</div>'
            f'<div class="alerta-b">{detalle}</div></div>')


def tabla(cols, filas, aligns=None, clase=""):
    a = aligns or ["l"] + ["r"] * (len(cols) - 1)
    th = "".join(f'<th class="{ {"l":"tl","r":"tr","c":"tc"}[a[i]] }">{c}</th>'
                 for i, c in enumerate(cols))
    tb = []
    for f in filas:
        tds = "".join(f'<td class="{ {"l":"tl","r":"tr","c":"tc"}[a[i]] }">{c}</td>'
                      for i, c in enumerate(f))
        tb.append(f"<tr>{tds}</tr>")
    return f'<table class="{clase}"><thead><tr>{th}</tr></thead><tbody>{"".join(tb)}</tbody></table>'


# ===========================================================================
def render(D):
    sem = D["semana_ini"]
    sem_fin = D["semana_fin"]
    iso = D["semana_iso"]

    # ---- series semanales ordenadas cronológicamente ----
    ent = {r["semana"]: r for r in D["flujo"] if r["flujo"] == "ENTRADA"}
    sal = {r["semana"]: r for r in D["flujo"] if r["flujo"] == "SALIDA"}
    semanas = sorted(ent.keys())
    prev = semanas[semanas.index(sem) - 1] if semanas.index(sem) > 0 else None
    ult4 = [s for s in semanas if s < sem][-4:]

    def prom(dic, k):
        v = [dic[s][k] for s in ult4 if s in dic and dic[s].get(k) is not None]
        return sum(v) / len(v) if v else None

    reac = {r["semana"]: r for r in D["reacciones"]}
    pool = {r["semana"]: r for r in D["desvio_pool"]}
    banda_sem = {}
    for r in D["afe_banda"]:
        banda_sem.setdefault(r["semana"], {})[r["banda"]] = r["tn"]

    e_now, e_prev = ent.get(sem, {}), ent.get(prev, {}) if prev else {}
    s_now, s_prev = sal.get(sem, {}), sal.get(prev, {}) if prev else {}
    r_now, r_prev = reac.get(sem, {}), reac.get(prev, {}) if prev else {}
    p_now = pool.get(sem, {})

    # despachos de la semana
    dsem = [d for d in D["despachos"] if sem <= d["fecha"] <= sem_fin]
    dsem_tn = sum(d["tn"] for d in dsem)
    dsem_fs = sum(1 for d in dsem if d["fs"])
    dfut = [d for d in D["despachos"] if d["fecha"] > sem_fin]
    dfut_tn = sum(d["tn"] for d in dfut)
    dfut_fs = sum(1 for d in dfut if d["fs"])

    # stock
    stock = D["stock"]
    stock_tot = sum(r["tn"] for r in stock)
    afe_s = {r["banda"]: r for r in stock if r["producto"] == "AFE-S"}
    ab = (afe_s.get("A", {}).get("tn", 0) or 0) + (afe_s.get("B", {}).get("tn", 0) or 0)
    ab_libre = (afe_s.get("A", {}).get("libre", 0) or 0) + (afe_s.get("B", {}).get("libre", 0) or 0)
    afe_s_tot = sum(r["tn"] for r in stock if r["producto"] == "AFE-S")
    comp_desp_tot = sum(r["c_desp"] for r in stock)
    comp_venc_tot = sum(r["c_venc"] for r in stock)
    comp_prod_vivo = sum(r["tn"] for r in D["comp_prod"] if not r["vencido"])

    # banda A en ingresos: ¿hace cuántas semanas que no entra?
    sin_a = 0
    for s in reversed(semanas):
        if (banda_sem.get(s, {}).get("A") or 0) > 0:
            break
        sin_a += 1

    # ritmo de exportación y autonomía del pool A+B
    exp_4 = [sal[s]["tn"] for s in ult4 if s in sal]
    ritmo_exp = sum(exp_4) / len(exp_4) if exp_4 else 0

    # ================= ALERTAS =================
    # capacidad de dilución: TN de AG-C que el AFE-S en tanque puede absorber sin
    # pasarse de spec, con los % de la tabla de bandas (A 7%, B 4%, C 1,5%, D 0%).
    cap_dil = sum((afe_s.get(b, {}).get("tn", 0) or 0) * p
                  for b, p in (("A", .07), ("B", .04), ("C", .015), ("D", 0)))
    ag_c = sum(r["tn"] for r in stock if r["producto"].startswith("AG-C"))

    alertas = []
    if cap_dil < ag_c:
        alertas.append(semaforo(
            "critico",
            f"El AFE-S en tanque sólo banca {_n(cap_dil,1)} TN de AG-C y hay {_n(ag_c,1)} TN esperando salida",
            f"Sin banda A en tanque (0 TN, {sin_a} semanas sin ingreso de banda A) y con "
            f"{_n(afe_s.get('B',{}).get('c_desp',0),0)} de las {_n(afe_s.get('B',{}).get('tn',0),0)} TN "
            f"de banda B ya comprometidas a despacho, la capacidad de dilución del AG-E es de "
            f"<b>{_n(cap_dil,1)} TN</b> (A×7% + B×4% + C×1,5%). Por eso los contenedores se están armando "
            f"casi con AFE-S puro al límite de spec y el AG-C se acumula. "
            f"<b>Decisión:</b> comprar AFE-S limpio (ver proveedores, pág. 2) o renegociar la spec."))
    if dfut_fs or dsem_fs:
        alertas.append(semaforo(
            "grave", f"{dsem_fs + dfut_fs} despachos fuera de especificación en los últimos 14 días",
            "Azufre &gt; 50 ppm o fósforo &gt; 150 ppm sobre la mezcla ponderada del despacho. "
            f"Sólo {sum(1 for d in D['despachos'] if d['fs'] and d.get('aprob'))} de esos {dsem_fs + dfut_fs} "
            "tienen aprobación de dirección registrada; el resto se confirmó igual. "
            "<b>Decisión:</b> bloquear la confirmación sin visto de dirección, o renegociar la spec pactada."))
    if p_now.get("desvio") is not None:
        dv = p_now["desvio"]
        pctd = abs(dv) / (p_now.get("real_t") or 1) * 100
        est = "ok" if pctd < 10 else ("alerta" if pctd < 25 else "grave")
        alertas.append(semaforo(
            est, f"Desvío de stock del pool de exportación: {_n(dv,0)} TN ({_n(pctd,0)}% del stock medido)",
            "Es la diferencia entre lo que el libro dice que debería haber (AFE+AG juntos) y lo que "
            "midieron los radares. Los desvíos por familia (AFE −%s TN / AG +%s TN) se compensan entre sí: "
            "el AFE que se mezcla y sale como AG-E no genera movimiento en el libro. "
            "<b>El faltante real es el consolidado, no el de cada familia por separado.</b>" % (
                _n(abs([f for f in D["desvio_familia"] if f["semana"] == sem and f["familia"] == "AFE"][0]["desvio"]), 0)
                if [f for f in D["desvio_familia"] if f["semana"] == sem and f["familia"] == "AFE"] else "—",
                _n([f for f in D["desvio_familia"] if f["semana"] == sem and f["familia"] == "AG"][0]["desvio"], 0)
                if [f for f in D["desvio_familia"] if f["semana"] == sem and f["familia"] == "AG"] else "—")))

    # ================= P1 · KPIs =================
    kpis = []
    kpis.append(kpi("Ingresos de planta", _n(e_now.get("tn"), 0), " TN",
                    f'{e_now.get("tk","—")} camiones',
                    sparkline([ent[s]["tn"] for s in semanas], 150, 28, AZUL[2]),
                    delta(e_now.get("tn"), e_prev.get("tn")),
                    delta(e_now.get("tn"), prom(ent, "tn"))))
    kpis.append(kpi("AFE ingresado", _n(e_now.get("tn_afe"), 0), " TN",
                    f'{_n((e_now.get("tn_afe") or 0)/(e_now.get("tn") or 1)*100,0)}% de los ingresos',
                    sparkline([ent[s]["tn_afe"] for s in semanas], 150, 28, AZUL[2]),
                    delta(e_now.get("tn_afe"), e_prev.get("tn_afe")),
                    delta(e_now.get("tn_afe"), prom(ent, "tn_afe"))))
    kpis.append(kpi("Salidas / exportación", _n(s_now.get("tn"), 0), " TN",
                    f'{s_now.get("tk","—")} camiones',
                    sparkline([sal[s]["tn"] for s in semanas if s in sal], 150, 28, AZUL[2]),
                    delta(s_now.get("tn"), s_prev.get("tn")),
                    delta(s_now.get("tn"), prom(sal, "tn"))))
    kpis.append(kpi("Despachos cerrados", str(len(dsem)), "",
                    f"{_n(dsem_tn,0)} TN · {sum(d['cont'] for d in dsem)} contenedores",
                    "", ("—", MUTED), ("—", MUTED),
                    f'<span style="color:{CRIT}">{dsem_fs} fuera de spec</span>' if dsem_fs else ""))
    kpis.append(kpi("Reacciones terminadas", str(r_now.get("n", 0) or 0), "",
                    f'{_n(r_now.get("tn"),0)} TN producidas',
                    sparkline([reac[s]["n"] for s in sorted(reac)], 150, 28, AZUL[2]),
                    delta(r_now.get("n"), r_prev.get("n")),
                    delta(r_now.get("n"), prom(reac, "n"))))
    kpis.append(kpi("Cobertura de laboratorio", _n(e_now.get("cob"), 0), "%",
                    "de las TN que ingresan tienen análisis",
                    sparkline([ent[s]["cob"] for s in semanas], 150, 28, AZUL[2]),
                    delta(e_now.get("cob"), e_prev.get("cob")),
                    delta(e_now.get("cob"), prom(ent, "cob"))))
    kpis.append(kpi("Stock medido en tanques", _n(stock_tot, 0), " TN",
                    f'{sum(r["tanques"] for r in stock)} tanques · 100% con medición física',
                    "", ("—", MUTED), ("—", MUTED)))
    dv = p_now.get("desvio")
    dv_prev = pool.get(prev, {}).get("desvio") if prev else None
    kpis.append(kpi("Desvío de stock (pool expo)", _n(dv, 0), " TN",
                    f'{_n(abs(dv or 0)/(p_now.get("real_t") or 1)*100,0)}% del stock medido del pool',
                    sparkline([pool[s]["desvio"] for s in sorted(pool)], 150, 28, AZUL[2]),
                    delta(abs(dv or 0), abs(dv_prev or 0), mas_es_mejor=False),
                    ("—", MUTED)))

    # tabla semanal
    fil_sem = []
    for s in reversed(semanas[-6:]):
        r = reac.get(s, {})
        p = pool.get(s, {})
        fil_sem.append([
            f'<b>{fdate(s)}</b>' if s == sem else fdate(s),
            _n(ent.get(s, {}).get("tn"), 0), _n(ent.get(s, {}).get("tn_afe"), 0),
            _n(ent.get(s, {}).get("cob"), 0) + "%",
            _n(sal.get(s, {}).get("tn"), 0),
            str(r.get("n", "—")), _n(r.get("tn"), 0),
            f'<span style="color:{CRIT if (p.get("desvio") or 0) < 0 else INK2}">{_n(p.get("desvio"),0)}</span>'])
    t_sem = tabla(["Semana (lun)", "Ingresos TN", "AFE TN", "Cob. lab", "Salidas TN",
                   "Reacc.", "TN prod.", "Desvío pool TN"], fil_sem)

    fil_mes = []
    for m in D["meses"]:
        fil_mes.append([fmes(m["mes"]), _n(m["ing"], 0), _n(m["afe"], 0), _n(m["cob"], 0) + "%",
                        _n(m["sal"], 0), str(m["reac_n"] or "—"), _n(m["reac_tn"], 0),
                        str(m["desp_n"] or "—"), _n(m["desp_tn"], 0)])
    t_mes = tabla(["Mes", "Ingresos TN", "AFE TN", "Cob. lab", "Salidas TN",
                   "Reacc.", "TN prod.", "Desp.", "TN desp."], fil_mes)

    # ================= P2 · calidad =================
    sem12 = semanas[-12:]
    g_banda = stack100([(f"{fdate(s)[:6]}", banda_sem.get(s, {})) for s in sem12])
    b_now = banda_sem.get(sem, {})
    tot_b = sum(b_now.values()) or 1
    fil_b = []
    for b in ORDEN_BANDA:
        v = b_now.get(b, 0) or 0
        prev4 = [sum([banda_sem.get(s, {}).get(b, 0) or 0]) for s in ult4]
        pr = sum(prev4) / len(prev4) if prev4 else 0
        r = next((x for x in D["afe_banda"] if x["semana"] == sem and x["banda"] == b), {})
        fil_b.append([
            f'<span class="dot" style="background:{BANDA_COLOR[b]}"></span><b>{b}</b> · {BANDA_DESC[b]}',
            _n(v, 1), _n(v / tot_b * 100, 0) + "%", _n(pr, 1),
            _n(r.get("s"), 0), _n(r.get("p"), 0),
            _n(afe_s.get(b, {}).get("tn"), 1) if b in ("A", "B", "C", "D") else "—"])
    t_banda = tabla(["Banda de calidad", "TN semana", "% sem.", "TN prom. 4 sem.",
                     "S ppm", "P ppm", "TN en tanque"], fil_b)

    fil_prov = []
    for p in D.get("proveedores", []):
        c3 = GOOD if (p["pct_ab3"] or 0) >= 40 else (WARN if (p["pct_ab3"] or 0) >= 25 else CRIT)
        fil_prov.append([_e(p["prov"]), _n(p["tn_tot"], 0), _n(p["tn_sem"], 1),
                         _n(p["pct_ab"], 0) + "%", _n(p["pct_d"], 0) + "%",
                         f'<span style="color:{c3};font-weight:700">{_n(p["pct_ab3"],0)}%</span>'])
    t_prov = tabla(["Proveedor", "TN 9 sem.", "TN semana", "% A+B", "% D",
                    "% A+B últ. 3 sem."], fil_prov)

    # ================= P3 · stock =================
    filas_afe = []
    for b in ["A", "B", "C", "D"]:
        r = afe_s.get(b, {"tn": 0, "c_desp": 0, "libre": 0, "tanques": 0})
        filas_afe.append((f"AFE-S {b} · {BANDA_DESC[b]}", BANDA_COLOR[b],
                          [("comprometido", r.get("c_desp", 0), BANDA_COLOR[b]),
                           ("libre", r.get("libre", 0), "#cfd6df")], r.get("tn", 0)))
    g_afe = barra_stock(filas_afe)

    _ord = [x for x in sorted(stock, key=lambda x: -x["tn"]) if x["tn"] >= 1]
    _top, _resto = _ord[:12], _ord[12:]
    fil_stock = []
    for r in _top:
        et = r["producto"] + (f' · {r["banda"]}' if r["banda"] not in ("N/A",) else "")
        col = BANDA_COLOR.get(r["banda"], INK)
        fil_stock.append([
            (f'<span class="dot" style="background:{col}"></span>' if r["banda"] != "N/A" else "") + _e(et),
            str(r["tanques"]), _n(r["tn"], 1), _n(r["c_desp"], 1), _n(r["libre"], 1),
            _n(r["s"], 0), _n(r["p"], 0),
            f'{r["h"]} h' if r["h"] is not None else "—"])
    if _resto:
        fil_stock.append([f'<i>otros {len(_resto)} productos</i>',
                          str(sum(x["tanques"] for x in _resto)),
                          _n(sum(x["tn"] for x in _resto), 1),
                          _n(sum(x["c_desp"] for x in _resto), 1),
                          _n(sum(x["libre"] for x in _resto), 1), "—", "—", "—"])
    t_stock = tabla(["Producto · calidad", "Tanques", "Stock TN", "Comp. despacho TN",
                     "Libre TN", "S ppm", "P ppm", "Antig. medición"], fil_stock)

    fil_cp = [[_e(x["producto"]), _e(x["rol"]), _e(x["estado"]), _n(x["tn"], 1)]
              for x in D["comp_prod"] if not x["vencido"]]
    _venc = [x for x in D["comp_prod"] if x["vencido"]]
    if _venc:
        fil_cp.append([f'<i>{len(_venc)} movimientos vencidos ('
                       + ", ".join(sorted({x["producto"] for x in _venc}))[:70] + ')</i>',
                       "—", "batch ya cerrado",
                       f'<span style="color:{CRIT};font-weight:700">'
                       + _n(sum(x["tn"] for x in _venc), 1) + '</span>'])
    t_cp = tabla(["Producto", "Rol", "Estado del batch", "TN"], fil_cp)

    # ================= P4 · desvíos =================
    g_pool = diverging([(fdate(s), pool[s]["desvio"]) for s in sorted(pool)])
    fam_now = {f["familia"]: f for f in D["desvio_familia"] if f["semana"] == sem}
    fam_prev = {f["familia"]: f for f in D["desvio_familia"] if f["semana"] != sem}
    fil_fam = []
    for f in sorted(fam_now.values(), key=lambda x: x["desvio"]):
        pc = abs(f["desvio"]) / (f["real_t"] or 1) * 100
        col = GOOD if pc < 10 else (WARN if pc < 25 else CRIT)
        fil_fam.append([f'<b>{_e(f["familia"])}</b>', _n(f["ini"], 1), _n(f["prod"], 1),
                        _n(f["e_in"], 1), _n(f["e_out"], 1), _n(f["proy"], 1), _n(f["real_t"], 1),
                        f'<span style="color:{col};font-weight:700">{_n(f["desvio"],1)}</span>',
                        _n(fam_prev.get(f["familia"], {}).get("desvio"), 1)])
    t_fam = tabla(["Familia", "Stock ini.", "Producido", "Entradas", "Salidas",
                   "Proyectado", "Medido", "Desvío TN", "Desvío sem. previa"], fil_fam)

    def _ccol(v):
        if v is None:
            return MUTED
        if 80 <= v <= 120:
            return GOOD
        if 50 <= v < 80 or 120 < v <= 160:
            return WARN
        return CRIT
    cob = [(c["sector"], c["cob"], _ccol(c["cob"]))
           for c in sorted(D["cobertura_libro"], key=lambda x: -x["fis"])]
    g_cob = barras_h(cob, maxv=100)

    _cf = sorted(D["confianza"], key=lambda x: -x["kl"])
    fil_conf = [[_e(c["sector"]), str(c["tanques"]), _n(c["kl"], 1),
                 f'<span style="color:{GOOD if c["h"]<=12 else WARN}">{c["h"]} h</span>']
                for c in _cf[:6]]
    if _cf[6:]:
        fil_conf.append([f'<i>otros {len(_cf[6:])} sectores</i>',
                         str(sum(c["tanques"] for c in _cf[6:])),
                         _n(sum(c["kl"] for c in _cf[6:]), 1),
                         f'<span style="color:{GOOD if max(c["h"] for c in _cf[6:])<=12 else WARN}">'
                         f'{max(c["h"] for c in _cf[6:])} h</span>'])
    t_conf = tabla(["Sector", "Tanques", "Volumen kL", "Medición más vieja"], fil_conf)

    # ================= P5 · despachos, reacciones, proyección =================
    fil_desp = []
    for d in sorted(D["despachos"], key=lambda x: x["fecha"]):
        if d["fecha"] < sem:
            continue
        fs = (f'<span style="color:{CRIT};font-weight:700">FUERA DE SPEC</span>' if d["fs"]
              else f'<span style="color:{GOOD}">en spec</span>')
        ap = "aprobado" if d.get("aprob") else ("—" if not d["fs"] else
             f'<span style="color:{CRIT}">sin aprobar</span>')
        fil_desp.append([fdate(d["fecha"]), _e(d["titulo"]), _e(d["destino"]),
                         str(d["cont"]), _n(d["tn"], 1), _n(d["s"], 0), _n(d["p"], 0),
                         fs, ap, _e(d["estado"])])
    t_desp = tabla(["Fecha", "Despacho", "Destino", "Cont.", "TN", "S ppm", "P ppm",
                    "Spec (S≤50 / P≤150)", "Dirección", "Estado"], fil_desp)

    fil_r = []
    for s in sorted(reac, reverse=True)[:5]:
        r = reac[s]
        dh = r.get("desvio_h")
        col = MUTED if dh is None else (GOOD if abs(dh) <= 4 else (WARN if abs(dh) <= 12 else CRIT))
        fil_r.append([fdate(s), str(r["n"]), _n(r["tn"], 1), _n(r["tn_form"], 1),
                      _n(r["rend"], 0) + "%", _n(r["uti"], 0) + "%",
                      _n(r.get("ciclo_h"), 1), _n(r.get("prog_h"), 1),
                      f'<span style="color:{col};font-weight:600">{_n(dh,1)}</span>',
                      f'{r["n_conf"]}/{r["n"]}'])
    t_reac = tabla(["Semana", "Reacc.", "TN reales", "TN fórmula", "Rendim.", "Utiliz.",
                    "Ciclo h", "Programado h", "Desvío h", "Tiempos confiables"], fil_r)

    liq = D["liquidos"]
    import calendar as _cal
    _y, _m = int(liq[-1]["mes"][:4]), int(liq[-1]["mes"][5:7])
    g_liq, proy = acumulado_proy(liq, dias_mes=_cal.monthrange(_y, _m)[1], etiqueta=fmes)
    liq_ult = liq[-1]
    liq_prev = liq[-2] if len(liq) > 1 else None

    css = """
@page { size: A4; margin: 11mm 12mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Inter, Roboto, Arial, sans-serif;
       color:#0b0b0b; margin:0; background:#f9f9f7; font-size:9.5px; line-height:1.45; }
.page { width:186mm; min-height:271mm; background:#fff; margin:0 auto 6mm; padding:0 0 6mm;
        page-break-after:always; position:relative; }
.page:last-child { page-break-after:auto; }
@media print { body{background:#fff} .page{margin:0;box-shadow:none;width:auto;min-height:0} }
.hd { display:flex; justify-content:space-between; align-items:flex-end;
      border-bottom:2.5px solid #0b0b0b; padding-bottom:6px; margin-bottom:10px; }
.hd h1 { font-size:17px; margin:0; letter-spacing:-.3px; }
.hd .sub { font-size:9px; color:#52514e; margin-top:2px; }
.hd .rt { text-align:right; font-size:8.5px; color:#898781; }
.hd .rt b { display:block; font-size:11px; color:#0b0b0b; }
h2 { font-size:12px; margin:13px 0 5px; padding-bottom:3px; border-bottom:1px solid #e1e0d9;
     letter-spacing:-.2px; }
h2 .n { color:#898781; font-weight:400; margin-right:5px; }
h3 { font-size:10px; margin:9px 0 3px; color:#52514e; text-transform:uppercase;
     letter-spacing:.5px; font-weight:700; }
p.lead { font-size:9px; color:#52514e; margin:2px 0 7px; }
.alerta { background:#fcfcfb; border:1px solid #e1e0d9; border-left-width:4px; border-radius:3px;
          padding:6px 9px; margin-bottom:5px; }
.alerta-h { font-weight:700; font-size:10px; }
.alerta-b { font-size:8.7px; color:#52514e; margin-top:2px; }
.grid { display:grid; grid-template-columns:repeat(4,1fr); gap:5px; margin:8px 0; }
.kpi { border:1px solid #e1e0d9; border-radius:4px; padding:6px 7px; background:#fcfcfb; }
.kpi-t { font-size:8px; color:#898781; text-transform:uppercase; letter-spacing:.4px;
         font-weight:700; min-height:19px; }
.kpi-v { font-size:19px; font-weight:800; letter-spacing:-.6px; line-height:1.1; }
.kpi-u { font-size:9px; font-weight:600; color:#52514e; }
.kpi-d { font-size:7.6px; color:#898781; margin-top:1px; }
.kpi-s { margin:2px 0 0; height:28px; }
.kpi-n { font-size:7.8px; color:#52514e; }
table { width:100%; border-collapse:collapse; font-size:8.6px; margin:4px 0 8px; }
th { background:#f4f4f1; font-weight:700; font-size:7.8px; text-transform:uppercase;
     letter-spacing:.3px; color:#52514e; padding:4px 5px; border-bottom:1.5px solid #c3c2b7; }
td { padding:3.2px 5px; border-bottom:1px solid #ececE6; }
tr:last-child td { border-bottom:none; }
.tl{text-align:left} .tr{text-align:right; font-variant-numeric:tabular-nums} .tc{text-align:center}
.dot { display:inline-block; width:7px; height:7px; border-radius:2px; margin-right:4px; }
.box { border:1px solid #e1e0d9; border-radius:4px; padding:7px 9px; background:#fcfcfb;
       font-size:8.7px; color:#52514e; margin:6px 0; }
.box b { color:#0b0b0b; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.big { font-size:26px; font-weight:800; letter-spacing:-1px; line-height:1; }
.big span { font-size:11px; font-weight:600; color:#52514e; }
.foot { position:absolute; bottom:0; left:0; right:0; font-size:7.5px; color:#898781;
        border-top:1px solid #e1e0d9; padding-top:3px; display:flex; justify-content:space-between; }
.leg { font-size:8px; color:#52514e; margin:3px 0 0; }
.leg span { margin-right:10px; white-space:nowrap; }
.nota { font-size:7.9px; color:#898781; line-height:1.4; margin:6px 0 0;
        border-top:1px solid #e1e0d9; padding-top:5px; }
.nota b { color:#52514e; }
"""

    def head(p):
        return f"""<div class="hd">
  <div><h1>WORMS · Brief de Dirección</h1>
    <div class="sub">Semana {iso} · {fdate(sem)} al {fdate(sem_fin)} de {sem[:4]} · comparada con las 4 semanas previas y los meses anteriores</div></div>
  <div class="rt"><b>{p}</b>emitido {fdate(D['emitido'])}</div></div>"""

    def foot(p, t):
        return (f'<div class="foot"><span>Fuente: Supabase · portería, laboratorio, radares de tanque, '
                f'despachos y batches. Semana ISO cerrada (lunes a domingo).</span><span>{t} · pág. {p}/5</span></div>')

    leg_banda = ('<div class="leg">' + "".join(
        f'<span><span class="dot" style="background:{BANDA_COLOR[b]}"></span>{b} · {BANDA_DESC[b]}</span>'
        for b in ORDEN_BANDA) + '</div>')

    H = []
    # ---------------- PÁGINA 1 ----------------
    H.append(f"""<div class="page">{head("Tablero")}
<h2><span class="n">1</span>Lo que exige una decisión esta semana</h2>
{''.join(alertas)}
<h2><span class="n">2</span>Tablero de la semana</h2>
<div class="grid">{''.join(kpis)}</div>
<h3>Semana a semana · últimas 6</h3>
{t_sem}
<h3>Mes a mes · últimos 5</h3>
{t_mes}
<div class="box"><b>Cómo leer el desvío del pool.</b> El desvío por familia por separado es engañoso:
el AFE que se mezcla y se despacha como AG-E no genera movimiento en el libro, así que el AFE aparece
faltando y el AG aparece sobrando casi por el mismo número. La cifra que sirve para controlar es el
<b>consolidado AFE + AG</b>, que es la que muestra el tablero.</div>
{foot(1, "Tablero")}</div>""")

    # ---------------- PÁGINA 2 ----------------
    H.append(f"""<div class="page">{head("Ingresos y calidad")}
<h2><span class="n">3</span>Qué entró y con qué calidad</h2>
<div class="cols">
  <div><h3>Ingresos de la semana</h3>
    <div class="big">{_n(e_now.get('tn'),0)}<span> TN</span></div>
    <p class="lead">{e_now.get('tk')} camiones · {_n(e_now.get('tn_afe'),0)} TN de AFE
    ({_n((e_now.get('tn_afe') or 0)/(e_now.get('tn') or 1)*100,0)}%) ·
    cobertura de laboratorio {_n(e_now.get('cob'),0)}%</p></div>
  <div><h3>Contra el mes anterior</h3>
    <p class="lead">El mes anterior cerró en {_n(D['meses'][-2]['ing'],0)} TN ({_n(D['meses'][-2]['afe'],0)} TN de AFE).
    Agosto lleva {_n(D['meses'][-1]['ing'],0)} TN a la fecha, con cobertura de laboratorio
    {_n(D['meses'][-1]['cob'],0)}% contra {_n(D['meses'][-2]['cob'],0)}% de julio.</p></div>
</div>

<h3>AFE que ingresa, por banda de calidad · últimas 12 semanas (% de las TN de cada semana)</h3>
{g_banda}
{leg_banda}
<p class="lead">La banda sale del laboratorio del ticket: índice = el peor de azufre/50 y fósforo/150
contra la spec de venta del AG-E. A = margen ≥20% · B = 10–20% · C = cumple sin margen ·
D = no cumple solo, únicamente entra mezclado. Es el mismo criterio que usa el algoritmo de despacho.</p>

<h3>Detalle de la semana {iso}</h3>
{t_banda}

<h3>Quién nos vende qué calidad · últimas 9 semanas</h3>
{t_prov}
<p class="lead">%A+B = porción de las TN de ese proveedor que llegó en banda A o B. La última columna es
el mismo dato pero sólo de las últimas 3 semanas: sirve para ver quién se está degradando.</p>

<div class="box"><b>Lo que dice este cuadro.</b> Hace <b>{sin_a} semanas que no ingresa AFE-S de banda A</b>
y no queda nada de banda A en tanque. El AFE que entra se corrió hacia C y D: el fósforo promedio de la
banda D de esta semana fue {_n(next((x['p'] for x in D['afe_banda'] if x['semana']==sem and x['banda']=='D'), None),0)} ppm
contra un máximo de venta de 150 ppm. Como el AG-E se vende diluido, menos banda A y B significa menos
AG-E por contenedor o más riesgo de salir fuera de spec.</div>
{foot(2, "Ingresos y calidad")}</div>""")

    # ---------------- PÁGINA 3 ----------------
    H.append(f"""<div class="page">{head("Stock por calidad")}
<h2><span class="n">4</span>Stock único, por producto y por calidad</h2>
<p class="lead">Un solo número de stock: el que miden los radares y las varillas de los tanques.
Todo lo de abajo sale de esa medición, nunca de una estimación contable.
Total medido: <b>{_n(stock_tot,0)} TN</b> en {sum(r['tanques'] for r in stock)} tanques.</p>

<h3>AFE-S por banda · comprometido a despacho vs. libre (TN)</h3>
{g_afe}
<p class="leg"><span><span class="dot" style="background:#2a78d6"></span>color pleno = comprometido a un despacho confirmado</span>
<span><span class="dot" style="background:#cfd6df"></span>gris = libre</span></p>

<div class="cols">
  <div class="box"><b>Pool A+B (el que permite meter AG-C en la mezcla)</b><br>
    Stock: <b>{_n(ab,1)} TN</b> · libre: <b>{_n(ab_libre,1)} TN</b> ·
    {_n(ab/(afe_s_tot or 1)*100,0)}% del AFE-S en tanque.<br>
    Capacidad de dilución del AFE-S completo: <b>{_n(cap_dil,1)} TN de AG-C</b>
    (A×7% + B×4% + C×1,5%), contra <b>{_n(ag_c,1)} TN de AG-C</b> parados en tanque.</div>
  <div class="box"><b>Pool C+D (el que hay que colocar mezclado)</b><br>
    Stock: <b>{_n((afe_s.get('C',{}).get('tn',0) or 0)+(afe_s.get('D',{}).get('tn',0) or 0),1)} TN</b>
    · libre: <b>{_n((afe_s.get('C',{}).get('libre',0) or 0)+(afe_s.get('D',{}).get('libre',0) or 0),1)} TN</b><br>
    Es {_n(((afe_s.get('C',{}).get('tn',0) or 0)+(afe_s.get('D',{}).get('tn',0) or 0))/(afe_s_tot or 1)*100,0)}%
    del AFE-S en planta. Sin A+B suficiente, este material no tiene con qué diluirse.</div>
</div>

<h3>Todo el stock, por producto y calidad</h3>
{t_stock}

<h3>Comprometido para producción</h3>
<p class="lead">Movimientos planificados por el Centro de Planificación que todavía no se ejecutaron.
"Vencido" = el batch ya cerró y el movimiento nunca pasó a ejecutado: no es un compromiso real,
es deuda de datos que infla el comprometido.</p>
{t_cp}
<div class="box">Comprometido real (batches vivos): <b>{_n(comp_prod_vivo,1)} TN</b> ·
Planificados vencidos a limpiar: <b>{_n(sum(r['tn'] for r in D['comp_prod'] if r['vencido']),1)} TN</b> ·
Comprometido a despachos confirmados: <b>{_n(comp_desp_tot,1)} TN</b>.</div>
{foot(3, "Stock por calidad")}</div>""")

    # ---------------- PÁGINA 4 ----------------
    H.append(f"""<div class="page">{head("Desvíos de stock")}
<h2><span class="n">5</span>Desvíos: lo que el libro dice contra lo que hay en el tanque</h2>
<h3>Desvío del pool de exportación (AFE + AG) · TN por semana</h3>
{g_pool}
<p class="lead">Positivo = hay más material del que el libro explica. Negativo = falta.
Fórmula: stock inicial + producido + entradas − salidas − consumos internos = proyectado; desvío = medido − proyectado.</p>

<h3>Desvío por familia · semana {iso}</h3>
{t_fam}
<p class="lead">El color del desvío mide su <b>tamaño relativo</b> al stock de esa familia (verde &lt;10%,
ámbar &lt;25%, rojo por encima), no su signo.</p>

<div class="box"><b>Antes de sospechar de un faltante, mirá la cobertura del libro.</b> El desvío por familia
se explica casi entero por movimientos que ocurren físicamente y no se registran: el AFE que se mezcla y sale
como AG-E, y las salidas de AG que no descuentan del tanque. Por eso AFE y AG se compensan.
El número a vigilar es el consolidado del gráfico de arriba.</div>

<h3>Cobertura del libro por sector · semana {iso}</h3>
<p class="lead">Qué porcentaje del movimiento físico medido por los radares tiene un movimiento registrado
que lo explique. Por debajo de 50% el desvío de ese sector no es concluyente.</p>
{g_cob}

<h3>Confiabilidad de la medición</h3>
<p class="lead">Antigüedad de la última medición física por sector. Mientras esto se mantenga en horas,
el stock medido es un dato duro y el desvío apunta al registro, no a la balanza.</p>
{t_conf}
{foot(4, "Desvíos de stock")}</div>""")

    # ---------------- PÁGINA 5 ----------------
    H.append(f"""<div class="page">{head("Despachos, reacciones y proyección")}
<h2><span class="n">6</span>Cómo estamos posicionados para despachar</h2>
{t_desp}
<div class="box"><b>Posición.</b> {len(dfut)} despachos por delante ({_n(dfut_tn,1)} TN),
{dfut_fs} de ellos ya calculan fuera de spec con el stock actual. Con banda A en cero, cada contenedor
se arma prácticamente con AFE-S puro: el azufre promedio de los últimos {len(D['despachos'])} despachos
fue {_n(sum(d['s'] for d in D['despachos'])/max(len(D['despachos']),1),1)} ppm sobre un máximo de 50 —
{sum(1 for d in D['despachos'] if d['s']>=49)} de {len(D['despachos'])} salieron a 49 ppm o más.
Margen operativo: prácticamente cero.</div>

<h2><span class="n">7</span>Cómo vienen las reacciones</h2>
{t_reac}
<p class="lead">Rendimiento = kg reales sobre kg de fórmula. Utilización = cuánto del reactor se llenó.
Desvío h = ciclo real menos ciclo programado; sólo se promedia sobre batches con tiempos confiables.</p>

<h2><span class="n">8</span>Proyección · disposición final de líquidos</h2>
<p class="lead">TN acumuladas día a día, un mes por línea. La línea naranja punteada proyecta el cierre de
{fmes(liq_ult['mes'])} al ritmo diario de los primeros {liq_ult['ult']} días.</p>
{g_liq}
<div class="cols">
  <div class="box">Acumulado {fmes(liq_ult['mes'])} al día {liq_ult['ult']}: <b>{_n(liq_ult['tn'],0)} TN</b><br>
    Proyección de cierre de mes: <b>{_n(proy,0)} TN</b><br>
    {fmes(liq_prev['mes']) if liq_prev else '—'} cerró en <b>{_n(liq_prev['tn'],0) if liq_prev else '—'} TN</b>
    → <b>{_n((proy/(liq_prev['tn'] or 1)-1)*100,0) if liq_prev else '—'}%</b></div>
  <div class="box"><b>Qué mirar.</b> La pendiente de la línea del mes en curso contra las anteriores.
    Si se aplana a mitad de mes es caída de recepción; si se empina, es riesgo de capacidad en piletas.</div>
</div>
<p class="nota"><b>Nota metodológica.</b> Ingresos y salidas salen de los tickets de portería.
La calidad de cada ticket sale del último análisis de laboratorio de ese ticket; los que no tienen análisis
se cuentan en TN pero no en banda. El stock es medición física de tanque (radares WeDo y aforo por
centímetros). El desvío compara ese stock medido contra el libro de movimientos. Las reacciones salen de
los batches cerrados. Ningún número de este informe se carga a mano.</p>
{foot(5, "Despachos y proyección")}</div>""")

    return (f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            f'<title>WORMS · Brief de Dirección · {iso}</title><style>{css}</style></head>'
            f'<body>{"".join(H)}</body></html>')
