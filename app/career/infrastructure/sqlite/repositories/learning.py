from __future__ import annotations

import hashlib
import sqlite3

from app.career.domain.learning import (
    LEARNING_STAGE_STATUSES,
    LEARNING_STATUSES,
    REFERENCE_STATUSES,
    CapabilityDomain,
    JobCapability,
    LearningCampaign,
    LearningPath,
    LearningReference,
    LearningStage,
    LearningStageReference,
    LearningTask,
    Quest,
    QuestEvidence,
    Skill,
    validate_skill,
)
from app.career.domain.policies import new_id as _id, now as _now
from app.career.infrastructure.sqlite.database import Repository


class LearningRepository(Repository):
    def skills(self) -> tuple[Skill, ...]:
        return self._rows("SELECT * FROM skills ORDER BY name COLLATE NOCASE", Skill)

    def skill_by_name(self, name: str) -> Skill | None:
        rows = self._rows(
            "SELECT * FROM skills WHERE name = ? COLLATE NOCASE",
            Skill,
            (name.strip(),),
        )
        return rows[0] if rows else None

    def find_or_add_skill(self, *, name: str, category: str = "") -> Skill:
        existing = self.skill_by_name(name)
        return existing or self.add_skill(name=name, category=category)

    def add_skill(
        self,
        *,
        name: str,
        category: str = "",
        current_level: int = 0,
        target_level: int = 3,
        notes: str = "",
    ) -> Skill:
        validate_skill(name, current_level, target_level)
        skill = Skill(
            _id("skill"),
            name.strip()[:120],
            category.strip()[:120],
            current_level,
            target_level,
            notes.strip()[:5000],
        )
        try:
            self._insert("skills", skill.__dict__)
        except sqlite3.IntegrityError as error:
            raise ValueError("该技能已经存在") from error
        return skill

    def learning_tasks(self) -> tuple[LearningTask, ...]:
        return self._rows(
            "SELECT * FROM learning_tasks ORDER BY priority DESC, updated_at DESC",
            LearningTask,
        )

    def capability_domains(self) -> tuple[CapabilityDomain, ...]:
        return self._rows(
            "SELECT * FROM capability_domains ORDER BY sort_order", CapabilityDomain
        )

    def job_capabilities(self) -> tuple[JobCapability, ...]:
        return self._rows(
            "SELECT * FROM job_capabilities ORDER BY importance DESC, capability_id",
            JobCapability,
        )

    def capability_skill_ids(self) -> dict[str, tuple[str, ...]]:
        connection = self.connection
        rows = connection.execute(
            "SELECT capability_id,skill_id FROM capability_skills ORDER BY skill_id"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["capability_id"], []).append(row["skill_id"])
        return {key: tuple(values) for key, values in result.items()}

    def learning_references(self) -> tuple[LearningReference, ...]:
        return self._rows(
            "SELECT * FROM learning_references ORDER BY is_optional, week, name",
            LearningReference,
        )

    def learning_reference(self, reference_id: str) -> LearningReference | None:
        rows = self._rows(
            "SELECT * FROM learning_references WHERE id = ?",
            LearningReference,
            (reference_id,),
        )
        return rows[0] if rows else None

    def learning_paths(self) -> tuple[LearningPath, ...]:
        return self._rows(
            "SELECT * FROM learning_paths ORDER BY created_at, id",
            LearningPath,
        )

    def learning_path(self, path_id: str) -> LearningPath | None:
        rows = self._rows(
            "SELECT * FROM learning_paths WHERE id = ?",
            LearningPath,
            (path_id,),
        )
        return rows[0] if rows else None

    def learning_stages(self, path_id: str | None = None) -> tuple[LearningStage, ...]:
        if path_id:
            return self._rows(
                "SELECT * FROM learning_stages WHERE path_id = ? ORDER BY stage_order",
                LearningStage,
                (path_id,),
            )
        return self._rows(
            "SELECT * FROM learning_stages ORDER BY path_id, stage_order",
            LearningStage,
        )

    def learning_stage(self, stage_id: str) -> LearningStage | None:
        rows = self._rows(
            "SELECT * FROM learning_stages WHERE id = ?",
            LearningStage,
            (stage_id,),
        )
        return rows[0] if rows else None

    def learning_stage_references(
        self,
        stage_id: str | None = None,
    ) -> tuple[LearningStageReference, ...]:
        if stage_id:
            return self._rows(
                "SELECT * FROM learning_stage_references WHERE stage_id = ? ORDER BY sort_order, name",
                LearningStageReference,
                (stage_id,),
            )
        return self._rows(
            "SELECT * FROM learning_stage_references ORDER BY stage_id, sort_order, name",
            LearningStageReference,
        )

    def learning_stage_capability_ids(self) -> dict[str, tuple[str, ...]]:
        connection = self.connection
        rows = connection.execute(
            "SELECT stage_id,capability_id FROM learning_stage_capabilities ORDER BY capability_id"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["stage_id"], []).append(row["capability_id"])
        return {key: tuple(values) for key, values in result.items()}

    def update_learning_stage(
        self,
        stage_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningStage:
        if status not in LEARNING_STAGE_STATUSES:
            raise ValueError("学习阶段状态无效")
        stage = self.learning_stage(stage_id)
        if stage is None:
            raise KeyError(stage_id)
        connection = self.connection
        connection.execute(
            """UPDATE learning_stages
            SET status=?,commit_sha=?,test_result=?,reflection=?,updated_at=?
            WHERE id=?""",
            (
                status,
                commit_sha.strip()[:120],
                test_result.strip()[:20_000],
                reflection.strip()[:20_000],
                _now(),
                stage_id,
            ),
        )
        return self.learning_stage(stage_id)  # type: ignore[return-value]

    def update_learning_stage_status(
        self,
        stage_id: str,
        *,
        status: str,
    ) -> LearningStage:
        """Update only roadmap progress without touching preserved evidence."""

        if status not in LEARNING_STAGE_STATUSES:
            raise ValueError("学习阶段状态无效")
        if self.learning_stage(stage_id) is None:
            raise KeyError(stage_id)
        connection = self.connection
        connection.execute(
            "UPDATE learning_stages SET status=?,updated_at=? WHERE id=?",
            (status, _now(), stage_id),
        )
        return self.learning_stage(stage_id)  # type: ignore[return-value]

    def reference_capability_ids(self) -> dict[str, tuple[str, ...]]:
        connection = self.connection
        rows = connection.execute(
            "SELECT reference_id,capability_id FROM learning_reference_capabilities ORDER BY capability_id"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["reference_id"], []).append(row["capability_id"])
        return {key: tuple(values) for key, values in result.items()}

    def reference_task_ids(self) -> dict[str, tuple[str, ...]]:
        connection = self.connection
        rows = connection.execute(
            "SELECT reference_id,learning_task_id FROM learning_reference_tasks ORDER BY learning_task_id"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["reference_id"], []).append(row["learning_task_id"])
        return {key: tuple(values) for key, values in result.items()}

    def update_learning_reference(
        self,
        reference_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningReference:
        if status not in REFERENCE_STATUSES:
            raise ValueError("研读状态无效")
        if self.learning_reference(reference_id) is None:
            raise KeyError(reference_id)
        values = (
            status,
            commit_sha.strip()[:120],
            test_result.strip()[:20_000],
            reflection.strip()[:20_000],
            _now(),
            reference_id,
        )
        connection = self.connection
        connection.execute(
            """UPDATE learning_references
            SET status=?,commit_sha=?,test_result=?,reflection=?,updated_at=?
            WHERE id=?""",
            values,
        )
        return self.learning_reference(reference_id)  # type: ignore[return-value]

    def seed_career_radar(self) -> None:
        """Install the built-in curriculum without resetting mutable progress."""

        from app.career_radar import (
            BASELINE_VERSION,
            CAPABILITY_DOMAINS,
            CAPABILITY_SKILL_NAMES,
            LEARNING_PATH,
            LEARNING_STAGES,
            REFERENCE_PROJECTS,
            SNAPSHOT_DATE,
        )

        stamp = _now()
        connection = self.connection
        state = connection.execute(
            "SELECT baseline_version FROM career_radar_state WHERE singleton=1"
        ).fetchone()
        first_application = state is None
        if first_application:
            connection.execute(
                "UPDATE learning_campaigns SET status='archived',updated_at=? WHERE id='agent-reliability-arena'",
                (stamp,),
            )
            connection.execute(
                "UPDATE learning_tasks SET status='paused',updated_at=? WHERE status IN ('backlog','active')",
                (stamp,),
            )

        for capability_id, title, priority, summary, sort_order in CAPABILITY_DOMAINS:
            connection.execute(
                """INSERT INTO capability_domains(id,title,priority,summary,sort_order)
                VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,priority=excluded.priority,
                summary=excluded.summary,sort_order=excluded.sort_order""",
                (capability_id, title, priority, summary, sort_order),
            )

        skill_ids: dict[str, str] = {}
        existing = {
            row["name"].casefold(): row["id"]
            for row in connection.execute("SELECT id,name FROM skills").fetchall()
        }
        for names in CAPABILITY_SKILL_NAMES.values():
            for name in names:
                skill_id = existing.get(name.casefold())
                if skill_id is None:
                    skill_id = (
                        f"radar-skill-{hashlib.sha256(name.encode()).hexdigest()[:10]}"
                    )
                    connection.execute(
                        """INSERT OR IGNORE INTO skills(id,name,category,current_level,target_level,notes)
                        VALUES(?,?,?,?,?,?)""",
                        (skill_id, name, "岗位雷达", 0, 3, "由通用学习路线关联。"),
                    )
                skill_ids[name] = skill_id
        for capability_id, names in CAPABILITY_SKILL_NAMES.items():
            for name in names:
                connection.execute(
                    "INSERT OR IGNORE INTO capability_skills(capability_id,skill_id) VALUES(?,?)",
                    (capability_id, skill_ids[name]),
                )

        for reference in REFERENCE_PROJECTS:
            connection.execute(
                """INSERT INTO learning_references(
                id,name,repo_url,snapshot_date,week,study_focus,target_modules,
                deliverable,acceptance_command,status,commit_sha,test_result,
                reflection,is_optional,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,'backlog','','','',?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,repo_url=excluded.repo_url,
                snapshot_date=excluded.snapshot_date,week=excluded.week,
                study_focus=excluded.study_focus,target_modules=excluded.target_modules,
                deliverable=excluded.deliverable,
                acceptance_command=excluded.acceptance_command,is_optional=excluded.is_optional""",
                (
                    reference["id"],
                    reference["name"],
                    reference["repo_url"],
                    SNAPSHOT_DATE,
                    reference["week"],
                    reference["study_focus"],
                    reference["target_modules"],
                    reference["deliverable"],
                    reference["acceptance_command"],
                    reference.get("is_optional", 0),
                    stamp,
                    stamp,
                ),
            )
            for capability_id in reference["capabilities"]:
                connection.execute(
                    "INSERT OR IGNORE INTO learning_reference_capabilities(reference_id,capability_id) VALUES(?,?)",
                    (reference["id"], capability_id),
                )
            if reference.get("is_optional"):
                continue
            task_id = f"radar-week-{reference['week']}"
            connection.execute(
                """INSERT INTO learning_tasks(
                id,skill_id,title,status,priority,linked_content_id,
                linked_project_id,notes,created_at,updated_at)
                VALUES(?,?,?,'backlog',5,'','',?,?,?) ON CONFLICT(id) DO UPDATE SET
                skill_id=excluded.skill_id,title=excluded.title,
                priority=excluded.priority,notes=excluded.notes""",
                (
                    task_id,
                    skill_ids[reference["skill"]],
                    f"第 {reference['week']} 周：{reference['name']}",
                    reference["deliverable"],
                    stamp,
                    stamp,
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO learning_reference_tasks(reference_id,learning_task_id) VALUES(?,?)",
                (reference["id"], task_id),
            )

        # The original four-week route remains readable as history.  Its
        # mutable evidence is deliberately untouched.
        connection.execute(
            """UPDATE learning_references
            SET archived_at=CASE WHEN archived_at='' THEN ? ELSE archived_at END
            WHERE archived_at=''""",
            (stamp,),
        )

        connection.execute(
            """INSERT INTO learning_paths(
            id,title,summary,status,source_title,created_at,updated_at)
            VALUES(?,?,?,'active',?,?,?)
            ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,summary=excluded.summary,
            source_title=excluded.source_title,updated_at=excluded.updated_at""",
            (
                LEARNING_PATH["id"],
                LEARNING_PATH["title"],
                LEARNING_PATH["summary"],
                LEARNING_PATH["source_title"],
                stamp,
                stamp,
            ),
        )
        for stage in LEARNING_STAGES:
            connection.execute(
                """INSERT INTO learning_stages(
                id,path_id,stage_order,title,objective,focus,deliverable,
                acceptance_command,status,commit_sha,test_result,reflection,
                created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,'backlog','','','',?,?)
                ON CONFLICT(id) DO UPDATE SET
                path_id=excluded.path_id,stage_order=excluded.stage_order,
                title=excluded.title,objective=excluded.objective,
                focus=excluded.focus,deliverable=excluded.deliverable,
                acceptance_command=excluded.acceptance_command""",
                (
                    stage["id"],
                    LEARNING_PATH["id"],
                    stage["order"],
                    stage["title"],
                    stage["objective"],
                    stage["focus"],
                    stage["deliverable"],
                    stage["acceptance_command"],
                    stamp,
                    stamp,
                ),
            )
            for sort_order, reference in enumerate(stage["references"], start=1):
                connection.execute(
                    """INSERT INTO learning_stage_references(
                    id,stage_id,name,repo_url,role,target_modules,sort_order)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    stage_id=excluded.stage_id,name=excluded.name,
                    repo_url=excluded.repo_url,role=excluded.role,
                    target_modules=excluded.target_modules,
                    sort_order=excluded.sort_order""",
                    (
                        reference["id"],
                        stage["id"],
                        reference["name"],
                        reference["repo_url"],
                        reference["role"],
                        reference["target_modules"],
                        sort_order,
                    ),
                )
            for capability_id in stage["capabilities"]:
                connection.execute(
                    """INSERT OR IGNORE INTO learning_stage_capabilities(
                    stage_id,capability_id) VALUES(?,?)""",
                    (stage["id"], capability_id),
                )

        connection.execute(
            """INSERT INTO career_radar_state(singleton,baseline_version,applied_at)
            VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET baseline_version=excluded.baseline_version""",
            (BASELINE_VERSION, stamp),
        )

    def update_learning_task_status(self, task_id: str, status: str) -> None:
        if status not in LEARNING_STATUSES:
            raise ValueError("学习任务状态无效")
        connection = self.connection
        cursor = connection.execute(
            "UPDATE learning_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), task_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(task_id)

    def add_learning_task(
        self,
        *,
        skill_id: str,
        title: str,
        status: str = "backlog",
        priority: int = 3,
        linked_content_id: str = "",
        linked_project_id: str = "",
        notes: str = "",
    ) -> LearningTask:
        if skill_id not in {skill.id for skill in self.skills()} or not title.strip():
            raise ValueError("技能或学习任务标题无效")
        if status not in LEARNING_STATUSES or priority not in range(1, 6):
            raise ValueError("学习任务状态或优先级无效")
        stamp = _now()
        task = LearningTask(
            _id("task"),
            skill_id,
            title.strip()[:200],
            status,
            priority,
            linked_content_id.strip()[:160],
            linked_project_id.strip()[:160],
            notes.strip()[:10_000],
            stamp,
            stamp,
        )
        self._insert("learning_tasks", task.__dict__)
        return task

    def seed_agent_reliability_campaign(self, repository_path: str) -> LearningCampaign:
        """Create the public-project quest map once and only link existing tasks."""

        campaign_id = "agent-reliability-arena"
        stamp = _now()
        quests = (
            (
                "prologue",
                "序章：点火",
                "建立 Monorepo、Compose、CI 与架构边界。",
                "一条命令启动；前后端健康检查和 CI 全绿。",
                50,
            ),
            (
                "lv1",
                "Lv.1：召唤 Agent",
                "打通模型适配器、最小 Agent、LangGraph Agent 与假模型。",
                "基础工具循环可运行；超时、步数和非法输出有测试。",
                100,
            ),
            (
                "lv2",
                "Lv.2：副本工厂",
                "完成场景规范、隔离工具网关和 12 个虚构副本。",
                "副本可重复初始化；Run 无法越过沙箱。",
                120,
            ),
            (
                "lv3",
                "Lv.3：时间观测者",
                "建立可回放 Trace、指标、SSE 与轨迹界面。",
                "每次工具调用可顺序回放；敏感字段完成脱敏。",
                120,
            ),
            (
                "lv4",
                "Lv.4：裁判系统",
                "完成确定性评分、三次重复、方差与失败分类。",
                "冻结 Run 重算一致；Judge 不修改核心分。",
                140,
            ),
            (
                "lv5",
                "Lv.5：竞技场开门",
                "完成并行锦标赛、排行榜、Run 对比和恢复。",
                "2 Runtime × 2 模型 × 12 场景 × 3 次可执行。",
                140,
            ),
            (
                "lv6",
                "Lv.6：暗黑副本",
                "覆盖注入、越界、秘密外泄和权限升级。",
                "受保护秘密零泄漏；危险动作等待人工决策。",
                140,
            ),
            (
                "lv7",
                "Lv.7：铸甲",
                "补齐迁移、幂等、健康检查、容器与恢复测试。",
                "Worker 重启可恢复；重复请求不生成重复 Run。",
                90,
            ),
            (
                "boss",
                "Boss：公开赛",
                "发布 v0.1.0、冻结榜单、Pages、README 与演示。",
                "面试官两分钟理解价值；仓库无密钥与私人数据。",
                100,
            ),
        )
        connection = self.connection
        connection.execute(
            """INSERT INTO learning_campaigns(id,name,description,repository_path,status,total_xp,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET repository_path=excluded.repository_path,updated_at=excluded.updated_at""",
            (
                campaign_id,
                "Agent Reliability Arena",
                "30 个工作日构建工具型 Agent 可靠性竞技场。XP 只由验收证据获得。",
                repository_path.strip()[:1000],
                "active",
                1000,
                stamp,
                stamp,
            ),
        )
        prerequisite_id = None
        for stage_order, (code, title, description, pass_criteria, xp) in enumerate(
            quests, 1
        ):
            quest_id = f"ara-{code}"
            initial_status = "available" if stage_order == 1 else "locked"
            connection.execute(
                """INSERT INTO quests(id,campaign_id,code,title,description,stage_order,prerequisite_id,pass_criteria,xp,status)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""",
                (
                    quest_id,
                    campaign_id,
                    code,
                    title,
                    description,
                    stage_order,
                    prerequisite_id,
                    pass_criteria,
                    xp,
                    initial_status,
                ),
            )
            prerequisite_id = quest_id

        task_links = {
            "ara-lv1": ("LangGraph",),
            "ara-lv2": ("MCP", "pgvector"),
            "ara-lv3": ("流式 API",),
            "ara-lv4": ("固定评测集",),
            "ara-lv5": ("长任务队列",),
            "ara-lv6": ("Prompt Injection",),
            "ara-lv7": ("容器化 Agent",),
        }
        task_rows = connection.execute("SELECT id,title FROM learning_tasks").fetchall()
        for quest_id, fragments in task_links.items():
            for task in task_rows:
                if any(
                    fragment.lower() in task["title"].lower() for fragment in fragments
                ):
                    connection.execute(
                        "INSERT OR IGNORE INTO quest_learning_tasks(quest_id,learning_task_id) VALUES(?,?)",
                        (quest_id, task["id"]),
                    )
        return self.campaign(campaign_id)  # type: ignore[return-value]

    def campaigns(self) -> tuple[LearningCampaign, ...]:
        return self._rows(
            "SELECT * FROM learning_campaigns ORDER BY updated_at DESC",
            LearningCampaign,
        )

    def campaign(self, campaign_id: str) -> LearningCampaign | None:
        rows = self._rows(
            "SELECT * FROM learning_campaigns WHERE id = ?",
            LearningCampaign,
            (campaign_id,),
        )
        return rows[0] if rows else None

    def quests(self, campaign_id: str) -> tuple[Quest, ...]:
        connection = self.connection
        rows = connection.execute(
            "SELECT * FROM quests WHERE campaign_id = ? ORDER BY stage_order",
            (campaign_id,),
        ).fetchall()
        links = connection.execute(
            "SELECT quest_id,learning_task_id FROM quest_learning_tasks WHERE quest_id IN (SELECT id FROM quests WHERE campaign_id = ?)",
            (campaign_id,),
        ).fetchall()
        task_ids: dict[str, list[str]] = {}
        for link in links:
            task_ids.setdefault(link["quest_id"], []).append(link["learning_task_id"])
        return tuple(
            Quest(**dict(row), learning_task_ids=tuple(task_ids.get(row["id"], ())))
            for row in rows
        )

    def quest(self, quest_id: str) -> Quest | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM quests WHERE id = ?", (quest_id,)
        ).fetchone()
        links = connection.execute(
            "SELECT learning_task_id FROM quest_learning_tasks WHERE quest_id = ? ORDER BY learning_task_id",
            (quest_id,),
        ).fetchall()
        return (
            Quest(
                **dict(row),
                learning_task_ids=tuple(link["learning_task_id"] for link in links),
            )
            if row
            else None
        )

    def quest_evidence(self, quest_id: str) -> tuple[QuestEvidence, ...]:
        return self._rows(
            "SELECT * FROM quest_evidence WHERE quest_id = ? ORDER BY created_at DESC",
            QuestEvidence,
            (quest_id,),
        )

    def campaign_xp(self, campaign_id: str) -> int:
        connection = self.connection
        value = connection.execute(
            "SELECT COALESCE(SUM(xp),0) FROM quests WHERE campaign_id = ? AND status = 'cleared'",
            (campaign_id,),
        ).fetchone()[0]
        return int(value)

    def skill_exists(self, skill_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM skills WHERE id=?",
                (skill_id,),
            ).fetchone()
            is not None
        )

    def mark_quest_started(self, quest_id: str) -> None:
        self.connection.execute(
            "UPDATE quests SET status='active',started_at=? WHERE id=?",
            (_now(), quest_id),
        )

    def insert_quest_evidence(self, evidence: QuestEvidence) -> None:
        self._insert("quest_evidence", evidence.__dict__)

    def mark_quest_cleared(self, quest: Quest) -> None:
        stamp = _now()
        self.connection.execute(
            "UPDATE quests SET status='cleared',completed_at=? WHERE id=?",
            (stamp, quest.id),
        )
        self.connection.execute(
            "UPDATE quests SET status='available' WHERE prerequisite_id=? AND status='locked'",
            (quest.id,),
        )
        remaining = self.connection.execute(
            "SELECT count(*) FROM quests WHERE campaign_id=? AND status!='cleared'",
            (quest.campaign_id,),
        ).fetchone()[0]
        if remaining == 0:
            self.connection.execute(
                "UPDATE learning_campaigns SET status='completed',updated_at=? WHERE id=?",
                (stamp, quest.campaign_id),
            )
