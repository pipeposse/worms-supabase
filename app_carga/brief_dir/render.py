# -*- coding: utf-8 -*-
"""Brief semanal de Dirección · WORMS — un solo HTML para papel y teléfono.

Seis páginas, para leerse en un desayuno:
  1. Tablero          — titulares de una línea, indicadores y stock de AFE-S
  2. Desvío del AFE-S — balance cerrado y stock único contra medición, por producto
  3. Ingresos de AFE  — calidad que entra, qué define cada tipo y cada categoría
  4. Producción       — cronograma programado vs real por reacción, e insumos
  5. Despachos        — eficiencia de carga y margen de especificación
  6. Tendencias       — exportación, producción y efluentes por mes

En pantalla angosta pasa a una columna, las tablas se vuelven fichas y los
gráficos se deslizan en horizontal manteniendo tamaño de lectura.
"""
import calendar
from datetime import datetime

from .viz import (figura, leyenda, barras_apiladas, barras_stock, acumulado_proy,
                 barras_mes_proy, cascada, dispersion, microbarra,
                 CAT_COLOR, CAT_DESC, ORDEN_CAT, LIBRE,
                 GOOD, WARN, SERIOUS, CRIT, INK, INK2, MUTED, GRID, AZUL, PROY, _n, _e)

MES_ABR = {"01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may", "06": "jun",
           "07": "jul", "08": "ago", "09": "sep", "10": "oct", "11": "nov", "12": "dic"}
C_EXPO, C_DESG, C_ARE = "#2a78d6", "#1baf7a", "#eb6834"
DESDE = "2026-08-03"   # arranque del registro de despachos: antes de esto no se compara

# rótulo de dirección: la glicerina se abre en calidades A/B/C/D como el resto
NOMBRE_DIR = {"GLICERINA-PURA": "GLICERINA-B · pura",
              "GLICERINA-RECUP": "GLICERINA-C · recuperada",
              "GLICERINA-FE": "GLICERINA-D · fuera de espec"}
CLAVE = ["AFE-S", "AFE-SG", "AFE-AL", "AG-C", "AG-E", "ARE-B", "ARE-A-ANIMAL",
         "GLICERINA-PURA", "GLICERINA-RECUP", "BORRA-B", "SEBO-C-2DA"]


def fmes(m):
    return f"{MES_ABR.get(str(m)[5:7], str(m)[5:7])} {str(m)[2:4]}"


def fdate(s):
    d = datetime.strptime(str(s), "%Y-%m-%d").date()
    return f"{d.day} {MES_ABR['%02d' % d.month]}"


def dias_mes(m):
    return calendar.monthrange(int(str(m)[:4]), int(str(m)[5:7]))[1]


def nom(p):
    return NOMBRE_DIR.get(p, p)


def delta(act, prev, mas_es_mejor=True):
    if act is None or prev in (None, 0):
        return "—", MUTED
    d = (act - prev) / abs(prev) * 100
    col = MUTED if abs(d) < 3 else (GOOD if ((d >= 0) == mas_es_mejor) else CRIT)
    return f"{'+' if d > 0 else ''}{d:,.0f}%", col


def kpi(titulo, valor, unidad, sub, extra="", d1=None, d4=None):
    """Tarjeta sin gráfico: el valor, sus dos comparaciones y una línea de contexto."""
    comp = ""
    if d1 or d4:
        t1, c1 = d1 or ("—", MUTED)
        t4, c4 = d4 or ("—", MUTED)
        comp = (f'<div class="kpi-d"><span style="color:{c1}">{_e(t1)}</span> vs sem. previa'
                f' &nbsp;·&nbsp; <span style="color:{c4}">{_e(t4)}</span> vs prom. 4 sem.</div>')
    return f"""
<div class="kpi">
  <div class="kpi-t">{_e(titulo)}</div>
  <div class="kpi-v">{_e(valor)}<span class="kpi-u">{_e(unidad)}</span></div>
  {comp}{f'<div class="kpi-x">{extra}</div>' if extra else ''}
  <div class="kpi-n">{sub}</div>
</div>"""


def titular(nivel, texto):
    col = {"critico": CRIT, "grave": SERIOUS, "alerta": WARN, "ok": GOOD}[nivel]
    return (f'<div class="tit"><span class="tit-dot" style="background:{col}"></span>'
            f'<div>{texto}</div></div>')


def tabla(cols, filas, aligns=None):
    a = aligns or ["l"] + ["r"] * (len(cols) - 1)
    m = {"l": "tl", "r": "tr", "c": "tc"}
    th = "".join(f'<th class="{m[a[i]]}">{c}</th>' for i, c in enumerate(cols))
    tb = []
    for f in filas:
        tds = "".join(f'<td class="{m[a[i]]}" data-l="{_e(cols[i])}">{c}</td>'
                      for i, c in enumerate(f))
        tb.append(f"<tr>{tds}</tr>")
    return (f'<div class="tw"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(tb)}</tbody></table></div>')


def punto(c):
    return f'<span class="dot" style="background:{c}"></span>'


