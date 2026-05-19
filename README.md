# FB Catalog Dashboard

Dashboard local para crear y gestionar campañas Advantage+ Catalog Ads en Facebook usando el "truco" de in_stock/out_of_stock.

## Features

- ✅ Selector de cuenta publicitaria, BM, página, pixel
- ✅ Crear/editar productos sin Google Sheets externo
- ✅ Feed CSV público auto-generado por catálogo
- ✅ Generador de sets con plantillas (1 sucio + 2 limpios, etc.) y nomenclatura tipo `05_L01_V1+V2+V3`
- ✅ Wizard de campañas con CBO/ABO + todas las estrategias de puja (volumen, cost cap, ROAS, bid cap)
- ✅ Plantillas guardables y reusables
- ✅ Truco automático: cron horario que apaga productos `clean` apenas Facebook aprueba el ad
- ✅ Sincroniza catálogo, feed y product sets directamente a Meta vía API
- ✅ Multi-advertiser opt-out (intenta vía API)

## Setup local

1. **Instalar Python 3.11+**
2. Crear virtualenv y activar:
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```
3. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Copiar `.env.example` a `.env` y rellenar:
   - `PUBLIC_BASE_URL`: en local usa `http://localhost:5000`
   - `MONGODB_URI`: por ejemplo `mongodb://localhost:27017` o tu URI de Atlas
   - `MONGODB_DB_NAME`: por ejemplo `fb_catalog_dashboard`
   - `FB_ACCESS_TOKEN`: opcional; también puedes guardarlo desde `/setup`
5. Correr:
   ```bash
   python run.py
   ```
6. Abrir 👉 [http://localhost:5000](http://localhost:5000)

## Docker produccion

Si vas a correr solo la app, necesitas que `MONGODB_URI` apunte a un MongoDB real y accesible. Si no, el contenedor falla al iniciar.

Opcion A: usar Docker Compose con Mongo incluido

1. Copiar variables: `copy .env.example .env`
2. Levantar app + mongo: `docker compose up --build -d`
3. Abrir `http://localhost:5000`
4. Ver logs: `docker compose logs -f app`

Opcion B: usar solo la imagen con Mongo externo

```bash
docker build -t fb-catalog-dashboard .
docker run --rm -p 5000:5000 \
  -e PORT=5000 \
  -e PUBLIC_BASE_URL=http://localhost:5000 \
  -e SESSION_SECRET=change-me \
  -e MONGODB_URI=mongodb://host.docker.internal:27017 \
  -e MONGODB_DB_NAME=fb_catalog_dashboard \
  fb-catalog-dashboard
```

## Flujo de uso

1. **/setup** — Selecciona BM, ad account, página y pixel por default
2. **/catalogs/new** — Crea catálogo (sincroniza a Meta automáticamente)
3. **/catalogs/{id}/products** — Agrega productos: marca cada uno como `clean` (limpio) o `dirty` (sucio)
4. **/catalogs/{id}/sets/new** — Crea sets con plantillas rápidas (1 sucio + 2 limpios, etc.)
5. **/campaigns/new** — Wizard completo. Marca "Truco automático" para que apague blancos cuando aprueben
6. Activa la campaña en Ads Manager → cuando se aprueba, el cron apaga blancos automáticamente

## Arquitectura

- **Backend:** FastAPI + MongoDB
- **Frontend:** Jinja2 templates + Tailwind CSS (CDN)
- **Cron:** APScheduler en background
- **Feed CSV:** endpoint público `/feed/{slug}.csv` que Meta consulta

## Deploy a Render

Ver [INSTALL.md](INSTALL.md).

## Estructura

```
app/
├── main.py              FastAPI app + lifecycle
├── config.py            env vars
├── database.py          MongoDB session
├── models.py            modelos Mongo (Catalog, Product, ProductSet, Campaign, Template, ...)
├── meta_api.py          wrapper Marketing API
├── trick_runner.py      cron del truco
├── routers/
│   ├── setup.py
│   ├── catalogs.py
│   ├── products.py
│   ├── sets.py
│   ├── campaigns.py
│   ├── templates.py
│   ├── trick.py
│   └── feed.py
├── templates/           HTML
└── static/              CSS, JS
```

## MongoDB

La app usa MongoDB como base principal. Para ejecutar:

1. Instala dependencias: `pip install -r requirements.txt`
2. Configura `.env`:
   ```bash
   MONGODB_URI=mongodb+srv://USER:PASS@HOST/?retryWrites=true&w=majority
   MONGODB_DB_NAME=fb_catalog_dashboard
   ```
3. Si tienes datos viejos en SQLite, instala dependencia de migracion y ejecuta el importador una vez:
   ```bash
   pip install -r requirements-migration.txt
   python scripts/migrate_to_mongo.py --source sqlite:///./data/dashboard.db --mongo-uri "mongodb+srv://USER:PASS@HOST/?retryWrites=true&w=majority"
   ```
4. Arranca normal: `python run.py`
