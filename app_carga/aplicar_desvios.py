# -*- coding: utf-8 -*-
"""
aplicar_desvios.py  —  Aplica en Windows los cambios "Desvios + Variacion semanal -> Direccion".
Idempotente y tolerante: si ya estan aplicados, no hace nada. Corre asi:

    cd "C:\\Users\\fposs\\dashboard produccion\\worms_supabase"
    python app_carga\\aplicar_desvios.py

Edita app_carga\\planificacion.py y app_carga\\app.py. Despues: git add / commit / push.
"""
import os, re, sys, io

HERE = os.path.dirname(os.path.abspath(__file__))
# buscar app_carga (este script vive dentro de app_carga, o al lado)
def _find(base):
    for cand in (base, os.path.join(base, "app_carga")):
        if os.path.exists(os.path.join(cand, "planificacion.py")) and os.path.exists(os.path.join(cand, "app.py")):
            return cand
    return None
APPDIR = _find(HERE) or _find(os.getcwd())
if not APPDIR:
    print("ERROR: no encuentro planificacion.py + app.py. Corré el script desde worms_supabase o app_carga."); sys.exit(1)
print("Carpeta app_carga:", APPDIR)

def rd(p): return io.open(p, encoding="utf-8").read()
def wr(p, s): io.open(p, "w", encoding="utf-8", newline="\n").write(s)

