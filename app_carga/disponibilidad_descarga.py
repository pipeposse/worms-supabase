# -*- coding: utf-8 -*-
"""Disponibilidad de descarga (Centro de Planificación y Producción en planta).

El problema: llega un camión y no se sabe dónde descargarlo — hay poca
disponibilidad y la semana pasada un camión terminó repartido en 7 tanques.
Esta sección ataca los dos frentes:

  1. 🗺️ MAPA DE ESPACIO: ver a simple vista dónde hay lugar, por sector y por
     producto, con la calidad (banda A/B/C/D) de lo que ya hay en cada tanque.
  2. 🧭 RECOMENDADOR: para un líquido con sus parámetros (un camión por llegar,
     una hipótesis), ranking de tanques — PRIMERO el de parámetros similares —
     usando el MISMO motor de Asignación AFE (afinidad + historial + espacio +
     degradación).
  3. 🎯 ASIGNACIÓN AFE embebida: cada ticket real que entra se recomienda y se
     CONFIRMA acá mismo — se ve dónde descargar y se elige en el mismo lugar.

Sólo lectura salvo la asignación (que es el circuito auditado de siempre)."""

import pandas as pd
import streamlit as st

import asignacion_afe as _asg

# Spec de venta para bandear la calidad del contenido (misma regla que Tanques):
# r = max(S/50, P/150) -> A<=0,80 · B<=0,90 · C<=1,00 · D>1,00.
_SPEC_S, _SPEC_P = 50.0, 150.0
_BANDA_CLR = {"A": "#16a34a", "B": "#84cc16", "C": "#f59e0b", "D": "#dc2626"}
_ESPACIO_UTIL = 5000.0     # con menos de esto, el tanque no salva un camión


