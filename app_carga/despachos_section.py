"""Despachos (Centro de Planificación) — carga de un despacho de exportación con su formulación.

Réplica corregida de la planilla "FORMULACION EXPO.xlsx":
  - Cabecera: destino, cliente, producto, tipo de carga, Nº de contenedores × litros por contenedor
    -> litros objetivo (y toneladas objetivo con la densidad del producto).
  - Especificación de venta: acidez % / AyS % / azufre ppm / fósforo ppm (máximos).
  - Formulación: una línea por tanque con los litros a cargar. El producto, la densidad y los
    parámetros de laboratorio se traen solos desde el tanque (vw_tanque_panel) y se pueden pisar.
  - Cálculo: kg = litros × densidad. Los promedios de acidez/fósforo/azufre/AyS se ponderan por KG
    (no por litros) porque % y ppm son fracciones másicas: ponderar por litros mezcla densidades
    distintas (AFE-S 0,89 vs AG-E 0,92) y da un resultado sesgado.
  - Validaciones: litros vs objetivo, litros vs stock real del tanque, cobertura de lab,
    y cumplimiento de cada spec con margen.

render(USR, cat, conectar)
"""
import io
import json
import datetime as _dt

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")

SPEC_DEFAULT = {"acidez": 5.0, "ays": 2.0, "azufre": 50.0, "fosforo": 150.0}
TIPOS_CARGA = ["FLEX", "ISO TANK", "BULK", "CAMION", "TAMBORES"]
ESTADOS = ["BORRADOR", "CONFIRMADO", "DESPACHADO", "ANULADO"]

_COLS_MIN = ["Tanque", "Litros"]
_COLS_LAB = ["Acidez %", "Fósforo ppm", "Azufre ppm", "AyS %"]
_COLS_ED = _COLS_MIN + _COLS_LAB
_PARAMS = (("Acidez %", "acidez"), ("Fósforo ppm", "fosforo"),
           ("Azufre ppm", "azufre"), ("AyS %", "agua_sedimento"))
_NAN = float("nan")


def _base_vacia(cols):
    """DataFrame vacío con dtypes correctos: evita que el editor muestre 'None' en las celdas."""
    return pd.DataFrame({c: pd.Series(dtype=("object" if c == "Tanque" else "float64"))
                         for c in cols})


def _faltan_lab(r):
    """Parámetros de laboratorio ausentes en un tanque."""
    return [n for n, k in _PARAMS if pd.isna(r.get(k))]


# ------------------------------------------------------------------ datos

