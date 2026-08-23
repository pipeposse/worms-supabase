# -*- coding: utf-8 -*-
"""Centro de Planificacion -> Administracion de reacciones: alta de la opcion
'✏️ Edicion rapida' (modulo editor_reacciones)."""
import io
P = "planificacion.py"
s = io.open(P, encoding="utf-8").read()

O = '''        _admin_opts = ["🛠️ Gestión de reacciones", "🏁 Terminadas (objetivo vs real)", "🧴 Decantación ARE", "🫧 Desgomado acuoso", "⏭️ Avanzar fase (manual)"]'''
assert s.count(O) == 1, "m1"
N = '''        _admin_opts = ["🛠️ Gestión de reacciones", "✏️ Edición rápida", "🏁 Terminadas (objetivo vs real)", "🧴 Decantación ARE", "🫧 Desgomado acuoso", "⏭️ Avanzar fase (manual)"]'''
s = s.replace(O, N)

O = '''        if _admin.startswith("🛠️"):
            _gestion_reacciones(USR, cat, conectar)'''
assert s.count(O) == 1, "m2"
N = '''        if _admin.startswith("🛠️"):
            _gestion_reacciones(USR, cat, conectar)
        elif _admin.startswith("✏️"):
            try:
                import editor_reacciones
                editor_reacciones.render(USR, cat, conectar)
            except Exception as _e:
                import traceback as _tb
                st.error("No se pudo cargar Edición rápida: %s" % _e)
                with st.expander("🔧 Detalle técnico"):
                    st.code(_tb.format_exc())'''
s = s.replace(O, N)

io.open(P, "w", encoding="utf-8").write(s)
print("menu edicion rapida ok")
