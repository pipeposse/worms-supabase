# GAPRE · App de carga (Canal 2)

Página Streamlit para que el administrativo cargue líneas de documentos y se
inserten en el esquema `gapre` de Supabase, emulando las exportaciones de Odoo.

## Tablas (esquema `gapre`)

Maestros: `clientes`, `proveedores`, `productos`.

Documentos:

| Tipo | Tabla | Contraparte |
|------|-------|-------------|
| Orden de venta | `odv` | cliente |
| Cobro | `recibos` | cliente |
| Factura de cliente | `facturas_clientes` | cliente |
| Orden de compra | `odc` | proveedor |
| Orden de pago | `odp` | proveedor |
| Factura de proveedor | `facturas_proveedores` | proveedor |

## Cómo funciona

1. El administrativo elige el **tipo de línea**.
2. Selecciona el cliente/proveedor (buscador con autocompletado) o elige
   **➕ Crear nuevo…**, que lo da de alta en el maestro correspondiente.
3. Completa los campos básicos del documento.
4. Al guardar, se inserta la fila (y la contraparte nueva, si corresponde).

El **Número/Referencia** de ODV, ODC, RECIBOS y ODP se autosugiere con el
siguiente correlativo; en las facturas se ingresa manualmente.

## Correr local

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # y poné la password
streamlit run app.py
```

## Deploy

Subir a Streamlit Community Cloud / servidor interno y cargar el DSN en
**Secrets**. La conexión es directa a Postgres (psycopg2); no usa PostgREST,
así que no hace falta exponer el esquema `gapre` en la API de Supabase.
