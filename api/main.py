import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routes import searches, trends, postings

# Browser origins allowed to call the API (the frontend), comma-separated.
# Defaults cover the usual local dev servers (Vite, Next/CRA).
CORS_ORIGINS = [o.strip() for o in (os.getenv("API_CORS_ORIGINS") or
                "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]

# The data changes once a day (the ingestion Action), so clients and CDNs may reuse
# responses for an hour. /health, /docs and errors aren't cached.
CACHED_PREFIXES = ("/searches", "/trends", "/postings", "/companies")
CACHE_CONTROL = "public, max-age=3600"

# Initialize the application
app = FastAPI(title="Canadian Job Data API")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET"],
                   allow_headers=["*"])
app.include_router(searches.router)
app.include_router(trends.router)
app.include_router(postings.router)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    if (request.method == "GET" and response.status_code == 200
            and request.url.path.startswith(CACHED_PREFIXES)):
        response.headers.setdefault("Cache-Control", CACHE_CONTROL)
    return response


@app.get("/")
def read_root():
    return {"name": app.title, "docs": "/docs"}

@app.get("/health")
def read_health():
    return{"status": "ok"}
