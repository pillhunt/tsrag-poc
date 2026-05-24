from incident_intent.keyword_expand import expand_keywords_with_english


def test_expand_russian_adds_english():
    out, notes = expand_keywords_with_english(["сохран", "кнопк", "таймаут"])
    low = {k.casefold() for k in out}
    assert "save" in low
    assert "button" in low
    assert "timeout" in low
    assert notes


def test_english_only_unchanged():
    out, notes = expand_keywords_with_english(["PutProjectType", "SqlException"])
    assert "PutProjectType" in out
    assert len(notes) == 0