def _fx(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _banda(prod, az, p):
    """Banda de calidad del contenido para la familia AFE/AG; '—' si no aplica."""
    _p = str(prod or "").strip().upper()
    if not (_p.startswith("AFE") or _p.startswith("AG")):
        return None
    rr = []
    if _fx(az) is not None:
        rr.append(_fx(az) / _SPEC_S)
    if _fx(p) is not None:
        rr.append(_fx(p) / _SPEC_P)
    if not rr:
        return "?"
    r = max(rr)
    return "A" if r <= 0.80 else ("B" if r <= 0.90 else ("C" if r <= 1.00 else "D"))


def _mapa(USR, cat):
    tks = cat("SELECT p.id_tanque, p.nombre, p.sector, p.producto_principal, "
              "p.capacidad_litros, p.litros_actual, p.acidez, p.fosforo, p.azufre, "
              "p.agua_sedimento, p.condicion, COALESCE(t.uso,'ACOPIO') AS uso "
              "FROM produccion.vw_tanque_panel p "
              "JOIN produccion.dim_tanque t ON t.id_tanque = p.id_tanque "
              "WHERE p.activo AND COALESCE(p.condicion,'EN USO') <> 'FUERA DE USO' "
              "ORDER BY p.sector, p.nombre")
    if tks is None or tks.empty:
        st.info("No hay tanques activos para mostrar.")
        return
    tks = tks.copy()
    for c in ("capacidad_litros", "litros_actual", "acidez", "fosforo", "azufre"):
        tks[c] = pd.to_numeric(tks[c], errors="coerce")
    tks["_lts"] = tks["litros_actual"].fillna(0.0).clip(lower=0.0)
    tks["_cap"] = tks["capacidad_litros"].fillna(0.0)
    tks["_libre"] = (tks["_cap"] - tks["_lts"]).clip(lower=0.0)
    tks["_pct"] = (100.0 * tks["_lts"] / tks["_cap"].replace(0, pd.NA)).fillna(0.0)
    tks["_banda"] = [_banda(r["producto_principal"], r["azufre"], r["fosforo"])
                     for _, r in tks.iterrows()]

    f1, f2, f3, f4 = st.columns([1.4, 1.4, 1.1, 1.1])
    _prods = sorted(tks["producto_principal"].dropna().astype(str).unique().tolist())
    _fp = f1.multiselect("Producto", _prods, key="dd_fprod",
                         help="Vacío = todos. El espacio útil es por producto: un camión de "
                              "AFE-S sólo puede ir a tanques de AFE-S (o vacíos habilitados).")
    _secs = sorted(tks["sector"].dropna().astype(str).unique().tolist())
    _fs = f2.multiselect("Sector", _secs, key="dd_fsec")
    _solo = f3.checkbox("Sólo con espacio útil (≥ %s L)" % "{:,.0f}".format(_ESPACIO_UTIL),
                        value=False, key="dd_solo")
    _ord = f4.selectbox("Orden", ["Más espacio primero", "N° de tanque"], key="dd_ord")

    v = tks
    if _fp:
        v = v[v["producto_principal"].astype(str).isin(_fp)]
    if _fs:
        v = v[v["sector"].astype(str).isin(_fs)]
    if _solo:
        v = v[v["_libre"] >= _ESPACIO_UTIL]
    if v.empty:
        st.warning("Ningún tanque cumple los filtros.")
        return

    # ---- KPIs: el diagnóstico en un vistazo
    _tot_libre = float(v["_libre"].sum())
    _utiles = int((v["_libre"] >= _ESPACIO_UTIL).sum())
    _por_prod = (v.groupby(v["producto_principal"].astype(str))["_libre"].sum()
                 .sort_values(ascending=False))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Espacio libre total", "%.2f kL" % (_tot_libre / 1000.0))
    k2.metric("Tanques con espacio útil", "%d de %d" % (_utiles, len(v)),
              help="Espacio útil = al menos %s L libres." % "{:,.0f}".format(_ESPACIO_UTIL))
    _p1 = _por_prod.index[0] if len(_por_prod) else "—"
    k3.metric("Más lugar en", str(_p1),
              "%.2f kL" % (float(_por_prod.iloc[0]) / 1000.0) if len(_por_prod) else None,
              delta_color="off")
    _crit = _por_prod[_por_prod < 30000.0]
    k4.metric("Productos críticos (< 30 kL libres)", "%d" % len(_crit),
              help=("Poco lugar para: " + ", ".join(
                    "%s (%.1f kL)" % (i, x / 1000.0) for i, x in _crit.items()))
              if len(_crit) else "Ningún producto con menos de 30 kL libres.")
    if len(_crit):
        st.warning("🔴 **Poco espacio para:** " + " · ".join(
            "**%s** %.1f kL" % (i, x / 1000.0) for i, x in _crit.items())
            + ". Un camión (~30 kL) de esos productos va a terminar repartido: "
              "conviene despachar o reacomodar antes de que llegue.")

    st.caption("Cada tarjeta: producto y **banda de calidad** del contenido (A/B/C/D contra la "
               "spec de venta S≤50 · P≤150), barra de **% lleno** y los **kL libres**. Borde "
               "verde = lugar de sobra · amarillo = justo · rojo = casi lleno.")

    _orden_srt = (["sector", "_libre"], [True, False]) if _ord.startswith("Más") \
        else (["sector", "nombre"], [True, True])
    for _sec in sorted(v["sector"].dropna().astype(str).unique().tolist()):
        _vs = v[v["sector"].astype(str) == _sec].sort_values(_orden_srt[0],
                                                             ascending=_orden_srt[1])
        _lib_sec = float(_vs["_libre"].sum()) / 1000.0
        st.markdown("**%s** · %.2f kL libres en %d tanque(s)" % (_sec, _lib_sec, len(_vs)))
        _cards = []
        for _, r in _vs.iterrows():
            _lib = float(r["_libre"])
            _pct = min(100.0, float(r["_pct"]))
            _brd = "#16a34a" if _lib >= 20000 else ("#f59e0b" if _lib >= _ESPACIO_UTIL
                                                    else "#dc2626")
            _bar = "#dc2626" if _pct >= 90 else ("#f59e0b" if _pct >= 70 else "#16a34a")
            _bd = r["_banda"]
            _chip = ("<span style='background:%s;color:#fff;border-radius:8px;padding:0 7px;"
                     "font-size:.72rem;font-weight:800'>%s</span>"
                     % (_BANDA_CLR.get(_bd, "#6b7280"), _bd)) if _bd else ""
            _cards.append(
                "<div style='border:2px solid %s;border-radius:12px;padding:8px 10px;"
                "width:200px;background:#fff'>"
                "<div style='display:flex;justify-content:space-between;align-items:center'>"
                "<b style='font-size:.9rem'>%s</b>%s</div>"
                "<div style='font-size:.76rem;color:#555'>%s</div>"
                "<div style='background:#e5e7eb;border-radius:6px;height:10px;margin:6px 0'>"
                "<div style='background:%s;width:%.0f%%;height:10px;border-radius:6px'></div></div>"
                "<div style='font-size:.8rem'>Libre <b>%.2f kL</b> · %.0f%% lleno</div>"
                "</div>"
                % (_brd, str(r["nombre"]), _chip,
                   str(r["producto_principal"] or "sin producto"),
                   _bar, _pct, _lib / 1000.0, _pct))
        st.markdown("<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px'>"
                    + "".join(_cards) + "</div>", unsafe_allow_html=True)


def _recomendador(USR, cat):
    st.caption("Simulá el camión ANTES de que llegue (o un líquido hipotético): el motor es el "
               "mismo de Asignación AFE — **primero el tanque de parámetros similares**, después "
               "historial, espacio y que no degrade lo que ya hay. Para el ticket real, la "
               "decisión se confirma en la pestaña 🎯.")
    _pr = cat("SELECT id_producto, codigo_producto FROM produccion.dim_producto "
              "WHERE COALESCE(activo,true) ORDER BY codigo_producto")
    if _pr is None or _pr.empty:
        st.error("No se pudo leer el maestro de productos.")
        return
    _cods = _pr["codigo_producto"].astype(str).tolist()
    _ids = dict(zip(_pr["codigo_producto"].astype(str), _pr["id_producto"].astype(int)))
    c1, c2 = st.columns([1.2, 1.0])
    _def = _cods.index("AFE-S") if "AFE-S" in _cods else 0
    _pcod = c1.selectbox("Producto que llega", _cods, index=_def, key="dd_sim_prod")
    _kg = c2.number_input("Kg del camión", min_value=1000.0, max_value=80000.0,
                          value=30000.0, step=500.0, format="%.0f", key="dd_sim_kg")
    p1, p2, p3, p4, p5 = st.columns(5)
    _ac = p1.number_input("Acidez %", min_value=0.0, step=0.1, format="%.2f",
                          key="dd_sim_ac", help="0 = sin dato.")
    _az = p2.number_input("Azufre ppm", min_value=0.0, step=1.0, format="%.0f",
                          key="dd_sim_az", help="0 = sin dato.")
    _fo = p3.number_input("Fósforo ppm", min_value=0.0, step=5.0, format="%.0f",
                          key="dd_sim_fo", help="0 = sin dato.")
    _ag = p4.number_input("Agua %", min_value=0.0, step=0.1, format="%.2f",
                          key="dd_sim_ag", help="0 = sin dato.")
    _se = p5.number_input("Sedimentos %", min_value=0.0, step=0.1, format="%.2f",
                          key="dd_sim_se", help="0 = sin dato.")
    if st.button("🧭 Recomendar dónde descargar", type="primary", key="dd_sim_go"):
        st.session_state["dd_sim_run"] = True
    if not st.session_state.get("dd_sim_run"):
        return
    _idp = _ids.get(_pcod)
    cands = _asg._candidatos(cat, int(_idp))
    if cands is None or cands.empty:
        st.error("No hay tanques de acopio habilitados para **%s** (permitido o producto "
                 "principal). Habilitalo en el maestro de tanques." % _pcod)
        return
    tk = {"acidez": (_ac or None), "azufre": (_az or None), "fosforo": (_fo or None),
          "agua": (_ag or None), "sed": (_se or None)}
    dens = _asg._densidad(cat, int(_idp))
    litros = float(_kg) / dens if dens else 0.0
    rank = _asg._rankear(cands, tk, litros, kg=float(_kg))
    if not rank:
        st.warning("Ningún tanque puntuable para este producto.")
        return
    sug = _asg._sugerir(rank, float(_kg), dens)
    st.markdown("##### Sugerencia (%d tanque(s) para %s kg ≈ %.1f kL)"
                % (len(sug), "{:,.0f}".format(float(_kg)), litros / 1000.0))
    if len(sug) >= 4:
        st.warning("⚠️ Hacen falta **%d tanques** para absorber este camión: la "
                   "disponibilidad está crítica (el caso de los 7 tanques). Mirá el mapa "
                   "y considerá despachar o reacomodar antes." % len(sug))
    for s in sug:
        _fa = float(s.get("_falta") or 0.0)
        st.markdown("**%d. %s** (%s) — **%s kg** · afinidad %.0f%% · libre %s L · %s"
                    % (int(s["_orden"]), str(s["nombre"]), str(s["sector"]),
                       "{:,.0f}".format(float(s["_kg"])), 100.0 * float(s["_afin"]),
                       "{:,.0f}".format(float(s["_disp"])), _asg._porque(s)))
        if _fa > 0.5:
            st.error("⛔ Quedan **%s kg SIN LUGAR** ni repartiendo en 7 tanques: no hay "
                     "espacio suficiente para este producto. Hay que liberar tanques "
                     "(despachar) antes de recibir el camión." % "{:,.0f}".format(_fa))
    with st.expander("📊 Ranking completo de tanques (por qué cada puntaje)", expanded=False):
        _rows = [{
            "Tanque": str(r["nombre"]), "Sector": str(r["sector"]),
            "Score": round(float(r["_score"]), 3) if float(r["_score"]) > 0 else None,
            "Afinidad %": round(100.0 * float(r["_afin"]), 0),
            "Libre (kL)": round(float(r["_disp"]) / 1000.0, 2),
            "Contenido (kL)": round(float(r["_lts_est"]) / 1000.0, 2),
            "Acidez": _fx(r.get("acidez_pct")), "S ppm": _fx(r.get("ppm_azufre")),
            "P ppm": _fx(r.get("ppm_fosforo")),
            "Estado": ("⛔ " + str(r["_bloqueo"])) if not r["_ok"] else
                      ("🕳️ vacío" if r.get("_vacio") else "OK"),
        } for r in rank[:15]]
        st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)
        st.caption("Score = 40%% afinidad de parámetros + 25%% historial + 20%% espacio + "
                   "15%% consolidación, con veto por degradación y por máximos del tanque. "
                   "⛔ = el líquido supera un máximo declarado del tanque.")


