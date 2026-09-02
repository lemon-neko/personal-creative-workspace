from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.income import IncomeRepository
from app.main import create_app


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_four_sources_are_fixed_ordered_and_idempotent(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    again = IncomeRepository(tmp_path)

    assert [item.key for item in repository.sources()] == [
        "digital_product",
        "intelligence_subscription",
        "micro_saas",
        "ads_cps",
    ]
    assert len(again.sources()) == 4
    with pytest.raises(ValueError, match="无效"):
        repository.add_entry(
            source_key="freelancing",
            entry_type="revenue",
            gross_fen=10_000,
        )


def test_source_editing_accepts_only_known_status_and_safe_https(
    tmp_path: Path,
) -> None:
    repository = IncomeRepository(tmp_path)
    source = repository.update_source(
        "digital_product",
        status="preparing",
        current_product="Agent 评测模板",
        price_note="¥29",
        sales_url="https://example.test/products/agent-eval",
        next_action="完成最小可交付版本",
    )

    assert source.status == "preparing"
    assert source.current_product == "Agent 评测模板"
    assert source.next_action == "完成最小可交付版本"
    with pytest.raises(ValueError, match="HTTPS"):
        repository.update_source(
            "digital_product",
            status="selling",
            current_product="模板",
            price_note="¥29",
            sales_url="http://example.test/product",
            next_action="售卖",
        )
    with pytest.raises(ValueError, match="状态"):
        repository.update_source(
            "digital_product",
            status="unknown",
            current_product="",
            price_note="",
            sales_url="",
            next_action="",
        )


def test_income_metrics_use_confirmed_cash_only(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    today = datetime.now(SHANGHAI).date().isoformat()
    confirmed = repository.add_entry(
        source_key="digital_product",
        entry_type="revenue",
        gross_fen=19_900,
        platform_fee_fen=1_900,
        occurred_at=today,
    )
    pending = repository.add_entry(
        source_key="micro_saas",
        entry_type="revenue",
        gross_fen=9_900,
        platform_fee_fen=900,
        occurred_at=today,
    )
    expense = repository.add_entry(
        source_key="digital_product",
        entry_type="expense",
        gross_fen=2_000,
        occurred_at=today,
    )
    refund = repository.add_entry(
        source_key="digital_product",
        entry_type="refund",
        gross_fen=3_000,
        occurred_at=today,
    )
    voided = repository.add_entry(
        source_key="ads_cps",
        entry_type="revenue",
        gross_fen=50_000,
        occurred_at=today,
    )

    repository.confirm_entry(confirmed.id)
    repository.confirm_entry(expense.id)
    repository.confirm_entry(refund.id)
    repository.void_entry(voided.id)
    metrics = repository.metrics()

    assert metrics.earned_fen == 18_000
    assert metrics.month_earned_fen == 18_000
    assert metrics.pending_fen == 9_000
    assert metrics.deductions_fen == 6_900
    assert metrics.net_cash_fen == 13_000
    assert repository.entry(pending.id).cash_status == "pending"  # type: ignore[union-attr]
    summaries = repository.source_summaries()
    assert summaries[0].earned_fen == 18_000
    assert summaries[0].order_count == 1
    assert summaries[2].pending_fen == 9_000
    assert all(point["month"] for point in repository.monthly_trend())


def test_entries_validate_fees_dates_and_state_transitions(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    with pytest.raises(ValueError, match="只有收入"):
        repository.add_entry(
            source_key="digital_product",
            entry_type="expense",
            gross_fen=1_000,
            platform_fee_fen=100,
        )
    with pytest.raises(ValueError, match="日期"):
        repository.add_entry(
            source_key="digital_product",
            entry_type="revenue",
            gross_fen=1_000,
            occurred_at="not-a-date",
        )
    item = repository.add_entry(
        source_key="digital_product",
        entry_type="revenue",
        gross_fen=1_000,
    )
    repository.confirm_entry(item.id)
    with pytest.raises(ValueError, match="待确认"):
        repository.confirm_entry(item.id)
    with pytest.raises(ValueError, match="已确认错误"):
        repository.void_entry(item.id)


def _legacy_database(root: Path, *, use_view: bool = False) -> Path:
    database = root / "workspace.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """CREATE TABLE schema_migrations (
                subsystem TEXT PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations VALUES('bounty_income',2,'2026-08-24T00:00:00+08:00');
            CREATE TABLE bounty_opportunities(id TEXT PRIMARY KEY);
            CREATE TABLE business_experiments(id TEXT PRIMARY KEY);
            """
        )
        if use_view:
            connection.execute("CREATE VIEW business_signals AS SELECT 1 AS id")
        else:
            connection.execute("CREATE TABLE business_signals(id TEXT PRIMARY KEY)")
    return database


def test_income_migration_snapshots_and_removes_legacy_tables(tmp_path: Path) -> None:
    database = _legacy_database(tmp_path)
    repository = IncomeRepository(tmp_path)

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE subsystem='bounty_income'"
        ).fetchone()[0]
        income_version = connection.execute(
            "SELECT version FROM schema_migrations WHERE subsystem='income'"
        ).fetchone()[0]
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert version == 3
    assert income_version == 3
    assert "bounty_opportunities" not in names
    assert "business_experiments" not in names
    assert "business_signals" not in names
    assert {
        "income_sources",
        "income_entries",
        "money_engine_products",
        "product_metric_snapshots",
        "revenue_validations",
        "revenue_role_cards",
        "money_profiles",
        "money_opportunities",
        "money_evidence",
        "money_retros",
    } <= names
    assert len(repository.sources()) == 4
    assert list((tmp_path / "working" / "db-migrations").glob("*.db"))


def test_failed_legacy_cleanup_rolls_back_and_keeps_snapshot(tmp_path: Path) -> None:
    database = _legacy_database(tmp_path, use_view=True)

    with pytest.raises(sqlite3.OperationalError):
        IncomeRepository(tmp_path)

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE subsystem='bounty_income'"
        ).fetchone()[0]
        signal_view = connection.execute(
            "SELECT type FROM sqlite_master WHERE name='business_signals'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='bounty_opportunities'"
        ).fetchone()
    assert version == 2
    assert signal_view == "view"
    assert list((tmp_path / "working" / "db-migrations").glob("*.db"))


def test_income_pages_and_manual_forms(tmp_path: Path) -> None:
    application = create_app(content_root=tmp_path, enable_scheduler=False)
    client = TestClient(application)

    dashboard = client.get("/income")
    assert dashboard.status_code == 200
    assert "收入面板" in dashboard.text
    assert "MONEY ENGINE V1" in dashboard.text
    assert "羽白 Agent 应用可靠性上线包" in dashboard.text
    assert dashboard.text.index("数字产品") < dashboard.text.index("情报订阅")
    assert "¥0.00" in dashboard.text
    assert client.get("/income/entries").status_code == 200

    update = client.post(
        "/income/sources/digital_product",
        data={
            "status": "preparing",
            "current_product": "最小模板包",
            "price_note": "¥19",
            "sales_url": "https://example.test/product",
            "next_action": "完成交付说明",
        },
        follow_redirects=False,
    )
    assert update.status_code == 303
    created = client.post(
        "/income/entries",
        data={
            "source_key": "digital_product",
            "entry_type": "revenue",
            "gross": "19.90",
            "platform_fee": "0.90",
            "occurred_at": "2026-08-24",
            "note": "虚构测试订单",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    item = application.state.income.entries()[0]
    confirmed = client.post(
        f"/income/entries/{item.id}/confirm", follow_redirects=False
    )
    assert confirmed.status_code == 303
    assert application.state.income.metrics().earned_fen == 1_900
    assert "完成交付说明" in client.get("/income").text


def test_money_engine_product_is_fixed_and_urls_are_restricted(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    product = repository.active_product()

    assert product.id == "agent-reliability-launch-kit"
    assert product.price_fen == 990
    assert product.source_key == "digital_product"
    assert len(repository.product_roles(product.id)) == 5
    assert {role.source_key for role in repository.product_roles(product.id)} == {
        "digital_product"
    }
    updated = repository.update_product(
        product.id,
        package_version="1.0.1",
        current_stage="store_setup",
        github_url="https://github.com/example/agent-reliability-launch-kit",
        article_url="https://mp.weixin.qq.com/s/example",
        store_url="https://mbd.pub/o/example",
        next_action="校验自动交付",
    )
    assert updated.package_version == "1.0.1"
    assert updated.store_url.startswith("https://mbd.pub/")
    with pytest.raises(ValueError, match="全部首单条件"):
        repository.update_product(
            product.id,
            package_version="1.0.1",
            current_stage="cleared",
            github_url="",
            article_url="",
            store_url="",
            next_action="",
        )
    with pytest.raises(ValueError, match="仓库名"):
        repository.update_product(
            product.id,
            package_version="1.0.1",
            current_stage="store_setup",
            github_url="https://github.com/example/wrong-name",
            article_url="",
            store_url="",
            next_action="",
        )
    with pytest.raises(ValueError, match="面包多"):
        repository.update_product(
            product.id,
            package_version="1.0.1",
            current_stage="store_setup",
            github_url="",
            article_url="",
            store_url="https://evil.example/product",
            next_action="",
        )


def test_money_engine_metrics_roles_and_first_yuan_gate(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    product = repository.active_product()
    metric = repository.add_metric_snapshot(
        product.id,
        observed_at="2026-08-25",
        impressions=100,
        store_clicks=8,
        paid_orders=1,
        delivered_orders=1,
        refunds=0,
    )
    assert repository.latest_metric(product.id) == metric
    with pytest.raises(ValueError, match="自动交付"):
        repository.add_metric_snapshot(
            product.id,
            observed_at="2026-08-25",
            impressions=0,
            store_clicks=0,
            paid_orders=0,
            delivered_orders=1,
            refunds=0,
        )
    role = repository.update_role(
        product.id,
        "product",
        status="active",
        observable_result="ZIP 已生成",
        next_action="执行清单校验",
        requires_confirmation=True,
    )
    assert role.status == "active"
    assert role.observable_result == "ZIP 已生成"

    entry = repository.add_entry(
        source_key="digital_product",
        entry_type="revenue",
        gross_fen=990,
        platform_fee_fen=100,
    )
    pending = repository.record_validation(
        product.id,
        income_entry_id=entry.id,
        unfamiliar_buyer=True,
        no_direct_sales=True,
        third_party_payment=True,
        automatic_delivery=True,
        refund_window_ended=True,
        no_refund=True,
    )
    assert not pending.cleared
    repository.confirm_entry(entry.id)
    too_small = repository.record_validation(
        product.id,
        income_entry_id=entry.id,
        unfamiliar_buyer=True,
        no_direct_sales=True,
        third_party_payment=True,
        automatic_delivery=True,
        refund_window_ended=True,
        no_refund=True,
    )
    assert too_small.cleared
    assert repository.first_yuan_cleared(product.id)


@pytest.mark.parametrize(
    "missing",
    [
        "unfamiliar_buyer",
        "no_direct_sales",
        "third_party_payment",
        "automatic_delivery",
        "refund_window_ended",
        "no_refund",
    ],
)
def test_first_yuan_requires_every_check(tmp_path: Path, missing: str) -> None:
    repository = IncomeRepository(tmp_path)
    product = repository.active_product()
    entry = repository.add_entry(
        source_key="digital_product",
        entry_type="revenue",
        gross_fen=990,
    )
    repository.confirm_entry(entry.id)
    checks = {
        "unfamiliar_buyer": True,
        "no_direct_sales": True,
        "third_party_payment": True,
        "automatic_delivery": True,
        "refund_window_ended": True,
        "no_refund": True,
    }
    checks[missing] = False
    validation = repository.record_validation(
        product.id, income_entry_id=entry.id, **checks
    )
    assert not validation.cleared
    assert not repository.first_yuan_cleared(product.id)


def test_money_engine_product_routes(tmp_path: Path) -> None:
    application = create_app(content_root=tmp_path, enable_scheduler=False)
    client = TestClient(application)
    product = application.state.income.active_product()

    page = client.get(f"/income/products/{product.id}")
    assert page.status_code == 200
    assert "完整包清单" in page.text
    assert "五张收入职责卡" in page.text
    assert "第一笔 ¥1 验证" in page.text
    updated = client.post(
        f"/income/products/{product.id}",
        data={
            "package_version": "1.0.1",
            "current_stage": "store_setup",
            "github_url": "https://github.com/example/agent-reliability-launch-kit",
            "article_url": "https://mp.weixin.qq.com/s/example",
            "store_url": "https://mbd.pub/o/example",
            "next_action": "测试交付",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    metric = client.post(
        f"/income/products/{product.id}/metrics",
        data={
            "observed_at": "2026-08-25",
            "impressions": "12",
            "store_clicks": "3",
            "paid_orders": "1",
            "delivered_orders": "1",
            "refunds": "0",
        },
        follow_redirects=False,
    )
    assert metric.status_code == 303
    role = client.post(
        f"/income/products/{product.id}/roles/product",
        data={
            "status": "active",
            "observable_result": "已有草稿",
            "next_action": "完成 ZIP",
            "requires_confirmation": "true",
        },
        follow_redirects=False,
    )
    assert role.status_code == 303
    assert client.get("/income/products/missing").status_code == 404


def test_money_skill_profile_and_verified_opportunity_loop(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    profile = repository.money_profile()
    assert profile.tier == "T2"
    updated = repository.update_money_profile(
        tier="T2",
        tier_reason="可以独立实现和交付小工具",
        skills="Python、FastAPI",
        weekly_hours=8,
        startup_capital_fen=0,
        region="中国",
        languages="中文",
        can_show_face="no",
        goal="验证第一笔真实收入",
        willing_to_learn=True,
    )
    assert updated.weekly_hours == 8
    opportunity = repository.create_opportunity(
        name="测试报告模板",
        source_key="digital_product",
        category="digital_product",
        target_customer="需要交付测试报告的独立开发者",
        for_tier="T2",
        money_flow="开发者为节省报告整理时间付费",
        signal_summary="先记录假设，不把赚钱教程当证据",
    )
    assert not repository.verification(opportunity.id).ready
    with pytest.raises(ValueError, match="公开 HTTPS"):
        repository.add_evidence(
            opportunity.id,
            source_url="http://localhost/demand",
            source_title="无效来源",
            source_kind="demand",
            published_at="2026-08-20",
            checked_at="2026-08-31",
            note="",
        )
    repository.add_evidence(
        opportunity.id,
        source_url="https://example.com/issues/123",
        source_title="用户公开提出报告自动化需求",
        source_kind="demand",
        published_at="2026-08-20",
        checked_at="2026-08-31",
        note="明确描述手工整理耗时",
    )
    repository.add_evidence(
        opportunity.id,
        source_url="https://example.org/jobs/456",
        source_title="岗位要求自动生成测试报告",
        source_kind="recruiting",
        published_at="2026-07-01",
        checked_at="2026-08-31",
        note="第二个独立来源",
    )
    verified = repository.update_opportunity_verification(
        opportunity.id,
        status="verifying",
        verdict="viable",
        hard_flags=(),
        suspect_flags=("B1",),
        money_flow=opportunity.money_flow,
        signal_summary="需求与招聘两个独立信号",
        freshness_note="两条证据均在一年内",
        cross_check="用户痛点与岗位采购能力相互印证",
    )
    assert verified.verdict == "viable"
    assert repository.verification(opportunity.id).ready
    planned = repository.update_opportunity_plan(
        opportunity.id,
        validation_step="发布一个精简样例并观察真实商品点击",
        two_week_plan="第一周完成样例，第二周发布",
        income_expectation="首轮可能为 0，目标是获得一个真实付费",
        stop_loss="没有两个真实点击则暂停",
        ai_leverage="只辅助生成虚构测试样例",
        predicted_hours=8,
        predicted_first_income_days=14,
        predicted_min_fen=0,
        predicted_max_fen=990,
    )
    assert planned.status == "chosen"
    assert planned.prediction_locked_at
    with pytest.raises(ValueError, match="已经冻结"):
        repository.update_opportunity_plan(
            opportunity.id,
            validation_step=planned.validation_step,
            two_week_plan=planned.two_week_plan,
            income_expectation=planned.income_expectation,
            stop_loss=planned.stop_loss,
            ai_leverage=planned.ai_leverage,
            predicted_hours=9,
            predicted_first_income_days=14,
            predicted_min_fen=0,
            predicted_max_fen=990,
        )
    retro = repository.add_retro(
        opportunity.id,
        actual_hours=6,
        actual_income_fen=0,
        first_income_at="",
        red_flags_seen="",
        blockers="公开流量不足",
        decision="adjust",
        lesson="先验证入口，再继续完善产品",
    )
    assert retro.decision == "adjust"


def test_hard_red_flag_forces_high_risk_and_drop(tmp_path: Path) -> None:
    repository = IncomeRepository(tmp_path)
    opportunity = repository.current_opportunity()
    assert opportunity is not None
    updated = repository.update_opportunity_verification(
        opportunity.id,
        status="verifying",
        verdict="suspect",
        hard_flags=("A1",),
        suspect_flags=(),
        money_flow=opportunity.money_flow,
        signal_summary=opportunity.signal_summary,
        freshness_note="",
        cross_check="",
    )
    assert updated.verdict == "high_risk"
    assert updated.status == "dropped"


def test_money_skill_pages_and_forms(tmp_path: Path) -> None:
    application = create_app(content_root=tmp_path, enable_scheduler=False)
    client = TestClient(application)
    assert client.get("/income/profile").status_code == 200
    opportunities = client.get("/income/opportunities")
    assert opportunities.status_code == 200
    assert "候选机会" in opportunities.text
    opportunity = application.state.income.current_opportunity()
    assert opportunity is not None
    detail = client.get(f"/income/opportunities/{opportunity.id}")
    assert detail.status_code == 200
    assert "需求证据" in detail.text
    assert "反诈核验" in detail.text
    created = client.post(
        "/income/opportunities",
        data={
            "name": "本地数据检查工具",
            "source_key": "micro_saas",
            "category": "micro_saas",
            "target_customer": "需要检查数据的团队",
            "for_tier": "T2",
            "money_flow": "团队为减少人工检查付费",
            "signal_summary": "待补公开证据",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert client.get("/income/opportunities/missing").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/income/signals",
        "/income/experiments",
        "/income/ledger",
        "/income/settings",
        "/income/scan",
        "/income/bounties/legacy",
    ],
)
def test_removed_business_urls_return_404(tmp_path: Path, path: str) -> None:
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    assert client.get(path).status_code == 404


def test_mobile_gateway_exposes_no_income_routes(tmp_path: Path) -> None:
    from app.mobile_main import create_mobile_app

    client = TestClient(create_mobile_app(data_root=tmp_path))
    assert client.get("/income").status_code in {404, 503}
