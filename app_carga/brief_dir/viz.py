# -*- coding: utf-8 -*-
"""Gráficos SVG inline para el brief de dirección.

Sin JS y sin dependencias: el brief tiene que imprimirse igual en pantalla,
en PDF y en la impresora del director.

Paleta validada (scripts/validate_palette.js, modo light, superficie #ffffff):
bandas A/B/C/D pasan banda de luminosidad, piso de croma, separación CVD
(peor par adyacente ΔE 19.8 deutan) y piso de visión normal (ΔE 24.1). El
amarillo queda bajo 3:1 de contraste -> SIEMPRE lleva etiqueta directa visible.
"""
from html import escape

# --- roles de color ---------------------------------------------------------
BANDA_COLOR = {"A": "#008300", "B": "#2a78d6", "C": "#eda100",
               "D": "#d03b3b", "SIN LAB": "#898781"}
BANDA_DESC = {"A": "excelente", "B": "bueno", "C": "justo",
              "D": "fuera de spec", "SIN LAB": "sin análisis"}
ORDEN_BANDA = ["A", "B", "C", "D", "SIN LAB"]

GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURF = "#e1e0d9", "#c3c2b7", "#ffffff"
# rampa azul ordinal (piso light = step 250)
AZUL = ["#86b6ef", "#3987e5", "#256abf", "#0d366b"]
PROY = "#eb6834"   # proyección: nunca del mismo hue que el real


def _n(v, d=1):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{d}f}".replace(",", " ")
    except Exception:
        return "—"


def _e(t):
    return escape(str(t if t is not None else ""))


# --- sparkline --------------------------------------------------------------
def sparkline(vals, w=150, h=30, color="#2a78d6"):
    """Línea fina de tendencia. vals en orden cronológico (viejo -> nuevo)."""
    vv = [v for v in vals if v is not None]
    if len(vv) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(vv), max(vv)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts, last = [], None
    for i, v in enumerate(vals):
        if v is None:
            continue
        x = 1 + i * (w - 2) / max(n - 1, 1)
        y = h - 2 - (v - lo) / rng * (h - 5)
        pts.append(f"{x:.1f},{y:.1f}")
        last = (x, y)
    d = " ".join(pts)
    dot = (f'<circle cx="{last[0]:.1f}" cy="{last[1]:.1f}" r="2.4" fill="{color}" '
           f'stroke="{SURF}" stroke-width="1.4"/>') if last else ""
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>{dot}</svg>')


# --- barras apiladas 100% (bandas de calidad) -------------------------------
def stack100(semanas, w=560, h=150, etiquetas_min_pct=7):
    """semanas: [(label, {banda: tn})] cronológico. Cada segmento se rotula."""
    n = len(semanas)
    if not n:
        return ""
    pad_l, pad_b, pad_t = 4, 26, 6
    bw = min(34.0, (w - pad_l) / n - 6)
    step = (w - pad_l) / n
    ph = h - pad_b - pad_t
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    for i, (lab, d) in enumerate(semanas):
        tot = sum(d.get(b, 0) or 0 for b in ORDEN_BANDA) or 1.0
        x = pad_l + i * step + (step - bw) / 2
        y = pad_t
        for b in ORDEN_BANDA:
            v = d.get(b, 0) or 0
            if v <= 0:
                continue
            seg = v / tot * ph
            # 2px de superficie entre segmentos apilados
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                       f'height="{max(seg-2,1):.1f}" fill="{BANDA_COLOR[b]}" rx="1.5"/>')
            if v / tot * 100 >= etiquetas_min_pct:
                out.append(f'<text x="{x+bw/2:.1f}" y="{y+seg/2+3:.1f}" text-anchor="middle" '
                           f'font-size="8.5" font-weight="700" fill="#fff">{_e(b)}</text>')
            y += seg
        out.append(f'<text x="{x+bw/2:.1f}" y="{h-14}" text-anchor="middle" '
                   f'font-size="7.5" fill="{MUTED}">{_e(lab)}</text>')
        out.append(f'<text x="{x+bw/2:.1f}" y="{h-4}" text-anchor="middle" '
                   f'font-size="7.5" fill="{INK2}">{_n(tot,0)}</text>')
    out.append("</svg>")
    return "".join(out)


