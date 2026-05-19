"""Modelo Mongo para campañas planificadas."""
from ..mongo_odm import Field, MongoModel, utcnow


class PlannedCampaign(MongoModel):
    __tablename__ = "planned_campaigns"
    status = Field("pending")
    type = Field()
    name = Field()
    ad_account_id = Field("")
    page_id = Field("")
    pixel_id = Field("")
    instagram_id = Field("")
    cbo_or_abo = Field("ABO")
    daily_budget_usd = Field(5.0)
    bid_strategy = Field("LOWEST_COST_WITHOUT_CAP")
    bid_amount_usd = Field(0.0)
    roas_floor = Field(0.0)
    countries = Field("US")
    age_min = Field(18)
    age_max = Field(65)
    locale_id = Field(6)
    objective = Field("OUTCOME_SALES")
    optimization_goal = Field("OFFSITE_CONVERSIONS")
    custom_event_type = Field("PURCHASE")
    url_tags = Field("")
    config = Field({})
    result_ids = Field({})
    error_msg = Field("")
    created_at = Field(utcnow)
    executed_at = Field()


def migrate_planning(_db=None):
    return None
