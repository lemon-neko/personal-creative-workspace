import re
import sqlite3
from contextlib import closing

from app.main import create_app
from app.mobile_main import create_mobile_app
from app.workflow_store import WorkflowStore
from tools.architecture_audit import ROOT


def test_documented_sqlite_owners_cover_the_fresh_schema(tmp_path):
    create_app(data_root=tmp_path, enable_scheduler=False)
    create_mobile_app(data_root=tmp_path)
    WorkflowStore(tmp_path)  # Optional workflow subsystem.

    document = (ROOT / "docs/architecture/data-ownership.md").read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| `(workspace\.db|mobile\.db)` \| `(\w+)` \| (\d+|—) \| [^|]+ \| ([^|]+) \|$",
        document,
        re.MULTILINE,
    )
    for filename, registry in (("workspace.db", "schema_migrations"), ("mobile.db", "mobile_schema_migrations")):
        names = []
        versions = {}
        for database, owner, version, tables in rows:
            if database != filename:
                continue
            names.extend(re.findall(r"`(\w+)`", tables))
            if version != "—":
                assert owner not in versions
                versions[owner] = int(version)
        assert len(names) == len(set(names)), f"Multiple owners in {filename}"
        with closing(sqlite3.connect(tmp_path / filename)) as connection:
            actual = connection.execute(
                "SELECT name FROM pragma_table_list WHERE schema='main' "
                "AND type IN ('table','virtual') AND name NOT LIKE 'sqlite_%'"
            )
            assert set(names) == {name for (name,) in actual}
            assert versions == dict(connection.execute(f"SELECT subsystem,version FROM {registry}"))
