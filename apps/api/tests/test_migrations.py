import re
from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "migrations"


def test_numbered_migrations_are_contiguous_and_unique():
    files = sorted(MIGRATIONS.glob("*.sql"))
    numbers = [int(path.name.split("_", 1)[0]) for path in files]
    assert numbers == list(range(1, len(files) + 1))
    assert len(numbers) == len(set(numbers))


def test_phase9_indexes_match_bounded_query_shapes():
    migration = (MIGRATIONS / "009_query_bounds.sql").read_text(encoding="utf-8")
    for index_name in (
        "ix_infrastructure_relationship_from_type",
        "ix_infrastructure_relationship_to_type",
        "ix_event_observed_id",
        "ix_assessment_event_score",
        "ix_assessment_asset_score",
    ):
        assert re.search(rf"CREATE INDEX IF NOT EXISTS {index_name}\b", migration)
