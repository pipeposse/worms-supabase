# -*- coding: utf-8 -*-
"""Visualización de tanques — el estado de la planta de un vistazo.

Cada tanque se dibuja como un recipiente a escala: el nivel es el stock medido
sobre la capacidad, la parte rayada de arriba del líquido es lo COMPROMETIDO en
despachos confirmados (está en el tanque pero ya tiene dueño), y el color es el
producto. Al pie, la banda de calidad A/B/C/D contra la spec de venta, el último
lab y el movimiento neto de las últimas horas.

Es HTML/CSS puro sin estado (ningún widget adentro de las tarjetas): no puede
colgarse ni resetear nada, y dibuja 50 tanques en un solo render.
"""
import html as _html

import pandas as pd
import streamlit as st

# spec de venta (la misma que Balance) para la banda A/B/C/D
_SPEC_S, _SPEC_P = 50.0, 150.0
_BANDA_COL = {"A": "#166534", "B": "#1d4ed8", "C": "#b45309", "D": "#b91c1c", "—": "#94a3b8"}
_BANDA_DESC = {"A": "excelente", "B": "bueno", "C": "justo", "D": "fuera de spec",
               "—": "sin lab"}
# color del líquido por producto (familias); el resto cae en el default
_PROD_COL = [("AFE-SG", "#64748b"), ("AFE-S", "#0284c7"), ("AFE-G", "#7c3aed"),
             ("AFE", "#0ea5e9"), ("AG-E", "#d97706"), ("AG", "#f59e0b"),
             ("ARE", "#16a34a"), ("SEBO", "#a16207"), ("GLICERINA", "#db2777"),
             ("MP", "#6b7280")]


def _color_prod(p):
    up = str(p or "").strip().upper()
    for pref, col in _PROD_COL:
        if up.startswith(pref):
            return col
    return "#475569"


def _banda(s, p):
    if pd.isna(s) and pd.isna(p):
        return "—"
    ic = max((float(s) / _SPEC_S) if pd.notna(s) else 0.0,
             (float(p) / _SPEC_P) if pd.notna(p) else 0.0)
    if ic <= 0.80:
        return "A"
    if ic <= 0.90:
        return "B"
    if ic <= 1.00:
        return "C"
    return "D"


def _fnum(v, dec=0, vacio="—"):
    try:
        if v is None or pd.isna(v):
            return vacio
        return ("{:,.%df}" % dec).format(float(v))
    except Exception:
        return vacio


