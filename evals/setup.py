import hashlib
import importlib
import importlib.util
import shutil
import subprocess
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from evals.benchmark import Benchmark
from truesight.agent import model_from_env
from truesight.settings import LLMSettings, load

REPO = Path(__file__).resolve().parents[1]
BUILT_IN = "evals.benchmarks"


class ModelApi(StrEnum):
    CHAT = "chat"
    RESPONSES = "responses"


def load_benchmark(ref: str) -> Benchmark:
    if ref.endswith(".py"):
        path = Path(ref).expanduser().resolve()
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load benchmark file {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        try:
            module = importlib.import_module(f"{BUILT_IN}.{ref}")
        except ModuleNotFoundError as exc:
            raise ValueError(f"no built-in benchmark {ref!r}") from exc
    return module.create_benchmark()


def model_factory(api: ModelApi) -> Callable[[], Model]:
    if api is ModelApi.CHAT:
        return model_from_env
    return _responses_model


def _responses_model() -> Model:
    settings = load(LLMSettings)
    provider = OpenAIProvider(
        api_key=settings.api_key.get_secret_value(), base_url=str(settings.base_url).rstrip("/")
    )
    return OpenAIResponsesModel(
        settings.model,
        provider=provider,
        settings=OpenAIResponsesModelSettings(
            openai_store=False, timeout=settings.timeout_seconds, max_retries=settings.max_retries
        ),
    )


def git_state() -> tuple[str, bool]:
    git = shutil.which("git")
    if git is None:
        return ("unknown", True)
    sha = _git(git, "rev-parse", "HEAD") or "unknown"
    dirty = bool(_git(git, "status", "--porcelain", "--untracked-files=no"))
    return (sha, dirty)


def _git(git: str, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [git, *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
