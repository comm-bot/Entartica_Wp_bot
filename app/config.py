"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API."""

    app_name: str = "Entartica WhatsApp Chatbot"
    app_env: str = "development"
    app_revision: str = "local"
    router_revision: str = "raipur-router-20260802-1"
    debug: bool = False
    log_level: str = "INFO"
    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None
    exotel_account_sid: str | None = None
    exotel_api_key: SecretStr | None = None
    exotel_api_token: SecretStr | None = None
    exotel_api_base_url: str = Field(default="https://api.exotel.com", validation_alias=AliasChoices("EXOTEL_BASE_URL", "EXOTEL_API_BASE_URL"))
    exotel_whatsapp_from: str | None = None
    exotel_status_callback_url: str | None = None
    public_base_url: str | None = None
    coimbatore_customer_details_form_enabled: bool = True
    coimbatore_customer_details_form_ttl_minutes: int = 30
    coimbatore_customer_details_flow_id: str | None = None
    coimbatore_standard_razorpay_payment_button_id: str = "pl_TS1dAzTQUAPVxw"
    coimbatore_standard_up_to_9_razorpay_payment_button_id: str | None = None
    coimbatore_standard_up_to_12_razorpay_payment_button_id: str | None = None
    coimbatore_couple_romance_razorpay_payment_button_id: str = "pl_TS1ekmc61KTlf9"
    razorpay_enabled: bool = False
    razorpay_mode: Literal["test", "live"] = "test"
    razorpay_key_id: str | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_api_base_url: str = "https://api.razorpay.com/v1"
    exotel_outbound_enabled: bool = False
    exotel_signature_validation_enabled: bool = False
    openai_api_key: SecretStr | None = None
    openai_embedding_model: str | None = None
    openai_embedding_dimensions: int | None = None
    openai_chat_model: str | None = None
    chiki_sales_fine_tuned_model: str | None = None
    chiki_sales_fine_tuned_enabled: bool = False
    chiki_sales_gold_fewshot_enabled: bool = False
    knowledge_min_similarity: float = 0.65
    knowledge_top_k: int = 5
    knowledge_lexical_min_score: float = 0.30
    coimbatore_knowledge_min_similarity: float = 0.30
    coimbatore_persist_sales_state: bool = False
    coimbatore_langgraph_enabled: bool = True
    coimbatore_package_media_enabled: bool = True
    raipur_knowledge_min_confidence: float = 0.65
    app_timezone: str = "Asia/Kolkata"
    availability_max_age_minutes: int = 30
    raipur_availability_provider: Literal["unavailable", "supabase"] = "unavailable"
    raipur_inbound_orchestrator_enabled: bool = False
    raipur_draft_creation_enabled: bool = False
    raipur_draft_review_migration_ready: bool = False
    raipur_approved_draft_send_enabled: bool = False
    raipur_automatic_reply_enabled: bool = False
    # LangGraph is the primary Raipur conversation engine.  Set the explicit
    # compatibility flag to false only for an emergency legacy rollback.
    raipur_langgraph_enabled: bool = True
    raipur_langgraph_comparison_mode: bool = False
    raipur_automatic_reply_intents: Annotated[tuple[str, ...], NoDecode] = ("information", "location", "services")
    entartica_sales_phone: str = "+919429691418"
    entartica_sales_email: str = "sales@entartica.com"
    raipur_conversation_context_ttl_minutes: int = 120
    conversation_session_ttl_minutes: int = 30
    raipur_outbound_test_recipients: Annotated[tuple[str, ...], NoDecode] = ()
    interactive_whatsapp_enabled: bool = True
    raipur_general_quote_flow_id: str | None = None
    raipur_celebration_flow_id: str | None = None
    raipur_pontoon_celebration_flow_id: str | None = None
    raipur_pontoon_celebration_template_id: str | None = None
    mvp_default_location_code: str | None = "coimbatore"
    mvp_enabled_location_codes: Annotated[tuple[str, ...], NoDecode] = ("coimbatore",)
    active_location: Literal["coimbatore"] = "coimbatore"
    active_product: Literal["pontoon_celebration"] = "pontoon_celebration"
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    aws_region: str = "ap-south-1"
    s3_presigned_url_expiry_seconds: int = 3600
    coimbatore_confirmation_s3_bucket: str = "coimbatore-chatbot"
    coimbatore_confirmation_s3_prefix: str = "booking-confirmations"
    booking_confirmation_unicode_font_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("mvp_default_location_code", mode="before")
    @classmethod
    def normalize_default_location_code(cls, value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip().lower()

    @field_validator("mvp_enabled_location_codes", mode="before")
    @classmethod
    def normalize_enabled_location_codes(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        values = value.split(",") if isinstance(value, str) else value
        if not isinstance(values, (list, tuple, set)):
            return ()
        return tuple(dict.fromkeys(item.strip().lower() for item in values if isinstance(item, str) and item.strip()))

    @field_validator("raipur_outbound_test_recipients", mode="before")
    @classmethod
    def normalize_test_recipients(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, str): return ()
        return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))

    @field_validator("raipur_automatic_reply_intents", mode="before")
    @classmethod
    def normalize_automatic_reply_intents(cls, value: object) -> tuple[str, ...]:
        values = value.split(",") if isinstance(value, str) else value
        if not isinstance(values, (list, tuple, set)):
            return ()
        return tuple(dict.fromkeys(item.strip().lower() for item in values if isinstance(item, str) and item.strip()))

    def mvp_location_configuration_is_valid(self) -> bool:
        """Return whether the configured MVP location scope is usable."""

        return bool(
            self.mvp_default_location_code
            and self.mvp_enabled_location_codes
            and self.mvp_default_location_code in self.mvp_enabled_location_codes
        )

    def embedding_configuration_is_valid(self) -> bool:
        """Return whether live embedding calls have an explicit safe configuration."""

        return bool(
            self.openai_api_key
            and self.openai_embedding_model
            and self.openai_embedding_dimensions
            and self.openai_embedding_dimensions > 0
        )

    @field_validator("knowledge_min_similarity")
    @classmethod
    def validate_knowledge_min_similarity(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("knowledge_min_similarity must be between zero and one.")
        return value

    @field_validator("knowledge_top_k")
    @classmethod
    def validate_knowledge_top_k(cls, value: int) -> int:
        if value < 1:
            raise ValueError("knowledge_top_k must be positive.")
        return value

    @field_validator("knowledge_lexical_min_score")
    @classmethod
    def validate_knowledge_lexical_min_score(cls, value: float) -> float:
        if not 0 <= value <= 1: raise ValueError("knowledge_lexical_min_score must be between zero and one.")
        return value

    @field_validator("availability_max_age_minutes")
    @classmethod
    def validate_availability_max_age_minutes(cls, value: int) -> int:
        if value < 1:
            raise ValueError("availability_max_age_minutes must be positive.")
        return value

    @field_validator("raipur_conversation_context_ttl_minutes")
    @classmethod
    def validate_raipur_conversation_context_ttl_minutes(cls, value: int) -> int:
        if value < 1:
            raise ValueError("raipur_conversation_context_ttl_minutes must be positive.")
        return value

    @field_validator("conversation_session_ttl_minutes")
    @classmethod
    def validate_conversation_session_ttl_minutes(cls, value: int) -> int:
        if value < 1: raise ValueError("conversation_session_ttl_minutes must be positive.")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""

    return Settings()
