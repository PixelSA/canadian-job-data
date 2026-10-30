from fastapi import FastAPI

from api.routes import searches, trends

# Initialize the application
app = FastAPI(title="Canadian Job Data API")
app.include_router(searches.router)
app.include_router(trends.router)

@app.get("/")
def read_root():
    return {"name": app.title, "docs": "/docs"}

@app.get("/health")
def read_health():
    return{"status": "ok"}

