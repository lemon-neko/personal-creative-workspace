from __future__ import annotations

from app.career.domain.profile import CareerProfile, normalize_profile_fields
from app.career.domain.policies import now as _now
from app.career.infrastructure.sqlite.database import Repository


class ProfileRepository(Repository):
    def profile(self) -> CareerProfile:
        connection = self.connection
        row = connection.execute("SELECT * FROM profile WHERE singleton = 1").fetchone()
        if row is None:
            return CareerProfile()
        data = dict(row)
        data.pop("singleton", None)
        return CareerProfile(**data)

    def save_profile(self, **fields: str) -> CareerProfile:
        cleaned = normalize_profile_fields(fields)
        cleaned["updated_at"] = _now()
        connection = self.connection
        connection.execute(
            """INSERT INTO profile(singleton,target_roles,contact,education,experience,certifications,skills,facts,updated_at)
            VALUES(1,:target_roles,:contact,:education,:experience,:certifications,:skills,:facts,:updated_at)
            ON CONFLICT(singleton) DO UPDATE SET target_roles=excluded.target_roles, contact=excluded.contact,
            education=excluded.education, experience=excluded.experience, certifications=excluded.certifications,
            skills=excluded.skills, facts=excluded.facts, updated_at=excluded.updated_at""",
            cleaned,
        )
        return self.profile()
