from shared.dedup import normalize_name_for_dedup

def test_strips_trademark_and_edition_words():
    assert normalize_name_for_dedup('The Witcher 3: Wild Hunt – Game of the Year Edition') == 'witcher 3 wild hunt'

def test_collapses_punctuation():
    assert normalize_name_for_dedup('DOOM™ Eternal') == 'doom eternal'