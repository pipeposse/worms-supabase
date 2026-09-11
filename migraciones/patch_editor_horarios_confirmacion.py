# -*- coding: utf-8 -*-
"""El cartelito de "guardado" desaparecía antes de poder leerlo.

Reportado por dirección el 11/09/2026 sobre Centro de Planificación →
Administración de producción → Gestión total, vinculando tickets a reacciones
finalizadas: "el cartelito que aparece se va rápido y no sabés si se guardó o no".

CAUSA. El patrón en las seis acciones de esta pantalla era:

    st.success("Guardado")
    cat.clear(); st.rerun()

`st.success()` escribe el mensaje en el dibujo ACTUAL y `st.rerun()` tira ese
dibujo a la basura un milisegundo después. El cartel existe, pero en una pantalla
que ya no está. Lo que se alcanza a ver es el parpadeo.

QUÉ CAMBIA.

1. La confirmación se guarda ANTES del rerun y se dibuja en el rerun siguiente,
   **y se queda hasta que la persona la cierra**. No se va sola.
2. Aparece donde pasó la cosa, no arriba de todo: si asignó tickets, la ve en el
   bloque de tickets, que es donde está mirando. Para eso cada confirmación lleva
   un `donde` y cada panel dibuja sólo lo suyo.
3. Dice QUÉ pasó, no "guardado": qué tickets, a qué reacción, cuántos kilos y
   **cuánto quedó el total de la reacción**, que es el número que ella tiene que
   controlar. Una confirmación que no trae el dato nuevo obliga a ir a buscarlo.
4. Queda un registro "Lo que se guardó en esta sesión" con hora, hasta 15 líneas.
   Después de vincular ocho tickets se puede repasar todo junto en vez de confiar
   en la memoria.

Idempotente.

    python migraciones/patch_editor_horarios_confirmacion.py app_carga/editor_horarios.py
"""
import io
import sys

HELPERS = '''

# ===================== confirmaciones que no se escapan =====================
# st.success() + st.rerun() pinta el cartel en un dibujo que se descarta enseguida:
# por eso "aparecía y se iba". Acá la confirmación se guarda antes del rerun, se
# dibuja en el siguiente y NO se va sola — la cierra la persona cuando la leyó.
_FLASH = "ehz_flash"
_HIST = "ehz_hist"


def _flash(donde, titulo, detalle=None, tipo="ok"):
    """Deja la confirmación lista para el próximo dibujo. ``donde`` decide en qué
    bloque aparece ('tabla', 'tk:<id>', 'lab:<id>'), así se ve al lado de lo que
    se acaba de hacer y no arriba de todo."""
    from datetime import datetime
    _h = st.session_state.setdefault(_HIST, [])
    _h.insert(0, {"hora": datetime.now().strftime("%H:%M"), "t": titulo,
                  "d": detalle or "", "k": tipo})
    del _h[15:]
    st.session_state[_FLASH] = {"donde": donde, "t": titulo, "d": detalle, "k": tipo}


_FLASH_CSS = """<style>
.ehz-ok{border:1px solid #abefc6;background:#ecfdf3;border-left:3px solid #067647}
.ehz-warn{border:1px solid #fedf89;background:#fffaeb;border-left:3px solid #b54708}
.ehz-box{border-radius:8px;padding:12px 14px}
.ehz-box .t{font-weight:700;font-size:.98rem;color:#16181d;line-height:1.3}
.ehz-box .d{font-size:.87rem;color:#3f434d;margin-top:4px;line-height:1.45}
</style>"""


def _confirmacion(donde):
    """Dibuja la confirmación de este bloque, si la hay. Se queda hasta que la cierren."""
    f = st.session_state.get(_FLASH)
    if not f or f.get("donde") != donde:
        return
    st.markdown(_FLASH_CSS, unsafe_allow_html=True)
    c1, c2 = st.columns([7, 1.5], vertical_alignment="center")
    c1.markdown(
        '<div class="ehz-box ehz-%s"><div class="t">%s %s</div>%s</div>'
        % ("warn" if f.get("k") == "warn" else "ok",
           "⚠️" if f.get("k") == "warn" else "✅",
           f.get("t") or "",
           ('<div class="d">%s</div>' % f["d"]) if f.get("d") else ""),
        unsafe_allow_html=True)
    if c2.button("Entendido", key="ehz_flash_ok", use_container_width=True):
        st.session_state.pop(_FLASH, None)
        st.rerun()


def _historial():
    """Lo guardado en esta sesión, con hora. Para repasar ocho vinculaciones seguidas
    sin depender de haber leído cada cartel."""
    h = st.session_state.get(_HIST) or []
    if not h:
        return
    with st.expander("🕘 Lo que se guardó en esta sesión (%d)" % len(h), expanded=False):
        for x in h:
            st.markdown("**%s** · %s%s" % (x["hora"], x["t"],
                                           ("  \\n&nbsp;&nbsp;&nbsp;%s" % x["d"]) if x["d"] else ""),
                        unsafe_allow_html=True)
        st.caption("Es el registro de esta pantalla en esta sesión; si recargás la página se vacía. "
                   "Lo guardado en la base queda igual.")
'''

