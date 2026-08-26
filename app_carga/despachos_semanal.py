# -*- coding: utf-8 -*-
"""worms_supabase / app_carga / despachos_semanal.py

Despachos → vista "⬇️ Semanal": descarga rápida de los despachos de cada semana con sus
materias primas en TN, como Excel (una hoja por semana + resumen + detalle de líneas) y
PNG (una lámina por semana con gráfico apilado + tabla; más una lámina resumen).

Fuente: fact_despacho × fact_despacho_linea (lo FORMULADO). TN = litros × densidad de la
línea (la misma regla que usa el armador). Se agrupa por producto de la línea (materia
prima / diluyente) y por semana ISO del despacho.
"""

import io
import zipfile
from datetime import date, timedelta

import pandas as pd
import streamlit as st

ESTADOS_DEF = ["CONFIRMADO", "DESPACHADO"]
# colores fijos por materia prima para que todas las láminas se lean igual
COLORES = {"AFE-S": "#2563eb", "AG-E": "#f59e0b", "AFE-AL": "#10b981", "AFE-M": "#8b5cf6",
           "AFE-G": "#14b8a6", "AFE-P": "#0ea5e9", "AG-C": "#ef4444", "AG-A": "#f97316",
           "AG-B": "#fb7185", "ARE-A": "#a16207", "ARE-B": "#78350f", "ARE-A-ANIMAL": "#92400e"}
_PALETA_EXTRA = ["#64748b", "#84cc16", "#e11d48", "#06b6d4", "#a855f7", "#eab308"]


def _color(mp, i):
    return COLORES.get(str(mp), _PALETA_EXTRA[i % len(_PALETA_EXTRA)])


def _sem_label(anio, sem):
    return "%d-S%02d" % (int(anio), int(sem))


def _sem_rango(anio, sem):
    try:
        d1 = date.fromisocalendar(int(anio), int(sem), 1)
        d2 = d1 + timedelta(days=6)
        return "%s–%s" % (d1.strftime("%d/%m"), d2.strftime("%d/%m"))
    except Exception:
        return ""


# ------------------------------------------------------------------ datos

def _lineas(cat, estados, dias):
    return cat(
        "SELECT d.id_despacho, d.titulo, COALESCE(NULLIF(d.cliente,''),'EGNITRADE') AS cliente, d.destino, "
        "       d.producto_codigo AS producto_venta, d.tipo_carga, d.estado, d.fecha_despacho, "
        "       COALESCE(d.anio, EXTRACT(isoyear FROM d.fecha_despacho))::int AS anio, "
        "       COALESCE(d.semana_iso, EXTRACT(week FROM d.fecha_despacho))::int AS semana_iso, "
        "       COALESCE(d.n_contenedores,0) AS n_contenedores, "
        "       l.orden, l.producto_codigo AS mp, t.nombre AS tanque, l.litros, "
        "       COALESCE(l.densidad, p.densidad_g_ml, 0.9) AS densidad, "
        "       l.litros * COALESCE(l.densidad, p.densidad_g_ml, 0.9) AS kg "
        "FROM produccion.fact_despacho d "
        "JOIN produccion.fact_despacho_linea l ON l.id_despacho = d.id_despacho "
        "LEFT JOIN produccion.dim_tanque t ON t.id_tanque = l.id_tanque "
        "LEFT JOIN produccion.dim_producto p ON p.codigo_producto = l.producto_codigo "
        "WHERE d.estado = ANY(%s) AND d.fecha_despacho >= current_date - %s "
        "ORDER BY d.fecha_despacho, d.id_despacho, l.orden", (list(estados), int(dias)))


