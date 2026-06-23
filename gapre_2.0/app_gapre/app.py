"""
GAPRE · Carga de documentos (Canal 2)
Página administrativa: el usuario elige el tipo de línea, completa los datos
y se agrega una fila en la tabla correspondiente del esquema `gapre` en Supabase.

Tipos de línea:
  Clientes   -> ODV (orden de venta) · RECIBOS (cobro) · FACTURAS_CLIENTES
  Proveedores-> ODC (orden de compra) · ODP (orden de pago) · FACTURAS_PROVEEDORES
"""
import datetime as dt
import streamlit as st

import db

st.set_page_config(page_title="GAPRE · Carga Canal 2", page_icon="📑", layout="centered")

UNIDADES = ["Toneladas", "Unidad(es)", "Kilogramos", "Litros", "Servicio"]
MONEDAS = ["ARS", "USD"]
EMPRESA_DEF = "Worms Arg SA-Ej 2024"
NUEVO = "➕ Crear nuevo…"

st.title("📑 GAPRE · Carga de documentos")
st.caption("Canal 2 — alta de líneas en Supabase (esquema `gapre`)")

TIPOS = {
    "ODV · Orden de venta": "odv",
    "RECIBOS · Cobro de cliente": "recibos",
    "FACTURAS_CLIENTES": "facturas_clientes",
    "ODC · Orden de compra": "odc",
    "ODP · Orden de pago": "odp",
    "FACTURAS_PROVEEDORES": "facturas_proveedores",
}
tipo_label = st.selectbox("Tipo de línea a crear", list(TIPOS.keys()))
tipo = TIPOS[tipo_label]
es_cliente = tipo in ("odv", "recibos", "facturas_clientes")

st.divider()


# ---------------------------------------------------------------------------
# Selector / alta de contraparte (cliente o proveedor)
# ---------------------------------------------------------------------------
def selector_contraparte():
    """Devuelve (id, nombre) de la contraparte elegida o creada. None si falta."""
    if es_cliente:
        registros = db.listar_clientes()
        etiqueta = "Cliente"
    else:
        registros = db.listar_proveedores()
        etiqueta = "Proveedor"

    opciones = {f"{r['nombre']}  ·  {r['cuit'] or 's/CUIT'}": r for r in registros}
    sel = st.selectbox(
        f"{etiqueta}", [NUEVO] + list(opciones.keys()),
        help="Escribí para buscar. Si no existe, elegí «Crear nuevo…».",
    )

    if sel != NUEVO:
        r = opciones[sel]
        return r["id"], r["nombre"]

    # --- Alta de contraparte nueva ---
    st.info(f"Nuevo {etiqueta.lower()} — se agregará a la base de {etiqueta.lower()}s.")
    c1, c2 = st.columns(2)
    nombre = c1.text_input(f"Nombre {etiqueta.lower()} *", key="np_nombre")
    cuit = c2.text_input("CUIT", key="np_cuit")
    c3, c4 = st.columns(2)
    direccion = c3.text_input("Dirección", key="np_dir")
    localidad = c4.text_input("Localidad", key="np_loc")
    c5, c6 = st.columns(2)
    telefono = c5.text_input("Teléfono", key="np_tel")
    mail = c6.text_input("Mail", key="np_mail")
    c7, c8, c9 = st.columns(3)
    forma_pago = c7.text_input("Forma de pago", key="np_fp")
    tipo_1o2 = c8.selectbox("1 o 2", ["", "1", "2", "1 Y 2"], key="np_t12")
    plazo = c9.number_input("Plazo (días)", min_value=0, max_value=365, step=1,
                            value=0, key="np_plazo")

    base = dict(
        nombre=(nombre or "").strip() or None,
        cuit=(cuit or "").strip() or None,
        direccion=(direccion or "").strip() or None,
        localidad=(localidad or "").strip() or None,
        telefono=(telefono or "").strip() or None,
        mail=(mail or "").strip() or None,
        forma_pago=(forma_pago or "").strip() or None,
        tipo_1o2=tipo_1o2 or None,
        plazo_dias=int(plazo) or None,
    )

    if es_cliente:
        prods = db.listar_productos()
        prod_opts = ["Linea completa"] + [f"{p['codigo']} · {p['producto']}" for p in prods]
        prod_sel = st.multiselect("Productos principales", prod_opts, key="np_prod")
        base["prod_principal"] = ", ".join(prod_sel) or None
    else:
        cc1, cc2 = st.columns(2)
        base["rubros"] = (cc1.text_input("Rubros", key="np_rub") or "").strip() or None
        base["sector"] = (cc2.text_input("Sector", key="np_sec") or "").strip() or None

    # Marcador para que el submit cree primero la contraparte.
    st.session_state["_nueva_contraparte"] = base
    return None, base["nombre"]


