# -*- coding: utf-8 -*-
"""Avisar, al cerrar por decantación, que todavía falta el acopio final.

Hay dos caminos para terminar una orden y sólo uno pide el producto final:
  · "🏁 Acopio final" (app.py) valida — sin kilos no deja guardar.
  · "Confirmar decantación" (acá) marca FINALIZADO y genera los movimientos de
    stock, pero nunca escribe kg_obtenido.
Por eso hay 23 órdenes FINALIZADAS sin kilos.

No se rellena kg_obtenido con el valor de la fórmula aunque esté a mano en esta
pantalla: sería comparar la fórmula contra sí misma y daría rendimiento perfecto
siempre. El kilo real lo carga una persona con la medición del tanque o el ticket
de pesada. Acá sólo se avisa, y la bandeja HOY lo recuerda hasta que se cargue.
"""
import io, sys

P = sys.argv[1] if len(sys.argv) > 1 else "app_carga/decantacion.py"
s = io.open(P, encoding="utf-8", newline="").read()

# 1) el checklist dice qué falta DESPUÉS de confirmar
A1 = """    if not _medido:
        st.info("Medí el tanque destino y marcá la casilla: sin medición post-acopio no se puede verificar el rendimiento "
                "real (si se despacha antes de medir, el ingreso queda tapado).")
"""
N1 = """    if not _medido:
        st.info("Medí el tanque destino y marcá la casilla: sin medición post-acopio no se puede verificar el rendimiento "
                "real (si se despacha antes de medir, el ingreso queda tapado).")
    st.caption("⚠️ Confirmar la decantación NO carga los kilos obtenidos. Después de esto entrá a "
               "**🏭 Producción → 🏁 Acopio final** y cargá cuánto salió: sin ese dato la orden queda "
               "cerrada sin rendimiento y aparece en la bandeja HOY hasta que se complete.")
"""

# 2) el mensaje de éxito dice cuál es el paso siguiente
A2 = '''            st.success("Decantación confirmada. Movimientos generados y producción FINALIZADA.")
'''
N2 = '''            st.success("Decantación confirmada. Movimientos generados y producción FINALIZADA.")
            st.warning("Falta el paso final: cargá los kilos obtenidos en **🏭 Producción → 🏁 Acopio final**. "
                       "Hasta entonces esta orden no tiene rendimiento calculable.")
'''

crlf = "\\r\\n" in s
pairs = [(A1, N1), (A2, N2)]
if crlf:
    pairs = [(a.replace("\\n", "\\r\\n"), b.replace("\\n", "\\r\\n")) for a, b in pairs]
for a, b in pairs:
    assert s.count(a) == 1, "ancla no encontrada (%d): %s" % (s.count(a), a[:50])
    s = s.replace(a, b, 1)
io.open(P, "w", encoding="utf-8", newline="").write(s)
print("OK crlf=%s" % crlf)
