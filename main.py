from fastapi import FastAPI
from app.api import router

app = FastAPI(title="BookFerry")

app.include_router(router)