# -*- coding: utf-8 -*-
"""Visualización de tanques — el estado de la planta de un vistazo.

Cada tanque es un recipiente a escala: nivel = stock medido / capacidad, la franja
rayada arriba del líquido es lo COMPROMETIDO en despachos confirmados, el color es
el producto. Chip de calidad: para AFE/AG es la banda A/B/C/D contra la spec de
venta; para el resto (ARE-B, AG-C…) es la calidad propia del producto. Cada
tarjeta dice el medidor (WeDo/Manual), cuándo se midió por última vez y cuál fue
el último movimiento tipificado (despacho, asignación AFE, carga…).

El HTML se genera SIN saltos de línea: st.markdown trata las líneas con sangría
como bloque de código y aparecían '</div>' sueltos en pantalla.
"""
import html as _html

import pandas as pd
import streamlit as st

_SPEC_S, _SPEC_P = 50.0, 150.0     # spec de venta (misma que Balance) para la banda AFE/AG
_BANDA_COL = {"A": "#166534", "B": "#1d4ed8", "C": "#b45309", "D": "#b91c1c", "—": "#94a3b8"}
_PROD_COL = [("AFE-SG", "#64748b"), ("AFE-S", "#0284c7"), ("AFE-G", "#7c3aed"),
             ("AFE", "#0ea5e9"), ("AG-E", "#d97706"), ("AG", "#f59e0b"),
             ("ARE", "#16a34a"), ("SEBO", "#a16207"), ("GLICERINA", "#db2777"),
             ("MP", "#6b7280")]
_ORIGEN_LBL = {"despacho": "🚢 Despacho", "asignacion_afe": "🎯 Asig. AFE",
               "recuperacion_ag": "♻️ Recuperación", "carga_operario": "🏭 Carga",
               "decantacion": "🧴 Decantación", "planificacion": "🗓️ Planif.",
               "lab_sync": "🚛 Ingreso", "porteria_sync": "🚛 Ingreso",
               "ajuste_manual": "✍️ Ajuste", "sistema": "⚙️ Sistema",
               "sync_wedo": "📡 WeDo", "despacho_salida": "🚢 Despacho"}


def _color_prod(p):
    up = str(p or "").strip().upper()
    for pref, col in _PROD_COL:
        if up.startswith(pref):
            return col
    return "#475569"


def _chip_calidad(prod, s, p):
    """(letra, color, tooltip).

    - AFE-S y AG-E (lo que se despacha contra la spec de venta): banda A/B/C/D
      calculada con el laboratorio (S≤50 / P≤150).
    - Cualquier producto cuya letra de calidad viene EN el código (AG-C, ARE-A,
      ARE-B…): esa letra es su calidad — un AG-C es C, sin importar el lab.
    - Sin letra de calidad en el código (SEBO, MP…): sin chip."""
    up = str(prod or "").strip().upper()
    if up in ("AFE-S", "AG-E"):
        if pd.isna(s) and pd.isna(p):
            return ("—", _BANDA_COL["—"], "Sin análisis de laboratorio")
        ic = max((float(s) / _SPEC_S) if pd.notna(s) else 0.0,
                 (float(p) / _SPEC_P) if pd.notna(p) else 0.0)
        b = "A" if ic <= 0.80 else ("B" if ic <= 0.90 else ("C" if ic <= 1.00 else "D"))
        d = {"A": "excelente", "B": "bueno", "C": "justo", "D": "fuera de spec"}[b]
        return (b, _BANDA_COL[b], "Banda %s · %s (contra spec de venta S≤50 / P≤150)" % (b, d))
    if "-" in up:
        cal = up.rsplit("-", 1)[1]
        if cal in ("A", "B", "C", "D", "E"):
            col = _BANDA_COL.get(cal, "#334155")
            return (cal, col, "Calidad %s del producto %s (viene en el código)" % (cal, up))
    return None


def _fnum(v, dec=0, vacio="—"):
    try:
        if v is None or pd.isna(v):
            return vacio
        return ("{:,.%df}" % dec).format(float(v))
    except Exception:
        return vacio


def _fts(ts):
    try:
        t = pd.to_datetime(ts, utc=True)
        if pd.isna(t):
            return None
        return t.tz_convert("America/Argentina/Buenos_Aires").strftime("%d/%m %H:%M")
    except Exception:
        return None


