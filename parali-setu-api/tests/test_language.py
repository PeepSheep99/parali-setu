"""The farmer never picks a language: it is read from what they say."""
import pytest

import language


@pytest.mark.parametrize("text, expected", [
    ("ਮੇਰੇ ਕੋਲ 10 ਕਿੱਲੇ ਝੋਨਾ ਹੈ", "Punjabi"),
    ("मेरे पास 8 एकड़ धान है", "Hindi"),
    ("I have 10 acres of paddy near Sangrur", "English"),
    ("mere kol 10 kille jhona hai, kanak 25 tak", "Punjabi"),
    ("mere paas 8 ekad dhaan hai, gehun kab tak", "Hindi"),
    ("Is this a government scheme?", "English"),
    ("আমার দশ বিঘা ধান আছে", language.UNSUPPORTED),
    ("میرے پاس دس ایکڑ ہیں", language.UNSUPPORTED),
    ("9876543210", None),
    ("", None),
])
def test_detect(text, expected):
    assert language.detect(text) == expected


@pytest.mark.parametrize("ongoing, words, expected", [
    # Found by bench/bench_agent.py: a romanised-Punjabi farmer giving a name and
    # number got the offer in English.
    ("Punjabi", "mera naam Gurpreet Singh, number 9876500007", "Punjabi"),
    ("Hindi", "mera naam Ramesh Kumar, number 9876500007", "Hindi"),
    ("Punjabi", "Gurpreet Singh 9876500007", "Punjabi"),
    ("English", "Gurpreet Singh 9876500007", "English"),
    # Clear evidence still switches the language.
    ("Punjabi", "My name is Gurpreet and I want to know when you will pay", "English"),
    ("Punjabi", "मेरा नाम रमेश है", "Hindi"),
    ("Hindi", "mere kol 10 kille jhona hai", "Punjabi"),
    (None, "mera naam Gurpreet, number 98765", "Punjabi"),
])
def test_a_name_and_a_number_do_not_switch_the_language(ongoing, words, expected):
    import agent
    conv = {"language": ongoing} if ongoing else None
    assert agent.reply_language(words, None, conv) == expected
