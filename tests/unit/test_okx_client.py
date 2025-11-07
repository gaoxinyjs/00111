import pytest

from src.data.okx_client import OKXClient


@pytest.fixture(autouse=True)
def reset_okx_client():
    OKXClient.reset_instance()
    yield
    OKXClient.reset_instance()


def test_okx_client_singleton_identity():
    client_one = OKXClient()
    client_two = OKXClient.get_instance()
    assert client_one is client_two


@pytest.mark.asyncio
async def test_okx_client_session_lifecycle():
    client = OKXClient.get_instance()

    session = await client._ensure_session()
    assert client._session is session

    await client.close()

    assert client._session is None