def _card(r, mov, ult):
    nombre = _html.escape(str(r["nombre"]))
    prod = str(r["producto_principal"] or "—")
    prod_lbl = str(r.get("producto_rotulo") or prod)   # rótulo oficial: trae la calidad
    col = _color_prod(prod)
    cap = float(r["capacidad_litros"]) if pd.notna(r["capacidad_litros"]) else 0.0
    lts = float(r["litros_actual"]) if pd.notna(r["litros_actual"]) else None
    comp = float(r.get("litros_comprometido") or 0.0)
    pct = min(100.0, max(0.0, 100.0 * (lts or 0.0) / cap)) if cap > 0 else 0.0
    comp_draw = min(comp, (lts or 0.0))
    pct_comp = min(pct, 100.0 * comp_draw / cap) if cap > 0 else 0.0
    pct_disp = max(0.0, pct - pct_comp)
    chip = _chip_calidad(prod, r.get("azufre"), r.get("fosforo"))
    chip_html = ""
    if chip:
        _b, _c, _tt = chip
        chip_html = ("<span class='tvq-bnd' style='background:%s22;color:%s;border:1px solid %s55'"
                     " title='%s'>%s</span>" % (_c, _c, _c, _html.escape(_tt), _b))
    lab = "ac %s · P %s · S %s" % (_fnum(r.get("acidez"), 2), _fnum(r.get("fosforo"), 0),
                                   _fnum(r.get("azufre"), 0))
    # medidor + última medición
    _fm = str(r.get("fuente_medicion") or "Manual")
    _mi = "📡" if _fm == "WeDo" else "✍️"
    _tm = _fts(r.get("ultima_medicion"))
    stale = ""
    try:
        _um = pd.to_datetime(r.get("ultima_medicion"), utc=True)
        if pd.notna(_um):
            _hsx = (pd.Timestamp.now(tz="UTC") - _um).total_seconds() / 3600.0
            if _hsx > 48:
                stale = " <b style='color:#b45309'>⏱%dd</b>" % int(_hsx // 24)
    except Exception:
        pass
    med = "%s %s · %s%s" % (_mi, _fm, (_tm or "sin medición"), stale)
    # Δ de la ventana
    if mov is not None and abs(float(mov.get("neto") or 0.0)) >= 100:
        _n = float(mov["neto"])
        dl = ("<span style='color:%s;font-weight:700'>%s%s L</span>"
              % ("#15803d" if _n > 0 else "#b91c1c", "▲+" if _n > 0 else "▼−", _fnum(abs(_n))))
    else:
        dl = "<span style='color:#94a3b8'>Δ 0</span>"
    # último movimiento tipificado
    umv = ""
    if ult is not None:
        _lb = _ORIGEN_LBL.get(str(ult.get("origen") or ""), "↔️ Mov.")
        if str(ult.get("origen") or "") == "despacho" and pd.notna(ult.get("id_despacho")):
            _lb += " #%d" % int(ult["id_despacho"])
        _sg = "−" if str(ult.get("tipo")) == "OUT" else "+"
        umv = ("<div class='tvq-ult' title='Último movimiento registrado'>últ: %s %s%s L · %s</div>"
               % (_lb, _sg, _fnum(ult.get("litros")), _fts(ult.get("ts")) or ""))
    _niv = _fnum(lts) if lts is not None else "s/med"
    _lock = ("<div class='tvq-lock'>🔒 %s L comp.</div>" % _fnum(comp)) if comp > 0 else ""
    h = ("<div class='tvq-card'>"
         "<div class='tvq-head' title='%s · %s'><span class='tvq-nom'>%s</span>%s</div>"
         "<div class='tvq-body'>"
         "<div class='tvq-tank %s'>"
         "<div class='tvq-fill' style='height:%.1f%%;background:linear-gradient(180deg,%scc,%s);bottom:%.1f%%'></div>"
         "<div class='tvq-comp' style='height:%.1f%%' title='🔒 %s L comprometidos en despachos confirmados'></div>"
         "<div class='tvq-pct'>%.0f%%</div>"
         "</div>"
         "<div class='tvq-info'>"
         "<div class='tvq-lts'><b>%s</b><span class='tvq-cap'> / %s L</span></div>"
         "<div class='tvq-prod' style='color:%s'>%s</div>"
         "<div class='tvq-lab' title='Último análisis de laboratorio'>%s</div>"
         "<div class='tvq-med' title='Medidor y última medición'>%s</div>"
         "<div class='tvq-mov'>%s</div>%s%s"
         "</div></div></div>"
         % (nombre, _html.escape(prod_lbl), nombre, chip_html,
            ("tvq-nomed" if lts is None else ""),
            pct_disp, col, col, pct_comp,
            pct_comp, _fnum(comp), pct,
            _niv, _fnum(cap), col, _html.escape(prod_lbl), lab, med, dl, umv, _lock))
    return h


_CSS = ("<style>"
        ".tvq-grid{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 14px}"
        ".tvq-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:8px 10px;"
        "width:224px;box-shadow:0 1px 2px rgba(15,23,42,.06)}"
        ".tvq-head{display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:6px}"
        ".tvq-nom{font-weight:700;font-size:.8rem;color:#0f172a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        ".tvq-bnd{font-weight:800;font-size:.72rem;border-radius:8px;padding:1px 7px;flex:none}"
        ".tvq-body{display:flex;gap:10px;align-items:stretch}"
        ".tvq-tank{position:relative;width:54px;min-height:112px;border:2px solid #94a3b8;"
        "border-radius:8px 8px 12px 12px;background:#f8fafc;overflow:hidden;flex:none}"
        ".tvq-tank.tvq-nomed{border-style:dashed;background:repeating-linear-gradient(45deg,#f8fafc,"
        "#f8fafc 6px,#f1f5f9 6px,#f1f5f9 12px)}"
        ".tvq-fill{position:absolute;left:0;right:0}"
        ".tvq-comp{position:absolute;left:0;right:0;bottom:0;"
        "background:repeating-linear-gradient(45deg,#0f172a55,#0f172a55 4px,#0f172a22 4px,#0f172a22 8px)}"
        ".tvq-pct{position:absolute;top:4px;left:0;right:0;text-align:center;font-weight:800;"
        "font-size:.76rem;color:#0f172a;text-shadow:0 0 4px #fff}"
        ".tvq-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;justify-content:center}"
        ".tvq-lts{font-size:.8rem;color:#0f172a}"
        ".tvq-cap{color:#64748b;font-size:.7rem}"
        ".tvq-prod{font-weight:700;font-size:.72rem}"
        ".tvq-lab{font-size:.66rem;color:#475569;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        ".tvq-med{font-size:.64rem;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        ".tvq-mov{font-size:.68rem}"
        ".tvq-ult{font-size:.64rem;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        ".tvq-lock{font-size:.66rem;color:#7c2d12}"
        ".tvq-sec{display:flex;align-items:baseline;gap:10px;margin:14px 0 2px}"
        ".tvq-sec h4{margin:0;font-size:1.02rem}"
        ".tvq-secbar{flex:1;height:8px;background:#e2e8f0;border-radius:6px;overflow:hidden;max-width:260px}"
        ".tvq-secfill{height:100%;background:linear-gradient(90deg,#0ea5e9,#0284c7)}"
        ".tvq-sect{font-size:.78rem;color:#475569}"
        ".tvq-prods{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 2px}"
        ".tvq-pchip{font-size:.72rem;font-weight:700;border:1px solid;border-radius:9px;"
        "padding:2px 9px;background:#fff}"
        ".tvq-pplanta{font-weight:400;color:#64748b}"
        "</style>")


def render(USR, cat, conectar=None):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#0c4a6e,#0284c7);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🧭 Visualización de tanques</div>"
        "<div style='color:#e0f2fe;font-size:.88rem;margin-top:3px'>La planta de un vistazo: nivel "
        "sobre capacidad, producto, calidad, comprometido en despachos, medidor y últimos "
        "movimientos.</div></div>", unsafe_allow_html=True)

    df = cat("SELECT id_tanque, nombre, sector, producto_principal, producto_rotulo, "
             "capacidad_litros, "
             "litros_actual, kg_actual, litros_comprometido, litros_disponible, densidad, "
             "acidez, fosforo, azufre, agua_sedimento, ultima_medicion, fuente_medicion, "
             "condicion FROM produccion.vw_tanque_panel WHERE activo ORDER BY sector, nombre")
    if df is None or df.empty:
        st.info("No hay tanques activos.")
        return
    df = df.copy()
    for c in ("capacidad_litros", "litros_actual", "kg_actual", "litros_comprometido",
              "litros_disponible", "acidez", "fosforo", "azufre", "agua_sedimento", "densidad"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # etiqueta visible = rótulo oficial (con calidad); el código queda para la lógica
    df["prod_lbl"] = (df["producto_rotulo"].fillna(df["producto_principal"])
                        .fillna("—").astype(str))
    _cod_de = dict(zip(df["prod_lbl"], df["producto_principal"].fillna("—").astype(str)))

    # total de planta por producto, ANTES de filtrar (recordatorio por sector)
    _tot_planta = (df.assign(_l=df["litros_actual"].fillna(0))
                     .groupby(df["prod_lbl"])["_l"].sum().to_dict())

    # ---------- filtros ----------
    f1, f2, f3, f4 = st.columns([1.6, 1.6, 1.2, 1.0])
    _secs = sorted(df["sector"].fillna("—").unique().tolist())
    f_sec = f1.multiselect("Sector", _secs, key="tvq_sec", placeholder="todos")
    _prods = sorted(df["prod_lbl"].unique().tolist())
    f_prod = f2.multiselect("Producto", _prods, key="tvq_prod", placeholder="todos")
    _orden = f3.selectbox("Ordenar por", ["% de llenado", "Litros", "Producto", "Nombre",
                                          "Calidad"], key="tvq_ord")
    _hs = int(f4.selectbox("Movs. últimas", [6, 12, 24, 48], index=2, key="tvq_hs",
                           help="Ventana del Δ neto que muestra cada tarjeta."))
    if f_sec:
        df = df[df["sector"].fillna("—").isin(f_sec)]
    if f_prod:
        df = df[df["prod_lbl"].isin(f_prod)]
    if df.empty:
        st.info("Ningún tanque cumple los filtros.")
        return

    # ---------- movimientos: neto de la ventana + ÚLTIMO tipificado (7 días) ----------
    movs = cat("SELECT mv.id_tanque, "
               "SUM(CASE WHEN mv.tipo='OUT' THEN -COALESCE(mv.litros,0) "
               "         ELSE COALESCE(mv.litros,0) END) AS neto, "
               "SUM(CASE WHEN mv.tipo<>'OUT' THEN COALESCE(mv.litros,0) ELSE 0 END) AS entro, "
               "SUM(CASE WHEN mv.tipo='OUT' THEN COALESCE(mv.litros,0) ELSE 0 END) AS salio, "
               "COUNT(*) AS n "
               "FROM produccion.fact_movimiento_tanque mv "
               "WHERE mv.ts >= now() - (%s || ' hours')::interval "
               "GROUP BY mv.id_tanque", (str(_hs),))
    _mv = {}
    if movs is not None and not movs.empty:
        for _, m in movs.iterrows():
            _mv[int(m["id_tanque"])] = {"neto": float(m["neto"] or 0),
                                        "entro": float(m["entro"] or 0),
                                        "salio": float(m["salio"] or 0), "n": int(m["n"])}
    ults = cat("SELECT DISTINCT ON (mv.id_tanque) mv.id_tanque, mv.tipo, mv.litros, mv.ts, "
               "ms.origen, ms.id_despacho "
               "FROM produccion.fact_movimiento_tanque mv "
               "LEFT JOIN produccion.fact_movimiento_stock ms ON ms.id_mov_stock = mv.id_mov_stock "
               "WHERE mv.ts >= now() - interval '7 days' "
               "ORDER BY mv.id_tanque, mv.ts DESC")
    _ult = {}
    if ults is not None and not ults.empty:
        for _, u in ults.iterrows():
            _ult[int(u["id_tanque"])] = u

    # ---------- KPIs ----------
    _lts = df["litros_actual"].fillna(0)
    _cap = df["capacidad_litros"].fillna(0)
    _dns = df["densidad"].fillna(0.91)
    _comp = df["litros_comprometido"].fillna(0)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Tanques", int(len(df)))
    k2.metric("Stock", "%s t" % _fnum((_lts * _dns).sum() / 1000.0))
    k3.metric("Ocupación", "%.0f %%" % (100.0 * _lts.sum() / _cap.sum() if _cap.sum() else 0))
    k4.metric("🔒 Comprometido", "%s L" % _fnum(_comp.sum()),
              help="En despachos confirmados sin terminar de pesar: es la franja rayada "
                   "arriba del líquido de cada tanque.")
    _neto_f = sum(_mv.get(int(t), {"neto": 0})["neto"] for t in df["id_tanque"])
    k5.metric("Δ últimas %d h" % _hs, "%s%s L" % ("+" if _neto_f >= 0 else "−", _fnum(abs(_neto_f))),
              help="Movimiento neto (entradas − salidas) de los tanques visibles.")
    st.caption("🎨 Chip de calidad: en **AFE/AG** es la banda contra la spec de venta "
               "(🟢 A excelente · 🔵 B bueno · 🟠 C justo · 🔴 D fuera de spec · — sin lab); "
               "en el resto es la **calidad del producto** (ARE-B → B). Franja **rayada** = "
               "comprometido en despachos · recipiente **punteado** = sin medición · "
               "📡 WeDo / ✍️ Manual con fecha y hora de la última medición · "
               "⏱ = medición con más de 48 h.")

    # ---------- orden ----------
    df["_pct"] = (100.0 * _lts / _cap.replace(0, pd.NA)).fillna(-1)
    df["_chp"] = [(c[0] if c else "z") for c in
                  (_chip_calidad(p, s, f) for p, s, f in
                   zip(df["producto_principal"], df["azufre"], df["fosforo"]))]
    _keys = {"% de llenado": ("_pct", False), "Litros": ("litros_actual", False),
             "Producto": ("prod_lbl", True), "Nombre": ("nombre", True),
             "Calidad": ("_chp", True)}
    _k, _asc = _keys[_orden]
    df = df.sort_values([_k, "nombre"], ascending=[_asc, True], na_position="last")

    # ---------- tarjetas por sector ----------
    st.markdown(_CSS, unsafe_allow_html=True)
    _ords = (df.groupby("sector")["litros_actual"].sum().sort_values(ascending=False))
    for _sec in _ords.index:
        _d = df[df["sector"] == _sec]
        _sl = float(_d["litros_actual"].fillna(0).sum())
        _sc = float(_d["capacidad_litros"].fillna(0).sum())
        _po = (100.0 * _sl / _sc) if _sc else 0.0
        st.markdown(
            "<div class='tvq-sec'><h4>🏭 %s</h4>"
            "<div class='tvq-secbar'><div class='tvq-secfill' style='width:%.0f%%'></div></div>"
            "<span class='tvq-sect'>%s / %s L · %.0f%% · %d tanques</span></div>"
            % (_html.escape(str(_sec or "—")), min(100, _po), _fnum(_sl), _fnum(_sc), _po,
               len(_d)), unsafe_allow_html=True)
        # resumen del sector por producto (el código ya trae la calidad: AG-C, ARE-B…)
        _gp = (_d.assign(_l=_d["litros_actual"].fillna(0))
                 .groupby(_d["prod_lbl"])["_l"].sum()
                 .sort_values(ascending=False))
        _chips = []
        for _pn, _pl in _gp.items():
            if _pl <= 0:
                continue
            _cp = _color_prod(_cod_de.get(_pn, _pn))
            _tp = float(_tot_planta.get(_pn, 0.0))
            _pctp = (100.0 * _pl / _tp) if _tp > 0 else 0.0
            _chips.append(
                "<span class='tvq-pchip' style='border-color:%s55;color:%s' "
                "title='%s en este sector · en toda la planta hay %s L'>"
                "%s <b>%s L</b><span class='tvq-pplanta'> · %.0f%% de %s L en planta</span></span>"
                % (_cp, _cp, _html.escape(str(_pn)), _fnum(_tp),
                   _html.escape(str(_pn)), _fnum(_pl), _pctp, _fnum(_tp)))
        if _chips:
            st.markdown("<div class='tvq-prods'>%s</div>" % "".join(_chips),
                        unsafe_allow_html=True)
        _cards = "".join(_card(r, _mv.get(int(r["id_tanque"])), _ult.get(int(r["id_tanque"])))
                         for _, r in _d.iterrows())
        st.markdown("<div class='tvq-grid'>%s</div>" % _cards, unsafe_allow_html=True)

    # ---------- los que más se movieron ----------
    with st.expander("📈 Movimientos de las últimas %d horas — los que más se movieron" % _hs):
        if not _mv:
            st.info("Sin movimientos registrados en la ventana.")
        else:
            _nom = {int(r["id_tanque"]): (str(r["nombre"]), str(r["prod_lbl"] or "—"),
                                          str(r["sector"] or "—")) for _, r in df.iterrows()}
            _rows = [{"Tanque": _nom[t][0], "Producto": _nom[t][1], "Sector": _nom[t][2],
                      "Entró (L)": m["entro"], "Salió (L)": m["salio"], "Neto (L)": m["neto"],
                      "Movs": m["n"]}
                     for t, m in _mv.items() if t in _nom]
            _rows = sorted(_rows, key=lambda x: -abs(x["Neto (L)"]))[:20]
            if not _rows:
                st.info("Los tanques visibles no tuvieron movimientos en la ventana.")
            else:
                st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True,
                             column_config={c: st.column_config.NumberColumn(format="%.0f")
                                            for c in ("Entró (L)", "Salió (L)", "Neto (L)")})
                st.caption("Neto = entradas − salidas del ledger de movimientos. Un neto grande "
                           "sin medición nueva es aviso de que el nivel del panel quedó viejo.")
