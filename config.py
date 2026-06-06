import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MONTHLY_LIMIT_USD: float = float(os.getenv("CLAUDE_MONTHLY_LIMIT_USD", "2.00"))
GPT_MONTHLY_LIMIT_USD: float = float(os.getenv("GPT_MONTHLY_LIMIT_USD", "2.00"))
DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "claude-cli")
BRIDGE_BASE_URL: str = os.getenv("BRIDGE_BASE_URL", "http://127.0.0.1:8787")
BRIDGE_TOKEN: str = os.getenv("BRIDGE_TOKEN", "")
BRIDGE_CWD: str = os.getenv("BRIDGE_CWD", "/workspace/liby-runs")
BRIDGE_TIMEOUT_SEC: int = int(os.getenv("BRIDGE_TIMEOUT_SEC", "900"))
VAULT_PATH: str = os.getenv("VAULT_PATH", "./vault")
DB_PATH: str = os.getenv("DB_PATH", "./liby.db")

# Discord 봇 + 외부 열람(Tailscale). 토큰 비어 있으면 봇 비활성.
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_ALLOWED_USER_ID: str = os.getenv("DISCORD_ALLOWED_USER_ID", "")
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
BOT_API_TOKEN: str = os.getenv("BOT_API_TOKEN", "")

CLAUDE_MODELS: dict[str, str] = {
    "tier1": "claude-haiku-4-5",
    "tier2": "claude-sonnet-4-6",
    "tier3": "claude-opus-4-7",
}
GPT_MODELS: dict[str, str] = {
    "tier1": "gpt-4o-mini",
    "tier2": "gpt-4o",
    "tier3": "gpt-4o-mini",  # o1-mini 폐기 → 저비용 호환 모델로 대체
}