def _tanques(cat):
    """Tanques activos con stock, densidad y último lab."""
    df = cat("SELECT id_tanque, codigo, nombre, sector, producto_principal, densidad, "
             "capacidad_litros, litros_actual, kg_actual, nivel_pct_actual, "
             "acidez, fosforo, azufre, agua_sedimento, lab_actualizado_en, condicion "
             "FROM produccion.vw_tanque_panel WHERE activo ORDER BY sector, codigo")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    for c in ["densidad", "capacidad_litros", "litros_actual", "kg_actual", "nivel_pct_actual",
              "acidez", "fosforo", "azufre", "agua_sedimento"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["etq"] = df.apply(lambda r: _etq_tanque(r), axis=1)
    return df


def _etq_tanque(r):
    _p = str(r.get("producto_principal") or "—")
    _l = r.get("litros_actual")
    _l = f"{_l:,.0f} L" if pd.notna(_l) else "sin medición"
    return f"{r['nombre']} · {_p} · {_l}"


def _productos(cat):
    df = cat("SELECT codigo_producto, coalesce(rotulo_oficial, codigo_producto) AS producto, "
             "tipo_producto, densidad_g_ml, es_exportacion FROM produccion.dim_producto "
             "WHERE activo ORDER BY 2")
    return df if df is not None else pd.DataFrame()


# ------------------------------------------------------------------ cálculo

def _resolver(ed: pd.DataFrame, tks: pd.DataFrame) -> pd.DataFrame:
    """Toma lo editado (Tanque + Litros + overrides) y devuelve la formulación resuelta."""
    if ed is None or ed.empty or tks.empty:
        return pd.DataFrame()
    mapa = tks.set_index("etq")
    filas = []
    for i, r in ed.iterrows():
        etq = r.get("Tanque")
        if not etq or etq not in mapa.index:
            continue
        try:
            lit = float(r.get("Litros") or 0)
        except Exception:
            lit = 0.0
        if lit <= 0:
            continue
        t = mapa.loc[etq]
        dens = float(t["densidad"]) if pd.notna(t["densidad"]) else 0.91
        fila = {
            "orden": len(filas) + 1,
            "id_tanque": int(t["id_tanque"]),
            "Tanque": t["nombre"],
            "Sector": t["sector"],
            "Producto": t["producto_principal"],
            "Litros": lit,
            "Densidad": dens,
            "kg": lit * dens,
            "TN": lit * dens / 1000.0,
            "Disp. (L)": float(t["litros_actual"]) if pd.notna(t["litros_actual"]) else 0.0,
        }
        for k_ed, k_tk, k_out in (("Acidez %", "acidez", "Acidez %"),
                                  ("Fósforo ppm", "fosforo", "Fósforo ppm"),
                                  ("Azufre ppm", "azufre", "Azufre ppm"),
                                  ("AyS %", "agua_sedimento", "AyS %")):
            v = r.get(k_ed)
            v = float(v) if (v is not None and str(v).strip() != "" and pd.notna(v)) else None
            if v is None:
                v = float(t[k_tk]) if pd.notna(t[k_tk]) else None
                fila[k_out + "_src"] = "lab" if v is not None else "—"
            else:
                fila[k_out + "_src"] = "manual"
            fila[k_out] = v
        fila["Restante (L)"] = fila["Disp. (L)"] - lit
        fila["Excede"] = lit > fila["Disp. (L)"] + 0.5
        filas.append(fila)
    return pd.DataFrame(filas)


def _ponderar(df: pd.DataFrame, col: str):
    """Promedio ponderado por kg + % de la masa que tiene ese dato."""
    if df.empty or col not in df.columns:
        return None, 0.0
    d = df[pd.notna(df[col])]
    kg_tot = float(df["kg"].sum())
    if d.empty or kg_tot <= 0:
        return None, 0.0
    kg_c = float(d["kg"].sum())
    if kg_c <= 0:
        return None, 0.0
    return float((d[col] * d["kg"]).sum() / kg_c), 100.0 * kg_c / kg_tot


def _panel_specs(res: pd.DataFrame, spec: dict):
    """Tarjetas de cumplimiento. Devuelve True si todo lo medible cumple."""
    filas = [("Acidez %", "Acidez %", spec["acidez"], "{:.2f}"),
             ("AyS %", "AyS %", spec["ays"], "{:.2f}"),
             ("Azufre ppm", "Azufre ppm", spec["azufre"], "{:.1f}"),
             ("Fósforo ppm", "Fósforo ppm", spec["fosforo"], "{:.1f}")]
    ok_total = True
    cols = st.columns(4)
    for (titulo, col, lim, fmt), c in zip(filas, cols):
        val, cob = _ponderar(res, col)
        if val is None or not lim:
            c.markdown(f"<div style='font-size:.78rem;color:#666'>{titulo}</div>"
                       f"<div style='font-size:1.3rem;font-weight:800;color:#94a3b8'>—</div>"
                       f"<div style='font-size:.72rem;color:#94a3b8'>sin dato de lab</div>",
                       unsafe_allow_html=True)
            continue
        cumple = val <= float(lim)
        margen = 100.0 * (float(lim) - val) / float(lim)
        if not cumple:
            clr, nota = "#dc2626", f"EXCEDE por {fmt.format(val - float(lim))}"
        elif margen < 5:
            clr, nota = "#b45309", f"al límite ({margen:.1f}% de margen)"
        else:
            clr, nota = "#16a34a", f"margen {margen:.1f}%"
        ok_total = ok_total and cumple
        _av = "" if cob >= 99.5 else f" · sólo {cob:.0f}% de la masa medida"
        c.markdown(f"<div style='font-size:.78rem;color:#666'>{titulo} · máx {fmt.format(float(lim))}</div>"
                   f"<div style='font-size:1.3rem;font-weight:800;color:{clr}'>{fmt.format(val)}</div>"
                   f"<div style='font-size:.72rem;color:{clr}'>{nota}{_av}</div>",
                   unsafe_allow_html=True)
    return ok_total


# ------------------------------------------------------------------ sugerencia de mezcla

def _sugerir(tks, prod_cod, litros_obj, spec, min_l=1000.0):
    """Heurística: llena el objetivo tomando primero los tanques de mejor calidad relativa.

    score = peor ratio contra la spec (val/límite). Menor score = más margen. Se cargan tanques
    de menor a mayor score hasta cubrir el objetivo; el último se toma parcial.
    """
    d = tks[(tks["producto_principal"].astype(str).str.upper() == str(prod_cod).upper())
            & (tks["litros_actual"].fillna(0) >= min_l)].copy()
    if d.empty:
        return pd.DataFrame(), "No hay tanques con ese producto y stock suficiente."

    def _score(r):
        rr = []
        for c, lim in (("acidez", spec["acidez"]), ("agua_sedimento", spec["ays"]),
                       ("azufre", spec["azufre"]), ("fosforo", spec["fosforo"])):
            if lim and pd.notna(r[c]):
                rr.append(float(r[c]) / float(lim))
        return max(rr) if rr else 0.90  # sin lab: prioridad media-baja

    d["score"] = d.apply(_score, axis=1)
    d = d.sort_values(["score", "litros_actual"], ascending=[True, False])
    out, acum = [], 0.0
    for _, r in d.iterrows():
        if acum >= litros_obj:
            break
        toma = min(float(r["litros_actual"]), litros_obj - acum)
        if toma < min_l * 0.2:
            continue
        out.append({"Tanque": r["etq"], "Litros": round(toma, 0),
                    "Acidez %": _NAN, "Fósforo ppm": _NAN, "Azufre ppm": _NAN, "AyS %": _NAN})
        acum += toma
    if not out:
        return pd.DataFrame(), "No se pudo armar una mezcla con el stock disponible."
    falta = litros_obj - acum
    msg = (f"Propuesta con {len(out)} tanque(s) — {acum:,.0f} L."
           + (f" Faltan {falta:,.0f} L: no alcanza el stock del producto." if falta > 1 else ""))
    return pd.DataFrame(out), msg


# ------------------------------------------------------------------ formulación por mezcla

# Productos que no salen de un tanque homogéneo sino de una mezcla deliberada.
# AG-E es el caso real de la planta: se arma en el tanque "Formulación AG-E" (FORM-AG-E)
# combinando ARE (producción propia, acidez alta, barato) con AFE (comprado, acidez baja,
# caro). El AFE entra sólo para bajar la acidez hasta la especificación de venta: cuanto
# menos AFE se necesite, más barata sale la tonelada despachada.
MEZCLAS = {
    "AG-E": {
        "tanque": "FORM-AG-E",
        "base": ("ARE-B", "ARE-A", "ARE-A-ANIMAL"),
        "corrector": ("AFE-S", "AFE-SG", "AFE-AL", "AFE-G", "AFE-P"),
        "base_lbl": "ARE — base propia (acidez alta, costo bajo)",
        "corr_lbl": "AFE — corrector comprado (acidez baja, costo alto)",
        "nota": "El AG-E de exportación se formula mezclando ARE con AFE. El ARE es producción "
                "propia y sale más barato, pero tiene la acidez muy por encima de la spec; el AFE "
                "comprado la baja. La mezcla óptima es la que usa **la mayor proporción de ARE "
                "que todavía cumpla la especificación**.",
    },
}
DENS_DEF = 0.91


def _familia(prod_cod):
    """Productos admitidos en un despacho de prod_cod: él mismo + sus componentes de mezcla."""
    cod = str(prod_cod or "").strip().upper()
    m = MEZCLAS.get(cod)
    if not m:
        return [cod], None
    return [cod] + list(m["base"]) + list(m["corrector"]), m


def _a_usd_t(precio, unidad, moneda, tc, dens):
    """Normaliza cualquier precio de dim_precio_ref a USD por tonelada."""
    try:
        p = float(precio)
    except Exception:
        return None
    if p <= 0:
        return None
    u = str(unidad or "").upper()
    mo = str(moneda or "").upper()
    if mo == "ARS":
        if not tc or tc <= 0:
            return None
        p = p / float(tc)
    elif mo != "USD":
        return None
    if u == "TN":
        return p
    if u == "KG":
        return p * 1000.0
    if u == "L":
        d = float(dens) if dens else DENS_DEF
        return p * 1000.0 / max(d, 0.01)
    return None


def _precios(cat):
    """codigo_producto -> USD/t, resolviendo dim_precio_map contra dim_precio_ref."""
    try:
        ref = cat("SELECT codigo, precio, unidad, moneda FROM produccion.dim_precio_ref")
        mapa = cat("SELECT codigo_producto, codigo_precio, densidad_ref "
                   "FROM produccion.dim_precio_map")
    except Exception:
        return {}
    if ref is None or ref.empty or mapa is None or mapa.empty:
        return {}
    tc = None
    _t = ref[ref["codigo"].astype(str).str.upper() == "TC_USD"]
    if not _t.empty:
        try:
            tc = float(_t.iloc[0]["precio"])
        except Exception:
            tc = None
    ix = ref.set_index(ref["codigo"].astype(str).str.upper())
    out = {}
    for _, r in mapa.iterrows():
        cp = str(r.get("codigo_precio") or "").upper()
        if cp not in ix.index:
            continue
        f = ix.loc[cp]
        v = _a_usd_t(f["precio"], f["unidad"], f["moneda"], tc, r.get("densidad_ref"))
        if v is not None:
            out[str(r["codigo_producto"]).upper()] = v
    return out


def _pool(df):
    """Agrega un conjunto de tanques en un solo 'componente' virtual.

    Reparte proporcional al stock disponible, así el promedio ponderado que se calcula acá
    es exactamente el de la mezcla que se va a cargar (no una aproximación).
    """
    if df is None or df.empty:
        return None
    d = df.copy()
    d["_l"] = pd.to_numeric(d["litros_actual"], errors="coerce").fillna(0.0)
    d = d[d["_l"] > 0]
    if d.empty:
        return None
    d["_d"] = pd.to_numeric(d["densidad"], errors="coerce").fillna(DENS_DEF)
    d["_kg"] = d["_l"] * d["_d"]
    kg = float(d["_kg"].sum())
    lit = float(d["_l"].sum())
    p = {"litros": lit, "kg": kg, "dens": (kg / lit if lit > 0 else DENS_DEF), "tks": d}
    for _lbl, _c in _PARAMS:
        s = d[pd.notna(d[_c])]
        if s.empty or float(s["_kg"].sum()) <= 0:
            p[_c] = None
            p[_c + "_cob"] = 0.0
        else:
            p[_c] = float((pd.to_numeric(s[_c]) * s["_kg"]).sum() / float(s["_kg"].sum()))
            p[_c + "_cob"] = 100.0 * float(s["_kg"].sum()) / kg
    return p


def _x_optimo(pb, pc, spec, margen_pct=0.0):
    """Fracción MÁSICA de base (ARE) máxima que sigue cumpliendo todas las specs.

    Para cada parámetro: v(x) = x*vb + (1-x)*vc <= limite  =>  x <= (limite - vc)/(vb - vc).
    Si la base ya cumple sola, ese parámetro no limita. Si ni el corrector puro cumple, no
    hay mezcla posible con estos dos tanques. Devuelve (x, limitante, detalle_por_parametro).
    """
    xs, det, bloqueo = [], [], None
    for lbl, c in _PARAMS:
        lim = spec.get({"acidez": "acidez", "agua_sedimento": "ays",
                        "azufre": "azufre", "fosforo": "fosforo"}[c])
        vb, vc = pb.get(c), pc.get(c)
        if not lim or vb is None or vc is None:
            det.append({"Parámetro": lbl, "Base": vb, "Corrector": vc, "Límite": lim,
                        "Máx. base %": None, "Nota": "sin dato de lab o sin límite"})
            continue
        lim = float(lim) * (1.0 - float(margen_pct) / 100.0)
        if vb <= lim:
            det.append({"Parámetro": lbl, "Base": vb, "Corrector": vc, "Límite": lim,
                        "Máx. base %": 100.0, "Nota": "la base sola ya cumple"})
            continue
        if vc >= lim:
            bloqueo = lbl
            det.append({"Parámetro": lbl, "Base": vb, "Corrector": vc, "Límite": lim,
                        "Máx. base %": 0.0, "Nota": "ni el corrector puro cumple"})
            xs.append(0.0)
            continue
        x = (lim - vc) / (vb - vc)
        x = max(0.0, min(1.0, x))
        xs.append(x)
        det.append({"Parámetro": lbl, "Base": vb, "Corrector": vc, "Límite": lim,
                    "Máx. base %": 100.0 * x, "Nota": ""})
    if not xs:
        return None, None, pd.DataFrame(det), bloqueo
    x = min(xs)
    lim_lbl = None
    for d in det:
        if d["Máx. base %"] is not None and abs(d["Máx. base %"] / 100.0 - x) < 1e-9:
            lim_lbl = d["Parámetro"]
            break
    return x, lim_lbl, pd.DataFrame(det), bloqueo


def _litros_por_fraccion(x, dens_b, dens_c, litros_tot):
    """Litros de cada lado para una fracción MÁSICA x de base y un total en LITROS.

    No se puede repartir los litros por x directamente: x es masa y las densidades difieren
    (ARE 0,88 vs AFE 0,89). Resolviendo el sistema masa/volumen:
        Lb = T * x*dc / ((1-x)*db + x*dc)
    """
    db = float(dens_b or DENS_DEF)
    dc = float(dens_c or DENS_DEF)
    den = (1.0 - x) * db + x * dc
    if den <= 0:
        return 0.0, float(litros_tot)
    lb = float(litros_tot) * x * dc / den
    return lb, float(litros_tot) - lb


def _reparto(pool, litros):
    """Reparte litros entre los tanques del pool, proporcional al stock de cada uno."""
    d = pool["tks"]
    tot = float(d["_l"].sum())
    out = []
    if tot <= 0 or litros <= 0:
        return out
    for _, r in d.iterrows():
        L = float(litros) * float(r["_l"]) / tot
        if L < 1:
            continue
        out.append({"Tanque": r["etq"], "Litros": round(L, 0),
                    "Acidez %": _NAN, "Fósforo ppm": _NAN, "Azufre ppm": _NAN, "AyS %": _NAN})
    return out


def _p_pool(pool, precios):
    """USD/t del pool, ponderado por kg según dim_precio_map."""
    num, kg = 0.0, 0.0
    for _, r in pool["tks"].iterrows():
        v = precios.get(str(r.get("producto_principal") or "").upper())
        if v is None:
            continue
        num += float(v) * float(r["_kg"])
        kg += float(r["_kg"])
    return (num / kg) if kg > 0 else None


def _mezclar(pb, pc, x):
    """Valores de laboratorio de la mezcla para una fracción másica x de base."""
    out = {}
    for _lbl, c in _PARAMS:
        vb, vc = pb.get(c), pc.get(c)
        out[c] = None if (vb is None or vc is None) else (x * vb + (1.0 - x) * vc)
    return out


def _bloque_mezcla(cat, tks, prod_cod, prod_lbl, lit_obj, spec, ss):
    """Sección 2b: arma el producto mezclando base + corrector y calcula la proporción óptima."""
    fam, m = _familia(prod_cod)
    if not m:
        return
    st.markdown("#### 2b · Formulación de **%s** (tanque %s) — cuánto ARE y cuánto AFE"
                % (prod_lbl, m["tanque"]))
    st.info(m["nota"])

    _up = tks["producto_principal"].astype(str).str.strip().str.upper()
    _lt = tks["litros_actual"].fillna(0)
    tb = tks[_up.isin([c.upper() for c in m["base"]]) & (_lt > 0)].copy()
    tc_ = tks[_up.isin([c.upper() for c in m["corrector"]]) & (_lt > 0)].copy()
    if tb.empty or tc_.empty:
        st.warning("Para formular %s hacen falta tanques con stock de los dos lados: base (%s) y "
                   "corrector (%s). Hoy falta uno de los dos, así que sólo se puede despachar de "
                   "tanques que ya tengan %s hecho."
                   % (prod_lbl, ", ".join(m["base"]), ", ".join(m["corrector"]), prod_lbl))
        return
    tb = tb.sort_values("litros_actual", ascending=False)
    tc_ = tc_.sort_values("litros_actual", ascending=False)

    c1, c2 = st.columns(2)
    sb = c1.multiselect(m["base_lbl"], tb["etq"].tolist(), default=tb["etq"].tolist()[:2],
                        key="dsp_mz_b")
    sc = c2.multiselect(m["corr_lbl"], tc_["etq"].tolist(), default=tc_["etq"].tolist()[:2],
                        key="dsp_mz_c")
    if not sb or not sc:
        st.caption("Elegí al menos un tanque de cada lado para ver el cálculo.")
        return
    pb = _pool(tb[tb["etq"].isin(sb)])
    pc = _pool(tc_[tc_["etq"].isin(sc)])
    if pb is None or pc is None:
        st.warning("Los tanques elegidos no tienen stock medido.")
        return

    precios = _precios(cat)
    _pb0 = _p_pool(pb, precios)
    _pc0 = _p_pool(pc, precios)
    q1, q2, q3 = st.columns(3)
    margen = q1.number_input("Margen de seguridad (%)", min_value=0.0, max_value=50.0,
                             value=float(ss.get("dsp_mz_marg", 10.0)), step=5.0, key="dsp_mz_marg",
                             help="Apunta a quedar ese % por debajo del máximo de cada spec. "
                                  "Cubre el error de medición del lab y la heterogeneidad del tanque.")
    usd_b = q2.number_input("USD/t del ARE (costo)", min_value=0.0,
                            value=float(round(_pb0 or 0.0, 1)), step=10.0, key="dsp_mz_pb",
                            help="Prellenado con el precio de la tabla de referencia. Ojo: el ARE-B "
                                 "está cargado a precio de VENTA, no a costo de producción. "
                                 "Pisalo con el costo real para que el ahorro tenga sentido.")
    usd_c = q3.number_input("USD/t del AFE (compra)", min_value=0.0,
                            value=float(round(_pc0 or 0.0, 1)), step=10.0, key="dsp_mz_pc")

    x_opt, lim_lbl, det, bloqueo = _x_optimo(pb, pc, spec, margen)
    if bloqueo:
        st.error("Ni el corrector puro cumple **%s**: con estos tanques no hay mezcla que dé "
                 "la especificación. Revisá el límite o elegí otro tanque de AFE." % bloqueo)
    if x_opt is None:
        st.warning("No hay datos de laboratorio suficientes en los tanques elegidos para calcular "
                   "la proporción. Cargá el lab de acidez de los dos lados.")
        return

    r1, r2 = st.columns([3, 1])
    x = r1.number_input("% de ARE a usar (sobre masa)", min_value=0.0, max_value=100.0,
                        value=float(round(x_opt * 100.0, 1)), step=0.5, key="dsp_mz_x",
                        help="Arranca en el óptimo calculado. Podés bajarlo para ir más "
                             "conservador; subirlo rompe la spec.") / 100.0
    if r2.button("↺ Volver al óptimo", use_container_width=True):
        ss.pop("dsp_mz_x", None)
        st.rerun()

    Lb, Lc = _litros_por_fraccion(x, pb["dens"], pc["dens"], lit_obj)
    kg_tot = Lb * pb["dens"] + Lc * pc["dens"]
    mez = _mezclar(pb, pc, x)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ARE", "%.1f %%" % (100 * x), "%s L" % format(Lb, ",.0f"))
    k2.metric("AFE", "%.1f %%" % (100 * (1 - x)), "%s L" % format(Lc, ",.0f"))
    _ac = mez.get("acidez")
    k3.metric("Acidez resultante", "—" if _ac is None else "%.2f %%" % _ac,
              None if _ac is None else "%+.2f vs spec %.2f" % (_ac - spec["acidez"], spec["acidez"]),
              delta_color="inverse")
    k4.metric("Óptimo / limitante", "%.1f %% ARE" % (100 * x_opt), lim_lbl or "sin límite activo",
              delta_color="off")

    if usd_b > 0 and usd_c > 0:
        cm = x * usd_b + (1 - x) * usd_c
        ahorro = (usd_c - cm) * kg_tot / 1000.0
        p1, p2, p3 = st.columns(3)
        p1.metric("Costo de la mezcla", "%s USD/t" % format(cm, ",.0f"))
        p2.metric("Contra 100 % AFE", "%s USD/t" % format(usd_c, ",.0f"),
                  "%s USD/t" % format(cm - usd_c, "+,.0f"), delta_color="inverse")
        p3.metric("Ahorro del despacho", "%s USD" % format(ahorro, ",.0f"),
                  help="Diferencia contra comprar todo AFE, sobre %s t formuladas."
                       % format(kg_tot / 1000.0, ",.1f"))
        if usd_b >= usd_c:
            st.warning("El ARE está cargado más caro que el AFE (%s vs %s USD/t). Eso pasa porque "
                       "en la tabla de precios el ARE-B figura a **precio de venta** y el AFE a "
                       "**precio de compra**: son cosas distintas. Mientras no pises el USD/t del "
                       "ARE con el costo de producción, el ahorro que ves acá está mal y el cálculo "
                       "sugiere lo contrario de lo que conviene."
                       % (format(usd_b, ",.0f"), format(usd_c, ",.0f")))

    _falta = []
    if Lb > pb["litros"] + 1:
        _falta.append("ARE: pide %s L y hay %s L" % (format(Lb, ",.0f"), format(pb["litros"], ",.0f")))
    if Lc > pc["litros"] + 1:
        _falta.append("AFE: pide %s L y hay %s L" % (format(Lc, ",.0f"), format(pc["litros"], ",.0f")))
    if _falta:
        _max = lit_obj
        if Lb > 0 and pb["litros"] < Lb:
            _max = min(_max, lit_obj * pb["litros"] / Lb)
        if Lc > 0 and pc["litros"] < Lc:
            _max = min(_max, lit_obj * pc["litros"] / Lc)
        st.error("No alcanza el stock para el objetivo con esta proporción — " + " · ".join(_falta) +
                 ". Con lo que hay se pueden formular hasta **%s L** (%s %% del objetivo)."
                 % (format(_max, ",.0f"), format(100 * _max / lit_obj if lit_obj else 0, ",.0f")))

    with st.expander("🔎 De dónde sale la proporción", expanded=False):
        st.caption("Cada parámetro impone su propio techo de ARE: como la mezcla promedia por masa, "
                   "`valor = x·base + (1−x)·corrector`, el máximo de ARE que cumple es "
                   "`x ≤ (límite − corrector) / (base − corrector)`. Se toma el más exigente de los "
                   "cuatro. El límite mostrado ya tiene aplicado el margen de seguridad.")
        _dd = det.copy()
        for _c in ["Base", "Corrector", "Límite", "Máx. base %"]:
            _dd[_c] = pd.to_numeric(_dd[_c], errors="coerce").round(2)
        st.dataframe(_dd, hide_index=True, use_container_width=True)
        _cob = [lbl for lbl, c in _PARAMS if pb.get(c + "_cob", 0) < 99 or pc.get(c + "_cob", 0) < 99]
        if _cob:
            st.caption("⚠️ Lab incompleto en parte de la masa para: " + ", ".join(_cob) +
                       ". El promedio ignora esa masa, así que puede quedar optimista.")

    if st.button("🎯 Usar esta mezcla en la formulación", type="primary",
                 help="Carga las líneas de abajo repartiendo los litros entre los tanques elegidos, "
                      "proporcional al stock de cada uno."):
        ss["dsp_lineas"] = pd.DataFrame(_reparto(pb, Lb) + _reparto(pc, Lc))
        st.rerun()
    st.divider()


# ------------------------------------------------------------------ persistencia

def _guardar(conectar, USR, cab, res, id_despacho=None):
    with conectar(USR["id_usuario"]) as (conn, _a):
        with conn.cursor() as cur:
            if id_despacho:
                cur.execute(
                    "UPDATE produccion.fact_despacho SET titulo=%s, destino=%s, cliente=%s, "
                    "producto_codigo=%s, tipo_carga=%s, fecha_despacho=%s, semana_iso=%s, anio=%s, "
                    "n_contenedores=%s, litros_por_contenedor=%s, spec_acidez_max=%s, spec_ays_max=%s, "
                    "spec_azufre_max=%s, spec_fosforo_max=%s, estado=%s, observaciones=%s, "
                    "actualizado_en=now() WHERE id_despacho=%s",
                    (cab["titulo"], cab["destino"], cab["cliente"], cab["producto_codigo"],
                     cab["tipo_carga"], cab["fecha"], cab["semana"], cab["anio"],
                     cab["n_cont"], cab["l_cont"], cab["sp_ac"], cab["sp_ays"], cab["sp_az"],
                     cab["sp_fos"], cab["estado"], cab["obs"], int(id_despacho)))
                cur.execute("DELETE FROM produccion.fact_despacho_linea WHERE id_despacho=%s",
                            (int(id_despacho),))
                _id = int(id_despacho)
            else:
                cur.execute(
                    "INSERT INTO produccion.fact_despacho (titulo,destino,cliente,producto_codigo,"
                    "tipo_carga,fecha_despacho,semana_iso,anio,n_contenedores,litros_por_contenedor,"
                    "spec_acidez_max,spec_ays_max,spec_azufre_max,spec_fosforo_max,estado,observaciones,"
                    "creado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING id_despacho",
                    (cab["titulo"], cab["destino"], cab["cliente"], cab["producto_codigo"],
                     cab["tipo_carga"], cab["fecha"], cab["semana"], cab["anio"],
                     cab["n_cont"], cab["l_cont"], cab["sp_ac"], cab["sp_ays"], cab["sp_az"],
                     cab["sp_fos"], cab["estado"], cab["obs"], USR.get("nombre")))
                _id = int(cur.fetchone()[0])
            for _, r in res.iterrows():
                cur.execute(
                    "INSERT INTO produccion.fact_despacho_linea (id_despacho,orden,id_tanque,"
                    "producto_codigo,litros,densidad,acidez,fosforo,azufre,agua_sedimento,lab_origen) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (_id, int(r["orden"]), int(r["id_tanque"]), (r["Producto"] or None),
                     float(r["Litros"]), float(r["Densidad"]),
                     _n(r.get("Acidez %")), _n(r.get("Fósforo ppm")), _n(r.get("Azufre ppm")),
                     _n(r.get("AyS %")),
                     "MANUAL" if "manual" in {r.get("Acidez %_src"), r.get("Fósforo ppm_src"),
                                              r.get("Azufre ppm_src"), r.get("AyS %_src")} else "TANQUE"))
    return _id


