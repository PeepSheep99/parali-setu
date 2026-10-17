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
