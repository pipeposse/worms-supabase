#!/usr/bin/env python3
"""
Conector WeDo (ThingsBoard) -> Supabase.
Lee el stock actual de cada tanque (volume / level) desde la API WeDo y lo escribe
en produccion.fact_stock_tanque, usando el vínculo de produccion.dim_tanque_wedo.

Uso:
    python -m etl.wedo_stock descubrir   # lista dispositivos y sus keys de telemetría
    python -m etl.wedo_stock sync        # sincroniza el stock actual (default)

API Key:
    - Variable de entorno WEDO_API_KEY, o
    - archivo we_do/tb_*.txt dentro del repo.

Doc API: ver we_do/Instructivo_WeDo_API_Clientes.pdf
"""
from __future__ import annotations
import os, sys, glob, json, urllib.request, urllib.parse
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from etl.config import DATABASE_URL  # noqa: E402

BASE = "https://iot.we-do.io"


def _api_key() -> str:
    k = os.environ.get("WEDO_API_KEY")
    if k:
        return k.strip()
    for p in glob.glob(str(ROOT / "we_do" / "tb_*.txt")):
        return Path(p).read_text(encoding="utf-8").strip()
    raise SystemExit("Falta la API Key: definí WEDO_API_KEY o dejá we_do/tb_*.txt")


def _get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers={"X-Authorization": "ApiKey " + _api_key()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def listar_dispositivos() -> list[dict]:
    """Dispositivos asignados al usuario (paginado)."""
    out, page = [], 0
    while True:
        d = _get(f"/api/user/devices?pageSize=100&page={page}")
        out += d.get("data", [])
        if not d.get("hasNext"):
            break
        page += 1
    return [{"id": x["id"]["id"], "name": x.get("name"), "label": x.get("label"), "type": x.get("type")} for x in out]


def telemetria(device_id: str, keys: list[str]) -> dict:
    q = urllib.parse.urlencode({"keys": ",".join(keys)})
    d = _get(f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries?{q}")
    res = {}
    for k, v in (d or {}).items():
        if v:
            res[k] = {"value": v[0].get("value"), "ts": v[0].get("ts")}
    return res


def descubrir():
    devs = listar_dispositivos()
    print(f"{len(devs)} dispositivos:")
    for d in devs:
        try:
            ks = _get(f"/api/plugins/telemetry/DEVICE/{d['id']}/keys/timeseries")
        except Exception:
            ks = []
        print(f"  {d['label'] or '?':8} | {d['name']} | {d['type']} | keys: {','.join(ks)}")


def sync():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            cur.execute("SELECT id_tanque, wedo_device_id, key_volumen, key_nivel "
                        "FROM dim_tanque_wedo WHERE activo")
            vinculos = cur.fetchall()
            n = 0
            for id_tanque, dev_id, kvol, kniv in vinculos:
                try:
                    t = telemetria(dev_id, [kvol, kniv])
                except Exception as e:
                    print(f"  ⚠ {dev_id}: {e}")
                    continue
                vol = t.get(kvol, {}).get("value")
                niv = t.get(kniv, {}).get("value")
                ts = t.get(kvol, {}).get("ts") or t.get(kniv, {}).get("ts")
                if vol is None and niv is None:
                    continue
                cur.execute(
                    "INSERT INTO fact_stock_tanque (id_tanque, medido_en, litros, nivel_pct, observaciones) "
                    "VALUES (%s, to_timestamp(%s/1000.0), %s, %s, 'WeDo API')",
                    (id_tanque, ts or 0, vol, niv))
                cur.execute("UPDATE dim_tanque_wedo SET ultima_sync=now() WHERE id_tanque=%s", (id_tanque,))
                n += 1
        conn.commit()
        print(f"✅ Stock sincronizado: {n}/{len(vinculos)} tanques.")
    finally:
        conn.close()


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if modo == "descubrir":
        descubrir()
    else:
        sync()
