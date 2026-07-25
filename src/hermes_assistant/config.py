"""Configuration & settings for HERMES assistant (Pydantic v2)."""

import sys
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

def _compute_default_data_dir() -> str:
    """Return a platform-specific data directory outside the repository.

    Override at runtime with the ``HERMES_DATA_DIR`` environment variable.

    Defaults:
    - Windows:  ``%LOCALAPPDATA%\\hermes-data``
    - macOS/Linux: ``~/.hermes/data``
    """
    import os  # noqa: PLC0415

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return str(Path(base) / "hermes-data")
    return str(Path.home() / ".hermes" / "data")


_DEFAULT_DATA_DIR = _compute_default_data_dir()

# Project-type taxonomy ships with the package as YAML data. Resolved relative
# to this file so it works regardless of the caller's working directory.
_PKG_ROOT = Path(__file__).resolve().parent
_DEFAULT_PROJECT_TYPES_PATH = str(_PKG_ROOT / "hermes" / "project_types_data")
# Rubrics ship as YAML data alongside the package (Phase 3 critic).
_DEFAULT_RUBRICS_PATH = str(_PKG_ROOT / "rubrics" / "data")
# Calibration gold sets ship as YAML data alongside the package (Phase 4, C2).
_DEFAULT_CALIBRATION_PATH = str(_PKG_ROOT / "calibration" / "data")
# Library (failure modes + exemplars) ships as YAML data alongside the package.
_DEFAULT_LIBRARY_PATH = str(_PKG_ROOT / "library" / "data")


class Settings(BaseSettings):
    """Load from .env, environment, or defaults.

    All paths are local. No cloud endpoints are permitted: ``ollama_host``
    must point at loopback (enforced by the LLM client).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Data directory (Layer 1b) --------------------------------------- #
    # Platform-specific directory outside the repository for all runtime
    # SQLite databases and generated artefacts.  Override with the
    # ``HERMES_DATA_DIR`` environment variable.
    data_dir: str = Field(
        default=_DEFAULT_DATA_DIR,
        validation_alias=AliasChoices("HERMES_DATA_DIR", "data_dir"),
    )

    ollama_host: str = "http://localhost:11434"
    vectorstore_path: str = "./data/vectorstore"
    projects_path: str = "./data/projects"
    traces_path: str = "./data/traces/llm_trace.jsonl"
    ollama_num_thread: int = 10
    log_level: str = "INFO"

    # --- Project-type taxonomy (Phase 2) --------------------------------- #
    # Directory of YAML project-type definitions + the generic phase spine.
    # New project types are added as files here, with no code changes.
    project_types_path: str = _DEFAULT_PROJECT_TYPES_PATH

    # --- Calibration gold sets (Phase 4, C2) ----------------------------- #
    # Directory of human-graded gold YAML files ({rubric_id}.gold.yaml).
    calibration_path: str = _DEFAULT_CALIBRATION_PATH

    # --- Library (Phase P2) ---------------------------------------------- #
    # Directory with failure_modes/ and exemplars/ subdirectories.
    library_path: str = _DEFAULT_LIBRARY_PATH

    # --- Rubric critic & async job queue (Phase 3) ---------------------- #
    # Directory of versioned rubric YAML files ({id}.v{N}.yaml). New rubrics
    # are added as data with no code changes (mirrors project_types_path).
    rubrics_path: str = _DEFAULT_RUBRICS_PATH
    # SQLite job queue (WAL mode) and per-job JSONL traceability logs.
    queue_db_path: str = "./data/queue/jobs.db"
    queue_logs_path: str = "./data/queue/logs"
    # Critic model override. Empty -> use the roster CRITIC entry (thinking MoE,
    # a different family from the PLANNER draft model to reduce judge bias).
    critic_model: str = ""
    # Self-consistency samples per criterion (majority vote; odd number avoids
    # ties). Sample 1 is low-temperature; 2..N add diversity.
    critic_samples: int = 3

    # --- Diverse panel (Phase 5) ----------------------------------------- #
    # CSV of model IDs to use as panel judges (overrides default roster).
    # Empty -> use the default PANEL roster (qwen3:8b, gemma3:4b, llama3.1:8b).
    panel_models: str = ""
    # Minimum number of panelists required before degrading to single-judge.
    panel_min_judges: int = 2
    # Number of self-consistency samples per panelist (1 = no self-consistency).
    # Keep at 1 to avoid latency explosion on 16 GB hardware.
    panel_samples: int = 1
    # Optional YAML file path with per-model κ weights (empty = equal weights).
    panel_weights_path: str = ""

    # --- Task store (Phase 2.5) ------------------------------------------ #
    # SQLite database for the WBS task/pendenz tree.  Stored outside the repo
    # under data_dir to prevent accidental commits of runtime state.
    tasks_db_path: str = str(Path(_DEFAULT_DATA_DIR) / "tasks.db")

    # --- RAG (Phase 1) --------------------------------------------------- #
    # Single Chroma collection for the whole corpus; a per-model collection
    # split is deferred to Phase 2 (see rag/store.py).
    rag_collection_name: str = "hermes_corpus"
    # Dense retrieval fan-out (top-k chunks returned per query).
    rag_top_k: int = 5
    # Heading-aware chunking window and overlap, measured in ~word tokens.
    rag_chunk_size_tokens: int = 512
    rag_chunk_overlap_tokens: int = 64
    # Embedding model (must be pulled in local Ollama). bge-m3 = multilingual.
    rag_embed_model: str = "bge-m3"
    # Chunks embedded per Ollama /api/embed call during ingest.
    rag_embed_batch_size: int = 16


settings = Settings()