def render(USR, cat, conectar, contexto="PLANTA"):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#065f46,#0e7490);border-radius:14px;"
        "padding:14px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.3rem;font-weight:900'>📍 Disponibilidad de descarga</div>"
        "<div style='color:#d1fae5;font-size:.86rem;margin-top:3px'>Dónde hay lugar y a qué "
        "tanque conviene descargar cada camión — mapa visual, recomendador y la asignación "
        "de AFEs en un solo lugar.</div></div>",
        unsafe_allow_html=True)
    try:
        import wedo_estado
        wedo_estado.banner(cat)   # elegir dónde descargar con niveles viejos = desastre
    except Exception:
        pass
    _opts = ["🗺️ Mapa de espacio", "🧭 Recomendador", "🎯 Asignación AFE (tickets)"]
    try:
        _v = st.segmented_control("Vista", _opts, default=_opts[0],
                                  key="dd_view_sc_%s" % contexto, label_visibility="collapsed")
    except Exception:
        _v = st.radio("Vista", _opts, horizontal=True, key="dd_view_rd_%s" % contexto)
    _v = _v or _opts[0]
    st.write("")
    if _v.startswith("🗺️"):
        _mapa(USR, cat)
    elif _v.startswith("🧭"):
        _recomendador(USR, cat)
    else:
        # la decisión real, embebida: se ve dónde descargar y se ELIGE acá mismo
        _asg.render(USR, cat, conectar, contexto)
