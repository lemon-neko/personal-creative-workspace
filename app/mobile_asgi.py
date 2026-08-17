"""Production ASGI entry point for the private mobile gateway."""

from app.mobile_main import create_mobile_app


app = create_mobile_app()
