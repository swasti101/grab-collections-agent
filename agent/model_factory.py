import os
import json
from functools import lru_cache
from typing import Any

import boto3
from dotenv import load_dotenv

load_dotenv()


class BedrockRuntimeResponse:
    def __init__(self, content: str, raw: dict[str, Any]) -> None:
        self.content = content
        self.raw = raw


class BedrockRuntimeChatModel:
    def __init__(
        self,
        *,
        client: Any,
        model_id: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens

    def invoke(self, prompt: Any) -> BedrockRuntimeResponse:
        payload = {
            "messages": [{"role": "user", "content": str(prompt)}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        body = json.loads(response["body"].read())
        return BedrockRuntimeResponse(content=_extract_text(body), raw=body)


def _extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts = [_extract_text(item) for item in payload]
        return "\n".join(part for part in parts if part).strip()
    if not isinstance(payload, dict):
        return str(payload)

    content = payload.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        if parts:
            return "\n".join(parts).strip()
    if isinstance(content, str) and content.strip():
        return content.strip()

    message = payload.get("message")
    if isinstance(message, dict):
        message_text = _extract_text(message.get("content"))
        if message_text:
            return message_text

    for key in ("outputText", "generation", "text", "result", "completion", "response"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            choice_text = _extract_text(first.get("message") or first.get("text") or first.get("content"))
            if choice_text:
                return choice_text

    return json.dumps(payload, ensure_ascii=True)


class ModelFactory:
    def __init__(self) -> None:
        self.region = os.getenv("BEDROCK_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not self.region:
            raise RuntimeError("BEDROCK_REGION or AWS_DEFAULT_REGION must be set for Bedrock.")

        self.reasoning_model_id = os.getenv("BEDROCK_REASONING_MODEL", "deepseek.v3.2")
        self.fast_model_id = os.getenv("BEDROCK_FAST_MODEL", self.reasoning_model_id)
        self.embed_model_id = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")

        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_session_token = os.getenv("AWS_SESSION_TOKEN")

        client_kwargs: dict[str, str] = {
            "service_name": "bedrock-runtime",
            "region_name": self.region,
        }
        if self.aws_access_key_id:
            client_kwargs["aws_access_key_id"] = self.aws_access_key_id
        if self.aws_secret_access_key:
            client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key
        if self.aws_session_token:
            client_kwargs["aws_session_token"] = self.aws_session_token

        # This mirrors the user's working sample: boto3.client(..., aws_access_key_id=..., aws_secret_access_key=..., aws_session_token=...)
        self._client = boto3.client(**client_kwargs)

    @property
    def client(self):
        return self._client

    def create_chat_model(
        self,
        *,
        model_id: str,
        temperature: float,
        max_tokens: int,
        **model_kwargs: Any,
    ) -> BedrockRuntimeChatModel:
        if model_kwargs:
            raise ValueError("Additional Bedrock runtime model kwargs are not supported by this adapter.")
        return BedrockRuntimeChatModel(
            client=self._client,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def create_reasoning_model(self) -> BedrockRuntimeChatModel:
        return self.create_chat_model(
            model_id=self.reasoning_model_id,
            temperature=0.3,
            max_tokens=1000,
        )

    def create_fast_model(self) -> BedrockRuntimeChatModel:
        return self.create_chat_model(
            model_id=self.fast_model_id,
            temperature=0.1,
            max_tokens=300,
        )


@lru_cache(maxsize=1)
def get_model_factory() -> ModelFactory:
    return ModelFactory()
