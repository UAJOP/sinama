from app.config import SemanticJudgeProvider, Settings
from app.semantic_judge import OpenAISemanticJudge, SemanticJudge


def build_semantic_judge(settings: Settings) -> SemanticJudge | None:
    if settings.semantic_judge_provider is SemanticJudgeProvider.DISABLED:
        return None
    if settings.semantic_judge_provider is SemanticJudgeProvider.OPENAI:
        if settings.semantic_judge_api_key is None:
            # Settings validation owns this invariant; fail closed if a caller
            # bypasses normal settings construction.
            raise ValueError("Semantic judge API key is required for OpenAI provider.")
        return OpenAISemanticJudge(
            api_key=settings.semantic_judge_api_key,
            model=settings.semantic_judge_model,
            timeout_seconds=settings.semantic_judge_timeout_seconds,
            max_input_chars=settings.semantic_judge_max_input_chars,
        )
    raise ValueError("Unsupported semantic judge provider.")
