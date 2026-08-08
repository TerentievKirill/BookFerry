import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CATALOG_DB_NAME
from scripts.import_anarchist import build_catalog


OPDS_URL = "https://ru.anarchistlibraries.net/opds/titles/1"
CATALOG_CODE = "anarchist_ru"
CATALOG_NAME = "Библиотека Анархизма"


if __name__ == "__main__":
    build_catalog(
        opds_url=OPDS_URL,
        catalog_db=Path(CATALOG_DB_NAME),
        catalog_code=CATALOG_CODE,
        catalog_name=CATALOG_NAME,
        default_language="ru",
    )
