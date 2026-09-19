import pytest

from tracekite.db import store_config


@pytest.mark.parametrize("password", [
    "",
    "password",
    "neo4j",
    "change-me-to-something-long",
])
def test_distributed_passwords_are_unsafe(password):
    assert store_config.is_unsafe_neo4j_password(password)


def test_generated_password_is_not_a_known_default():
    assert not store_config.is_unsafe_neo4j_password(
        "a4a0d40b2b1c97fe536ef563dd37fbf734dce8dd")
