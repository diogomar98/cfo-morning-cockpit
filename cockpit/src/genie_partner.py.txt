"""Client for asking natural-language questions against a Databricks Genie Space.

Uses ``WorkspaceClient().genie`` (databricks-sdk's ``GenieAPI``) to start/continue a
conversation, waits for the AI response, and pulls out the answer text, generated SQL,
and query result rows.
"""

import pandas as pd

from src.config import USE_MOCKS, GENIE_SPACE_ID

GENIE_ROW_CAP = 100

_MOCK_ANSWER_TEXT = (
    "[MOCK Genie response] Q3 net interest income was EUR 412M, up 3.1% QoQ, "
    "driven by higher loan volumes in the corporate book. No live Genie Space "
    "is configured -- set GENIE_SPACE_ID (and Databricks auth) to enable live queries."
)

_MOCK_SQL = (
    "SELECT quarter, net_interest_income_eur_m\n"
    "FROM finance.gold.income_statement\n"
    "WHERE quarter = '2025-Q3'"
)

_MOCK_DATA = pd.DataFrame(
    [
        {"quarter": "2025-Q2", "net_interest_income_eur_m": 400},
        {"quarter": "2025-Q3", "net_interest_income_eur_m": 412},
    ]
)


def _mock_response() -> dict:
    return {
        "answer_text": _MOCK_ANSWER_TEXT,
        "sql": _MOCK_SQL,
        "data": _MOCK_DATA,
        "conversation_id": "mock-conversation-id",
    }


def _get_client():
    import os
    import streamlit as st
    from databricks.sdk import WorkspaceClient

    user_token = st.context.headers.get("X-Forwarded-Access-Token")
    if user_token:
        return WorkspaceClient(
            host=os.environ.get("DATABRICKS_HOST"),
            token=user_token,
            auth_type="pat",
        )
    return WorkspaceClient()


def _extract_answer_text(message) -> str:
    parts = []
    for attachment in getattr(message, "attachments", None) or []:
        text_obj = getattr(attachment, "text", None)
        if text_obj:
            text_content = getattr(text_obj, "content", None)
            if text_content:
                parts.append(text_content)
    if parts:
        return "\n\n".join(parts)
    return getattr(message, "content", "") or ""


def _extract_query_attachment(message):
    for attachment in getattr(message, "attachments", None) or []:
        if getattr(attachment, "query", None) is not None:
            return attachment
    return None


def _rows_to_dataframe(query_result) -> pd.DataFrame:
    statement_response = getattr(query_result, "statement_response", None)
    if statement_response is None:
        return pd.DataFrame()

    result_obj = getattr(statement_response, "result", None)
    if result_obj is None:
        return pd.DataFrame()

    manifest = getattr(statement_response, "manifest", None)
    schema_obj = getattr(manifest, "schema", None) if manifest else None
    schema_columns = getattr(schema_obj, "columns", None) if schema_obj else None
    columns = (
        [getattr(col, "name", f"col_{i}") for i, col in enumerate(schema_columns)]
        if schema_columns
        else None
    )

    data_array = getattr(result_obj, "data_array", None) or []
    capped_rows = data_array[:GENIE_ROW_CAP]

    if columns:
        return pd.DataFrame(capped_rows, columns=columns)
    return pd.DataFrame(capped_rows)


def _fetch_query_result(client, space_id, conversation_id, message_id, attachment_id):
    """Retrieve Genie query results, resilient across SDK versions."""
    # Try SDK methods (name changed across versions)
    for method_name in (
        "get_message_attachment_query_result",
        "get_message_query_result_by_attachment",
        "execute_message_attachment_query",
    ):
        method = getattr(client.genie, method_name, None)
        if method is not None:
            return method(
                space_id=space_id,
                conversation_id=conversation_id,
                message_id=message_id,
                attachment_id=attachment_id,
            )

    # Fallback: direct REST API call
    import requests

    host = client.config.host.rstrip("/")
    token = getattr(client.config, "token", None)
    headers = {"Authorization": f"Bearer {token}"}

    url = (
        f"{host}/api/2.0/genie/spaces/{space_id}"
        f"/conversations/{conversation_id}"
        f"/messages/{message_id}"
        f"/attachments/{attachment_id}/query-result"
    )
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return _parse_rest_query_result(resp.json())


