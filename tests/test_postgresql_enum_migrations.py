import ast
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql.named_types import DropEnumType

MIGRATION_ENUMS = {
    "20260723_0001_initial_schema.py": {
        "risktolerance",
        "journalstatus",
    },
    "20260723_0002_portfolio_engine.py": {
        "transactiontype",
    },
    "20260723_0003_decision_engine.py": {
        "decisionstatus",
        "evidencesourcetype",
        "revisionevent",
    },
    "20260724_0004_macro_data_engine.py": {
        "seriescategory",
        "datafrequency",
        "seasonaladjustment",
        "observationstatus",
        "importstatus",
        "qualityissuetype",
        "qualityissuestatus",
    },
}


def _created_enum_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "sa"
            and function.attr == "Enum"
        ):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "name"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                names.add(keyword.value.value)
    return names


def test_every_native_enum_is_cleaned_up_by_its_owning_migration() -> None:
    versions = Path("migrations/versions")
    discovered: set[str] = set()
    for filename, expected in MIGRATION_ENUMS.items():
        source = (versions / filename).read_text(encoding="utf-8")
        created = _created_enum_names(source)
        assert created == expected
        discovered.update(created)

        downgrade = source[source.index("def downgrade()") :]
        assert 'bind.dialect.name != "postgresql"' in source
        assert "checkfirst=True" in source
        assert downgrade.rfind("_drop_owned_postgresql_enums(") > downgrade.rfind("op.drop_table(")
        for enum_name in expected:
            assert f'"{enum_name}"' in downgrade

    assert len(discovered) == 13


def test_quality_status_is_reused_not_owned_by_v0006() -> None:
    source = Path("migrations/versions/20260724_0006_data_contracts.py").read_text(encoding="utf-8")
    assert 'name="qualityissuestatus", create_type=False' in source
    assert "_drop_owned_postgresql_enums" not in source
    assert source.index('op.drop_table("data_quality_issue_events")') < source.index(
        "_alter_timestamps(timezone=False)"
    )


def test_all_owned_enum_drop_statements_compile_for_postgresql() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    for names in MIGRATION_ENUMS.values():
        for name in names:
            ddl = str(DropEnumType(ENUM(name=name)).compile(dialect=dialect))
            assert ddl == f"DROP TYPE {name}"
