"""Modelos Mongo para el Truco de Idiomas."""
from ..mongo_odm import Field, MongoModel, utcnow


class MediaAsset(MongoModel):
    __tablename__ = "media_assets"
    name = Field()
    type = Field("image")
    public_url = Field()
    local_path = Field()
    meta_id = Field()
    ad_account_id = Field()
    uploaded_to_meta = Field(False)
    notes = Field()
    is_default = Field(False)
    language_label = Field("")
    created_at = Field(utcnow)


class LanguageCarnada(MongoModel):
    __tablename__ = "language_carnadas"
    locale_id = Field()
    locale_code = Field()
    language_name = Field()
    body = Field()
    title = Field()
    description = Field("")
    url = Field()
    notes = Field("")
    created_at = Field(utcnow)


class CopyBundle(MongoModel):
    __tablename__ = "copy_bundles"
    name = Field()
    real_body = Field()
    real_title = Field()
    real_desc = Field()
    real_url = Field()
    target_locale_id = Field(6)
    target_locale_code = Field("en_XX")
    carnada_ids = Field([])
    real_label = Field("")
    real_locales = Field([])
    default_copy = Field({})
    created_at = Field(utcnow)


def migrate_extras(_db=None):
    return None
