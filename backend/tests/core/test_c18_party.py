"""C18 mechanism 1: the counterparty is a soft, fuzzy signal, never a veto by default."""

import pytest

from teratai import extract, match

# (merchant on the transaction, span the customer wrote). Same party written differently: typo, spacing, case, noise.
_SAME = [
    ("GameVault", "gamevalt"), ("GoRide", "Go Ride"), ("GoRide", "goride"), ("PAYCOIN LTD", "@paycoin"),
    ("QUICKBUY STORE", "quickbuy"), ("ElektroHub Seremban", "electrohub"), ("TiketKu Travel", "tiketku travel"),
    ("Shalini a/p Nair", "Shalini"), ("Cheah Pei Shan", "cheah pei shan"), ("ShopLah Online", "shoplah"),
]  # fmt: skip
_DIFFERENT = [
    ("GoRide", "FoodKu"), ("Ravi a/l Velu", "Aisyah binti Hassan"), ("Hakim bin Ibrahim", "Faris bin Salleh"),
    ("GameVault", "LuxeGoods London"), ("PayCoin", "ShopLah"),
]  # fmt: skip
_NOT_NAMES = ["akaun berakhir 1548", "acc hujung 4921", "acc 1730", "akaun 9576", "2109", "Selasa", "my account", "the ATM"]


@pytest.mark.parametrize(("merchant", "span"), _SAME)
def test_same_party_written_differently_is_a_hit_and_never_a_mismatch(merchant: str, span: str) -> None:
    assert match.party_similarity(merchant, span) >= 0.8
    assert match.counterparty_hit(merchant, span, "")


@pytest.mark.parametrize(("merchant", "span"), _DIFFERENT)
def test_a_clearly_different_party_is_a_mismatch(merchant: str, span: str) -> None:
    assert match.party_similarity(merchant, span) < 0.5


@pytest.mark.parametrize("span", _NOT_NAMES)
def test_account_numbers_and_date_words_are_not_names(span: str) -> None:
    assert not extract.is_name_span(span)
    assert not match.counterparty_hit("Anything Sdn Bhd", span, "")  # not even a stray-token hit


@pytest.mark.parametrize("span", ["GoRide", "Cheah Pei Shan", "Nur Izzati", "LUXEGOODS LONDON", "@paycoin"])
def test_names_are_names(span: str) -> None:
    assert extract.is_name_span(span)
