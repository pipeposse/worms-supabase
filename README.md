# worms_supabase

Sistema de carga de producción WORMS · PostgreSQL en **Supabase** (cloud) + Streamlit.

> 👉 **Setup local:** [`docs/GUIA.md`](docs/GUIA.md) — paso a paso, 30 min.
>
> 🚀 **Deploy a producción (URL pública):** [`docs/DEPLOY_STREAMLIT_CLOUD.md`](docs/DEPLOY_STREAMLIT_CLOUD.md) — gratis, vía Streamlit Community Cloud.

## Características

- **Login obligatorio** — usuario + PIN. Sin login no se puede cargar nada.
- **Auditoría no falsificable** — cada INSERT lleva `id_usuario_carga` (FK a `dim_usuario`), no string libre.
- **Formularios cerrados** — productos, parámetros, unidades, calidades, sectores: todo desplegables con catálogos. No hay texto libre donde haya un dato.
- **Validación por rango** — el `number_input` se limita al rango del parámetro. Si querés cargar fuera de rango, exige motivo escrito.
- **Roles** — OPERADOR / SUPERVISOR / ADMIN. Solo ADMIN puede dar de alta usuarios.
- **Cloud** — la BD vive en Supabase (gratis para tu volumen). Si la PC se apaga, los datos están a salvo.

## Estructura

```
worms_supabase/
├── README.md                este archivo
├── .env.example             template de credenciales (copia a .env)
├── install.bat              instalación all-in-one
├── setup.py / setup.bat     aplica schema + seed a Supabase
├── 01_schema/schema.sql     DDL completo (con dim_usuario)
├── 02_seed_data/seed.sql    catálogos + admin inicial (admin/1234)
├── etl/
│   ├── config.py            lee DATABASE_URL del .env
│   ├── db.py                conexión + login + audit + crear_usuario
│   └── validaciones.py
├── app_carga/
│   ├── app.py               Streamlit con login + tabs (Producción / Mis cargas / Audit / Admin)
│   ├── requirements.txt
│   └── run.bat              levantar la app
└── docs/
    ├── GUIA.md                          guía instalación + admin (empezá acá)
    ├── DEPLOY_STREAMLIT_CLOUD.md        cómo deployar a Streamlit Cloud
    ├── diccionario_datos.md             schema completo, FKs, vistas
    ├── 01_diagnostico_excels_legacy.md  por qué reemplazamos los Excel viejos
    ├── SOP_carga_diaria.md              manual del operador (1 página)
    ├── SOP_operador_primer_uso.md       primer uso del operador
    ├── ROADMAP_3_semanas.md             plan día a día
    └── GANTT.md                         Gantt visual
```

## Quick start

```powershell
# 1. instalación local
cd worms_supabase
install.bat

# 2. crear cuenta + proyecto en supabase.com (gratis, sin tarjeta)
#    copiar el URI de Settings -> Database -> Connection string

# 3. configurar .env
copy .env.example .env
notepad .env                 # pegar URI

# 4. crear schema + seed
setup.bat

# 5. levantar la app
app_carga\run.bat
```

Login inicial: `admin` / PIN `1234`. Cambialo desde la pestaña **⚙️ Admin** apenas entrás.

## Auditoría: cómo funciona

Cada tabla operativa tiene `id_usuario_carga` que apunta a `dim_usuario`. La app **no tiene textbox de usuario** — toma el id del usuario logueado en sesión. Imposible falsificar.

Además, cada INSERT/UPDATE/DELETE genera una fila en `aud_eventos`:
```
id_evento | ts                  | id_usuario | operacion | tabla              | pk_valor | cambios
----------|----------------------|------------|-----------|--------------------|----------|---------
1         | 2026-05-05 09:23:11  | 7 (sosa)   | I         | fact_analisis_lab  | 1234     | {...}
```

Vista `v_audit_resumen` agrupa por usuario para reporting rápido.

## Validaciones (formulario)

| Campo | Validación |
|---|---|
| Fecha | date_input, no permite futuro |
| Producto | selectbox de `dim_producto` (no se puede tipear) |
| Parámetro | selectbox filtrado por corriente del producto |
| Valor | number_input con `min_value`/`max_value` del rango |
| Unidad | selectbox: estándar primero, conversiones disponibles después |
| Fuera de rango | checkbox automático + motivo obligatorio |
| Calidad | selectbox de `dic_calidad` |
| Sector / Turno | selectboxes de catálogo |
| Insumos | selectbox de `dic_insumo` + cantidad numérica |
| Texto libre | solo en `observaciones` y `conclusion`, con max_chars |

## Backup

Supabase free hace backups diarios automáticos (7 días retención). Para más historia: `pg_dump` mensual a NAS. Ver guía.

## Próximos pasos del proyecto

1. Dashboard v1 que reemplaza `Dashboard.html` (otra app Streamlit, solo lectura).
2. Carga histórica de los Excel viejos (a definir si se hace o se empieza limpio).
3. Capacitación operadores con SOP impreso.
