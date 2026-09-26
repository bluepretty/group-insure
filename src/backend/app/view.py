"""Template registry shared by the API layer.

Named ``view`` (not ``templates``) to avoid colliding with the
``app/templates`` directory.

The templates directory is resolved relative to this module so the app works
no matter where pytest or uvicorn is launched from.
"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