def _n(v):
    return float(v) if (v is not None and pd.notna(v)) else None


def _excel(cab, res, spec):
    """Planilla de formulación equivalente a la de la directora, con los totales bien calculados."""
    buf = io.BytesIO()
    tot_l = float(res["Litros"].sum()) if not res.empty else 0.0
    tot_kg = float(res["kg"].sum()) if not res.empty else 0.0
    d = res.copy()
    if not d.empty:
        d["%"] = 100.0 * d["Litros"] / tot_l if tot_l else 0.0
    cols = ["Producto", "Acidez %", "Fósforo ppm", "Azufre ppm", "TN", "Litros", "%", "Tanque"]
    d = d.reindex(columns=cols)
    tot = {"Producto": "TOTAL", "TN": tot_kg / 1000.0, "Litros": tot_l, "%": 100.0 if tot_l else 0.0,
           "Tanque": ""}
    for c, k in (("Acidez %", "Acidez %"), ("Fósforo ppm", "Fósforo ppm"), ("Azufre ppm", "Azufre ppm")):
        v, _ = _ponderar(res, k)
        tot[c] = v
    d = pd.concat([d, pd.DataFrame([tot])], ignore_index=True)
    enc = pd.DataFrame([
        ["DESPACHO", cab["titulo"]], ["DESTINO", cab["destino"]], ["CLIENTE", cab["cliente"]],
        ["PRODUCTO", cab["producto_codigo"]], ["TIPO DE CARGA", cab["tipo_carga"]],
        ["FECHA", str(cab["fecha"] or "")], ["SEMANA", cab["semana"]],
        ["Nº CONTENEDORES", cab["n_cont"]], ["LITROS POR CONTENEDOR", cab["l_cont"]],
        ["LITROS OBJETIVO", cab["n_cont"] * cab["l_cont"]],
        ["LITROS FORMULADOS", tot_l], ["TN FORMULADAS", round(tot_kg / 1000.0, 2)],
        ["SPEC Acidez % (máx)", spec["acidez"]], ["SPEC AyS % (máx)", spec["ays"]],
        ["SPEC Azufre ppm (máx)", spec["azufre"]], ["SPEC Fósforo ppm (máx)", spec["fosforo"]],
    ], columns=["Campo", "Valor"])
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        enc.to_excel(w, sheet_name="Despacho", index=False, startrow=0)
        d.to_excel(w, sheet_name="Despacho", index=False, startrow=len(enc) + 3)
    return buf.getvalue()


