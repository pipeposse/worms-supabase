"""
import_desgomado_acuoso.py
Backfill de los tratamientos de DESGOMADO_ACUOSO (hoja 'TRATAMIENTO REACTOR') a Supabase.

- AFE(SG) -> AFE-SG (inicial),  AFE(S) -> AFE-S (obtenido).
- Merma -> kg_merma.  Fuel Oil (L) -> insumos.fuel_l.
- T inicio/fin + Q horas + % goma/ppm fósforo -> parametros_proceso (jsonb).
- corriente fija = VEGETAL (definido por el usuario).
- inicio_ts = fecha_inicio + hora_inicio_calentamiento ; fin_ts = fecha_fin + hora_fin_calentamiento.
- Idempotente: anti-join por (identificador_unidad, tipo_proceso='DESGOMADO_ACUOSO').

Uso: python import_desgomado_acuoso.py --xlsx <ruta> --out <sql>
"""
import argparse, json, re
from datetime import datetime, time as _time
import pandas as pd

ID_AFE_SG = 2          # producto inicial
ID_AFE_S  = 1          # producto obtenido
BIEN_R2   = 4          # REACTOR_2
ID_USER   = 1          # admin
CORRIENTE = "VEGETAL"
MARKER    = "IMPORT desgomado mayo2026"

def norm_ticket(t):
    return re.sub(r"\s+", "", str(t)).upper()