# --- barras divergentes (desvío) -------------------------------------------
def diverging(items, w=560, h=118, unidad="TN"):
    """items: [(label, valor)] cronológico. La línea de cero se ubica según el rango
    real de los datos, así una serie casi toda positiva no desperdicia media caja."""
    if not items:
        return ""
    vals = [v for _, v in items if v is not None] or [0]
    vmax, vmin = max(max(vals), 0.0), min(min(vals), 0.0)
    rango = (vmax - vmin) or 1.0
    n = len(items)
    pad_t, pad_b = 12, 22
    ph = h - pad_t - pad_b
    zero = pad_t + (vmax / rango) * ph
    step = w / n
    bw = min(30.0, step - 8)
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    out.append(f'<line x1="0" y1="{zero:.1f}" x2="{w}" y2="{zero:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    for i, (lab, v) in enumerate(items):
        if v is None:
            continue
        x = i * step + (step - bw) / 2
        hh = max(abs(v) / rango * ph, 1.5)
        col = CRIT if v < 0 else "#2a78d6"
        y = zero - hh if v >= 0 else zero
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                   f'fill="{col}" rx="2"/>')
        ty = (y - 3) if v >= 0 else (y + hh + 8.5)
        out.append(f'<text x="{x+bw/2:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="8" '
                   f'font-weight="600" fill="{INK2}">{_n(v,0)}</text>')
        out.append(f'<text x="{x+bw/2:.1f}" y="{h-5}" text-anchor="middle" font-size="7.5" '
                   f'fill="{MUTED}">{_e(lab)}</text>')
    out.append("</svg>")
    return "".join(out)


# --- barra segmentada horizontal (stock comprometido vs libre) --------------
def barra_stock(filas, w=560, alto_fila=26, maxv=None):
    """filas: [(label, color_label, [(tramo_label, valor, color)], total)]"""
    if not filas:
        return ""
    tot_max = maxv or max((f[3] for f in filas), default=1) or 1
    lab_w, val_w = 118, 62
    plot = w - lab_w - val_w
    h = alto_fila * len(filas) + 6
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    for i, (lab, lcol, tramos, total) in enumerate(filas):
        y = i * alto_fila + 4
        out.append(f'<text x="0" y="{y+13}" font-size="9.5" font-weight="600" '
                   f'fill="{lcol or INK}">{_e(lab)}</text>')
        x = lab_w
        for tl, v, c in tramos:
            if not v or v <= 0:
                continue
            ww = v / tot_max * plot
            out.append(f'<rect x="{x:.1f}" y="{y+2}" width="{max(ww-2,1):.1f}" height="14" '
                       f'fill="{c}" rx="2"/>')
            if ww > 34:
                out.append(f'<text x="{x+ww/2-1:.1f}" y="{y+12.5}" text-anchor="middle" '
                           f'font-size="8" font-weight="700" fill="#fff">{_n(v,0)}</text>')
            x += ww
        out.append(f'<text x="{w}" y="{y+13}" text-anchor="end" font-size="9.5" '
                   f'font-weight="700" fill="{INK}">{_n(total,1)}</text>')
    out.append("</svg>")
    return "".join(out)


# --- acumulado mensual + proyección (el gráfico de líquidos) ---------------
def acumulado_proy(meses, w=560, h=178, dias_mes=31, etiqueta=None):
    """meses: [{'mes','dias':[(dia,tn)],'ult'}] cronológico; el último proyecta.

    Devuelve (svg, proyeccion_fin_de_mes). La proyección va punteada y en un
    color propio para que nunca se confunda con el real del mes en curso.
    """
    if not meses:
        return "", 0.0
    pad_l, pad_r, pad_t, pad_b = 38, 96, 8, 20
    pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
    series = []
    for m in meses:
        acum, ser = 0.0, []
        for d, tn in sorted(m["dias"]):
            acum += tn or 0
            ser.append((d, acum))
        series.append((m["mes"], ser, m.get("ult") or (ser[-1][0] if ser else 0)))
    ult_mes, ult_serie, ult_dia = series[-1]
    ritmo = (ult_serie[-1][1] / ult_dia) if ult_serie and ult_dia else 0
    proy_fin = ritmo * dias_mes
    hi = (max([s2[-1][1] for _, s2, _ in series if s2] + [proy_fin]) or 1) * 1.08

    def X(d):
        return pad_l + (d - 1) / max(dias_mes - 1, 1) * pw

    def Y(v):
        return pad_t + ph - v / hi * ph

    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    for k in range(5):
        v = hi * k / 4
        y = Y(v)
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l+pw}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pad_l-5}" y="{y+3:.1f}" text-anchor="end" font-size="7.5" '
                   f'fill="{MUTED}">{_n(v/1000,1)}k</text>')
    for d in (1, 5, 10, 15, 20, 25, dias_mes):
        out.append(f'<text x="{X(d):.1f}" y="{h-7}" text-anchor="middle" font-size="7.5" '
                   f'fill="{MUTED}">{d}</text>')
    ly = pad_t + 4
    for i, (mes, ser, _u) in enumerate(series):
        col = AZUL[min(i, len(AZUL) - 1)]
        pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in ser)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" '
                   f'stroke-linejoin="round"/>')
        out.append(f'<rect x="{pad_l+pw+8}" y="{ly-6}" width="9" height="3" fill="{col}" rx="1.5"/>')
        et = etiqueta(mes) if etiqueta else mes
        out.append(f'<text x="{pad_l+pw+21}" y="{ly-2}" font-size="8" fill="{INK2}">'
                   f'{_e(et)} · {_n(ser[-1][1]/1000,1)}k</text>')
        ly += 12
    if ult_serie and ritmo:
        d0, v0 = ult_serie[-1]
        out.append(f'<line x1="{X(d0):.1f}" y1="{Y(v0):.1f}" x2="{X(dias_mes):.1f}" '
                   f'y2="{Y(proy_fin):.1f}" stroke="{PROY}" stroke-width="2" '
                   f'stroke-dasharray="5 3"/>')
        out.append(f'<circle cx="{X(dias_mes):.1f}" cy="{Y(proy_fin):.1f}" r="3.5" '
                   f'fill="{SURF}" stroke="{PROY}" stroke-width="2"/>')
        out.append(f'<rect x="{pad_l+pw+8}" y="{ly-6}" width="9" height="3" fill="{PROY}" rx="1.5"/>')
        out.append(f'<text x="{pad_l+pw+21}" y="{ly-2}" font-size="8" font-weight="700" '
                   f'fill="{PROY}">proy. {_n(proy_fin/1000,1)}k</text>')
    out.append("</svg>")
    return "".join(out), proy_fin