cid, cnombre = selector_contraparte()

st.divider()
st.subheader("Datos del documento")
hoy = dt.date.today()


# ---------------------------------------------------------------------------
# Formularios por tipo
# ---------------------------------------------------------------------------
def num_field(tabla, columna, prefijo):
    try:
        sug = db.sugerir_numero(tabla, columna, prefijo)
    except Exception:
        sug = f"{prefijo} 0001-00000001"
    return st.text_input("Número / Referencia", value=sug)


datos = {}

if tipo == "odv":
    numero = num_field("odv", "referencia", "OV")
    c1, c2 = st.columns(2)
    fecha = c1.date_input("Fecha de la orden", hoy)
    moneda = c2.selectbox("Moneda", MONEDAS)
    cond = st.text_input("Condiciones de pago", "30 Dias")
    desc = st.text_input("Descripción de la línea")
    c3, c4, c5 = st.columns(3)
    unidad = c3.selectbox("Unidad", UNIDADES)
    cantidad = c4.number_input("Cantidad", min_value=0.0, step=1.0, format="%.4f")
    precio = c5.number_input("Precio unit.", min_value=0.0, step=1.0, format="%.4f")
    total = st.number_input("Total", value=float(cantidad * precio), format="%.2f")
    vendedor = st.text_input("Vendedor")
    datos = dict(referencia=numero, fecha_orden=fecha, condiciones_pago=cond,
                 linea_descripcion=desc, unidad_medida=unidad, cantidad=cantidad,
                 precio_unitario=precio, total=total, moneda=moneda, vendedor=vendedor,
                 estado="Orden de venta", empresa=EMPRESA_DEF, cliente_nombre=cnombre)
    fk = "cliente_id"

elif tipo == "recibos":
    numero = num_field("recibos", "numero", "RE-X")
    c1, c2 = st.columns(2)
    fecha = c1.date_input("Fecha", hoy)
    metodo = c2.text_input("Método de pago", "Manual (Banco Bica)")
    c3, c4 = st.columns(2)
    importe = c3.number_input("Importe", step=1.0, format="%.2f")
    total = c4.number_input("Total pago", value=0.0, step=1.0, format="%.2f")
    conc = st.text_input("Líneas conciliadas (factura)")
    datos = dict(numero=numero, fecha=fecha, metodo_pago=metodo, importe=importe,
                 total_pago=total or importe, lineas_conciliadas=conc or None,
                 estado="Pagado", empresa=EMPRESA_DEF, cliente_nombre=cnombre)
    fk = "cliente_id"

elif tipo == "facturas_clientes":
    numero = st.text_input("Número (p.ej. FA-A 00005-00000001)")
    c1, c2 = st.columns(2)
    ffac = c1.date_input("Fecha de factura", hoy)
    fven = c2.date_input("Fecha de vencimiento", hoy)
    c3, c4 = st.columns(2)
    estado = c3.selectbox("Estado", ["Registrado", "Borrador", "Cancelado"])
    epago = c4.selectbox("Estado del pago", ["Sin pagar", "Pagado", "Parcial"])
    desc = st.text_input("Etiqueta / descripción de la línea")
    c5, c6, c7 = st.columns(3)
    lcant = c5.number_input("Cantidad", min_value=0.0, step=1.0, format="%.4f")
    lprecio = c6.number_input("Precio unit.", min_value=0.0, step=1.0, format="%.4f")
    lunidad = c7.selectbox("Unidad", UNIDADES)
    c8, c9 = st.columns(2)
    imp_sin = c8.number_input("Importe sin impuestos", value=float(lcant * lprecio), format="%.2f")
    total = c9.number_input("Total firmado", value=0.0, format="%.2f")
    referencia = st.text_input("Referencia")
    datos = dict(numero=numero, estado=estado, estado_pago=epago, fecha_factura=ffac,
                 fecha_vencimiento=fven, importe_sin_impuestos=imp_sin, total_firmado=total,
                 total_moneda_firmado=total, cantidad_por_pagar=(0 if epago == "Pagado" else total),
                 referencia=referencia or None, linea_etiqueta=desc, linea_cantidad=lcant,
                 linea_precio_unitario=lprecio, linea_unidad_medida=lunidad,
                 cliente_nombre=cnombre)
    fk = "cliente_id"

