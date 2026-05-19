from .mongo_odm import Field, MongoModel, utcnow


class AppSettings(MongoModel):
    __tablename__ = "app_settings"
    default_business_id = Field()
    default_ad_account_id = Field()
    default_page_id = Field()
    default_pixel_id = Field()
    fb_access_token = Field()
    fb_token_last4 = Field()
    telegram_bot_token = Field()
    telegram_chat_id = Field()
    slack_webhook_url = Field()
    notify_on_approval = Field(True)
    notify_on_conversion = Field(True)
    updated_at = Field(utcnow)


class MetaConnection(MongoModel):
    __tablename__ = "meta_connections"
    name = Field("")
    token = Field("")
    token_last4 = Field("")
    business_id = Field()
    business_name = Field()
    default_ad_account_id = Field()
    default_page_id = Field()
    default_pixel_id = Field()
    is_active = Field(False)
    is_valid = Field(False)
    last_error = Field()
    last_tested_at = Field()
    created_at = Field(utcnow)


class Catalog(MongoModel):
    __tablename__ = "catalogs"
    fb_catalog_id = Field()
    name = Field()
    business_id = Field()
    feed_slug = Field()
    fb_feed_id = Field()
    created_at = Field(utcnow)


class Product(MongoModel):
    __tablename__ = "products"
    catalog_id = Field()
    retailer_id = Field()
    title = Field()
    description = Field("")
    availability = Field("in stock")
    condition = Field("new")
    price = Field("10.00 USD")
    link = Field()
    image_link = Field()
    brand = Field("Brand")
    video_url = Field()
    video_label = Field()
    tag = Field("dirty")
    created_at = Field(utcnow)


class ProductSet(MongoModel):
    __tablename__ = "product_sets"
    catalog_id = Field()
    fb_set_id = Field()
    name = Field()
    retailer_ids = Field([])
    created_at = Field(utcnow)


class CampaignTemplate(MongoModel):
    __tablename__ = "campaign_templates"
    name = Field()
    config = Field({})
    created_at = Field(utcnow)


class Campaign(MongoModel):
    __tablename__ = "campaigns"
    fb_campaign_id = Field()
    fb_adset_id = Field()
    fb_creative_id = Field()
    fb_ad_id = Field()
    name = Field()
    ad_account_id = Field()
    catalog_id = Field()
    product_set_id = Field()
    config = Field({})
    trick_enabled = Field(False)
    trick_executed = Field(False)
    trick_executed_at = Field()
    last_status = Field()
    last_conversions = Field(0)
    last_spend = Field(0.0)
    notified_approval = Field(False)
    campaign_type = Field("catalog")
    media_asset_id = Field()
    default_media_id = Field()
    copy_bundle_id = Field()
    created_at = Field(utcnow)
