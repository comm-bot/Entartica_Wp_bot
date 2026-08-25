"""Tests for environment-backed application configuration."""

from app.config import Settings, get_settings


def test_settings_reads_supabase_secret_key(monkeypatch) -> None:
    """The server-side Supabase key uses the current environment variable."""

    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret-key")

    settings = Settings()

    assert settings.supabase_secret_key is not None
    assert settings.supabase_secret_key.get_secret_value() == "test-secret-key"


def test_embedding_configuration_requires_explicit_model_and_dimensions(monkeypatch) -> None:
    assert Settings(
        openai_api_key="test-key",
        openai_embedding_model=None,
        openai_embedding_dimensions=None,
    ).embedding_configuration_is_valid() is False

    assert Settings(
        openai_api_key="test-key",
        openai_embedding_model="approved-embedding-model",
        openai_embedding_dimensions=123,
    ).embedding_configuration_is_valid() is True


def test_settings_reads_knowledge_retrieval_threshold_and_top_k(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_MIN_SIMILARITY", "0.65")
    monkeypatch.setenv("KNOWLEDGE_TOP_K", "5")

    settings = Settings()

    assert settings.knowledge_min_similarity == 0.65
    assert settings.knowledge_top_k == 5


def test_langgraph_flag_defaults_and_process_environment_override(monkeypatch) -> None:
    monkeypatch.delenv("RAIPUR_LANGGRAPH_ENABLED", raising=False)
    assert Settings(_env_file=None).raipur_langgraph_enabled is True


def test_coimbatore_customer_details_form_defaults_and_ttl_override(monkeypatch) -> None:
    assert Settings(_env_file=None).coimbatore_customer_details_form_enabled is True
    monkeypatch.setenv("COIMBATORE_CUSTOMER_DETAILS_FORM_ENABLED", "false")
    monkeypatch.setenv("COIMBATORE_CUSTOMER_DETAILS_FORM_TTL_MINUTES", "45")
    monkeypatch.setenv("COIMBATORE_CUSTOMER_DETAILS_FLOW_ID", "published-flow-id")
    settings = Settings(_env_file=None)
    assert settings.coimbatore_customer_details_form_enabled is False
    assert settings.coimbatore_customer_details_form_ttl_minutes == 45
    assert settings.coimbatore_customer_details_flow_id == "published-flow-id"
    assert Settings(_env_file=None).coimbatore_langgraph_enabled is True
    monkeypatch.setenv("COIMBATORE_LANGGRAPH_ENABLED", "false")
    assert Settings(_env_file=None).coimbatore_langgraph_enabled is False
    monkeypatch.setenv("RAIPUR_LANGGRAPH_ENABLED", "true")
    assert Settings(_env_file=None).raipur_langgraph_enabled is True


def test_fine_tuned_sales_model_is_opt_in(monkeypatch) -> None:
    settings = Settings(_env_file=None, chiki_sales_fine_tuned_model="ft:test")
    assert settings.chiki_sales_fine_tuned_enabled is False
    assert settings.chiki_sales_fine_tuned_model == "ft:test"


def test_gold_fewshot_sales_composer_is_opt_in() -> None:
    settings = Settings(_env_file=None)
    assert settings.chiki_sales_gold_fewshot_enabled is False


def test_pontoon_template_and_flow_identifiers_are_optional_runtime_configuration(monkeypatch) -> None:
    monkeypatch.setenv("RAIPUR_PONTOON_CELEBRATION_TEMPLATE_ID", "approved-template")
    monkeypatch.setenv("RAIPUR_PONTOON_CELEBRATION_FLOW_ID", "approved-flow")
    settings = Settings(_env_file=None)
    assert settings.raipur_pontoon_celebration_template_id == "approved-template"
    assert settings.raipur_pontoon_celebration_flow_id == "approved-flow"


def test_cached_settings_keep_effective_flag_until_cache_is_cleared(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("RAIPUR_LANGGRAPH_ENABLED", "false")
    first = get_settings()
    monkeypatch.setenv("RAIPUR_LANGGRAPH_ENABLED", "true")
    assert get_settings() is first and get_settings().raipur_langgraph_enabled is False
    get_settings.cache_clear()
    assert get_settings().raipur_langgraph_enabled is True
    get_settings.cache_clear()