elif tipo == "odc":
    numero = num_field("odc", "referencia", "OC")
    c1, c2 = st.columns(2)
    fconf = c1.date_input("Fecha de confirmación", hoy)
    flim = c2.date_input("Fecha límite", hoy)
    producto = st.text_input("Producto")
    desc = st.text_input("Descripción de la línea")
    c3, c4, c5 = st.columns(3)
    unidad = c3.selectbox("Unidad", UNIDADES, index=1)
    cantidad = c4.number_input("Cantidad", min_value=0.0, value=1.0, step=1.0, format="%.4f")
    precio = c5.number_input("Precio unit.", min_value=0.0, step=1.0, format="%.4f")
    total = st.number_input("Total", value=float(cantidad * precio), format="%.2f")
    comprador = st.text_input("Comprador")
    datos = dict(referencia=numero, fecha_confirmacion=fconf, fecha_limite=flim,
                 producto=producto or None, linea_descripcion=desc, producto_unidad=unidad,
                 cantidad_total=cantidad, precio_unitario=precio, total=total,
                 comprador=comprador or None, estado="Orden de compra",
                 empresa=EMPRESA_DEF, proveedor_nombre=cnombre)
    fk = "proveedor_id"

elif tipo == "odp":
    numero = num_field("odp", "numero", "OP-X")
    c1, c2 = st.columns(2)
    fecha = c1.date_input("Fecha", hoy)
    metodo = c2.text_input("Método de pago", "Manual (Banco Bica)")
    c3, c4 = st.columns(2)
    importe = c3.number_input("Importe", step=1.0, format="%.2f")
    total = c4.number_input("Total pago", value=0.0, step=1.0, format="%.2f")
    conc = st.text_input("Líneas conciliadas (OC / factura)")
    datos = dict(numero=numero, fecha=fecha, metodo_pago=metodo, importe=importe,
                 total_pago=total or importe, lineas_conciliadas=conc or None,
                 estado="Pagado", empresa=EMPRESA_DEF, proveedor_nombre=cnombre)
    fk = "proveedor_id"

else:  # facturas_proveedores
    numero = st.text_input("Número (p.ej. FA-A 00002-00000001)")
    c1, c2 = st.columns(2)
    ffac = c1.date_input("Fecha de factura", hoy)
    fven = c2.date_input("Fecha de vencimiento", hoy)
    c3, c4 = st.columns(2)
    estado = c3.selectbox("Estado", ["Registrado", "Borrador", "Cancelado"])
    epago = c4.selectbox("Estado del pago", ["Sin pagar", "Pagado", "Parcial"])
    desc = st.text_input("Etiqueta / descripción de la línea")
    c5, c6, c7 = st.columns(3)
    lcant = c5.number_input("Cantidad", min_value=0.0, value=1.0, step=1.0, format="%.4f")
    lprecio = c6.number_input("Precio unit.", step=1.0, format="%.4f")
    lunidad = c7.selectbox("Unidad", UNIDADES, index=1)
    c8, c9 = st.columns(2)
    imp_sin = c8.number_input("Importe sin impuestos", value=float(lcant * lprecio), format="%.2f")
    total = c9.number_input("Total firmado", value=0.0, format="%.2f")
    referencia = st.text_input("Referencia / Origen (OC)")
    datos = dict(numero=numero, estado=estado, estado_pago=epago, fecha_factura=ffac,
                 fecha_vencimiento=fven, importe_sin_impuestos=imp_sin, total_firmado=total,
                 total_moneda_firmado=total, cantidad_por_pagar=(0 if epago == "Pagado" else total),
                 referencia=referencia or None, linea_etiqueta=desc, linea_cantidad=lcant,
                 linea_precio_unitario=lprecio, linea_unidad_medida=lunidad,
                 origen_doc=referencia or None, proveedor_nombre=cnombre)
    fk = "proveedor_id"


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------
st.divider()
if st.button("💾 Guardar línea", type="primary", use_container_width=True):
    errores = []
    if not cnombre:
        errores.append("Falta elegir o nombrar la contraparte.")
    if tipo in ("facturas_clientes", "facturas_proveedores") and not datos.get("numero"):
        errores.append("Las facturas requieren Número.")

    if errores:
        st.error("  •  ".join(errores))
    else:
        try:
            # 1) crear contraparte si es nueva
            if cid is None:
                base = st.session_state.get("_nueva_contraparte")
                if es_cliente:
                    nuevo_id = db.crear_cliente(base)
                else:
                    nuevo_id = db.crear_proveedor(base)
            else:
                nuevo_id = cid

            # 2) insertar el documento
            datos[fk] = nuevo_id
            doc_id = db.insert_returning_id(tipo, datos)
            st.success(f"✅ Línea creada en `gapre.{tipo}` (id {doc_id}).")
            st.session_state.pop("_nueva_contraparte", None)
            st.balloons()
        except Exception as e:
            st.error(f"Error al guardar: {e}")


# ---------------------------------------------------------------------------
# Últimas filas
# ---------------------------------------------------------------------------
with st.expander(f"Ver últimas filas de {tipo}"):
    try:
        rows = db.q(f"select * from gapre.{tipo} order by id desc limit 10")
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.write("Sin registros todavía.")
    except Exception as e:
        st.write(f"No se pudo leer: {e}")
