"""Tests for the questions answered without a model.

The value of these is entirely in when they decline. A matcher that fires on a
question it can only half answer is worse than no matcher: the user cannot see
which half was dropped, and the answer reads as though the coach considered the
rest and had nothing to say.
"""

from __future__ import annotations

import pytest

from hevy_coach.coach import answers
from hevy_coach.config import Settings
from hevy_coach.db import Database


class TestVolumeBalance:
    def test_reports_sets_per_week_against_the_goal_floor(
        self, db: Database, settings: Settings
    ) -> None:
        found = answers.answer("Is my volume distribution balanced?", db, settings)

        assert found is not None
        assert "sets/week" in found.answer
        assert "hypertrophy" in found.answer
        assert "8 sets/week per group" in found.answer, "the goal's own threshold"
        assert "volume" in found.source

    def test_a_goal_without_a_floor_says_so_rather_than_inventing_one(
        self, db: Database, settings: Settings
    ) -> None:
        """Powerlifting sets `low_weekly_sets = None` on purpose."""
        lifter = settings.model_copy(update={"training_goal": "powerlifting"})

        found = answers.answer("is my volume spread evenly?", db, lifter)

        assert found is not None
        assert "does not set a volume floor" in found.answer
        assert "below target" not in found.answer


class TestProgression:
    def test_answers_whether_a_named_lift_is_moving(
        self, db: Database, settings: Settings
    ) -> None:
        found = answers.answer("Am I progressing on bench press?", db, settings)

        assert found is not None
        assert "Bench Press (Barbell)" in found.answer
        assert "kg/month" in found.answer

    def test_carries_the_next_session_prescription(
        self, db: Database, settings: Settings
    ) -> None:
        """"and what should I do next" is answerable: session.py already does."""
        found = answers.answer("am I progressing on squat and what next", db, settings)

        assert found is not None
        assert "Next session:" in found.answer

    def test_a_nickname_is_not_guessed_at(self, db: Database, settings: Settings) -> None:
        """"bench" is not "Bench Press" - the model reads nicknames, this does not.

        Matching on a prefix would let "press" pick up the leg press, so the
        bare title has to appear in full and a nickname declines instead.
        """
        assert answers.answer("is my bench stalling", db, settings) is None
        assert answers.answer("is my bench press stalling", db, settings) is not None

    def test_declines_when_no_exercise_is_named(
        self, db: Database, settings: Settings
    ) -> None:
        assert answers.answer("am I progressing?", db, settings) is None

    def test_declines_on_an_exercise_that_is_not_in_the_log(
        self, db: Database, settings: Settings
    ) -> None:
        assert answers.answer("am I progressing on the snatch?", db, settings) is None

    def test_respects_the_display_unit(self, db: Database, settings: Settings) -> None:
        imperial = settings.model_copy(update={"units": "lb"})

        found = answers.answer("am I progressing on bench press", db, imperial)

        assert found is not None
        assert "lb" in found.answer
        assert "kg" not in found.answer.replace("kg/month", "")


class TestFurthestBehind:
    def test_names_the_weakest_lift_and_the_gap(
        self, db: Database, settings: Settings
    ) -> None:
        found = answers.answer("which lift is furthest behind the standards?", db, settings)

        assert found is not None
        assert "furthest behind" in found.answer
        assert "short of" in found.answer
        assert "Next session:" in found.answer

    def test_carries_the_placeholder_bodyweight_caveat(
        self, db: Database, tmp_path: object
    ) -> None:
        """A defaulted bodyweight rescales every level, so it must travel along."""
        unset = Settings(_env_file=None, database_path=db.path)

        found = answers.answer("what is my weakest lift by level", db, unset)

        assert found is not None
        assert "placeholder bodyweight" in found.answer


class TestDeclining:
    @pytest.mark.parametrize(
        "question",
        [
            "What should I change in my training this month?",
            "Is my volume balanced and should I change my split?",
            "which lift is furthest behind, and how do I fix it with a new programme?",
            "why is my bench stalling?",
            "am I progressing on bench press given my sleep has been bad",
            "should I deload my squat?",
            "how is my bench press looking",
            "",
            "hello",
        ],
    )
    def test_open_ended_questions_go_to_the_model(
        self, question: str, db: Database, settings: Settings
    ) -> None:
        assert answers.answer(question, db, settings) is None

    def test_an_empty_log_has_nothing_to_compute_from(
        self, empty_db: Database, settings: Settings
    ) -> None:
        assert answers.answer("is my volume balanced?", empty_db, settings) is None
