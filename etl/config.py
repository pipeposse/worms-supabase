"""worms_supabase / etl / config.py"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT  = BASE_DIR


def _load_dotenv():
    f = PROJECT / ".env"
    if not f.exists(): return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_streamlit_secrets():
    """Si corre en Streamlit Cloud, leer st.secrets también. Fuerza overwrite."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and len(st.secrets) > 0:
            for k in st.secrets.keys():
                try:
                    v = st.secrets[k]
                    # forzar overwrite, no setdefault (puede haber env vacíos)
                    os.environ[k] = str(v)
                except Exception:
                    continue
    except Exception:
        pass


_load_dotenv()
_load_streamlit_secrets()

DATABASE_URL = os.getenv("DATABASE_URL")

# Diagnóstico opcional: si está vacío, imprimir hint (queda en logs de Cloud)
if not DATABASE_URL:
    print("[config] DATABASE_URL vacio. Verificar .env local o Streamlit Secrets.")
if not DATABASE_URL:
    host = os.getenv("PGHOST")
    if host:
        port = os.getenv("PGPORT", "5432")
        user = os.getenv("PGUSER", "postgres")
        pwd  = os.getenv("PGPASSWORD", "")
        db   = os.getenv("PGDATABASE", "postgres")
        ssl  = os.getenv("PGSSLMODE", "require")
        DATABASE_URL = f"postgresql://{user}:{pwd}@{host}:{port}/{db}?sslmode={ssl}"

INPUTS_DIR = BASE_DIR.parent / "00_inputs"
LOGS_DIR   = PROJECT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA_SQL = PROJECT / "01_schema"    / "schema.sql"
SEED_SQL   = PROJECT / "02_seed_data" / "seed.sql"

PRODUCTO_ALIAS = {
    "AFE": "AFE-S", "AFE(S)": "AFE-S", "AFE(SG)": "AFE-SG",
    "AG-A": "AG-A", "AG-B": "AG-B", "AG-C": "AG-C",
    "AG-D": "AG-D", "AG-E": "AG-E",
    "ARE(V)-B": "ARE(V)-B", "ARE(AN)": "ARE(AN)",
    "biodiesel": "ARE(V)-B",
    "glicerina": "GLICERINA-CRUDA", "glicerina_pura": "GLICERINA-PURA",
    "aceite_crudo": "ACEITE-CRUDO",
    "aceite_filtrado": "ACEITE-FILTRADO",
    "aceite_refinado": "ACEITE-REFINADO",
    "SEBO 2DA C": "SEBO-2DA-C", "A PESCADO": "A-PESCADO",
    "BORRA-A": "BORRA-A", "BORRA-B": "BORRA-B",
}

PARAMETRO_ALIAS = {
    "acidez": "prc_acidez", "humedad": "prc_agua", "agua": "prc_agua",
    "sedimentos": "prc_sedimentos", "indice_iodo": "sebo_indice_yodo",
    "azufre": "ppm_azufre", "fosforo": "ppm_fosforo",
    "densidad": "densidad", "color": "color", "concentracion": "concentracion",
}

DATE_FLOOR = "2026-01-01"
