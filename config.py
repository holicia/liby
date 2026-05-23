import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MONTHLY_LIMIT_USD = float(os.getenv("CLAUDE_MONTHLY_LIMIT_USD", "2.00"))
GPT_MONTHLY_LIMIT_USD = float(os.getenv("GPT_MONTHLY_LIMIT_USD", "2.00"))
DEFAULT_AI_PROVIDER = os.getenv("DEFAULT_AI_PROVIDER", "claude")
VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
DB_PATH = os.getenv("DB_PATH", "./liby.db")

CLAUDE_MODELS = {
    "tier1": "claude-haiku-4-5",
    "tier2": "claude-sonnet-4-6",
    "tier3": "claude-opus-4-7",
}
GPT_MODELS = {
    "tier1": "gpt-4o-mini",
    "tier2": "gpt-4o",
    "tier3": "o1-mini",
}
