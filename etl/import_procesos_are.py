"""
import_procesos_are.py
Backfill de las reacciones ARE del Excel `procesos_are.xlsx` (hoja `proceso`) a Supabase.

- Normaliza producto (AG -C -> AG-C, ARE(V)-B -> ARE-B), reactor, ticket.
- Duracion = fin - inicio (cae a `tiempo total` parseado solo si falta).
- Fusiona Nro RX duplicados (filas de continuacion/correccion).
- Corrige el "drift" de fuel (RX 86-92: la columna trae horas, no litros) -> fuel = NULL.
- Separa `Recuperacion GLI` como salida de decantacion (GLICERINA-CRUDA).
- NaOH: guarda litros y kg (kg = lts * densidad soda).
- Genera SQL idempotente (anti-join por identificador_unidad) y un reporte fila por fila.

Uso:
    python import_procesos_are.py --xlsx <ruta> --out <ruta.sql>   # dry-run + genera SQL
No escribe en la base por si mismo: el SQL se aplica via el MCP de Supabase / psql.
"""
import argparse, json, re, sys
from datetime import datetime
import pandas as pd

# ---- IDs / constantes (de Supabase, esquema produccion) ----
ID_AG_C        = 5
ID_ARE_B       = 41
ID_GLI_CRUDA   = 16           # Recuperacion GLI (byproduct recuperado)
BIEN = {"REACTOR 1": 3, "REACTOR 2": 4}
ID_USER_IMPORT = 1            # admin
DENS_SODA      = 1.33         # kg/L (editable en dic_insumo)
FUEL_MIN_L     = 100.0        # por debajo => dato de fuel invalido (drift de columna)
MARKER         = "IMPORT procesos_are mayo2026"

COLS = {  # nombre crudo (post strip/replace \n) -> alias interno
    "Unnamed: 0":"rx", "Reactor":"reactor", "N° Ticket":"ticket",
    "Inicio Proceso":"inicio", "Final proceso":"fin", "tiempo total":"ttotal",
    "Producto a procesar":"mp", "Cantidad  (lt)":"cant_lt", "Cantidad (KG)":"cant_kg",
    "Glicerina  (lt)":"gli_lt", "Glicerina  (Kg)":"gli_kg",
    "Glicerina recuperada (lt)":"glirec_lt", "NaOH (lts)":"naoh_lt",
    "Recuperación GLI (lts)":"recup_gli_lt",
    "Producciòn ARE (lts)":"are_lt", "Producciòn ARE (KG)":"are_kg",
    "Producto Obtenido":"obt", "Acidez  incial":"acidez_ini", "Acidez   Final":"acidez_fin",
    "Densidad (gr/cm3)":"dens_fin", "% AyS":"ays", "TK Acopio":"tk", "Consumo Fuel      (Lt)":"fuel_lt",
}

def parse_ttotal_horas(v):
    """Solo se usa como fallback. Devuelve horas float o None."""
    if v is None or (isinstance(v, float) and pd.isna(v)): return None
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, datetime): return v.hour + v.minute/60 + v.second/3600  # epoch 1900 -> usar solo hora
    s = str(v).strip()
    m = re.match(r"(?:(\d+)\s*day[s]?,\s*)?(\d+):(\d+):(\d+)", s)
    if m:
        d = int(m.group(1) or 0); h=int(m.group(2)); mi=int(m.group(3))
        return d*24 + h + mi/60
    try: return float(s)
    except: return None

def norm_ticket(t):
    return re.sub(r"\s+", "", str(t)).upper()

