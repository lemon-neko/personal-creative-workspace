"""Production ASGI entry point for the desktop workspace.

Import application factories from :mod:`app.main` in tests and maintenance
tools.  Only the server entry point is allowed to initialize the real private
workspace.
"""

from app.main import create_app


app = create_app()
