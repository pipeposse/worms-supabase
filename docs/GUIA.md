# Guía paso a paso · worms_supabase

> 30 minutos de principio a fin, asumiendo que no instalaste nada.

---

## 1. Crear cuenta en Supabase (5 min)

1. https://supabase.com → **Start your project**.
2. Login con GitHub o email. Es **gratis**, sin tarjeta.
3. **New project**:
   - Name: `worms-prod`
   - Database password: clave fuerte. **GUARDALA** en gestor de contraseñas.
   - Region: `South America (São Paulo)` (`sa-east-1`).
   - Plan: Free.
4. Click **Create new project**. Espera ~2 min.

---

## 2. Conseguir cadena de conexión (2 min)

1. **Settings** (engranaje izq abajo) → **Database**.
2. **Connection string** → tab **URI** → modo **Transaction (port 6543)**.
3. Copiá el URI. Reemplazá `[YOUR-PASSWORD]` con la clave del paso 1.

---

## 3. Instalar local (3 min)

```bat
cd "C:\Users\fposs\dashboard produccion\worms_supabase"
install.bat
```

---

## 4. Configurar `.env` (1 min)

```bat
copy .env.example .env
notepad .env
```

Pegá tu URI en `DATABASE_URL=`. Sin comillas.

---

## 5. Crear schema + seed (2 min)

```bat
setup.bat
```

---

## 6. Levantar la app (1 min)

```bat
app_carga\run.bat
```

Vas a ver la URL `http://localhost:8501`. Abrir en Chrome.

---

## 7. Primer login

Pantalla de login:
```
Usuario:  [Administrador (admin) ▼]
PIN:      [● ● ● ●          ]
```

**Usuario: `admin` · PIN: `1234`**

---

## 8. ⚙️ Administración de usuarios

> Pestaña **Admin** — solo visible para usuarios con rol `ADMIN`.

### 8.1 Lo PRIMERO que tenés que hacer

**Cambiar el PIN del admin.** Click en barra lateral → **🔑 Cambiar mi PIN**:
1. PIN actual: `1234`
2. PIN nuevo: el que vos quieras (4-6 dígitos)
3. Repetir

### 8.2 Roles y qué puede hacer cada uno

```
┌─────────────┬──────────────────────────────────────────┐
│  ROL        │  ACCESO                                  │
├─────────────┼──────────────────────────────────────────┤
│ OPERADOR    │ 🏭 Producción · ✏️ Mis cargas            │
│ SUPERVISOR  │ + 🕒 Audit (ver historial completo)      │
│ ADMIN       │ + ⚙️ Admin (gestión de usuarios)         │
└─────────────┴──────────────────────────────────────────┘
```

Cada rol incluye lo de los anteriores.

### 8.3 Crear un usuario nuevo

Pestaña **⚙️ Admin** → expander **➕ Crear nuevo usuario**:

| Campo | Ejemplo | Reglas |
|---|---|---|
| Usuario (login) | `sosa` | minúsculas, sin espacios |
| Nombre completo | `José Sosa` | como aparece en el dropdown del login |
| PIN | `4729` | 4 a 6 dígitos numéricos |
| Rol | `OPERADOR` | tres opciones |
| Sector default | `BACHAS` | opcional, sirve como recordatorio |

Click **Crear usuario**. Listo.

### 8.4 Administrar un usuario existente

1. Pestaña **⚙️ Admin** → desplegás la lista de usuarios.
2. **Seleccionar usuario** del dropdown.
3. Aparecen 3 paneles con acciones:

```
┌───────────────────┬─────────────────────┬─────────────────────────┐
│  Estado           │  Reset PIN          │  Rol / Sector           │
├───────────────────┼─────────────────────┼─────────────────────────┤
│ [Desactivar]      │  PIN nuevo: [____]  │  Rol:    [OPERADOR ▼]   │
│  o [Reactivar]    │  [Resetear PIN]     │  Sector: [BACHAS  ▼]    │
│                   │                     │  [Aplicar cambios]      │
└───────────────────┴─────────────────────┴─────────────────────────┘
```

#### ¿Cuándo usar cada acción?

| Acción | Cuándo |
|---|---|
| **Desactivar** | Empleado se va. NO se borran sus cargas anteriores, sólo no puede volver a entrar. |
| **Reactivar** | Empleado vuelve. Mismo PIN que tenía. |
| **Reset PIN** | Operador olvidó su PIN. Le ponés uno nuevo y se lo decís. |
| **Cambiar Rol** | Promoción a supervisor, alguien que ya no es admin, etc. |
| **Cambiar Sector** | Cambio de área de trabajo. |

### 8.5 Cambiar tu PROPIO PIN (cualquier rol)

Cualquier usuario puede cambiar su propio PIN:
1. Barra lateral → **🔑 Cambiar mi PIN**
2. PIN actual + PIN nuevo + repetir.

### 8.6 Reglas importantes

- **No te podés desactivar a vos mismo** (la app te frena).
- **NO se borran usuarios**, sólo se desactivan. Los datos cargados quedan firmados con su id.
- **Todos los cambios admin quedan en audit** con tu id de administrador.
- Si te quedás sin admin (todos desactivados o cambiaron de rol): conexión directa a la BD (Supabase SQL Editor) y `UPDATE dim_usuario SET rol='ADMIN' WHERE nombre='tu_usuario'`.

---

## 9. Capacitación operadores (10 min por persona)

