from __future__ import annotations

from copy import deepcopy

from pymongo import ASCENDING, MongoClient
from pymongo.collection import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .config import MONGODB_DB_NAME, MONGODB_URI
from .models import Base, Catalog, Product, ProductSet


if MONGODB_URI.startswith("mongomock://"):
    import mongomock

    client = mongomock.MongoClient()
else:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
engine = client
mongo_db = client[MONGODB_DB_NAME]


def _ensure_indexes():
    mongo_db["app_settings"].create_index([("id", ASCENDING)], unique=True)
    mongo_db["meta_connections"].create_index([("id", ASCENDING)], unique=True)
    mongo_db["meta_connections"].create_index([("is_active", ASCENDING)])
    mongo_db["catalogs"].create_index([("id", ASCENDING)], unique=True)
    mongo_db["catalogs"].create_index([("fb_catalog_id", ASCENDING)], unique=True, sparse=True)
    mongo_db["catalogs"].create_index([("feed_slug", ASCENDING)], unique=True)
    mongo_db["products"].create_index([("id", ASCENDING)], unique=True)
    mongo_db["product_sets"].create_index([("id", ASCENDING)], unique=True)
    mongo_db["campaign_templates"].create_index([("id", ASCENDING)], unique=True)
    mongo_db["campaigns"].create_index([("id", ASCENDING)], unique=True)


class Query:
    def __init__(self, session: MongoSession, model):
        self.session = session
        self.model = model
        self.conditions = []
        self.sort_specs = []

    def filter(self, *conditions):
        self.conditions.extend(conditions)
        return self

    def order_by(self, *sort_specs):
        self.sort_specs.extend(sort_specs)
        return self

    def _matches(self, obj) -> bool:
        return all(condition.matches(obj) for condition in self.conditions)

    def _load_all(self):
        items = []
        for raw in self.session.database[self.model.__collection__].find({}, {"_id": 0}):
            obj = self.model.from_mongo(raw)
            obj = self.session._register(obj, is_new=False)
            if self._matches(obj):
                items.append(obj)
        for sort_spec in reversed(self.sort_specs):
            if hasattr(sort_spec, "field_name"):
                items.sort(
                    key=lambda item: (getattr(item, sort_spec.field_name) is None, getattr(item, sort_spec.field_name)),
                    reverse=sort_spec.descending,
                )
            else:
                items.sort(key=lambda item: getattr(item, sort_spec.name), reverse=False)
        return items

    def all(self):
        return self._load_all()

    def first(self):
        items = self._load_all()
        return items[0] if items else None

    def count(self):
        return len(self._load_all())


class MongoSession:
    def __init__(self, database):
        self.database = database
        self._tracked = {}
        self._snapshots = {}
        self._new = set()
        self._deleted = set()

    def _key_for(self, model, obj_id):
        return (model.__collection__, obj_id)

    def _register(self, obj, is_new: bool):
        obj_id = getattr(obj, "id", None)
        if obj_id is None:
            return obj
        key = self._key_for(type(obj), obj_id)
        if key not in self._tracked:
            self._tracked[key] = obj
            self._snapshots[key] = deepcopy(obj.to_mongo())
        else:
            obj = self._tracked[key]
        if is_new:
            self._new.add(key)
        return obj

    def _next_id(self, collection_name: str) -> int:
        result = self.database["_counters"].find_one_and_update(
            {"_id": collection_name},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(result["seq"])

    def query(self, model):
        return Query(self, model)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id(type(obj).__collection__)
        self._register(obj, is_new=True)

    def delete(self, obj):
        obj_id = getattr(obj, "id", None)
        if obj_id is None:
            return
        self._register(obj, is_new=False)
        self._deleted.add(self._key_for(type(obj), obj_id))

    def commit(self):
        try:
            for key in list(self._deleted):
                collection_name, obj_id = key
                self.database[collection_name].delete_one({"id": obj_id})
                if collection_name == Catalog.__collection__:
                    self.database[Product.__collection__].delete_many({"catalog_id": obj_id})
                    self.database[ProductSet.__collection__].delete_many({"catalog_id": obj_id})
                if collection_name == ProductSet.__collection__:
                    self.database["campaigns"].update_many(
                        {"product_set_id": obj_id},
                        {"$set": {"product_set_id": None}},
                    )
                self._tracked.pop(key, None)
                self._snapshots.pop(key, None)
                self._new.discard(key)

            for key, obj in list(self._tracked.items()):
                if key in self._deleted:
                    continue
                payload = obj.to_mongo()
                self.database[type(obj).__collection__].replace_one({"id": obj.id}, payload, upsert=True)
                self._snapshots[key] = deepcopy(payload)
                self._new.discard(key)
        except DuplicateKeyError as exc:
            raise ValueError("Registro duplicado en MongoDB") from exc

    def refresh(self, obj):
        obj_id = getattr(obj, "id", None)
        if obj_id is None:
            return
        raw = self.database[type(obj).__collection__].find_one({"id": obj_id}, {"_id": 0})
        if not raw:
            return
        for name in type(obj).__fields__:
            setattr(obj, name, deepcopy(raw.get(name)))
        self._register(obj, is_new=False)

    def rollback(self):
        for key, snapshot in self._snapshots.items():
            obj = self._tracked.get(key)
            if obj is None:
                continue
            for name in type(obj).__fields__:
                setattr(obj, name, deepcopy(snapshot.get(name)))
        for key in list(self._new):
            self._tracked.pop(key, None)
            self._snapshots.pop(key, None)
        self._new.clear()
        self._deleted.clear()

    def close(self):
        self._tracked.clear()
        self._snapshots.clear()
        self._new.clear()
        self._deleted.clear()


Session = MongoSession


def SessionLocal():
    return MongoSession(mongo_db)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db():
    _ensure_indexes()
