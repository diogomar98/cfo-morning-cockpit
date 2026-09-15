from src.config import (
    USE_MOCKS,
    DATABRICKS_HOST,
    DATABRICKS_TOKEN,
    DATABRICKS_SERVING_ENDPOINT,
)
from src.openai_partner import build_executive_prompt

_MOCK_COCKPIT_RESPONSE = (
    "[MOCK Databricks response] CET1 ratio is within the reported range. "
    "NIM and cost-to-income figures reflect the latest synthetic data. "
    "No live Databricks endpoint is configured -- set DATABRICKS_HOST and "
    "DATABRICKS_TOKEN in .env to enable live model serving."
)

_MOCK_SIGNAL_JSON = '{"signals": []}'


def _get_client():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(host=DATABRICKS_HOST, token=DATABRICKS_TOKEN)


def _query_endpoint(prompt: str) -> str:
    if not DATABRICKS_SERVING_ENDPOINT:
        raise RuntimeError(
            "DATABRICKS_SERVING_ENDPOINT is missing. Add it to the .env file."
        )

    client = _get_client()
    response = client.serving_endpoints.query(
        name=DATABRICKS_SERVING_ENDPOINT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content if response.choices else None
    if not text:
        raise RuntimeError(
            "Databricks serving endpoint returned an empty response. "
            "Check the endpoint name, token, and model availability."
        )

    return text


def generate_databricks_response(cockpit_facts: dict, user_question: str) -> str:
    if USE_MOCKS:
        return _MOCK_COCKPIT_RESPONSE

    prompt = build_executive_prompt(user_question, cockpit_facts)
    try:
        return _query_endpoint(prompt)
    except Exception as exc:
        raise RuntimeError(f"Databricks partner error: {exc}") from exc


def generate(prompt: str) -> str:
    if USE_MOCKS:
        return _MOCK_SIGNAL_JSON

    try:
        return _query_endpoint(prompt)
    except Exception as exc:
        raise RuntimeError(f"Databricks partner error: {exc}") from exc