import argparse
import os

from pymongo import ASCENDING, DESCENDING, MongoClient
from sqlalchemy import MetaData, create_engine, select


TABLES = [
    "app_settings", "catalogs", "products", "product_sets", "campaign_templates",
    "campaigns", "media_assets", "language_carnadas", "copy_bundles", "planned_campaigns",
]


def main():
    parser = argparse.ArgumentParser(description="Importa la DB vieja SQL a MongoDB una sola vez.")
    parser.add_argument("--source", default=os.getenv("SOURCE_DATABASE_URL") or "sqlite:///./data/dashboard.db")
    parser.add_argument("--mongo-uri", default=os.getenv("MONGODB_URI"))
    parser.add_argument("--mongo-db", default=os.getenv("MONGODB_DB", "fb_catalog_dashboard"))
    parser.add_argument("--drop", action="store_true", help="Borra colecciones destino antes de importar.")
    args = parser.parse_args()

    if not args.mongo_uri:
        raise SystemExit("Falta --mongo-uri o MONGODB_URI")
    if args.source.startswith("mongodb"):
        raise SystemExit("--source debe apuntar a la DB vieja SQL, no a MongoDB")

    engine = create_engine(args.source, future=True)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    mongo = MongoClient(args.mongo_uri)[args.mongo_db]

    with engine.connect() as conn:
        for table_name in TABLES:
            if table_name not in metadata.tables:
                print(f"{table_name}: no existe en origen")
                continue

            table = metadata.tables[table_name]
            collection = mongo[table_name]
            if args.drop:
                collection.drop()
            collection.create_index([("id", ASCENDING)], unique=True)

            rows = [dict(row._mapping) for row in conn.execute(select(table)).all()]
            for doc in rows:
                collection.replace_one({"id": doc["id"]}, doc, upsert=True)

            max_doc = collection.find_one(sort=[("id", DESCENDING)])
            mongo["_counters"].replace_one(
                {"_id": table_name},
                {"_id": table_name, "seq": int((max_doc or {}).get("id") or 0)},
                upsert=True,
            )
            print(f"{table_name}: {len(rows)} documentos")

    print(f"Migracion completada en MongoDB database '{args.mongo_db}'")


if __name__ == "__main__":
    main()
