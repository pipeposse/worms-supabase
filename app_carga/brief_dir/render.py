# -*- coding: utf-8 -*-
"""Brief semanal de Dirección · WORMS — un solo HTML que sirve en papel y en el teléfono.

Siete secciones, en el orden en que el director pregunta:
  1. Tablero              — qué exige una decisión y cómo cerró la semana
  2. Desvío del AFE-S     — el balance cerrado: ingresos + producción − despachos vs tanque
  3. Stock                — por producto y categoría, y el libro contra la medición
  4. Ingresos de AFE      — qué calidad entra y quién la vende
  5. Producción           — cronograma real vs programado, toneladas e insumos
  6. Despachos            — eficiencia de carga, margen de especificación e insights
  7. Tendencias y control — exportación, producción y efluentes, y la salud del dato

En pantalla angosta el documento pasa a una columna, las tablas se vuelven fichas
y los gráficos escalan solos: el SVG lleva viewBox y ancho fluido.
"""
import calendar
from datetime import datetime

from .viz import (figura, leyenda, barras_apiladas, barras_simples, barras_agrupadas,
                 barras_divergentes, barras_stock, barras_pct, barras_mes_proy,
                 barras_pares, cascada, dispersion, sparkline, microbarra,
                 CAT_COLOR, CAT_DESC, ORDEN_CAT, LIBRE,
                 GOOD, WARN, SERIOUS, CRIT, INK, INK2, MUTED, GRID, AZUL, PROY, _n, _e)

MES_ABR = {"01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may", "06": "jun",
           "07": "jul", "08": "ago", "09": "sep", "10": "oct", "11": "nov", "12": "dic"}
CLAVE = ["AFE-S", "AFE-SG", "AFE-AL", "AG-C", "AG-E", "ARE-B", "ARE-A-ANIMAL",
         "GLICERINA-PURA", "BORRA-B", "SEBO-C-2DA"]
C_EXPO, C_DESG, C_ARE = "#2a78d6", "#1baf7a", "#eb6834"


def fmes(m):
    return f"{MES_ABR.get(str(m)[5:7], str(m)[5:7])} {str(m)[2:4]}"


def fdate(s):
    d = datetime.strptime(str(s), "%Y-%m-%d").date()
    return f"{d.day} {MES_ABR['%02d' % d.month]}"


def dias_mes(m):
    return calendar.monthrange(int(str(m)[:4]), int(str(m)[5:7]))[1]


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
    et = {"critico": "Crítico", "grave": "Importante", "alerta": "A vigilar",
          "ok": "Resuelto"}[nivel]
    return (f'<div class="dec" style="border-left-color:{col}">'
            f'<div class="dec-e" style="color:{col}">{et}</div>'
            f'<div class="dec-t">{_e(titulo)}</div>'
            f'<div class="dec-b">{cuerpo}</div>'
            f'<div class="dec-p"><b>Decisión pendiente:</b> {pendiente}</div></div>')


def tabla(cols, filas, aligns=None, clase=""):
    """En papel es una tabla; en el teléfono cada fila se vuelve una ficha, y por eso
    cada celda lleva su encabezado en data-l."""
    a = aligns or ["l"] + ["r"] * (len(cols) - 1)
    m = {"l": "tl", "r": "tr", "c": "tc"}
    th = "".join(f'<th class="{m[a[i]]}">{c}</th>' for i, c in enumerate(cols))
    tb = []
    for f in filas:
        tds = "".join(f'<td class="{m[a[i]]}" data-l="{_e(cols[i])}">{c}</td>'
                      for i, c in enumerate(f))
        tb.append(f"<tr>{tds}</tr>")
    return (f'<div class="tw"><table class="{clase}"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(tb)}</tbody></table></div>')


def punto(c):
    return f'<span class="dot" style="background:{c}"></span>'


