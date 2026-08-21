#!/usr/bin/env python3
"""
main.py — production entry point.

Works with both start commands Railway may use:
  - `python main.py`      (runs uvicorn itself)
  - `uvicorn main:app`    (Railway's auto-detected FastAPI command)

For local interactive CLI, run:  python cli.py
"""
from server import build_app, main

app = build_app()

if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
