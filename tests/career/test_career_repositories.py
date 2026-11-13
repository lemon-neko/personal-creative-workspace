import ast
from pathlib import Path

from app.career import SCHEMA_VERSION, CareerRepository
from app.main import create_app


def test_container_and_facade_expose_the_same_services_and_reopen_existing_records(
    tmp_path,
):
    app = create_app(content_root=tmp_path, enable_scheduler=False)
    career = app.state.container.career
    assert career is app.state.career
    with career.unit_of_work(write=True) as stores:
        profile = stores.profile.save_profile(facts="synthetic evidence")
        job = stores.jobs.add_job(
            company="Example", title="Engineer", status="interviewing"
        )
    reopened = CareerRepository(tmp_path)
    assert reopened.profile() == profile
    assert reopened.job(job.id) == job
    assert reopened.job_events(job.id)[0].status == "interviewing"
    with career.unit_of_work() as stores:
        assert (
            stores.jobs.connection.execute(
                "SELECT version FROM schema_migrations WHERE subsystem='career'"
            ).fetchone()[0]
            == SCHEMA_VERSION
            == 8
        )


def test_domain_and_application_import_directions():
    root = Path(__file__).resolve().parents[2] / "app" / "career"
    for layer, forbidden in {
        "infrastructure/sqlite/repositories": (
            "app.career.infrastructure.sqlite.repositories",
            "fastapi",
        ),
        "domain": (
            "fastapi",
            "sqlite3",
            "app.database",
            "app.career.infrastructure",
            "app.career.application",
        ),
        "application": (
            "fastapi",
            "sqlite3",
            "app.database",
            "app.career.infrastructure",
        ),
    }.items():
        for path in (root / layer).glob("*.py"):
            imports = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            assert not any(
                module == prefix or module.startswith(prefix + ".")
                for module in imports
                for prefix in forbidden
            ), path.name