# ------------------------------------------------------------------ UI

def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#0f766e,#0ea5e9);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🚢 Despachos</div>"
        "<div style='color:#e0f2fe;font-size:.88rem;margin-top:3px'>Armá la formulación de un despacho "
        "combinando tanques: los litros, la densidad y el laboratorio salen del sistema y se controla "
        "la especificación antes de confirmar.</div></div>", unsafe_allow_html=True)

    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return

    _opts = ["🧪 Armar / editar despacho", "🎟️ Tickets de portería", "📋 Despachos cargados"]
    try:
        _t = st.segmented_control("Vista", _opts, default=_opts[0], key="dsp_tab_sc",
                                  label_visibility="collapsed")
    except Exception:
        _t = st.radio("Vista", _opts, horizontal=True, key="dsp_tab")
    _t = _t or _opts[0]
    st.write("")

    if _t.startswith("📋"):
        _listado(USR, cat, conectar)
    elif _t.startswith("🎟️"):
        _tickets(USR, cat, conectar)
    else:
        _armar(USR, cat, conectar)


def _armar(USR, cat, conectar):
    ss = st.session_state
    tks = _tanques(cat)
    if tks.empty:
        st.error("No se pudieron leer los tanques.")
        return
    prods = _productos(cat)

    # ---------- 1 · Cabecera ----------
    st.markdown("#### 1 · Datos del despacho")
    hoy = _dt.date.today()
    c1, c2, c3 = st.columns([2, 1.4, 1])
    titulo = c1.text_input("Título / referencia", value=ss.get("dsp_titulo", ""),
                           placeholder="DESPACHO FLEX 07/07", key="dsp_titulo")
    destino = c2.text_input("Destino", value=ss.get("dsp_destino", ""),
                            placeholder="Rotterdam", key="dsp_destino")
    cliente = c3.text_input("Cliente", value=ss.get("dsp_cliente", ""), key="dsp_cliente")

    c1, c2, c3, c4 = st.columns(4)
    _pl = prods["producto"].tolist() if not prods.empty else []
    _pcod = dict(zip(prods["producto"], prods["codigo_producto"])) if not prods.empty else {}
    _def_p = _pl.index("AFE-S") if "AFE-S" in _pl else 0
    prod_lbl = c1.selectbox("Producto a despachar", _pl, index=_def_p, key="dsp_prod",
                            help="Rótulo oficial. Define el filtro de tanques en la sugerencia.")
    prod_cod = _pcod.get(prod_lbl, prod_lbl)
    tipo = c2.selectbox("Tipo de carga", TIPOS_CARGA, key="dsp_tipo")
    fecha = c3.date_input("Fecha de despacho", value=ss.get("dsp_fecha", hoy), key="dsp_fecha")
    semana = int(pd.Timestamp(fecha).isocalendar().week)
    c4.metric("Semana ISO", f"S{semana}")

    c1, c2, c3, c4 = st.columns(4)
    n_cont = c1.number_input("Nº de contenedores", min_value=1, max_value=200,
                             value=int(ss.get("dsp_ncont", 14)), step=1, key="dsp_ncont")
    l_cont = c2.number_input("Litros por contenedor", min_value=100.0, max_value=100000.0,
                             value=float(ss.get("dsp_lcont", 26000.0)), step=500.0, key="dsp_lcont")
    lit_obj = float(n_cont) * float(l_cont)
    _dens_p = None
    if not prods.empty:
        _r = prods[prods["codigo_producto"] == prod_cod]
        if not _r.empty and pd.notna(_r.iloc[0]["densidad_g_ml"]):
            _dens_p = float(_r.iloc[0]["densidad_g_ml"])
    c3.metric("Litros objetivo", f"{lit_obj:,.0f} L")
    c4.metric("TN objetivo aprox.", f"{lit_obj * (_dens_p or 0.91) / 1000:,.1f} t",
              help=f"Litros objetivo × densidad {(_dens_p or 0.91):.2f} kg/L. "
                   "La planilla vieja mostraba litros bajo el rótulo 'TN a entregar'.")

    with st.expander("📐 Especificación de venta (máximos)", expanded=True):
        s1, s2, s3, s4 = st.columns(4)
        sp_ac = s1.number_input("Acidez % máx", min_value=0.0, value=float(ss.get("dsp_spac", SPEC_DEFAULT["acidez"])),
                                step=0.5, key="dsp_spac")
        sp_ays = s2.number_input("AyS % máx", min_value=0.0, value=float(ss.get("dsp_spays", SPEC_DEFAULT["ays"])),
                                 step=0.5, key="dsp_spays")
        sp_az = s3.number_input("Azufre ppm máx", min_value=0.0, value=float(ss.get("dsp_spaz", SPEC_DEFAULT["azufre"])),
                                step=5.0, key="dsp_spaz")
        sp_fos = s4.number_input("Fósforo ppm máx", min_value=0.0, value=float(ss.get("dsp_spfos", SPEC_DEFAULT["fosforo"])),
                                 step=10.0, key="dsp_spfos")
    spec = {"acidez": sp_ac, "ays": sp_ays, "azufre": sp_az, "fosforo": sp_fos}

    # ---------- 2 · Tanques del producto ----------
    # Para productos de formulación (AG-E) el universo de tanques no es sólo el del producto
    # final: también entran los componentes con los que se arma (ARE + AFE).
    _fam, _mz = _familia(prod_cod)
    if _mz:
        st.markdown(f"#### 2 · Tanques de **{prod_lbl}** y de sus componentes")
        st.caption("**%s** se puede despachar de un tanque que ya lo tenga hecho, o formularlo en "
                   "el momento mezclando %s + %s. Por eso acá aparecen los tanques de los tres."
                   % (prod_lbl, _mz["base"][0].split("-")[0], _mz["corrector"][0].split("-")[0]))
    else:
        st.markdown(f"#### 2 · Tanques con **{prod_lbl}**")
    _tp = tks[tks["producto_principal"].astype(str).str.strip().str.upper()
              .isin([c.upper() for c in _fam])].copy()
    if _tp.empty:
        st.error(f"No hay ningún tanque activo con producto **{prod_lbl}** ({prod_cod}). "
                 "Revisá el producto principal de los tanques en el panel de tanques.")
        return

    _con = _tp[_tp["litros_actual"].fillna(0) > 0].copy()
    if _con.empty:
        st.error(f"Hay tanques de **{prod_lbl}** pero ninguno con stock medido. "
                 "Cargá las mediciones de nivel antes de armar el despacho.")
        return
    _sin_lab = _con[_con.apply(lambda r: len(_faltan_lab(r)) > 0, axis=1)]
    k1, k2, k3 = st.columns(3)
    k1.metric("Tanques con stock", f"{len(_con)}")
    k2.metric("Stock disponible", f"{_con['litros_actual'].fillna(0).sum():,.0f} L")
    k3.metric("Con lab completo", f"{len(_con) - len(_sin_lab)} de {len(_con)}")

    if not _sin_lab.empty:
        _det = []
        for _, r in _sin_lab.iterrows():
            _f = _faltan_lab(r)
            _det.append(f"**{r['nombre']}** ({r['litros_actual']:,.0f} L) → falta {', '.join(_f)}"
                        if pd.notna(r["litros_actual"]) else f"**{r['nombre']}** → falta {', '.join(_f)}")
        st.error("🧪 **Faltan análisis de laboratorio.** Estos tanques no tienen todos los parámetros "
                 "cargados, así que no se pueden verificar contra la especificación:\n\n- "
                 + "\n- ".join(_det)
                 + "\n\nPedile al laboratorio que los cargue antes de armar el despacho. Si igual los usás, "
                 "el promedio ponderado ignora esa masa y puede quedar **optimista**.")

    try:
        _viejos = _con[pd.notna(_con["lab_actualizado_en"])].copy()
        if not _viejos.empty:
            _ts = pd.to_datetime(_viejos["lab_actualizado_en"], errors="coerce")
            if getattr(_ts.dt, "tz", None) is not None:
                _ts = _ts.dt.tz_localize(None)
            _viejos["_dias"] = (pd.Timestamp.now() - _ts).dt.days
            _v = _viejos[_viejos["_dias"] > 30]
            if not _v.empty:
                st.warning("⏳ Laboratorio desactualizado (>30 días): " +
                           ", ".join(f"{r['nombre']} ({int(r['_dias'])} d)" for _, r in _v.iterrows()))
    except Exception:
        pass

    with st.expander("Ver laboratorio por tanque", expanded=False):
        _lt = _con.rename(columns={"nombre": "Tanque", "sector": "Sector", "litros_actual": "Disp. (L)",
                                   "densidad": "Densidad", "acidez": "Acidez %", "fosforo": "Fósforo ppm",
                                   "azufre": "Azufre ppm", "agua_sedimento": "AyS %",
                                   "lab_actualizado_en": "Lab del"})
        st.dataframe(_lt[["Tanque", "Sector", "Disp. (L)", "Densidad", "Acidez %", "Fósforo ppm",
                          "Azufre ppm", "AyS %", "Lab del"]],
                     hide_index=True, use_container_width=True,
                     column_config={"Disp. (L)": st.column_config.NumberColumn(format="%.0f"),
                                    "Lab del": st.column_config.DatetimeColumn(format="DD/MM/YY")})

    if _mz:
        _bloque_mezcla(cat, tks, prod_cod, prod_lbl, lit_obj, spec, ss)

    # ---------- 3 · Formulación ----------
    st.markdown("#### 3 · Formulación por tanque")
    ca, cb, cc = st.columns([1, 1, 2.4])
    if ca.button("🎯 Sugerir mezcla", use_container_width=True,
                 help="Propone tanques del producto elegido, priorizando los de mayor margen contra la spec."):
        _sug, _msg = _sugerir(tks, prod_cod, lit_obj, spec)
        if _sug.empty:
            cc.warning(_msg)
        else:
            ss["dsp_lineas"] = _sug
            st.rerun()
    if cb.button("🗑️ Vaciar", use_container_width=True):
        ss["dsp_lineas"] = _base_vacia(_COLS_ED)
        st.rerun()
    pisar = cc.checkbox("✏️ Pisar valores de laboratorio a mano", key="dsp_pisar",
                        help="Sólo si el lab te pasó un valor que todavía no está en el sistema. "
                             "Por defecto los parámetros salen del tanque.")
    _cols = _COLS_ED if pisar else _COLS_MIN

    base = ss.get("dsp_lineas")
    if base is None or not isinstance(base, pd.DataFrame):
        base = _base_vacia(_COLS_ED)
    base = base.reindex(columns=_cols)
    base["Tanque"] = base["Tanque"].astype("object")
    for _c in _cols[1:]:
        base[_c] = pd.to_numeric(base[_c], errors="coerce")

    _o = _con["etq"].tolist()
    _cfg = {
        "Tanque": st.column_config.SelectboxColumn("Tanque", options=_o, width="large", required=True,
                                                   help=("Tanques con stock de " + str(prod_lbl) +
                                                         (" o de sus componentes (" +
                                                          ", ".join(_fam[1:]) + ")." if _mz else "."))),
        "Litros": st.column_config.NumberColumn("Litros a cargar", min_value=0.0, step=500.0,
                                                format="%.0f"),
    }
    if pisar:
        _cfg.update({
            "Acidez %": st.column_config.NumberColumn("Acidez % (pisar)", format="%.2f",
                                                      help="Vacío = usa el último lab del tanque."),
            "Fósforo ppm": st.column_config.NumberColumn("Fósforo ppm (pisar)", format="%.1f"),
            "Azufre ppm": st.column_config.NumberColumn("Azufre ppm (pisar)", format="%.1f"),
            "AyS %": st.column_config.NumberColumn("AyS % (pisar)", format="%.2f"),
        })
    ed = st.data_editor(base, num_rows="dynamic", hide_index=True, use_container_width=True,
                        key=("dsp_ed_p" if pisar else "dsp_ed"), column_config=_cfg)
    st.caption("Elegí el tanque y los litros. Producto, densidad, acidez, fósforo, azufre y AyS "
               "se completan solos con el último análisis del tanque.")

    res = _resolver(ed, tks)
    if res.empty:
        st.info("Cargá al menos una línea con tanque y litros para ver los cálculos.")
        return

    # ---------- 4 · Resultado ----------
    st.markdown("#### 4 · Resultado de la mezcla")
    tot_l = float(res["Litros"].sum())
    tot_kg = float(res["kg"].sum())
    dif = tot_l - lit_obj
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Litros formulados", f"{tot_l:,.0f} L", f"{dif:+,.0f} L vs objetivo")
    m2.metric("Toneladas", f"{tot_kg/1000:,.2f} t")
    m3.metric("Cobertura", f"{(100*tot_l/lit_obj if lit_obj else 0):,.1f} %")
    m4.metric("Tanques usados", f"{len(res)}")

    st.markdown("**Cumplimiento de especificación** (promedios ponderados por kg)")
    ok = _panel_specs(res, spec)

    _d = res.copy()
    _d["Litros"] = _d["Litros"].round(0)
    _d["% del total"] = (100.0 * _d["Litros"] / tot_l).round(2)
    _d["TN"] = _d["TN"].round(2)
    _show = _d[["Tanque", "Producto", "Litros", "% del total", "Densidad", "TN",
                "Acidez %", "Fósforo ppm", "Azufre ppm", "AyS %", "Disp. (L)", "Restante (L)"]]
    st.dataframe(_show, hide_index=True, use_container_width=True,
                 column_config={"Litros": st.column_config.NumberColumn(format="%.0f"),
                                "Disp. (L)": st.column_config.NumberColumn(format="%.0f"),
                                "Restante (L)": st.column_config.NumberColumn(format="%.0f")})

    # ---------- 4 · Avisos ----------
    avisos = []
    _ex = res[res["Excede"]]
    if not _ex.empty:
        avisos.append("Estos tanques no tienen tanto stock: " +
                      ", ".join(f"{r['Tanque']} (pide {r['Litros']:,.0f} L, hay {r['Disp. (L)']:,.0f} L)"
                                for _, r in _ex.iterrows()))
    if abs(dif) > max(500.0, 0.02 * lit_obj):
        avisos.append(f"La formulación difiere del objetivo en {dif:+,.0f} L "
                      f"({100*dif/lit_obj:+.1f}%).")
    _sin = res[res[["Acidez %", "Fósforo ppm", "Azufre ppm"]].isna().any(axis=1)]
    if not _sin.empty:
        avisos.append("Sin análisis completo de laboratorio: " +
                      ", ".join(_sin["Tanque"].astype(str).tolist()) +
                      " — el promedio ponderado ignora esa masa y puede quedar optimista.")
    _multi = res["Producto"].dropna().unique().tolist()
    if len(_multi) > 1:
        _fuera = [p for p in _multi if str(p).strip().upper() not in [c.upper() for c in _fam]]
        if _mz and not _fuera:
            st.caption("ℹ️ Esto es una **formulación de %s**: combina %s. Los promedios de abajo "
                       "son los del producto que sale del tanque de mezcla."
                       % (prod_lbl, ", ".join(map(str, _multi))))
        else:
            avisos.append("La mezcla combina productos distintos: " + ", ".join(map(str, _multi)) + ".")
    if avisos:
        for a in avisos:
            st.warning(a)
    if not ok:
        st.error("La mezcla **no cumple** la especificación. Reemplazá los tanques de peor calidad "
                 "o bajá su participación antes de confirmar.")

    # ---------- 5 · Guardar ----------
    st.markdown("#### 5 · Guardar")
    g1, g2, g3 = st.columns([1.2, 1, 1.6])
    estado = g1.selectbox("Estado", ESTADOS, index=0, key="dsp_estado")
    obs = g3.text_input("Observaciones", key="dsp_obs")
    cab = {"titulo": (titulo or f"DESPACHO {tipo} {fecha:%d/%m}"), "destino": destino or None,
           "cliente": cliente or None, "producto_codigo": prod_cod, "tipo_carga": tipo,
           "fecha": fecha, "semana": semana, "anio": int(pd.Timestamp(fecha).isocalendar().year),
           "n_cont": int(n_cont), "l_cont": float(l_cont), "sp_ac": sp_ac, "sp_ays": sp_ays,
           "sp_az": sp_az, "sp_fos": sp_fos, "estado": estado, "obs": obs or None}

    if estado != "BORRADOR" and not ok:
        g2.button("💾 Guardar", disabled=True, use_container_width=True,
                  help="No cumple la spec: sólo se puede guardar como BORRADOR.")
    elif g2.button("💾 Guardar", type="primary", use_container_width=True):
        try:
            _id = _guardar(conectar, USR, cab, res, ss.get("dsp_edit_id"))
            cat.clear()
            ss["dsp_edit_id"] = None
            st.success(f"Despacho guardado (id {_id}).")
        except Exception as e:
            st.error(f"No se pudo guardar: {e}")

    st.download_button("⬇️ Descargar planilla (.xlsx)", _excel(cab, res, spec),
                       file_name=f"despacho_{fecha:%Y%m%d}_{(destino or 'SD').replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _listado(USR, cat, conectar):
    df = cat("SELECT id_despacho, titulo, destino, cliente, producto, tipo_carga, fecha_despacho, "
             "semana_iso, n_contenedores, litros_objetivo, litros_total, tn_total, pct_cubierto, "
             "acidez_pond, fosforo_pond, azufre_pond, ays_pond, spec_acidez_max, spec_fosforo_max, "
             "spec_azufre_max, spec_ays_max, estado, n_lineas, n_lineas_exceden_stock, creado_por, "
             "creado_en FROM produccion.v_despacho_resumen")
    if df is None or df.empty:
        st.info("Todavía no hay despachos cargados.")
        return
    df = df.copy()

    def _est(r):
        p = []
        for v, lim in ((r["acidez_pond"], r["spec_acidez_max"]), (r["fosforo_pond"], r["spec_fosforo_max"]),
                       (r["azufre_pond"], r["spec_azufre_max"]), (r["ays_pond"], r["spec_ays_max"])):
            if pd.notna(v) and pd.notna(lim) and float(lim) > 0:
                p.append(float(v) <= float(lim))
        return "✅" if p and all(p) else ("❌" if p else "—")

    df["Spec"] = df.apply(_est, axis=1)
    _t = df.rename(columns={"id_despacho": "ID", "titulo": "Despacho", "destino": "Destino",
                            "producto": "Producto", "tipo_carga": "Carga", "fecha_despacho": "Fecha",
                            "semana_iso": "Sem", "n_contenedores": "Cont.", "litros_total": "Litros",
                            "tn_total": "TN", "pct_cubierto": "% objetivo", "estado": "Estado",
                            "n_lineas": "Tanques", "acidez_pond": "Acidez %",
                            "fosforo_pond": "Fósforo ppm", "azufre_pond": "Azufre ppm"})
    st.dataframe(_t[["ID", "Despacho", "Fecha", "Sem", "Destino", "Producto", "Carga", "Cont.",
                     "Litros", "TN", "% objetivo", "Acidez %", "Fósforo ppm", "Azufre ppm",
                     "Spec", "Estado", "Tanques"]],
                 hide_index=True, use_container_width=True)

    st.markdown("---")
    _ids = df["id_despacho"].tolist()
    _lbl = {int(r["id_despacho"]): f"#{int(r['id_despacho'])} · {r['titulo']} · {r['destino'] or 's/destino'}"
            for _, r in df.iterrows()}
    sel = st.selectbox("Ver detalle", _ids, format_func=lambda i: _lbl.get(int(i), str(i)), key="dsp_sel")
    if sel is None:
        return
    det = cat("SELECT orden, tanque_nombre, tanque_sector, producto, litros, densidad, kg, tn, "
              "acidez, fosforo, azufre, agua_sedimento, tanque_litros_actual, litros_restantes, "
              "excede_stock FROM produccion.v_despacho_linea WHERE id_despacho=%s ORDER BY orden",
              (int(sel),))
    if det is None or det.empty:
        st.info("Ese despacho no tiene líneas cargadas.")
    else:
        _d = det.rename(columns={"orden": "#", "tanque_nombre": "Tanque", "tanque_sector": "Sector",
                                 "producto": "Producto", "litros": "Litros", "densidad": "Densidad",
                                 "kg": "kg", "tn": "TN", "acidez": "Acidez %", "fosforo": "Fósforo ppm",
                                 "azufre": "Azufre ppm", "agua_sedimento": "AyS %",
                                 "tanque_litros_actual": "Disp. hoy (L)",
                                 "litros_restantes": "Restante (L)"})
        st.dataframe(_d[["#", "Tanque", "Sector", "Producto", "Litros", "Densidad", "TN",
                         "Acidez %", "Fósforo ppm", "Azufre ppm", "AyS %", "Disp. hoy (L)",
                         "Restante (L)"]], hide_index=True, use_container_width=True)
        st.caption("*Disp. hoy* es el stock actual del tanque, no el del momento de la carga.")

    r = df[df["id_despacho"] == sel].iloc[0]
    c1, c2, c3 = st.columns([1.2, 1, 2])
    _nuevo = c1.selectbox("Cambiar estado", ESTADOS, index=ESTADOS.index(r["estado"]), key="dsp_est_up")
    if c2.button("Aplicar", use_container_width=True):
        try:
            with conectar(USR["id_usuario"]) as (conn, _a):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_despacho SET estado=%s, actualizado_en=now() "
                                "WHERE id_despacho=%s", (_nuevo, int(sel)))
                    cur.execute("SELECT count(*), coalesce(sum(kg),0)/1000.0 "
                                "FROM produccion.fact_movimiento_stock "
                                "WHERE id_despacho=%s AND origen='despacho' AND anulado IS NOT TRUE",
                                (int(sel),))
                    _nm, _tn = cur.fetchone()
            cat.clear()
            if _nm:
                st.success(f"Estado actualizado. Impacto en stock: {_nm} movimiento(s) de salida "
                           f"por {float(_tn):,.1f} t descontados de los tanques.")
            elif _nuevo in ("CONFIRMADO", "DESPACHADO"):
                st.warning("Estado actualizado, pero no se generaron movimientos de stock "
                           "(revisá que el despacho tenga líneas con tanque y litros).")
            else:
                st.success("Estado actualizado. Se revirtieron los movimientos de stock del despacho.")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo actualizar: {e}")
    if c3.checkbox("Habilitar borrado", key="dsp_del_ok") and c3.button("🗑️ Borrar despacho"):
        try:
            with conectar(USR["id_usuario"]) as (conn, _a):
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM produccion.fact_despacho WHERE id_despacho=%s", (int(sel),))
            cat.clear(); st.success("Despacho borrado."); st.rerun()
        except Exception as e:
            st.error(f"No se pudo borrar: {e}")


