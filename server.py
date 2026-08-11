import uvicorn
from app.main import app
from app.config import PORT

ACTUAL_PORT = PORT

def run(start_port=None):
    global ACTUAL_PORT
    target_port = start_port or PORT
    
    for attempt_port in range(target_port, target_port + 10):
        try:
            ACTUAL_PORT = attempt_port
            print(f"Starting FastAPI + Uvicorn server on port {ACTUAL_PORT}...")
            uvicorn.run(app, host="0.0.0.0", port=attempt_port)
            return
        except OSError as e:
            if attempt_port == target_port + 9:
                raise e
            continue

if __name__ == '__main__':
    run()
