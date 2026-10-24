"""Application configuration settings."""
import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Customer Support Resolution Agent"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    AUTH_MODE: str = "demo"  # demo identities are accepted only in development
    PAYMENT_PROVIDER: str = "mock"
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    ALLOW_LIVE_PAYMENT_CREDENTIALS: bool = False
    ASYNC_WORKFLOWS: bool = False
    SEED_DEMO_DATA: bool = True
    AUTO_CREATE_SCHEMA: bool = True
    OIDC_ISSUER: Optional[str] = None
    OIDC_AUDIENCE: str = "support-api"
    OIDC_CLIENT_ID: str = "support-portal"
    OIDC_REQUIRE_STAFF_MFA: bool = True
    OIDC_REVIEW_LIMIT_MINOR: int = 50000
    INTEGRATION_BASE_URL: Optional[str] = None
    INTEGRATION_API_TOKEN: Optional[str] = None
    REQUESTS_PER_MINUTE: int = 120
    POLICY_MIN_LEXICAL_OVERLAP: float = 0.12
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./support_agent.db")
    SYNC_DATABASE_URL: str = os.getenv("SYNC_DATABASE_URL", "sqlite:///./support_agent.db")
    
    # LangGraph & Checkpointing
    CHECKPOINT_DATABASE_URL: str = os.getenv("CHECKPOINT_DATABASE_URL", "sqlite:///./checkpoints.db")
    
    # Security / Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-dev-key-change-in-prod-xyz789")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # 24 hours
    
    # Store settings
    STORE_NAME: str = "ElectroVault Global"
    CURRENCY: str = "USD"
    MAX_AUTO_REFUND_LIMIT_MINOR: int = 0 # 0 means EVERY refund strictly requires human approval
    PROPOSAL_EXPIRY_HOURS: int = 48
    
    # LLM Settings (OpenAI, Gemini, Anthropic, or mock deterministic fallback)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock") # mock or openai (explicit opt-in)
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", None)
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", None)
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY", None)
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    
    # Mock external service behaviors
    PAYMENT_TIMEOUT_MS: int = int(os.getenv("PAYMENT_TIMEOUT_MS", "3000"))
    SIMULATE_TIMEOUT_FOR_KEY_PREFIX: str = "timeout_test_"
    SIMULATE_FAILURE_FOR_KEY_PREFIX: str = "fail_test_"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
