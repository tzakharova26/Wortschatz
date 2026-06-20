from bot.today import _card_text


def test_card_text_noun_escapes_html():
    text = _card_text(
        {
            "part_of_speech": "n",
            "article": "die",
            "german": "Tür <alt>",
            "plural": "Türen",
            "translation": "door & gate",
        }
    )
    assert text == "die Tür &lt;alt&gt; (pl: Türen) = door &amp; gate"


def test_card_text_phrase():
    text = _card_text(
        {
            "part_of_speech": "phrase",
            "german": "auf jeden Fall",
            "translation": "in any case",
        }
    )
    assert text == "auf jeden Fall (phrase) = in any case"
