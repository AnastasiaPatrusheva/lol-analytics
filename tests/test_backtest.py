"""Тесты метрик проверки модели «Состав» (scripts/build_composition_backtest.py)."""
import pandas as pd
import pytest

from build_composition_backtest import _auc, _head_to_head


def test_auc_perfect_separation():
    scores = pd.Series([0.1, 0.2, 0.8, 0.9])
    wins = pd.Series([False, False, True, True])
    assert _auc(scores, wins) == pytest.approx(1.0)


def test_auc_reversed_is_zero():
    scores = pd.Series([0.9, 0.8, 0.2, 0.1])
    wins = pd.Series([False, False, True, True])
    assert _auc(scores, wins) == pytest.approx(0.0)


def test_auc_all_tied_is_half():
    # одинаковые оценки не различают классы: средний ранг даёт ровно 0.5,
    # а не смещённое значение, как было бы при обычном RANK()
    scores = pd.Series([0.5] * 6)
    wins = pd.Series([True, True, True, False, False, False])
    assert _auc(scores, wins) == pytest.approx(0.5)


def _match(mid, s100, s200, win100):
    return [
        {"match_id": mid, "team_id": 100, "score": s100, "win": win100},
        {"match_id": mid, "team_id": 200, "score": s200, "win": not win100},
    ]


def test_head_to_head_counts_only_decided():
    rows = (_match("m1", 0.55, 0.45, True)      # выше оценка — победила: угадали
            + _match("m2", 0.55, 0.45, False)   # выше оценка — проиграла: мимо
            + _match("m3", 0.50, 0.50, True))   # ничья по оценке — не засчитываем
    hit, total = _head_to_head(pd.DataFrame(rows), "score")
    assert (hit, total) == (1, 2)


def test_head_to_head_symmetric_to_team_order():
    """Итог не должен зависеть от того, какая сторона записана первой."""
    a = pd.DataFrame(_match("m1", 0.6, 0.4, True))
    b = pd.DataFrame(_match("m1", 0.4, 0.6, False))   # те же данные, стороны поменяны
    assert _head_to_head(a, "score") == _head_to_head(b, "score")