def _preparar(df):
    df = df.copy()
    for c in ("litros", "densidad", "kg", "n_contenedores"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["tn"] = df["kg"] / 1000.0
    df["mp"] = df["mp"].fillna("?").astype(str)
    df["Semana"] = [_sem_label(a, s) for a, s in zip(df["anio"], df["semana_iso"])]
    df["Rango"] = [_sem_rango(a, s) for a, s in zip(df["anio"], df["semana_iso"])]
    df["fecha_despacho"] = pd.to_datetime(df["fecha_despacho"], errors="coerce")
    return df


def _orden_mp(df):
    """AFE-S primero (es el grueso), después el resto por TN totales."""
    tot = df.groupby("mp")["tn"].sum().sort_values(ascending=False)
    mps = [m for m in tot.index if m == "AFE-S"] + [m for m in tot.index if m != "AFE-S"]
    return mps


def _tabla_semana(df_s, mps):
    """Despachos de una semana × materias primas (TN) + fila TOTAL."""
    cab = (df_s.groupby("id_despacho", sort=False)
               .agg(Despacho=("titulo", "first"), Fecha=("fecha_despacho", "first"),
                    Producto=("producto_venta", "first"), Cliente=("cliente", "first"),
                    Destino=("destino", "first"), Cont=("n_contenedores", "first"))
               .reset_index())
    piv = df_s.pivot_table(index="id_despacho", columns="mp", values="tn", aggfunc="sum", fill_value=0.0)
    piv = piv.reindex(columns=[m for m in mps if m in piv.columns], fill_value=0.0)
    piv["TN total"] = piv.sum(axis=1)
    t = cab.merge(piv.reset_index(), on="id_despacho", how="left").sort_values(["Fecha", "id_despacho"])
    t["Fecha"] = t["Fecha"].dt.strftime("%d/%m/%Y")
    t = t.drop(columns=["id_despacho"])
    mp_cols = [c for c in t.columns if c in mps] + ["TN total"]
    tot = {c: "" for c in t.columns}
    tot["Despacho"] = "TOTAL SEMANA"
    tot["Cont"] = int(t["Cont"].sum())
    for c in mp_cols:
        tot[c] = float(t[c].sum())
    t = pd.concat([t, pd.DataFrame([tot])], ignore_index=True)
    for c in mp_cols:
        t[c] = pd.to_numeric(t[c], errors="coerce").round(2)
    t["Cont"] = pd.to_numeric(t["Cont"], errors="coerce").fillna(0).astype(int)
    return t, mp_cols


def _tabla_resumen(df, mps):
    """Semanas × materias primas (TN) + despachos + contenedores + TN total."""
    piv = df.pivot_table(index=["Semana", "Rango"], columns="mp", values="tn", aggfunc="sum", fill_value=0.0)
    piv = piv.reindex(columns=[m for m in mps if m in piv.columns], fill_value=0.0)
    piv["TN total"] = piv.sum(axis=1)
    n = df.groupby(["Semana", "Rango"]).agg(Despachos=("id_despacho", "nunique"))
    cont = (df.drop_duplicates("id_despacho").groupby(["Semana", "Rango"])["n_contenedores"].sum()
              .rename("Contenedores"))
    r = n.join(cont).join(piv).reset_index().sort_values("Semana")
    tot = {"Semana": "TOTAL", "Rango": "", "Despachos": int(r["Despachos"].sum()),
           "Contenedores": int(r["Contenedores"].sum())}
    for c in [m for m in mps if m in r.columns] + ["TN total"]:
        tot[c] = float(r[c].sum())
    r = pd.concat([r, pd.DataFrame([tot])], ignore_index=True)
    for c in [m for m in mps if m in r.columns] + ["TN total"]:
        r[c] = pd.to_numeric(r[c], errors="coerce").round(2)
    for c in ("Despachos", "Contenedores"):
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(0).astype(int)
    return r


# ------------------------------------------------------------------ Excel

def _excel(df, mps):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    semanas = sorted(df["Semana"].unique().tolist(), reverse=True)
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        res = _tabla_resumen(df, mps)
        res.to_excel(w, sheet_name="Resumen semanal", index=False)
        hojas = [("Resumen semanal", res, ["TN total"] + [m for m in mps if m in res.columns])]
        for s in semanas:
            df_s = df[df["Semana"] == s]
            t, mp_cols = _tabla_semana(df_s, mps)
            nombre = ("%s %s" % (s, df_s["Rango"].iloc[0])).replace("/", "-")[:31]
            t.to_excel(w, sheet_name=nombre, index=False)
            hojas.append((nombre, t, mp_cols))
        det = df[["Semana", "Rango", "fecha_despacho", "titulo", "producto_venta", "cliente", "destino", "estado",
                  "n_contenedores", "orden", "mp", "tanque", "litros", "densidad", "tn"]].copy()
        det["fecha_despacho"] = det["fecha_despacho"].dt.strftime("%d/%m/%Y")
        det = det.rename(columns={"fecha_despacho": "Fecha", "titulo": "Despacho", "producto_venta": "Producto venta",
                                  "cliente": "Cliente", "destino": "Destino", "estado": "Estado",
                                  "n_contenedores": "Cont", "orden": "Línea", "mp": "Materia prima",
                                  "tanque": "Tanque", "litros": "Litros", "densidad": "Densidad", "tn": "TN"})
        det["TN"] = det["TN"].round(3)
        det.to_excel(w, sheet_name="Detalle líneas", index=False)
        hojas.append(("Detalle líneas", det, ["TN"]))

        head_fill = PatternFill("solid", fgColor="1e3a8a")
        tot_fill = PatternFill("solid", fgColor="e0e7ff")
        for nombre, t, num_cols in hojas:
            ws = w.sheets[nombre]
            for c in range(1, len(t.columns) + 1):
                cell = ws.cell(row=1, column=c)
                cell.font = Font(bold=True, color="ffffff")
                cell.fill = head_fill
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                col = t.columns[c - 1]
                if col in num_cols:
                    for r in range(2, len(t) + 2):
                        ws.cell(row=r, column=c).number_format = "#,##0.00"
                elif col in ("Litros",):
                    for r in range(2, len(t) + 2):
                        ws.cell(row=r, column=c).number_format = "#,##0"
                ancho = max([len(str(col))] + [len(str(v)) for v in t[col].head(200).tolist()]) + 2
                ws.column_dimensions[get_column_letter(c)].width = min(max(ancho, 8), 38)
            if nombre != "Detalle líneas":
                for c in range(1, len(t.columns) + 1):
                    cell = ws.cell(row=len(t) + 1, column=c)
                    cell.font = Font(bold=True)
                    cell.fill = tot_fill
            ws.freeze_panes = "B2"
    return buf.getvalue()


# ------------------------------------------------------------------ PNG

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False})
    return plt


