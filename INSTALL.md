# Deploy a Render.com

Guía para el programador que va a deployar este dashboard a producción.

## Pre-requisitos

- Cuenta en https://render.com (free tier o Starter $7/mes)
- Repositorio de Git con este código (subirlo a GitHub primero)

## Pasos

1. **Crear repo en GitHub** y subir el código:
   ```bash
   cd fb-catalog-dashboard
   git init
   git add .
   git commit -m "initial dashboard"
   git remote add origin https://github.com/USER/fb-catalog-dashboard.git
   git push -u origin main
   ```

2. **En Render:** New → Blueprint → conectar el repo
   - Render detecta automáticamente `render.yaml` y usa el `Dockerfile`
   - `docker-compose.yml` no se usa en Render; solo corre el contenedor web
   - Configura un MongoDB externo accesible desde Render, idealmente MongoDB Atlas

3. **Variables de entorno (en panel de Render):**
   - `PUBLIC_BASE_URL`: la URL final de Render (ej: `https://fb-catalog-dashboard.onrender.com`) — IMPORTANTE: este es el URL que Meta consultará para el feed CSV
   - `SESSION_SECRET`: Render lo autogenera
   - `MONGODB_URI`: URI de conexion a MongoDB Atlas o cualquier Mongo publico/privado accesible desde Render
   - `MONGODB_DB_NAME`: nombre de la base de datos
   - `TRICK_RUNNER_INTERVAL`: opcional, default `3600`
   - `FB_ACCESS_TOKEN`: opcional, solo como fallback inicial; luego puedes gestionar tokens desde `/setup`

4. **Deploy:** Render construye la imagen Docker y arranca automáticamente

5. **Acceder:** la URL aparece en el panel de Render. Visitar `/setup` para configurar BM, cuenta, página, pixel.

## Notas técnicas

- **MongoDB:** la app usa `MONGODB_URI` y `MONGODB_DB_NAME`; no depende de disco persistente local.
- **Importante:** no uses `mongodb://localhost:27017` ni `host.docker.internal` en Render; desde Render debes usar una URI externa real.
- **Token expiration:** Long-lived tokens duran 60 días. Renovar en Graph API Explorer y actualizar `FB_ACCESS_TOKEN` en Render.
- **Cron interval:** controlado por `TRICK_RUNNER_INTERVAL` (default 3600s = 1h). Cambiar en env si se necesita.
- **Rate limits Meta:** el wrapper hace retry exponencial en 429 / códigos transitorios.

## Variables Mongo recomendadas

1. `MONGODB_URI`: string de conexion, por ejemplo `mongodb+srv://...`
2. `MONGODB_DB_NAME`: nombre de la base, por ejemplo `fb_catalog_dashboard`

## Logs

- Render → Logs tab muestra todos los outputs
- Buscar `[trick]` para ver actividad del cron del truco
- Buscar errores HTTP en respuestas de Meta API

## Health check

El endpoint `/health` retorna `{"status": "ok"}` y se puede usar como healthcheck en Render.

## Backup de la DB

```bash
# Ejemplo con mongodump:
mongodump --uri "$MONGODB_URI" --db "$MONGODB_DB_NAME"
```
