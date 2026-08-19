# -*- coding: utf-8 -*-
"""Gráficos SVG del brief de dirección.

Sin JS y sin dependencias: el mismo SVG se ve igual en pantalla, en el PDF y en
la impresora. Todos los gráficos comparten el mismo marco —eje Y con escala y
unidad, eje X con etiquetas y título, y una anotación opcional que dice qué hay
que mirar— para que se lean como un sistema y no como ocho gráficos sueltos.

Paleta validada con scripts/validate_palette.js del skill dataviz (modo light,
superficie #ffffff): las categorías A/B/C/D pasan la banda de luminosidad, piso de croma,
separación CVD (peor par adyacente ΔE 19.8 deutan) y piso de visión normal (ΔE 24.1).
El amarillo queda bajo 3:1 de contraste, así que SIEMPRE lleva etiqueta directa.
"""
import math
from html import escape

# --- roles de color ---------------------------------------------------------
CAT_COLOR = {"A": "#008300", "B": "#2a78d6", "C": "#eda100",
               "D": "#d03b3b", "SIN LAB": "#898781"}
CAT_DESC = {"A": "", "B": "", "C": "",
              "D": " · fuera de espec", "SIN LAB": " · sin análisis"}
ORDEN_CAT = ["A", "B", "C", "D", "SIN LAB"]

GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURF = "#e8e7e1", "#c3c2b7", "#ffffff"
AZUL = ["#9ec5f4", "#5598e7", "#256abf", "#0d366b"]   # rampa ordinal (meses)
PROY = "#eb6834"                                       # proyección: hue propio
LIBRE = "#d3dae3"                                      # tramo "libre" en barras

ANCHO = 660          # ancho útil dentro de la caja de 186 mm
ALTO = 235           # alto por defecto: un gráfico se lee, no se adivina


def _n(v, d=1):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{d}f}".replace(",", " ")
    except Exception:
        return "—"


def _e(t):
    return escape(str(t if t is not None else ""))


# --- escala con números redondos -------------------------------------------
def _paso(bruto):
    if bruto <= 0:
        return 1.0
    exp = math.floor(math.log10(bruto))
    base = bruto / (10 ** exp)
    for c in (1, 2, 2.5, 5, 10):
        if base <= c:
            return c * (10 ** exp)
    return 10 ** (exp + 1)


def _ticks(vmax, vmin=0.0, n=4):
    """Devuelve (lo, hi, [valores]) con cortes redondos que contienen los datos."""
    if vmax == vmin:
        vmax = vmin + 1
    paso = _paso((vmax - vmin) / n)
    lo = math.floor(vmin / paso) * paso
    hi = math.ceil(vmax / paso) * paso
    vals, v = [], lo
    while v <= hi + paso * 1e-9:
        vals.append(round(v, 10))
        v += paso
    return lo, hi, vals


def _fmt_eje(v, hi):
    if hi >= 10000:
        return f"{v/1000:,.0f}k".replace(",", " ")
    if hi >= 1000:
        return f"{v/1000:,.1f}k".replace(",", " ")
    if hi >= 10:
        return f"{v:,.0f}".replace(",", " ")
    return f"{v:,.1f}".replace(",", " ")


# --- marco común ------------------------------------------------------------
def _marco(w, h, lo, hi, ticks, x_titulo, y_titulo, ml=52, mr=18, mt=14, mb=46,
           cero=True):
    """Rejilla horizontal, escala del eje Y, títulos de ambos ejes.

    Devuelve (piezas_svg, X0, X1, Y) donde Y(valor) -> coordenada."""
    pw, ph = w - ml - mr, h - mt - mb
    rango = (hi - lo) or 1.0

    def Y(v):
        return mt + ph - (v - lo) / rango * ph

    o = []
    for t in ticks:
        y = Y(t)
        es_cero = abs(t) < 1e-9
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                 f'stroke="{AXIS if (es_cero and cero) else GRID}" stroke-width="1"/>')
        o.append(f'<text x="{ml-7}" y="{y+3.2:.1f}" text-anchor="end" font-size="8.5" '
                 f'fill="{MUTED}">{_fmt_eje(t, hi)}</text>')
    if y_titulo:
        o.append(f'<text x="{ml-40}" y="{mt+ph/2:.1f}" font-size="8.5" font-weight="700" '
                 f'fill="{INK2}" text-anchor="middle" '
                 f'transform="rotate(-90 {ml-40} {mt+ph/2:.1f})">{_e(y_titulo)}</text>')
    if x_titulo:
        o.append(f'<text x="{ml+pw/2:.1f}" y="{h-6}" text-anchor="middle" font-size="8.5" '
                 f'font-weight="700" fill="{INK2}">{_e(x_titulo)}</text>')
    return o, ml, ml + pw, Y


