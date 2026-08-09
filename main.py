from fastapi import FastAPI

from app.api import router
from app.db.catalog_database import init_catalog_db
from app.db.database import init_db
from app.logging_config import (
    configure_logging,
    request_logging_middleware,
)


configure_logging()
init_db()
init_catalog_db()


app = FastAPI(title="BookFerry")
app.middleware("http")(request_logging_middleware)
app.include_router(router)
