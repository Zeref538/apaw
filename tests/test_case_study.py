import re

from web.build_case_study import build


def test_case_study_builds_with_every_number_filled_and_no_em_dash():
    html = build()
    assert not re.search(r"\{\{[A-Z0-9_]+\}\}", html)
    assert "/*%%DATA%%*/" not in html
    assert "\u2014" not in html
    assert "Not an official warning" in html