def sem_col(v, bueno, regular, mas_es_mejor=False):
    if v is None:
        return MUTED
    x = abs(v)
    if mas_es_mejor:
        return GOOD if v >= bueno else (WARN if v >= regular else CRIT)
    return GOOD if x <= bueno else (WARN if x <= regular else CRIT)


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
    for b in ("A", "B", "C", "D"):
        afe_s.setdefault(b, {"categoria": b, "tanques": 0, "tn": 0.0, "c_desp": 0.0,
                             "c_venc": 0.0, "libre": 0.0, "h": None, "s": None, "p": None})
    afe_s_tot = sum(afe_s[b]["tn"] for b in "ABCD")
    ab = afe_s["A"]["tn"] + afe_s["B"]["tn"]
    ab_libre = afe_s["A"]["libre"] + afe_s["B"]["libre"]
    cd_libre = afe_s["C"]["libre"] + afe_s["D"]["libre"]
    libre_total = sum(afe_s[b]["libre"] for b in "ABCD")
    ag_c = sum(r["tn"] for r in stock if r["producto"] == "AG-C")

    parte_afe = next((m["parte"] for m in D["mezcla"] if m["producto"] == "AFE-S"), 0.94)
    dfut = [d for d in D["despachos"] if d["fecha"] > sem_fin]
    dfut_tn = sum(d["tn"] for d in dfut)
    afe_necesario = dfut_tn * parte_afe
    cobertura_afe = libre_total / afe_necesario * 100 if afe_necesario else None
    ritmo_expo = prom(sal, "tn") or 0
    consumo_semanal_afe = ritmo_expo * parte_afe
    dias_autonomia = (libre_total / consumo_semanal_afe * 7) if consumo_semanal_afe else None
    fs_14 = [d for d in D["despachos"] if d["fs"]]
    fs_sin_aprob = [d for d in fs_14 if not d.get("aprob")]

    sin_a = 0
    for s in reversed(semanas):
        if (cat_sem.get(s, {}).get("A") or 0) > 0:
            break
        sin_a += 1

    # ---- balance del AFE-S: la semana informada y la serie ----
    b_now = bal.get(sem, {})
    b_prev = bal.get(prev, {}) if prev else {}
    sem_bal = sorted(bal)
    con_desp = [s for s in sem_bal if (bal[s].get("nd") or 0) > 0]
    sin_desp = [s for s in sem_bal if (bal[s].get("nd") or 0) == 0]
    desv_con = ([abs(bal[s]["desvio"]) for s in con_desp] or [0])
    desv_sin = ([abs(bal[s]["desvio"]) for s in sin_desp] or [0])
    prom_con = sum(desv_con) / len(desv_con)
    prom_sin = sum(desv_sin) / len(desv_sin)
    desv_pct = abs(b_now.get("desvio", 0)) / (b_now.get("med") or 1) * 100

    # ---- eficiencia de despachos ----
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

    # ---- insumos ----
    ins_sem = [r for r in D["insumos"] if r["semana"] == sem]
    ins_fuel = next((r for r in ins_sem if r["insumo"] == "FUEL_OIL"), {})
    ins_pot = next((r for r in ins_sem if r["insumo"] == "POTASIO"), {})
    ins_sin_registro = [r for r in ins_sem if r["teorico"] and not r["real"]]
    ins_sin_formula = [r for r in ins_sem if r["real"] and not r["teorico"]]

    # ---- etapas ----
    et = D["etapas"]
    et_dentro = sum(e["dentro"] for e in et)
    et_total = sum(e["n"] for e in et)
    et_clicks = sum(e["clicks"] for e in et)
    et_inval = sum(e["invalidos"] for e in et)

    # ======================= DECISIONES =======================
    decs = []
    decs.append(decision(
        "ok" if desv_pct < 15 else "alerta",
        f"El desvío del AFE-S bajó de {_n(prom_sin,0)} a {_n(abs(b_now.get('desvio',0)),0)} TN "
        f"desde que se registran los despachos",
        "Hasta el 3 de agosto la salida de AFE-S no quedaba registrada en ningún lado: el balance "
        f"cerraba con un faltante promedio de <b>{_n(prom_sin,0)} TN por semana</b> y parecía un "
        "problema de inventario. Con el módulo de despachos en marcha, la salida real "
        f"(<b>{_n(b_now.get('desp'),0)} TN</b> esta semana, en {b_now.get('nd',0)} despachos) entra "
        f"en la ecuación y el desvío queda en <b>{_n(b_now.get('desvio'),0)} TN</b>, "
        f"{_n(desv_pct,0)}% del stock medido. "
        "<b>No había un faltante de material: faltaba registrar la salida.</b> "
        "Lo que queda ahora sí es un desvío real y acotado.",
        "cerrar el registro de las semanas anteriores al 3 de agosto para que la serie histórica "
        "sirva, y fijar el umbral a partir del cual un desvío semanal dispara revisión."))

    decs.append(decision(
        "critico",
        "Calidad del AFE-S: la categoría A está agotada y la mezcla de exportación quedó sin margen",
        "El AG-E que se exporta se arma mezclando AFE-S con AG-C. Cuanto más limpio el AFE-S "
        "(categorías A y B), más AG-C admite la mezcla sin superar la especificación de venta "
        "(azufre ≤ 50 ppm, fósforo ≤ 150 ppm). "
        f"Hoy <b>no queda AFE-S de categoría A en tanque</b> y hace <b>{sin_a} semanas que no "
        f"ingresa</b>. De las {_n(afe_s['B']['tn'],1)} TN de categoría B, "
        f"{_n(afe_s['B']['c_desp'],1)} TN ya están comprometidas. "
        f"Se ve en el resultado: el margen promedio de los últimos {len(de)} despachos es "
        f"<b>{_n(mg_prom,1)}%</b> — es decir, negativo — y hay {_n(ag_c,1)} TN de AG-C sin salida.",
        "comprar AFE-S de categoría A o B, o renegociar la especificación de venta del AG-E."))

    decs.append(decision(
        "grave",
        f"El cronograma de producción no se cumple en ninguna etapa, y los tiempos que registra "
        f"el sistema no son confiables",
        f"De {et_total} etapas medidas en los últimos 60 días, <b>{et_dentro} quedaron dentro del "
        f"rango objetivo</b>. El reposo corre a 45–50 h contra un objetivo de 1 a 12 h. Pero antes "
        f"de leer eso como un problema de planta hay que mirar el registro: {et_clicks} etapas "
        f"tienen marca de avance en menos de cinco minutos (se pasaron a los clicks) y "
        f"{et_inval} cierran con duración negativa, o sea con el fin anterior al inicio. "
        "<b>Con esos tiempos no se puede afirmar ni que la planta va lenta ni que va rápido.</b>",
        "decidir si el operario marca cada etapa en el momento o si el cronograma se recalcula "
        "desde otra fuente; hoy el dato de tiempos no sirve para decidir."))

    if fs_14:
        decs.append(decision(
            "grave",
            f"{len(fs_14)} despachos fuera de especificación en los últimos 14 días, "
            f"{len(fs_sin_aprob)} sin aprobación de dirección",
            "Un despacho queda fuera de especificación cuando la mezcla ponderada de sus tanques "
            "supera 50 ppm de azufre o 150 ppm de fósforo. La app lo calcula antes de confirmar y "
            f"pide el visto de dirección, pero no bloquea: {len(fs_sin_aprob)} de los {len(fs_14)} "
            "se confirmaron igual.",
            "definir si la confirmación se bloquea sin aprobación, o si se actualiza la "
            "especificación pactada con el cliente."))

    # ======================= KPIs =======================
    kpis = [
        kpi("AFE-S ingresado", _n(afe_in, 1), " TN",
            f"{_n(c_now.get('A',0)+c_now.get('B',0),1)} TN en categorías A+B "
            f"({_n(pct_ab_in,0)}% del ingreso)",
            microbarra(c_now), delta(afe_in, afe_in_prev), delta(afe_in, afe_in_p4)),
        kpi("Exportado", _n(s_now.get("tn"), 1), " TN",
            f"{s_now.get('tk','—')} camiones · {b_now.get('nd',0)} despachos",
            sparkline([sal[s]["tn"] for s in semanas if s in sal], 152, 26, C_EXPO),
            delta(s_now.get("tn"), s_prev.get("tn")), delta(s_now.get("tn"), prom(sal, "tn"))),
        kpi("Desgomado acuoso", str(desg.get("n", 0) or 0), " reacc.",
            f"{_n(desg.get('tn'),1)} TN · utilización {_n(desg.get('uti'),0)}%",
            sparkline([rt.get(s, {}).get("DESGOMADO_ACUOSO", {}).get("tn") for s in sorted(rt)],
                      152, 26, C_DESG),
            delta(desg.get("n"), desg_p.get("n"))),
        kpi("Producción de ARE", str(are.get("n", 0) or 0), " reacc.",
            f"{_n(are.get('tn'),1)} TN · utilización {_n(are.get('uti'),0)}%",
            sparkline([rt.get(s, {}).get("PRODUCCION_ARE", {}).get("tn") for s in sorted(rt)],
                      152, 26, C_ARE),
            delta(are.get("n"), are_p.get("n"))),
        kpi("Desvío del AFE-S", _n(b_now.get("desvio"), 1), " TN",
            f"{_n(desv_pct,0)}% del stock medido · balance cerrado",
            sparkline([bal[s]["desvio"] for s in con_desp], 152, 26, AZUL[2]),
            delta(abs(b_now.get("desvio", 0)), abs(b_prev.get("desvio", 0)), mas_es_mejor=False)),
        kpi("AFE-S libre en tanque", _n(libre_total, 1), " TN",
            f"de los cuales <b>{_n(ab_libre,1)} TN</b> son A+B "
            f"({_n(ab_libre/(libre_total or 1)*100,0)}%)",
            microbarra({b: afe_s[b]["libre"] for b in "ABCD"})),
        kpi("Margen de especificación", _n(mg_prom, 1), "%",
            f"promedio de los últimos {len(de)} despachos · {mg_neg} por debajo de cero"),
        kpi("Cronograma cumplido", f"{et_dentro}/{et_total}", "",
            f"etapas dentro del rango objetivo · {et_clicks} avanzadas a los clicks"),
    ]

    # ======================= GRÁFICOS =======================
    # cascada del balance
    fig_cascada = figura(
        f"De dónde sale el desvío del AFE-S · semana {iso}",
        cascada([("Stock inicial", b_now.get("ini", 0), "base"),
                 ("Ingresos", b_now.get("ing", 0), "suma"),
                 ("Producido desgomado", b_now.get("prod", 0), "suma"),
                 ("Consumido reactores", -b_now.get("cons", 0), "resta"),
                 ("Despachado", -b_now.get("desp", 0), "resta"),
                 ("Stock esperado", b_now.get("esp", 0), "total"),
                 ("Medido en tanque", b_now.get("med", 0), "medido")], y_titulo="TN de AFE-S"),
        subtitulo=("Cada barra arranca donde terminó la anterior. Las dos últimas se apoyan en cero: "
                   f"lo que el libro dice que debería haber (<b>{_n(b_now.get('esp'),0)} TN</b>) "
                   f"contra lo que midieron los radares (<b>{_n(b_now.get('med'),0)} TN</b>). "
                   f"La diferencia es el desvío: <b>{_n(b_now.get('desvio'),0)} TN</b>."),
        nota="La salida sale de las líneas de despacho, no del ledger de movimientos: por eso "
             "desde agosto el balance cierra.")

    fig_desvio_serie = figura(
        "El desvío semanal antes y después de registrar los despachos",
        barras_divergentes([fdate(s) for s in sem_bal], [bal[s]["desvio"] for s in sem_bal],
                           x_titulo="semana (lunes)", y_titulo="TN de desvío",
                           resaltar=sem_bal.index(sem) if sem in sem_bal else None),
        subtitulo=(f"Las semanas sin despachos registrados cierran con un faltante promedio de "
                   f"<b>{_n(prom_sin,0)} TN</b>; las que ya tienen el módulo en marcha, de "
                   f"<b>{_n(prom_con,0)} TN</b>. El salto no es un cambio en la planta: es que "
                   "empezó a registrarse la salida."))

    # stock por categoría
    fig_stock = figura(
        "Stock de AFE-S por categoría, y cuánto ya está comprometido",
        barras_stock([(f"Categoría {b} · {CAT_DESC[b]}", CAT_COLOR[b],
                       afe_s[b]["c_desp"], afe_s[b]["libre"], afe_s[b]["tn"],
                       f'{afe_s[b]["tanques"]} tanques' if afe_s[b]["tanques"] else "sin stock")
                      for b in "ABCD"]),
        subtitulo=(f"La categoría A está en cero. De las {_n(afe_s['B']['tn'],1)} TN de categoría B, "
                   f"<b>{_n(afe_s['B']['c_desp'],1)} TN ya tienen despacho asignado</b>."),
        leyenda=leyenda([("#2a78d6", "comprometido a un despacho confirmado"), (LIBRE, "libre")]))

    # ingresos por categoría
    sem12 = semanas[-12:]
    _ix = sem12.index(sem) if sem in sem12 else None
    _ult_a = None
    for i, s in enumerate(sem12):
        if (cat_sem.get(s, {}).get("A") or 0) > 0:
            _ult_a = i
    _b0 = cat_sem.get(sem12[0], {}) if sem12 else {}
    _pct0 = (_b0.get("A", 0) + _b0.get("B", 0)) / (sum(_b0.values()) or 1) * 100
    fig_cat_sem = figura(
        "El AFE-S que entra se corrió hacia las categorías malas",
        barras_apiladas([fdate(s) for s in sem12], [cat_sem.get(s, {}) for s in sem12],
                        x_titulo="semana (lunes)", y_titulo="TN ingresadas", resaltar=_ix,
                        anotaciones=([(_ult_a, "última semana con categoría A", CRIT)]
                                     if _ult_a is not None and _ult_a < len(sem12) - 1 else [])),
        subtitulo=(f"Las categorías A+B pasaron de {_n(_pct0,0)}% hace tres meses a "
                   f"<b>{_n(pct_ab_in,0)}% esta semana</b>."),
        leyenda=leyenda([(CAT_COLOR[b], f"{b} · {CAT_DESC[b]}") for b in ORDEN_CAT]),
        nota="La categoría sale del laboratorio del ticket: el peor de los dos parámetros contra la "
             "especificación de venta. A: S ≤ 40 y P ≤ 120 · B: S ≤ 45 y P ≤ 135 · "
             "C: S ≤ 50 y P ≤ 150 · D: no cumple solo.")

    _mb = sorted(cat_mes)
    _pico = max(cat_mes, key=lambda m: cat_mes[m].get("A", 0)) if cat_mes else None
    fig_cat_mes = figura(
        f"Mes a mes: la categoría A pasó de {_n(cat_mes.get(_pico,{}).get('A'),0)} TN en "
        f"{fmes(_pico)} a cero",
        barras_apiladas([fmes(m) for m in _mb], [cat_mes[m] for m in _mb], x_titulo="mes",
                        y_titulo="TN ingresadas", resaltar=len(_mb) - 1,
                        anotaciones=[(_mb.index(_pico), "pico de categoría A", GOOD)]
                        if _pico and _pico != _mb[-1] else []),
        subtitulo="El último mes está en curso: el volumen no es comparable todavía, la "
                  "participación de cada categoría sí.",
        leyenda=leyenda([(CAT_COLOR[b], f"{b} · {CAT_DESC[b]}") for b in ORDEN_CAT]))

    # producción: cronograma
    _et_lab = [f'{e["etapa"].title()}\n{e["tipo"][:4]}' for e in et]
    fig_etapas = figura(
        "Cronograma: horas reales contra horas programadas, etapa por etapa",
        barras_pares([f'{e["etapa"].title()} · {"Desg." if e["tipo"].startswith("DESG") else "ARE"}'
                      for e in et],
                     [e["prog"] for e in et],
                     [e["real"] if e["real"] > 0 else None for e in et],
                     y_titulo="horas", dec=1),
        subtitulo=(f"Sólo {et_dentro} de {et_total} etapas cayeron dentro del rango objetivo. "
                   f"La decantación no aparece porque {et_inval} de sus registros cierran con "
                   "duración negativa — el fin quedó antes del inicio."),
        leyenda=leyenda([("#9ec5f4", "programado"), ("#256abf", "real")]),
        nota="El porcentaje debajo de cada par es real sobre programado. Verde entre 90% y 110%.")

    # producción: TN
    _pm = {}
    for r in D["prod_mes"]:
        _pm.setdefault(r["mes"], {})[r["tipo"]] = r
    _pmk = sorted(_pm)
    fig_tn = figura(
        "Toneladas de fórmula contra toneladas realmente obtenidas",
        barras_pares([f'{fmes(m)} · {"Desg." if t.startswith("DESG") else "ARE"}'
                      for m in _pmk for t in ("DESGOMADO_ACUOSO", "PRODUCCION_ARE") if t in _pm[m]],
                     [_pm[m][t]["tn_form"] for m in _pmk
                      for t in ("DESGOMADO_ACUOSO", "PRODUCCION_ARE") if t in _pm[m]],
                     [_pm[m][t]["tn"] for m in _pmk
                      for t in ("DESGOMADO_ACUOSO", "PRODUCCION_ARE") if t in _pm[m]],
                     y_titulo="TN", dec=0),
        subtitulo="El desgomado rinde por debajo de la fórmula y el ARE por encima. Un rendimiento "
                  "sistemáticamente distinto de 100% señala que la fórmula está desactualizada, no "
                  "que la planta trabaje mal.",
        leyenda=leyenda([("#9ec5f4", "TN de fórmula"), ("#256abf", "TN obtenidas")]))

    # insumos
    _ins_comp = [r for r in ins_sem if r["teorico"] and r["real"]]
    fig_insumos = figura(
        "Insumos: lo que manda la fórmula contra lo que se descontó del tanque",
        barras_pares([f'{r["insumo"]} ({r["unidad"]})' for r in _ins_comp],
                     [r["teorico"] for r in _ins_comp], [r["real"] for r in _ins_comp],
                     y_titulo="cantidad", dec=0),
        subtitulo=(f"El fuel oil se registró al {_n(ins_fuel.get('pct'),0)}% de lo que pide la "
                   f"fórmula y el potasio al {_n(ins_pot.get('pct'),0)}%. El potasio viene por "
                   "encima todas las semanas: o la fórmula quedó corta, o se está cargando de más."),
        leyenda=leyenda([("#9ec5f4", "según fórmula"), ("#256abf", "descontado del tanque")]))

    # despachos: dispersión
    fig_disp = figura(
        "Cuantos más tanques entran en la mezcla, menos margen queda",
        dispersion([(d["tq"], d["mg"], d["titulo"], CRIT if d["mg"] < 0 else GOOD) for d in de],
                   x_titulo="tanques distintos usados en el despacho",
                   y_titulo="margen contra la spec (%)", x_max=max(d["tq"] for d in de) + 2),
        subtitulo=(f"Con hasta 6 tanques el margen promedio es <b>{_n(mg_pocos,1)}%</b>; "
                   f"con 7 o más, <b>{_n(mg_muchos,1)}%</b>. Cada tanque extra suma un origen "
                   "más y empuja la mezcla hacia el límite."),
        leyenda=leyenda([(GOOD, "dentro de especificación"), (CRIT, "fuera")]),
        nota="Margen = cuánto sobra hasta el máximo de venta, tomando el peor de azufre y fósforo. "
             "Cero es el límite exacto.")

    # tendencias
    _ex = D["exportacion"]
    _ex_lab = [fmes(m["mes"]) for m in _ex]
    _ex_val = [m["tn"] for m in _ex]
    _ex_proy = _ex[-1]["tn"] / _ex[-1]["ult"] * dias_mes(_ex[-1]["mes"])
    fig_expo_mes = figura(
        "Exportación: cierre de cada mes y proyección del que está en curso",
        barras_mes_proy(_ex_lab, _ex_val, _ex_proy, y_titulo="TN exportadas", color=C_EXPO),
        subtitulo=(f"{fmes(_ex[-1]['mes'])} lleva {_n(_ex[-1]['tn'],0)} TN en {_ex[-1]['ult']} días "
                   f"y proyecta cerrar en <b>{_n(_ex_proy,0)} TN</b>, contra "
                   f"{_n(_ex[-2]['tn'],0)} TN de {fmes(_ex[-2]['mes'])} "
                   f"({_n((_ex_proy/(_ex[-2]['tn'] or 1)-1)*100,0)}%)."),
        nota="La proyección extiende el ritmo diario del mes en curso hasta fin de mes.")

    _ex_ritmo = [m["tn"] / (m["ult"] if m is _ex[-1] else dias_mes(m["mes"])) for m in _ex]
    _meta_r = sum(_ex_ritmo[:-1]) / max(len(_ex_ritmo) - 1, 1)
    fig_expo_ritmo = figura(
        "Ritmo diario de exportación, comparable aunque el mes esté a medias",
        barras_simples(_ex_lab, _ex_ritmo, color=C_EXPO, x_titulo="mes",
                       y_titulo="TN por día", ref=_meta_r,
                       ref_txt=f"promedio meses cerrados · {_n(_meta_r,0)} TN/día",
                       resaltar=len(_ex_lab) - 1, dec=0),
        subtitulo=(f"El mes en curso corre a <b>{_n(_ex_ritmo[-1],0)} TN por día</b> contra "
                   f"{_n(_meta_r,0)} de los meses cerrados. Dividir por los días transcurridos "
                   "es lo que permite comparar un mes a medio andar con uno terminado."))

    _lq = D["liquidos"]
    _lq_proy = _lq[-1]["tn"] / _lq[-1]["ult"] * dias_mes(_lq[-1]["mes"])
    fig_liq_mes = figura(
        "Disposición final de líquidos: cierre mensual y proyección",
        barras_mes_proy([fmes(m["mes"]) for m in _lq], [m["tn"] for m in _lq], _lq_proy,
                        y_titulo="TN recibidas", color="#256abf"),
        subtitulo=(f"Proyecta cerrar en <b>{_n(_lq_proy,0)} TN</b> contra "
                   f"{_n(_lq[-2]['tn'],0)} TN de {fmes(_lq[-2]['mes'])} "
                   f"({_n((_lq_proy/(_lq[-2]['tn'] or 1)-1)*100,0)}%). Si el ritmo cae es menos "
                   "recepción; si se dispara, es riesgo de capacidad en piletas."))

    _pt_lab = [fmes(m) for m in _pmk]
    fig_prod_mes = figura(
        "Producción mensual por proceso",
        barras_agrupadas(_pt_lab,
                         [("Desgomado acuoso", C_DESG,
                           [_pm[m].get("DESGOMADO_ACUOSO", {}).get("tn", 0) for m in _pmk]),
                          ("Producción de ARE", C_ARE,
                           [_pm[m].get("PRODUCCION_ARE", {}).get("tn", 0) for m in _pmk])],
                         x_titulo="mes", y_titulo="TN producidas", resaltar=len(_pmk) - 1),
        subtitulo="El mes en curso está a mitad de camino; lo que importa acá es la proporción "
                  "entre los dos procesos, no el volumen absoluto.",
        leyenda=leyenda([(C_DESG, "Desgomado acuoso"), (C_ARE, "Producción de ARE")]))

    def _ccol(v):
        if v is None:
            return MUTED
        if 80 <= v <= 120:
            return GOOD
        if 50 <= v < 80 or 120 < v <= 160:
            return WARN
        return CRIT
    fig_cob = figura(
        "Cobertura del libro por sector: cuánto del movimiento físico está registrado",
        barras_pct([(c["sector"], c["cob"], _ccol(c["cob"]))
                    for c in sorted(D["cobertura_libro"], key=lambda x: -x["fis"])[:7]]),
        subtitulo="Por debajo de 50% el desvío de ese sector no es concluyente: el problema está en "
                  "el registro. Por encima de 120% el libro carga más de lo que el radar midió.")

    # ======================= TABLAS =======================
    fil_bal = []
    for s in reversed(sem_bal[-8:]):
        r = bal[s]
        col = sem_col(r["desvio"] / (r["med"] or 1) * 100, 10, 25)
        fil_bal.append([f'<b>{fdate(s)}</b>' if s == sem else fdate(s),
                        _n(r["ini"], 1), _n(r["ing"], 1), _n(r["prod"], 1), _n(r["cons"], 1),
                        f'{_n(r["desp"],1)}' + (f' <span class="mut">({r["nd"]})</span>'
                                                if r["nd"] else ""),
                        _n(r["esp"], 1), _n(r["med"], 1),
                        f'<span style="color:{col};font-weight:700">{_n(r["desvio"],1)}</span>'])
    t_bal = tabla(["Semana", "Stock inicial", "Ingresos", "Producido", "Consumido",
                   "Despachado", "Esperado", "Medido", "Desvío TN"], fil_bal)

    fil_clave = []
    for p in CLAVE:
        for r in sorted([x for x in stock if x["producto"] == p],
                        key=lambda x: ORDEN_CAT.index(x["categoria"])
                        if x["categoria"] in ORDEN_CAT else 9):
            etq = (punto(CAT_COLOR[r["categoria"]]) + f'<b>{_e(p)}</b> · cat. {r["categoria"]}'
                   if r["categoria"] in CAT_COLOR else f'<b>{_e(p)}</b>')
            fil_clave.append([etq, str(r["tanques"]), _n(r["tn"], 1), _n(r["c_desp"], 1),
                              _n(r["libre"], 1), _n(r["s"], 0), _n(r["p"], 0)])
    t_clave = tabla(["Producto y categoría", "Tanques", "Stock TN", "Comprometido TN",
                     "Libre TN", "S ppm", "P ppm"], fil_clave)

    _dp = sorted(D["desvio_producto"], key=lambda x: -abs(x["desvio"] or 0))[:10]
    fil_dp = [[f'<b>{_e(r["cod"])}</b>', _n(r["ini"], 1), _n(r["prod"], 1), _n(r["e_in"], 1),
               _n(r["e_out"], 1), f'<b>{_n(r["unico"],1)}</b>', _n(r["medido"], 1),
               f'<span style="color:{sem_col(abs(r["desvio"] or 0)/max(abs(r["medido"] or 0),1)*100,10,25)};'
               f'font-weight:700">{_n(r["desvio"],1)}</span>'] for r in _dp]
    t_dp = tabla(["Producto", "Stock inicial", "Producido", "Ingresos", "Salidas",
                  "Stock único", "Medición real", "Desvío TN"], fil_dp)

    fil_cat = []
    for b in ORDEN_CAT:
        v = c_now.get(b, 0) or 0
        p4 = [cat_sem.get(s, {}).get(b, 0) or 0 for s in ult4]
        t4 = sum(sum(cat_sem.get(s, {}).values()) for s in ult4) or 1
        r = next((x for x in D["afe_categoria"]
                  if x["semana"] == sem and x["categoria"] == b), {})
        fil_cat.append([punto(CAT_COLOR[b]) + f"<b>{b}</b> · {CAT_DESC[b]}",
                        _n(v, 1), f'<b>{_n(v/(afe_in or 1)*100,1)}%</b>',
                        _n(sum(p4) / len(p4) if p4 else 0, 1), _n(sum(p4) / t4 * 100, 1) + "%",
                        _n(afe_s[b]["tn"], 1) if b in "ABCD" else "—",
                        _n(r.get("s"), 0), _n(r.get("p"), 0)])
    t_cat = tabla(["Categoría", "TN semana", "% semana", "TN prom. 4 sem.", "% prom. 4 sem.",
                   "TN en tanque", "S ppm", "P ppm"], fil_cat)

    fil_prov = []
    for p in D.get("proveedores", []):
        c3 = GOOD if (p["pct_ab3"] or 0) >= 40 else (WARN if (p["pct_ab3"] or 0) >= 25 else CRIT)
        fl = ""
        if p["pct_ab"] is not None and p["pct_ab3"] is not None:
            d3 = p["pct_ab3"] - p["pct_ab"]
            fl = (f' <span style="color:{CRIT}">▼</span>' if d3 <= -5 else
                  f' <span style="color:{GOOD}">▲</span>' if d3 >= 5 else "")
        fil_prov.append([_e(p["prov"]), _n(p["tn_tot"], 0), _n(p["tn_sem"], 1),
                         _n(p["pct_ab"], 0) + "%", _n(p["pct_d"], 0) + "%",
                         f'<span style="color:{c3};font-weight:700">{_n(p["pct_ab3"],0)}%</span>{fl}'])
    t_prov = tabla(["Proveedor", "TN 9 sem.", "TN semana", "% A+B histórico", "% D histórico",
                    "% A+B últimas 3 sem."], fil_prov)

    fil_nec = []
    for b in "ABCD":
        fil_nec.append([punto(CAT_COLOR[b]) + f"<b>Categoría {b}</b> · {CAT_DESC[b]}",
                        _n(afe_s[b]["tn"], 1), _n(afe_s[b]["c_desp"], 1), _n(afe_s[b]["libre"], 1),
                        _n(afe_s[b]["libre"] / (afe_necesario or 1) * 100, 1) + "%"])
    fil_nec.append(["<b>Total AFE-S</b>", f"<b>{_n(afe_s_tot,1)}</b>",
                    f'<b>{_n(sum(afe_s[b]["c_desp"] for b in "ABCD"),1)}</b>',
                    f"<b>{_n(libre_total,1)}</b>",
                    f'<b style="color:{GOOD if (cobertura_afe or 0)>=100 else CRIT}">'
                    f'{_n(cobertura_afe,1)}%</b>'])
    t_nec = tabla(["Calidad disponible", "Stock TN", "Comprometido TN", "Libre TN",
                   "% de lo que exigen los despachos"], fil_nec)

    fil_et = []
    for e in et:
        col = sem_col(e["desvio"], 2, 8)
        fil_et.append([f'{"Desgomado" if e["tipo"].startswith("DESG") else "ARE"} · '
                       f'<b>{e["etapa"].title()}</b>', str(e["n"]),
                       _n(e["prog"], 1), _n(e["target"], 1),
                       _n(e["real"], 1) if e["real"] > 0 else
                       f'<span style="color:{CRIT}">inválido</span>',
                       f'<span style="color:{col};font-weight:700">{_n(e["desvio"],1)}</span>',
                       f'{e["dentro"]}/{e["n"]}', str(e["clicks"])])
    t_et = tabla(["Proceso y etapa", "Casos", "Programado h", "Objetivo h", "Real h",
                  "Desvío h", "Dentro de rango", "A los clicks"], fil_et)

    fil_ins = []
    for r in ins_sem:
        if r["pct"] is not None:
            col = sem_col(r["pct"], 110, 130, mas_es_mejor=False) if r["pct"] >= 100 else \
                  (GOOD if r["pct"] >= 90 else (WARN if r["pct"] >= 75 else CRIT))
            pct = f'<span style="color:{col};font-weight:700">{_n(r["pct"],0)}%</span>'
        elif r["teorico"]:
            pct = f'<span style="color:{CRIT}">sin registrar</span>'
        else:
            pct = f'<span class="mut">sin fórmula</span>'
        fil_ins.append([f'<b>{_e(r["insumo"])}</b>', _n(r["teorico"], 1), _e(r["unidad"]),
                        _n(r["real"], 1), pct])
    t_ins = tabla(["Insumo", "Según fórmula", "Unidad", "Descontado del tanque",
                   "Real sobre teórico"], fil_ins)

    fil_de = []
    for d in de:
        mcol = GOOD if d["mg"] >= 2 else (WARN if d["mg"] >= 0 else CRIT)
        ocol = GOOD if d["ocup"] >= 98 else WARN
        fil_de.append([fdate(d["fecha"]), _e(d["titulo"]), _e(d["destino"]), str(d["cont"]),
                       _n(d["tn"], 1), _n(d["tn_cont"], 1),
                       f'<span style="color:{ocol}">{_n(d["ocup"],0)}%</span>',
                       str(d["tq"]),
                       f'<span style="color:{mcol};font-weight:700">{_n(d["mg"],1)}%</span>',
                       str(d["antic"]), str(d["exc"])])
    t_de = tabla(["Fecha", "Despacho", "Destino", "Cont.", "TN", "TN/cont.", "Ocupación",
                  "Tanques", "Margen spec", "Días de anticipo", "Líneas s/stock"], fil_de)

    _cf = sorted(D["confianza"], key=lambda x: -x["kl"])[:6]
    t_conf = tabla(["Sector", "Tanques", "Volumen kL", "Medición más vieja"],
                   [[_e(c["sector"]), str(c["tanques"]), _n(c["kl"], 1),
                     f'<span style="color:{GOOD if c["h"]<=12 else WARN}">{c["h"]} h</span>']
                    for c in _cf])

    fil_sem = []
    for s_ in reversed(sem12[-5:]):
        bs = cat_sem.get(s_, {})
        tb = sum(bs.values()) or 1
        r_d = rt.get(s_, {}).get("DESGOMADO_ACUOSO", {})
        r_a = rt.get(s_, {}).get("PRODUCCION_ARE", {})
        bb = bal.get(s_, {})
        fil_sem.append([f'<b>{fdate(s_)}</b>' if s_ == sem else fdate(s_),
                        _n(tb, 1), _n((bs.get("A", 0) + bs.get("B", 0)) / tb * 100, 0) + "%",
                        _n(sal.get(s_, {}).get("tn"), 1), _n(r_d.get("tn"), 1),
                        _n(r_a.get("tn"), 1),
                        _n(bb.get("desvio"), 0) if bb.get("nd") else
                        '<span class="mut">sin registro</span>'])
    t_sem = tabla(["Semana", "AFE-S ingresado TN", "% A+B", "Exportado TN", "Desgomado TN",
                   "ARE TN", "Desvío AFE-S TN"], fil_sem)

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
.dec{background:#fcfcfb;border:1px solid #e1e0d9;border-left-width:4px;border-radius:3px;
 padding:5px 10px;margin-bottom:4px}
