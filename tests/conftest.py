import pytest

from investigator.config import Config
from investigator.warehouse.seed import build_warehouse


@pytest.fixture(scope="session")
def test_config(tmp_path_factory) -> Config:
    """A real synthetic warehouse built once per test session — every
    guardrail/detection test below is deterministic and makes zero LLM
    calls, so this fixture never touches the network."""
    db_path = tmp_path_factory.mktemp("warehouse") / "test_warehouse.db"
    config = Config(gemini_api_key="unused-in-tests", warehouse_path=db_path)
    build_warehouse(config)
    return config