# --- barras horizontales simples (cobertura) -------------------------------
def barras_h(items, w=560, alto=20, maxv=100, sufijo="%"):
    if not items:
        return ""
    lab_w, val_w = 150, 46
    plot = w - lab_w - val_w
    h = alto * len(items) + 4
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    for i, (lab, v, col) in enumerate(items):
        y = i * alto + 3
        raw = max(v or 0, 0) / maxv
        ww = min(raw, 1) * plot
        out.append(f'<text x="0" y="{y+11}" font-size="9" fill="{INK2}">{_e(lab)}</text>')
        out.append(f'<rect x="{lab_w}" y="{y+2}" width="{plot}" height="11" fill="{GRID}" rx="2"/>')
        out.append(f'<rect x="{lab_w}" y="{y+2}" width="{max(ww,1):.1f}" height="11" '
                   f'fill="{col}" rx="2"/>')
        if raw > 1:  # desborde: marca de "se pasa de la escala"
            out.append(f'<path d="M{lab_w+plot+2},{y+3} l5,4.5 l-5,4.5 z" fill="{col}"/>')
        out.append(f'<text x="{w}" y="{y+11}" text-anchor="end" font-size="9" '
                   f'font-weight="600" fill="{INK}">{_n(v,0)}{sufijo}</text>')
    out.append("</svg>")
    return "".join(out)


# --- barras verticales simples (una serie por semana) ------------------------
def barras_v(items, w=560, h=125, color="#2a78d6", decimales=0, meta=None):
    """items: [(label, valor)] cronológico. Valor rotulado arriba de cada barra."""
    items = [i for i in items if i[1] is not None]
    if not items:
        return ""
    hi = (max(v for _, v in items) or 1) * 1.18
    n = len(items)
    pad_t, pad_b = 12, 22
    ph = h - pad_t - pad_b
    step = w / n
    bw = min(30.0, step - 8)
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    if meta:
        y = pad_t + ph - meta / hi * ph
        out.append(f'<line x1="0" y1="{y:.1f}" x2="{w}" y2="{y:.1f}" stroke="{MUTED}" '
                   f'stroke-width="1" stroke-dasharray="4 3"/>')
    for i, (lab, v) in enumerate(items):
        x = i * step + (step - bw) / 2
        hh = max(v / hi * ph, 1)
        y = pad_t + ph - hh
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                   f'fill="{color}" rx="2.5"/>')
        out.append(f'<text x="{x+bw/2:.1f}" y="{y-3:.1f}" text-anchor="middle" font-size="8" '
                   f'font-weight="700" fill="{INK2}">{_n(v,decimales)}</text>')
        out.append(f'<text x="{x+bw/2:.1f}" y="{h-6}" text-anchor="middle" font-size="7.5" '
                   f'fill="{MUTED}">{_e(lab)}</text>')
    out.append(f'<line x1="0" y1="{pad_t+ph:.1f}" x2="{w}" y2="{pad_t+ph:.1f}" '
               f'stroke="{AXIS}" stroke-width="1"/></svg>')
    return "".join(out)


