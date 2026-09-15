"""Orchestration that answers a natural-language data question using the served
OpenAI model (src/databricks_partner.py) as the reasoner and Genie
(src/genie_partner.py) as the data tool.

Flow: Formulate a precise question for Genie -> Retrieve data from Genie ->
Analyze that data (and only that data) into a CFO-ready answer.
"""

import pandas as pd

# from src.databricks_partner import generate
from src.openai_partner import generate_prompt_response as generate
from src.genie_partner import ask_genie

PROMPT_MAX_ROWS = 50

FORMULATE_SYSTEM_PROMPT = """You are a query-formulation assistant for a text-to-SQL \
data agent called Genie. Genie can only see a single natural-language question at a \
time -- it has no memory of any conversation before this one and it writes its own SQL.

Rewrite the user's question below into ONE single, precise, self-contained \
natural-language question that Genie can answer directly from the data warehouse.

Rules:
1. Output ONLY the rewritten question. No preamble, no explanation, no quotes.
2. Do not write SQL yourself -- Genie writes the SQL.
3. Preserve the user's intent exactly. Do not narrow, broaden, or add assumptions.
4. If the user's question already is a single precise question, return it unchanged.
"""

ANALYZE_SYSTEM_PROMPT = """You are an AI Financial Partner assisting a European bank \
CFO. You have been given the original question the CFO asked, and the response a \
text-to-SQL agent (Genie) produced to answer it.

Genie may respond with tabular query-result rows, a narrative text summary, or both. \
All of these are equally valid data sources.

Strict rules:
1. Use ONLY the information supplied below (Genie's summary, SQL, and/or tabular \
   data). Never invent numbers, trends, peer comparisons, or figures that are not \
   present in at least one of these sources.
2. If Genie provided a narrative summary with concrete figures, treat those figures \
   as authoritative even when no tabular rows were returned.
3. If ALL supplied sources (summary, SQL, and data) are empty or do not address the \
   question, say so plainly instead of guessing.
4. Do not perform speculative new calculations beyond simple arithmetic on the \
   supplied values (e.g. differences, percentages).
5. Keep the response concise, CFO-ready, and insight-oriented -- lead with the \
   answer, then the supporting figures.
6. This is a hackathon prototype; all data are SYNTHETIC and illustrative.
"""

_NO_DATA_MESSAGE = (
    "Genie did not return any data for this question, so no data-driven answer "
    "can be given."
)


def _build_formulate_prompt(user_question: str) -> str:
    return f"{FORMULATE_SYSTEM_PROMPT}\n\nUser question:\n{user_question}"


def _has_data(data) -> bool:
    if data is None:
        return False
    if isinstance(data, pd.DataFrame):
        return not data.empty
    return len(data) > 0


def _data_to_prompt_text(data) -> str:
    if not _has_data(data):
        return "(no rows returned)"

    if isinstance(data, pd.DataFrame):
        trimmed = data.head(PROMPT_MAX_ROWS)
        text = trimmed.to_csv(index=False)
        if len(data) > PROMPT_MAX_ROWS:
            text += f"... ({len(data) - PROMPT_MAX_ROWS} more rows truncated)\n"
        return text

    return str(data[:PROMPT_MAX_ROWS])


def _build_analyze_prompt(user_question: str, genie_result: dict) -> str:
    return f"""{ANALYZE_SYSTEM_PROMPT}

Original CFO question:
{user_question}

Genie's own summary:
{genie_result.get("answer_text") or "(none)"}

Genie's SQL:
{genie_result.get("sql") or "(none)"}

Genie's data:
{_data_to_prompt_text(genie_result.get("data"))}
"""


def answer_data_question(user_question: str) -> dict:
    """Answer a natural-language data question by formulating a Genie question,
    retrieving the data, and analyzing only that data into a final answer.
    """
    refined_question = generate(_build_formulate_prompt(user_question)).strip()

    genie_result = ask_genie(refined_question)
    data = genie_result.get("data")
    genie_note = (genie_result.get("answer_text") or "").strip()

    if _has_data(data) or genie_note:
        final_answer = generate(_build_analyze_prompt(user_question, genie_result)).strip()
    else:
        final_answer = _NO_DATA_MESSAGE

    return {
        "final_answer": final_answer,
        "refined_question": refined_question,
        "sql": genie_result.get("sql"),
        "data": data,
        "conversation_id": genie_result.get("conversation_id"),
    }


if __name__ == "__main__":
    result = answer_data_question("How did net interest income trend recently?")
    print("Final answer:", result["final_answer"])
    print("Refined question:", result["refined_question"])
    print("SQL:", result["sql"])
    print("Conversation ID:", result["conversation_id"])
    print("Data:")
    print(result["data"])