from fastapi import FastAPI

from app.api import router
from app.db.catalog_database import init_catalog_db
from app.db.database import init_db


init_db()
init_catalog_db()


app = FastAPI(title="BookFerry")

app.include_router(router)
