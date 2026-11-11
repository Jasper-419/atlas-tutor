"""Apply versioned migrations. Atlas never creates an account with a built-in password."""

from alembic import command
from alembic.config import Config
from backend.config import ROOT


def ensure_schema():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    ensure_schema()
