from .mongo_database import MongoSession, ensure_mongo_indexes


def get_db():
    db = MongoSession()
    try:
        yield db
    finally:
        db.close()


def create_db_session():
    return MongoSession()


def migrate_db():
    ensure_mongo_indexes()
