from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import OperationFailure

from .config import MONGODB_DB, MONGODB_URI
from .mongo_odm import Criterion, Field, MongoModel, Sort


def _mongo_uri() -> str:
    uri = MONGODB_URI
    if not uri.startswith("mongodb"):
        raise RuntimeError("MongoDB requires MONGODB_URI")
    return uri


client = MongoClient(_mongo_uri())
mongo_db = client[MONGODB_DB]


def _collection_names() -> list[str]:
    return [
        "app_settings", "meta_connections", "catalogs", "products", "product_sets", "campaign_templates",
        "campaigns", "media_assets", "language_carnadas", "copy_bundles", "planned_campaigns",
    ]


def ensure_mongo_indexes():
    for name in _collection_names():
        try:
            mongo_db[name].create_index([("id", ASCENDING)], unique=True)
        except OperationFailure as exc:
            if exc.code != 86:
                raise


def _collection_for(model: type[MongoModel]) -> str:
    return model.__tablename__


def _document_to_model(model: type[MongoModel], doc: dict[str, Any] | None):
    if not doc:
        return None
    data = {k: v for k, v in doc.items() if k != "_id"}
    return model(**data)


def _model_to_document(obj: MongoModel) -> dict[str, Any]:
    return obj.to_document()


def _next_id(collection: str) -> int:
    counters = mongo_db["_counters"]
    if counters.find_one({"_id": collection}) is None:
        max_doc = mongo_db[collection].find_one(sort=[("id", DESCENDING)])
        counters.insert_one({"_id": collection, "seq": int((max_doc or {}).get("id") or 0)})
    doc = counters.find_one_and_update(
        {"_id": collection}, {"$inc": {"seq": 1}}, return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


def _criterion_to_mongo(criterion: Criterion) -> dict[str, Any]:
    if criterion.op == "eq":
        return {criterion.field: criterion.value}
    if criterion.op == "ne":
        return {criterion.field: {"$ne": criterion.value}}
    if criterion.op == "in":
        return {criterion.field: {"$in": list(criterion.value)}}
    raise ValueError(f"Unsupported Mongo filter operator: {criterion.op}")


class MongoQuery:
    def __init__(self, session: "MongoSession", model: type[MongoModel]):
        self.session = session
        self.model = model
        self.collection_name = _collection_for(model)
        self.filters: list[dict[str, Any]] = []
        self.sorts: list[tuple[str, int]] = []

    def filter(self, *criteria: Criterion):
        self.filters.extend(_criterion_to_mongo(c) for c in criteria)
        return self

    def order_by(self, *criteria: Sort):
        for criterion in criteria:
            if isinstance(criterion, Sort):
                self.sorts.append((criterion.field, criterion.direction))
            elif isinstance(criterion, Field):
                self.sorts.append((criterion.name, ASCENDING))
            else:
                raise ValueError(f"Unsupported Mongo sort expression: {criterion!r}")
        return self

    def _filter_doc(self) -> dict[str, Any]:
        if not self.filters:
            return {}
        if len(self.filters) == 1:
            return self.filters[0]
        return {"$and": self.filters}

    def all(self):
        cursor = mongo_db[self.collection_name].find(self._filter_doc())
        if self.sorts:
            cursor = cursor.sort(self.sorts)
        return [self.session._track(_document_to_model(self.model, doc)) for doc in cursor]

    def first(self):
        cursor = mongo_db[self.collection_name].find(self._filter_doc())
        if self.sorts:
            cursor = cursor.sort(self.sorts)
        doc = next(cursor.limit(1), None)
        return self.session._track(_document_to_model(self.model, doc))

    def count(self):
        return mongo_db[self.collection_name].count_documents(self._filter_doc())

    def delete(self, synchronize_session: bool = False):
        result = mongo_db[self.collection_name].delete_many(self._filter_doc())
        return result.deleted_count


class MongoSession:
    def __init__(self):
        self._tracked: dict[tuple[str, int], MongoModel] = {}
        self._deleted: set[tuple[str, int]] = set()

    def query(self, model: type[MongoModel]):
        return MongoQuery(self, model)

    def add(self, obj: MongoModel):
        collection = _collection_for(type(obj))
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", _next_id(collection))
        self._tracked[(collection, int(obj.id))] = obj

    def delete(self, obj: MongoModel):
        collection = _collection_for(type(obj))
        obj_id = int(obj.id)
        mongo_db[collection].delete_one({"id": obj_id})
        self._deleted.add((collection, obj_id))
        self._tracked.pop((collection, obj_id), None)

        if collection == "catalogs":
            mongo_db["products"].delete_many({"catalog_id": obj_id})
            mongo_db["product_sets"].delete_many({"catalog_id": obj_id})

    def commit(self):
        for key, obj in list(self._tracked.items()):
            if key in self._deleted:
                continue
            collection, obj_id = key
            doc = _model_to_document(obj)
            if doc.get("created_at") is None:
                doc["created_at"] = datetime.utcnow()
                setattr(obj, "created_at", doc["created_at"])
            mongo_db[collection].replace_one({"id": obj_id}, doc, upsert=True)

    def rollback(self):
        self._tracked.clear()

    def refresh(self, obj: MongoModel):
        return obj

    def close(self):
        self._tracked.clear()
        self._deleted.clear()

    def _track(self, obj: MongoModel | None):
        if obj is not None and getattr(obj, "id", None) is not None:
            self._tracked[(_collection_for(type(obj)), int(obj.id))] = obj
        return obj