def _xlabels(o, labels, x0, ancho_paso, y, resaltar=None):
    for i, lab in enumerate(labels):
        cx = x0 + i * ancho_paso + ancho_paso / 2
        peso = "700" if (resaltar is not None and i == resaltar) else "400"
        col = INK if (resaltar is not None and i == resaltar) else MUTED
        o.append(f'<text x="{cx:.1f}" y="{y}" text-anchor="middle" font-size="8.2" '
                 f'font-weight="{peso}" fill="{col}">{_e(lab)}</text>')


def _anotacion(o, x, y, texto, color=INK2, ancho=150, hacia="arriba"):
    """Globo de texto con línea guía. Cuenta qué hay que mirar en ese punto."""
    lineas = []
    palabras, cur = str(texto).split(), ""
    for p in palabras:
        if len(cur) + len(p) + 1 > 30:
            lineas.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        lineas.append(cur)
    alto = 11 * len(lineas) + 7
    bx = max(2, min(x - ancho / 2, 640 - ancho))
    by = y - alto - 12 if hacia == "arriba" else y + 12
    o.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" '
             f'y2="{(by+alto) if hacia=="arriba" else by:.1f}" stroke="{color}" '
             f'stroke-width="1" stroke-dasharray="2 2"/>')
    o.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{ancho}" height="{alto}" rx="3" '
             f'fill="{SURF}" stroke="{color}" stroke-width="1"/>')
    for k, ln in enumerate(lineas):
        o.append(f'<text x="{bx+ancho/2:.1f}" y="{by+12+11*k:.1f}" text-anchor="middle" '
                 f'font-size="8.2" font-weight="600" fill="{color}">{_e(ln)}</text>')


def figura(titulo, svg, subtitulo="", nota="", leyenda="", ancho_min=560):
    """Envuelve un gráfico con su título, su bajada y su leyenda.

    En pantalla angosta el SVG no se encoge hasta volverse ilegible: se mantiene a
    tamaño de lectura dentro de un contenedor que se desliza en horizontal.
    """
    s = f'<div class="fig"><div class="fig-t">{_e(titulo)}</div>'
    if subtitulo:
        s += f'<div class="fig-s">{subtitulo}</div>'
    s += f'<div class="figx" style="--wmin:{ancho_min}px">{svg}</div>'
    s += '<div class="figx-hint">Deslizá el gráfico para verlo completo →</div>'
    if leyenda:
        s += leyenda
    if nota:
        s += f'<div class="fig-n">{nota}</div>'
    return s + "</div>"


def leyenda(items):
    """items: [(color, etiqueta)] · siempre presente cuando hay 2+ series."""
    return ('<div class="leg">' + "".join(
        f'<span><i class="dot" style="background:{c}"></i>{_e(t)}</span>' for c, t in items)
        + '</div>')


