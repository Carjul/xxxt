"""
Modelos nuevos para el Truco de Idiomas.
Agregar a app/models.py (o importar desde aquí).

Tablas nuevas:
  - media_assets   : registro de imágenes/videos subidos a Meta
  - copy_bundles   : paquetes de copy multi-idioma reusables

Migración automática (ALTER TABLE seguro): ver migrate_extras() abajo.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON

# Importar Base del módulo principal del dashboard
try:
    from ..database import Base
except ImportError:
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, default="image")          # 'image' o 'video'
    local_path = Column(String, nullable=True)       # ruta local (si se subió desde PC)
    public_url = Column(String, nullable=True)       # URL si se descargó de internet
    meta_id = Column(String, nullable=True)          # hash (image) o video_id
    ad_account_id = Column(String, nullable=True)    # ad account donde se subió
    is_default = Column(Boolean, default=False)      # True si es la "carnada" multi-idioma
    language_label = Column(String, default="en_XX") # etiqueta del idioma
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CopyBundle(Base):
    __tablename__ = "copy_bundles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    # Copy "real" (el agresivo)
    real_body = Column(Text, nullable=False)
    real_title = Column(String, nullable=False)
    real_desc = Column(Text, nullable=True)
    real_url = Column(String, nullable=False)
    real_label = Column(String, default="en_XX")
    real_locales = Column(JSON, default=[6])
    # Copy de carnada en multi-idioma (JSON: {fr: {...}, ru: {...}, ja: {...}, ar: {...}})
    default_copy = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def migrate_extras(engine):
    """
    Agrega columnas a Campaign existente para soportar tipos de truco.
    Llamar desde la función migrate_db() de database.py:

        from app.services.language_models import migrate_extras
        migrate_extras(engine)
    """
    from sqlalchemy import inspect, text

    Base.metadata.create_all(bind=engine, tables=[
        MediaAsset.__table__, CopyBundle.__table__
    ])

    insp = inspect(engine)
    if "campaigns" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("campaigns")}
        with engine.begin() as conn:
            if "campaign_type" not in cols:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN campaign_type VARCHAR DEFAULT 'catalog'"))
            if "media_asset_id" not in cols:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN media_asset_id INTEGER"))
            if "default_media_id" not in cols:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN default_media_id INTEGER"))
            if "copy_bundle_id" not in cols:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN copy_bundle_id INTEGER"))
