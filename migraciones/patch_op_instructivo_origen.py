# -*- coding: utf-8 -*-
"""De dónde salió la materia prima, en la pantalla de la OP.

`produccion.v_op_origen_mp` reconstruye la cadena OP → tanque → camiones. Mostrarla
en un reporte aparte sería otra pantalla a la que nadie entra: va acá, donde el
operario y el supervisor ya están mirando la orden, como un renglón plegado.

Se dibuja ANTES del early-return del instructivo: una OP sin fórmula tampoco tiene
instructivo, pero sí tiene materia prima y merece decir de dónde vino.
"""
import io, sys

P = sys.argv[1] if len(sys.argv) > 1 else "app_carga/op_instructivo.py"
s = io.open(P, encoding="utf-8", newline="").read()

FUNC = '''
def _origen_mp(cat, id_batch):
    """Cadena de trazabilidad de la MP: ticket de balanza directo, o los camiones
    que llenaron el tanque del que se sacó (origen probable, no lote identificado)."""
    try:
        df = cat("SELECT producto, kg, fuente, tanque, ticket_directo, tickets, origen, "
                 "       n_tickets, entrada_mas_vieja, entrada_mas_nueva "
                 "FROM produccion.v_op_origen_mp WHERE id_batch = %s ORDER BY id_batch_insumo",
                 (int(id_batch),))
    except Exception:
        return
    if df is None or df.empty:
        return
    sin = df[df["origen"].isin(["TANQUE_SIN_TRAZA", "SIN_ORIGEN"])]
    cab = "🚛 Origen de la materia prima"
    if len(sin):
        cab += f" · {len(sin)} sin trazar"
    with st.expander(cab, expanded=False):
        for _, r in df.iterrows():
            kg = _n(r["kg"])
            if r["origen"] == "TICKET":
                st.markdown(f"**{r['producto']}** · {kg} kg — ticket de balanza **{r['ticket_directo']}**")
            elif r["origen"] == "TANQUE_TRAZADO":
                n = int(r["n_tickets"]) if pd.notna(r["n_tickets"]) else 0
                st.markdown(f"**{r['producto']}** · {kg} kg — de **{r['tanque']}**, cargado por "
                            f"{n} camión(es): {r['tickets']}")
            else:
                st.markdown(f"**{r['producto']}** · {kg} kg — de **{r['tanque'] or 'origen no registrado'}**, "
                            "sin entradas registradas")
        if len(sin):
            st.caption("Los tanques de proceso se llenan por trasvase interno desde acopio y ese movimiento "
                       "no se registra: por eso la cadena se corta ahí. Para cerrarla habría que anotar el "
                       "trasvase, no el consumo.")
        st.caption("Cuando la MP sale de un tanque, los camiones son los que lo cargaron antes de este consumo: "
                   "es el origen probable del contenido, no un lote identificado.")


'''

ANCLA_FUNC = "def render(USR, cat, conectar, id_batch):\n"
ANCLA_CALL = """def render(USR, cat, conectar, id_batch):
    _congelar(conectar, cat, USR, id_batch)
"""
NUEVO_CALL = """def render(USR, cat, conectar, id_batch):
    _origen_mp(cat, id_batch)
    _congelar(conectar, cat, USR, id_batch)
"""
crlf = "\\r\\n" in s
if crlf:
    FUNC = FUNC.replace("\\n", "\\r\\n")
    ANCLA_FUNC = ANCLA_FUNC.replace("\\n", "\\r\\n")
    ANCLA_CALL = ANCLA_CALL.replace("\\n", "\\r\\n")
    NUEVO_CALL = NUEVO_CALL.replace("\\n", "\\r\\n")

assert s.count(ANCLA_CALL) == 1, "ancla render (%d)" % s.count(ANCLA_CALL)
s = s.replace(ANCLA_FUNC, FUNC.lstrip("\\r\\n") + ANCLA_FUNC, 1)   # la función, justo antes de render
s = s.replace(ANCLA_CALL, NUEVO_CALL, 1)                           # y la llamada adentro
io.open(P, "w", encoding="utf-8", newline="").write(s)
print("OK crlf=%s" % crlf)