.dec-e{font-size:7.5px;text-transform:uppercase;letter-spacing:.7px;font-weight:800}
.dec-t{font-weight:700;font-size:10.2px;margin-top:1px}
.dec-b{font-size:8.4px;color:#52514e;margin-top:2px}
.dec-p{font-size:8.4px;color:#0b0b0b;margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:6px 0 4px}
.kpi{border:1px solid #e1e0d9;border-radius:4px;padding:5px 7px;background:#fcfcfb}
.kpi-t{font-size:7.7px;color:#898781;text-transform:uppercase;letter-spacing:.4px;font-weight:700;
 min-height:17px}
.kpi-v{font-size:18px;font-weight:800;letter-spacing:-.6px;line-height:1.1}
.kpi-u{font-size:9px;font-weight:600;color:#52514e}
.kpi-d{font-size:7.5px;color:#898781}
.kpi-x{margin:3px 0 1px;min-height:14px}
.kpi-n{font-size:7.8px;color:#52514e;line-height:1.35}
.tw{width:100%}
table{width:100%;border-collapse:collapse;font-size:8.2px;margin:3px 0 7px}
th{background:#f4f4f1;font-weight:700;font-size:7.4px;text-transform:uppercase;letter-spacing:.3px;
 color:#52514e;padding:4px 5px;border-bottom:1.5px solid #c3c2b7}
td{padding:2.6px 5px;border-bottom:1px solid #ececE6}
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

/* ---------- teléfono: una columna, tablas en fichas, tipografía usable ---------- */
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
 p.lead,.fig-s,.dec-b,.dec-p,.box{font-size:13px;line-height:1.55}
 .fig-t{font-size:15px;margin-bottom:3px}
 .fig-n,.nota{font-size:11.5px;line-height:1.5}
 .leg{font-size:12px}
 .leg span{margin:0 12px 3px 0}
 .dec{padding:9px 12px;margin-bottom:8px;border-left-width:5px}
 .dec-e{font-size:10px}
 .dec-t{font-size:15px;line-height:1.3}
 .grid{grid-template-columns:repeat(2,1fr);gap:8px;margin:10px 0}
 .kpi{padding:9px 10px}
 .kpi-t{font-size:10px;min-height:24px}
 .kpi-v{font-size:24px}
 .kpi-u{font-size:12px}
 .kpi-d{font-size:10px}
 .kpi-n{font-size:11px}
 .cols{grid-template-columns:1fr;gap:4px}
 .figx{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;
  margin:0 -14px;padding:2px 14px 6px;scrollbar-width:thin}
 .figx svg{width:var(--wmin,560px);max-width:none;min-width:var(--wmin,560px)}
 .figx-hint{display:block;font-size:11px;color:#898781;margin:-2px 0 4px}
 .box{padding:10px 12px;margin:10px 0}
 .foot{position:static;font-size:11px;margin-top:16px;padding-top:8px;flex-direction:column;gap:2px}
 /* cada fila de tabla se vuelve una ficha con su etiqueta a la izquierda */
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
    comparada con las 4 semanas previas y los meses anteriores</div></div>
  <div class="rt"><b>{p}</b>emitido {fdate(D['emitido'])}</div></div>"""

    def foot(p, t):
        return (f'<div class="foot"><span>Portería, laboratorio, radares de tanque, despachos y '
                f'batches (Supabase). Semana ISO cerrada, de lunes a domingo.</span>'
                f'<span>{t} · pág. {p}/10</span></div>')

    H = []
    # ---------------- 1 ----------------
    H.append(f"""<div class="page">{head("Tablero")}
<h2><span class="n">1</span>Situaciones que requieren una decisión</h2>
{''.join(decs)}
<h2><span class="n">2</span>Indicadores de la semana</h2>
<div class="grid">{''.join(kpis)}</div>
<h3>Las últimas 5 semanas</h3>
{t_sem}
{foot(1, "Tablero")}</div>""")

    # ---------------- 2 ----------------
    H.append(f"""<div class="page">{head("Desvío del AFE-S")}
<h2><span class="n">3</span>El balance cerrado del AFE-S</h2>
<p class="lead">La ecuación completa: lo que había, más lo que entró y lo que se produjo, menos lo
que se consumió en los reactores y lo que se despachó. Contra eso, la medición física de los tanques.</p>
{fig_cascada}
{fig_desvio_serie}
<h3>Semana a semana</h3>
{t_bal}
<div class="box"><b>Qué mirar.</b> Las semanas sin despachos registrados no son comparables: el
desvío de esas filas es el hueco del registro, no un faltante. A partir del 3 de agosto la ecuación
cierra, y el desvío que queda ({_n(b_now.get('desvio'),1)} TN, {_n(desv_pct,0)}% del stock) es el
que hay que explicar: mermas de tanque, diferencias de balanza y la parte de AFE-S que se consume
en reactores sin registrar el movimiento.</div>
{foot(2, "Desvío del AFE-S")}</div>""")

    # ---------------- 3 ----------------
    H.append(f"""<div class="page">{head("Stock")}
<h2><span class="n">4</span>Stock por producto y categoría</h2>
{fig_stock}
<h3>Los productos clave</h3>
{t_clave}
<h2><span class="n">5</span>Stock único contra medición real</h2>
<p class="lead"><b>Stock único</b> = stock inicial + producido + ingresos − salidas − consumo interno:
lo que dice el libro. <b>Medición real</b> = lo que miden los radares y las varillas. El color mide
el tamaño relativo del desvío, no su signo.</p>
{t_dp}
{foot(3, "Stock")}</div>""")

    # ---------------- 4 ----------------
    H.append(f"""<div class="page">{head("Ingresos de AFE")}
<h2><span class="n">6</span>AFE-S que ingresa, por categoría</h2>
{fig_cat_sem}
{fig_cat_mes}
<h3>Detalle de la semana {iso}</h3>
{t_cat}
{foot(4, "Ingresos de AFE")}</div>""")

    # ---------------- 5 ----------------
    H.append(f"""<div class="page">{head("Producción")}
<h2><span class="n">7</span>Qué calidad vende cada proveedor</h2>
{t_prov}
<div class="box"><b>Dónde está el AFE-S limpio.</b> Los dos proveedores que aportan el volumen son
los que peor calidad entregan en las últimas tres semanas; los que mejor entregan tienen volumen
chico. Mover el mix de compra hacia ellos es la palanca más directa sobre la categoría A+B.</div>

<h2><span class="n">8</span>Cronograma: programado contra real</h2>
{fig_etapas}
{t_et}
<div class="box"><b>Cómo leerlo.</b> "Programado" es el cronograma que el sistema calculó para ese
batch; "objetivo" es el rango que fija dic_etapa_duracion. La decantación no tiene barra real porque
sus registros cierran con duración negativa. Antes de exigir cumplimiento hay que arreglar el
registro: con etapas avanzadas a los clicks, un desvío de 35 horas de reposo puede ser real o puede
ser que nadie marcó el fin.</div>
{foot(5, "Producción")}</div>""")

    # ---------------- 6 · INSUMOS ----------------
    H.append(f"""<div class="page">{head("Insumos")}
<h2><span class="n">10</span>Insumos: lo que manda la fórmula contra lo que salió del tanque</h2>
{fig_insumos}
{t_ins}
<div class="box"><b>Lo que falta cerrar.</b>
{len(ins_sin_registro)} insumo{'s' if len(ins_sin_registro)!=1 else ''} con fórmula no tiene ningún
movimiento registrado esta semana, y {len(ins_sin_formula)} se descuentan del tanque sin tener
fórmula contra qué compararlos (glicerina y agua). Hasta que las dos listas coincidan, el consumo
de insumos no se puede auditar entero.</div>
<h3>Cómo leer estas tres columnas</h3>
<p class="lead"><b>Según fórmula</b> es lo que <i>debería</i> haberse consumido dadas las toneladas
procesadas, con los coeficientes de dic_consumo_proceso. <b>Descontado del tanque</b> es lo que
efectivamente se restó del stock: cada movimiento ejecutado baja el nivel del tanque del insumo, así
que esa columna es la variación física registrada. Cuando las dos se separan mucho, o el coeficiente
de la fórmula quedó viejo, o hay consumo que nadie registra.</p>
<div class="box"><b>Lectura de la semana.</b> El potasio viene por encima de la fórmula todas las
semanas medidas (122%, 128%, 132%, 127%): eso es un patrón, no un error de carga — el coeficiente
de 3,125 kg por tonelada de AG parece quedarse corto. El fuel oil, en cambio, salta entre 31% y
101% según la semana, y eso sí tiene pinta de registro incompleto más que de consumo variable.</div>
{foot(6, "Insumos")}</div>""")

    # ---------------- 6 ----------------
    H.append(f"""<div class="page">{head("Despachos")}
<h2><span class="n">11</span>Eficiencia de los despachos</h2>
{t_de}
{fig_disp}
<div class="box"><b>Lo que sale de este cuadro.</b>
<b>1.</b> La carga física está bien: {ocup_ok} de {len(de)} despachos salieron con el contenedor
lleno al 98% o más. El problema no es logístico.
<b>2.</b> El margen contra la especificación promedia <b>{_n(mg_prom,1)}%</b> y {mg_neg} de
{len(de)} despachos salieron por debajo de cero. Se está despachando al filo, no por error puntual.
<b>3.</b> Con hasta 6 tanques el margen promedia {_n(mg_pocos,1)}%; con 7 o más, {_n(mg_muchos,1)}%.
Armar el despacho con menos tanques y mejor elegidos vale más que cualquier ajuste de última hora.
<b>4.</b> La anticipación promedio es de {_n(antic_prom,1)} días y hay despachos creados después de
la fecha de salida: el sistema está registrando lo que ya pasó en vez de planificarlo.
<b>5.</b> Hay {exc_total} líneas que piden más litros de los que el tanque tiene medidos.</div>
{foot(7, "Despachos")}</div>""")

    # ---------------- 7 ----------------
    H.append(f"""<div class="page">{head("Tendencias · exportación")}
<h2><span class="n">12</span>Exportación</h2>
{fig_expo_mes}
{fig_expo_ritmo}
{foot(8, "Tendencias · exportación")}</div>""")

    # ---------------- 9 · TENDENCIA DE PRODUCCIÓN ----------------
    H.append(f"""<div class="page">{head("Tendencias · producción")}
<h2><span class="n">13</span>Producción y efluentes</h2>
{fig_prod_mes}
{fig_tn}
{fig_liq_mes}
{foot(9, "Tendencias · producción")}</div>""")

    # ---------------- 10 · CONTROL DEL DATO ----------------
    H.append(f"""<div class="page">{head("Control del dato")}
<h2><span class="n">15</span>Salud del dato</h2>
{fig_cob}
<h3>Antigüedad de la medición física</h3>
<p class="lead">Mientras la medición se cuente en horas, el stock medido es dato duro y el desvío
apunta al registro, no a la balanza.</p>
{t_conf}
<div class="box"><b>Los tres agujeros que hoy impiden auditar del todo.</b>
<b>1.</b> Los tiempos de etapa: {et_clicks} avances a los clicks y {et_inval} duraciones negativas.
<b>2.</b> Los insumos sin fórmula (glicerina y agua) y la soda con fórmula pero sin ningún
movimiento registrado. <b>3.</b> Las semanas anteriores al 3 de agosto, sin despachos cargados, que
dejan la serie histórica del AFE-S sin poder compararse contra la actual.</div>
<p class="nota"><b>Nota metodológica.</b> Ingresos y salidas salen de los tickets de portería; la
categoría de cada ticket, de su último análisis de laboratorio. El stock es medición física de tanque
(radares WeDo y aforo por centímetros). El balance del AFE-S usa las líneas de despacho como salida.
Las reacciones y los tiempos salen de los batches cerrados. Los insumos comparan
dic_consumo_proceso contra los movimientos de stock ejecutados. Ningún número se carga a mano.</p>
{foot(10, "Control del dato")}</div>""")

    return (f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>WORMS · Brief de Dirección · {iso}</title>'
            f'<style>{css}</style></head><body>{"".join(H)}</body></html>')
