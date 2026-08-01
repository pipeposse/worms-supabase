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
# Por debajo de esto un tanque no entra en la formulación: suele ser fondo de tanque
# (borra/sedimento decantado), que arruina la calidad de la mezcla.
MIN_L_DESPACHO = 3500.0
TIPOS_CARGA = ["FLEX", "ISO TANK", "BULK", "CAMION", "TAMBORES"]
ESTADOS = ["BORRADOR", "CONFIRMADO", "DESPACHADO", "ANULADO"]

# El AG-E que sale a exportación no es el contenido de un solo tanque: es una FORMULACIÓN.
# Siempre lleva UN componente base de AG-E (alto en acidez y azufre, fuera de spec por sí solo)
# y el resto son AFE — casi siempre AFE-S — que lo diluyen hasta entrar en especificación.
# FORMULADOS: producto despachado -> prefijos de los productos que lo diluyen. Se usan prefijos
# y no una lista fija para que un AFE nuevo (AFE-M, AFE-P…) aparezca solo, sin tocar el código.
FORMULADOS = {"AG-E": ("AFE",)}
# Orden de preferencia al listar y al sugerir diluyentes; el resto va después, alfabético.
PREFERIDOS = ("AFE-S",)

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


def _familia(prod_cod, prods=None):
    """Productos que puede tomar un despacho de prod_cod: el base + con lo que se lo formula.

    Devuelve [base] + diluyentes ordenados por preferencia (AFE-S primero). Los diluyentes se
    leen de dim_producto por prefijo, así que dar de alta un AFE nuevo alcanza para que aparezca.
    """
    cod = str(prod_cod or "").strip().upper()
    if cod not in FORMULADOS:
        return [cod]
    pref = FORMULADOS[cod]
    extra = []
    if prods is not None and not getattr(prods, "empty", True):
        for c in prods["codigo_producto"].astype(str).str.strip().str.upper().tolist():
            if c != cod and any(c.startswith(x) for x in pref):
                extra.append(c)
    if not extra:
        extra = list(PREFERIDOS)
    extra = sorted(set(extra),
                   key=lambda c: (PREFERIDOS.index(c) if c in PREFERIDOS else 99, c))
    return [cod] + extra


def _es_base(prod, prod_cod):
    """True si el producto del tanque es el componente base del despacho (el AG-E)."""
    return str(prod or "").strip().upper() == str(prod_cod or "").strip().upper()


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
    """Etiqueta del desplegable: producto, stock y laboratorio, para elegir viendo la calidad."""
    _p = str(r.get("producto_principal") or "—")
    _l = r.get("litros_actual")
    _l = f"{_l:,.0f} L" if pd.notna(_l) else "sin medición"
    _a, _f, _s = r.get("acidez"), r.get("fosforo"), r.get("azufre")
    if pd.isna(_a) and pd.isna(_f) and pd.isna(_s):
        _lab = "sin lab"
    else:
        _lab = "ac %s · P %s · S %s" % (
            ("%.2f" % float(_a)) if pd.notna(_a) else "?",
            ("%.0f" % float(_f)) if pd.notna(_f) else "?",
            ("%.0f" % float(_s)) if pd.notna(_s) else "?")
    return f"{r['nombre']} · {_p} · {_l} · {_lab}"


def _productos(cat):
    df = cat("SELECT codigo_producto, coalesce(rotulo_oficial, codigo_producto) AS producto, "
             "tipo_producto, densidad_g_ml, es_exportacion FROM produccion.dim_producto "
             "WHERE activo ORDER BY 2")
    return df if df is not None else pd.DataFrame()


# ------------------------------------------------------------------ cálculo

def _resolver(ed: pd.DataFrame, tks: pd.DataFrame, prod_cod=None) -> pd.DataFrame:
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
            "Rol": ("BASE" if _es_base(t["producto_principal"], prod_cod) else "DILUYENTE"),
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


