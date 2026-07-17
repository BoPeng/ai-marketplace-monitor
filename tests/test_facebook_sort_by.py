import pytest

from ai_marketplace_monitor.facebook import SORT_BY_PARAM, FacebookItemConfig, SortBy


def _item_config(**kwargs: object) -> FacebookItemConfig:
    return FacebookItemConfig(
        name="test_item",
        search_phrases=["EMTB"],
        **kwargs,
    )


def test_sort_by_defaults_to_none() -> None:
    """When unspecified, sort_by stays None so no sortBy parameter is added."""
    assert _item_config().sort_by is None


@pytest.mark.parametrize("value", [s.value for s in SortBy])
def test_sort_by_accepts_valid_values(value: str) -> None:
    assert _item_config(sort_by=value).sort_by == value


def test_sort_by_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="sort_by must be one of"):
        _item_config(sort_by="oldest")


def test_sort_by_param_mapping_covers_non_default_values() -> None:
    """Every SortBy except the default `suggested` maps to a facebook query value."""
    expected = {s.value for s in SortBy} - {SortBy.SUGGESTED.value}
    assert set(SORT_BY_PARAM) == expected
    assert SORT_BY_PARAM[SortBy.NEW.value] == "creation_time_descend"
