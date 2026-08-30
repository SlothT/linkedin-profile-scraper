import json
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def sample_payload() -> dict:
    return json.loads((_FIXTURES / "profile_sample.json").read_text())


@pytest.fixture
def rich_payload() -> dict:
    return json.loads((_FIXTURES / "profile_rich_sample.json").read_text())
