from __future__ import annotations

from copy import deepcopy
from datetime import datetime


class Comparison:
    def __init__(self, field_name: str, operator: str, value):
        self.field_name = field_name
        self.operator = operator
        self.value = value

    def matches(self, obj) -> bool:
        current = getattr(obj, self.field_name, None)
        if self.operator == "eq":
            return current == self.value
        if self.operator == "in":
            return current in self.value
        if self.operator == "isnot":
            return current is not self.value
        raise ValueError(f"Unsupported operator: {self.operator}")


class SortSpec:
    def __init__(self, field_name: str, descending: bool = False):
        self.field_name = field_name
        self.descending = descending


class QueryField:
    def __init__(self, default=None, default_factory=None):
        self.default = default
        self.default_factory = default_factory
        self.name = ""

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.get(self.name)

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value

    def get_default(self):
        if self.default_factory is not None:
            return self.default_factory()
        return deepcopy(self.default)

    def __eq__(self, other):  # type: ignore[override]
        return Comparison(self.name, "eq", other)

    def in_(self, values):
        return Comparison(self.name, "in", list(values))

    def isnot(self, value):
        return Comparison(self.name, "isnot", value)

    def desc(self):
        return SortSpec(self.name, descending=True)

    def asc(self):
        return SortSpec(self.name, descending=False)


def field(default=None, default_factory=None):
    return QueryField(default=default, default_factory=default_factory)


class _Metadata:
    def create_all(self, bind=None):
        return None


class BaseDocument:
    metadata = _Metadata()
    __collection__ = ""
    __fields__: dict[str, QueryField] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        fields = {}
        for base in reversed(cls.__mro__[1:]):
            fields.update(getattr(base, "__fields__", {}))
        for name, value in cls.__dict__.items():
            if isinstance(value, QueryField):
                fields[name] = value
        cls.__fields__ = fields

    def __init__(self, **kwargs):
        for name, descriptor in self.__fields__.items():
            if name in kwargs:
                setattr(self, name, kwargs[name])
            else:
                setattr(self, name, descriptor.get_default())

    def to_mongo(self):
        return {name: getattr(self, name) for name in self.__fields__}

    @classmethod
    def from_mongo(cls, data: dict):
        return cls(**{name: deepcopy(data.get(name)) for name in cls.__fields__})


Base = BaseDocument


class AppSettings(Base):
    __collection__ = "app_settings"

    id = field()
    default_business_id = field()
    default_ad_account_id = field()
    default_page_id = field()
    default_pixel_id = field()
    fb_token_last4 = field()
    telegram_bot_token = field()
    telegram_chat_id = field()
    slack_webhook_url = field()
    notify_on_approval = field(default=True)
    notify_on_conversion = field(default=True)
    updated_at = field(default_factory=datetime.utcnow)


class MetaConnection(Base):
    __collection__ = "meta_connections"

    id = field()
    name = field(default="")
    token = field(default="")
    token_last4 = field(default="")
    business_id = field()
    business_name = field()
    default_ad_account_id = field()
    default_page_id = field()
    default_pixel_id = field()
    is_active = field(default=False)
    is_valid = field(default=False)
    last_error = field()
    last_tested_at = field()
    created_at = field(default_factory=datetime.utcnow)


class Catalog(Base):
    __collection__ = "catalogs"

    id = field()
    fb_catalog_id = field(default="")
    name = field(default="")
    business_id = field()
    feed_slug = field(default="")
    fb_feed_id = field()
    created_at = field(default_factory=datetime.utcnow)


class Product(Base):
    __collection__ = "products"

    id = field()
    catalog_id = field()
    retailer_id = field(default="")
    title = field(default="")
    description = field(default="")
    availability = field(default="in stock")
    condition = field(default="new")
    price = field(default="10.00 USD")
    link = field(default="")
    image_link = field(default="")
    brand = field(default="Brand")
    video_url = field()
    video_label = field()
    tag = field(default="dirty")
    created_at = field(default_factory=datetime.utcnow)


class ProductSet(Base):
    __collection__ = "product_sets"

    id = field()
    catalog_id = field()
    fb_set_id = field()
    name = field(default="")
    retailer_ids = field(default_factory=list)
    created_at = field(default_factory=datetime.utcnow)


class CampaignTemplate(Base):
    __collection__ = "campaign_templates"

    id = field()
    name = field(default="")
    config = field(default_factory=dict)
    created_at = field(default_factory=datetime.utcnow)


class Campaign(Base):
    __collection__ = "campaigns"

    id = field()
    fb_campaign_id = field()
    fb_adset_id = field()
    fb_creative_id = field()
    fb_ad_id = field()
    name = field(default="")
    ad_account_id = field(default="")
    catalog_id = field()
    product_set_id = field()
    config = field(default_factory=dict)
    trick_enabled = field(default=False)
    trick_executed = field(default=False)
    trick_executed_at = field()
    last_status = field()
    last_conversions = field(default=0)
    last_spend = field(default=0.0)
    notified_approval = field(default=False)
    created_at = field(default_factory=datetime.utcnow)
