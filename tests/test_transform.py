"""Тесты нормализации id матча (build_common_analytics_layer.normalize_match_id)."""
import numpy as np

from build_common_analytics_layer import normalize_match_id


def test_nan_becomes_empty_string():
    assert normalize_match_id(np.nan) == ""


def test_float_integer_has_no_decimal_tail():
    # 123.0 -> "123", а не "123.0" (иначе id не совпадут между источниками)
    assert normalize_match_id(123.0) == "123"


def test_string_passthrough():
    assert normalize_match_id("EUW1_7875127465") == "EUW1_7875127465"


def test_plain_int():
    assert normalize_match_id(456) == "456"
