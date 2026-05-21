"""Motor del chat: Vanna (Gemini + ChromaDB) para generar SQL, ejecutado SIEMPRE
con el rol read-only (ai_readonly) y validado por el guardia SELECT-only."""

# ── Fix ChromaDB en Streamlit Community Cloud: su sqlite3 del sistema es viejo.
#    Reemplaza sqlite3 por pysqlite3 ANTES de importar chromadb. (No-op en local.)
try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except Exception:
    pass

import os
import json
import tempfile

import pandas as pd
import psycopg2
import streamlit as st

from . import config_chat as cfg
from .guard import assert_safe, is_select_only

CONTEXTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contexto")


# ──────────────────────── ejecución read-only ────────────────────────
def run_sql_readonly(sql: str) -> pd.DataFrame:
    """Ejecuta SOLO SELECT, con el rol ai_readonly, sesión read-only y timeout."""
    assert_safe(sql)
    conn = psycopg2.connect(cfg.DATABASE_URL_RO)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(cfg.STATEMENT_TIMEOUT_MS)}")
        return pd.read_sql_query(sql, conn)
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


# ──────────────────────── construcción de Vanna ────────────────────────
@st.cache_resource(show_spinner="Inicializando el asistente de consultas…")
def get_vanna():
    from vanna.chromadb import ChromaDB_VectorStore
    from vanna.google import GoogleGeminiChat

    class _V(ChromaDB_VectorStore, GoogleGeminiChat):
        def __init__(self, config=None):
            ChromaDB_VectorStore.__init__(self, config=config)
            GoogleGeminiChat.__init__(self, config=config)

    vn = _V(config={
        "api_key": cfg.GEMINI_API_KEY,
        "model": cfg.GEMINI_MODEL,
        # FS efímero en Cloud: el entrenamiento se rehace en cada arranque (rápido).
        "path": os.path.join(tempfile.gettempdir(), "chroma_worms_reporting"),
    })

    # Vanna ejecuta SQL a través de esta función (read-only + guardia).
    vn.run_sql = run_sql_readonly
    vn.run_sql_is_set = True

    _ensure_trained(vn)
    return vn


def _ensure_trained(vn):
    """Entrena DDL + contexto + ejemplos una sola vez (si está vacío)."""
    try:
        td = vn.get_training_data()
        if td is not None and len(td) > 0:
            return
    except Exception:
        pass

    # 1) DDL de las vistas del esquema reporting
    try:
        df = run_sql_readonly("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'reporting'
            ORDER BY table_name, ordinal_position
        """)
        if df is not None and not df.empty:
            for table, grp in df.groupby("table_name"):
                cols = ",\n  ".join(f"{r.column_name} {r.data_type}" for r in grp.itertuples())
                vn.train(ddl=f"CREATE TABLE reporting.{table} (\n  {cols}\n);")
    except Exception:
        pass

    # 2) documentación de negocio
    doc = os.path.join(CONTEXTO_DIR, "business_context.md")
    if os.path.exists(doc):
        with open(doc, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            vn.train(documentation=text)

    # 3) ejemplos pregunta -> SQL
    ex = os.path.join(CONTEXTO_DIR, "training_examples.json")
    if os.path.exists(ex):
        with open(ex, encoding="utf-8") as f:
            for e in json.load(f):
                vn.train(question=e["question"], sql=e["sql"])


# expone el guardia por conveniencia
__all__ = ["get_vanna", "run_sql_readonly", "is_select_only"]
