"""Google GenAI adapter. Client creation is deferred until a request is made."""
from typing import Any

from app.core.config import get_gemini_api_key, get_gemini_model, get_gemini_timeout_seconds
from app.schemas.decision import AgentDecision


class ProviderError(RuntimeError):
    error_code = "provider_failure"
    safe_message = "The response provider failed."


class MissingApiKeyError(ProviderError):
    error_code = "missing_api_key"
    safe_message = "Gemini API key is not configured."


class ProviderTimeoutError(ProviderError):
    error_code = "provider_timeout"
    safe_message = "Gemini did not respond before the configured timeout."


class ProviderRateLimitError(ProviderError):
    error_code = "rate_limited"
    safe_message = "Gemini rate limit was reached."


class GeminiResponseAdapter:
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.api_key = api_key if api_key is not None else get_gemini_api_key()
        self.model = model or get_gemini_model()
        self.timeout_seconds = timeout_seconds or get_gemini_timeout_seconds()

    def generate(self, system_instruction: str, prompt: str, agent_id: int | None = None) -> Any:
        if not self.api_key:
            raise MissingApiKeyError()
        from google import genai
        from google.genai import errors, types
        import httpx

        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=int(self.timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=AgentDecision,
                    temperature=0.2,
                    max_output_tokens=500,
                ),
            )
            if getattr(response, "parsed", None) is not None:
                return response.parsed
            return response.text
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeoutError() from exc
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code == 429:
                raise ProviderRateLimitError() from exc
            if code in (408, 504):
                raise ProviderTimeoutError() from exc
            raise ProviderError() from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError() from exc
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                close()