def sql_lit(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "NULL"
    if isinstance(v, bool): return "TRUE" if v else "FALSE"
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return repr(v)
    return "'" + str(v).replace("'", "''") + "'"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--out", default="import_mayo.sql")
    a = ap.parse_args()

    df = pd.read_excel(a.xlsx, sheet_name="proceso", header=1)
    df.columns = [str(c).replace("\n"," ").strip() for c in df.columns]
    df = df.rename(columns=COLS)
    df = df[pd.to_numeric(df["rx"], errors="coerce").notna()].copy()
    df["rx"] = df["rx"].astype(int)
    df["inicio_dt"] = pd.to_datetime(df["inicio"], errors="coerce")
    df["fin_dt"]    = pd.to_datetime(df["fin"], errors="coerce")
    # solo mayo 2026
    df = df[(df["inicio_dt"]>="2026-05-01") & (df["inicio_dt"]<"2026-06-01")].copy()

    # ---- fusion de duplicados por ticket normalizado ----
    df["tk_norm"] = df["ticket"].map(norm_ticket)
    grupos = []
    for tk, g in df.groupby("tk_norm", sort=False):
        g = g.copy()
        # base = fila con mas datos (mas no-nulos en cantidades)
        g["score"] = g[["cant_kg","are_kg","gli_kg","naoh_lt"]].notna().sum(axis=1)
        base = g.sort_values("score", ascending=False).iloc[0].to_dict()
        cont = g[g["cant_kg"].isna()]  # filas de continuacion (sin carga)
        # acidez final: tomar la de la continuacion si existe (correccion posterior)
        if not cont.empty and pd.notna(cont.iloc[-1].get("acidez_fin")):
            base["acidez_fin"] = cont.iloc[-1]["acidez_fin"]
        base["_dup"] = len(g) > 1
        base["_rxs"] = ",".join(str(int(x)) for x in sorted(g["rx"].unique()))
        grupos.append(base)

    filas, decant, rep = [], [], []
    for r in grupos:
        tk   = norm_ticket(r["ticket"])
        rx   = int(r["rx"])
        reactor = str(r["reactor"]).strip()
        bien = BIEN.get(reactor)
        inicio = r["inicio_dt"]; fin = r["fin_dt"]
        horas = None
        if pd.notna(inicio) and pd.notna(fin) and fin >= inicio:
            horas = round((fin - inicio).total_seconds()/3600, 2)
        else:
            horas = parse_ttotal_horas(r.get("ttotal"))
        # fuel: corregir drift
        fuel = r.get("fuel_lt")
        fuel = float(fuel) if pd.notna(fuel) else None
        fuel_flag = ""
        if fuel is not None and fuel < FUEL_MIN_L:
            fuel_flag = f"fuel descartado ({fuel:g} ~ horas)"
            fuel = None
        naoh_lt = float(r["naoh_lt"]) if pd.notna(r.get("naoh_lt")) else None
        naoh_kg = round(naoh_lt*DENS_SODA, 2) if naoh_lt is not None else None
        insumos = {}
        if fuel is not None: insumos["fuel_l"] = round(fuel, 3)
        obs = f"{MARKER} · RX {r['_rxs']} · MP {str(r['mp']).strip()} -> {str(r['obt']).strip()}"
        if r["_dup"]: obs += " · [fusion de filas duplicadas]"
        if fuel_flag: obs += f" · [{fuel_flag}]"

        fila = {
            "fecha": inicio.date().isoformat() if pd.notna(inicio) else None,
            "sector": "REACTORES",
            "id_usuario_carga": ID_USER_IMPORT,
            "tipo_operacion": "NORMAL",
            "identificador_unidad": tk,
            "id_producto_inicial": ID_AG_C,
            "kg_inicial": float(r["cant_kg"]) if pd.notna(r.get("cant_kg")) else None,
            "litros_inicial": float(r["cant_lt"]) if pd.notna(r.get("cant_lt")) else None,
            "id_producto_obtenido": ID_ARE_B,
            "kg_obtenido": float(r["are_kg"]) if pd.notna(r.get("are_kg")) else None,
            "litros_obtenido": float(r["are_lt"]) if pd.notna(r.get("are_lt")) else None,
            "calidad_final": "B",
            "insumos": json.dumps(insumos),
            "id_bien_uso": bien,
            "tipo_proceso": "PRODUCCION_ARE",
            "etapa_actual": "EN_TANQUE",
            "inicio_ts": inicio.isoformat() if pd.notna(inicio) else None,
            "fin_ts": fin.isoformat() if pd.notna(fin) else None,
            "tiempo_estimado_horas": horas,
            "id_producto_buscado": ID_ARE_B,
            "calidad_buscada": "B",
            "catalizador_tipo": "NAOH",
            "acidez_oleico_pct": float(r["acidez_ini"]) if pd.notna(r.get("acidez_ini")) else None,
            "q_ag_planeado_kg": float(r["cant_kg"]) if pd.notna(r.get("cant_kg")) else None,
            "gli_fresca_lts": float(r["gli_lt"]) if pd.notna(r.get("gli_lt")) else None,
            "gli_fresca_kg": float(r["gli_kg"]) if pd.notna(r.get("gli_kg")) else None,
            "gli_recup_lts": float(r["glirec_lt"]) if pd.notna(r.get("glirec_lt")) else None,
            "naoh_lts": naoh_lt, "naoh_kg": naoh_kg,
            "corriente": "VEGETAL",
            "acidez_final_pct": float(r["acidez_fin"]) if pd.notna(r.get("acidez_fin")) else None,
            "densidad_final": float(r["dens_fin"]) if pd.notna(r.get("dens_fin")) else None,
            "porc_ays": float(r["ays"]) if pd.notna(r.get("ays")) else None,
            "observaciones": obs,
            "fuera_de_rango": False,
        }
        filas.append(fila)
        # decantacion: Recuperacion GLI (output)
        rg = r.get("recup_gli_lt")
        if pd.notna(rg) and float(rg) > 0:
            decant.append({"ticket": tk, "lts": float(rg), "tk": str(r["tk"]).strip() if pd.notna(r.get("tk")) else None})
        rep.append((rx, tk, reactor, fila["kg_inicial"], fila["kg_obtenido"], fila["acidez_final_pct"],
                    naoh_lt, naoh_kg, float(rg) if pd.notna(rg) else None, horas,
                    insumos.get("fuel_l"), r["_dup"], fuel_flag))

    # ---------- reporte ----------
    print(f"=== DRY-RUN · {len(grupos)} reacciones (de {len(df)} filas; fusionadas {len(df)-len(grupos)}) ===")
    hdr = ("RX","ticket","reactor","AG_kg","ARE_kg","acid_fin","NaOH_l","NaOH_kg","recGLI_l","horas","fuel_l","dup","flag")
    print("{:>6} {:<8} {:<9} {:>9} {:>9} {:>8} {:>7} {:>8} {:>9} {:>6} {:>8} {:>4} {}".format(*hdr))
    for x in rep:
        print("{:>6} {:<8} {:<9} {:>9} {:>9} {:>8} {:>7} {:>8} {:>9} {:>6} {:>8} {:>4} {}".format(
            x[0], x[1], x[2],
            f"{x[3]:,.0f}" if x[3] else "-", f"{x[4]:,.0f}" if x[4] else "-",
            f"{x[5]:g}" if x[5] is not None else "-", f"{x[6]:g}" if x[6] is not None else "-",
            f"{x[7]:g}" if x[7] is not None else "-", f"{x[8]:,.0f}" if x[8] is not None else "-",
            f"{x[9]:g}" if x[9] is not None else "-", f"{x[10]:g}" if x[10] is not None else "-",
            "si" if x[11] else "-", x[12] or ""))
    print(f"\nDecantaciones (Recuperacion GLI) a insertar: {len(decant)}")

    # ---------- SQL idempotente (un INSERT..SELECT guardado por fila;
    #            evita el problema de tipos 'unknown' de un VALUES multi-fila con columnas all-NULL) ----------
    cols = list(filas[0].keys())
    def val_sql(c, v):
        if c == "insumos": return sql_lit(v) + "::jsonb"
        if c in ("inicio_ts","fin_ts"): return (sql_lit(v) + "::timestamptz") if v else "NULL::timestamptz"
        if c == "fecha": return (sql_lit(v) + "::date") if v else "NULL::date"
        return sql_lit(v)

    out = []
    out.append(f"-- {len(filas)} reacciones ARE mayo 2026. Idempotente: anti-join por identificador_unidad.")
    for f in filas:
        sel = ",".join(val_sql(c, f[c]) for c in cols)
        out.append(
            "INSERT INTO produccion.fact_batch_proceso (" + ",".join(cols) + ")\n"
            "SELECT " + sel + "\n"
            "WHERE NOT EXISTS (SELECT 1 FROM produccion.fact_batch_proceso b "
            f"WHERE b.identificador_unidad={sql_lit(f['identificador_unidad'])} AND b.tipo_proceso='PRODUCCION_ARE');")
    # decantaciones
    for d in decant:
        out.append(
            "INSERT INTO produccion.fact_salida_decantacion (id_batch,id_producto,lts,destino_tanque,tipo_salida,id_usuario,observaciones) "
            f"SELECT b.id_batch,{ID_GLI_CRUDA},{d['lts']},{sql_lit(d['tk'])},'glicerina',{ID_USER_IMPORT},'{MARKER}' "
            f"FROM produccion.fact_batch_proceso b WHERE b.identificador_unidad={sql_lit(d['ticket'])} AND b.tipo_proceso='PRODUCCION_ARE' "
            "AND NOT EXISTS (SELECT 1 FROM produccion.fact_salida_decantacion s WHERE s.id_batch=b.id_batch AND s.tipo_salida='glicerina');")
    sql = "\n".join(out)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(sql)
    print(f"\nSQL escrito en: {a.out}  ({len(sql):,} chars)")

if __name__ == "__main__":
    main()