def _estructura(res, prod_cod, prods=None):
    """Controla que la carga respete la formulación: 1 componente base + N diluyentes AFE.

    Devuelve (ok, mensajes). ok=False sólo cuando falta el base o falta el diluyente, que son los
    dos casos en los que lo cargado no es el producto que se despacha.
    """
    fam = _familia(prod_cod, prods)
    base_cod = fam[0]
    if len(fam) == 1 or res.empty or "Rol" not in res.columns:
        return True, []
    tot = float(res["Litros"].sum()) or 1.0
    b = res[res["Rol"] == "BASE"]
    d = res[res["Rol"] == "DILUYENTE"]
    l_b = float(b["Litros"].sum())
    l_d = float(d["Litros"].sum())
    c1, c2, c3 = st.columns([1, 1, 1.6])
    c1.metric("Componente %s" % base_cod, "{:,.0f} L".format(l_b),
              "%.2f %% del total" % (100.0 * l_b / tot), delta_color="off",
              help="El AG-E crudo: es el que aporta la acidez y el azufre altos.")
    c2.metric("Diluyentes · %d tanque(s)" % len(d), "{:,.0f} L".format(l_d),
              "%.2f %% del total" % (100.0 * l_d / tot), delta_color="off",
              help="Los AFE que bajan la mezcla hasta la especificación.")
    _mix = ", ".join(sorted(set(str(x) for x in d["Producto"].dropna()))) or "—"
    c3.metric("Con qué se diluye", _mix)

    msgs = []
    ok = True
    if b.empty:
        ok = False
        msgs.append(("error", "La carga **no tiene componente %s**. Un despacho de %s siempre lleva "
                              "un tanque de %s más los AFE que lo diluyen: así como está, lo que se "
                              "despacha no es %s." % (base_cod, base_cod, base_cod, base_cod)))
    elif len(b) > 1:
        msgs.append(("warning", "Hay %d líneas de %s (%s). Lo normal es que el componente base "
                                "salga de un solo tanque de formulación."
                     % (len(b), base_cod, ", ".join(b["Tanque"].astype(str)))))
    if d.empty:
        ok = False
        msgs.append(("error", "La carga es 100%% %s sin diluir. Agregá los tanques de AFE "
                              "(en general AFE-S) que bajan la acidez y el azufre." % base_cod))
    else:
        _cods = set(str(x).strip().upper() for x in d["Producto"].dropna())
        _raros = sorted(_cods - set(fam[1:]))
        if _raros:
            msgs.append(("warning", "Hay componentes que no son AFE: %s. Revisá el producto "
                                    "principal de esos tanques." % ", ".join(_raros)))
        _otros = sorted(_cods - set(PREFERIDOS) - set(_raros))
        if _otros:
            msgs.append(("info", "Se está diluyendo también con %s. Es válido, pero lo habitual "
                                 "es AFE-S." % ", ".join(_otros)))
    return ok, msgs


# ------------------------------------------------------------------ sugerencia de mezcla

