import os

from dotenv import load_dotenv

load_dotenv()

DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
DATABRICKS_SERVING_ENDPOINT = os.getenv("DATABRICKS_SERVING_ENDPOINT", "")
GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "")

USE_MOCKS = not GENIE_SPACE_ID


def databricks_configured() -> bool:
    return not USE_MOCKS