1. Le decís su usuario y PIN (papelito, no se comparte).
2. Le mostrás el flujo: abrir Chrome → URL → login → cargar.
3. Le explicás qué pestaña usa según su rol.

**Cada cosa que cargue va a quedar firmada con su id**. No se puede falsificar.

---

## 10. Acceso desde otras PCs

Tres opciones, de más simple a más robusto:

| Opción | Descripción | Cuándo |
|---|---|---|
| A | Una PC con la app prendida | Mientras decidís |
| B | Mini PC dedicada (~USD 300) | Solución definitiva on-premise |
| C | Streamlit Cloud (deploy gratis) | Acceso desde cualquier red |

---

## 11. Mantener viva la BD

Supabase free pausa la BD si **no hay actividad por 7 días**. Cualquier login la mantiene activa, así que en práctica casi nunca pasa. Si pasara: dashboard Supabase → click "Restore".

---

## 12. Backup mensual

Desde Supabase → **Database** → **Backups** → **Download** del día.
O por CLI:
```bat
pg_dump "TU_URI_AQUI" -n produccion > worms_backup_2026-05-05.sql
```

---

## 13. Troubleshooting

| Síntoma | Solución |
|---|---|
| Login dice "Usuario o PIN incorrecto" | Verificá el PIN. Si lo olvidaste, otro admin te lo resetea. |
| Login dice "usuario desactivado" | Pedile a un admin que te reactive. |
| Pestaña Admin no aparece | Tu rol no es `ADMIN`. Otro admin te lo cambia. |
| `password authentication failed` | URI mal en `.env`. Sin comillas, sin espacios. |
| `connection refused` | Proyecto pausado por inactividad. Dashboard → Restore. |
| Pantalla de login vacía | Aún no se aplicó el seed. Correr `setup.bat`. |

---

## 14. Si quisieras contraseña en lugar de PIN

El campo `pin_hash` admite cualquier string (hashea SHA-256 lo que le pongas). Para usar contraseña tradicional en lugar de PIN numérico:

1. En `app_carga/app.py`, cambiá la validación `not pin.isdigit() or not (4 <= len(pin) <= 6)` por `len(pin) < 8`.
2. En la pestaña Admin, sacá el `max_chars=6` de los inputs de PIN.

Es un cambio de 5 líneas. PIN se eligió por velocidad de tipeo en planta, no por debilidad de seguridad.

---

## 15. ✏️ Anular registros mal cargados

> Pestaña **Mis cargas** · disponible para todos los usuarios.

### Reglas por rol

| Rol | Qué ve | Ventana de anulación |
|---|---|---|
| OPERADOR | Solo lo que cargó él | 24 horas desde la carga |
| SUPERVISOR | Cargas de todos | 7 días desde la carga |
| ADMIN | Todas las cargas | Sin límite |

### Cómo anular

1. Pestaña **✏️ Mis cargas**.
2. Slider para elegir **días hacia atrás** a mostrar.
3. Tabla con todas las cargas (✅ activo / 🚫 ANULADO).
4. Dropdown **Seleccionar registro para anular**.
5. La app te dice si **podés** anularlo según tu rol y la ventana temporal.
6. Escribís el motivo (mínimo 5 caracteres).
7. Marcás la casilla "Confirmo".
8. Click **🚫 Anular registro**.

### Importante

- **El registro NO se borra.** Queda marcado como anulado, con motivo, quién lo anuló y cuándo.
- La anulación queda en `aud_eventos`.
- Las vistas de KPIs / dashboards filtran automáticamente: `WHERE NOT anulado`.
- Una vez anulado, podés cargar el dato correcto desde la pestaña **🏭 Producción**.
- Si necesitás recuperar datos de un registro anulado, están en la BD: solo no aparecen en reportes.

### Si no podés anular algo

- Si sos OPERADOR y pasaron más de 24 h: **pedile a un supervisor** que lo anule.
- Si sos SUPERVISOR y pasaron más de 7 días: **pedile a un ADMIN**.
- Si sos ADMIN: anulás cualquier cosa.

### Aplicación

Solo aplica a **producción** (incluye recuperación). Laboratorio y efluentes quedan fuera del alcance de este sistema (vienen de otras fuentes).

---

## 16. 🏭 Carga de producción · NORMAL vs RECUPERACIÓN

Cada carga arranca eligiendo el **tipo de operación**:

| Tipo | Cuándo se usa | Materia prima |
|---|---|---|
| **🏭 NORMAL** | Procesamiento estándar (ARE, desgomado, bachas, piletas) | **Obligatoria** — producto inicial + kg inicial |
| **♻️ RECUPERACIÓN** | Solo se obtiene producto, sin consumir MP (limpieza tanques, residuales) | **No se carga** — la app oculta los campos |

### Rangos de kg por producto

Cada producto tiene un **rango habitual** definido (`rango_kg_min` / `rango_kg_max` en `dim_producto`). Si cargás fuera de ese rango:

1. La app muestra `⚠️ Cantidad fuera del rango habitual (X–Y kg)`.
2. Aparece un campo **Motivo fuera de rango** (mín 5 caracteres).
3. Sin motivo, no podés guardar.
4. El registro queda con `fuera_de_rango=TRUE` + el motivo, para reporting.

Para ajustar los rangos, un ADMIN ejecuta en Supabase SQL Editor:
```sql
UPDATE produccion.dim_producto
SET rango_kg_min=10000, rango_kg_max=22000
WHERE codigo_producto='AG-A';
```