def _fmt(v):
    return "{:,.2f}".format(float(v)).replace(",", "@").replace(".", ",").replace("@", ".")


def _png_semana(df_s, mps, semana, rango):
    plt = _plt()
    t, mp_cols = _tabla_semana(df_s, mps)
    cuerpo = t.iloc[:-1]
    total = t.iloc[-1]
    mp_use = [m for m in mp_cols if m != "TN total" and float(t[m].iloc[-1]) > 0]
    n = len(cuerpo)
    alto_bar = max(2.2, 0.55 * n + 1.2)
    alto_tab = max(1.2, 0.34 * (n + 2))
    fig = plt.figure(figsize=(12, alto_bar + alto_tab + 1.1), dpi=150)
    gs = fig.add_gridspec(2, 1, height_ratios=[alto_bar, alto_tab], hspace=0.35)
    ax = fig.add_subplot(gs[0])
    fig.suptitle("Despachos semana %s  ·  %s  ·  %d despachos  ·  %d contenedores  ·  %s TN" % (
        semana, rango, n, int(total["Cont"]), _fmt(total["TN total"])),
        fontsize=12.5, fontweight="bold", x=0.02, ha="left", y=0.995)

    y = list(range(n))[::-1]
    izq = [0.0] * n
    for i, m in enumerate(mp_use):
        vals = cuerpo[m].astype(float).tolist()
        ax.barh(y, vals, left=izq, color=_color(m, i), label=m, height=0.62, edgecolor="white", linewidth=0.5)
        for yi, v, l in zip(y, vals, izq):
            if v >= max(3.0, 0.06 * float(total["TN total"] or 1)):
                ax.text(l + v / 2, yi, _fmt(v), ha="center", va="center", fontsize=7.5, color="white",
                        fontweight="bold")
        izq = [a + b for a, b in zip(izq, vals)]
    for yi, tot_i in zip(y, cuerpo["TN total"].astype(float).tolist()):
        ax.text(tot_i + 0.5, yi, _fmt(tot_i) + " TN", va="center", fontsize=8, fontweight="bold", color="#111827")
    ax.set_yticks(y)
    ax.set_yticklabels(["%s  (%s · %d cont.)" % (r["Despacho"], r["Fecha"][:5], int(r["Cont"]))
                        for _, r in cuerpo.iterrows()], fontsize=8.5)
    ax.set_xlabel("TN formuladas por materia prima")
    ax.set_xlim(0, max(1.0, float(cuerpo["TN total"].max()) * 1.18))
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16 - 0.9 / max(n, 1) * 0.3), ncol=min(len(mp_use), 6),
              frameon=False, fontsize=8)

    axt = fig.add_subplot(gs[1])
    axt.axis("off")
    cols = ["Despacho", "Fecha", "Producto", "Cliente", "Cont"] + mp_use + ["TN total"]
    celdas = []
    for _, r in t.iterrows():
        fila = []
        for c in cols:
            v = r[c]
            if c in mp_use or c == "TN total":
                fila.append(_fmt(v) if float(v or 0) else "—")
            elif c == "Cont":
                fila.append(str(int(v)) if str(v) != "" else "")
            else:
                fila.append(str(v)[:22])
        celdas.append(fila)
    tb = axt.table(cellText=celdas, colLabels=cols, loc="upper center", cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(7.6)
    tb.scale(1, 1.25)
    for (ri, ci), cell in tb.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if ri == 0:
            cell.set_facecolor("#1e3a8a")
            cell.set_text_props(color="white", fontweight="bold")
        elif ri == len(celdas):
            cell.set_facecolor("#e0e7ff")
            cell.set_text_props(fontweight="bold")
        elif ri % 2 == 0:
            cell.set_facecolor("#f8fafc")
    fig.text(0.02, 0.005, "Fuente: formulación de despachos (litros × densidad por línea). Estados: %s." % (
        ", ".join(sorted(df_s["estado"].unique().tolist()))), fontsize=7, color="#6b7280")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _png_resumen(df, mps):
    plt = _plt()
    r = _tabla_resumen(df, mps).iloc[:-1]
    mp_use = [m for m in mps if m in r.columns and float(r[m].sum()) > 0]
    n = len(r)
    fig, ax = plt.subplots(figsize=(max(8, 0.9 * n + 4), 5.2), dpi=150)
    x = list(range(n))
    base = [0.0] * n
    for i, m in enumerate(mp_use):
        vals = r[m].astype(float).tolist()
        ax.bar(x, vals, bottom=base, color=_color(m, i), label=m, width=0.66, edgecolor="white", linewidth=0.5)
        for xi, v, b in zip(x, vals, base):
            if v >= max(5.0, 0.07 * float(r["TN total"].max() or 1)):
                ax.text(xi, b + v / 2, _fmt(v), ha="center", va="center", fontsize=7.5, color="white",
                        fontweight="bold")
        base = [a + b for a, b in zip(base, vals)]
    for xi, tot, nd in zip(x, r["TN total"].astype(float).tolist(), r["Despachos"].tolist()):
        ax.text(xi, tot + float(r["TN total"].max()) * 0.015, "%s TN\n%d desp." % (_fmt(tot), int(nd)),
                ha="center", va="bottom", fontsize=8, fontweight="bold", color="#111827")
    ax.set_xticks(x)
    ax.set_xticklabels(["%s\n%s" % (s, g) for s, g in zip(r["Semana"], r["Rango"])], fontsize=8)
    ax.set_ylabel("TN formuladas")
    ax.set_ylim(0, float(r["TN total"].max() or 1) * 1.22)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper left", ncol=min(len(mp_use), 6), frameon=False, fontsize=8)
    ax.set_title("Despachos por semana y materia prima (TN)  ·  total %s TN en %d despachos" % (
        _fmt(r["TN total"].sum()), int(r["Despachos"].sum())), fontsize=12, fontweight="bold", loc="left")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


@st.cache_data(ttl=300, show_spinner=False)
def _paquete(df, mps):
    """Excel + todos los PNG, comprimidos. Cacheado: se arma una vez por combinación de datos."""
    xlsx = _excel(df, mps)
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("despachos_semanal.xlsx", xlsx)
        z.writestr("resumen_semanas.png", _png_resumen(df, mps))
        for s in sorted(df["Semana"].unique().tolist()):
            df_s = df[df["Semana"] == s]
            z.writestr("despachos_%s.png" % s, _png_semana(df_s, mps, s, df_s["Rango"].iloc[0]))
    return xlsx, zbuf.getvalue()


# ------------------------------------------------------------------ UI

def render(USR, cat, conectar=None):
    st.markdown("#### ⬇️ Despachos por semana — Excel y PNG")
    st.caption("Cada semana con sus despachos y las materias primas formuladas en TN. "
               "Excel: resumen + una hoja por semana + detalle de líneas. PNG: una lámina por semana.")
    f1, f2, f3 = st.columns([1, 1.4, 1.6])
    sem = int(f1.number_input("Semanas hacia atrás", min_value=1, max_value=52, value=8, step=1, key="dsw_sem"))
    est = f2.multiselect("Estados", ["CONFIRMADO", "DESPACHADO", "BORRADOR", "ANULADO"], default=ESTADOS_DEF,
                         key="dsw_est")
    if not est:
        st.info("Elegí al menos un estado.")
        return
    try:
        raw = _lineas(cat, est, sem * 7 + 6)
    except Exception as e:
        st.error("No se pudieron leer los despachos: %s" % e)
        return
    if raw is None or raw.empty:
        st.info("No hay despachos con líneas en ese rango.")
        return
    df = _preparar(raw)
    mps_all = _orden_mp(df)
    selp = f3.multiselect("Materias primas", mps_all, default=mps_all, key="dsw_mp")
    if selp:
        df = df[df["mp"].isin(selp)]
    if df.empty:
        st.info("Sin líneas con esas materias primas.")
        return
    mps = [m for m in mps_all if m in df["mp"].unique()]

    # ---- resumen + descargas globales
    res = _tabla_resumen(df, mps)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Semanas", int(len(res) - 1))
    k2.metric("Despachos", int(res["Despachos"].iloc[-1]))
    k3.metric("Contenedores", int(res["Contenedores"].iloc[-1]))
    k4.metric("TN formuladas", _fmt(res["TN total"].iloc[-1]))
    st.dataframe(res, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in mps + ["TN total"]})

    with st.spinner("Armando Excel y láminas…"):
        try:
            xlsx, zipb = _paquete(df, tuple(mps))
        except Exception as e:
            st.error("No se pudo armar el paquete: %s" % e)
            return
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇️ Excel (todas las semanas)", xlsx, file_name="despachos_semanal.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="dsw_xlsx", use_container_width=True, type="primary")
    d2.download_button("⬇️ PNG resumen semanas", _png_resumen(df, mps), file_name="resumen_semanas.png",
                       mime="image/png", key="dsw_png_res", use_container_width=True)
    d3.download_button("⬇️ ZIP · Excel + PNG de cada semana", zipb, file_name="despachos_semanal.zip",
                       mime="application/zip", key="dsw_zip", use_container_width=True)

    # ---- una semana
    st.markdown("---")
    semanas = sorted(df["Semana"].unique().tolist(), reverse=True)
    c1, c2 = st.columns([1, 3])
    s = c1.selectbox("Semana", semanas, key="dsw_semana",
                     format_func=lambda x: "%s · %s" % (x, df[df["Semana"] == x]["Rango"].iloc[0]))
    df_s = df[df["Semana"] == s]
    t, mp_cols = _tabla_semana(df_s, mps)
    png = _png_semana(df_s, mps, s, df_s["Rango"].iloc[0])
    c2.write("")
    c2.download_button("⬇️ PNG semana %s" % s, png, file_name="despachos_%s.png" % s, mime="image/png",
                       key="dsw_png_sem", use_container_width=True)
    st.dataframe(t, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in mp_cols})
    st.image(png, use_container_width=True)
