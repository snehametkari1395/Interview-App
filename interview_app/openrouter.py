"""Small OpenRouter client; all model traffic passes through this module."""

import json
import os

import httpx
import streamlit as st

from interview_app.security_guard import GuardError, parse_json_object

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def get_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("OPENROUTER_API_KEY", "")).strip()
    except Exception:
        return ""


def get_model() -> str:
    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if model:
        return model
    try:
        return str(st.secrets.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")).strip()
    except Exception:
        return "openai/gpt-4o-mini"


def chat_json(system_prompt: str, user_payload: dict) -> dict:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("Add OPENROUTER_API_KEY to your environment or .streamlit/secrets.toml to enable AI feedback.")

    response = httpx.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": get_model(),
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
        },
        timeout=45.0,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise GuardError("OpenRouter returned an unexpected response. Please try again.") from error
    if not isinstance(content, str):
        raise GuardError("OpenRouter returned an unexpected response. Please try again.")
    return parse_json_object(content)