def _card(r, mov):
    """HTML de la tarjeta de UN tanque."""
    nombre = _html.escape(str(r["nombre"]))
    prod = str(r["producto_principal"] or "—")
    col = _color_prod(prod)
    cap = float(r["capacidad_litros"]) if pd.notna(r["capacidad_litros"]) else 0.0
    lts = float(r["litros_actual"]) if pd.notna(r["litros_actual"]) else None
    comp = float(r.get("litros_comprometido") or 0.0)
    pct = min(100.0, max(0.0, 100.0 * (lts or 0.0) / cap)) if cap > 0 else 0.0
    # comprometido dibujado como la tajada SUPERIOR del líquido
    comp_draw = min(comp, (lts or 0.0))
    pct_comp = min(pct, 100.0 * comp_draw / cap) if cap > 0 else 0.0
    pct_disp = max(0.0, pct - pct_comp)
    bnd = _banda(r.get("azufre"), r.get("fosforo"))
    bcol = _BANDA_COL[bnd]
    # lab compacto
    lab = "ac %s · P %s · S %s" % (_fnum(r.get("acidez"), 2), _fnum(r.get("fosforo"), 0),
                                   _fnum(r.get("azufre"), 0))
    if pd.notna(r.get("agua_sedimento")):
        lab += " · AyS %s" % _fnum(r.get("agua_sedimento"), 2)
    # frescura de la medición
    stale = ""
    try:
        _um = pd.to_datetime(r.get("ultima_medicion"), utc=True)
        if pd.notna(_um):
            _hs = (pd.Timestamp.now(tz="UTC") - _um).total_seconds() / 3600.0
            if _hs > 48:
                stale = "<span title='Última medición hace %.0f h' style='color:#b45309'>⏱%dd</span>" % (_hs, int(_hs // 24))
    except Exception:
        pass
    # movimiento neto de la ventana
    _mv = ""
    if mov is not None:
        _n = float(mov.get("neto") or 0.0)
        if abs(_n) >= 100:
            _mv = ("<span style='color:%s;font-weight:700'>%s%s L</span>"
                   % ("#15803d" if _n > 0 else "#b91c1c",
                      "▲ +" if _n > 0 else "▼ −", _fnum(abs(_n))))
        else:
            _mv = "<span style='color:#94a3b8'>— sin mov.</span>"
    else:
        _mv = "<span style='color:#94a3b8'>— sin mov.</span>"
    _niv = ("%s" % _fnum(lts)) if lts is not None else "s/med"
    _sinm = lts is None
    return f"""
<div class="tvq-card">
  <div class="tvq-head" title="{nombre} · {_html.escape(prod)}">
    <span class="tvq-nom">{nombre}</span>
    <span class="tvq-bnd" style="background:{bcol}22;color:{bcol};border:1px solid {bcol}55"
          title="Banda {bnd} · {_BANDA_DESC[bnd]} (contra spec de venta S≤50 / P≤150)">{bnd}</span>
  </div>
  <div class="tvq-body">
    <div class="tvq-tank {'tvq-nomed' if _sinm else ''}">
      <div class="tvq-fill" style="height:{pct_disp:.1f}%;background:linear-gradient(180deg,{col}cc,{col});bottom:{pct_comp:.1f}%"></div>
      <div class="tvq-comp" style="height:{pct_comp:.1f}%"
           title="🔒 {_fnum(comp)} L comprometidos en despachos confirmados"></div>
      <div class="tvq-pct">{pct:.0f}%</div>
    </div>
    <div class="tvq-info">
      <div class="tvq-lts"><b>{_niv}</b><span class="tvq-cap"> / {_fnum(cap)} L</span></div>
      <div class="tvq-prod" style="color:{col}">{_html.escape(prod)}</div>
      <div class="tvq-lab" title="Último análisis de laboratorio">{lab}</div>
      <div class="tvq-mov">{_mv} {stale}</div>
      {"<div class='tvq-lock'>🔒 " + _fnum(comp) + " L comp.</div>" if comp > 0 else ""}
    </div>
  </div>
</div>"""


_CSS = """
<style>
.tvq-grid{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 14px}
.tvq-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:8px 10px;
  width:212px;box-shadow:0 1px 2px rgba(15,23,42,.06)}
.tvq-head{display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:6px}
.tvq-nom{font-weight:700;font-size:.8rem;color:#0f172a;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.tvq-bnd{font-weight:800;font-size:.72rem;border-radius:8px;padding:1px 7px}
.tvq-body{display:flex;gap:10px;align-items:stretch}
.tvq-tank{position:relative;width:58px;min-height:104px;border:2px solid #94a3b8;
  border-radius:8px 8px 12px 12px;background:#f8fafc;overflow:hidden;flex:none}
.tvq-tank.tvq-nomed{border-style:dashed;background:repeating-linear-gradient(45deg,#f8fafc,
  #f8fafc 6px,#f1f5f9 6px,#f1f5f9 12px)}
.tvq-fill{position:absolute;left:0;right:0}
.tvq-comp{position:absolute;left:0;right:0;bottom:0;
  background:repeating-linear-gradient(45deg,#0f172a55,#0f172a55 4px,#0f172a22 4px,#0f172a22 8px)}
.tvq-pct{position:absolute;top:4px;left:0;right:0;text-align:center;font-weight:800;
  font-size:.78rem;color:#0f172a;text-shadow:0 0 4px #fff}
.tvq-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;justify-content:center}
.tvq-lts{font-size:.82rem;color:#0f172a}
.tvq-cap{color:#64748b;font-size:.72rem}
.tvq-prod{font-weight:700;font-size:.74rem}
.tvq-lab{font-size:.68rem;color:#475569;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tvq-mov{font-size:.7rem}
.tvq-lock{font-size:.68rem;color:#7c2d12}
.tvq-sec{display:flex;align-items:baseline;gap:10px;margin:14px 0 2px}
.tvq-sec h4{margin:0;font-size:1.02rem}
.tvq-secbar{flex:1;height:8px;background:#e2e8f0;border-radius:6px;overflow:hidden;max-width:260px}
.tvq-secfill{height:100%;background:linear-gradient(90deg,#0ea5e9,#0284c7)}
.tvq-sect{font-size:.78rem;color:#475569}
</style>"""


def render(USR, cat, conectar=None):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#0c4a6e,#0284c7);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🧭 Visualización de tanques</div>"
        "<div style='color:#e0f2fe;font-size:.88rem;margin-top:3px'>La planta de un vistazo: nivel "
        "sobre capacidad, producto, banda de calidad, comprometido en despachos y el movimiento "
        "de las últimas horas.</div></div>", unsafe_allow_html=True)

    df = cat("SELECT id_tanque, nombre, sector, producto_principal, capacidad_litros, "
             "litros_actual, kg_actual, litros_comprometido, litros_disponible, densidad, "
             "acidez, fosforo, azufre, agua_sedimento, ultima_medicion, condicion "
             "FROM produccion.vw_tanque_panel WHERE activo ORDER BY sector, nombre")
    if df is None or df.empty:
        st.info("No hay tanques activos.")
        return
    df = df.copy()
    for c in ("capacidad_litros", "litros_actual", "kg_actual", "litros_comprometido",
              "litros_disponible", "acidez", "fosforo", "azufre", "agua_sedimento", "densidad"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---------- filtros ----------
    f1, f2, f3, f4 = st.columns([1.6, 1.6, 1.2, 1.0])
    _secs = sorted(df["sector"].fillna("—").unique().tolist())
    f_sec = f1.multiselect("Sector", _secs, key="tvq_sec", placeholder="todos")
    _prods = sorted(df["producto_principal"].fillna("—").unique().tolist())
    f_prod = f2.multiselect("Producto", _prods, key="tvq_prod", placeholder="todos")
    _orden = f3.selectbox("Ordenar por", ["% de llenado", "Litros", "Producto", "Nombre",
                                          "Banda de calidad"], key="tvq_ord")
    _hs = int(f4.selectbox("Movs. últimas", [6, 12, 24, 48], index=2, key="tvq_hs",
                           help="Ventana de movimientos que muestra cada tarjeta."))
    if f_sec:
        df = df[df["sector"].fillna("—").isin(f_sec)]
    if f_prod:
        df = df[df["producto_principal"].fillna("—").isin(f_prod)]
    if df.empty:
        st.info("Ningún tanque cumple los filtros.")
        return

    # ---------- movimientos de la ventana ----------
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
    _neto_tot = sum(m["neto"] for m in _mv.values() if int(0) == 0) if _mv else 0.0
    _neto_f = sum(_mv.get(int(t), {"neto": 0})["neto"] for t in df["id_tanque"])
    k5.metric("Δ últimas %d h" % _hs, "%s%s L" % ("+" if _neto_f >= 0 else "−", _fnum(abs(_neto_f))),
              help="Movimiento neto (entradas − salidas) de los tanques visibles.")
    st.caption("🎨 Banda contra la spec de venta (S ≤ 50 / P ≤ 150): "
               "🟢 **A** excelente · 🔵 **B** bueno · 🟠 **C** justo · 🔴 **D** fuera de spec · "
               "**—** sin lab. La franja **rayada** arriba del líquido es stock comprometido en "
               "despachos; el recipiente **punteado** no tiene medición cargada.")

    # ---------- orden ----------
    df["_pct"] = (100.0 * _lts / _cap.replace(0, pd.NA)).fillna(-1)
    df["_bnd"] = [(_banda(s, p)) for s, p in zip(df["azufre"], df["fosforo"])]
    _keys = {"% de llenado": ("_pct", False), "Litros": ("litros_actual", False),
             "Producto": ("producto_principal", True), "Nombre": ("nombre", True),
             "Banda de calidad": ("_bnd", True)}
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
        _cards = "".join(_card(r, _mv.get(int(r["id_tanque"]))) for _, r in _d.iterrows())
        st.markdown("<div class='tvq-grid'>%s</div>" % _cards, unsafe_allow_html=True)

    # ---------- los que más se movieron ----------
    with st.expander("📈 Movimientos de las últimas %d horas — los que más se movieron" % _hs):
        if not _mv:
            st.info("Sin movimientos registrados en la ventana.")
        else:
            _nom = {int(r["id_tanque"]): (str(r["nombre"]), str(r["producto_principal"] or "—"),
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
                st.caption("Neto = entradas − salidas del ledger de movimientos (cargas, "
                           "asignaciones, despachos, decantaciones). Un neto grande sin "
                           "medición nueva es aviso de que el nivel del panel quedó viejo.")
