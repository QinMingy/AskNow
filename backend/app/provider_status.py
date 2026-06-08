import importlib.util

from .config import Settings
from .schemas import AssistProviderStatus


def get_assist_provider_status(settings: Settings) -> AssistProviderStatus:
    provider = settings.assist_provider.strip().lower().replace("-", "_")

    if provider in {"rule", "rules", "rule_based", "rulebased"}:
        return AssistProviderStatus(
            provider=settings.assist_provider,
            ready=True,
            mode="local_rules",
            required=[],
            missing=[],
            details=["Rule-based assist is available without an LLM service."],
            next_step="Use /api/assist directly, or switch ASSIST_PROVIDER when you want an LLM.",
        )

    if provider in {"openai", "openai_compatible", "local_llm", "llm"}:
        required = ["ASSIST_BASE_URL", "ASSIST_MODEL"]
        missing = []
        if not settings.assist_base_url:
            missing.append("ASSIST_BASE_URL")
        if not settings.assist_model:
            missing.append("ASSIST_MODEL")

        return AssistProviderStatus(
            provider=settings.assist_provider,
            ready=not missing,
            mode="openai_compatible",
            required=required,
            missing=missing,
            details=[
                "Uses a /chat/completions endpoint compatible with OpenAI Chat Completions.",
                f"base_url={settings.assist_base_url or '<missing>'}",
                f"model={settings.assist_model or '<missing>'}",
            ],
            next_step=(
                "Set ASSIST_BASE_URL and ASSIST_MODEL before starting the backend."
                if missing
                else "Provider configuration is complete. Test with a short /api/assist request."
            ),
        )

    if provider in {"litellm", "lite_llm"}:
        required = ["ASSIST_MODEL", "DEEPSEEK_API_KEY or ASSIST_API_KEY", "litellm package"]
        missing = []
        if not settings.assist_model:
            missing.append("ASSIST_MODEL")
        if not settings.assist_api_key:
            missing.append("DEEPSEEK_API_KEY or ASSIST_API_KEY")
        if importlib.util.find_spec("litellm") is None:
            missing.append("litellm package")

        details = [
            "Uses LiteLLM as a unified provider layer.",
            f"model={settings.assist_model or '<missing>'}",
        ]
        if settings.assist_base_url:
            details.append(f"base_url={settings.assist_base_url}")

        return AssistProviderStatus(
            provider=settings.assist_provider,
            ready=not missing,
            mode="litellm",
            required=required,
            missing=missing,
            details=details,
            next_step=(
                "Install LiteLLM and set DEEPSEEK_API_KEY or ASSIST_API_KEY before starting the backend."
                if missing
                else "LiteLLM configuration is complete. Test with a short /api/assist request."
            ),
        )

    return AssistProviderStatus(
        provider=settings.assist_provider,
        ready=False,
        mode="unsupported",
        required=[],
        missing=["ASSIST_PROVIDER"],
        details=[f"Unsupported assist provider: {settings.assist_provider}"],
        next_step="Use ASSIST_PROVIDER=rule_based, openai_compatible, or litellm.",
    )
