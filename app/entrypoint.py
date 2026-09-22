"""Container entry point: bind exactly the port assigned by the host."""
import uvicorn
from app.config import PORT

if __name__ == '__main__':
    uvicorn.run('app.main:app', host='0.0.0.0', port=PORT)
