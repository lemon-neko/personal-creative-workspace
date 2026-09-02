"""Private income ledger and zero-cost Money Engine validation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.database import WORKSPACE_REGISTRY, apply_migrations, connect_database


SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_DEFINITIONS = (
    ("digital_product", 1, "数字产品", "模板、工作流、资料包与代码包"),
    ("intelligence_subscription", 2, "情报订阅", "按周或按月更新的精选数据与信息"),
    ("micro_saas", 3, "Micro-SaaS", "解决一个具体问题的小工具"),
    ("ads_cps", 4, "广告与 CPS", "免费工具或内容带来的广告与成交分成"),
)
SOURCE_KEYS = tuple(value[0] for value in SOURCE_DEFINITIONS)
SOURCE_STATUSES = {"not_started", "preparing", "selling", "paused"}
ENTRY_TYPES = {"revenue", "expense", "refund"}
ENTRY_STATUSES = {"pending", "confirmed", "void"}
PRODUCT_ID = "agent-reliability-launch-kit"
PRODUCT_STAGES = {
    "package_draft",
    "store_setup",
    "traffic_ready",
    "selling",
    "validating",
    "cleared",
    "paused",
}
ROLE_STATUSES = {"not_started", "active", "blocked", "done"}
ROLE_DEFINITIONS = (
    ("product", 1, "产品", "product", "完善可购买的交付物", "完成并校验完整 ZIP", 1),
    ("traffic", 2, "流量", "traffic", "让陌生用户发现免费仓库或文章", "创建公开精简仓库", 1),
    ("conversion", 3, "转化", "conversion", "让用户理解完整版价值并进入商品页", "完成商品说明和公众号介绍", 1),
    ("delivery", 4, "交付", "delivery", "确认第三方商店自动交付正确文件", "创建商品页并测试自动交付", 1),
    ("validation", 5, "验证", "validation", "记录订单、退款期和真实到账", "等待第一笔陌生用户订单", 1),
)
ROLE_KEYS = tuple(value[0] for value in ROLE_DEFINITIONS)
MONEY_TIERS = {"T0", "T1", "T2", "T3"}
MONEY_OPPORTUNITY_STATUSES = {
    "candidate",
    "verifying",
    "chosen",
    "running",
    "completed",
    "dropped",
}
MONEY_VERDICTS = {"unreviewed", "suspect", "viable", "high_risk"}
MONEY_CATEGORIES = {
    "service",
    "digital_product",
    "subscription",
    "micro_saas",
    "ads_cps",
    "other",
}
EVIDENCE_KINDS = {
    "demand",
    "recruiting",
    "procurement",
    "payment",
    "policy",
    "complaint",
    "official",
}
RETRO_DECISIONS = {"continue", "adjust", "stop"}
HARD_RED_FLAGS = {
    "A1": "要求先交报名、培训或入门费用",
    "A2": "保证收入或承诺异常高回报",
    "A3": "主要依靠拉人头和下线佣金",
    "A4": "要求代管资金、账户或支付工具",
    "A5": "核心商品仍是教人赚钱的递归课程",
    "A6": "涉及灰产、违法、刷量或平台作弊",
}
SUSPECT_FLAGS = {
    "B1": "缺少真实付款或采购证据",
    "B2": "报价明显偏离同类市场",
    "B3": "只能私聊且没有可信托管",
    "B4": "使用不合理的紧迫感催促决定",
    "B5": "要求先完成大段免费试做",
    "B6": "需求方或雇主无法验证",
}
MONEY_PROFILE_ID = "primary"
MONEY_PRODUCT_OPPORTUNITY_ID = "opportunity-agent-reliability-launch-kit"


def _now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def format_cny(fen: int) -> str:
    sign = "-" if fen < 0 else ""
    return f"{sign}¥{abs(fen) / 100:,.2f}"


def _https_url(value: str, *, hosts: set[str], label: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.lower() not in hosts
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{label}必须使用指定平台且不含账号信息的 HTTPS 地址")
    return value[:1000]


def _public_evidence_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or host == "localhost"
        or host.endswith(".local")
    ):
        raise ValueError("证据链接必须是没有账号信息的公开 HTTPS 地址")
    try:
        if ip_address(host).is_private or ip_address(host).is_loopback:
            raise ValueError("证据链接不能指向本机或私网地址")
    except ValueError as error:
        if "私网" in str(error):
            raise
    return value[:1000]


def _codes(values: tuple[str, ...], allowed: dict[str, str]) -> str:
    clean = tuple(dict.fromkeys(value for value in values if value))
    if any(value not in allowed for value in clean):
        raise ValueError("风险标记无效")
    return ",".join(clean)


@dataclass(frozen=True)
class IncomeSource:
    key: str
    position: int
    display_name: str
    description: str
    status: str
    current_product: str
    price_note: str
    sales_url: str
    next_action: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class IncomeEntry:
    id: str
    source_key: str
    entry_type: str
    cash_status: str
    gross_fen: int
    platform_fee_fen: int
    occurred_at: str
    note: str
    created_at: str
    updated_at: str

    @property
    def net_fen(self) -> int:
        if self.entry_type == "revenue":
            return self.gross_fen - self.platform_fee_fen
        return -self.gross_fen


@dataclass(frozen=True)
class IncomeMetrics:
    earned_fen: int
    month_earned_fen: int
    pending_fen: int
    deductions_fen: int
    net_cash_fen: int


@dataclass(frozen=True)
class IncomeSourceSummary:
    source: IncomeSource
    earned_fen: int
    pending_fen: int
    order_count: int


@dataclass(frozen=True)
class MoneyEngineProduct:
    id: str
    source_key: str
    name: str
    product_type: str
    target_user: str
    price_fen: int
    package_version: str
    current_stage: str
    github_url: str
    article_url: str
    store_url: str
    next_action: str
    active: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProductMetricSnapshot:
    id: str
    product_id: str
    observed_at: str
    impressions: int
    store_clicks: int
    paid_orders: int
    delivered_orders: int
    refunds: int
    created_at: str


@dataclass(frozen=True)
class RevenueValidation:
    id: str
    product_id: str
    income_entry_id: str
    unfamiliar_buyer: int
    no_direct_sales: int
    third_party_payment: int
    automatic_delivery: int
    refund_window_ended: int
    no_refund: int
    cleared_at: str
    created_at: str
    updated_at: str
    entry_status: str
    net_received_fen: int

    @property
    def cleared(self) -> bool:
        return bool(self.cleared_at)

    @property
    def completed_checks(self) -> int:
        return sum(
            bool(value)
            for value in (
                self.unfamiliar_buyer,
                self.no_direct_sales,
                self.third_party_payment,
                self.automatic_delivery,
                self.refund_window_ended,
                self.no_refund,
            )
        )


@dataclass(frozen=True)
class RevenueRoleCard:
    role_key: str
    product_id: str
    source_key: str
    position: int
    display_name: str
    funnel_stage: str
    purpose: str
    status: str
    observable_result: str
    next_action: str
    requires_confirmation: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MoneyProfile:
    id: str
    tier: str
    tier_reason: str
    skills: str
    weekly_hours: int | None
    startup_capital_fen: int
    region: str
    languages: str
    can_show_face: str
    goal: str
    willing_to_learn: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MoneyOpportunity:
    id: str
    source_key: str
    product_id: str
    name: str
    category: str
    target_customer: str
    for_tier: str
    money_flow: str
    status: str
    verdict: str
    hard_flags: str
    suspect_flags: str
    signal_summary: str
    freshness_note: str
    cross_check: str
    validation_step: str
    two_week_plan: str
    income_expectation: str
    stop_loss: str
    ai_leverage: str
    predicted_hours: int | None
    predicted_first_income_days: int | None
    predicted_min_fen: int | None
    predicted_max_fen: int | None
    prediction_locked_at: str
    created_at: str
    updated_at: str

    @property
    def hard_flag_codes(self) -> tuple[str, ...]:
        return tuple(value for value in self.hard_flags.split(",") if value)

    @property
    def suspect_flag_codes(self) -> tuple[str, ...]:
        return tuple(value for value in self.suspect_flags.split(",") if value)


@dataclass(frozen=True)
class MoneyEvidence:
    id: str
    opportunity_id: str
    source_url: str
    source_title: str
    source_host: str
    source_kind: str
    published_at: str
    checked_at: str
    note: str
    created_at: str

    @property
    def age_days(self) -> int | None:
        if not self.published_at:
            return None
        return (datetime.now(SHANGHAI).date() - date.fromisoformat(self.published_at)).days


@dataclass(frozen=True)
class MoneyRetro:
    id: str
    opportunity_id: str
    actual_hours: int
    actual_income_fen: int
    first_income_at: str
    red_flags_seen: str
    blockers: str
    decision: str
    lesson: str
    created_at: str


@dataclass(frozen=True)
class MoneyVerification:
    evidence_count: int
    independent_source_count: int
    fresh_evidence_count: int
    ready: bool
    reason: str


LEGACY_CLEANUP = """
DROP TABLE IF EXISTS business_metric_snapshots;
DROP TABLE IF EXISTS business_ledger_entries;
DROP TABLE IF EXISTS business_experiments;
DROP TABLE IF EXISTS business_opportunities;
DROP TABLE IF EXISTS business_signals;
DROP TABLE IF EXISTS business_source_runs;
DROP TABLE IF EXISTS business_settings;
DROP TABLE IF EXISTS bounty_events;
DROP TABLE IF EXISTS bounty_payouts;
DROP TABLE IF EXISTS bounty_opportunities;
DROP TABLE IF EXISTS bounty_scan_runs;
DROP TABLE IF EXISTS bounty_settings;
"""


class IncomeRepository:
    """Four fixed income sources plus a manually confirmed cash ledger."""

    def __init__(self, data_root: Path) -> None:
        self.database_path = data_root / "workspace.db"
        snapshot_root = data_root / "working" / "db-migrations"
        # Versions 1 and 2 belong to the removed bounty/business workflow. The
        # registry only stores versions, so no legacy runtime code is needed to
        # advance an existing database to the destructive, snapshotted cleanup.
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="bounty_income",
            snapshot_root=snapshot_root,
            migrations={1: "SELECT 1;", 2: "SELECT 1;", 3: LEGACY_CLEANUP},
        )
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="income",
            snapshot_root=snapshot_root,
            migrations={
                1: """CREATE TABLE IF NOT EXISTS income_sources (
                    source_key TEXT PRIMARY KEY CHECK(source_key IN (
                        'digital_product','intelligence_subscription','micro_saas','ads_cps'
                    )),
                    position INTEGER NOT NULL UNIQUE CHECK(position BETWEEN 1 AND 4),
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN (
                        'not_started','preparing','selling','paused'
                    )),
                    current_product TEXT NOT NULL DEFAULT '',
                    price_note TEXT NOT NULL DEFAULT '',
                    sales_url TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS income_entries (
                    id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL REFERENCES income_sources(source_key) ON DELETE RESTRICT,
                    entry_type TEXT NOT NULL CHECK(entry_type IN ('revenue','expense','refund')),
                    cash_status TEXT NOT NULL DEFAULT 'pending' CHECK(cash_status IN (
                        'pending','confirmed','void'
                    )),
                    gross_fen INTEGER NOT NULL CHECK(gross_fen > 0),
                    platform_fee_fen INTEGER NOT NULL DEFAULT 0 CHECK(platform_fee_fen >= 0),
                    occurred_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(platform_fee_fen <= gross_fen)
                );
                CREATE INDEX IF NOT EXISTS income_entries_status_idx
                    ON income_entries(cash_status, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS income_entries_source_idx
                    ON income_entries(source_key, occurred_at DESC);""",
                2: """CREATE TABLE money_engine_products (
                    id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL REFERENCES income_sources(source_key) ON DELETE RESTRICT,
                    name TEXT NOT NULL,
                    product_type TEXT NOT NULL CHECK(product_type='digital_product'),
                    target_user TEXT NOT NULL,
                    price_fen INTEGER NOT NULL CHECK(price_fen=990),
                    package_version TEXT NOT NULL DEFAULT '1.0.0',
                    current_stage TEXT NOT NULL CHECK(current_stage IN (
                        'package_draft','store_setup','traffic_ready','selling',
                        'validating','cleared','paused'
                    )),
                    github_url TEXT NOT NULL DEFAULT '',
                    article_url TEXT NOT NULL DEFAULT '',
                    store_url TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX money_engine_single_active_idx
                    ON money_engine_products(active) WHERE active=1;
                CREATE TABLE product_metric_snapshots (
                    id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL REFERENCES money_engine_products(id) ON DELETE CASCADE,
                    observed_at TEXT NOT NULL,
                    impressions INTEGER NOT NULL DEFAULT 0 CHECK(impressions>=0),
                    store_clicks INTEGER NOT NULL DEFAULT 0 CHECK(store_clicks>=0),
                    paid_orders INTEGER NOT NULL DEFAULT 0 CHECK(paid_orders>=0),
                    delivered_orders INTEGER NOT NULL DEFAULT 0 CHECK(delivered_orders>=0),
                    refunds INTEGER NOT NULL DEFAULT 0 CHECK(refunds>=0),
                    created_at TEXT NOT NULL,
                    CHECK(delivered_orders<=paid_orders),
                    CHECK(refunds<=paid_orders)
                );
                CREATE INDEX product_metric_date_idx
                    ON product_metric_snapshots(product_id,observed_at DESC,created_at DESC);
                CREATE TABLE revenue_validations (
                    id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL REFERENCES money_engine_products(id) ON DELETE CASCADE,
                    income_entry_id TEXT NOT NULL UNIQUE REFERENCES income_entries(id) ON DELETE RESTRICT,
                    unfamiliar_buyer INTEGER NOT NULL DEFAULT 0 CHECK(unfamiliar_buyer IN (0,1)),
                    no_direct_sales INTEGER NOT NULL DEFAULT 0 CHECK(no_direct_sales IN (0,1)),
                    third_party_payment INTEGER NOT NULL DEFAULT 0 CHECK(third_party_payment IN (0,1)),
                    automatic_delivery INTEGER NOT NULL DEFAULT 0 CHECK(automatic_delivery IN (0,1)),
                    refund_window_ended INTEGER NOT NULL DEFAULT 0 CHECK(refund_window_ended IN (0,1)),
                    no_refund INTEGER NOT NULL DEFAULT 0 CHECK(no_refund IN (0,1)),
                    cleared_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE revenue_role_cards (
                    role_key TEXT PRIMARY KEY CHECK(role_key IN (
                        'product','traffic','conversion','delivery','validation'
                    )),
                    product_id TEXT NOT NULL REFERENCES money_engine_products(id) ON DELETE CASCADE,
                    source_key TEXT NOT NULL CHECK(source_key='digital_product'),
                    position INTEGER NOT NULL UNIQUE CHECK(position BETWEEN 1 AND 5),
                    display_name TEXT NOT NULL,
                    funnel_stage TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN (
                        'not_started','active','blocked','done'
                    )),
                    observable_result TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    requires_confirmation INTEGER NOT NULL DEFAULT 1 CHECK(requires_confirmation IN (0,1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );""",
                3: """CREATE TABLE money_profiles (
                    id TEXT PRIMARY KEY CHECK(id='primary'),
                    tier TEXT NOT NULL CHECK(tier IN ('T0','T1','T2','T3')),
                    tier_reason TEXT NOT NULL DEFAULT '',
                    skills TEXT NOT NULL DEFAULT '',
                    weekly_hours INTEGER CHECK(weekly_hours IS NULL OR weekly_hours>=0),
                    startup_capital_fen INTEGER NOT NULL DEFAULT 0 CHECK(startup_capital_fen>=0),
                    region TEXT NOT NULL DEFAULT '',
                    languages TEXT NOT NULL DEFAULT '',
                    can_show_face TEXT NOT NULL DEFAULT 'unknown' CHECK(can_show_face IN (
                        'unknown','yes','no'
                    )),
                    goal TEXT NOT NULL DEFAULT '',
                    willing_to_learn INTEGER NOT NULL DEFAULT 1 CHECK(willing_to_learn IN (0,1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE money_opportunities (
                    id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL REFERENCES income_sources(source_key) ON DELETE RESTRICT,
                    product_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    category TEXT NOT NULL CHECK(category IN (
                        'service','digital_product','subscription','micro_saas','ads_cps','other'
                    )),
                    target_customer TEXT NOT NULL DEFAULT '',
                    for_tier TEXT NOT NULL CHECK(for_tier IN ('T0','T1','T2','T3')),
                    money_flow TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN (
                        'candidate','verifying','chosen','running','completed','dropped'
                    )),
                    verdict TEXT NOT NULL DEFAULT 'unreviewed' CHECK(verdict IN (
                        'unreviewed','suspect','viable','high_risk'
                    )),
                    hard_flags TEXT NOT NULL DEFAULT '',
                    suspect_flags TEXT NOT NULL DEFAULT '',
                    signal_summary TEXT NOT NULL DEFAULT '',
                    freshness_note TEXT NOT NULL DEFAULT '',
                    cross_check TEXT NOT NULL DEFAULT '',
                    validation_step TEXT NOT NULL DEFAULT '',
                    two_week_plan TEXT NOT NULL DEFAULT '',
                    income_expectation TEXT NOT NULL DEFAULT '',
                    stop_loss TEXT NOT NULL DEFAULT '',
                    ai_leverage TEXT NOT NULL DEFAULT '',
                    predicted_hours INTEGER CHECK(predicted_hours IS NULL OR predicted_hours>=0),
                    predicted_first_income_days INTEGER CHECK(
                        predicted_first_income_days IS NULL OR predicted_first_income_days>=0
                    ),
                    predicted_min_fen INTEGER CHECK(predicted_min_fen IS NULL OR predicted_min_fen>=0),
                    predicted_max_fen INTEGER CHECK(predicted_max_fen IS NULL OR predicted_max_fen>=0),
                    prediction_locked_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(predicted_min_fen IS NULL OR predicted_max_fen IS NULL
                        OR predicted_min_fen<=predicted_max_fen)
                );
                CREATE UNIQUE INDEX money_opportunity_product_idx
                    ON money_opportunities(product_id) WHERE product_id<>'';
                CREATE INDEX money_opportunity_status_idx
                    ON money_opportunities(status,updated_at DESC);
                CREATE TABLE money_evidence (
                    id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL REFERENCES money_opportunities(id) ON DELETE CASCADE,
                    source_url TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_host TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK(source_kind IN (
                        'demand','recruiting','procurement','payment','policy',
                        'complaint','official'
                    )),
                    published_at TEXT NOT NULL DEFAULT '',
                    checked_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(opportunity_id,source_url)
                );
                CREATE INDEX money_evidence_opportunity_idx
                    ON money_evidence(opportunity_id,checked_at DESC);
                CREATE TABLE money_retros (
                    id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL REFERENCES money_opportunities(id) ON DELETE CASCADE,
                    actual_hours INTEGER NOT NULL DEFAULT 0 CHECK(actual_hours>=0),
                    actual_income_fen INTEGER NOT NULL DEFAULT 0 CHECK(actual_income_fen>=0),
                    first_income_at TEXT NOT NULL DEFAULT '',
                    red_flags_seen TEXT NOT NULL DEFAULT '',
                    blockers TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL CHECK(decision IN ('continue','adjust','stop')),
                    lesson TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX money_retro_opportunity_idx
                    ON money_retros(opportunity_id,created_at DESC);""",
            },
        )
        self._seed_sources()
        self._seed_money_engine()
        self._seed_money_method()

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def _seed_sources(self) -> None:
        now = _now()
        with self.connect() as connection:
            for key, position, name, description in SOURCE_DEFINITIONS:
                connection.execute(
                    """INSERT OR IGNORE INTO income_sources(
                    source_key,position,display_name,description,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?)""",
                    (key, position, name, description, now, now),
                )

    def _seed_money_engine(self) -> None:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO money_engine_products(
                id,source_key,name,product_type,target_user,price_fen,package_version,
                current_stage,next_action,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    PRODUCT_ID,
                    "digital_product",
                    "羽白 Agent 应用可靠性上线包",
                    "digital_product",
                    "正在开发 Agent 应用的个人开发者",
                    990,
                    "1.0.0",
                    "package_draft",
                    "完成并校验可自动交付的完整 ZIP",
                    1,
                    now,
                    now,
                ),
            )

    def _seed_money_method(self) -> None:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO money_profiles(
                id,tier,tier_reason,skills,weekly_hours,startup_capital_fen,region,
                languages,can_show_face,goal,willing_to_learn,created_at,updated_at
                ) VALUES(?,?,?,?,NULL,?,?,?,?,?,?,?,?)""",
                (
                    MONEY_PROFILE_ID,
                    "T2",
                    "具备编程与工程实现能力，正在补齐 Agent 应用工程和商业验证。",
                    "Python、FastAPI、测试与评测、Agent 应用开发",
                    0,
                    "中国",
                    "中文",
                    "unknown",
                    "用可验证、可交付的产品或服务获得第一笔真实收入",
                    1,
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO money_opportunities(
                id,source_key,product_id,name,category,target_customer,for_tier,
                money_flow,status,verdict,signal_summary,validation_step,
                income_expectation,stop_loss,ai_leverage,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    MONEY_PRODUCT_OPPORTUNITY_ID,
                    "digital_product",
                    PRODUCT_ID,
                    "Agent 应用可靠性上线包",
                    "digital_product",
                    "正在开发 Agent 应用的个人开发者",
                    "T2",
                    "开发者为可复用的验收、权限、评测和上线模板付费",
                    "verifying",
                    "unreviewed",
                    "现有产品假设尚需用两个独立、近期的真实需求信号验证。",
                    "先补齐两个独立公开需求证据，再决定是否投入完整制作。",
                    "首轮只验证是否有人愿意为完整模板包支付 ¥9.9。",
                    "没有两个独立需求信号，或最小公开入口没有真实点击时暂停。",
                    "用 Codex 辅助整理模板、测试示例和发布清单，不自动销售或收款。",
                    now,
                    now,
                ),
            )
            for role in ROLE_DEFINITIONS:
                connection.execute(
                    """INSERT OR IGNORE INTO revenue_role_cards(
                    role_key,position,display_name,funnel_stage,purpose,next_action,
                    requires_confirmation,product_id,source_key,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (*role, PRODUCT_ID, "digital_product", now, now),
                )
            connection.execute(
                """UPDATE income_sources SET
                status=CASE WHEN status='not_started' THEN 'preparing' ELSE status END,
                current_product=CASE WHEN current_product='' THEN ? ELSE current_product END,
                price_note=CASE WHEN price_note='' THEN '¥9.9' ELSE price_note END,
                next_action=CASE WHEN next_action='' THEN ? ELSE next_action END,
                updated_at=? WHERE source_key='digital_product'""",
                (
                    "羽白 Agent 应用可靠性上线包",
                    "完成并校验可自动交付的完整 ZIP",
                    now,
                ),
            )

    @staticmethod
    def _source(row: sqlite3.Row) -> IncomeSource:
        values = dict(row)
        values["key"] = values.pop("source_key")
        return IncomeSource(**values)

    @staticmethod
    def _entry(row: sqlite3.Row) -> IncomeEntry:
        return IncomeEntry(**dict(row))

    @staticmethod
    def _product(row: sqlite3.Row) -> MoneyEngineProduct:
        return MoneyEngineProduct(**dict(row))

    @staticmethod
    def _metric(row: sqlite3.Row) -> ProductMetricSnapshot:
        return ProductMetricSnapshot(**dict(row))

    @staticmethod
    def _role(row: sqlite3.Row) -> RevenueRoleCard:
        return RevenueRoleCard(**dict(row))

    @staticmethod
    def _validation(row: sqlite3.Row) -> RevenueValidation:
        return RevenueValidation(**dict(row))

    @staticmethod
    def _money_profile(row: sqlite3.Row) -> MoneyProfile:
        return MoneyProfile(**dict(row))

    @staticmethod
    def _opportunity(row: sqlite3.Row) -> MoneyOpportunity:
        return MoneyOpportunity(**dict(row))

    @staticmethod
    def _evidence(row: sqlite3.Row) -> MoneyEvidence:
        return MoneyEvidence(**dict(row))

    @staticmethod
    def _retro(row: sqlite3.Row) -> MoneyRetro:
        return MoneyRetro(**dict(row))

    def sources(self) -> tuple[IncomeSource, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM income_sources ORDER BY position"
            ).fetchall()
        return tuple(self._source(row) for row in rows)

    def source(self, source_key: str) -> IncomeSource | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM income_sources WHERE source_key=?", (source_key,)
            ).fetchone()
        return self._source(row) if row else None

    def product(self, product_id: str = PRODUCT_ID) -> MoneyEngineProduct | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM money_engine_products WHERE id=?", (product_id,)
            ).fetchone()
        return self._product(row) if row else None

    def active_product(self) -> MoneyEngineProduct:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM money_engine_products WHERE active=1"
            ).fetchone()
        if row is None:
            raise LookupError("当前没有激活的 Money Engine 产品")
        return self._product(row)

    def update_product(
        self,
        product_id: str,
        *,
        package_version: str,
        current_stage: str,
        github_url: str,
        article_url: str,
        store_url: str,
        next_action: str,
    ) -> MoneyEngineProduct:
        if self.product(product_id) is None:
            raise LookupError("产品不存在")
        if current_stage not in PRODUCT_STAGES:
            raise ValueError("产品阶段无效")
        if current_stage == "cleared" and not self.first_yuan_cleared(product_id):
            raise ValueError("只有满足全部首单条件后才能进入已通关阶段")
        version = package_version.strip()
        if not version or len(version) > 40 or any(
            character not in "0123456789.-_" for character in version
        ):
            raise ValueError("产品版本只能包含数字、点、横线和下划线")
        github = _https_url(
            github_url,
            hosts={"github.com", "www.github.com"},
            label="GitHub 仓库",
        )
        if github and github.rstrip("/").split("/")[-1] != PRODUCT_ID:
            raise ValueError(f"GitHub 仓库名必须为 {PRODUCT_ID}")
        article = _https_url(
            article_url,
            hosts={"mp.weixin.qq.com"},
            label="公众号文章",
        )
        store = _https_url(
            store_url,
            hosts={"mbd.pub", "www.mbd.pub"},
            label="面包多商品页",
        )
        with self.connect() as connection:
            connection.execute(
                """UPDATE money_engine_products SET package_version=?,current_stage=?,
                github_url=?,article_url=?,store_url=?,next_action=?,updated_at=? WHERE id=?""",
                (
                    version,
                    current_stage,
                    github,
                    article,
                    store,
                    next_action.strip()[:500],
                    _now(),
                    product_id,
                ),
            )
        return self.product(product_id)  # type: ignore[return-value]

    def add_metric_snapshot(
        self,
        product_id: str,
        *,
        observed_at: str,
        impressions: int,
        store_clicks: int,
        paid_orders: int,
        delivered_orders: int,
        refunds: int,
    ) -> ProductMetricSnapshot:
        if self.product(product_id) is None:
            raise LookupError("产品不存在")
        values = (impressions, store_clicks, paid_orders, delivered_orders, refunds)
        if any(value < 0 for value in values):
            raise ValueError("漏斗数据不能为负数")
        if delivered_orders > paid_orders:
            raise ValueError("自动交付数不能超过付款订单数")
        if refunds > paid_orders:
            raise ValueError("退款数不能超过付款订单数")
        observed = observed_at.strip() or datetime.now(SHANGHAI).date().isoformat()
        try:
            date.fromisoformat(observed)
        except ValueError as error:
            raise ValueError("观察日期格式无效") from error
        item_id = f"metric-{uuid4().hex[:12]}"
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO product_metric_snapshots(
                id,product_id,observed_at,impressions,store_clicks,paid_orders,
                delivered_orders,refunds,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (item_id, product_id, observed, *values, _now()),
            )
        return self.metric_snapshot(item_id)  # type: ignore[return-value]

    def metric_snapshot(self, item_id: str) -> ProductMetricSnapshot | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM product_metric_snapshots WHERE id=?", (item_id,)
            ).fetchone()
        return self._metric(row) if row else None

    def latest_metric(self, product_id: str = PRODUCT_ID) -> ProductMetricSnapshot | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM product_metric_snapshots WHERE product_id=?
                ORDER BY observed_at DESC,created_at DESC LIMIT 1""",
                (product_id,),
            ).fetchone()
        return self._metric(row) if row else None

    def product_roles(self, product_id: str = PRODUCT_ID) -> tuple[RevenueRoleCard, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM revenue_role_cards WHERE product_id=?
                ORDER BY position""",
                (product_id,),
            ).fetchall()
        return tuple(self._role(row) for row in rows)

    def update_role(
        self,
        product_id: str,
        role_key: str,
        *,
        status: str,
        observable_result: str,
        next_action: str,
        requires_confirmation: bool,
    ) -> RevenueRoleCard:
        if self.product(product_id) is None:
            raise LookupError("产品不存在")
        if role_key not in ROLE_KEYS:
            raise LookupError("收入职责不存在")
        if status not in ROLE_STATUSES:
            raise ValueError("职责状态无效")
        with self.connect() as connection:
            connection.execute(
                """UPDATE revenue_role_cards SET status=?,observable_result=?,
                next_action=?,requires_confirmation=?,updated_at=?
                WHERE product_id=? AND role_key=?""",
                (
                    status,
                    observable_result.strip()[:500],
                    next_action.strip()[:500],
                    int(requires_confirmation),
                    _now(),
                    product_id,
                    role_key,
                ),
            )
            row = connection.execute(
                "SELECT * FROM revenue_role_cards WHERE product_id=? AND role_key=?",
                (product_id, role_key),
            ).fetchone()
        if row is None:
            raise LookupError("收入职责不存在")
        return self._role(row)

    def validations(self, product_id: str = PRODUCT_ID) -> tuple[RevenueValidation, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT validation.*,entry.cash_status AS entry_status,
                CASE WHEN entry.entry_type='revenue'
                    THEN entry.gross_fen-entry.platform_fee_fen ELSE 0 END AS net_received_fen
                FROM revenue_validations validation
                JOIN income_entries entry ON entry.id=validation.income_entry_id
                WHERE validation.product_id=? ORDER BY validation.updated_at DESC""",
                (product_id,),
            ).fetchall()
        return tuple(self._validation(row) for row in rows)

    def record_validation(
        self,
        product_id: str,
        *,
        income_entry_id: str,
        unfamiliar_buyer: bool,
        no_direct_sales: bool,
        third_party_payment: bool,
        automatic_delivery: bool,
        refund_window_ended: bool,
        no_refund: bool,
    ) -> RevenueValidation:
        product = self.product(product_id)
        entry = self.entry(income_entry_id)
        if product is None:
            raise LookupError("产品不存在")
        if (
            entry is None
            or entry.source_key != product.source_key
            or entry.entry_type != "revenue"
            or entry.cash_status == "void"
        ):
            raise ValueError("只能选择该数字产品尚未作废的收入记录")
        checks = (
            unfamiliar_buyer,
            no_direct_sales,
            third_party_payment,
            automatic_delivery,
            refund_window_ended,
            no_refund,
        )
        cleared = (
            all(checks)
            and entry.cash_status == "confirmed"
            and entry.net_fen >= 100
        )
        now = _now()
        validation_id = f"validation-{uuid4().hex[:12]}"
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id,created_at FROM revenue_validations WHERE income_entry_id=?",
                (income_entry_id,),
            ).fetchone()
            if existing:
                validation_id = existing["id"]
                created_at = existing["created_at"]
            else:
                created_at = now
            connection.execute(
                """INSERT INTO revenue_validations(
                id,product_id,income_entry_id,unfamiliar_buyer,no_direct_sales,
                third_party_payment,automatic_delivery,refund_window_ended,no_refund,
                cleared_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(income_entry_id) DO UPDATE SET
                unfamiliar_buyer=excluded.unfamiliar_buyer,
                no_direct_sales=excluded.no_direct_sales,
                third_party_payment=excluded.third_party_payment,
                automatic_delivery=excluded.automatic_delivery,
                refund_window_ended=excluded.refund_window_ended,
                no_refund=excluded.no_refund,
                cleared_at=excluded.cleared_at,updated_at=excluded.updated_at""",
                (
                    validation_id,
                    product_id,
                    income_entry_id,
                    *(int(value) for value in checks),
                    now if cleared else "",
                    created_at,
                    now,
                ),
            )
            if cleared:
                connection.execute(
                    """UPDATE money_engine_products SET current_stage='cleared',
                    updated_at=? WHERE id=?""",
                    (now, product_id),
                )
            elif connection.execute(
                """SELECT 1 FROM revenue_validations
                WHERE product_id=? AND id<>? AND cleared_at<>'' LIMIT 1""",
                (product_id, validation_id),
            ).fetchone() is None:
                connection.execute(
                    """UPDATE money_engine_products SET current_stage='validating',
                    updated_at=? WHERE id=? AND current_stage='cleared'""",
                    (now, product_id),
                )
        return next(
            item for item in self.validations(product_id)
            if item.income_entry_id == income_entry_id
        )

    def first_yuan_cleared(self, product_id: str = PRODUCT_ID) -> bool:
        return any(item.cleared for item in self.validations(product_id))

    def money_profile(self) -> MoneyProfile:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM money_profiles WHERE id=?", (MONEY_PROFILE_ID,)
            ).fetchone()
        if row is None:
            raise LookupError("赚钱画像不存在")
        return self._money_profile(row)

    def update_money_profile(
        self,
        *,
        tier: str,
        tier_reason: str,
        skills: str,
        weekly_hours: int | None,
        startup_capital_fen: int,
        region: str,
        languages: str,
        can_show_face: str,
        goal: str,
        willing_to_learn: bool,
    ) -> MoneyProfile:
        if tier not in MONEY_TIERS:
            raise ValueError("能力层级无效")
        if weekly_hours is not None and weekly_hours < 0:
            raise ValueError("每周时间不能为负数")
        if startup_capital_fen < 0:
            raise ValueError("启动资金不能为负数")
        if can_show_face not in {"unknown", "yes", "no"}:
            raise ValueError("出镜偏好无效")
        if not goal.strip():
            raise ValueError("请填写当前收入目标")
        with self.connect() as connection:
            connection.execute(
                """UPDATE money_profiles SET tier=?,tier_reason=?,skills=?,weekly_hours=?,
                startup_capital_fen=?,region=?,languages=?,can_show_face=?,goal=?,
                willing_to_learn=?,updated_at=? WHERE id=?""",
                (
                    tier,
                    tier_reason.strip()[:1000],
                    skills.strip()[:2000],
                    weekly_hours,
                    startup_capital_fen,
                    region.strip()[:200],
                    languages.strip()[:200],
                    can_show_face,
                    goal.strip()[:1000],
                    int(willing_to_learn),
                    _now(),
                    MONEY_PROFILE_ID,
                ),
            )
        return self.money_profile()

    def opportunities(self) -> tuple[MoneyOpportunity, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM money_opportunities
                ORDER BY CASE status
                    WHEN 'running' THEN 1 WHEN 'chosen' THEN 2 WHEN 'verifying' THEN 3
                    WHEN 'candidate' THEN 4 WHEN 'completed' THEN 5 ELSE 6 END,
                updated_at DESC"""
            ).fetchall()
        return tuple(self._opportunity(row) for row in rows)

    def opportunity(self, opportunity_id: str) -> MoneyOpportunity | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM money_opportunities WHERE id=?", (opportunity_id,)
            ).fetchone()
        return self._opportunity(row) if row else None

    def current_opportunity(self) -> MoneyOpportunity | None:
        items = self.opportunities()
        return next(
            (
                item
                for item in items
                if item.status in {"running", "chosen", "verifying", "candidate"}
            ),
            None,
        )

    def create_opportunity(
        self,
        *,
        name: str,
        source_key: str,
        category: str,
        target_customer: str,
        for_tier: str,
        money_flow: str,
        signal_summary: str,
    ) -> MoneyOpportunity:
        if source_key not in SOURCE_KEYS:
            raise ValueError("收入来源无效")
        if category not in MONEY_CATEGORIES:
            raise ValueError("机会类型无效")
        if for_tier not in MONEY_TIERS:
            raise ValueError("适合层级无效")
        if not name.strip() or not target_customer.strip() or not money_flow.strip():
            raise ValueError("机会名称、付费客户和资金流不能为空")
        opportunity_id = f"opportunity-{uuid4().hex[:12]}"
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO money_opportunities(
                id,source_key,name,category,target_customer,for_tier,money_flow,
                status,verdict,signal_summary,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,'candidate','unreviewed',?,?,?)""",
                (
                    opportunity_id,
                    source_key,
                    name.strip()[:300],
                    category,
                    target_customer.strip()[:500],
                    for_tier,
                    money_flow.strip()[:1000],
                    signal_summary.strip()[:2000],
                    now,
                    now,
                ),
            )
        return self.opportunity(opportunity_id)  # type: ignore[return-value]

    def evidence(self, opportunity_id: str) -> tuple[MoneyEvidence, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM money_evidence WHERE opportunity_id=?
                ORDER BY checked_at DESC,created_at DESC""",
                (opportunity_id,),
            ).fetchall()
        return tuple(self._evidence(row) for row in rows)

    def add_evidence(
        self,
        opportunity_id: str,
        *,
        source_url: str,
        source_title: str,
        source_kind: str,
        published_at: str,
        checked_at: str,
        note: str,
    ) -> MoneyEvidence:
        if self.opportunity(opportunity_id) is None:
            raise LookupError("商业机会不存在")
        if source_kind not in EVIDENCE_KINDS:
            raise ValueError("证据类型无效")
        url = _public_evidence_url(source_url)
        if not source_title.strip():
            raise ValueError("请填写证据标题")
        published = published_at.strip()
        checked = checked_at.strip() or datetime.now(SHANGHAI).date().isoformat()
        for value, label in ((published, "发布日期"), (checked, "核验日期")):
            if not value:
                continue
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"{label}格式无效") from error
        if published and date.fromisoformat(published) > datetime.now(SHANGHAI).date():
            raise ValueError("发布日期不能晚于今天")
        evidence_id = f"evidence-{uuid4().hex[:12]}"
        with self.connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO money_evidence(
                    id,opportunity_id,source_url,source_title,source_host,source_kind,
                    published_at,checked_at,note,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        evidence_id,
                        opportunity_id,
                        url,
                        source_title.strip()[:500],
                        (urlparse(url).hostname or "").lower(),
                        source_kind,
                        published,
                        checked,
                        note.strip()[:1500],
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("该机会已记录过这个证据链接") from error
        return next(item for item in self.evidence(opportunity_id) if item.id == evidence_id)

    def verification(self, opportunity_id: str) -> MoneyVerification:
        opportunity = self.opportunity(opportunity_id)
        if opportunity is None:
            raise LookupError("商业机会不存在")
        items = self.evidence(opportunity_id)
        usable = tuple(
            item for item in items if item.age_days is not None and item.age_days <= 730
        )
        fresh = tuple(item for item in usable if item.age_days is not None and item.age_days <= 365)
        independent = len({item.source_host for item in usable})
        if opportunity.hard_flag_codes:
            reason = "存在硬性红旗，不能进入执行。"
        elif len(usable) < 2 or independent < 2:
            reason = "至少需要两个不同来源、两年内的真实需求证据。"
        elif not fresh:
            reason = "需要至少一条一年内的新鲜证据。"
        elif not opportunity.cross_check.strip():
            reason = "请记录两个来源如何相互印证。"
        elif opportunity.verdict != "viable":
            reason = "证据已具备，请明确标记为可验证后再执行。"
        else:
            reason = "证据、时效和反诈检查均满足最小验证条件。"
        return MoneyVerification(
            evidence_count=len(items),
            independent_source_count=independent,
            fresh_evidence_count=len(fresh),
            ready=(
                not opportunity.hard_flag_codes
                and len(usable) >= 2
                and independent >= 2
                and bool(fresh)
                and bool(opportunity.cross_check.strip())
                and opportunity.verdict == "viable"
            ),
            reason=reason,
        )

    def update_opportunity_verification(
        self,
        opportunity_id: str,
        *,
        status: str,
        verdict: str,
        hard_flags: tuple[str, ...],
        suspect_flags: tuple[str, ...],
        money_flow: str,
        signal_summary: str,
        freshness_note: str,
        cross_check: str,
    ) -> MoneyOpportunity:
        item = self.opportunity(opportunity_id)
        if item is None:
            raise LookupError("商业机会不存在")
        if status not in MONEY_OPPORTUNITY_STATUSES:
            raise ValueError("机会状态无效")
        if verdict not in MONEY_VERDICTS:
            raise ValueError("验证结论无效")
        hard = _codes(hard_flags, HARD_RED_FLAGS)
        suspect = _codes(suspect_flags, SUSPECT_FLAGS)
        if hard:
            verdict = "high_risk"
            status = "dropped"
        evidence = self.evidence(opportunity_id)
        usable = tuple(
            value for value in evidence
            if value.age_days is not None and value.age_days <= 730
        )
        independent = len({value.source_host for value in usable})
        has_fresh = any(
            value.age_days is not None and value.age_days <= 365 for value in usable
        )
        if verdict == "viable" and (
            len(usable) < 2 or independent < 2 or not has_fresh or not cross_check.strip()
        ):
            raise ValueError("标记可验证前，需要两个独立的两年内证据、至少一个近期证据及交叉印证")
        if status in {"chosen", "running", "completed"} and verdict != "viable":
            raise ValueError("只有通过反诈与需求核验的机会才能进入执行")
        with self.connect() as connection:
            connection.execute(
                """UPDATE money_opportunities SET status=?,verdict=?,hard_flags=?,
                suspect_flags=?,money_flow=?,signal_summary=?,freshness_note=?,
                cross_check=?,updated_at=? WHERE id=?""",
                (
                    status,
                    verdict,
                    hard,
                    suspect,
                    money_flow.strip()[:1000],
                    signal_summary.strip()[:2000],
                    freshness_note.strip()[:1000],
                    cross_check.strip()[:2000],
                    _now(),
                    opportunity_id,
                ),
            )
        return self.opportunity(opportunity_id)  # type: ignore[return-value]

    def update_opportunity_plan(
        self,
        opportunity_id: str,
        *,
        validation_step: str,
        two_week_plan: str,
        income_expectation: str,
        stop_loss: str,
        ai_leverage: str,
        predicted_hours: int | None,
        predicted_first_income_days: int | None,
        predicted_min_fen: int | None,
        predicted_max_fen: int | None,
    ) -> MoneyOpportunity:
        item = self.opportunity(opportunity_id)
        if item is None:
            raise LookupError("商业机会不存在")
        if not self.verification(opportunity_id).ready:
            raise ValueError("先完成需求证据和反诈核验，再冻结执行预测")
        numbers = (
            predicted_hours,
            predicted_first_income_days,
            predicted_min_fen,
            predicted_max_fen,
        )
        if any(value is not None and value < 0 for value in numbers):
            raise ValueError("预测值不能为负数")
        if (
            predicted_min_fen is not None
            and predicted_max_fen is not None
            and predicted_min_fen > predicted_max_fen
        ):
            raise ValueError("预测收入下限不能高于上限")
        prediction = numbers
        current_prediction = (
            item.predicted_hours,
            item.predicted_first_income_days,
            item.predicted_min_fen,
            item.predicted_max_fen,
        )
        if item.prediction_locked_at and prediction != current_prediction:
            raise ValueError("执行前预测已经冻结，复盘时记录实际结果，不回改预测")
        if not validation_step.strip() or not stop_loss.strip():
            raise ValueError("最小验证步骤和止损条件不能为空")
        locked_at = item.prediction_locked_at or _now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE money_opportunities SET validation_step=?,two_week_plan=?,
                income_expectation=?,stop_loss=?,ai_leverage=?,predicted_hours=?,
                predicted_first_income_days=?,predicted_min_fen=?,predicted_max_fen=?,
                prediction_locked_at=?,status=CASE WHEN status IN ('candidate','verifying')
                    THEN 'chosen' ELSE status END,updated_at=? WHERE id=?""",
                (
                    validation_step.strip()[:1500],
                    two_week_plan.strip()[:3000],
                    income_expectation.strip()[:1000],
                    stop_loss.strip()[:1500],
                    ai_leverage.strip()[:1500],
                    predicted_hours,
                    predicted_first_income_days,
                    predicted_min_fen,
                    predicted_max_fen,
                    locked_at,
                    _now(),
                    opportunity_id,
                ),
            )
        return self.opportunity(opportunity_id)  # type: ignore[return-value]

    def retros(self, opportunity_id: str) -> tuple[MoneyRetro, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM money_retros WHERE opportunity_id=?
                ORDER BY created_at DESC""",
                (opportunity_id,),
            ).fetchall()
        return tuple(self._retro(row) for row in rows)

    def add_retro(
        self,
        opportunity_id: str,
        *,
        actual_hours: int,
        actual_income_fen: int,
        first_income_at: str,
        red_flags_seen: str,
        blockers: str,
        decision: str,
        lesson: str,
    ) -> MoneyRetro:
        if self.opportunity(opportunity_id) is None:
            raise LookupError("商业机会不存在")
        if actual_hours < 0 or actual_income_fen < 0:
            raise ValueError("实际工时和收入不能为负数")
        if decision not in RETRO_DECISIONS:
            raise ValueError("复盘结论无效")
        first_income = first_income_at.strip()
        if first_income:
            try:
                date.fromisoformat(first_income)
            except ValueError as error:
                raise ValueError("首笔收入日期格式无效") from error
        retro_id = f"retro-{uuid4().hex[:12]}"
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO money_retros(
                id,opportunity_id,actual_hours,actual_income_fen,first_income_at,
                red_flags_seen,blockers,decision,lesson,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    retro_id,
                    opportunity_id,
                    actual_hours,
                    actual_income_fen,
                    first_income,
                    red_flags_seen.strip()[:1500],
                    blockers.strip()[:1500],
                    decision,
                    lesson.strip()[:3000],
                    _now(),
                ),
            )
        return next(item for item in self.retros(opportunity_id) if item.id == retro_id)

    def update_source(
        self,
        source_key: str,
        *,
        status: str,
        current_product: str,
        price_note: str,
        sales_url: str,
        next_action: str,
    ) -> IncomeSource:
        if source_key not in SOURCE_KEYS or self.source(source_key) is None:
            raise LookupError("收入来源不存在")
        if status not in SOURCE_STATUSES:
            raise ValueError("收入来源状态无效")
        sales_url = sales_url.strip()
        if sales_url:
            parsed = urlparse(sales_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("销售链接必须是没有账号信息的 HTTPS 地址")
        with self.connect() as connection:
            connection.execute(
                """UPDATE income_sources SET status=?,current_product=?,price_note=?,
                sales_url=?,next_action=?,updated_at=? WHERE source_key=?""",
                (
                    status,
                    current_product.strip()[:300],
                    price_note.strip()[:120],
                    sales_url[:1000],
                    next_action.strip()[:500],
                    _now(),
                    source_key,
                ),
            )
        return self.source(source_key)  # type: ignore[return-value]

    def entries(self, *, limit: int | None = None) -> tuple[IncomeEntry, ...]:
        query = "SELECT * FROM income_entries ORDER BY occurred_at DESC,created_at DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (max(0, int(limit)),)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(self._entry(row) for row in rows)

    def entry(self, entry_id: str) -> IncomeEntry | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM income_entries WHERE id=?", (entry_id,)
            ).fetchone()
        return self._entry(row) if row else None

    def add_entry(
        self,
        *,
        source_key: str,
        entry_type: str,
        gross_fen: int,
        platform_fee_fen: int = 0,
        occurred_at: str = "",
        note: str = "",
    ) -> IncomeEntry:
        if source_key not in SOURCE_KEYS or self.source(source_key) is None:
            raise ValueError("收入来源无效")
        if entry_type not in ENTRY_TYPES:
            raise ValueError("收支类型无效")
        if gross_fen <= 0 or platform_fee_fen < 0:
            raise ValueError("金额必须大于 0")
        if entry_type != "revenue" and platform_fee_fen:
            raise ValueError("只有收入可以记录平台费用")
        if platform_fee_fen > gross_fen:
            raise ValueError("平台费用不能超过毛收入")
        occurred = occurred_at.strip() or datetime.now(SHANGHAI).date().isoformat()
        try:
            date.fromisoformat(occurred)
        except ValueError as error:
            raise ValueError("发生日期格式无效") from error
        entry_id = f"income-{uuid4().hex[:12]}"
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO income_entries(id,source_key,entry_type,cash_status,
                gross_fen,platform_fee_fen,occurred_at,note,created_at,updated_at)
                VALUES(?,?,?,'pending',?,?,?,?,?,?)""",
                (
                    entry_id,
                    source_key,
                    entry_type,
                    gross_fen,
                    platform_fee_fen,
                    occurred,
                    note.strip()[:1000],
                    now,
                    now,
                ),
            )
        return self.entry(entry_id)  # type: ignore[return-value]

    def confirm_entry(self, entry_id: str) -> IncomeEntry:
        item = self.entry(entry_id)
        if item is None:
            raise LookupError("收支记录不存在")
        if item.cash_status != "pending":
            raise ValueError("只有待确认记录可以确认")
        with self.connect() as connection:
            connection.execute(
                "UPDATE income_entries SET cash_status='confirmed',updated_at=? WHERE id=?",
                (_now(), entry_id),
            )
        return self.entry(entry_id)  # type: ignore[return-value]

    def void_entry(self, entry_id: str) -> IncomeEntry:
        item = self.entry(entry_id)
        if item is None:
            raise LookupError("收支记录不存在")
        if item.cash_status != "pending":
            raise ValueError("只有待确认记录可以作废；已确认错误请另记退款或费用")
        with self.connect() as connection:
            connection.execute(
                "UPDATE income_entries SET cash_status='void',updated_at=? WHERE id=?",
                (_now(), entry_id),
            )
        return self.entry(entry_id)  # type: ignore[return-value]

    def metrics(self) -> IncomeMetrics:
        entries = self.entries()
        current_month = datetime.now(SHANGHAI).strftime("%Y-%m")
        confirmed_revenue = tuple(
            item for item in entries
            if item.entry_type == "revenue" and item.cash_status == "confirmed"
        )
        earned = sum(item.gross_fen - item.platform_fee_fen for item in confirmed_revenue)
        month_earned = sum(
            item.gross_fen - item.platform_fee_fen
            for item in confirmed_revenue
            if item.occurred_at.startswith(current_month)
        )
        pending = sum(
            item.gross_fen - item.platform_fee_fen
            for item in entries
            if item.entry_type == "revenue" and item.cash_status == "pending"
        )
        fees = sum(item.platform_fee_fen for item in confirmed_revenue)
        expenses = sum(
            item.gross_fen for item in entries
            if item.cash_status == "confirmed" and item.entry_type == "expense"
        )
        refunds = sum(
            item.gross_fen for item in entries
            if item.cash_status == "confirmed" and item.entry_type == "refund"
        )
        return IncomeMetrics(
            earned_fen=earned,
            month_earned_fen=month_earned,
            pending_fen=pending,
            deductions_fen=fees + expenses + refunds,
            net_cash_fen=earned - expenses - refunds,
        )

    def source_summaries(self) -> tuple[IncomeSourceSummary, ...]:
        entries = self.entries()
        summaries = []
        for source in self.sources():
            matching = tuple(item for item in entries if item.source_key == source.key)
            summaries.append(
                IncomeSourceSummary(
                    source=source,
                    earned_fen=sum(
                        item.gross_fen - item.platform_fee_fen
                        for item in matching
                        if item.entry_type == "revenue" and item.cash_status == "confirmed"
                    ),
                    pending_fen=sum(
                        item.gross_fen - item.platform_fee_fen
                        for item in matching
                        if item.entry_type == "revenue" and item.cash_status == "pending"
                    ),
                    order_count=sum(
                        item.entry_type == "revenue" and item.cash_status == "confirmed"
                        for item in matching
                    ),
                )
            )
        return tuple(summaries)

    def monthly_trend(self, *, months: int = 12) -> tuple[dict[str, int | str], ...]:
        today = datetime.now(SHANGHAI).date()
        keys = []
        year, month = today.year, today.month
        for offset in range(months - 1, -1, -1):
            absolute = year * 12 + month - 1 - offset
            keys.append(f"{absolute // 12:04d}-{absolute % 12 + 1:02d}")
        totals = {key: 0 for key in keys}
        for item in self.entries():
            key = item.occurred_at[:7]
            if key not in totals or item.cash_status != "confirmed":
                continue
            if item.entry_type == "revenue":
                totals[key] += item.gross_fen - item.platform_fee_fen
            else:
                totals[key] -= item.gross_fen
        maximum = max((abs(value) for value in totals.values()), default=0)
        return tuple(
            {
                "month": key,
                "label": f"{int(key[5:])}月",
                "net_fen": value,
                "height": round(abs(value) / maximum * 100) if maximum else 0,
            }
            for key, value in totals.items()
        )
