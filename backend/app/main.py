from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.plugin_registry import get_registry
from app.db.session import async_session_factory, init_models
from app.plugins.base import PluginError
from app.routers import auth, best_practice, config_changes, configuration, devices, logs, monitoring, reports, topology, twin
from app.services import auth_service
from app.services.poller import poller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("infraos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting InfraOS backend...")
    await init_models()
    get_registry()  # eagerly validate plugins at startup, fail loudly if broken

    async with async_session_factory() as db:
        await auth_service.ensure_bootstrap_admin(
            db,
            username=os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin"),
            password=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "change-me-immediately"),
        )

    poller.start()
    logger.info("InfraOS backend ready.")
    yield
    logger.info("Shutting down InfraOS backend...")
    await poller.stop()
    await get_registry().close_all()


app = FastAPI(
    title="InfraOS — Palo Alto Module",
    description="Device management, configuration visibility, and monitoring for Palo Alto firewalls.",
    version="0.2.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# auth.router is intentionally NOT behind get_current_user — /login must be reachable
# unauthenticated, and /users is protected internally via require_admin.
app.include_router(auth.router)

_authenticated = [Depends(get_current_user)]
app.include_router(devices.router, dependencies=_authenticated)
app.include_router(configuration.router, dependencies=_authenticated)
app.include_router(monitoring.router, dependencies=_authenticated)
app.include_router(twin.router, dependencies=_authenticated)
app.include_router(config_changes.router, dependencies=_authenticated)
app.include_router(topology.router, dependencies=_authenticated)
app.include_router(logs.router, dependencies=_authenticated)
app.include_router(best_practice.router, dependencies=_authenticated)
app.include_router(reports.router, dependencies=_authenticated)


@app.exception_handler(PluginError)
async def plugin_error_handler(request: Request, exc: PluginError) -> JSONResponse:
    """Defense-in-depth safety net: any vendor-plugin error (auth failure,
    unreachable device, unsupported version, malformed response, ...) that a
    domain service forgets to catch explicitly lands here instead of
    surfacing as an unhandled 500. Domain services should still catch
    PluginError subclasses themselves where they can add useful context
    (see connectivity_service.discover_device), but this ensures no plugin
    exception ever escapes as a bare 500."""
    logger.warning("Unhandled plugin error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok"}
