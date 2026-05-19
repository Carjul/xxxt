# Integración del Truco de Idiomas

Esta guía explica cómo activar los módulos nuevos del **truco de idiomas** sin romper el dashboard de catálogo existente.

## Archivos NUEVOS (drop-in, no requieren tocar nada)

```
app/services/__init__.py
app/services/language_trick.py         ← lógica principal del truco
app/services/language_models.py        ← modelos DB (MediaAsset, CopyBundle)
app/routers/language_routes.py         ← endpoints /media, /copies, /campaigns/language-trick
app/templates/media/list.html          ← UI Media Library
app/templates/copies/list.html         ← UI Copy Bundles
app/templates/copies/create.html       ← form Copy Bundle
```

## 3 cambios MÍNIMOS en archivos existentes

### 1. `app/main.py` — registrar el router nuevo

Agregar después de los otros `include_router`:

```python
from .routers import language_routes
app.include_router(language_routes.router)
```

### 2. `app/database.py`

La app actual usa MongoDB. No hay migraciones SQL que ejecutar en runtime.

Esto agrega colecciones `media_assets` y `copy_bundles`, y campos en `campaigns`:
- `campaign_type` (catalog / language / normal)
- `media_asset_id`, `default_media_id`, `copy_bundle_id`

### 3. `app/templates/base.html` — agregar items al sidebar

En el `<nav>` del sidebar, agregar:

```html
<a href="/media" class="sidebar-item"><i data-lucide="image" class="lucide-icon"></i>Media</a>
<a href="/copies" class="sidebar-item"><i data-lucide="languages" class="lucide-icon"></i>Copy Multi-Idioma</a>
```

## Cómo usar (flow completo)

### Paso 1 — Subir creativos a Media Library
1. Ve a `/media`
2. Sube el creativo **REAL** (BizOp en inglés) → marca con label `en_XX`
3. Sube el creativo **DEFAULT** (lifestyle/neutral en francés) → marca el toggle "Es creativo DEFAULT"
4. Repite por cada par real/default que necesites

### Paso 2 — Crear paquete de Copy
1. Ve a `/copies` → "Nuevo paquete"
2. Llena el copy **REAL** (en inglés, agresivo)
3. Llena las **carnadas** en francés, ruso, japonés, árabe (texto benigno)
4. Guardar

### Paso 3 — Crear campaña con truco de idiomas
Vía API POST a `/campaigns/language-trick`:

```bash
curl -X POST https://tu-app.onrender.com/campaigns/language-trick \
  -d "ad_account_id=act_1540233950717702" \
  -d "page_id=908019265722171" \
  -d "pixel_id=2027997357776963" \
  -d "name=BizOp US Lang Trick #1" \
  -d "country=US" \
  -d "age_min=40&age_max=65" \
  -d "media_asset_id=1" \
  -d "default_media_id=2" \
  -d "copy_bundle_id=1" \
  -d "daily_budget_usd=1.50" \
  -d "url_tags=ad_id={{ad.id}}&placement={{placement}}" \
  -d "cbo_or_abo=ABO"
```

Devuelve JSON con los IDs creados (campaign, adset, creative, ad).

### Paso 4 — Activar manualmente

Por seguridad, todo se crea en **PAUSED**. Activas desde Ads Manager cuando estés listo.

## Cómo funciona el truco internamente

```
Asset Feed Spec del creative:
┌─────────────────────────────────────────────────┐
│ Real (en_XX, locale=6):   creativo BizOp agresivo│ ← lo que ve usuario US
│ Default (fr_XX):          creativo lifestyle FR  │ ← lo que ve el reviewer
│ Ruso, Japonés, Árabe:     carnadas adicionales   │
└─────────────────────────────────────────────────┘

Targeting:
  locales: [6]  ← Solo targetea usuarios inglés US

Resultado:
  - Reviewer francés revisa → ve creativo FR limpio → APRUEBA
  - Usuario US recibe ad → Meta selecciona creativo en_XX → ve BizOp agresivo
```

## Próximos pasos sugeridos

1. **Wizard UI completo** — agregar pantalla `/campaigns/language-trick/new` que llene todo desde el navegador
2. **Selector de tipo de truco** en el wizard general (catalog / language / normal)
3. **Plantillas multi-truco** — extender `CampaignTemplate` para soportar ambos tipos
4. **Validación pre-flight** — checar que el creativo default sea diferente del real

## Troubleshooting

- **Error "page-backed IG not found"**: la página de Facebook no tiene Instagram-backed account. Crearla en Meta → Page Settings → Linked accounts → Instagram.
- **Error en upload de video**: archivo demasiado grande para upload directo (>50MB) → el código usa resumable upload automáticamente, dale 1-2 minutos.
- **Error "Permissions error"**: el token no tiene `ads_management` o no es admin del ad account.
