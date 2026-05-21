# Deploy en Streamlit Community Cloud

> Resultado: una URL pública tipo `https://worms-prod.streamlit.app` accesible desde cualquier red. Cero servidor propio. Login obligatorio (PIN) protege la entrada.

---

## 1. Pre-requisitos

- Cuenta en GitHub (gratis).
- Proyecto Supabase ya creado y schema/seed cargados (sección 1-5 de la `GUIA.md`).
- App probada localmente y andando.

---

## 2. Subir el código a GitHub

### 2.1 Crear repo privado
1. github.com → tu avatar → **Your repositories** → **New**.
2. Nombre: `worms` (o lo que quieras).
3. **Private** → Create.

### 2.2 Subir desde tu PC (one-shot)
```bat
cd "C:\Users\fposs\dashboard produccion\worms_supabase"
setup_git.bat
```
Te pide usuario GitHub + nombre del repo, inicializa, hace el primer commit y push. Si el repo no existe en GitHub, te avisa para crearlo (privado, sin README ni gitignore).

> 🔒 `.gitignore` ya excluye `.env`, `__pycache__`, `.venv` y `.streamlit/secrets.toml`. **Verificá que `.env` NO esté en el repo** antes de hacer push.

---

## 3. Crear cuenta en Streamlit Cloud

1. https://streamlit.io/cloud → **Sign up** con GitHub.
2. Autorizar acceso a tus repos.

---

## 4. Crear la app

1. **New app** → seleccioná tu repo `worms`.
2. Branch: `main`
3. Main file path: `app_carga/app.py`
4. App URL: `worms-prod` (queda `worms-prod.streamlit.app`).
5. Click **Advanced settings** → Python version: `3.11`.
6. Deploy.

---

## 5. Cargar las credenciales

Después del primer deploy, la app va a fallar porque no tiene `DATABASE_URL`.

1. En el dashboard de Streamlit Cloud, click **⚙️ Settings** de tu app → **Secrets**.
2. Pegá:

```toml
DATABASE_URL = "postgresql://postgres.PROYECTO:PASSWORD@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
```

(la misma URI que tenés en `.env` local).

3. Save → la app reinicia sola.

---

## 6. Probar

Abrir `https://worms-prod.streamlit.app`. Tiene que aparecer la pantalla de login.

Login: `admin` / PIN `1234` (cambialo en cuanto entres).

---

## 7. Workflow para cambios (el día a día)

Cada vez que querés que un cambio aparezca en la URL pública:

```bat
cd "C:\Users\fposs\dashboard produccion\worms_supabase"
deploy.bat "mensaje del cambio"
```

`deploy.bat` hace `git add .`, `git commit` y `git push` en un solo paso. Streamlit Cloud detecta el push y rebuildea automáticamente en ~1 minuto.

Para verlo:
- https://share.streamlit.io → tu app → "Manage app" → Logs (ahí ves el rebuild en vivo).
- O simplemente refrescá la URL pública al minuto.

> 💡 Si cambiaste el schema o seed, primero corré `setup.bat` local para aplicarlo a Supabase. Streamlit Cloud comparte la BD con local — no necesita migrar nada por su lado.

### Para compartir con un compañero

1. **Solo lectura del dashboard**: pasale la URL pública (`https://worms-prod.streamlit.app`) + un usuario+PIN creados desde la pestaña Admin con rol OPERADOR o SUPERVISOR.
2. **Para que también pueda hacer cambios al código**: invitalo como colaborador del repo en GitHub (Settings → Collaborators). Después él cloná el repo y usa el mismo `deploy.bat`.

---

## 8. Limitaciones del free tier

| Recurso | Límite | Para tu caso |
|---|---|---|
| RAM | 1 GB | Sobra |
| CPU | compartida | Suficiente |
| Apps privadas | 1 | OK |
| Hibernate | tras ~1 semana sin uso | Primera carga del día tarda ~30s, después es instantáneo |
| Tráfico | sin límite duro | OK |

---

## 9. Seguridad

- La URL es **pública**. Cualquiera con el link la ve.
- **Sin login no se puede hacer NADA** (ya está implementado).
- Cada acción queda firmada con `id_usuario` (no falsificable).
- PIN está hasheado SHA-256 en BD.
- Credenciales de Supabase viven solo en Streamlit Secrets (no en código, no en git).

### Hardening opcional
- IP allowlist a nivel Supabase: dashboard → Database → Network restrictions → permitir solo IPs de Streamlit Cloud (ver docs de Streamlit).
- 2FA en GitHub y Streamlit Cloud.

---

## 10. Si tu PC se rompe

Como el código está en GitHub y la BD en Supabase: clonás el repo en otra PC, copias las credenciales, y seguís trabajando. Cero data loss.

```bat
git clone https://github.com/TU_USUARIO/worms.git
cd worms
copy .env.example .env
notepad .env   :: pegar URI
```

---

## 11. Troubleshooting

| Síntoma | Solución |
|---|---|
| Build falla con "no module named X" | falta en `requirements.txt`. Editar y push. |
| App dice "Falta DATABASE_URL" | secret no está cargado. Settings → Secrets → guardar de nuevo. |
| Push falla con "permission denied" | falta auth GitHub. `gh auth login` o reconectar. |
| App lenta primera vez del día | hibernation. Es normal, ~30 s y carga. |
| "No se pudo cargar Consultas IA" | falta `DATABASE_URL_RO` o `GEMINI_API_KEY` en Secrets, o falta una dep en `requirements.txt`. |

---

## 12. Consultas IA (sección Chat · solo lectura)

La sección **🤖 Consultas IA** (visible solo para SUPERVISOR y ADMIN) deja preguntar
en lenguaje natural sobre camiones y laboratorio. Genera SQL con Gemini y lo ejecuta
con un rol Postgres **de solo lectura** (`ai_readonly`), distinto del `DATABASE_URL`
de escritura. No puede modificar datos bajo ninguna circunstancia.

### Secrets adicionales
En *Settings → Secrets*, además de `DATABASE_URL`, agregá:

```toml
DATABASE_URL_RO = "postgresql://ai_readonly.svgmmfcmifsafmdnvhzf:PASSWORD_READONLY@aws-1-us-east-2.pooler.supabase.com:6543/postgres"
GEMINI_API_KEY  = "tu_api_key_de_gemini"   # gratis: https://aistudio.google.com/apikey
GEMINI_MODEL    = "gemini-2.0-flash"
```

### Notas
- El rol `ai_readonly` y las vistas `reporting.v_camiones` / `reporting.v_laboratorio`
  ya están creados en Supabase (migraciones aplicadas).
- El entrenamiento (esquema + ejemplos) se rehace solo en cada arranque en frío.
- Para mejorar respuestas: editar `chat/contexto/business_context.md` y
  `chat/contexto/training_examples.json` y volver a pushear.
