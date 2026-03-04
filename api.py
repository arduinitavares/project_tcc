from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import uvicorn

app = FastAPI(title="AgenticFlow API")

# Mount the static frontend directory
app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="frontend")

@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")

@app.get("/api/projects")
def get_projects():
    # Placeholder for actual FSM state integration
    # You will eventually hook this up to `get_current_state` from main.py
    return {
        "status": "success",
        "data": [
            {
                "id": 1,
                "name": "Project Alpha",
                "state": "Vision Generated",
                "summary": "Autonomous agent for supply chain optimization."
            }
        ]
    }

if __name__ == "__main__":
    print("Starting AgenticFlow Dashboard on http://localhost:8000")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
