"""Легенда архетипов на дашборде не должна отставать от ярлыков сборки."""
from build_player_segments import ARCHETYPE_BY_FEATURE

from dashboard.tabs.segments import ARCHETYPE_DESC, _legend


def test_every_build_label_has_description():
    assert set(ARCHETYPE_BY_FEATURE.values()) <= set(ARCHETYPE_DESC)


def test_legend_lists_only_given_groups_and_explains_refined_labels():
    text = _legend(["Часто умирает", "Керри + урон"])
    assert "**Часто умирает** — убийств на смерть меньше" in text
    assert "**Керри + урон** — убийств на смерть больше" in text
    assert "Агрессивный" not in text