NEW_FUNCS = 'def _desvios_semanal(USR, cat, conectar):\n    """Sección Desvíos (Dirección): stock semana anterior → proyectado con producción → real → desvío."""\n    _desvio_stock_ledger(USR, cat, conectar)\n    st.divider()\n    _reconciliacion_semanal(USR, cat, conectar)\n\n\ndef _desvio_stock_ledger(USR, cat, conectar):\n    st.subheader("📉 Desvíos de stock — proyectado vs real por familia")\n    st.caption("Partimos del **stock de la semana anterior**, le sumamos lo **producido** (y ajustes de portería) para "\n               "obtener cuánto **debería** haber quedado, y lo comparamos con el **stock real** medido al cierre de la semana. "\n               "La diferencia es el **desvío**.")\n    with st.expander("ℹ️ Cómo se calcula"):\n        st.markdown(\n            "**Proyectado = Stock semana anterior + Producción + Ext. entra − Ext. sale − Interno.**\\n\\n"\n            "- **Stock anterior (t)**: stock físico medido en los tanques de la familia al cierre de la semana previa.\\n"\n            "- **Producción (t)**: lo producido por reacciones terminadas de esa familia.\\n"\n            "- **Ext. entra / sale (t)**: ingresos/despachos por portería (proveedores/clientes).\\n"\n            "- **Interno (t)**: consumo por movimiento interno (ej. AG usado para fabricar AG-E).\\n"\n            "- **Proyectado (t)**: lo que *debería* quedar en tanque.\\n"\n            "- **Real (t)**: stock físico medido al cierre de la semana.\\n"\n            "- **Desvío (t) = Real − Proyectado** (🟢 |·|<5 · 🟡 5–20 · 🔴 >20).\\n\\n"\n            "⚠️ Familias de **alto flujo de portería** (AFE, AG) muestran desvíos grandes porque el movimiento de portería "\n            "no coincide 1:1 con el tanque físico (compra/consumo inmediato, subproductos despachados). El desvío es más "\n            "confiable en las familias que **producimos y acumulamos** (ARE, GLICERINA, SEBO).")\n    c1, c2 = st.columns([1, 2])\n    _sem = c1.number_input("Semanas atrás", 2, 52, 8, step=1, key="dsv_sem")\n    df = cat("SELECT semana, familia, stock_ini_t, prod_t, ext_in_t, ext_out_t, interno_t, "\n             "delta_esp_t, stock_proy_t, stock_real_t, desvio_t "\n             "FROM produccion.v_desvio_stock_semanal "\n             "WHERE semana >= (date_trunc(\'week\', now())::date - (%s || \' weeks\')::interval) "\n             "ORDER BY semana DESC, familia", (int(_sem),))\n    if df is None or df.empty:\n        st.info("Sin datos de stock para calcular desvíos."); return\n    df = df.copy()\n    for _c in ["stock_ini_t", "prod_t", "ext_in_t", "ext_out_t", "interno_t", "delta_esp_t",\n               "stock_proy_t", "stock_real_t", "desvio_t"]:\n        df[_c] = pd.to_numeric(df[_c], errors="coerce")\n    _fams = sorted(df["familia"].dropna().unique().tolist())\n    _def = [x for x in ["ARE", "GLICERINA", "SEBO"] if x in _fams] or _fams\n    _fsel = c2.multiselect("Familias", _fams, default=_def, key="dsv_fam",\n                           help="Por defecto las familias que producimos y acumulamos, donde el desvío es más confiable.")\n    dff = (df[df["familia"].isin(_fsel)] if _fsel else df).copy()\n    if dff.empty:\n        st.info("Elegí al menos una familia."); return\n    dff["Semana"] = pd.to_datetime(dff["semana"]).dt.strftime("S%V")\n\n    # --- Semana más reciente: tarjetas por familia ---\n    _ult = dff["semana"].max()\n    _lastw = dff[dff["semana"] == _ult].sort_values("familia")\n    st.markdown(f"**Última semana cerrada · {pd.to_datetime(_ult).strftime(\'S%V · sem del %d/%m\')}**")\n    for _, r in _lastw.iterrows():\n        if pd.isna(r["desvio_t"]):\n            continue\n        _d = float(r["desvio_t"])\n        _clr = "#16a34a" if abs(_d) < 5 else ("#b45309" if abs(_d) < 20 else "#dc2626")\n        cA, cB, cC, cD, cE = st.columns([1.1, 1, 1, 1, 1.1])\n        cA.markdown(f"**{r[\'familia\']}**")\n        cB.metric("Stock ant.", f"{r[\'stock_ini_t\']:,.1f} t" if pd.notna(r[\'stock_ini_t\']) else "—")\n        cC.metric("Proyectado", f"{r[\'stock_proy_t\']:,.1f} t" if pd.notna(r[\'stock_proy_t\']) else "—")\n        cD.metric("Real", f"{r[\'stock_real_t\']:,.1f} t" if pd.notna(r[\'stock_real_t\']) else "—")\n        cE.markdown(f"<div style=\'font-size:.8rem;color:#666\'>Desvío</div>"\n                    f"<div style=\'font-size:1.4rem;font-weight:800;color:{_clr}\'>{_d:+,.1f} t</div>",\n                    unsafe_allow_html=True)\n\n    # --- Gráfico proyectado vs real (última familia / todas) ---\n    try:\n        import altair as alt\n        _cg = dff.dropna(subset=["stock_proy_t", "stock_real_t"]).copy()\n        if not _cg.empty:\n            _orden = _cg.sort_values("semana")["Semana"].drop_duplicates().tolist()\n            _long = _cg.melt(id_vars=["Semana", "familia"], value_vars=["stock_proy_t", "stock_real_t"],\n                             var_name="tipo", value_name="t")\n            _long["tipo"] = _long["tipo"].map({"stock_proy_t": "Proyectado", "stock_real_t": "Real"})\n            _ch = (alt.Chart(_long).mark_bar().encode(\n                    x=alt.X("Semana:O", sort=_orden, title="Semana"),\n                    xOffset=alt.XOffset("tipo:N"),\n                    y=alt.Y("t:Q", title="Stock (t)"),\n                    color=alt.Color("tipo:N", title="", scale=alt.Scale(\n                        domain=["Proyectado", "Real"], range=["#94a3b8", "#2563eb"])),\n                    tooltip=["Semana", "familia", "tipo", alt.Tooltip("t:Q", format=",.1f")])\n                   .properties(height=340))\n            if len(_fsel) > 1:\n                _ch = _ch.facet(row=alt.Row("familia:N", title="")).resolve_scale(y="independent")\n            st.altair_chart(_ch, use_container_width=True)\n    except Exception:\n        pass\n\n    # --- Tabla detalle ---\n    st.markdown("**Detalle semanal**")\n    _disp = dff.rename(columns={"familia": "Familia", "stock_ini_t": "Stock ant. (t)",\n                                "prod_t": "Producción (t)", "ext_in_t": "Ext. entra (t)",\n                                "ext_out_t": "Ext. sale (t)", "interno_t": "Interno (t)",\n                                "stock_proy_t": "Proyectado (t)", "stock_real_t": "Real (t)",\n                                "desvio_t": "Desvío (t)"})\n    _disp = _disp[["Semana", "Familia", "Stock ant. (t)", "Producción (t)", "Ext. entra (t)",\n                   "Ext. sale (t)", "Interno (t)", "Proyectado (t)", "Real (t)", "Desvío (t)"]]\n\n    def _cc(v):\n        if pd.isna(v):\n            return ""\n        a = abs(v)\n        return ("color:#16a34a;font-weight:700" if a < 5 else\n                ("color:#b45309;font-weight:700" if a < 20 else "color:#dc2626;font-weight:700"))\n    _fmt = {c: "{:,.1f}" for c in ["Stock ant. (t)", "Producción (t)", "Ext. entra (t)", "Ext. sale (t)",\n                                   "Interno (t)", "Proyectado (t)", "Real (t)", "Desvío (t)"]}\n    try:\n        st.dataframe(_disp.style.map(_cc, subset=["Desvío (t)"]).format(_fmt, na_rep="—"),\n                     hide_index=True, use_container_width=True)\n    except Exception:\n        st.dataframe(_disp, hide_index=True, use_container_width=True)\n    st.caption("**Desvío**: 🟢 <5 t · 🟡 5–20 t · 🔴 >20 t. Un desvío positivo = quedó más stock del proyectado; "\n               "negativo = quedó menos (salió más, mermó, o producción sin acopiar).")\n\n'
NEW_DIR   = '    elif st.session_state.section == "DIRECCION":\n        # =================== DIRECCIÓN ===================\n        try:\n            import planificacion as _pl\n            st.title("🛂 Dirección")\n            _dir_opts = ["🛂 Aprobaciones", "📉 Desvíos", "📊 Variación semanal"]\n            try:\n                _dir = st.segmented_control("Sección", _dir_opts, default=_dir_opts[0],\n                                            key="dir_grupo_sc", label_visibility="collapsed")\n            except Exception:\n                _dir = st.radio("Sección", _dir_opts, horizontal=True, key="dir_grupo")\n            _dir = _dir or _dir_opts[0]\n            st.write("")\n            if _dir.startswith("📉"):\n                _pl._desvios_semanal(USR, cat, conectar)\n            elif _dir.startswith("📊"):\n                _pl._variacion_semanal(USR, cat, conectar)\n            else:\n                st.caption("Aprobación de planificaciones **fuera de norma**: cargas menores al 80% de la capacidad "\n                           "del reactor o bacha. Mientras el ticket esté pendiente, el operario no puede iniciar la producción.")\n                _pl._render_aprobaciones(USR, cat, conectar, compacto=False)\n        except Exception as _e:\n            import traceback as _tb\n            st.error(f"No se pudo cargar Dirección: {_e}")\n            with st.expander("🔧 Detalle técnico"):\n                st.code(_tb.format_exc())\n'

