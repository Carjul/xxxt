"""Entrypoint para correr el dashboard localmente."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "5000")), reload=True)