def _sugerir(tks, prod_cod, litros_obj, spec, prods=None, l_base=None, maximizar=False,
             min_l=MIN_L_DESPACHO):
    """Propone la carga respetando la formulación: primero el componente base, después los AFE.

    Con maximizar=True busca el MÁXIMO de componente base (AG-E) que sigue cumpliendo la
    especificación: el AG-E es más barato que el AFE-S, así que conviene la mayor participación
    posible. La búsqueda es binaria sobre los litros de base; en cada punto se completa el
    objetivo con los AFE (AFE-S primero, mejor margen primero) y se evalúa la mezcla ponderada
    por kg, igual que el panel de specs. La masa sin laboratorio no se puede evaluar y queda
    afuera del promedio (el panel ya lo avisa).
    """
    fam = _familia(prod_cod, prods)
    base_cod = fam[0]
    formulado = len(fam) > 1
    up = tks["producto_principal"].astype(str).str.strip().str.upper()
    dis = tks["litros_actual"].fillna(0)

    def _score(r):
        rr = []
        for c, lim in (("acidez", spec["acidez"]), ("agua_sedimento", spec["ays"]),
                       ("azufre", spec["azufre"]), ("fosforo", spec["fosforo"])):
            if lim and pd.notna(r[c]):
                rr.append(float(r[c]) / float(lim))
        return max(rr) if rr else 0.90  # sin lab: prioridad media-baja

    def _linea(r, litros):
        return {"Tanque": r["etq"], "Litros": round(float(litros), 0), "Acidez %": _NAN,
                "Fósforo ppm": _NAN, "Azufre ppm": _NAN, "AyS %": _NAN}

    # pool de diluyentes: AFE-S primero, después el resto, por margen contra la spec
    cod_dil = fam[1:] if formulado else [base_cod]
    d = tks[up.isin(cod_dil) & (dis >= min_l)].copy()
    if not d.empty:
        d["score"] = d.apply(_score, axis=1)
        d["_pref"] = up[d.index].apply(lambda c: PREFERIDOS.index(c) if c in PREFERIDOS else 99)
        d = d.sort_values(["_pref", "score", "litros_actual"], ascending=[True, True, False])

    # tanque del componente base: el de más stock
    rb, hay = None, 0.0
    if formulado:
        b = tks[up == base_cod].copy()
        if b.empty:
            return (pd.DataFrame(),
                    "No hay ningún tanque con %s. Sin componente base no hay despacho de %s."
                    % (base_cod, base_cod))
        b["_d"] = b["litros_actual"].fillna(0)
        b = b.sort_values("_d", ascending=False)
        # fondo de tanque (<min_l) tampoco sirve como base; sin medición (0) se permite
        # porque es el caso del tanque de formulación, que se llena al armar la carga
        _bok = b[(b["_d"] >= min_l) | (b["_d"] <= 0)]
        rb = (_bok if not _bok.empty else b).iloc[0]
        hay = float(rb["_d"])

    def _armar_mezcla(lb):
        """[(fila_tanque, litros)] con el base primero; completa el objetivo con el pool."""
        out, acum = [], 0.0
        if formulado and lb > 0:
            out.append((rb, float(lb)))
            acum = float(lb)
        for _, r in d.iterrows():
            if acum >= litros_obj:
                break
            toma = min(float(r["litros_actual"]), litros_obj - acum)
            if toma < min_l * 0.2:
                continue
            out.append((r, toma))
            acum += toma
        return out, acum

    def _cumple(lineas):
        """Promedios ponderados por kg de la masa medida vs los máximos de la spec."""
        for c, lim in (("acidez", spec["acidez"]), ("agua_sedimento", spec["ays"]),
                       ("azufre", spec["azufre"]), ("fosforo", spec["fosforo"])):
            if not lim:
                continue
            num = den = 0.0
            for r, lts in lineas:
                if pd.isna(r[c]):
                    continue
                _dn = float(r["densidad"]) if pd.notna(r.get("densidad")) else 0.91
                kg = lts * _dn
                num += float(r[c]) * kg
                den += kg
            if den > 0 and num / den > float(lim) + 1e-9:
                return False
        return True

    notas = []
    lb = 0.0
    if formulado:
        if maximizar:
            tope = min(hay, float(litros_obj))
            if tope <= 0:
                notas.append("el tanque de %s (%s) no tiene stock medido: no se puede maximizar, "
                             "poné los litros a mano" % (base_cod, rb["nombre"]))
            elif _cumple(_armar_mezcla(tope)[0]):
                lb = tope
                notas.append("entra TODO el stock de %s (%s L) y la mezcla sigue en spec"
                             % (base_cod, "{:,.0f}".format(tope)))
            elif not _cumple(_armar_mezcla(0.0)[0]):
                notas.append("ni siquiera sin %s la mezcla cumple la spec con estos AFE: "
                             "cambiá los tanques diluyentes" % base_cod)
            else:
                lo, hi = 0.0, tope
                for _ in range(30):
                    mid = (lo + hi) / 2.0
                    if _cumple(_armar_mezcla(mid)[0]):
                        lo = mid
                    else:
                        hi = mid
                lb = float(int(lo // 10) * 10)  # redondeo hacia abajo: margen, no exceso
        else:
            lb = float(l_base) if l_base else (min(hay, litros_obj) if hay > 0 else 0.0)
            lb = max(0.0, min(lb, float(litros_obj)))
            if lb <= 0 and not l_base:
                notas.append("el tanque de %s (%s) está sin medición: poné los litros a mano"
                             % (base_cod, rb["nombre"]))
            elif hay > 0 and lb > hay + 0.5:
                notas.append("%s tiene %s L y se piden %s L"
                             % (rb["nombre"], "{:,.0f}".format(hay), "{:,.0f}".format(lb)))

    lineas, acum = _armar_mezcla(lb)
    if not lineas:
        return pd.DataFrame(), "No se pudo armar una mezcla con el stock disponible."
    out = [_linea(r, lts) for r, lts in lineas]
    falta = litros_obj - acum
    msg = "Propuesta con %d tanque(s) — %s L." % (len(out), "{:,.0f}".format(acum))
    if formulado and maximizar:
        msg += (" Máximo %s que cumple la spec: %s L (%.1f%% de la carga)."
                % (base_cod, "{:,.0f}".format(lb), (100.0 * lb / acum if acum else 0.0)))
    elif formulado:
        msg += " La primera línea es el componente %s; el resto son AFE (primero AFE-S)." % base_cod
    if falta > 1:
        msg += " Faltan %s L: no alcanza el stock." % "{:,.0f}".format(falta)
    if notas:
        msg += " Ojo: " + "; ".join(notas) + "."
    return pd.DataFrame(out), msg


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
    cols = ["Rol", "Producto", "Acidez %", "Fósforo ppm", "Azufre ppm", "TN", "Litros", "%", "Tanque"]
    d = d.reindex(columns=cols)
    tot = {"Rol": "", "Producto": "TOTAL", "TN": tot_kg / 1000.0, "Litros": tot_l,
           "%": 100.0 if tot_l else 0.0, "Tanque": ""}
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

    ss = st.session_state
    _opts = ["🧪 Armar / editar despacho", "🔬 Control y confirmación", "🎟️ Tickets de portería",
             "📋 Despachos cargados"]
    # "Modificar en el armador" pide cambiar de vista: va vía dsp_tab_next porque el estado de
    # un widget ya instanciado no se puede pisar dentro del mismo run.
    _nx = ss.pop("dsp_tab_next", None)
    if _nx in _opts:
        ss["dsp_tab_sc"] = _nx
        ss["dsp_tab"] = _nx
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
    elif _t.startswith("🔬"):
        _control(USR, cat, conectar)
    else:
        _armar(USR, cat, conectar)


def _armar(USR, cat, conectar):
    ss = st.session_state
    tks = _tanques(cat)
    if tks.empty:
        st.error("No se pudieron leer los tanques.")
        return
    prods = _productos(cat)

    # líneas de un despacho guardado que se mandó a editar (ver _editar_despacho)
    _pend = ss.pop("dsp_load_pend", None)
    if _pend is not None:
        _mapa = {int(r["id_tanque"]): r["etq"] for _, r in tks.iterrows()}
        _filas, _sk, _algun_manual = [], [], False
        for _ln in _pend:
            _e = _mapa.get(int(_ln["id_tanque"])) if pd.notna(_ln.get("id_tanque")) else None
            if not _e:
                _sk.append(str(_ln.get("id_tanque")))
                continue
            _man = str(_ln.get("lab_origen") or "") == "MANUAL"
            _algun_manual = _algun_manual or _man
            _filas.append({
                "Tanque": _e,
                "Litros": float(_ln.get("litros") or 0),
                "Acidez %": (float(_ln["acidez"]) if _man and _ln.get("acidez") is not None else _NAN),
                "Fósforo ppm": (float(_ln["fosforo"]) if _man and _ln.get("fosforo") is not None else _NAN),
                "Azufre ppm": (float(_ln["azufre"]) if _man and _ln.get("azufre") is not None else _NAN),
                "AyS %": (float(_ln["agua_sedimento"]) if _man and _ln.get("agua_sedimento") is not None
                          else _NAN),
            })
        ss["dsp_lineas"] = pd.DataFrame(_filas) if _filas else _base_vacia(_COLS_ED)
        if _algun_manual:
            ss["dsp_pisar"] = True
        if _sk:
            st.warning("Quedaron afuera %d línea(s) de tanques que ya no están activos (id: %s)."
                       % (len(_sk), ", ".join(_sk)))

    if ss.get("dsp_edit_id"):
        _ci, _cx = st.columns([4, 1])
        _ci.info("✏️ Estás **editando el despacho #%d**: al guardar se pisa el existente y sus "
                 "líneas se reemplazan por lo que quede acá." % int(ss["dsp_edit_id"]))
        if _cx.button("✖ Cancelar edición", key="dsp_edit_cancel", use_container_width=True):
            ss["dsp_edit_id"] = None
            st.rerun()

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
    # Lo que sale a exportación es casi siempre AG-E, así que arranca elegido ese.
    _def_p = 0
    for _c in ("AG-E", "AFE-S"):
        if _c in _pl:
            _def_p = _pl.index(_c)
            break
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
    _fam = _familia(prod_cod, prods)
    _extra = _fam[1:]
    st.markdown(f"#### 2 · Tanques con **{prod_lbl}**" + (" y con lo que se formula" if _extra else ""))
    if _extra:
        st.caption("Un despacho de **%s** es una formulación: **un** componente de %s (el crudo, "
                   "fuera de spec por sí solo) más los **AFE** que lo diluyen, en general **AFE-S**. "
                   "Por eso acá aparecen los tanques de %s y de %s. Los litros de cada uno los "
                   "ponés vos." % (prod_lbl, _fam[0], _fam[0], ", ".join(_extra)))
    _tp = tks[tks["producto_principal"].astype(str).str.strip().str.upper()
              .isin(_fam)].copy()
    if _tp.empty:
        st.error(f"No hay ningún tanque activo con producto **{prod_lbl}** ({prod_cod}). "
                 "Revisá el producto principal de los tanques en el panel de tanques.")
        return

    # Un tanque sin stock medido igual puede ser el origen del despacho: el de formulación
    # (FORM-AG-E) se llena al momento de armar la carga, así que casi siempre figura en 0 y aun
    # así es de donde sale el producto. Antes se lo excluía del selector y la opción no aparecía.
    _lts = _tp["litros_actual"].fillna(0)
    _con = _tp[_lts >= MIN_L_DESPACHO].copy()
    _fondo = _tp[(_lts > 0) & (_lts < MIN_L_DESPACHO)].copy()
    _s0 = _tp[_lts <= 0].copy()
    if _con.empty and _s0.empty:
        st.error(f"Hay tanques de **{prod_lbl}** pero ninguno disponible. "
                 "Revisá el panel de tanques.")
        return
    _sin_lab = _con[_con.apply(lambda r: len(_faltan_lab(r)) > 0, axis=1)]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Tanques usables", f"{len(_con)}",
              help="Con al menos %s L. Menos que eso suele ser fondo de tanque y no entra."
                   % f"{MIN_L_DESPACHO:,.0f}")
    k2.metric("Stock disponible", f"{_con['litros_actual'].fillna(0).sum():,.0f} L")
    k3.metric("Con lab completo", f"{len(_con) - len(_sin_lab)} de {len(_con)}")
    k4.metric("Fondos excluidos", f"{len(_fondo)}",
              help="Tanques con menos de %s L: no se ofrecen ni se sugieren."
                   % f"{MIN_L_DESPACHO:,.0f}")
    if not _fondo.empty:
        st.caption("🛢️ **Quedan afuera por fondo de tanque (<%s L):** " % f"{MIN_L_DESPACHO:,.0f}"
                   + ", ".join(f"{r['nombre']} ({r['litros_actual']:,.0f} L)"
                               for _, r in _fondo.sort_values("litros_actual").iterrows()))

    # Stock a la vista: cuánto hay en cada tanque usable, ordenado de mayor a menor.
    _stk = _con.sort_values("litros_actual", ascending=False)[
        ["nombre", "producto_principal", "litros_actual", "capacidad_litros"]].copy()
    _stk["% lleno"] = (100.0 * _stk["litros_actual"] / _stk["capacidad_litros"].replace(0, pd.NA)).fillna(0.0).round(0)
    _stk = _stk.rename(columns={"nombre": "Tanque", "producto_principal": "Producto",
                                "litros_actual": "Stock (L)", "capacidad_litros": "Capacidad (L)"})
    st.dataframe(_stk, hide_index=True, use_container_width=True, height=min(38 * (len(_stk) + 1), 320),
                 column_config={
                     "Stock (L)": st.column_config.NumberColumn(format="%.0f"),
                     "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
                     "% lleno": st.column_config.ProgressColumn("% lleno", format="%.0f%%",
                                                                min_value=0, max_value=100)})
    if not _s0.empty:
        st.caption("Sin medición de nivel cargada, pero igual seleccionables: **" +
                   "**, **".join(_s0["nombre"].astype(str).tolist()) +
                   "**. Es el caso del tanque de formulación, que se llena al armar la carga: "
                   "elegilo y poné los litros a mano.")

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

    # ---------- 3 · Formulación ----------
    st.markdown("#### 3 · Formulación por tanque")
    _formulado = len(_fam) > 1
    if _formulado:
        ca, cb, cd, cc = st.columns([1.1, 0.9, 1.1, 1.5])
        _lb = cd.number_input("Litros de %s (0 = máximo)" % _fam[0], min_value=0.0, step=500.0,
                              value=float(ss.get("dsp_lbase", 0.0)), key="dsp_lbase",
                              help="En 0, la sugerencia calcula sola el MÁXIMO de %s que sigue "
                                   "cumpliendo la especificación (el %s es más barato que el AFE-S, "
                                   "conviene maximizar su participación). Con un valor, usa esos "
                                   "litros exactos." % (_fam[0], _fam[0]))
    else:
        ca, cb, cc = st.columns([1, 1, 2.4])
        _lb = 0.0
    _hlp = ("Arma la formulación: mete el MÁXIMO de %s que cumpla la spec (o los litros que pongas) "
            "y completa con los AFE (AFE-S primero, mayor margen primero)."
            % _fam[0]) if _formulado else \
           "Propone tanques del producto elegido, priorizando los de mayor margen contra la spec."
    if ca.button("🎯 Sugerir mezcla", use_container_width=True, help=_hlp):
        _sug, _msg = _sugerir(tks, prod_cod, lit_obj, spec, prods, (_lb or None),
                              maximizar=(_formulado and not _lb))
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

    _o = _con["etq"].tolist() + _s0["etq"].tolist()
    _cfg = {
        "Tanque": st.column_config.SelectboxColumn("Tanque", options=_o, width="large", required=True,
                                                   help="Tanques con " + " / ".join(_fam) + "."),
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

    res = _resolver(ed, tks, prod_cod)
    if res.empty:
        st.info("Cargá al menos una línea con tanque y litros para ver los cálculos.")
        return

    # Detalle por tanque: laboratorio y peso de cada tanque en la carga. Va acá, pegado al editor,
    # y no dentro del editor, porque st.data_editor dibuja la grilla con los datos de ANTES de la
    # edición: el % y el lab quedarían atrasados un click respecto de los litros que acabás de tocar.
    tot_l = float(res["Litros"].sum())
    _d = res.copy()
    _d["Litros"] = _d["Litros"].round(0)
    _d["% del total"] = (100.0 * _d["Litros"] / tot_l).round(2) if tot_l else 0.0
    _d["TN"] = _d["TN"].round(2)
    _d["Lab"] = _d.apply(
        lambda r: "✅" if all(pd.notna(r[c]) for c in ("Acidez %", "Fósforo ppm", "Azufre ppm"))
        else "⚠️ falta " + ", ".join(c for c in ("Acidez %", "Fósforo ppm", "Azufre ppm")
                                     if pd.isna(r[c])), axis=1)
    _show = _d[["Rol", "Tanque", "Producto", "Litros", "% del total", "Acidez %", "Fósforo ppm",
                "Azufre ppm", "AyS %", "Lab", "Densidad", "TN", "Disp. (L)", "Restante (L)"]]
    st.dataframe(
        _show, hide_index=True, use_container_width=True,
        column_config={
            "Rol": st.column_config.TextColumn("Rol", width="small",
                                               help="BASE = el componente AG-E. DILUYENTE = los AFE."),
            "Litros": st.column_config.NumberColumn(format="%.0f"),
            "% del total": st.column_config.NumberColumn("% del total", format="%.2f %%",
                                                         help="Peso de este tanque sobre los litros cargados."),
            "Acidez %": st.column_config.NumberColumn("Acidez %", format="%.2f"),
            "Fósforo ppm": st.column_config.NumberColumn("Fósforo ppm", format="%.1f"),
            "Azufre ppm": st.column_config.NumberColumn("Azufre ppm", format="%.1f"),
            "AyS %": st.column_config.NumberColumn("AyS %", format="%.2f"),
            "Lab": st.column_config.TextColumn("Lab", help="Parámetros que faltan para controlar la spec."),
            "Disp. (L)": st.column_config.NumberColumn(format="%.0f"),
            "Restante (L)": st.column_config.NumberColumn(format="%.0f")})
    st.caption("Acidez, fósforo, azufre y AyS son el último análisis del tanque. El **% del total** "
               "es sobre los litros efectivamente cargados acá, no sobre el objetivo.")

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

    if _formulado:
        st.markdown("**Estructura de la formulación** (%s + AFE)" % _fam[0])
    ok_est, _msg_est = _estructura(res, prod_cod, prods)

    st.markdown("**Cumplimiento de especificación** (promedios ponderados por kg)")
    ok_spec = _panel_specs(res, spec)
    ok = ok_spec and ok_est

    # ---------- 4 · Avisos ----------
    avisos = []
    _ex = res[res["Excede"]]
    if not _ex.empty:
        _sm = _ex[_ex["Disp. (L)"] <= 0]
        _ex = _ex[_ex["Disp. (L)"] > 0]
        if not _sm.empty:
            avisos.append("Sin medición de nivel cargada: " +
                          ", ".join(_sm["Tanque"].astype(str).tolist()) +
                          " — se toman los litros que pusiste a mano, sin control contra stock.")
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
        _fuera = [p for p in _multi if str(p).strip().upper() not in _fam]
        if _fuera:
            avisos.append("La mezcla combina productos distintos: " + ", ".join(map(str, _multi)) + ".")
        else:
            st.caption("ℹ️ El despacho combina " + ", ".join(map(str, _multi)) +
                       ", que es como se arma el " + str(prod_lbl) +
                       ". Los promedios de arriba ya son los del producto final cargado.")
    for _lvl, _m in _msg_est:
        getattr(st, _lvl)(_m)
    if avisos:
        for a in avisos:
            st.warning(a)
    if not ok_est:
        st.error("La carga **no respeta la formulación** de un despacho de %s: siempre es un "
                 "componente de %s más los AFE que lo diluyen." % (prod_lbl, _fam[0]))
    if not ok_spec:
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

    if st.button("✏️ Modificar en el armador", key="dsp_ed_open",
                 help="Precarga cabecera y líneas en la vista de armado; al guardar se pisa este despacho."):
        _editar_despacho(cat, st.session_state, int(sel))
        st.rerun()

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


def _editar_despacho(cat, ss, id_despacho):
    """Precarga un despacho guardado en el armador (cabecera + líneas) para modificarlo."""
    cab = cat("SELECT titulo, destino, cliente, producto_codigo, tipo_carga, fecha_despacho, "
              "n_contenedores, litros_por_contenedor, spec_acidez_max, spec_ays_max, "
              "spec_azufre_max, spec_fosforo_max, estado, observaciones "
              "FROM produccion.fact_despacho WHERE id_despacho=%s", (int(id_despacho),))
    if cab is None or cab.empty:
        st.error("No encontré el despacho #%d." % int(id_despacho))
        return
    r = cab.iloc[0]
    lin = cat("SELECT id_tanque, litros, acidez, fosforo, azufre, agua_sedimento, lab_origen "
              "FROM produccion.fact_despacho_linea WHERE id_despacho=%s ORDER BY orden",
              (int(id_despacho),))
    prods = _productos(cat)
    if not prods.empty:
        _m = prods[prods["codigo_producto"] == r["producto_codigo"]]
        if not _m.empty:
            ss["dsp_prod"] = _m.iloc[0]["producto"]
    ss["dsp_titulo"] = r["titulo"] or ""
    ss["dsp_destino"] = r["destino"] or ""
    ss["dsp_cliente"] = r["cliente"] or ""
    if r["tipo_carga"] in TIPOS_CARGA:
        ss["dsp_tipo"] = r["tipo_carga"]
    if pd.notna(r["fecha_despacho"]):
        ss["dsp_fecha"] = pd.to_datetime(r["fecha_despacho"]).date()
    ss["dsp_ncont"] = int(r["n_contenedores"] or 1)
    ss["dsp_lcont"] = float(r["litros_por_contenedor"] or 26000.0)
    for _k, _c in (("dsp_spac", "spec_acidez_max"), ("dsp_spays", "spec_ays_max"),
                   ("dsp_spaz", "spec_azufre_max"), ("dsp_spfos", "spec_fosforo_max")):
        if pd.notna(r[_c]):
            ss[_k] = float(r[_c])
    if r["estado"] in ESTADOS:
        ss["dsp_estado"] = r["estado"]
    ss["dsp_obs"] = r["observaciones"] or ""
    ss["dsp_load_pend"] = [] if lin is None else lin.to_dict("records")
    ss["dsp_edit_id"] = int(id_despacho)
    ss["dsp_tab_next"] = "🧪 Armar / editar despacho"


# ------------------------------------------------------------------ control y confirmación

def _control(USR, cat, conectar):
    """Repaso de los despachos pre-cargados: refrescar laboratorio, verificar spec, confirmar."""
    ss = st.session_state
    st.markdown("#### 🔬 Control y confirmación")
    st.caption("Los **borradores se guardan aunque no cumplan** la especificación (el laboratorio "
               "de los tanques suele estar desactualizado al armarlos). Acá se actualizan los "
               "parámetros con el último análisis, se controla la spec y, cuando cumple, se "
               "confirma: el despacho queda **iniciado**.")

    df = cat("SELECT id_despacho, titulo, destino, producto, fecha_despacho, estado, litros_total, "
             "tn_total FROM produccion.v_despacho_resumen WHERE estado IN ('BORRADOR','CONFIRMADO') "
             "ORDER BY (estado='BORRADOR') DESC, fecha_despacho DESC NULLS LAST, id_despacho DESC")
    if df is None or df.empty:
        st.info("No hay despachos en borrador ni confirmados para controlar.")
        return
    _lbl = {int(r["id_despacho"]): ("#%d · %s · %s · %s" % (int(r["id_despacho"]),
             r["titulo"] or "s/título", r["estado"], r["fecha_despacho"] or "s/fecha"))
            for _, r in df.iterrows()}
    sel = st.selectbox("Despacho a controlar", df["id_despacho"].tolist(),
                       format_func=lambda i: _lbl.get(int(i), str(i)), key="dsp_ctl_sel")
    if sel is None:
        return
    _estado = str(df[df["id_despacho"] == sel].iloc[0]["estado"])

    cabx = cat("SELECT spec_acidez_max, spec_ays_max, spec_azufre_max, spec_fosforo_max "
               "FROM produccion.fact_despacho WHERE id_despacho=%s", (int(sel),))
    _rs = cabx.iloc[0] if cabx is not None and not cabx.empty else {}
    spec = {"acidez": float(_rs.get("spec_acidez_max") or SPEC_DEFAULT["acidez"]),
            "ays": float(_rs.get("spec_ays_max") or SPEC_DEFAULT["ays"]),
            "azufre": float(_rs.get("spec_azufre_max") or SPEC_DEFAULT["azufre"]),
            "fosforo": float(_rs.get("spec_fosforo_max") or SPEC_DEFAULT["fosforo"])}

    lin = cat("SELECT l.id_linea, l.orden, l.id_tanque, l.producto_codigo, l.litros, l.densidad, "
              "l.acidez, l.fosforo, l.azufre, l.agua_sedimento, l.lab_origen, "
              "t.nombre AS tanque, t.acidez AS acidez_tk, t.fosforo AS fosforo_tk, "
              "t.azufre AS azufre_tk, t.agua_sedimento AS ays_tk, t.densidad AS dens_tk, "
              "t.lab_actualizado_en "
              "FROM produccion.fact_despacho_linea l "
              "LEFT JOIN produccion.vw_tanque_panel t ON t.id_tanque = l.id_tanque "
              "WHERE l.id_despacho=%s ORDER BY l.orden", (int(sel),))
    if lin is None or lin.empty:
        st.info("Este despacho no tiene líneas cargadas. Editalo en el armador.")
        return
    lin = lin.copy()
    for _c in ("litros", "densidad", "acidez", "fosforo", "azufre", "agua_sedimento",
               "acidez_tk", "fosforo_tk", "azufre_tk", "ays_tk", "dens_tk"):
        lin[_c] = pd.to_numeric(lin[_c], errors="coerce")
    _man = lin["lab_origen"].astype(str).eq("MANUAL")

    # ---- comparación guardado vs tanque hoy ----
    def _dif(a, b, tol):
        if pd.isna(a) and pd.isna(b):
            return False
        if pd.isna(a) or pd.isna(b):
            return True
        return abs(float(a) - float(b)) > tol

    _chg = lin.apply(lambda r: (_dif(r["acidez"], r["acidez_tk"], 0.005)
                                or _dif(r["fosforo"], r["fosforo_tk"], 0.5)
                                or _dif(r["azufre"], r["azufre_tk"], 0.5)
                                or _dif(r["agua_sedimento"], r["ays_tk"], 0.005)), axis=1)
    _v = pd.DataFrame({
        "Tanque": lin["tanque"].fillna("(id %s)" % 0),
        "Prod.": lin["producto_codigo"], "Litros": lin["litros"],
        "Origen lab": lin["lab_origen"].fillna("TANQUE"),
        "Acidez guard.": lin["acidez"], "Acidez hoy": lin["acidez_tk"],
        "P guard.": lin["fosforo"], "P hoy": lin["fosforo_tk"],
        "S guard.": lin["azufre"], "S hoy": lin["azufre_tk"],
        "AyS guard.": lin["agua_sedimento"], "AyS hoy": lin["ays_tk"],
        "Lab del": lin["lab_actualizado_en"],
        "¿Cambió?": ["🔄 sí" if x else "" for x in _chg],
    })
    st.dataframe(_v, hide_index=True, use_container_width=True,
                 column_config={"Litros": st.column_config.NumberColumn(format="%.0f"),
                                "Lab del": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})
    _nch = int(_chg.sum())
    if _nch:
        st.warning("🔄 %d línea(s) tienen el laboratorio del tanque distinto al guardado en el "
                   "despacho. Actualizá antes de confirmar." % _nch)

    # ---- cumplimiento: guardado y como quedaría con el lab de hoy ----
    def _mk(actual):
        if actual:
            dens = lin["dens_tk"].fillna(lin["densidad"])
            cols = {"Acidez %": lin["acidez_tk"].where(~_man, lin["acidez"]),
                    "AyS %": lin["ays_tk"].where(~_man, lin["agua_sedimento"]),
                    "Azufre ppm": lin["azufre_tk"].where(~_man, lin["azufre"]),
                    "Fósforo ppm": lin["fosforo_tk"].where(~_man, lin["fosforo"])}
        else:
            dens = lin["densidad"]
            cols = {"Acidez %": lin["acidez"], "AyS %": lin["agua_sedimento"],
                    "Azufre ppm": lin["azufre"], "Fósforo ppm": lin["fosforo"]}
        out = pd.DataFrame(cols)
        out["kg"] = lin["litros"].fillna(0) * dens.fillna(0.91)
        return out

    st.markdown("**Cumplimiento con el laboratorio guardado en el despacho**")
    ok_g = _panel_specs(_mk(False), spec)
    if _nch:
        st.markdown("**Como quedaría con el laboratorio de hoy** (sin pisar lo cargado a mano)")
        _panel_specs(_mk(True), spec)

    # ---- acciones ----
    c1, c2, c3 = st.columns([1.3, 1.1, 1.3])
    _pm = c1.checkbox("Pisar también los valores cargados a mano", value=False, key="dsp_ctl_pm",
                      help="Por defecto las líneas con lab_origen MANUAL se respetan.")
    if c1.button("🔄 Actualizar lab desde los tanques", key="dsp_ctl_upd", use_container_width=True):
        try:
            _sqlu = ("UPDATE produccion.fact_despacho_linea l "
                     "SET acidez=t.acidez, fosforo=t.fosforo, azufre=t.azufre, "
                     "agua_sedimento=t.agua_sedimento, densidad=COALESCE(t.densidad, l.densidad), "
                     "lab_origen='TANQUE' "
                     "FROM produccion.vw_tanque_panel t "
                     "WHERE t.id_tanque=l.id_tanque AND l.id_despacho=%s")
            if not _pm:
                _sqlu += " AND COALESCE(l.lab_origen,'TANQUE') <> 'MANUAL'"
            with conectar(USR["id_usuario"]) as (conn, _a):
                with conn.cursor() as cur:
                    cur.execute(_sqlu, (int(sel),))
                    _nu = cur.rowcount
            cat.clear()
            st.success("%d línea(s) actualizadas con el último análisis de su tanque." % _nu)
            st.rerun()
        except Exception as e:
            st.error("No se pudo actualizar: %s" % e)
    if c2.button("✏️ Modificar en el armador", key="dsp_ctl_edit", use_container_width=True):
        _editar_despacho(cat, ss, int(sel))
        st.rerun()
    if _estado == "BORRADOR":
        if ok_g:
            if c3.button("✅ Cumple — confirmar e iniciar", type="primary", key="dsp_ctl_go",
                         use_container_width=True):
                try:
                    with conectar(USR["id_usuario"]) as (conn, _a):
                        with conn.cursor() as cur:
                            cur.execute("UPDATE produccion.fact_despacho SET estado='CONFIRMADO', "
                                        "actualizado_en=now() WHERE id_despacho=%s", (int(sel),))
                    cat.clear()
                    st.success("Despacho #%d CONFIRMADO: queda iniciado." % int(sel))
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo confirmar: %s" % e)
        else:
            c3.button("✅ Confirmar e iniciar", disabled=True, use_container_width=True,
                      help="No cumple la spec con los valores guardados: actualizá el laboratorio "
                           "o modificá la mezcla en el armador.")
    else:
        c3.caption("Ya está **CONFIRMADO**. El estado se maneja desde *Despachos cargados*.")


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
