from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from server.auth.routes import router as auth_router
from server.web.admin import router as admin_router, _migrate_modpacks_from_json
from server.web import projects_router, launcher_router, news_router


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
    return JSONResponse(
        status_code=500,
        content={"error": "InternalServerError", "errorMessage": str(exc)},
    )


app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")
app.include_router(projects_router, prefix="/projects")
app.include_router(news_router, prefix="/projects")
app.include_router(launcher_router, prefix="/launcher")


@app.get("/")
async def root():
    return {"status": "ok", "server": "Uroboros Server", "version": "2.0.0"}
