"""Tests for the provenance glossary.

It is a hand-written table, so these guard the invariants the frontend relies
on rather than the wording: a missing `plain` silently leaves jargon on screen
in plain-language mode, and a missing `detail` leaves a term with an empty
tooltip, neither of which fails loudly on its own.
"""

from __future__ import annotations

import pytest

from hevy_coach import provenance

#: Terms the UI cannot render without. Adding to this list is how you say a
#: number has become load-bearing enough to need explaining.
REQUIRED = (
    "e1rm",
    "volume",
    "working_set",
    "ramp_up",
    "sets_per_week",
    "trend",
    "level",
    "level_score",
    "percentile",
    "prescription",
    "deload",
)


@pytest.mark.parametrize("key", REQUIRED)
def test_the_surface_vocabulary_is_covered(key: str) -> None:
    assert key in provenance.BY_KEY


def test_keys_are_unique() -> None:
    keys = [term.key for term in provenance.TERMS]

    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("term", provenance.TERMS, ids=lambda t: t.key)
def test_every_term_is_complete(term: provenance.Term) -> None:
    assert term.term.strip()
    assert term.plain.strip()
    assert term.detail.strip()


@pytest.mark.parametrize("term", provenance.TERMS, ids=lambda t: t.key)
def test_every_detail_is_a_readable_sentence(term: provenance.Term) -> None:
    """It goes in a tooltip, so it has to be prose and it has to be short."""
    assert term.detail.endswith(".")
    # Sentence case, but "10% off a weight..." is legitimate prose.
    assert not term.detail[0].islower()
    assert len(term.detail) <= 320


@pytest.mark.parametrize("term", provenance.TERMS, ids=lambda t: t.key)
def test_no_plain_name_reintroduces_the_jargon(term: provenance.Term) -> None:
    """"e1RM" must not be explained as "e1RM"."""
    assert "e1rm" not in term.plain.lower()
    assert "1rm" not in term.plain.lower()
    assert "dots" not in term.plain.lower()


def test_glossary_is_keyed_for_lookup() -> None:
    glossary = provenance.glossary()

    assert glossary["e1rm"]["plain"] == "estimated best single"
    assert glossary["e1rm"]["key"] == "e1rm"
    assert set(glossary) == {term.key for term in provenance.TERMS}


def test_borrowed_numbers_are_attributed() -> None:
    """The standards are someone else's data; the tooltip has to say so."""
    assert provenance.BY_KEY["level"].source == "strengthlevel.com"
    assert provenance.BY_KEY["percentile"].source == "strengthlevel.com"
    # Ours carry no attribution.
    assert provenance.BY_KEY["volume"].source is None


def test_plain_falls_back_to_the_key() -> None:
    """An unknown id shows the id rather than blanking the label."""
    assert provenance.plain("e1rm") == "estimated best single"
    assert provenance.plain("not_a_term") == "not_a_term"
