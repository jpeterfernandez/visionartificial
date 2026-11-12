from fastapi import FastAPI
from app.main import app

# Explicit FastAPI app instance for PyCharm IDE and Uvicorn
app: FastAPI = app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)