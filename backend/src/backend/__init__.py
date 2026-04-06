def main() -> None:
    print("Hello from backend!")
from .main import app, create_app

__all__ = ["app", "create_app"]
