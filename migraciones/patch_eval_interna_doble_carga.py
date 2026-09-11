# -*- coding: utf-8 -*-
"""La muestra de reacción se guardaba varias veces con el mismo valor.

Es la pantalla donde más se notó lo que reportó dirección el 11/09/2026: 36 de
141 mediciones de los últimos 4 meses eran cargas repetidas, con un caso de 23
filas idénticas en 10 segundos.

Dos causas, las dos acá:

1. Al guardar, los campos NO se vacían. La medición queda escrita en pantalla,
   así que volver a apretar Guardar manda exactamente lo mismo otra vez y parece
   una carga nueva. Ahora se limpian después de guardar bien.
2. Entre el click y el redibujo pasan segundos (se vacía la caché entera y se
   re-ejecuta toda la app). Se agrega un seguro por contenido: si lo que se está
   por guardar es idéntico a lo último guardado en esta sesión, no se manda de
   nuevo y se avisa.

El arreglo de fondo —que el botón no acepte clicks mientras la app trabaja— es
global y va en el CSS (inject_global_css). Esto es lo específico de la pantalla.

    python migraciones/patch_eval_interna_doble_carga.py app_carga/eval_interna.py
"""
import io
import sys

VIEJO = """        if st.button("🧪 Guardar muestra", type="primary", use_container_width=True, key="m_save"):
            if not med:
                st.error("Ingresá al menos una medición.")
            else:
                try:"""

NUEVO = """        _huella = (int(r2["id_batch"]), etapa_m, tuple(sorted(med.items())), (obs_m or "").strip())
        if st.button("🧪 Guardar muestra", type="primary", use_container_width=True, key="m_save"):
            if not med:
                st.error("Ingresá al menos una medición.")
            elif st.session_state.get("m_ultima") == _huella:
                # Mismo batch, misma etapa y los mismos valores que la última que entró:
                # es el segundo click, no una medición nueva.
                st.info("Esa medición ya se guardó recién. Si querés cargar otra, "
                        "cambiá los valores.")
            else:
                try:"""

VIEJO2 = """                    st.session_state["m_flash"] = {"id": int(id_m), "batch": int(r2["id_batch"])}
                    cat.clear()
                    st.rerun()"""

NUEVO2 = """                    st.session_state["m_flash"] = {"id": int(id_m), "batch": int(r2["id_batch"])}
                    st.session_state["m_ultima"] = _huella
                    # Vaciar los campos: si quedan escritos, el próximo click vuelve a
                    # mandar la misma medición y entra como si fuera otra.
                    for _k in [k for k in list(st.session_state.keys()) if k.startswith("m_par_")]:
                        st.session_state.pop(_k, None)
                    st.session_state.pop("m_obs", None)
                    cat.clear()
                    st.rerun()"""


def main(destino):
    src = io.open(destino, encoding="utf-8").read()
    if "m_ultima" in src:
        print("ya aplicado, no se toca")
        return 0
    for viejo, nuevo in ((VIEJO, NUEVO), (VIEJO2, NUEVO2)):
        if viejo not in src:
            print("ERROR: no encontré el anclaje:\n%s" % viejo[:120])
            return 1
        src = src.replace(viejo, nuevo, 1)
    io.open(destino, "w", encoding="utf-8").write(src)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "app_carga/eval_interna.py"))
