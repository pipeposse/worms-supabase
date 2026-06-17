"""worms_supabase / setup.py - aplica schema + seed a Supabase."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import psycopg2  # noqa
from etl.config import DATABASE_URL, SCHEMA_SQL, SEED_SQL  # noqa


def run():
    if not DATABASE_URL:
        print("[ERROR] No hay DATABASE_URL. Copiá .env.example a .env y completá.")
        sys.exit(1)
    print("Conectando a Supabase...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    print(f"Aplicando schema ({SCHEMA_SQL.name})...")
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print("   schema OK")
    except Exception as e:
        print(f"   ERROR schema: {e}")
        sys.exit(1)
    print(f"Cargando seed ({SEED_SQL.name})...")
    seed = SEED_SQL.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute(seed)
        print("   seed OK")
    except Exception as e:
        print(f"   ERROR seed: {e}")
        sys.exit(1)

    print("\nDatos cargados:")
    with conn.cursor() as cur:
        cur.execute("SET search_path TO produccion, public")
        for tabla in ("dim_usuario","dim_producto","dim_parametro_lab",
                      "ref_conversion_unidades","ref_meta_produccion","dic_insumo"):
            cur.execute(f"SELECT COUNT(*) FROM {tabla}")
            print(f"   {tabla}: {cur.fetchone()[0]}")
    conn.close()
    print("\nListo.")
    print("Usuario inicial: admin / PIN 1234   (cambialo desde la pestaña Admin)")
    print("Lanzar la app: streamlit run app_carga/app.py")


if __name__ == "__main__":
    run()
