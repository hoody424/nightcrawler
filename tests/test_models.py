import pytest

from nightcrawler.models import Condition, parse_condition, parse_price


@pytest.mark.parametrize("text,expected", [
    ("1.299,00 €", 1299.0), ("$1,299.99", 1299.99), ("EUR 45", 45.0), ("389,00 € VB", 389.0),
    ("12,5", 12.5), ("1 299 €", 1299.0), ("CHF 1'250.50", 1250.5), ("free", None), (None, None), (42, 42.0),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Gebraucht", Condition.USED), ("Brand New", Condition.NEW), ("Neu", Condition.NEW),
    ("Generalüberholt", Condition.REFURBISHED), ("Pre-owned", Condition.USED), ("wie neu", Condition.USED),
    ("Neuwertig", Condition.USED), ("", Condition.UNKNOWN), ("blue", Condition.UNKNOWN),
])
def test_parse_condition(text, expected):
    assert parse_condition(text) is expected
