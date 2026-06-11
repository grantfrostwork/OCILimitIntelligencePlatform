from app.services.collector import _percent_used


def test_percent_used_normal_case():
    assert _percent_used(100, 25) == 25


def test_percent_used_zero_allowed_zero_usage():
    assert _percent_used(0, 0) == 0


def test_percent_used_zero_allowed_positive_usage():
    assert _percent_used(0, 1) == 100


def test_percent_used_missing_values():
    assert _percent_used(None, 1) is None
    assert _percent_used(10, None) is None
