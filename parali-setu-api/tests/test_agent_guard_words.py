"""Found by a blind judge on the live site: numbers written as words slipped
past the number guardrail, and a softening "na" ("kar do na") read as a no."""
import pytest

import agent


@pytest.mark.parametrize("text, expected", [
    ("आपको छिहत्तर पैसे प्रति किलो मिलेंगे", {76.0, 0.76}),
    ("seventy six paise a kg", {76.0, 0.76}),
    ("सत्रह हज़ार पाँच सौ किलो", {17500.0}),
    ("17 हज़ार 500 किलो", {17000.0 + 500, 17.0, 500.0} - {17.0, 500.0} | {17.0, 500.0}),
    ("ਬਾਰਾਂ ਕਿੱਲੇ", {12.0}),
    ("twelve acres", {12.0}),
    ("one hundred and fifty", {150.0}),
])
def test_numbers_written_as_words(text, expected):
    assert expected <= agent.numbers_in(text)


@pytest.mark.parametrize("text", ["बुक कर दो", "ek baat batao", "एक सवाल है", "ਇੱਕ ਗੱਲ ਦੱਸੋ", "one more thing", "do it now"])
def test_everyday_words_are_not_numbers(text):
    assert agent.numbers_in(text) == set()


def test_a_number_in_words_that_no_tool_gave_is_blocked():
    assert agent.unsupported_numbers("आपको छिहत्तर पैसे मिलेंगे", ["मेरे पास 10 एकड़"], [{"price_per_kg": 0.6}]) == {76.0, 0.76}
    assert agent.unsupported_numbers("आपको साठ पैसे मिलेंगे", [], [{"price_per_kg": 0.6}]) == {60.0}, \
        "60 paise is the right price, but the bare 60 is not grounded: the rewrite asks for digits"


@pytest.mark.parametrize("words", ["book kar do na", "haan ji, kar do na", "बुक कर दो ना", "ਹਾਂ ਜੀ ਕਰ ਦਿਓ ਨਾ",
                                   "why not, book it", "haan, koi dikkat nahi, book kar do", "हाँ, कोई दिक्कत नहीं"])
def test_a_softened_yes_is_a_yes(words):
    assert agent.farmer_affirmed(words, None)


@pytest.mark.parametrize("words", ["nahi, abhi nahi", "no, not now", "मत करो", "ਨਹੀਂ ਜੀ", "kar do?", "na, rehne do"])
def test_a_no_or_a_question_is_still_not_a_yes(words):
    assert not agent.farmer_affirmed(words, None)
