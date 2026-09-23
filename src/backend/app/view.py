"""Template registry shared by the API layer.

Named ``view`` (not ``templates``) to avoid colliding with the
``app/templates`` directory.
"""
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
