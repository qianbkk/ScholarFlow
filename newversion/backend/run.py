"""Dev runner: `python -m scholarflow_v3.run` or `python run.py`.

Run from inside newversion/backend/ so the relative import works.
"""
import uvicorn

from .app import create_app

app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "scholarflow_v3.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=9000,
        reload=False,
    )
