# -*- coding: utf-8 -*-
"""Alinea con la paleta nueva los bloques de HTML inline que traían sus propios
colores (panel de tanques, stepper de etapas, fuente del dato).

El CSS global no llega a estos porque están escritos a mano en atributos style.
Idempotente: cada reemplazo se aplica sólo si encuentra el texto viejo.

    python migraciones/patch_app_colores_locales.py app_carga/app.py
"""
import io
import sys

CAMBIOS = [
    # --- panel de tanques: gris azulado genérico -> líneas y papel del sistema ---
    ('border:2px solid #cbd5e1;border-radius:9px 9px 16px 16px;',
     'border:2px solid #d2cfc8;border-radius:9px 9px 16px 16px;'),
    ('background:repeating-linear-gradient(0deg,#f8fafc,#f8fafc 9px,#eef2f7 9px,#eef2f7 18px)}',
     'background:repeating-linear-gradient(0deg,#fbfbf9,#fbfbf9 9px,#f1efea 9px,#f1efea 18px)}'),
    ('color:#0f172a;text-shadow:0 1px 2px #fff}', 'color:#16181d;text-shadow:0 1px 2px #fff}'),
    ('.tks{font-size:.72rem;color:#475569;', '.tks{font-size:.72rem;color:#6b7280;'),
    ('.tkv{font-size:.7rem;color:#64748b;', '.tkv{font-size:.7rem;color:#9aa0aa;'),
    ('.tkp{font-size:.66rem;color:#334155;margin-top:3px;background:#f1f5f9;',
     '.tkp{font-size:.66rem;color:#3f434d;margin-top:3px;background:#f4f3f0;'),
    # cabecera de sector: el violeta de marca pasa a ser la regla de acento
    ('border-left:5px solid #4f46e5;background:#eef1fe;border-radius:0 8px 8px 0}',
     'border-left:3px solid #1d4ed8;background:transparent;border-radius:0;'
     'text-transform:uppercase;letter-spacing:.06em;font-size:.78rem;color:#6b7280}'),
    ('.sech{font-weight:800;font-size:1rem;margin:14px 0 2px;padding:4px 10px;',
     '.sech{font-weight:700;margin:18px 0 6px;padding:2px 0 2px 10px;'),
    # origen del dato
    ('<span style="color:#0891b2">🛰️ WeDo</span>', '<span style="color:#0e7490">🛰️ WeDo</span>'),
    ('<span style="color:#7c3aed">✋ Manual</span>', '<span style="color:#6b7280">✋ Manual</span>'),
    # --- stepper de etapas: hecho / actual / pendiente ---
    ('_bg = "#10b981"; _tc = "#475569"', '_bg = "#067647"; _tc = "#6b7280"'),
    ('_bg = "#4f46e5"; _tc = "#4f46e5"', '_bg = "#1d4ed8"; _tc = "#1d4ed8"'),
    ('_bg = "#e2e8f0"; _tc = "#94a3b8"', '_bg = "#e4e2dd"; _tc = "#9aa0aa"'),
]


def main(destino):
    src = io.open(destino, encoding="utf-8").read()
    hechos, salteados = 0, 0
    for viejo, nuevo in CAMBIOS:
        if nuevo in src and viejo not in src:
            salteados += 1
            continue
        if viejo not in src:
            print("AVISO: no encontré -> %s" % viejo[:60])
            salteados += 1
            continue
        src = src.replace(viejo, nuevo)
        hechos += 1
    io.open(destino, "w", encoding="utf-8").write(src)
    print("ok: %d cambios, %d salteados" % (hechos, salteados))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"))
