"""Balance AFE-S ↔ Exportación (Centro de Planificación).

Responde una sola pregunta: ¿alcanza el AFE-S BUENO para sostener la exportación de AG-E?

  - Entradas de AFE por proveedor (portería, clases OTRO/INGRESO de familia AFE), cruzadas
    con el laboratorio del ticket (azufre y fósforo) y clasificadas en BUENO / MEDIO / MALO.
  - Exportación: las salidas que portería registra como "AG" con procedencia EGNITRADE S.L.
    hacia las terminales (SOUTHCROSS, PADILLA, LIBRA, MERCOMAR, INTERALMAR…) SON el AG-E
    comercial. Laboratorio no mide cada contenedor porque comparten fórmula.
  - Proyección: cuánto AFE-S bueno exige exportar E tn/semana con x% de AG-E, contra lo que
    entra y lo que hay en tanques → semanas de autonomía del stock bueno.

La misma clasificación explica el algoritmo de despacho: maximizar AG-E y, entre los AFE-S,
usar primero los de PEOR calidad que la spec tolere, reservando los buenos.
"""
import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
SPEC_S, SPEC_P = 50.0, 150.0          # spec de venta AG-E (máximos)
DENS_AFE = 0.89


def _banda(s, p, s_b, p_b):
    if pd.isna(s) and pd.isna(p):
        return "SIN LAB"
    s = float(s) if pd.notna(s) else 0.0
    p = float(p) if pd.notna(p) else 0.0
    if s > SPEC_S or p > SPEC_P:
        return "MALO"
    if s <= s_b and p <= p_b:
        return "BUENO"
    return "MEDIO"


