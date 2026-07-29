import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


class Settings:
    META_APP_SECRET: str = ""
    META_VERIFY_TOKEN: str = ""
    INTERNAL_SERVICE_SECRET: str = ""
    DJANGO_INTERNAL_URL: str = ""

    def load(self) -> None:
        self.META_APP_SECRET = _require("META_APP_SECRET")
        self.META_VERIFY_TOKEN = _require("META_VERIFY_TOKEN")
        self.INTERNAL_SERVICE_SECRET = _require("INTERNAL_SERVICE_SECRET")
        self.DJANGO_INTERNAL_URL = _require("DJANGO_INTERNAL_URL")


settings = Settings()