# ------------------------------------------------------------------ tickets de portería

_ROLES_TK = {
    "SALIDA": {
        "titulo": "🚚 Salidas a exportación (flexi / contenedor)",
        "ayuda": ("Cada ticket de salida es un camión que sale cargado a la terminal. En portería "
                  "aparecen con procedencia **EGNITRADE S.L.** y destino la terminal (SOUTHCROSS, "
                  "LIBRA, PADILLA, MERCOMAR, INTERALMAR…). El producto viene como *ACIDOS GRASOS* "
                  "genérico: el producto fino lo define el laboratorio, no portería."),
        "clases": ("SALIDA",),
    },
    "MP": {
        "titulo": "🛢️ Materia prima cargada (movimiento interno)",
        "ayuda": ("Los movimientos internos que alimentan la carga: procedencia **MOVIMIENTO INTERNO**, "
                  "destino PROPIO y el área en el campo *chofer* (EXPORTACIÓN, REACTORES, PILETAS, "
                  "BACHAS). El camión entra cargado y sale vacío, por eso el neto de portería es "
                  "negativo; acá se muestra en valor absoluto. También se listan los ingresos de "
                  "materia prima de terceros, por si querés trazar el despacho hasta la compra."),
        "clases": ("MP_EXPO", "INTERNO", "INGRESO"),
    },
}


