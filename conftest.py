import shutil
import tempfile
from typing import Callable, Generator

import pytest
from diskcache import Cache
from pytest import TempPathFactory

import ai_marketplace_monitor
from ai_marketplace_monitor.ai import OllamaBackend, OllamaConfig
from ai_marketplace_monitor.facebook import FacebookItemConfig
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.user import User, UserConfig


@pytest.fixture
def version() -> Generator[str, None, None]:
    """Sample pytest fixture."""
    yield ai_marketplace_monitor.__version__


@pytest.fixture
def listing() -> Listing:
    return Listing(
        marketplace="facebook",
        name="test",
        id="111",
        title="dddd",
        image="",
        price="$10",
        post_url="https://www.facebook.com/marketplace/item/1234567890",
        location="houston, tx",
        seller="some guy",
        condition="New",
        description="something good",
    )


@pytest.fixture
def item_config() -> FacebookItemConfig:
    return FacebookItemConfig(
        name="test",
        description="long description",
        enabled=True,
        antikeywords=["exclude1", "exclude2"],
        keywords=["include1", "include2"],
        search_phrases=["search word one"],
        marketplace="facebook",
        search_city=["houston"],
        # the following are common options
        seller_locations=["city"],
        condition=["new", "used_good"],
        date_listed=[7],
        ai=["openai"],
        availability=["out", "all"],
        delivery_method=["local_pick_up"],
        exclude_sellers=["seller"],
        max_price=300,
        rating=[4],
        max_search_interval=1000,
        search_interval=12,
        min_price=200,
        notify=["user1"],
        radius=[100],
        search_region=["usa"],
    )


@pytest.fixture
def ollama_config() -> OllamaConfig:
    return OllamaConfig(
        name="ollama",
        api_key="ollama",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b",
        max_retries=10,
    )


@pytest.fixture(scope="session")
def config_file(tmp_path_factory: TempPathFactory) -> Callable:
    def generate_config_file(content: str) -> str:
        fn = tmp_path_factory.mktemp("config") / "test.toml"
        with open(fn, "w") as f:
            f.write(content)
        return str(fn)

    return generate_config_file


@pytest.fixture
def temp_cache() -> Generator[Cache, None, None]:
    temp_dir = tempfile.mkdtemp()
    cache = Cache(temp_dir)
    yield cache
    cache.close()
    shutil.rmtree(temp_dir)


@pytest.fixture
def user_config() -> UserConfig:
    return UserConfig(
        name="test",
        pushbullet_token="whatever",
        remind=True,
    )


@pytest.fixture
def user(user_config: UserConfig) -> User:
    return User(user_config)


@pytest.fixture
def ollama(ollama_config: OllamaConfig) -> User:
    return OllamaBackend(ollama_config)