# --- barras agrupadas (dos o tres series por período) ------------------------
def barras_agrupadas(labels, series, w=560, h=135, decimales=0):
    """series: [(nombre, color, [valores alineados con labels])]"""
    if not labels or not series:
        return ""
    hi = (max([v for _, _, vs in series for v in vs if v is not None] or [1])) * 1.2
    n, k = len(labels), len(series)
    pad_t, pad_b = 12, 22
    ph = h - pad_t - pad_b
    step = w / n
    bw = min(15.0, (step - 10) / k)
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    for i, lab in enumerate(labels):
        x0 = i * step + (step - bw * k - 2 * (k - 1)) / 2
        for j, (_nom, col, vs) in enumerate(series):
            v = vs[i] if i < len(vs) else None
            if v is None:
                continue
            x = x0 + j * (bw + 2)
            hh = max(v / hi * ph, 1)
            y = pad_t + ph - hh
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                       f'fill="{col}" rx="2"/>')
            if v > 0:
                out.append(f'<text x="{x+bw/2:.1f}" y="{y-2.5:.1f}" text-anchor="middle" '
                           f'font-size="7" font-weight="700" fill="{INK2}">{_n(v,decimales)}</text>')
        out.append(f'<text x="{i*step+step/2:.1f}" y="{h-6}" text-anchor="middle" '
                   f'font-size="7.5" fill="{MUTED}">{_e(lab)}</text>')
    out.append(f'<line x1="0" y1="{pad_t+ph:.1f}" x2="{w}" y2="{pad_t+ph:.1f}" '
               f'stroke="{AXIS}" stroke-width="1"/></svg>')
    return "".join(out)


# --- barras apiladas en TN (no normalizadas) --------------------------------
def stack_abs(semanas, w=560, h=165, orden=None, colores=None, min_pct_label=9):
    """semanas: [(label, {clave: valor})] cronológico. Alto = TN reales."""
    orden = orden or ORDEN_BANDA
    colores = colores or BANDA_COLOR
    if not semanas:
        return ""
    tot = [sum(d.get(b, 0) or 0 for b in orden) for _, d in semanas]
    hi = (max(tot) or 1) * 1.14
    n = len(semanas)
    pad_t, pad_b = 12, 26
    ph = h - pad_t - pad_b
    step = w / n
    bw = min(32.0, step - 7)
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    for i, (lab, d) in enumerate(semanas):
        t = tot[i] or 0
        x = i * step + (step - bw) / 2
        y = pad_t + ph - (t / hi * ph)
        out.append(f'<text x="{x+bw/2:.1f}" y="{y-3:.1f}" text-anchor="middle" font-size="8" '
                   f'font-weight="700" fill="{INK2}">{_n(t,0)}</text>')
        for b in orden:
            v = d.get(b, 0) or 0
            if v <= 0:
                continue
            seg = v / hi * ph
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                       f'height="{max(seg-2,1):.1f}" fill="{colores[b]}" rx="1.5"/>')
            if t and v / t * 100 >= min_pct_label and seg > 11:
                out.append(f'<text x="{x+bw/2:.1f}" y="{y+seg/2+3:.1f}" text-anchor="middle" '
                           f'font-size="8" font-weight="700" fill="#fff">'
                           f'{_n(v/t*100,0)}%</text>')
            y += seg
        out.append(f'<text x="{x+bw/2:.1f}" y="{h-6}" text-anchor="middle" font-size="7.5" '
                   f'fill="{MUTED}">{_e(lab)}</text>')
    out.append(f'<line x1="0" y1="{pad_t+ph:.1f}" x2="{w}" y2="{pad_t+ph:.1f}" '
               f'stroke="{AXIS}" stroke-width="1"/></svg>')
    return "".join(out)


# --- microbarra para las tarjetas del tablero -------------------------------
def microbarra(d, orden=None, colores=None, w=150, h=13):
    """Una barra horizontal partida por clave, con la letra dentro si entra."""
    orden = orden or ORDEN_BANDA
    colores = colores or BANDA_COLOR
    tot = sum(d.get(b, 0) or 0 for b in orden)
    if not tot:
        return f'<svg width="{w}" height="{h}"></svg>'
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">']
    x = 0.0
    for b in orden:
        v = d.get(b, 0) or 0
        if v <= 0:
            continue
        ww = v / tot * w
        out.append(f'<rect x="{x:.1f}" y="0" width="{max(ww-1.5,1):.1f}" height="{h}" '
                   f'fill="{colores[b]}" rx="2"/>')
        if ww > 15:
            out.append(f'<text x="{x+ww/2-0.7:.1f}" y="{h-3.5}" text-anchor="middle" '
                       f'font-size="8" font-weight="700" fill="#fff">{_e(b)}</text>')
        x += ww
    out.append("</svg>")
    return "".join(out)