def _tk_asignados(cat, id_despacho, rol):
    return cat("SELECT id_dt, ticket, empresa, fecha, producto, destino, patente, kg, area, "
               "nro_contenedor, precinto, observaciones, estado_validacion, familia, sin_pesada "
               "FROM produccion.v_despacho_ticket WHERE id_despacho=%s AND rol=%s "
               "ORDER BY fecha, ticket", (int(id_despacho), rol))


def _tk_candidatos(cat, clases, d1, d2, txt, familia):
    q = ("SELECT p.id_transaccion, p.ticket, p.empresa, p.fecha, p.hora, p.producto, p.destino, "
         "p.area, p.procedencia, p.patente, p.kg, p.sin_pesada, p.familia, p.observaciones "
         "FROM produccion.v_porteria_ticket p "
         "LEFT JOIN produccion.fact_despacho_ticket a ON a.id_transaccion = p.id_transaccion "
         "WHERE a.id_transaccion IS NULL AND p.clase = ANY(%s) "
         "AND p.fecha BETWEEN %s AND %s ")
    par = [list(clases), d1, d2]
    if familia and familia != "Todas":
        q += "AND p.familia=%s "
        par.append(familia)
    if txt:
        q += ("AND (p.producto ILIKE %s OR p.destino ILIKE %s OR p.area ILIKE %s "
              "OR p.patente ILIKE %s OR p.observaciones ILIKE %s OR p.ticket::text LIKE %s) ")
        par += ["%" + txt + "%"] * 5 + ["%" + txt + "%"]
    q += "ORDER BY p.fecha DESC, p.ticket DESC LIMIT 400"
    return cat(q, tuple(par))


