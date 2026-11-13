from __future__ import annotations

from app.career.domain.profile import PROJECT_STATUSES, CareerProject
from app.career.domain.policies import new_id as _id, now as _now
from app.career.infrastructure.sqlite.database import Repository


class ProjectRepository(Repository):
    def projects(self) -> tuple[CareerProject, ...]:
        return self._rows(
            "SELECT * FROM projects ORDER BY updated_at DESC", CareerProject
        )

    def project(self, project_id: str) -> CareerProject | None:
        rows = self._rows(
            "SELECT * FROM projects WHERE id = ?", CareerProject, (project_id,)
        )
        return rows[0] if rows else None

    def add_project(self, **fields: str) -> CareerProject:
        name = str(fields.get("name", "")).strip()
        status = str(fields.get("status", "draft"))
        if not name:
            raise ValueError("项目名称不能为空")
        if status not in PROJECT_STATUSES:
            raise ValueError("项目状态无效")
        stamp = _now()
        project = CareerProject(
            id=_id("project"),
            name=name[:160],
            role=str(fields.get("role", "")).strip()[:160],
            timeframe=str(fields.get("timeframe", "")).strip()[:160],
            summary=str(fields.get("summary", "")).strip()[:10_000],
            technologies=str(fields.get("technologies", "")).strip()[:2000],
            challenge=str(fields.get("challenge", "")).strip()[:10_000],
            actions=str(fields.get("actions", "")).strip()[:10_000],
            outcome=str(fields.get("outcome", "")).strip()[:10_000],
            evidence=str(fields.get("evidence", "")).strip()[:10_000],
            status=status,
            created_at=stamp,
            updated_at=stamp,
        )
        self._insert("projects", project.__dict__)
        return project

    def update_project(self, project_id: str, **fields: str) -> CareerProject:
        current = self.project(project_id)
        if current is None:
            raise KeyError(project_id)
        status = str(fields.get("status", current.status))
        name = str(fields.get("name", current.name)).strip()
        if status not in PROJECT_STATUSES or not name:
            raise ValueError("项目名称或状态无效")
        values = {
            "id": project_id,
            "name": name[:160],
            "role": str(fields.get("role", current.role)).strip()[:160],
            "timeframe": str(fields.get("timeframe", current.timeframe)).strip()[:160],
            "summary": str(fields.get("summary", current.summary)).strip()[:10_000],
            "technologies": str(
                fields.get("technologies", current.technologies)
            ).strip()[:2000],
            "challenge": str(fields.get("challenge", current.challenge)).strip()[
                :10_000
            ],
            "actions": str(fields.get("actions", current.actions)).strip()[:10_000],
            "outcome": str(fields.get("outcome", current.outcome)).strip()[:10_000],
            "evidence": str(fields.get("evidence", current.evidence)).strip()[:10_000],
            "status": status,
            "updated_at": _now(),
        }
        assignments = ",".join(f"{key}=:{key}" for key in values if key != "id")
        connection = self.connection
        connection.execute(f"UPDATE projects SET {assignments} WHERE id=:id", values)
        return self.project(project_id)  # type: ignore[return-value]
