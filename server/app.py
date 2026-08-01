import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from server.auth.routes import router as auth_router, yggdrasil_router
from server.web.admin import router as admin_router, _migrate_modpacks_from_json
from server.web import projects_router, launcher_router, news_router

_log = logging.getLogger("uroboros")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _migrate_modpacks_from_json()
    from server.mc.whitelist import sync_all_whitelists
    try:
        await sync_all_whitelists()
    except Exception:
        pass
    import threading
    from server.mc.java import scan_java
    threading.Thread(target=scan_java, daemon=True).start()
    yield


app = FastAPI(title="Uroboros Server", version="2.0.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception(request: Request, exc: Exception):
    _log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "InternalServerError", "errorMessage": "An internal error occurred"},
    )


app.include_router(auth_router, prefix="/auth")
app.include_router(yggdrasil_router)
app.include_router(admin_router, prefix="/admin")
app.include_router(projects_router, prefix="/projects")
app.include_router(news_router, prefix="/projects")
app.include_router(launcher_router, prefix="/launcher")


@app.get("/")
async def root(request: Request):
    host = request.url.hostname or "127.0.0.1"
    skin_domains = ["localhost", "127.0.0.1", "0.0.0.0", host]
    seen = []
    for d in skin_domains:
        if d and d not in seen:
            seen.append(d)
    return {
        "status": "ok",
        "server": "Uroboros Server",
        "version": "2.0.0",
        "meta": {
            "serverName": "Uroboros Server",
            "implementationName": "Uroboros Yggdrasil",
            "implementationVersion": "2.0.0",
            "feature.non_email_login": True,
            "feature.no_mojang_namespace": True,
        },
        "skinDomains": seen,
    }
