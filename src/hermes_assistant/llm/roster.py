"""Model roster & configuration for the HERMES assistant (Pydantic v2).

Target hardware: 32 GB RAM + RTX A500 4 GB (prod) / 16 GB M4 Air (local POC).
ROUTER and EMBED run fully on GPU (num_gpu=1).  PLANNER and CRITIC are 30B MoE
models — one resident at a time; KV-cache q8_0 mandatory (spec §11).
"""

from enum import Enum

from pydantic import BaseModel


class ModelRole(str, Enum):
    """Model roles in the system."""

    ROUTER = "router"  # Fast intent/extraction (4B)
    PLANNER = "planner"  # Workhorse drafting (30B-A3B instruct)
    CRITIC = "critic"  # Final review/judge (30B-A3B thinking or gpt-oss-20b)
    EMBED = "embed"  # Embeddings (bge-m3)
    PANEL = "panel"  # Diverse judge panel (multiple families, 4-8B each)


class ModelMode(str, Enum):
    """Inference mode for a model."""

    INSTRUCT = "instruct"
    THINKING = "thinking"
    EMBED = "embed"


class ModelConfig(BaseModel):
    """Configuration for a single model in the roster."""

    id: str
    mode: ModelMode
    description: str
    tok_s_estimate: int | None = None
    fallback: str | None = None
    # GPU layer hint passed to Ollama (0=CPU-only, 1+=GPU). None = Ollama default.
    # Per spec §11: ROUTER and EMBED fully on GPU; 30B models CPU/GPU shared.
    num_gpu: int | None = None


# Model configs per role (prod: 32 GB RAM + RTX A500 4 GB; POC: M4 Air 16 GB)
ROSTER: dict[ModelRole, ModelConfig] = {
    ModelRole.ROUTER: ModelConfig(
        id="qwen3:4b",
        mode=ModelMode.INSTRUCT,
        tok_s_estimate=15,
        description="Fast intent routing & field extraction",
        num_gpu=1,  # fully on GPU per spec §11
    ),
    ModelRole.PLANNER: ModelConfig(
        id="qwen3-30b-a3b-instruct-2507:q4_K_M",
        mode=ModelMode.INSTRUCT,
        tok_s_estimate=8,
        description="Workhorse planner & drafter (MoE, low active params)",
        # One resident at a time; KV-cache q8_0 mandatory (spec §11)
    ),
    ModelRole.CRITIC: ModelConfig(
        id="qwen3-30b-a3b-thinking-2507:q4_K_M",
        mode=ModelMode.THINKING,
        tok_s_estimate=8,
        description="Critic/judge (thinking, capped ~1-2K tokens)",
        fallback="gpt-oss:20b",
        # One resident at a time; KV-cache q8_0 mandatory (spec §11)
    ),
    ModelRole.EMBED: ModelConfig(
        id="bge-m3",
        mode=ModelMode.EMBED,
        tok_s_estimate=None,  # Not applicable for embeddings
        description="Multilingual dense + sparse embeddings",
        num_gpu=1,  # fully on GPU per spec §11
    ),
}


def get_model_config(role: ModelRole) -> ModelConfig:
    """Get the full config for a given role."""
    return ROSTER[role]


def get_model(role: ModelRole) -> str:
    """Get model ID for a given role."""
    return ROSTER[role].id


def get_model_description(role: ModelRole) -> str:
    """Get human description of model."""
    return ROSTER[role].description


# Diverse panel roster — three different model families for Phase 5 evaluation.
# Sequential execution on 16 GB machine; peak resident ~5.3 GB per model.
# Order is reproducibility-critical (affects tie-break in deterministic tests).
PANEL: list[ModelConfig] = [
    ModelConfig(
        id="qwen3:8b",
        mode=ModelMode.INSTRUCT,
        tok_s_estimate=12,
        description="Panel judge — Qwen3 8B (Alibaba)",
    ),
    ModelConfig(
        id="gemma3:4b",
        mode=ModelMode.INSTRUCT,
        tok_s_estimate=15,
        description="Panel judge — Gemma 3 4B (Google)",
    ),
    ModelConfig(
        id="llama3.1:8b",
        mode=ModelMode.INSTRUCT,
        tok_s_estimate=10,
        description="Panel judge — Llama 3.1 8B (Meta)",
    ),
]


def get_panel_configs() -> list[ModelConfig]:
    """Return the diverse panel model configurations."""
    return PANEL