def _tk_panel(USR, cat, conectar, cab, rol):
    spec = _ROLES_TK[rol]
    st.markdown(f"##### {spec['titulo']}")
    st.caption(spec["ayuda"])

    asg = _tk_asignados(cat, cab["id_despacho"], rol)
    if asg is not None and not asg.empty:
        _a = asg.copy()
        _a["kg"] = pd.to_numeric(_a["kg"], errors="coerce")
        _err = _a[_a["estado_validacion"].astype(str).str.startswith("ERROR")]
        _avi = _a[_a["estado_validacion"].astype(str).str.startswith("AVISO")]
        if not _err.empty:
            st.error("⛔ **Tickets AFE sin pesada cerrada:** " +
                     ", ".join(str(int(t)) for t in _err["ticket"].dropna()) +
                     ". Un AFE siempre tiene que tener pesada de entrada y de salida; si falta, el "
                     "camión sigue adentro o la balanza no cerró el ticket. Corregilo en portería "
                     "antes de confirmar el despacho.")
        if not _avi.empty:
            st.warning("⚠️ **Tickets sin pesada cerrada:** " +
                       ", ".join(str(int(t)) for t in _avi["ticket"].dropna()) +
                       ". En AG-E de formulación (AG-E + AFE-S → AG-E de exportación) puede ser "
                       "legítimo, pero esos kg no suman al control de carga.")
        _v = _a.rename(columns={"ticket": "Ticket", "fecha": "Fecha", "producto": "Producto",
                                "destino": "Destino", "area": "Área", "patente": "Patente",
                                "kg": "kg", "nro_contenedor": "Contenedor", "precinto": "Precinto",
                                "observaciones": "Obs. portería", "estado_validacion": "Chequeo"})
        _cols = ["Ticket", "Fecha", "Producto", "Destino" if rol == "SALIDA" else "Área",
                 "Patente", "kg", "Contenedor", "Precinto", "Obs. portería", "Chequeo"]
        st.dataframe(_v[_cols], hide_index=True, use_container_width=True)

        c1, c2 = st.columns([2, 1])
        _q = c1.multiselect("Quitar tickets", _a["id_dt"].tolist(),
                            format_func=lambda i: f"#{int(_a[_a['id_dt'] == i]['ticket'].iloc[0])}",
                            key=f"dsp_tk_del_{rol}")
        if _q and c2.button("🗑️ Quitar", key=f"dsp_tk_delb_{rol}", use_container_width=True):
            try:
                with conectar(USR["id_usuario"]) as (conn, _x):
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM produccion.fact_despacho_ticket WHERE id_dt = ANY(%s)",
                                    ([int(i) for i in _q],))
                cat.clear(); st.success("Tickets desasignados."); st.rerun()
            except Exception as e:
                st.error(f"No se pudo quitar: {e}")
    else:
        st.info("Todavía no hay tickets asignados en este rol.")

    with st.expander("➕ Asignar tickets de portería", expanded=asg is None or asg.empty):
        _f = cab.get("fecha_despacho")
        _f = pd.to_datetime(_f).date() if pd.notna(_f) else _dt.date.today()
        f1, f2, f3, f4 = st.columns([1, 1, 1, 1.6])
        d1 = f1.date_input("Desde", _f - _dt.timedelta(days=7), key=f"dsp_tk_d1_{rol}")
        d2 = f2.date_input("Hasta", _f + _dt.timedelta(days=7), key=f"dsp_tk_d2_{rol}")
        fam = f3.selectbox("Familia", ["Todas", "AG", "AFE"], key=f"dsp_tk_fam_{rol}")
        txt = f4.text_input("Buscar (producto, destino, área, patente, obs., ticket)",
                            key=f"dsp_tk_txt_{rol}")

        cnd = _tk_candidatos(cat, spec["clases"], d1, d2, txt.strip(), fam)
        if cnd is None or cnd.empty:
            st.info("No hay tickets libres con ese filtro. Ampliá el rango de fechas o sacá el texto.")
            return
        cnd = cnd.copy()
        cnd["kg"] = pd.to_numeric(cnd["kg"], errors="coerce")
        cnd["Asignar"] = False
        cnd["Contenedor"] = ""
        cnd["Precinto"] = ""
        _pre = cnd.rename(columns={"ticket": "Ticket", "fecha": "Fecha", "hora": "Hora",
                                   "producto": "Producto", "destino": "Destino", "area": "Área",
                                   "patente": "Patente", "sin_pesada": "Sin pesada",
                                   "procedencia": "Procedencia", "observaciones": "Obs. portería"})
        _c = (["Asignar", "Ticket", "Fecha", "Hora", "Producto", "Destino", "Patente", "kg",
               "Sin pesada", "Obs. portería", "Contenedor", "Precinto"] if rol == "SALIDA" else
              ["Asignar", "Ticket", "Fecha", "Hora", "Producto", "Procedencia", "Área", "Patente",
               "kg", "Sin pesada", "Obs. portería", "Contenedor", "Precinto"])
        ed = st.data_editor(
            _pre[_c], hide_index=True, use_container_width=True, key=f"dsp_tk_ed_{rol}",
            disabled=[c for c in _c if c not in ("Asignar", "Contenedor", "Precinto")],
            column_config={
                "Asignar": st.column_config.CheckboxColumn("✔", width="small"),
                "kg": st.column_config.NumberColumn("kg", format="%.0f"),
                "Sin pesada": st.column_config.CheckboxColumn("Sin pesada", disabled=True,
                                                              help="El ticket no tiene pesada de salida cerrada."),
                "Contenedor": st.column_config.TextColumn("Contenedor", width="small"),
                "Precinto": st.column_config.TextColumn("Precinto", width="small"),
            })
        _sel = ed[ed["Asignar"] == True]  # noqa: E712
        st.caption(f"{len(cnd)} tickets libres en el rango · {len(_sel)} seleccionados "
                   f"({_sel['kg'].sum():,.0f} kg)".replace(",", "."))
        if len(_sel) and st.button(f"✅ Asignar {len(_sel)} ticket(s)", key=f"dsp_tk_add_{rol}",
                                   type="primary"):
            _idx = _sel.index.tolist()
            filas = []
            for i in _idx:
                o = cnd.loc[i]
                s = ed.loc[i]
                filas.append((int(cab["id_despacho"]), rol, int(o["id_transaccion"]),
                              int(o["ticket"]) if pd.notna(o["ticket"]) else None,
                              int(o["empresa"]) if pd.notna(o["empresa"]) else None,
                              o["fecha"], o["producto"],
                              o["destino"] if rol == "SALIDA" else o["area"],
                              o["patente"], float(o["kg"]) if pd.notna(o["kg"]) else None,
                              bool(o["sin_pesada"]),
                              (str(s.get("Contenedor") or "").strip() or None),
                              (str(s.get("Precinto") or "").strip() or None),
                              USR.get("nombre")))
            try:
                with conectar(USR["id_usuario"]) as (conn, _x):
                    with conn.cursor() as cur:
                        cur.executemany(
                            "INSERT INTO produccion.fact_despacho_ticket "
                            "(id_despacho, rol, id_transaccion, ticket, empresa, fecha, producto, "
                            " destino, patente, kg, sin_pesada, nro_contenedor, precinto, creado_por) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT (id_transaccion) DO NOTHING", filas)
                cat.clear(); st.success(f"{len(filas)} ticket(s) asignados."); st.rerun()
            except Exception as e:
                st.error(f"No se pudieron asignar: {e}")


