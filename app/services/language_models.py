"""
Modelos nuevos para el Truco de Idiomas.
Colecciones MongoDB nuevas:
  - media_assets   : registro de imágenes/videos subidos a Meta
  - copy_bundles   : paquetes de copy multi-idioma reusables

Campos agregados a Campaign:
  - campaign_type  : 'catalog', 'language', 'normal'
  - media_asset_id : referencia a media_assets
  - default_media_id : referencia a media_assets (la carnada)
  - copy_bundle_id : referencia a copy_bundles
"""
from datetime import datetime
from ..models import Base, field


class MediaAsset(Base):
    __collection__ = "media_assets"
    
    id = field()
    name = field(default="")
    type = field(default="image")                    # 'image' o 'video'
    local_path = field()                             # ruta local (si se subió desde PC)
    public_url = field()                             # URL si se descargó de internet
    meta_id = field()                                # hash (image) o video_id
    ad_account_id = field()                          # ad account donde se subió
    is_default = field(default=False)                # True si es la "carnada" multi-idioma
    language_label = field(default="en_XX")          # etiqueta del idioma
    notes = field()
    created_at = field(default_factory=datetime.utcnow)


class CopyBundle(Base):
    __collection__ = "copy_bundles"
    
    id = field()
    name = field(default="")
    # Copy "real" (el agresivo)
    real_body = field(default="")
    real_title = field(default="")
    real_desc = field()
    real_url = field(default="")
    real_label = field(default="en_XX")
    real_locales = field(default_factory=lambda: [6])
    # Copy de carnada en multi-idioma (JSON: {fr: {...}, ru: {...}, ja: {...}, ar: {...}})
    default_copy = field(default_factory=dict)
    created_at = field(default_factory=datetime.utcnow)


def migrate_extras(engine):
    """
    Con MongoDB no se necesitan migraciones SQL.
    Las colecciones se crean automáticamente al primer insert.
    Esta función es un placeholder para compatibilidad.
    """
    pass