CAMBIOS = [
    # ---------------------------------------------------------------- helpers
    ('ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")',
     'ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")' + HELPERS.rstrip() + '\n'),

    # ---------------------------------------------------------------- tabla
    ('''            st.success("Guardado: %d reacción(es) actualizadas." % len(cambios))
            cat.clear()
            st.rerun()''',
     '''            _ids = ", ".join(str(c.get("ident") or c["idb"]) for c in cambios[:6])
            _flash("tabla", "Guardado: %d reacción(es) actualizadas." % len(cambios),
                   "Se tocaron: %s%s. Los cambios ya están en la tabla de arriba."
                   % (_ids, (" y %d más" % (len(cambios) - 6)) if len(cambios) > 6 else ""))
            cat.clear()
            st.rerun()'''),

    # ---------------------------------------------------------------- volver a tickets
    ('''                st.success("Listo: los kilos finales vuelven a salir de los tickets.")
                cat.clear(); st.rerun()''',
     '''                _flash("tk:%d" % idb, "Se borró el cierre manual de %s." % r["ident"],
                       "Los kilos finales vuelven a salir de la suma de los tickets: %.2f t."
                       % (_tot / 1000.0))
                cat.clear(); st.rerun()'''),

    # ---------------------------------------------------------------- asignar tickets
    ('''                st.success("%d ticket(s) asignados al %.0f%%." % (_n, _frac * 100))
                cat.clear(); st.rerun()''',
     '''                _lst = ", ".join("#" + str(cand.iloc[_copt.index(s)]["ticket"]) for s in _sel[:8])
                _flash("tk:%d" % idb,
                       "%d ticket(s) vinculados a %s." % (_n, r["ident"]),
                       "Tickets %s%s · entra el %.0f%% de cada uno · suman %s kg. "
                       "El total de la reacción pasa a %.2f t."
                       % (_lst, (" y %d más" % (len(_sel) - 8)) if len(_sel) > 8 else "",
                          _frac * 100, "{:,.0f}".format(_kg_nuevos).replace(",", "."),
                          (_tot + _kg_nuevos) / 1000.0))
                cat.clear(); st.rerun()'''),

    # sumar los kg realmente asignados para poder informarlos
    ('''                            _n += 1
                        _recompute_final(cur, idb)''',
     '''                            _n += 1
                            _kg_nuevos += _kg
                        _recompute_final(cur, idb)'''),
    ('''            try:
                _n = 0
                with conectar(int(USR["id_usuario"])) as (conn, audit):''',
     '''            try:
                _n, _kg_nuevos = 0, 0.0
                with conectar(int(USR["id_usuario"])) as (conn, audit):'''),

    # ---------------------------------------------------------------- ticket a mano
    ('''                    st.success("Ticket %s asignado." % _mtv)
                    cat.clear(); st.rerun()''',
     '''                    _flash("tk:%d" % idb, "Ticket #%s vinculado a mano a %s." % (_mtv, r["ident"]),
                           "Suma %s kg (fracción %.0f%%). El total de la reacción pasa a %.2f t."
                           % ("{:,.0f}".format(round(_kgv, 0)).replace(",", "."),
                              float(_mf) * 100, (_tot + _kgv) / 1000.0))
                    cat.clear(); st.rerun()'''),

    # ---------------------------------------------------------------- guardar grilla de asignados
    ('''                st.success("Tickets actualizados; los kilos finales se recalcularon.")
                cat.clear(); st.rerun()''',
     '''                _quit = int(sum(1 for i in range(len(edp)) if bool(edp.iloc[i]["Quitar"])))
                _flash("tk:%d" % idb, "Tickets de %s actualizados." % r["ident"],
                       ("Se quitaron %d. " % _quit if _quit else "")
                       + "Los kilos finales se recalcularon sobre los %d ticket(s) que quedan."
                       % (len(edp) - _quit))
                cat.clear(); st.rerun()'''),

    # ---------------------------------------------------------------- laboratorio
    ('''            st.success("Muestra #%d asignada a %s." % (_id_lab, r["ident"]))
            cat.clear(); st.rerun()''',
     '''            _flash("lab:%d" % idb, "Muestra #%d asignada a %s." % (_id_lab, r["ident"]),
                   "La evaluación de laboratorio de esta reacción pasa a salir de esa muestra.")
            cat.clear(); st.rerun()'''),

    ('''            st.success("Asignación quitada; vuelve a resolverse por tickets o por ID.")
            cat.clear(); st.rerun()''',
     '''            _flash("lab:%d" % idb, "Se quitó la muestra asignada a %s." % r["ident"],
                   "El laboratorio de esta reacción vuelve a resolverse por los tickets de pesada "
                   "o por el ticket cargado con el ID.", tipo="warn")
            cat.clear(); st.rerun()'''),

    # -------------------------------------------------- la lista como cola de trabajo
    # La confirmación más fuerte de que algo se guardó es que la fila DESAPAREZCA de
    # lo que falta hacer. Con el filtro y el contador, vincular un ticket se ve como
    # 12 → 11 pendientes, sin depender de haber leído ningún cartel.
    ('''    _sin_l = g3.checkbox("Solo sin lab", value=False, key="ehz_f_sinlab",
                         help="Reacciones sin ninguna evaluación de laboratorio asociada.")''',
     '''    _sin_l = g3.checkbox("Solo sin lab", value=False, key="ehz_f_sinlab",
                         help="Reacciones sin ninguna evaluación de laboratorio asociada.")
    _sin_t = g3.checkbox("Solo sin tickets vinculados", value=False, key="ehz_f_sintk",
                         help="Reacciones terminadas a las que todavía no se les ató ningún "
                              "ticket de balanza. Es la cola de trabajo de esta pantalla: "
                              "cada ticket que vinculás saca una fila de acá.")'''),

    ('''    if _sin_l:
        df = df[df["fuente_lab"].isna()]''',
     '''    if _sin_l:
        df = df[df["fuente_lab"].isna()]
    if _sin_t:
        df = df[df["n_tickets"].fillna(0) <= 0]'''),

    ('''    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Reacciones", len(base))
    k2.metric("Producido (t)", "%.2f" % (base["real_kg"].fillna(0).sum() / 1000.0))
    k3.metric("Sin Final cargado", int((base["real_kg"].fillna(0) <= 0).sum()))
    k4.metric("Sin lab", int(base["fuente_lab"].isna().sum()))''',
     '''    _falta_tk = int((base["n_tickets"].fillna(0) <= 0).sum())
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Reacciones", len(base))
    k2.metric("Producido (t)", "%.2f" % (base["real_kg"].fillna(0).sum() / 1000.0))
    k3.metric("Sin tickets vinculados", _falta_tk,
              help="Lo que falta hacer en esta pantalla. Baja de a uno cada vez que vinculás.")
    k4.metric("Sin Final cargado", int((base["real_kg"].fillna(0) <= 0).sum()))
    k5.metric("Sin lab", int(base["fuente_lab"].isna().sum()))'''),

    # ---------------------------------------------------------------- dónde se dibujan
    ('''def _tickets(USR, cat, conectar, r):
    idb = int(r["id_batch"])''',
     '''def _tickets(USR, cat, conectar, r):
    idb = int(r["id_batch"])
    _confirmacion("tk:%d" % idb)'''),

    ('''def _lab(USR, cat, conectar, r):''',
     '''def _lab(USR, cat, conectar, r):
    _confirmacion("lab:%d" % int(r["id_batch"]))'''),

    ('''    df = cat(SQL_BASE)
    if df is None or df.empty:
        st.info("No hay reacciones finalizadas para editar.")
        return''',
     '''    _confirmacion("tabla")
    _historial()

    df = cat(SQL_BASE)
    if df is None or df.empty:
        st.info("No hay reacciones finalizadas para editar.")
        return'''),
]


def main(destino):
    src = io.open(destino, encoding="utf-8").read()
    if "_confirmacion(" in src:
        print("ya aplicado, no se toca")
        return 0
    for viejo, nuevo in CAMBIOS:
        if viejo not in src:
            print("ERROR: no encontré el anclaje:\n---\n%s\n---" % viejo[:200])
            return 1
        src = src.replace(viejo, nuevo, 1)
    io.open(destino, "w", encoding="utf-8").write(src)
    print("ok: %d cambios" % len(CAMBIOS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "app_carga/editor_horarios.py"))