def _tickets(USR, cat, conectar):
    df = cat("SELECT id_despacho, titulo, destino, cliente, producto, fecha_despacho, "
             "n_contenedores, litros_objetivo, tn_total, estado FROM produccion.v_despacho_resumen "
             "ORDER BY fecha_despacho DESC NULLS LAST, id_despacho DESC")
    if df is None or df.empty:
        st.info("Primero cargá un despacho en *Armar / editar despacho*.")
        return
    _lbl = {int(r["id_despacho"]): (f"#{int(r['id_despacho'])} · {r['titulo']} · "
                                    f"{r['destino'] or 's/destino'} · {r['fecha_despacho'] or 's/fecha'}")
            for _, r in df.iterrows()}
    sel = st.selectbox("Despacho", df["id_despacho"].tolist(),
                       format_func=lambda i: _lbl.get(int(i), str(i)), key="dsp_tk_desp")
    if sel is None:
        return
    cab = df[df["id_despacho"] == sel].iloc[0]

    res = cat("SELECT tickets_salida, tickets_mp, kg_salida, kg_mp, tickets_error, tickets_aviso "
              "FROM produccion.v_despacho_ticket_resumen WHERE id_despacho=%s", (int(sel),))
    r = res.iloc[0] if res is not None and not res.empty else {}
    _ns = int(r.get("tickets_salida") or 0)
    _nc = int(cab.get("n_contenedores") or 0)
    _ks = float(r.get("kg_salida") or 0)
    _km = float(r.get("kg_mp") or 0)
    _tn = float(cab.get("tn_total") or 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Contenedores", f"{_ns} de {_nc}", delta=(None if _ns == _nc else f"{_ns - _nc:+d}"))
    m2.metric("Salida despachada", f"{_ks / 1000:,.1f} TN".replace(",", "."))
    m3.metric("Objetivo formulación", f"{_tn:,.1f} TN".replace(",", "."))
    m4.metric("MP cargada", f"{_km / 1000:,.1f} TN".replace(",", "."),
              delta=(f"{(_km - _ks) / 1000:+.1f} TN vs salida" if _ks and _km else None))

    if _tn and _ks:
        _dif = (_ks / 1000) - _tn
        if abs(_dif) / _tn > 0.03:
            st.warning(f"⚖️ La salida pesada difiere **{_dif:+,.1f} TN** ({_dif / _tn * 100:+.1f} %) "
                       "de lo formulado. Revisá si faltan tickets, si sobran, o si la densidad "
                       "usada en la formulación no es la real.".replace(",", "."))
    if int(r.get("tickets_error") or 0):
        st.error(f"⛔ {int(r['tickets_error'])} ticket(s) con error de pesada — ver detalle abajo.")

    st.markdown("---")
    _o = ["🚚 Salidas a exportación", "🛢️ Materia prima"]
    try:
        _r = st.segmented_control("Rol", _o, default=_o[0], key="dsp_tk_rol_sc",
                                  label_visibility="collapsed")
    except Exception:
        _r = st.radio("Rol", _o, horizontal=True, key="dsp_tk_rol")
    _r = _r or _o[0]
    st.write("")
    _tk_panel(USR, cat, conectar, cab, "SALIDA" if _r.startswith("🚚") else "MP")