# ================= planificacion.py =================
pp = os.path.join(APPDIR, "planificacion.py")
plan = rd(pp)
plan0 = plan
report = []

if "_desvio_stock_ledger" in plan:
    report.append("planificacion.py: YA aplicado (funcion _desvio_stock_ledger presente) -> sin cambios")
else:
    # P-a: sacar los 2 items del menu de planificacion
    before = plan
    plan = plan.replace(', "\U0001F4CA Variación semanal", "\U0001F9EE Reconciliación"]', ']')
    report.append("P-a menu _grupo_opts: " + ("OK" if plan != before else "NO ENCONTRADO (revisar manual)"))

    # P-b: sacar los branches de dispatch (📊 y 🧮) del render de planificacion
    before = plan
    plan = re.sub(r'\n\s*if _grupo\.startswith\("\U0001F4CA"\):\n\s*_variacion_semanal\(USR, cat, conectar\)\n\s*return\n', "\n", plan)
    plan = re.sub(r'\n\s*if _grupo\.startswith\("\U0001F9EE"\):\n\s*_reconciliacion_semanal\(USR, cat, conectar\)\n\s*return\n', "\n", plan)
    report.append("P-b dispatch 📊/🧮: " + ("OK" if plan != before else "NO ENCONTRADO (revisar manual)"))

    # P-c: insertar funciones nuevas + renombrar subheader de _reconciliacion_semanal
    old_c = 'def _reconciliacion_semanal(USR, cat, conectar):\n    st.subheader("\U0001F9EE Reconciliación semanal — ¿la producción se ve en los tanques?")'
    new_c = NEW_FUNCS.rstrip("\n") + "\n\n\n" + 'def _reconciliacion_semanal(USR, cat, conectar):\n    st.subheader("\U0001F50E Balance de masa por familia (detalle)")'
    if old_c in plan:
        plan = plan.replace(old_c, new_c, 1)
        report.append("P-c funciones nuevas + subheader: OK")
    else:
        report.append("P-c: NO ENCONTRE el subheader viejo de _reconciliacion_semanal -> NO se insertaron las funciones. AVISAR.")

    if plan != plan0:
        wr(pp, plan)
        report.append(">> planificacion.py GUARDADO")

# ================= app.py =================
ap = os.path.join(APPDIR, "app.py")
appf = rd(ap)
if "dir_grupo_sc" in appf:
    report.append("app.py: YA aplicado (dir_grupo_sc presente) -> sin cambios")
else:
    pat = re.compile(r'    elif st\.session_state\.section == "DIRECCION":.*?\n    elif st\.session_state\.section == "FORMULAS":', re.S)
    if pat.search(appf):
        appf2 = pat.sub(lambda m: NEW_DIR.rstrip("\n") + "\n\n    elif st.session_state.section == \"FORMULAS\":", appf, count=1)
        wr(ap, appf2)
        report.append("app.py bloque DIRECCION reemplazado: OK -> GUARDADO")
    else:
        report.append("app.py: NO ENCONTRE el bloque DIRECCION..FORMULAS. AVISAR.")

print("\n".join(report))
print("\nListo. Ahora: git add app_carga/app.py app_carga/planificacion.py && git commit -m \"Direccion: Desvios + Variacion semanal\" && git push")
