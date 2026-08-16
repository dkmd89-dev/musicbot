import pytest
from config import Config


@pytest.fixture
def config():
    return Config()