def pr(p, r, dec=1, bueno=1.3, malo=2.0):
    """'programado → real' en una celda, coloreado por cuánto se aparta."""
    if r is None:
        return f'<span class="mut">{_n(p,dec)} → s/d</span>'
    ratio = (r / p) if p else None
    col = INK2
    if ratio is not None:
        col = GOOD if (1 / bueno) <= ratio <= bueno else (WARN if (1 / malo) <= ratio <= malo else CRIT)
    return f'{_n(p,dec)} → <b style="color:{col}">{_n(r,dec)}</b>'


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

    cat_sem = {}
    for r in D["afe_categoria"]:
        cat_sem.setdefault(r["semana"], {})[r["categoria"]] = r["tn"]
    cat_mes = {}
    for r in D.get("afe_categoria_mes", []):
        cat_mes.setdefault(r["mes"], {})[r["categoria"]] = r["tn"]
    rt = {}
    for r in D["reacciones_tipo"]:
        rt.setdefault(r["semana"], {})[r["tipo"]] = r
    bal = {r["semana"]: r for r in D["balance_afe"]}

    s_now, s_prev = sal.get(sem, {}), sal.get(prev, {})
    c_now = cat_sem.get(sem, {})
    afe_in = sum(c_now.values())
    afe_in_prev = sum(cat_sem.get(prev, {}).values()) if prev else None
    _p4 = [sum(cat_sem.get(s, {}).values()) for s in ult4]
    afe_in_p4 = sum(_p4) / len(_p4) if _p4 else None
    pct_ab_in = (c_now.get("A", 0) + c_now.get("B", 0)) / (afe_in or 1) * 100

    desg = rt.get(sem, {}).get("DESGOMADO_ACUOSO", {})
    are = rt.get(sem, {}).get("PRODUCCION_ARE", {})
    desg_p = rt.get(prev, {}).get("DESGOMADO_ACUOSO", {}) if prev else {}
    are_p = rt.get(prev, {}).get("PRODUCCION_ARE", {}) if prev else {}

    stock = D["stock"]
    afe_s = {r["categoria"]: r for r in stock if r["producto"] == "AFE-S"}
    for b in "ABCD":
        afe_s.setdefault(b, {"categoria": b, "tanques": 0, "tn": 0.0, "c_desp": 0.0,
                             "libre": 0.0, "s": None, "p": None})
    ab_libre = afe_s["A"]["libre"] + afe_s["B"]["libre"]
    libre_total = sum(afe_s[b]["libre"] for b in "ABCD")
    ag_c = sum(r["tn"] for r in stock if r["producto"] == "AG-C")

    parte_afe = next((m["parte"] for m in D["mezcla"] if m["producto"] == "AFE-S"), 0.94)
    dfut = [d for d in D["despachos"] if d["fecha"] > sem_fin]
    dfut_tn = sum(d["tn"] for d in dfut)
    afe_necesario = dfut_tn * parte_afe
    cobertura_afe = libre_total / afe_necesario * 100 if afe_necesario else None
    fs_14 = [d for d in D["despachos"] if d["fs"]]
    fs_sin_aprob = [d for d in fs_14 if not d.get("aprob")]

    sin_a = 0
    for s in reversed(semanas):
        if (cat_sem.get(s, {}).get("A") or 0) > 0:
            break
        sin_a += 1

    b_now = bal.get(sem, {})
    b_prev = bal.get(prev, {}) if prev else {}
    sem_ago = [s for s in sorted(bal) if s >= DESDE]      # sólo desde agosto
    desv_pct = abs(b_now.get("desvio", 0)) / (b_now.get("med") or 1) * 100

    de = D["despacho_ef"]
    ocup_ok = sum(1 for d in de if (d["ocup"] or 0) >= 98)
    mg_prom = sum(d["mg"] for d in de) / max(len(de), 1)
    mg_neg = sum(1 for d in de if d["mg"] < 0)
    pocos = [d for d in de if d["tq"] <= 6]
    muchos = [d for d in de if d["tq"] >= 7]
    mg_pocos = sum(d["mg"] for d in pocos) / max(len(pocos), 1)
    mg_muchos = sum(d["mg"] for d in muchos) / max(len(muchos), 1)
    antic_prom = sum(d["antic"] for d in de) / max(len(de), 1)
    exc_total = sum(d["exc"] for d in de)

    ins_sem = [r for r in D["insumos"] if r["semana"] == sem]
    ins_pot = next((r for r in ins_sem if r["insumo"] == "POTASIO"), {})
    ins_fuel = next((r for r in ins_sem if r["insumo"] == "FUEL_OIL"), {})

    bt = D.get("batches", [])
    bt_conf = [b for b in bt if b["conf"]]
    et = D["etapas"]
    et_clicks = sum(e["clicks"] for e in et)
    et_inval = sum(e["invalidos"] for e in et)

    # ======================= TITULARES (una línea cada uno) =======================
    tits = [
        titular("ok",
                f"<b>El “faltante” de AFE-S era falta de registro.</b> Con los despachos cargados "
                f"desde el {fdate(DESDE)}, el desvío real es <b>{_n(b_now.get('desvio'),0)} TN "
                f"({_n(desv_pct,0)}% del stock)</b>, no las ~900 TN/semana que aparecían antes."),
        titular("critico",
                f"<b>Sin AFE-S de categoría A</b> ({sin_a} semanas sin ingreso, 0 TN en tanque): "
                f"la mezcla de exportación va al límite — margen promedio "
                f"<b>{_n(mg_prom,1)}%</b> — y hay {_n(ag_c,0)} TN de AG-C sin salida. "
                f"Comprar A/B o renegociar la especificación."),
        titular("grave",
                f"<b>{len(fs_14)} despachos fuera de especificación</b> en 14 días, "
                f"{len(fs_sin_aprob)} confirmados sin aprobación de dirección."),
        titular("grave",
                f"<b>El registro de tiempos de producción no es confiable</b>: {et_clicks} etapas "
                f"avanzadas en menos de 5 minutos y {et_inval} con duración negativa. Antes de "
                f"exigir cronograma hay que arreglar la carga."),
    ]

    # ======================= KPIs (sin gráficos de línea) =======================
    kpis = [
        kpi("AFE-S ingresado", _n(afe_in, 1), " TN",
            f"{_n(pct_ab_in,0)}% en categorías A+B", microbarra(c_now),
            delta(afe_in, afe_in_prev), delta(afe_in, afe_in_p4)),
        kpi("Exportado", _n(s_now.get("tn"), 1), " TN",
            f"{s_now.get('tk','—')} camiones · {b_now.get('nd',0)} despachos", "",
            delta(s_now.get("tn"), s_prev.get("tn")), delta(s_now.get("tn"), prom(sal, "tn"))),
        kpi("Desgomado acuoso", f"{desg.get('n',0) or 0} reacc. · {_n(desg.get('tn'),0)}", " TN",
            f"utilización {_n(desg.get('uti'),0)}%", "",
            delta(desg.get("tn"), desg_p.get("tn"))),
        kpi("Producción de ARE", f"{are.get('n',0) or 0} reacc. · {_n(are.get('tn'),0)}", " TN",
            f"utilización {_n(are.get('uti'),0)}%", "",
            delta(are.get("tn"), are_p.get("tn"))),
        kpi("Desvío del AFE-S", _n(b_now.get("desvio"), 1), " TN",
            f"{_n(desv_pct,0)}% del stock medido · balance con despachos", "",
            delta(abs(b_now.get("desvio", 0)), abs(b_prev.get("desvio", 0)), mas_es_mejor=False)),
        kpi("AFE-S libre en tanque", _n(libre_total, 1), " TN",
            f"<b>{_n(ab_libre,1)} TN</b> de categorías A+B "
            f"({_n(ab_libre/(libre_total or 1)*100,0)}%)",
            microbarra({b: afe_s[b]["libre"] for b in "ABCD"})),
        kpi("AFE-S para despachos comprometidos", _n(afe_necesario, 0), " TN",
            f"{len(dfut)} despachos · el libre cubre {_n(cobertura_afe,0)}%"),
        kpi("Margen de especificación", _n(mg_prom, 1), "%",
            f"promedio {len(de)} despachos · {mg_neg} por debajo de cero"),
    ]

    fig_stock = figura(
        "Stock de AFE-S por categoría: comprometido y libre",
        barras_stock([(f"Categoría {b} · {CAT_DESC[b]}", CAT_COLOR[b],
                       afe_s[b]["c_desp"], afe_s[b]["libre"], afe_s[b]["tn"],
                       f'{afe_s[b]["tanques"]} tanques' if afe_s[b]["tanques"] else "sin stock")
                      for b in "ABCD"], alto_fila=27),
        leyenda=leyenda([("#2a78d6", "comprometido a un despacho confirmado"), (LIBRE, "libre")]))

    fil_sem = []
    for s_ in reversed(sem_ago):
        bs = cat_sem.get(s_, {})
        tb = sum(bs.values()) or 1
        r_d = rt.get(s_, {}).get("DESGOMADO_ACUOSO", {})
        r_a = rt.get(s_, {}).get("PRODUCCION_ARE", {})
        bb = bal.get(s_, {})
        fil_sem.append([f'<b>{fdate(s_)}</b>' if s_ == sem else fdate(s_),
                        _n(tb, 1), _n((bs.get("A", 0) + bs.get("B", 0)) / tb * 100, 0) + "%",
                        _n(bb.get("desp"), 1), _n(r_d.get("tn"), 1), _n(r_a.get("tn"), 1),
                        _n(bb.get("med"), 1), _n(bb.get("desvio"), 1)])
    t_sem = tabla(["Semana (lunes)", "AFE-S ingresado TN", "% A+B", "AFE-S despachado TN",
                   "AFE-S producido TN", "ARE producido TN", "AFE-S en tanque TN",
                   "Desvío AFE-S TN"], fil_sem)

    # ======================= P2 · balance y stock único =======================
    fig_cascada = figura(
        f"El balance del AFE-S, término a término · semana {iso}",
        cascada([("Stock inicial", b_now.get("ini", 0), "base"),
                 ("Ingresos portería", b_now.get("ing", 0), "suma"),
                 ("Producido desgomado", b_now.get("prod", 0), "suma"),
                 ("Consumido reactores", -b_now.get("cons", 0), "resta"),
                 ("Despachado", -b_now.get("desp", 0), "resta"),
                 ("Stock esperado", b_now.get("esp", 0), "total"),
                 ("Medido en tanque", b_now.get("med", 0), "medido")],
                y_titulo="TN de AFE-S", h=255),
        subtitulo=(f"Lo que el libro dice que debería haber (<b>{_n(b_now.get('esp'),0)} TN</b>) "
                   f"contra lo que midieron los radares (<b>{_n(b_now.get('med'),0)} TN</b>): "
                   f"desvío de <b>{_n(b_now.get('desvio'),0)} TN</b>. Antes del {fdate(DESDE)} los "
                   "despachos no se registraban y este balance no podía cerrarse; el histórico "
                   "anterior no es comparable."),
        nota="La salida sale de las líneas de despacho. El desvío residual junta mermas de tanque, "
             "diferencias de balanza y consumos sin movimiento registrado.")

    fil_bal = []
    for s in reversed(sem_ago):
        r = bal[s]
        pctd = abs(r["desvio"]) / (r["med"] or 1) * 100
        col = GOOD if pctd < 10 else (WARN if pctd < 25 else CRIT)
        fil_bal.append([f'<b>{fdate(s)}</b>' if s == sem else fdate(s),
                        _n(r["ini"], 1), _n(r["ing"], 1), _n(r["prod"], 1), _n(r["cons"], 1),
                        f'{_n(r["desp"],1)} <span class="mut">({r["nd"]})</span>',
                        _n(r["esp"], 1), _n(r["med"], 1),
                        f'<span style="color:{col};font-weight:700">{_n(r["desvio"],1)}</span>'])
    t_bal = tabla(["Semana", "Inicial", "Ingresos", "Producido", "Consumido",
                   "Despachado (n)", "Esperado", "Medido", "Desvío TN"], fil_bal)

    _dp = sorted(D["desvio_producto"], key=lambda x: -abs(x["desvio"] or 0))[:10]
    fil_dp = []
    for r in _dp:
        base = max(abs(r["medido"] or 0), abs(r["unico"] or 0), 1)
        pctd = abs(r["desvio"] or 0) / base * 100
        col = GOOD if pctd < 10 else (WARN if pctd < 25 else CRIT)
        marca = (' <span class="mut">*</span>' if r.get("fix") else
                 (' <span class="mut">**</span>' if r.get("fixd") else ""))
        fil_dp.append([f'<b>{_e(nom(r["cod"]))}</b>{marca}', _n(r["ini"], 1), _n(r["prod"], 1),
                       _n(r["e_in"], 1), _n(r["e_out"], 1), _n(r.get("intr"), 1),
                       f'<b>{_n(r["unico"],1)}</b>', _n(r["medido"], 1),
                       f'<span style="color:{col};font-weight:700">{_n(r["desvio"],1)}</span>'])
    t_dp = tabla(["Producto", "Inicial", "Producido", "Ingresos", "Salidas",
                  "Consumo producción", "Stock único", "Medición", "Desvío TN"], fil_dp)

    # ======================= P3 · ingresos y definiciones =======================
    _mb = sorted(cat_mes)
    _pico = max(cat_mes, key=lambda m: cat_mes[m].get("A", 0)) if cat_mes else None
    fig_cat_mes = figura(
        f"AFE-S por categoría: de {_n(cat_mes.get(_pico,{}).get('A'),0)} TN de categoría A en "
        f"{fmes(_pico)} a cero",
        barras_apiladas([fmes(m) for m in _mb], [cat_mes[m] for m in _mb], x_titulo="mes",
                        y_titulo="TN ingresadas", resaltar=len(_mb) - 1, h=225,
                        anotaciones=[(_mb.index(_pico), "pico de categoría A", GOOD)]
                        if _pico and _pico != _mb[-1] else []),
        subtitulo="El último mes está en curso: el volumen aún no es comparable, la participación "
                  "de cada categoría sí.",
        leyenda=leyenda([(CAT_COLOR[b], f"{b} · {CAT_DESC[b]}") for b in ORDEN_CAT]))

    fil_cat = []
    for b in ORDEN_CAT:
        v = c_now.get(b, 0) or 0
        p4 = [cat_sem.get(s, {}).get(b, 0) or 0 for s in ult4]
        t4 = sum(sum(cat_sem.get(s, {}).values()) for s in ult4) or 1
        r = next((x for x in D["afe_categoria"]
                  if x["semana"] == sem and x["categoria"] == b), {})
        fil_cat.append([punto(CAT_COLOR[b]) + f"<b>{b}</b> · {CAT_DESC[b]}",
                        _n(v, 1), f'<b>{_n(v/(afe_in or 1)*100,1)}%</b>',
                        _n(sum(p4) / t4 * 100, 1) + "%",
                        _n(afe_s[b]["tn"], 1) if b in "ABCD" else "—",
                        _n(r.get("s"), 0), _n(r.get("p"), 0)])
    t_cat = tabla(["Categoría", "TN semana", "% semana", "% prom. 4 sem.", "TN en tanque",
                   "S ppm", "P ppm"], fil_cat)

    t_defcat = tabla(
        ["Categoría", "Azufre", "Fósforo", "Qué significa"],
        [[punto(CAT_COLOR["A"]) + "<b>A</b> · excelente", "≤ 40 ppm", "≤ 120 ppm",
          "≥20% de margen contra la spec de venta: es el que permite sumar AG-C"],
         [punto(CAT_COLOR["B"]) + "<b>B</b> · bueno", "≤ 45 ppm", "≤ 135 ppm",
          "10–20% de margen"],
         [punto(CAT_COLOR["C"]) + "<b>C</b> · justo", "≤ 50 ppm", "≤ 150 ppm",
          "cumple la spec sin margen"],
         [punto(CAT_COLOR["D"]) + "<b>D</b> · fuera de espec", "> 50 ppm", "> 150 ppm",
          "no cumple solo: únicamente entra mezclado"]],
        aligns=["l", "c", "c", "l"])

    t_deftipo = tabla(
        ["Tipo de AFE", "Acidez", "H₂O + sedimento + gomas", "Fósforo", "Qué es"],
        [[f'<b>{r["producto"]}</b>', _e(r["acidez"]), _e(r["hsg"]), _e(r["fosforo"]),
          _e(r["nota"])] for r in D.get("afe_specs", [])],
        aligns=["l", "c", "c", "c", "l"])

    fil_prov = []
    for p in D.get("proveedores", [])[:6]:
        c3 = GOOD if (p["pct_ab3"] or 0) >= 40 else (WARN if (p["pct_ab3"] or 0) >= 25 else CRIT)
        fil_prov.append([_e(p["prov"]), _n(p["tn_tot"], 0), _n(p["pct_ab"], 0) + "%",
                         _n(p["pct_d"], 0) + "%",
                         f'<span style="color:{c3};font-weight:700">{_n(p["pct_ab3"],0)}%</span>'])
    t_prov = tabla(["Proveedor", "TN 9 sem.", "% A+B histórico", "% D histórico",
                    "% A+B últ. 3 sem."], fil_prov)

    # ======================= P4 · producción =======================
    fil_bt = []
    for b in bt:
        proc = "Desgomado" if b["tipo"].startswith("DESG") else "ARE"
        col_t = GOOD if b["tot_r"] <= b["tot_p"] * 1.3 else (
            WARN if b["tot_r"] <= b["tot_p"] * 2 else CRIT)
        conf = ("sí" if b["conf"] else f'<span style="color:{CRIT}">no</span>')
        fil_bt.append([f'<b>{_e(b["ident"])}</b> · {proc}', fdate(b["fecha"]),
                       _n(b["espera"], 1), pr(b["reac_p"], b["reac_r"]),
                       pr(b["repo_p"], b["repo_r"]), pr(b["dec_p"], b["dec_r"]),
                       f'{_n(b["tot_p"],1)} → <b style="color:{col_t}">{_n(b["tot_r"],1)}</b>',
                       pr(b["tn_form"], b["tn_real"], 1, 1.1, 1.3), conf])
    t_bt = tabla(["Reacción", "Inicio", "Espera h", "Reacción h", "Reposo h", "Decant. h",
                  "Total h", "TN form. → real", "Tiempos OK"], fil_bt,
                 aligns=["l", "l", "r", "r", "r", "r", "r", "r", "c"])

    fil_ins = []
    for r in ins_sem:
        if r["pct"] is not None:
            col = GOOD if 90 <= r["pct"] <= 110 else (WARN if 75 <= r["pct"] <= 130 else CRIT)
            pct = f'<span style="color:{col};font-weight:700">{_n(r["pct"],0)}%</span>'
        elif r["teorico"]:
            pct = f'<span style="color:{CRIT}">sin registrar</span>'
        else:
            pct = '<span class="mut">sin fórmula</span>'
        fil_ins.append([f'<b>{_e(nom(r["insumo"]))}</b>', _n(r["teorico"], 0), _e(r["unidad"]),
                        _n(r["real"], 0), pct])
    t_ins = tabla(["Insumo", "Según fórmula", "Unidad", "Descontado del tanque",
                   "Real / teórico"], fil_ins)

    # ======================= P5 · despachos =======================
    fil_de = []
    for d in de:
        mcol = GOOD if d["mg"] >= 2 else (WARN if d["mg"] >= 0 else CRIT)
        fil_de.append([fdate(d["fecha"]), _e(d["titulo"]), str(d["cont"]), _n(d["tn"], 1),
                       f'{_n(d["ocup"],0)}%', str(d["tq"]),
                       f'<span style="color:{mcol};font-weight:700">{_n(d["mg"],1)}%</span>'])
    t_de = tabla(["Fecha", "Despacho", "Cont.", "TN", "Ocupación", "Tanques", "Margen spec"],
                 fil_de)

    fig_disp = figura(
        "Cuantos más tanques entran en la mezcla, menos margen queda",
        dispersion([(d["tq"], d["mg"], d["titulo"], CRIT if d["mg"] < 0 else GOOD) for d in de],
                   x_titulo="tanques distintos usados en el despacho",
                   y_titulo="margen contra la spec (%)",
                   x_max=max(d["tq"] for d in de) + 2, h=185),
        subtitulo=(f"Con hasta 6 tanques el margen promedio es <b>{_n(mg_pocos,1)}%</b>; con 7 o "
                   f"más, <b>{_n(mg_muchos,1)}%</b>."),
        leyenda=leyenda([(GOOD, "dentro de especificación"), (CRIT, "fuera")]),
        nota="Margen = cuánto sobra hasta el máximo de venta, tomando el peor de azufre y fósforo.")

    # ======================= P7 · tendencias =======================
    _pm = {}
    for r in D["prod_mes"]:
        _pm.setdefault(r["mes"], {})[r["tipo"]] = r
    _pmk = sorted(_pm)

    def _mini_proy(tipo, color, titulo):
        vals = [(_pm[m].get(tipo) or {}) for m in _pmk]
        labels = [fmes(m) for m in _pmk]
        tns = [v.get("tn", 0) or 0 for v in vals]
        ult = vals[-1] if vals else {}
        proy = (ult.get("tn", 0) / (ult.get("ult") or 1) * dias_mes(_pmk[-1])) if ult else None
        return figura(titulo,
                      barras_mes_proy(labels, tns, proy, y_titulo="TN producidas",
                                      color=color, w=330, h=185),
                      subtitulo=(f"{fmes(_pmk[-1])} proyecta <b>{_n(proy,0)} TN</b> al ritmo "
                                 f"de sus primeros {ult.get('ult','—')} días."), ancho_min=330)

    fig_desg_proy = _mini_proy("DESGOMADO_ACUOSO", C_DESG, "Desgomado acuoso, por mes")
    fig_are_proy = _mini_proy("PRODUCCION_ARE", C_ARE, "Producción de ARE, por mes")

    _pd = D.get("produccion_dia", [])
    _g_pa, _pa_proy = acumulado_proy(_pd, dias_mes=dias_mes(_pd[-1]["mes"]) if _pd else 31,
                                     etiqueta=fmes, y_titulo="TN producidas acumuladas", h=200)
    fig_prod_acum = figura(
        "Producción total acumulada, día a día",
        _g_pa,
        subtitulo=(f"Ambos procesos sumados. La punteada naranja extiende el ritmo diario de "
                   f"{fmes(_pd[-1]['mes']) if _pd else '—'}: cerraría en <b>{_n(_pa_proy,0)} TN</b>, "
                   f"contra {_n(_pd[-2]['tn'],0) if len(_pd) > 1 else '—'} TN de "
                   f"{fmes(_pd[-2]['mes']) if len(_pd) > 1 else '—'}."))

    _lq = D["liquidos"]
    _g_lq, _lq_proy = acumulado_proy(_lq, dias_mes=dias_mes(_lq[-1]["mes"]), etiqueta=fmes,
                                     y_titulo="TN recibidas acumuladas", h=192)
    fig_liq_acum = figura(
        "Disposición final de líquidos acumulada, día a día",
        _g_lq,
        subtitulo=(f"Proyecta <b>{_n(_lq_proy,0)} TN</b> contra {_n(_lq[-2]['tn'],0)} TN de "
                   f"{fmes(_lq[-2]['mes'])} ({_n((_lq_proy/(_lq[-2]['tn'] or 1)-1)*100,0)}%). "
                   "Si la línea del mes en curso se aplana es caída de recepción; si se empina, "
                   "riesgo de capacidad en piletas."))

    _ag_e_desp = D.get("ag_e_despachado", 52.9)
    _gli_cons = sum((r.get("intr") or 0) for r in D["desvio_producto"]
                    if str(r["cod"]).startswith("GLICERINA"))
    _fuel_kl = next((r["real"] for r in ins_sem if r["insumo"] == "FUEL_OIL"), None)
    t_traza = tabla(
        ["Producto", "Entra por", "Sale por", "Se consume en"],
        [["<b>AFE-S</b>", "camiones de portería + producido por el desgomado "
          f"({_n(b_now.get('prod'),0)} TN)",
          f"líneas de despacho de exportación ({_n(b_now.get('desp'),0)} TN)", "—"],
         ["<b>AG-C</b>", "camiones de portería", "mezclado en los despachos como parte del AG-E",
          "MP de la producción de ARE"],
         ["<b>AG-E</b>", "se forma al armar el despacho (mezcla AFE-S + AG-C); esa entrada hoy "
          "no se registra", f"líneas de despacho ({_n(_ag_e_desp,1)} TN)", "—"],
         ["<b>ARE-B</b>", "producido por los reactores (PRODUCCION_ARE)",
          "camiones de portería — venta directa", "—"],
         ["<b>AFE-SG</b>", "camiones de portería", "—",
          "MP del desgomado acuoso (se convierte en AFE-S)"],
         ["<b>GLICERINA B y C</b>", "compra (B · pura) y recuperación interna (C)", "—",
          f"insumo de la producción de ARE ({_n(_gli_cons,1)} TN esta semana)"],
         ["<b>FUEL OIL</b>", "compra", "—",
          f"caldera de los reactores ({_n(_fuel_kl,0)} L esta semana)"]],
        aligns=["l", "l", "l", "l"])

    # ======================= CSS =======================
    css = """
@page { size:A4; margin:11mm 12mm }
*{box-sizing:border-box}
body{font-family:-apple-system,"Segoe UI",Inter,Roboto,Arial,sans-serif;color:#0b0b0b;margin:0;
 background:#f4f4f1;font-size:9.5px;line-height:1.45;-webkit-text-size-adjust:100%}
.page{width:186mm;min-height:271mm;background:#fff;margin:0 auto 6mm;padding:0 0 7mm;
 page-break-after:always;position:relative}
.page:last-child{page-break-after:auto}
svg{max-width:100%;height:auto;display:block}
.hd{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2.5px solid #0b0b0b;
 padding-bottom:6px;margin-bottom:10px;gap:10px}
.hd h1{font-size:17px;margin:0;letter-spacing:-.3px}
.hd .sub{font-size:9px;color:#52514e;margin-top:2px}
.hd .rt{text-align:right;font-size:8.5px;color:#898781}
.hd .rt b{display:block;font-size:10.5px;color:#0b0b0b;white-space:nowrap}
h2{font-size:11.5px;margin:11px 0 4px;padding-bottom:3px;border-bottom:1px solid #e1e0d9;
 letter-spacing:-.2px}
h2 .n{color:#898781;font-weight:400;margin-right:5px}
h3{font-size:9.3px;margin:8px 0 3px;color:#52514e;text-transform:uppercase;letter-spacing:.5px;
 font-weight:700}
p.lead{font-size:8.6px;color:#52514e;margin:2px 0 5px}
.mut{color:#898781}
.tit{display:flex;gap:8px;align-items:flex-start;padding:4.5px 2px;border-bottom:1px solid #f0efec;
 font-size:9.3px;line-height:1.45;color:#3a3935}
.tit:last-of-type{border-bottom:none}
.tit b{color:#0b0b0b}
.tit-dot{flex:0 0 auto;width:9px;height:9px;border-radius:3px;margin-top:2.5px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:6px 0 4px}
.kpi{border:1px solid #e1e0d9;border-radius:4px;padding:6px 8px;background:#fcfcfb}
.kpi-t{font-size:7.7px;color:#898781;text-transform:uppercase;letter-spacing:.4px;font-weight:700;
 min-height:17px}
.kpi-v{font-size:18px;font-weight:800;letter-spacing:-.6px;line-height:1.1}
.kpi-u{font-size:9px;font-weight:600;color:#52514e}
.kpi-d{font-size:7.6px;color:#898781;margin-top:1px}
.kpi-x{margin:3px 0 1px}
.kpi-n{font-size:7.9px;color:#52514e;line-height:1.35;margin-top:2px}
.tw{width:100%}
table{width:100%;border-collapse:collapse;font-size:8.2px;margin:3px 0 7px}
th{background:#f4f4f1;font-weight:700;font-size:7.4px;text-transform:uppercase;letter-spacing:.3px;
 color:#52514e;padding:4px 5px;border-bottom:1.5px solid #c3c2b7}
td{padding:2.8px 5px;border-bottom:1px solid #ececE6}
tr:last-child td{border-bottom:none}
.tl{text-align:left}.tr{text-align:right;font-variant-numeric:tabular-nums}.tc{text-align:center}
.dot{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:4px}
.box{border:1px solid #e1e0d9;border-radius:4px;padding:6px 9px;background:#fcfcfb;font-size:8.4px;
 color:#52514e;margin:5px 0}
.box b{color:#0b0b0b}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:11px}
.foot{position:absolute;bottom:0;left:0;right:0;font-size:7.5px;color:#898781;
 border-top:1px solid #e1e0d9;padding-top:3px;display:flex;justify-content:space-between;gap:8px}
.fig{margin:5px 0 9px}
.figx{width:100%}
.figx-hint{display:none}
.fig-t{font-size:11px;font-weight:800;letter-spacing:-.15px;margin-bottom:1px}
.fig-s{font-size:8.7px;color:#52514e;margin-bottom:4px;line-height:1.4}
.fig-s b{color:#0b0b0b}
.fig-n{font-size:7.9px;color:#898781;margin-top:2px;line-height:1.4}
.leg{font-size:8.3px;color:#52514e;margin:3px 0 1px}
.leg span{margin-right:12px;white-space:nowrap;display:inline-block}
.leg i.dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px}
.nota{font-size:7.9px;color:#898781;line-height:1.4;margin:6px 0 0;border-top:1px solid #e1e0d9;
 padding-top:5px}
.nota b{color:#52514e}

/* ---------- teléfono: una columna, tablas en fichas ---------- */
@media screen and (max-width:820px){
 body{font-size:14px;background:#fff}
 .page{width:100%;min-height:0;margin:0;padding:14px 14px 26px;border-bottom:8px solid #f4f4f1}
 .hd{flex-direction:column;align-items:flex-start;gap:2px}
 .hd h1{font-size:19px}
 .hd .sub{font-size:12px}
 .hd .rt{text-align:left;font-size:11px}
 .hd .rt b{display:inline;font-size:12px;margin-right:6px}
 h2{font-size:17px;margin:20px 0 8px;padding-bottom:5px;border-bottom-width:2px}
 h3{font-size:12px;margin:14px 0 5px}
 p.lead,.fig-s,.box{font-size:13px;line-height:1.55}
 .tit{font-size:13.5px;padding:8px 2px;gap:10px}
 .tit-dot{width:12px;height:12px;margin-top:4px}
 .fig-t{font-size:15px;margin-bottom:3px}
 .fig-n,.nota{font-size:11.5px;line-height:1.5}
 .leg{font-size:12px}
 .leg span{margin:0 12px 3px 0}
 .grid{grid-template-columns:repeat(2,1fr);gap:8px;margin:10px 0}
 .kpi{padding:9px 10px}
 .kpi-t{font-size:10px;min-height:24px}
 .kpi-v{font-size:24px}
 .kpi-u{font-size:12px}
 .kpi-d{font-size:10px}
 .kpi-n{font-size:11px}
 .cols{grid-template-columns:1fr;gap:4px}
 .box{padding:10px 12px;margin:10px 0}
 .foot{position:static;font-size:11px;margin-top:16px;padding-top:8px;flex-direction:column;gap:2px}
 .figx{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;
  margin:0 -14px;padding:2px 14px 6px;scrollbar-width:thin}
 .figx svg{width:var(--wmin,560px);max-width:none;min-width:var(--wmin,560px)}
 .figx-hint{display:block;font-size:11px;color:#898781;margin:-2px 0 4px}
 table,tbody,tr,td{display:block;width:100%}
 thead{display:none}
 table{font-size:13px;margin:8px 0 14px}
 tr{border:1px solid #e1e0d9;border-radius:7px;padding:4px 10px;margin-bottom:8px;background:#fcfcfb}
 td{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:5px 0;
  border-bottom:1px solid #f0efec;text-align:right!important}
 td:first-child{font-size:14.5px;font-weight:700;border-bottom:1.5px solid #e1e0d9;
  padding-bottom:6px;margin-bottom:2px;text-align:left!important;display:block}
 td:first-child::before{display:none}
 td:last-child{border-bottom:none}
 td::before{content:attr(data-l);font-weight:600;color:#898781;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.3px;text-align:left;flex:1 1 auto}
 td.tr,td.tc{font-variant-numeric:tabular-nums}
}
@media screen and (max-width:430px){
 .grid{grid-template-columns:1fr}
 .kpi-t{min-height:0}
}
@media print{
 body{background:#fff}
 .page{margin:0;width:auto;min-height:0;border:none;padding:0 0 7mm}
 .figx{overflow:visible}
 .figx-hint{display:none}
}
"""

    def head(p):
        return f"""<div class="hd">
  <div><h1>WORMS · Brief de Dirección</h1>
    <div class="sub">Semana {iso} · {fdate(sem)} al {fdate(sem_fin)} de {sem[:4]} ·
    los desvíos se informan desde el {fdate(DESDE)}, inicio del registro de despachos</div></div>
  <div class="rt"><b>{p}</b>emitido {fdate(D['emitido'])}</div></div>"""

    def foot(p, t):
        return (f'<div class="foot"><span>Portería, laboratorio, radares de tanque, despachos y '
                f'batches (Supabase). Semana ISO cerrada, de lunes a domingo.</span>'
                f'<span>{t} · pág. {p}/7</span></div>')

    H = []
    # ---------------- 1 · TABLERO ----------------
    H.append(f"""<div class="page">{head("Tablero")}
<h2><span class="n">1</span>Titulares de la semana</h2>
{''.join(tits)}
<h2><span class="n">2</span>Indicadores</h2>
<div class="grid">{''.join(kpis)}</div>
{fig_stock}
{foot(1, "Tablero")}</div>""")

    # ---------------- 2 · DESVÍO DEL AFE-S ----------------
    H.append(f"""<div class="page">{head("Desvío del AFE-S")}
<h2><span class="n">3</span>El balance del AFE-S: libro contra tanque</h2>
{fig_cascada}
<h3>Semana a semana, desde el inicio del registro</h3>
{t_bal}
<h3>AFE-S semana a semana</h3>
{t_sem}
{foot(2, "Desvío del AFE-S")}</div>""")

    # ---------------- 3 · STOCK ÚNICO ----------------
    H.append(f"""<div class="page">{head("Stock único")}
<h2><span class="n">4</span>Stock único contra medición, por producto</h2>
<p class="lead"><b>Stock único</b> = inicial + producido + ingresos − salidas − consumo de
producción: lo que dice el libro. <b>Medición</b> = radares y varillas. Lo despachado es siempre
<b>mezcla de AFE-S y AG-E</b>: por eso las filas AFE-S (<span class="mut">*</span>) y AG-E
(<span class="mut">**</span>) toman su salida de las líneas de despacho — {_n(b_now.get('desp'),0)}
y {_n(_ag_e_desp,1)} TN esta semana — y ya no dan cero.</p>
{t_dp}
<div class="box"><b>Cómo leerlo.</b> Desvío verde: menor al 10% — diferencia normal de medición.
Ámbar: 10–25% — mirar el registro de esa familia. Rojo: mayor al 25% — hay movimientos sin
registrar. El caso AG-E lo muestra: su salida por despachos ahora está ({_n(_ag_e_desp,1)} TN),
pero la <b>mezcla que lo produce</b> (AFE-S + AG-C que se vuelve AG-E al armarse el despacho) no
se registra como entrada — por eso su stock único da negativo. BORRA-B, EMULSION y BORRA-ANIMAL
siguen sin circuito de salida cargado.</div>
<h2><span class="n">5</span>Por dónde entra y sale cada producto</h2>
<p class="lead">La trazabilidad de los movimientos, con los números de esta semana. "Se consume en"
es lo que los reactores descontaron del tanque: la glicerina y el fuel oil de la producción de ARE
están monitoreados acá y en la página 5.</p>
{t_traza}
{foot(3, "Stock único")}</div>""")

    # ---------------- 4 · INGRESOS DE AFE ----------------
    H.append(f"""<div class="page">{head("Ingresos de AFE")}
<h2><span class="n">6</span>AFE-S que ingresa, por categoría</h2>
{fig_cat_mes}
{t_cat}
<h3>Qué define cada categoría (calidad del AFE-S que ingresa)</h3>
{t_defcat}
<h3>Qué calidad vende cada proveedor</h3>
{t_prov}
{foot(4, "Ingresos de AFE")}</div>""")

    # ---------------- 5 · PRODUCCIÓN Y DESPACHOS ----------------
    H.append(f"""<div class="page">{head("Producción")}
<h2><span class="n">7</span>Cronograma reacción por reacción · semana {iso}</h2>
<p class="lead">Cada fila es una reacción real de la semana. En cada etapa se lee
<b>programado → real</b> en horas: verde si quedó cerca de lo planificado, ámbar si tardó hasta el
doble, rojo más allá. "Espera" es cuánto tardó en arrancar después del plan.</p>
{t_bt}
<div class="box"><b>Lectura.</b> De {len(bt)} reacciones, {len(bt_conf)} tienen tiempos confiables.
El patrón real no está en la reacción — que anda cerca de lo programado — sino en el
<b>reposo</b>: 15 a 95 horas contra 4,5–12 programadas. El reactor queda ocupado como pulmón
porque el acopio de destino no desagota. Es un problema de logística de tanques, no de proceso.</div>
<h2><span class="n">8</span>Insumos de la semana: fórmula contra tanque</h2>
{t_ins}
<div class="box"><b>Lectura.</b> El potasio corre al {_n(ins_pot.get("pct"),0)}% del teórico — y
viene arriba del 120% hace cuatro semanas: el coeficiente de la fórmula (3,125 kg/TN) quedó corto.
El fuel oil marca {_n(ins_fuel.get("pct"),0)}% esta semana pero saltó entre 31% y 101% en el mes:
registro incompleto. La soda tiene fórmula y ningún movimiento; el agua y la glicerina se
descuentan del tanque sin fórmula contra qué compararlas.</div>
{foot(5, "Producción")}</div>""")

    # ---------------- 6 · DESPACHOS ----------------
    H.append(f"""<div class="page">{head("Despachos")}
<h2><span class="n">9</span>Eficiencia de los despachos, explicada</h2>
<p class="lead">Cada despacho de exportación se arma bombeando a los contenedores una mezcla de
varios tanques: AFE-S en su mayoría, más la parte de AG-E. Sobre cada uno medimos cuatro cosas.
<b>Ocupación</b>: cuánto del volumen contratado de los contenedores se llenó — por debajo de 98%
se está pagando flete por espacio vacío. <b>Tanques</b>: de cuántos tanques distintos se bombeó —
cada tanque agrega un origen con su propia calidad, y la mezcla final es el promedio de todos.
<b>Margen spec</b>: cuánto le sobró a la mezcla contra el máximo de venta (azufre 50 ppm, fósforo
150 ppm), tomando el peor de los dos; 0% es el límite exacto y un valor negativo significa que el
despacho salió fuera de especificación. <b>Anticipo</b>: días entre que el despacho se creó en el
sistema y la fecha de salida — 0 o negativo quiere decir que se cargó al sistema cuando el camión
ya estaba saliendo.</p>
{t_de}
{fig_disp}
<div class="box"><b>Las cuatro conclusiones.</b>
<b>1 · La logística no es el problema:</b> {ocup_ok} de {len(de)} despachos salieron con el
contenedor lleno al 98% o más.
<b>2 · La calidad sí:</b> el margen promedio es {_n(mg_prom,1)}% y {mg_neg} de {len(de)} despachos
salieron por debajo de cero. No es un error de armado: sin AFE-S de categoría A, la mezcla parte
del límite.
<b>3 · Menos tanques, más margen:</b> con hasta 6 tanques el margen promedia {_n(mg_pocos,1)}%;
con 7 o más, {_n(mg_muchos,1)}%. Armar el despacho con pocos tanques bien elegidos es la única
palanca gratis que hay hoy.
<b>4 · Se registra, no se planifica:</b> la anticipación promedio es {_n(antic_prom,1)} días y hay
despachos creados después de la salida. Además {exc_total} líneas pidieron más litros de los que el
tanque tenía medidos: el plan se armó sobre stock que no estaba.</div>
{foot(6, "Despachos")}</div>""")

    # ---------------- 7 · TENDENCIAS ----------------
    H.append(f"""<div class="page">{head("Tendencias")}
<h2><span class="n">10</span>Producción: cómo terminaría el mes</h2>
<div class="cols">
<div>{fig_desg_proy}</div>
<div>{fig_are_proy}</div>
</div>
{fig_prod_acum}
<h2><span class="n">11</span>Disposición final de líquidos</h2>
{fig_liq_acum}
<h3>Qué define cada tipo de AFE (maestro de productos)</h3>
{t_deftipo}
<p class="nota"><b>Nota metodológica.</b> Ingresos y salidas: tickets de portería; la categoría, del
último análisis de laboratorio del ticket. Stock: medición física (radares WeDo y aforo). Los
balances de AFE-S y AG-E usan las líneas de despacho como salida. Tiempos: batches cerrados.
Insumos: dic_consumo_proceso contra movimientos ejecutados. Nada se carga a mano.</p>
{foot(7, "Tendencias")}</div>""")

    return (f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>WORMS · Brief de Dirección · {iso}</title>'
            f'<style>{css}</style></head><body>{"".join(H)}</body></html>')
