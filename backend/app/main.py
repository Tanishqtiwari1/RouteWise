import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import analytics, customers, geocode, health, networks, orders, routes, settings, vehicles, warehouses
from app.core.config import get_settings
from app.core.errors import install_error_handlers

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    cfg = get_settings()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(
        title="RouteWise API",
        version="1.0.0",
        description="Smart delivery cost minimiser. Primary routing uses a custom Uniform Cost Search over "
                    "OpenStreetMap road networks. All costs are model estimates unless marked actual.",
        docs_url="/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-Admin-Token"])
    install_error_handlers(app)
    v1 = APIRouter(prefix=API_PREFIX)
    for r in (health, settings, warehouses, customers, geocode, orders, vehicles, networks, routes, analytics):
        v1.include_router(r.router)
    app.include_router(v1)
    return app


app = create_app()