def _parse_rest_query_result(data: dict):
    """Wrap REST JSON in a minimal object matching the SDK shape."""

    class _Obj:
        def __init__(self, d):
            for k, v in d.items():
                if isinstance(v, dict):
                    setattr(self, k, _Obj(v))
                elif isinstance(v, list):
                    setattr(self, k, [_Obj(i) if isinstance(i, dict) else i for i in v])
                else:
                    setattr(self, k, v)

        def __getattr__(self, name):
            return None

    return _Obj(data)


def _msg_attr(obj, *names):
    """Return the first truthy attribute found on *obj* from *names*.

    Tries direct attribute access first, then falls back to dictionary
    introspection via as_dict() / vars() to handle SDK versions where
    fields exist in the serialised form but not as Python attributes.
    """
    if obj is None:
        return None
    # 1. Direct attribute access
    for name in names:
        val = getattr(obj, name, None)
        if val is not None:
            return val
    # 2. Dictionary introspection fallback
    d = None
    if hasattr(obj, "as_dict"):
        try:
            d = obj.as_dict()
        except Exception:
            pass
    if d is None:
        try:
            d = vars(obj)
        except TypeError:
            pass
    if isinstance(d, dict):
        for name in names:
            val = d.get(name)
            if val is not None:
                return val
    return None


def ask_genie(question: str, conversation_id: str | None = None) -> dict:
    """Ask Genie a natural-language question and return its answer, SQL, and data.

    Starts a new Genie conversation, or continues an existing one when
    ``conversation_id`` is given. Waits (polls) until the response is complete,
    then extracts the text answer, the generated SQL (if any), and up to
    ``GENIE_ROW_CAP`` rows of query result data.
    """
    if USE_MOCKS:
        return _mock_response()

    if not GENIE_SPACE_ID:
        raise RuntimeError("GENIE_SPACE_ID is missing. Add it to the .env file.")

    client = _get_client()

    try:
        if conversation_id:
            message = client.genie.create_message_and_wait(
                space_id=GENIE_SPACE_ID,
                conversation_id=conversation_id,
                content=question,
            )
        else:
            message = client.genie.start_conversation_and_wait(
                space_id=GENIE_SPACE_ID,
                content=question,
            )

        msg_status = getattr(message, "status", None)
        if msg_status:
            status_val = getattr(msg_status, "value", msg_status)
            if str(status_val) == "FAILED":
                err_obj = getattr(message, "error", None)
                error_text = getattr(err_obj, "error", "Unknown error") if err_obj else "Unknown error"
                raise RuntimeError(f"Genie query failed: {error_text}")

        answer_text = _extract_answer_text(message)

        sql = None
        data = pd.DataFrame()
        query_attachment = _extract_query_attachment(message)
        if query_attachment is not None:
            query_obj = getattr(query_attachment, "query", None)
            sql = getattr(query_obj, "query", None) if query_obj else None
            msg_conversation_id = _msg_attr(message, "conversation_id", "id")
            msg_message_id = _msg_attr(message, "message_id", "id")
            att_id = (
                _msg_attr(query_attachment, "attachment_id", "id")
                or _msg_attr(query_obj, "id", "attachment_id", "statement_id")
            )

            # Data fetch is best-effort — answer text + SQL are the priority.
            try:
                msg_qr = getattr(message, "query_result", None)
                if msg_qr is not None:
                    data = _rows_to_dataframe(msg_qr)
                elif att_id is not None:
                    query_result = _fetch_query_result(
                        client,
                        space_id=GENIE_SPACE_ID,
                        conversation_id=msg_conversation_id,
                        message_id=msg_message_id,
                        attachment_id=att_id,
                    )
                    data = _rows_to_dataframe(query_result)
            except Exception:
                data = pd.DataFrame()  # graceful degradation

        return {
            "answer_text": answer_text,
            "sql": sql,
            "data": data,
            "conversation_id": _msg_attr(message, "conversation_id", "id"),
        }
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Genie partner error: {exc}") from exc


if __name__ == "__main__":
    result = ask_genie("What was net interest income in the most recent quarter?")
    print("Answer:", result["answer_text"])
    print("SQL:", result["sql"])
    print("Conversation ID:", result["conversation_id"])
    print("Data:")
    print(result["data"])