def _pond(df, col, kgcol="kg"):
    d = df[pd.notna(df[col])]
    if d.empty or float(d[kgcol].sum()) <= 0:
        return None
    return float((d[col] * d[kgcol]).sum() / d[kgcol].sum())


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#7c2d12,#ca8a04);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🧮 Balance AFE-S ↔ Exportación</div>"
        "<div style='color:#fef3c7;font-size:.88rem;margin-top:3px'>Qué calidad de AFE-S entra, cuánto "
        "AG-E se exporta y si el AFE-S bueno alcanza para sostener el ritmo.</div></div>",
        unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return

    # ---------------- configuración ----------------
    c1, c2, c3, c4 = st.columns(4)
    s_b = c1.number_input("Azufre máx. para BUENO (ppm)", 0.0, SPEC_S, 45.0, 1.0, key="ba_sb",
                          help="Un AFE-S es BUENO si su azufre y su fósforo quedan por debajo de "
                               "estos umbrales: es el que banca la dilución del AG-E.")
    p_b = c2.number_input("Fósforo máx. para BUENO (ppm)", 0.0, SPEC_P, 130.0, 5.0, key="ba_pb")
    sem_h = int(c3.selectbox("Ventana de análisis", [8, 13, 26, 52], index=1, key="ba_h",
                             help="Semanas hacia atrás."))
    exp_obj = c4.number_input("Exportación objetivo (t/sem)", 100.0, 3000.0, 900.0, 50.0, key="ba_e",
                              help="Te dicen 800–1000 t semanales.")
    st.caption("Bandas: **BUENO** = S ≤ %g y P ≤ %g · **MEDIO** = dentro de spec pero no bueno · "
               "**MALO** = ya fuera de spec por sí solo (S > %g o P > %g) · **SIN LAB** = el ticket "
               "no tiene análisis." % (s_b, p_b, SPEC_S, SPEC_P))

    _desde = (pd.Timestamp.today() - pd.Timedelta(weeks=sem_h)).date()

    # ---------------- 1 · lo que entra ----------------
    st.markdown("#### 1 · AFE que entra a planta (portería × laboratorio)")
    ing = cat(
        "SELECT p.fecha, to_char(p.fecha,'IYYY·\"S\"IW') AS semana, to_char(p.fecha,'YYYY-MM') AS mes, "
        "COALESCE(p.procedencia,'—') AS proveedor, abs(p.kg) AS kg, "
        "l.ppm_azufre AS s, l.ppm_fosforo AS p "
        "FROM produccion.v_porteria_ticket p "
        "LEFT JOIN LATERAL (SELECT pl.ppm_azufre, pl.ppm_fosforo FROM produccion.procesos_lab pl "
        "  WHERE btrim(pl.ticket)=p.ticket::text AND COALESCE(pl.anulado,false)=false "
        "  ORDER BY pl.fecha DESC NULLS LAST LIMIT 1) l ON true "
        "WHERE p.familia='AFE' AND p.clase IN ('OTRO','INGRESO') AND p.kg IS NOT NULL "
        "AND p.fecha >= %s", (_desde,))
    if ing is None or ing.empty:
        st.info("No hay ingresos de AFE en la ventana elegida.")
        return
    ing = ing.copy()
    for _c in ("kg", "s", "p"):
        ing[_c] = pd.to_numeric(ing[_c], errors="coerce")
    ing["tn"] = ing["kg"] / 1000.0
    ing["banda"] = [(_banda(a, b, s_b, p_b)) for a, b in zip(ing["s"], ing["p"])]

    _tot = float(ing["tn"].sum())
    _clab = ing[ing["banda"] != "SIN LAB"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ingreso total", "%.0f t" % _tot, "%.0f t/sem" % (_tot / sem_h))
    k2.metric("Con lab (S y P)", "%.0f %%" % (100.0 * float(_clab["tn"].sum()) / _tot if _tot else 0))
    _pb = float(ing.loc[ing["banda"] == "BUENO", "tn"].sum())
    k3.metric("BUENO", "%.0f t (%.0f%%)" % (_pb, 100.0 * _pb / _tot if _tot else 0),
              "%.0f t/sem" % (_pb / sem_h))
    _pm = float(ing.loc[ing["banda"].isin(["MEDIO", "MALO"]), "tn"].sum())
    k4.metric("MEDIO + MALO", "%.0f t (%.0f%%)" % (_pm, 100.0 * _pm / _tot if _tot else 0),
              "%.0f t/sem" % (_pm / sem_h))
    st.caption("⚠️ La banda se conoce sólo en lo medido: el **SIN LAB** puede esconder bueno o malo. "
               "Cuanto más mida laboratorio los ingresos, mejor la proyección.")

    _piv = ing.pivot_table(index="semana", columns="banda", values="tn", aggfunc="sum").fillna(0.0)
    for _c in ("BUENO", "MEDIO", "MALO", "SIN LAB"):
        if _c not in _piv.columns:
            _piv[_c] = 0.0
    _piv = _piv[["BUENO", "MEDIO", "MALO", "SIN LAB"]].round(1)
    st.bar_chart(_piv, use_container_width=True)

    ta, tb, tc = st.tabs(["📅 Por semana", "🗓️ Por mes", "🚚 Por proveedor"])
    with ta:
        st.dataframe(_piv.assign(TOTAL=_piv.sum(axis=1).round(1)).reset_index(),
                     hide_index=True, use_container_width=True)
    with tb:
        _pm2 = ing.pivot_table(index="mes", columns="banda", values="tn", aggfunc="sum").fillna(0.0).round(1)
        st.dataframe(_pm2.assign(TOTAL=_pm2.sum(axis=1).round(1)).reset_index(),
                     hide_index=True, use_container_width=True)
    with tc:
        _g = ing.groupby("proveedor").apply(lambda d: pd.Series({
            "t": d["tn"].sum(), "t/sem": d["tn"].sum() / sem_h,
            "S pond (ppm)": _pond(d, "s"), "P pond (ppm)": _pond(d, "p"),
            "% con lab": 100.0 * d.loc[d["banda"] != "SIN LAB", "tn"].sum() / max(d["tn"].sum(), 1e-9),
            "% BUENO (de lo medido)": (100.0 * d.loc[d["banda"] == "BUENO", "tn"].sum()
                                       / max(d.loc[d["banda"] != "SIN LAB", "tn"].sum(), 1e-9)),
        })).reset_index().sort_values("t", ascending=False)
        st.dataframe(_g.round(1), hide_index=True, use_container_width=True,
                     column_config={"% con lab": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                                    "% BUENO (de lo medido)": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})
        st.caption("Con esto se ve **qué proveedor trae el AFE-S bueno** y a quién conviene pedirle "
                   "más volumen (o más análisis de laboratorio).")

    # ---------------- 2 · lo que sale ----------------
    st.markdown("#### 2 · Exportación de AG-E (salidas EGNITRADE → terminales)")
    st.caption("Portería las registra como **AG / ACIDOS GRASOS** con procedencia **EGNITRADE S.L.** "
               "y destino la terminal (SOUTHCROSS, PADILLA, LIBRA, MERCOMAR, INTERALMAR…): eso es lo "
               "que nosotros llamamos **AG-E**. Laboratorio no mide cada contenedor porque son muchos "
               "con la misma fórmula.")
    exp = cat(
        "SELECT p.fecha, to_char(p.fecha,'IYYY·\"S\"IW') AS semana, to_char(p.fecha,'YYYY-MM') AS mes, "
        "COALESCE(p.destino,'—') AS destino, abs(p.kg) AS kg "
        "FROM produccion.v_porteria_ticket p "
        "WHERE p.clase='SALIDA' AND p.kg IS NOT NULL AND p.fecha >= %s", (_desde,))
    exp_sem_prom = 0.0
    if exp is None or exp.empty:
        st.info("No hay salidas de exportación en la ventana.")
    else:
        exp = exp.copy()
        exp["tn"] = pd.to_numeric(exp["kg"], errors="coerce") / 1000.0
        _te = float(exp["tn"].sum()); exp_sem_prom = _te / sem_h
        e1, e2, e3 = st.columns(3)
        e1.metric("Exportado", "%.0f t" % _te, "%.0f t/sem promedio" % exp_sem_prom)
        _uls = exp.groupby("semana")["tn"].sum().sort_index()
        e2.metric("Última semana", "%.0f t" % (float(_uls.iloc[-1]) if len(_uls) else 0.0))
        e3.metric("Camiones", "%d" % len(exp))
        st.bar_chart(_uls.round(1), use_container_width=True)
        with st.expander("Por mes y por terminal"):
            _em = exp.groupby("mes")["tn"].sum().round(1).reset_index()
            _ed = exp.groupby("destino")["tn"].sum().sort_values(ascending=False).round(1).reset_index()
            _x1, _x2 = st.columns(2)
            _x1.dataframe(_em, hide_index=True, use_container_width=True)
            _x2.dataframe(_ed, hide_index=True, use_container_width=True)

    # ---------------- 3 · stock actual por banda ----------------
    st.markdown("#### 3 · Stock actual de AFE-S y AG-E por banda")
    tk = cat("SELECT nombre, producto_principal, litros_actual, capacidad_litros, densidad, "
             "azufre, fosforo, codigo FROM produccion.vw_tanque_panel "
             "WHERE activo AND upper(producto_principal) IN ('AFE-S','AG-E')")
    stock_bueno_t = 0.0
    if tk is None or tk.empty:
        st.info("Sin tanques de AFE-S / AG-E.")
    else:
        tk = tk.copy()
        for _c in ("litros_actual", "capacidad_litros", "densidad", "azufre", "fosforo"):
            tk[_c] = pd.to_numeric(tk[_c], errors="coerce")
        # regla de fondo: en base plana sólo se usa el 90% de la capacidad; en cónicos, el 100%
        _nm = (tk["nombre"].astype(str) + " " + tk["codigo"].astype(str)).str.upper()
        _con = _nm.str.contains("CONIC") | _nm.str.contains("C-NICO") | _nm.str.contains("CÓNICO")
        _resv = (0.10 * tk["capacidad_litros"].fillna(0)).where(~_con, 0.0)
        tk["util_l"] = (tk["litros_actual"].fillna(0) - _resv).clip(lower=0)
        tk["tn"] = tk["util_l"] * tk["densidad"].fillna(DENS_AFE) / 1000.0
        tk["banda"] = [(_banda(a, b, s_b, p_b)) for a, b in zip(tk["azufre"], tk["fosforo"])]
        _afe = tk[tk["producto_principal"].str.upper() == "AFE-S"]
        _age = tk[tk["producto_principal"].str.upper() == "AG-E"]
        stock_bueno_t = float(_afe.loc[_afe["banda"] == "BUENO", "tn"].sum())
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("AFE-S BUENO", "%.0f t" % stock_bueno_t)
        s2.metric("AFE-S MEDIO/MALO", "%.0f t" % float(_afe.loc[_afe["banda"].isin(["MEDIO", "MALO"]), "tn"].sum()))
        s3.metric("AFE-S sin lab", "%.0f t" % float(_afe.loc[_afe["banda"] == "SIN LAB", "tn"].sum()))
        s4.metric("AG-E en tanques", "%.0f t" % float(_age["tn"].sum()))
        st.caption("Toneladas **útiles**: en base plana ya se descontó el 10%% de capacidad que queda "
                   "como fondo de tanque; los cónicos se usan al 100%%.")
        with st.expander("Detalle por tanque"):
            _d = tk.sort_values(["producto_principal", "tn"], ascending=[True, False])[
                ["nombre", "producto_principal", "banda", "util_l", "tn", "azufre", "fosforo"]]
            st.dataframe(_d.rename(columns={"nombre": "Tanque", "producto_principal": "Prod.",
                                            "banda": "Banda", "util_l": "Útil (L)", "tn": "t útiles",
                                            "azufre": "S ppm", "fosforo": "P ppm"}).round(1),
                         hide_index=True, use_container_width=True)

    # ---------------- 4 · proyección ----------------
    st.markdown("#### 4 · ¿Alcanza el AFE-S bueno? (proyección)")
    _lab_in = ing[ing["banda"] != "SIN LAB"]
    _bue = _lab_in[_lab_in["banda"] == "BUENO"]
    _mal = _lab_in[_lab_in["banda"].isin(["MEDIO", "MALO"])]
    s_bueno = _pond(_bue, "s") or 40.0
    p_bueno = _pond(_bue, "p") or 110.0
    s_malo = _pond(_mal, "s") or 47.0
    p_malo = _pond(_mal, "p") or 220.0
    _age_lab = None
    try:
        _age_lab = tk[tk["producto_principal"].str.upper() == "AG-E"]
    except Exception:
        pass
    s_age = (_pond(_age_lab, "azufre", "tn") if _age_lab is not None and not _age_lab.empty else None) or 180.0
    p_age = (_pond(_age_lab, "fosforo", "tn") if _age_lab is not None and not _age_lab.empty else None) or 300.0

    # flujo de bueno: entrada semanal medida + prorrateo del SIN LAB con la misma proporción
    _tn_lab = float(_lab_in["tn"].sum())
    _frac_bueno = (float(_bue["tn"].sum()) / _tn_lab) if _tn_lab > 0 else 0.0
    in_bueno_sem = _frac_bueno * (_tot / sem_h)

    st.caption("Calidades ponderadas medidas — AFE-S bueno: S %.1f / P %.1f · AFE-S medio+malo: "
               "S %.1f / P %.1f · AG-E (tanques): S %.1f / P %.1f. El SIN LAB se prorratea con la "
               "proporción de lo medido (%.0f%% bueno)."
               % (s_bueno, p_bueno, s_malo, p_malo, s_age, p_age, 100 * _frac_bueno))

    filas = []
    for x_pct in (2, 4, 6, 8, 10, 12):
        x = x_pct / 100.0
        # blend en masa: x·AGE + (1-x)·(f·bueno + (1-f)·malo) <= spec  →  f mínima por S y por P
        def _fmin(sa, sb2, sm, lim):
            t = (lim - x * sa) / (1.0 - x)
            if sm <= t:
                return 0.0            # con puro malo alcanza
            if sb2 >= t:
                return None           # ni con puro bueno alcanza
            return (sm - t) / (sm - sb2)
        f_s = _fmin(s_age, s_bueno, s_malo, SPEC_S)
        f_p = _fmin(p_age, p_bueno, p_malo, SPEC_P)
        if f_s is None or f_p is None:
            filas.append({"% AG-E": x_pct, "AFE-S total (t/sem)": round(exp_obj * (1 - x)),
                          "% bueno mín.": None, "Bueno req. (t/sem)": None,
                          "Bueno que entra (t/sem)": round(in_bueno_sem),
                          "Balance (t/sem)": None, "Autonomía stock bueno": "INVIABLE"})
            continue
        f = max(f_s, f_p)
        need = exp_obj * (1 - x) * f
        bal = in_bueno_sem - need
        if bal >= 0:
            auto = "∞ (entra más de lo que se usa)"
        else:
            auto = ("%.1f semanas" % (stock_bueno_t / -bal)) if stock_bueno_t > 0 else "0 semanas"
        filas.append({"% AG-E": x_pct, "AFE-S total (t/sem)": round(exp_obj * (1 - x)),
                      "% bueno mín.": round(100 * f, 1), "Bueno req. (t/sem)": round(need),
                      "Bueno que entra (t/sem)": round(in_bueno_sem),
                      "Balance (t/sem)": round(bal), "Autonomía stock bueno": auto})
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
    st.caption("Lectura: para exportar **%.0f t/sem**, cada fila muestra cuánto AFE-S **bueno** exige "
               "ese %% de AG-E. Balance negativo = se consume más bueno del que entra y el stock "
               "bueno se agota en las semanas indicadas." % exp_obj)

    _ok = [f for f in filas if isinstance(f["Balance (t/sem)"], (int, float)) and f["Balance (t/sem)"] >= 0]
    if _ok:
        _mx = max(_ok, key=lambda f: f["% AG-E"])
        st.success("✅ **%% de AG-E sostenible: hasta ~%d%%.** Por encima, el bueno que entra no "
                   "alcanza y se come el stock." % _mx["% AG-E"])
    else:
        st.error("🔴 Con el ingreso actual de AFE-S bueno, **ningún nivel de AG-E es sostenible** a "
                 "%.0f t/sem: hay que conseguir más AFE-S bueno o bajar la exportación." % exp_obj)

    # ---------------- 5 · cómo ajusta la fórmula de despacho ----------------
    with st.expander("📐 Cómo ajusta esto la fórmula de despacho", expanded=True):
        st.markdown(
            "1. **El AG-E sigue al máximo** que la spec tolere (es lo más barato): eso no cambia.\n"
            "2. **Entre los AFE-S, la sugerencia ahora carga primero los de PEOR calidad** (azufre y "
            "fósforo altos) y va sumando buenos **sólo los necesarios** para que la mezcla cierre en "
            "spec. Antes hacía lo contrario (gastaba los mejores primero) y por eso el bueno se agotaba.\n"
            "3. El **techo sostenible de %% AG-E** sale de la tabla de arriba: si el despacho pide más "
            "AG-E que ese techo, cumple hoy pero funde el stock de bueno en las semanas indicadas.\n"
            "4. Regla operativa: si la autonomía baja de ~4 semanas, o se consigue AFE-S bueno "
            "(ver pestaña por proveedor: quién lo trae), o se baja un punto el %% de AG-E.\n"
            "5. Más análisis de laboratorio en ingresos = menos masa SIN LAB = proyección más firme.")