# ===========================================================================
# 1 · barras apiladas verticales (TN por período, abierto por calidad)
# ===========================================================================
def barras_apiladas(labels, datos, orden=None, colores=None, w=ANCHO, h=ALTO,
                    x_titulo="", y_titulo="TN", resaltar=None, anotaciones=None,
                    etiqueta_pct=True, min_pct=8):
    orden = orden or ORDEN_CAT
    colores = colores or CAT_COLOR
    if not labels:
        return ""
    tot = [sum(d.get(k, 0) or 0 for k in orden) for d in datos]
    lo, hi, ticks = _ticks(max(tot) * 1.16 if tot else 1)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo)
    paso = (x1 - x0) / len(labels)
    bw = min(38.0, paso - 9)
    for i, d in enumerate(datos):
        t = tot[i] or 0
        x = x0 + i * paso + (paso - bw) / 2
        y = Y(t)
        if resaltar is not None and i == resaltar:
            o.append(f'<rect x="{x-3:.1f}" y="{y-16:.1f}" width="{bw+6:.1f}" '
                     f'height="{Y(0)-y+18:.1f}" fill="#f2f5fa" rx="3"/>')
        o.append(f'<text x="{x+bw/2:.1f}" y="{y-4:.1f}" text-anchor="middle" font-size="9" '
                 f'font-weight="800" fill="{INK}">{_n(t,0)}</text>')
        for k in orden:
            v = d.get(k, 0) or 0
            if v <= 0:
                continue
            seg = (Y(0) - Y(v))
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{max(seg-2,1):.1f}" fill="{colores[k]}" rx="2"/>')
            if etiqueta_pct and t and v / t * 100 >= min_pct and seg > 13:
                o.append(f'<text x="{x+bw/2:.1f}" y="{y+seg/2+3.2:.1f}" text-anchor="middle" '
                         f'font-size="8.6" font-weight="700" fill="#fff">'
                         f'{_n(v/t*100,0)}%</text>')
            y += seg
    _xlabels(o, labels, x0, paso, h - 26, resaltar)
    for idx, txt, col in (anotaciones or []):
        _anotacion(o, x0 + idx * paso + paso / 2, Y(tot[idx] if idx < len(tot) else 0) - 18,
                   txt, col)
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 2 · barras simples verticales con línea de referencia
# ===========================================================================
def barras_simples(labels, valores, w=ANCHO, h=ALTO, color="#2a78d6", x_titulo="",
                   y_titulo="TN", ref=None, ref_txt="", dec=0, resaltar=None,
                   anotaciones=None):
    if not labels:
        return ""
    vv = [v for v in valores if v is not None] or [0]
    lo, hi, ticks = _ticks(max(vv + ([ref] if ref else [])) * 1.16)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo)
    paso = (x1 - x0) / len(labels)
    bw = min(38.0, paso - 9)
    for i, v in enumerate(valores):
        if v is None:
            continue
        x = x0 + i * paso + (paso - bw) / 2
        y = Y(v)
        col = color if (resaltar is None or i != resaltar) else "#0d366b"
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                 f'height="{max(Y(0)-y,1):.1f}" fill="{col}" rx="3"/>')
        o.append(f'<text x="{x+bw/2:.1f}" y="{y-4:.1f}" text-anchor="middle" font-size="9" '
                 f'font-weight="800" fill="{INK}">{_n(v,dec)}</text>')
    if ref:
        y = Y(ref)
        o.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{INK2}" '
                 f'stroke-width="1.5" stroke-dasharray="6 3"/>')
        o.append(f'<rect x="{x0+2}" y="{y-16:.1f}" width="146" height="13.5" rx="2" '
                 f'fill="{SURF}" stroke="{INK2}" stroke-width="0.8"/>')
        o.append(f'<text x="{x0+75}" y="{y-6:.1f}" text-anchor="middle" font-size="8.2" '
                 f'font-weight="700" fill="{INK2}">{_e(ref_txt)}</text>')
    _xlabels(o, labels, x0, paso, h - 26, resaltar)
    for idx, txt, col in (anotaciones or []):
        _anotacion(o, x0 + idx * paso + paso / 2, Y(valores[idx] or 0) - 18, txt, col)
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 3 · barras agrupadas (dos procesos lado a lado)
# ===========================================================================
def barras_agrupadas(labels, series, w=ANCHO, h=ALTO, x_titulo="", y_titulo="TN",
                     dec=0, resaltar=None):
    if not labels or not series:
        return ""
    vv = [v for _, _, s in series for v in s if v is not None] or [0]
    lo, hi, ticks = _ticks(max(vv) * 1.18)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo)
    paso = (x1 - x0) / len(labels)
    k = len(series)
    bw = min(22.0, (paso - 14) / k)
    for i in range(len(labels)):
        gx = x0 + i * paso + (paso - (bw * k + 3 * (k - 1))) / 2
        if resaltar is not None and i == resaltar:
            o.append(f'<rect x="{gx-5:.1f}" y="{Y(hi)+2:.1f}" width="{bw*k+3*(k-1)+10:.1f}" '
                     f'height="{Y(lo)-Y(hi)-2:.1f}" fill="#f2f5fa" rx="3"/>')
        for j, (_nom, col, vs) in enumerate(series):
            v = vs[i] if i < len(vs) else None
            if v is None:
                continue
            x = gx + j * (bw + 3)
            y = Y(v)
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{max(Y(0)-y,1):.1f}" fill="{col}" rx="2.5"/>')
            if v > 0:
                o.append(f'<text x="{x+bw/2:.1f}" y="{y-3.5:.1f}" text-anchor="middle" '
                         f'font-size="8.4" font-weight="700" fill="{INK2}">{_n(v,dec)}</text>')
    _xlabels(o, labels, x0, paso, h - 26, resaltar)
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 4 · barras divergentes (desvíos, positivo y negativo)
# ===========================================================================
def barras_divergentes(labels, valores, w=ANCHO, h=ALTO, x_titulo="", y_titulo="TN",
                       pos_color="#2a78d6", neg_color=CRIT, resaltar=None):
    if not labels:
        return ""
    vv = [v for v in valores if v is not None] or [0]
    lo, hi, ticks = _ticks(max(max(vv), 0) * 1.2, min(min(vv), 0) * 1.2)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo)
    paso = (x1 - x0) / len(labels)
    bw = min(38.0, paso - 9)
    for i, v in enumerate(valores):
        if v is None:
            continue
        x = x0 + i * paso + (paso - bw) / 2
        y = min(Y(v), Y(0))
        alto = abs(Y(v) - Y(0))
        col = pos_color if v >= 0 else neg_color
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(alto,1.5):.1f}" '
                 f'fill="{col}" rx="2.5"/>')
        ty = (Y(v) - 4) if v >= 0 else (Y(v) + 10)
        o.append(f'<text x="{x+bw/2:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="8.6" '
                 f'font-weight="700" fill="{INK2}">{_n(v,0)}</text>')
    _xlabels(o, labels, x0, paso, h - 26, resaltar)
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 5 · barras horizontales apiladas (stock: comprometido vs libre)
# ===========================================================================
def barras_stock(filas, w=ANCHO, x_titulo="TN", alto_fila=30):
    """filas: [(etiqueta, color, comprometido, libre, total, detalle)]"""
    if not filas:
        return ""
    ml, mr, mt, mb = 128, 74, 8, 34
    pw = w - ml - mr
    h = mt + alto_fila * len(filas) + mb
    hi = max(f[4] for f in filas) or 1
    lo, hi, ticks = _ticks(hi * 1.1)
    o = []
    for t in ticks:
        x = ml + (t - lo) / ((hi - lo) or 1) * pw
        o.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt+alto_fila*len(filas)}" '
                 f'stroke="{GRID}" stroke-width="1"/>')
        o.append(f'<text x="{x:.1f}" y="{mt+alto_fila*len(filas)+13}" text-anchor="middle" '
                 f'font-size="8.5" fill="{MUTED}">{_fmt_eje(t, hi)}</text>')
    o.append(f'<text x="{ml+pw/2:.1f}" y="{h-4}" text-anchor="middle" font-size="8.5" '
             f'font-weight="700" fill="{INK2}">{_e(x_titulo)}</text>')
    for i, (lab, col, comp, libre, total, det) in enumerate(filas):
        y = mt + i * alto_fila + 4
        o.append(f'<text x="0" y="{y+11}" font-size="9.6" font-weight="700" fill="{col}">'
                 f'{_e(lab)}</text>')
        if det:
            o.append(f'<text x="0" y="{y+20}" font-size="7.8" fill="{MUTED}">{_e(det)}</text>')
        x = ml
        for v, c, et in ((comp, col, "comprometido"), (libre, LIBRE, "libre")):
            if not v or v <= 0:
                continue
            ww = v / ((hi - lo) or 1) * pw
            o.append(f'<rect x="{x:.1f}" y="{y+1}" width="{max(ww-2,1):.1f}" height="16" '
                     f'fill="{c}" rx="2.5"/>')
            if ww > 26:
                o.append(f'<text x="{x+ww/2-1:.1f}" y="{y+12.5}" text-anchor="middle" '
                         f'font-size="8.4" font-weight="700" '
                         f'fill="{"#fff" if c != LIBRE else INK2}">{_n(v,0)}</text>')
            x += ww
        o.append(f'<text x="{w}" y="{y+13}" text-anchor="end" font-size="10.5" '
                 f'font-weight="800" fill="{INK}">{_n(total,1)}</text>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 7 · barras horizontales de porcentaje (cobertura del libro)
# ===========================================================================
def barras_pct(items, w=ANCHO, alto=22, maxv=100, x_titulo="% del movimiento físico explicado"):
    if not items:
        return ""
    ml, mr, mt, mb = 168, 56, 4, 30
    pw = w - ml - mr
    h = mt + alto * len(items) + mb
    o = []
    for t in (0, 25, 50, 75, 100):
        x = ml + t / maxv * pw
        o.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt+alto*len(items)}" '
                 f'stroke="{GRID}" stroke-width="1"/>')
        o.append(f'<text x="{x:.1f}" y="{mt+alto*len(items)+12}" text-anchor="middle" '
                 f'font-size="8.2" fill="{MUTED}">{t}%</text>')
    o.append(f'<text x="{ml+pw/2:.1f}" y="{h-3}" text-anchor="middle" font-size="8.5" '
             f'font-weight="700" fill="{INK2}">{_e(x_titulo)}</text>')
    for i, (lab, v, col) in enumerate(items):
        y = mt + i * alto + 3
        raw = max(v or 0, 0) / maxv
        ww = min(raw, 1) * pw
        o.append(f'<text x="0" y="{y+11}" font-size="9" fill="{INK2}">{_e(lab)}</text>')
        o.append(f'<rect x="{ml}" y="{y+2}" width="{pw}" height="12" fill="#f1f0eb" rx="2.5"/>')
        o.append(f'<rect x="{ml}" y="{y+2}" width="{max(ww,1.5):.1f}" height="12" '
                 f'fill="{col}" rx="2.5"/>')
        if raw > 1:
            o.append(f'<path d="M{ml+pw+3},{y+3} l6,5 l-6,5 z" fill="{col}"/>')
        o.append(f'<text x="{w}" y="{y+11}" text-anchor="end" font-size="9.2" '
                 f'font-weight="700" fill="{INK}">{_n(v,0)}%</text>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 8 · piezas chicas para las tarjetas del tablero
# ===========================================================================
def sparkline(vals, w=152, h=26, color="#2a78d6"):
    vv = [v for v in vals if v is not None]
    if len(vv) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(vv), max(vv)
    rng = (hi - lo) or 1.0
    pts, last = [], None
    for i, v in enumerate(vals):
        if v is None:
            continue
        x = 1 + i * (w - 2) / max(len(vals) - 1, 1)
        y = h - 2 - (v - lo) / rng * (h - 5)
        pts.append(f"{x:.1f},{y:.1f}")
        last = (x, y)
    dot = (f'<circle cx="{last[0]:.1f}" cy="{last[1]:.1f}" r="2.6" fill="{color}" '
           f'stroke="{SURF}" stroke-width="1.4"/>') if last else ""
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>{dot}</svg>')


def microbarra(d, orden=None, colores=None, w=152, h=14):
    orden = orden or ORDEN_CAT
    colores = colores or CAT_COLOR
    tot = sum(d.get(b, 0) or 0 for b in orden)
    if not tot:
        return (f'<svg width="{w}" height="{h}"><rect width="{w}" height="{h}" rx="2.5" '
                f'fill="#f1f0eb"/><text x="{w/2}" y="{h-3.5}" text-anchor="middle" '
                f'font-size="8" fill="{MUTED}">sin datos</text></svg>')
    o, x = [], 0.0
    for b in orden:
        v = d.get(b, 0) or 0
        if v <= 0:
            continue
        ww = v / tot * w
        o.append(f'<rect x="{x:.1f}" y="0" width="{max(ww-1.5,1):.1f}" height="{h}" '
                 f'fill="{colores[b]}" rx="2.5"/>')
        if ww > 17:
            o.append(f'<text x="{x+ww/2-0.7:.1f}" y="{h-3.6}" text-anchor="middle" '
                     f'font-size="8.2" font-weight="700" fill="#fff">{_e(b)}</text>')
        x += ww
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 9 · cascada: de dónde sale el desvío (balance cerrado)
# ===========================================================================
def cascada(pasos, w=ANCHO, h=270, y_titulo="TN", x_titulo=""):
    """pasos: [(etiqueta, valor, tipo)] con tipo 'base'|'suma'|'resta'|'total'|'medido'.

    Cada barra arranca donde terminó la anterior, así se ve qué suma y qué resta
    entre el stock inicial y el final. Los 'total' y 'medido' se apoyan en cero.
    """
    if not pasos:
        return ""
    acum, geom, techo, piso = 0.0, [], 0.0, 0.0
    for lab, val, tipo in pasos:
        if tipo in ("base", "total", "medido"):
            ini, fin = 0.0, float(val)
            acum = float(val)
        else:
            ini = acum
            acum += float(val)
            fin = acum
        geom.append((lab, ini, fin, float(val), tipo))
        techo, piso = max(techo, ini, fin), min(piso, ini, fin)
    lo, hi, ticks = _ticks(techo * 1.22, piso)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo, mb=56)
    paso = (x1 - x0) / len(geom)
    bw = min(56.0, paso - 12)
    col = {"base": "#5598e7", "suma": "#1baf7a", "resta": CRIT,
           "total": "#0d366b", "medido": "#256abf"}
    prev_fin = None
    for i, (lab, ini, fin, val, tipo) in enumerate(geom):
        x = x0 + i * paso + (paso - bw) / 2
        yt, yb = Y(max(ini, fin)), Y(min(ini, fin))
        o.append(f'<rect x="{x:.1f}" y="{yt:.1f}" width="{bw:.1f}" '
                 f'height="{max(yb-yt,2):.1f}" fill="{col[tipo]}" rx="2.5"/>')
        signo = "+" if tipo == "suma" else ("−" if tipo == "resta" else "")
        o.append(f'<text x="{x+bw/2:.1f}" y="{yt-5:.1f}" text-anchor="middle" font-size="9.4" '
                 f'font-weight="800" fill="{INK}">{signo}{_n(abs(val),0)}</text>')
        if prev_fin is not None and tipo in ("suma", "resta"):
            o.append(f'<line x1="{x-(paso-bw)+1:.1f}" y1="{Y(ini):.1f}" x2="{x:.1f}" '
                     f'y2="{Y(ini):.1f}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="2 2"/>')
        prev_fin = fin
        # etiqueta del eje X en dos renglones
        palabras, ren, cur = lab.split(), [], ""
        for p in palabras:
            if len(cur) + len(p) + 1 > 13:
                ren.append(cur); cur = p
            else:
                cur = (cur + " " + p).strip()
        if cur:
            ren.append(cur)
        for k, t in enumerate(ren[:2]):
            o.append(f'<text x="{x+bw/2:.1f}" y="{h-34+11*k}" text-anchor="middle" '
                     f'font-size="8.2" font-weight="{"700" if tipo in ("total","medido") else "400"}" '
                     f'fill="{INK if tipo in ("total","medido") else MUTED}">{_e(t)}</text>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 10 · cierre mensual con la barra del mes en curso proyectada
# ===========================================================================
def barras_mes_proy(labels, reales, proyeccion=None, w=ANCHO, h=ALTO,
                    y_titulo="TN", x_titulo="mes", color="#256abf"):
    if not labels:
        return ""
    vv = [v for v in reales if v is not None] + ([proyeccion] if proyeccion else [])
    lo, hi, ticks = _ticks(max(vv or [1]) * 1.2)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo)
    paso = (x1 - x0) / len(labels)
    bw = min(66.0, paso - 26)
    for i, (lab, v) in enumerate(zip(labels, reales)):
        if v is None:
            continue
        x = x0 + i * paso + (paso - bw) / 2
        ultimo = (i == len(labels) - 1)
        o.append(f'<rect x="{x:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" height="{Y(0)-Y(v):.1f}" '
                 f'fill="{color}" rx="3"/>')
        if ultimo and proyeccion and proyeccion > v:
            o.append(f'<rect x="{x:.1f}" y="{Y(proyeccion):.1f}" width="{bw:.1f}" '
                     f'height="{Y(v)-Y(proyeccion):.1f}" fill="{PROY}" fill-opacity="0.20" '
                     f'stroke="{PROY}" stroke-width="1.6" stroke-dasharray="5 3" rx="3"/>')
            o.append(f'<text x="{x+bw/2:.1f}" y="{Y(proyeccion)-6:.1f}" text-anchor="middle" '
                     f'font-size="10" font-weight="800" fill="{PROY}">{_n(proyeccion,0)}</text>')
            if Y(v) - Y(proyeccion) > 16:
                o.append(f'<text x="{x+bw/2:.1f}" y="{Y(proyeccion)+(Y(v)-Y(proyeccion))/2+3:.1f}" '
                         f'text-anchor="middle" font-size="8.2" font-weight="700" fill="{PROY}">'
                         f'faltan {_n(proyeccion-v,0)}</text>')
            o.append(f'<text x="{x+bw/2:.1f}" y="{Y(v)+14:.1f}" text-anchor="middle" font-size="9" '
                     f'font-weight="800" fill="#fff">{_n(v,0)}</text>')
        else:
            o.append(f'<text x="{x+bw/2:.1f}" y="{Y(v)-5:.1f}" text-anchor="middle" font-size="10" '
                     f'font-weight="800" fill="{INK}">{_n(v,0)}</text>')
        o.append(f'<text x="{x+bw/2:.1f}" y="{h-26}" text-anchor="middle" font-size="8.6" '
                 f'font-weight="{"700" if ultimo else "400"}" '
                 f'fill="{INK if ultimo else MUTED}">{_e(lab)}{" (en curso)" if ultimo else ""}</text>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 11 · pares teórico vs real (insumos, TN de fórmula vs producidas)
# ===========================================================================
def barras_pares(labels, izq, der, nom_izq="teórico", nom_der="real", w=ANCHO, h=ALTO,
                 y_titulo="", x_titulo="", col_izq="#9ec5f4", col_der="#256abf", dec=0):
    if not labels:
        return ""
    vv = [v for v in list(izq) + list(der) if v is not None] or [1]
    lo, hi, ticks = _ticks(max(vv) * 1.2)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo)
    paso = (x1 - x0) / len(labels)
    bw = min(26.0, (paso - 16) / 2)
    for i, lab in enumerate(labels):
        gx = x0 + i * paso + (paso - bw * 2 - 3) / 2
        for j, (v, c) in enumerate(((izq[i], col_izq), (der[i], col_der))):
            if v is None:
                continue
            x = gx + j * (bw + 3)
            o.append(f'<rect x="{x:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" '
                     f'height="{max(Y(0)-Y(v),1):.1f}" fill="{c}" rx="2.5"/>')
            o.append(f'<text x="{x+bw/2:.1f}" y="{Y(v)-4:.1f}" text-anchor="middle" '
                     f'font-size="8.4" font-weight="700" fill="{INK2}">{_n(v,dec)}</text>')
        if izq[i] and der[i]:
            pct = der[i] / izq[i] * 100
            c = GOOD if 90 <= pct <= 110 else (WARN if 75 <= pct <= 130 else CRIT)
            o.append(f'<text x="{gx+bw+1.5:.1f}" y="{h-38}" text-anchor="middle" font-size="8.6" '
                     f'font-weight="800" fill="{c}">{_n(pct,0)}%</text>')
        o.append(f'<text x="{x0+i*paso+paso/2:.1f}" y="{h-26}" text-anchor="middle" '
                 f'font-size="8.4" fill="{MUTED}">{_e(lab)}</text>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 12 · dispersión chica (tanques usados vs margen de spec)
# ===========================================================================
def dispersion(puntos, w=ANCHO, h=225, x_titulo="", y_titulo="", x_max=None, cero=True):
    """puntos: [(x, y, etiqueta, color)]"""
    if not puntos:
        return ""
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    xhi = x_max or (max(xs) + 1)
    lo, hi, ticks = _ticks(max(ys) * 1.25, min(min(ys) * 1.25, 0))
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, x_titulo, y_titulo, mb=42)
    pw = x1 - x0

    def X(v):
        return x0 + (v - 0) / (xhi or 1) * pw
    for t in range(0, int(xhi) + 1, max(1, int(xhi // 8))):
        o.append(f'<text x="{X(t):.1f}" y="{h-26}" text-anchor="middle" font-size="8.2" '
                 f'fill="{MUTED}">{t}</text>')
    for px, py, lab, c in puntos:
        o.append(f'<circle cx="{X(px):.1f}" cy="{Y(py):.1f}" r="5" fill="{c}" '
                 f'fill-opacity="0.85" stroke="{SURF}" stroke-width="1.4"/>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">' + "".join(o) + "</svg>"


# ===========================================================================
# 13 · acumulado diario por mes con proyección (el gráfico de tendencia)
# ===========================================================================
def acumulado_proy(meses, w=ANCHO, h=250, dias_mes=31, etiqueta=None,
                   y_titulo="TN acumuladas"):
    """meses: [{'mes','dias':[(dia,tn)],'ult'}] cronológico; el último se proyecta.

    Una línea por mes sobre el eje "día del mes"; la punteada naranja extiende el
    ritmo diario del mes en curso hasta fin de mes. Devuelve (svg, proyección).
    """
    if not meses:
        return "", 0.0
    series = []
    for m in meses:
        acum, ser = 0.0, []
        for d, tn in sorted(m["dias"]):
            acum += tn or 0
            ser.append((d, acum))
        series.append((etiqueta(m["mes"]) if etiqueta else m["mes"], ser,
                       m.get("ult") or (ser[-1][0] if ser else 0)))
    _mes_ult, ult_serie, ult_dia = series[-1]
    ritmo = (ult_serie[-1][1] / ult_dia) if ult_serie and ult_dia else 0
    proy = ritmo * dias_mes
    lo, hi, ticks = _ticks(max([s[-1][1] for _, s, _ in series if s] + [proy]) * 1.1)
    o, x0, x1, Y = _marco(w, h, lo, hi, ticks, "día del mes", y_titulo, ml=52, mr=110, mb=46)
    pw = x1 - x0

    def X(d):
        return x0 + (d - 1) / max(dias_mes - 1, 1) * pw

    for d in (1, 5, 10, 15, 20, 25, dias_mes):
        o.append(f'<text x="{X(d):.1f}" y="{h-26}" text-anchor="middle" font-size="8.2" '
                 f'fill="{MUTED}">{d}</text>')
    ly = 24
    for i, (mes, ser, _u) in enumerate(series):
        col = AZUL[min(i, len(AZUL) - 1)]
        grosor = 2.8 if i == len(series) - 1 else 2.0
        pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in ser)
        o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" '
                 f'stroke-width="{grosor}" stroke-linejoin="round" stroke-linecap="round"/>')
        o.append(f'<rect x="{x1+10}" y="{ly-7}" width="12" height="4" fill="{col}" rx="2"/>')
        o.append(f'<text x="{x1+27}" y="{ly-2}" font-size="8.6" fill="{INK2}">{_e(mes)}</text>')
        o.append(f'<text x="{w-2}" y="{ly-2}" text-anchor="end" font-size="8.6" '
                 f'font-weight="700" fill="{INK2}">{_fmt_eje(ser[-1][1], hi)}</text>')
        ly += 15
    if ult_serie and ritmo:
        d0, v0 = ult_serie[-1]
        o.append(f'<circle cx="{X(d0):.1f}" cy="{Y(v0):.1f}" r="3.4" fill="{AZUL[-1]}" '
                 f'stroke="{SURF}" stroke-width="1.6"/>')
        o.append(f'<line x1="{X(d0):.1f}" y1="{Y(v0):.1f}" x2="{X(dias_mes):.1f}" '
                 f'y2="{Y(proy):.1f}" stroke="{PROY}" stroke-width="2.6" stroke-dasharray="7 4"/>')
        o.append(f'<circle cx="{X(dias_mes):.1f}" cy="{Y(proy):.1f}" r="4.2" fill="{SURF}" '
                 f'stroke="{PROY}" stroke-width="2.6"/>')
        o.append(f'<rect x="{x1+10}" y="{ly-7}" width="12" height="4" fill="{PROY}" rx="2"/>')
        o.append(f'<text x="{x1+27}" y="{ly-2}" font-size="8.6" font-weight="800" '
                 f'fill="{PROY}">proyección</text>')
        o.append(f'<text x="{w-2}" y="{ly-2}" text-anchor="end" font-size="8.6" '
                 f'font-weight="800" fill="{PROY}">{_fmt_eje(proy, hi)}</text>')
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            + "".join(o) + "</svg>"), proy
