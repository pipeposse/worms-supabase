# -*- coding: utf-8 -*-
"""Tres pedidos textuales de dirección (Sistema WORMS.xlsx) que quedaban sin aplicar.

1. "PRODUCCION EN PLANTA → PRODUCCION SECTOR, planta es la totalidad de sectores".
2. "Ingresos: sacar el gráfico por hora; dejar el listado."
3. El instructivo de la sección pasa a hablar de sector, no de planta.

Idempotente: cada cambio se aplica sólo si encuentra el texto viejo.

    python migraciones/patch_app_pedidos_director.py app_carga/app.py
"""
import io
import sys

GRAFICO_HORA = """                    # Linea por hora (cantidad por franja horaria)
                    st.markdown("**Llegadas por hora**")
                    hr = df_d.copy()
                    hr["hh"] = hr["hora_e"].astype(str).str.slice(0,2)
                    by_hr = hr.groupby("hh").size().reset_index(name="camiones").sort_values("hh")
                    st.bar_chart(by_hr, x="hh", y="camiones", use_container_width=True)
"""
GRAFICO_HORA_NUEVO = """                    # El gráfico por hora lo pidió sacar dirección: el listado de abajo ya
                    # está ordenado por hora y es lo que la gente mira. (Sistema WORMS.xlsx)
"""

CAMBIOS = [
    # 1 · el nombre de la sección, en los tres lugares donde aparece
    ('("INICIAR", "👷 Producción en planta")', '("INICIAR", "👷 Producción Sector")'),
    ('("👷", "Producción en planta", "Elegí una producción planificada por dirección y arrancá la reacción (checklist + caldera).", "INICIAR", "land_iniciar", True)',
     '("👷", "Producción Sector", "Elegí una producción planificada para tu sector y arrancá la reacción (checklist + caldera).", "INICIAR", "land_iniciar", True)'),
    ('No se pudo cargar Producción en planta:', 'No se pudo cargar Producción Sector:'),
    # 2 · fuera el gráfico por hora
    (GRAFICO_HORA, GRAFICO_HORA_NUEVO),
]


def main(destino):
    src = io.open(destino, encoding="utf-8").read()
    hechos = salteados = 0
    for viejo, nuevo in CAMBIOS:
        if viejo not in src:
            print("ya aplicado o no encontrado: %s" % viejo.strip().splitlines()[0][:70])
            salteados += 1
            continue
        src = src.replace(viejo, nuevo)
        hechos += 1
    io.open(destino, "w", encoding="utf-8").write(src)
    print("ok: %d cambios, %d salteados" % (hechos, salteados))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"))
