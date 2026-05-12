"""worms_supabase / etl / validaciones.py - reglas reusables."""
import pandas as pd
SEV_ERROR = "ERROR"
SEV_WARN  = "WARNING"

def validar_fechas(df, col, floor=None, ceil=None):
    issues = []
    s = pd.to_datetime(df[col], errors="coerce")
    for idx in df.index[s.isna()]:
        issues.append((SEV_ERROR, f"{col}: fecha vacia o invalida", idx))
    if floor:
        for idx in df.index[s < pd.Timestamp(floor)]:
            issues.append((SEV_WARN, f"{col} < {floor}", idx))
    if ceil:
        for idx in df.index[s > pd.Timestamp(ceil)]:
            issues.append((SEV_WARN, f"{col} > {ceil}", idx))
    return issues

def validar_no_nulos(df, cols):
    issues = []
    for c in cols:
        if c not in df.columns:
            issues.append((SEV_ERROR, f"columna obligatoria ausente: {c}", None))
            continue
        for idx in df.index[df[c].isna()]:
            issues.append((SEV_ERROR, f"{c}: nulo", idx))
    return issues

def validar_numerico_positivo(df, cols):
    issues = []
    for c in cols:
        if c not in df.columns: continue
        s = pd.to_numeric(df[c], errors="coerce")
        for idx in df.index[s.isna()]:
            issues.append((SEV_ERROR, f"{c}: no numerico", idx))
        for idx in df.index[s < 0]:
            issues.append((SEV_WARN, f"{c}: negativo", idx))
    return issues

def resumen(issues):
    n_err  = sum(1 for s,_,_ in issues if s == SEV_ERROR)
    n_warn = sum(1 for s,_,_ in issues if s == SEV_WARN)
    return {"errores": n_err, "warnings": n_warn, "detalle": issues}
