from fastapi import FastAPI

from api.routes import searches

# Initialize the application
app = FastAPI(title="Canadian Job Data API")
app.include_router(searches.router)

@app.get("/")
def read_root():
    return {"Hello": "World"}

# Define a route with path and query parameters
@app.get("/health")
def read_health():
    return{"status": "ok"}

