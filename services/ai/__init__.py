import config
from services.ai.claude import ClaudeProvider
from services.ai.openai_provider import OpenAIProvider
from services.ai.fallback import FallbackProvider
from services.ai.base import AIProvider

def get_provider(name: str | None = None) -> AIProvider:
    provider_name = name or config.DEFAULT_AI_PROVIDER
    if provider_name == "claude":
        return ClaudeProvider()
    if provider_name == "gpt":
        return OpenAIProvider()
    return FallbackProvider()