def sql_lit(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "NULL"
    if isinstance(v, bool): return "TRUE" if v else "FALSE"
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return repr(v)
    return "'" + str(v).replace("'", "''") + "'"

def _combine(d, t):
    if pd.isna(d): return None
    if isinstance(t, _time):
        return datetime.combine(pd.to_datetime(d).date(), t)
    return pd.to_datetime(d).to_pydatetime()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--out", default="import_desgomado.sql")
    a = ap.parse_args()

    df = pd.read_excel(a.xlsx, sheet_name="TRATAMIENTO REACTOR", header=0)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    # localizar columnas por contenido (los headers traen kg/unidades pegadas)
    def col(frag):
        for c in df.columns:
            if frag.lower() in c.lower():
                return c
        return None
    C = {
        "fini": col("Fecha inicio"), "ffin": col("fecha fin"), "reactor": col("Ubicación Reactor"),
        "ntrat": col("tratamiento"), "ticket": col("Ticket"), "stock": col("Pertenencia stock"),
        "pini": col("Producto inicial"), "goma": col("% Goma"), "fosf": col("Fósforo"),
        "qin": col("Q Producto a tratar"), "qout": col("Q Prod. Obtenido"), "merma": col("Q Merma"),
        "pobt": col("Producto Obtenido"), "clasif": col("Clasificacion"), "coment": col("Comentario"),
        "hini": col("Hora inicio calentamiento"), "hfin": col("Hora Fin calentamiento"),
        "qhoras": col("Q Horas"), "tini": col("T inicio"), "tfin": col("T fin"),
        "gasoil": col("Gasoil"), "sulf": col("Sulfurico"), "clorh": col("Clorhídrico"),
        "nacl": col("Cloruro de sodio"), "citrico": col("Citrico"), "fuel": col("Fuel Oil"),
    }
    df = df[df[C["ntrat"]].apply(lambda x: pd.notna(x) and str(x).strip() != "")].copy()

    filas, rep = [], []
    for _, r in df.iterrows():
        tk = norm_ticket(r[C["ticket"]])
        n  = int(r[C["ntrat"]])
        fini = r[C["fini"]]; ffin = r[C["ffin"]]
        ini = _combine(fini, r[C["hini"]])
        fin = _combine(ffin, r[C["hfin"]])
        kg_in  = float(r[C["qin"]])  if pd.notna(r[C["qin"]])  else None
        kg_out = float(r[C["qout"]]) if pd.notna(r[C["qout"]]) else None
        merma  = float(r[C["merma"]]) if pd.notna(r[C["merma"]]) else None
        fuel   = float(r[C["fuel"]]) if pd.notna(r[C["fuel"]]) else None
        qh     = float(r[C["qhoras"]]) if pd.notna(r[C["qhoras"]]) else None
        insumos = {}
        if fuel and fuel > 0: insumos["fuel_l"] = round(fuel, 3)
        for k_ins, c in [("GASOIL", "gasoil"), ("acido_kg", "sulf"), ("cloruro_sodio", "nacl")]:
            v = r[C[c]]
            if pd.notna(v) and float(v) > 0:
                insumos[k_ins] = float(v)
        params = {}
        if pd.notna(r[C["tini"]]): params["temp_inicio_c"] = float(r[C["tini"]])
        if pd.notna(r[C["tfin"]]): params["temp_fin_c"] = float(r[C["tfin"]])
        if pd.notna(r[C["goma"]]): params["pct_goma"] = float(r[C["goma"]])
        if pd.notna(r[C["fosf"]]): params["ppm_fosforo"] = float(r[C["fosf"]])
        if qh: params["q_horas_calentamiento"] = qh

        obs = f"{MARKER} · N°trat {n} · stock {r[C['stock']]}"
        if pd.notna(ffin):
            obs += f" · reposo hasta {pd.to_datetime(ffin).date()}"
        coment = r[C["coment"]]
        if pd.notna(coment) and str(coment).strip():
            obs += f" · {str(coment).strip()}"

        fila = {
            "fecha": pd.to_datetime(fini).date().isoformat() if pd.notna(fini) else None,
            "sector": "REACTORES", "id_usuario_carga": ID_USER, "tipo_operacion": "NORMAL",
            "identificador_unidad": tk,
            "id_producto_inicial": ID_AFE_SG, "kg_inicial": kg_in,
            "id_producto_obtenido": ID_AFE_S, "kg_obtenido": kg_out,  # kg_merma es columna generada (kg_inicial-kg_obtenido)
            "insumos": json.dumps(insumos),
            "id_bien_uso": BIEN_R2, "tipo_proceso": "DESGOMADO_ACUOSO", "etapa_actual": "EN_TANQUE",
            "inicio_ts": ini.isoformat() if ini else None,
            "fin_ts": fin.isoformat() if fin else None,
            "tiempo_estimado_horas": qh,
            "id_producto_buscado": ID_AFE_S,
            "parametros_proceso": json.dumps(params),
            "corriente": CORRIENTE,
            "observaciones": obs, "fuera_de_rango": False,
        }
        filas.append(fila)
        rep.append((n, tk, kg_in, kg_out, merma, fuel, qh,
                    params.get("temp_inicio_c"), params.get("temp_fin_c")))

    # ---- dry-run ----
    print(f"=== DRY-RUN desgomado · {len(filas)} tratamientos ===")
    print("{:>5} {:<9} {:>10} {:>10} {:>8} {:>8} {:>6} {:>6} {:>6}".format(
        "N°", "ticket", "kg_in", "kg_out", "merma", "fuel_L", "horas", "Tini", "Tfin"))
    for x in rep:
        print("{:>5} {:<9} {:>10} {:>10} {:>8} {:>8} {:>6} {:>6} {:>6}".format(
            x[0], x[1],
            f"{x[2]:,.0f}" if x[2] else "-", f"{x[3]:,.0f}" if x[3] else "-",
            f"{x[4]:,.0f}" if x[4] else "-", f"{x[5]:,.1f}" if x[5] else "-",
            f"{x[6]:g}" if x[6] else "-", f"{x[7]:g}" if x[7] is not None else "-",
            f"{x[8]:g}" if x[8] is not None else "-"))

    # ---- SQL idempotente (un INSERT..SELECT guardado por fila) ----
    cols = list(filas[0].keys())
    def val_sql(c, v):
        if c in ("insumos", "parametros_proceso"): return sql_lit(v) + "::jsonb"
        if c in ("inicio_ts", "fin_ts"): return (sql_lit(v) + "::timestamptz") if v else "NULL::timestamptz"
        if c == "fecha": return (sql_lit(v) + "::date") if v else "NULL::date"
        return sql_lit(v)
    out = [f"-- {len(filas)} tratamientos DESGOMADO_ACUOSO mayo 2026 (idempotente)."]
    for f in filas:
        out.append(
            "INSERT INTO produccion.fact_batch_proceso (" + ",".join(cols) + ")\n"
            "SELECT " + ",".join(val_sql(c, f[c]) for c in cols) + "\n"
            "WHERE NOT EXISTS (SELECT 1 FROM produccion.fact_batch_proceso b "
            f"WHERE b.identificador_unidad={sql_lit(f['identificador_unidad'])} AND b.tipo_proceso='DESGOMADO_ACUOSO');")
    open(a.out, "w", encoding="utf-8").write("\n".join(out))
    print(f"\nSQL -> {a.out} ({sum(len(x) for x in out):,} chars)")

if __name__ == "__main__":
    main()
