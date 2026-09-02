"""Manual-only income dashboard routes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.income import (
    HARD_RED_FLAGS,
    SUSPECT_FLAGS,
    IncomeRepository,
    format_cny,
)
from app.web import TEMPLATES, not_found


router = APIRouter()

PRODUCT_STAGE_LABELS = {
    "package_draft": "制作交付物",
    "store_setup": "配置商品页",
    "traffic_ready": "搭建公开入口",
    "selling": "开始售卖",
    "validating": "验证首单",
    "cleared": "首个 ¥1 已跑通",
    "paused": "暂停",
}
ROLE_STATUS_LABELS = {
    "not_started": "未开始",
    "active": "进行中",
    "blocked": "有阻断",
    "done": "已完成",
}
MONEY_TIER_LABELS = {
    "T0": "零基础",
    "T1": "会用工具",
    "T2": "能独立实现",
    "T3": "可经营与规模化",
}
OPPORTUNITY_STATUS_LABELS = {
    "candidate": "候选",
    "verifying": "核验中",
    "chosen": "已选择",
    "running": "执行中",
    "completed": "已完成",
    "dropped": "已停止",
}
VERDICT_LABELS = {
    "unreviewed": "未核验",
    "suspect": "存疑",
    "viable": "可验证",
    "high_risk": "高风险",
}
CATEGORY_LABELS = {
    "service": "服务",
    "digital_product": "数字产品",
    "subscription": "订阅",
    "micro_saas": "Micro-SaaS",
    "ads_cps": "广告与 CPS",
    "other": "其他",
}
EVIDENCE_KIND_LABELS = {
    "demand": "公开需求",
    "recruiting": "招聘需求",
    "procurement": "采购信号",
    "payment": "真实付款",
    "policy": "政策与规则",
    "complaint": "用户抱怨",
    "official": "官方信息",
}
RETRO_LABELS = {"continue": "继续", "adjust": "调整", "stop": "停止"}


def _repository(request: Request) -> IncomeRepository:
    return request.app.state.income


def _fen(value: str, *, allow_zero: bool = False) -> int:
    try:
        amount = Decimal(value.strip()).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError) as error:
        raise ValueError("请输入有效的人民币金额") from error
    if amount < 0 or (not allow_zero and amount == 0):
        raise ValueError("金额必须大于 0" if not allow_zero else "金额不能为负数")
    return int(amount * 100)


def _count(value: str, label: str) -> int:
    try:
        result = int(value.strip() or "0")
    except ValueError as error:
        raise ValueError(f"{label}必须是整数") from error
    if result < 0:
        raise ValueError(f"{label}不能为负数")
    return result


def _optional_count(value: str, label: str) -> int | None:
    if not value.strip():
        return None
    return _count(value, label)


def _optional_fen(value: str) -> int | None:
    if not value.strip():
        return None
    return _fen(value, allow_zero=True)


def _dashboard_context(
    request: Request, *, notice: str = "", error: str = ""
) -> dict:
    repository = _repository(request)
    product = repository.active_product()
    opportunity = repository.current_opportunity()
    return {
        "active_page": "income",
        "metrics": repository.metrics(),
        "source_summaries": repository.source_summaries(),
        "trend": repository.monthly_trend(),
        "recent_entries": repository.entries(limit=8),
        "product": product,
        "latest_metric": repository.latest_metric(product.id),
        "product_roles": repository.product_roles(product.id),
        "validations": repository.validations(product.id),
        "first_yuan_cleared": repository.first_yuan_cleared(product.id),
        "money_profile": repository.money_profile(),
        "current_opportunity": opportunity,
        "opportunity_verification": (
            repository.verification(opportunity.id) if opportunity else None
        ),
        "money_tier_labels": MONEY_TIER_LABELS,
        "opportunity_status_labels": OPPORTUNITY_STATUS_LABELS,
        "verdict_labels": VERDICT_LABELS,
        "format_cny": format_cny,
        "notice": notice,
        "error": error,
        "status_labels": {
            "not_started": "未开始",
            "preparing": "准备中",
            "selling": "售卖中",
            "paused": "暂停",
        },
        "entry_labels": {
            "revenue": "收入",
            "expense": "费用",
            "refund": "退款",
        },
        "cash_labels": {
            "pending": "待确认",
            "confirmed": "已确认",
            "void": "已作废",
        },
        "product_stage_labels": PRODUCT_STAGE_LABELS,
        "role_status_labels": ROLE_STATUS_LABELS,
    }


def _opportunities_context(
    request: Request,
    *,
    notice: str = "",
    error: str = "",
    form_data: dict | None = None,
) -> dict:
    repository = _repository(request)
    sources = repository.sources()
    return {
        "active_page": "income",
        "profile": repository.money_profile(),
        "opportunities": repository.opportunities(),
        "sources": sources,
        "notice": notice,
        "error": error,
        "form_data": form_data or {},
        "money_tier_labels": MONEY_TIER_LABELS,
        "opportunity_status_labels": OPPORTUNITY_STATUS_LABELS,
        "verdict_labels": VERDICT_LABELS,
        "category_labels": CATEGORY_LABELS,
    }


def _opportunity_context(
    request: Request,
    opportunity_id: str,
    *,
    notice: str = "",
    error: str = "",
) -> dict:
    repository = _repository(request)
    opportunity = repository.opportunity(opportunity_id)
    if opportunity is None:
        raise LookupError("商业机会不存在")
    return {
        "active_page": "income",
        "opportunity": opportunity,
        "evidence": repository.evidence(opportunity_id),
        "verification": repository.verification(opportunity_id),
        "retros": repository.retros(opportunity_id),
        "notice": notice,
        "error": error,
        "format_cny": format_cny,
        "money_tier_labels": MONEY_TIER_LABELS,
        "opportunity_status_labels": OPPORTUNITY_STATUS_LABELS,
        "verdict_labels": VERDICT_LABELS,
        "evidence_kind_labels": EVIDENCE_KIND_LABELS,
        "retro_labels": RETRO_LABELS,
        "hard_red_flags": HARD_RED_FLAGS,
        "suspect_flags": SUSPECT_FLAGS,
    }


def _profile_context(
    request: Request, *, notice: str = "", error: str = ""
) -> dict:
    return {
        "active_page": "income",
        "profile": _repository(request).money_profile(),
        "notice": notice,
        "error": error,
        "money_tier_labels": MONEY_TIER_LABELS,
    }


def _product_context(
    request: Request,
    product_id: str,
    *,
    notice: str = "",
    error: str = "",
) -> dict:
    repository = _repository(request)
    product = repository.product(product_id)
    if product is None:
        raise LookupError("产品不存在")
    return {
        "active_page": "income",
        "product": product,
        "latest_metric": repository.latest_metric(product.id),
        "product_roles": repository.product_roles(product.id),
        "validations": repository.validations(product.id),
        "revenue_entries": tuple(
            item
            for item in repository.entries()
            if item.source_key == product.source_key
            and item.entry_type == "revenue"
            and item.cash_status != "void"
        ),
        "first_yuan_cleared": repository.first_yuan_cleared(product.id),
        "format_cny": format_cny,
        "product_stage_labels": PRODUCT_STAGE_LABELS,
        "role_status_labels": ROLE_STATUS_LABELS,
        "notice": notice,
        "error": error,
    }


def _entries_context(
    request: Request, *, notice: str = "", error: str = "", form_data: dict | None = None
) -> dict:
    repository = _repository(request)
    sources = repository.sources()
    return {
        "active_page": "income",
        "sources": sources,
        "entries": repository.entries(),
        "format_cny": format_cny,
        "notice": notice,
        "error": error,
        "form_data": form_data or {},
        "source_lookup": {item.key: item for item in sources},
        "entry_labels": {
            "revenue": "收入",
            "expense": "费用",
            "refund": "退款",
        },
        "cash_labels": {
            "pending": "待确认",
            "confirmed": "已确认",
            "void": "已作废",
        },
    }


@router.get("/income", response_class=HTMLResponse, name="income")
async def income(request: Request, saved: str = "") -> HTMLResponse:
    notice = {
        "source": "收入来源已更新。",
        "entry": "收支记录已保存，确认前不会进入实际到账。",
        "confirmed": "收支记录已确认。",
        "void": "待确认记录已作废。",
        "product": "Money Engine 产品状态已更新。",
        "metric": "漏斗快照已记录。",
        "validation": "首单验证状态已更新。",
        "role": "收入职责已更新。",
        "profile": "赚钱画像已更新。",
        "opportunity": "候选机会已保存。",
    }.get(saved, "")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="income.html",
        context=_dashboard_context(request, notice=notice),
    )


@router.get("/income/profile", response_class=HTMLResponse, name="income_profile")
async def income_profile(request: Request, saved: str = "") -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="income_profile.html",
        context=_profile_context(
            request, notice="赚钱画像已更新。" if saved == "profile" else ""
        ),
    )


@router.post("/income/profile", name="update_income_profile")
async def update_income_profile(
    request: Request,
    tier: str = Form(...),
    tier_reason: str = Form(default=""),
    skills: str = Form(default=""),
    weekly_hours: str = Form(default=""),
    startup_capital: str = Form(default="0"),
    region: str = Form(default=""),
    languages: str = Form(default=""),
    can_show_face: str = Form(default="unknown"),
    goal: str = Form(...),
    willing_to_learn: bool = Form(default=False),
) -> HTMLResponse:
    try:
        _repository(request).update_money_profile(
            tier=tier,
            tier_reason=tier_reason,
            skills=skills,
            weekly_hours=_optional_count(weekly_hours, "每周可投入时间"),
            startup_capital_fen=_fen(startup_capital or "0", allow_zero=True),
            region=region,
            languages=languages,
            can_show_face=can_show_face,
            goal=goal,
            willing_to_learn=willing_to_learn,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_profile.html",
            context=_profile_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_profile").include_query_params(saved="profile"),
        status_code=303,
    )


@router.get(
    "/income/opportunities",
    response_class=HTMLResponse,
    name="income_opportunities",
)
async def income_opportunities(request: Request, saved: str = "") -> HTMLResponse:
    notice = "候选机会已保存，先补真实需求证据。" if saved == "opportunity" else ""
    return TEMPLATES.TemplateResponse(
        request=request,
        name="income_opportunities.html",
        context=_opportunities_context(request, notice=notice),
    )


@router.post("/income/opportunities", name="create_income_opportunity")
async def create_income_opportunity(
    request: Request,
    name: str = Form(...),
    source_key: str = Form(...),
    category: str = Form(...),
    target_customer: str = Form(...),
    for_tier: str = Form(...),
    money_flow: str = Form(...),
    signal_summary: str = Form(default=""),
) -> HTMLResponse:
    form_data = {
        "name": name,
        "source_key": source_key,
        "category": category,
        "target_customer": target_customer,
        "for_tier": for_tier,
        "money_flow": money_flow,
        "signal_summary": signal_summary,
    }
    try:
        _repository(request).create_opportunity(**form_data)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_opportunities.html",
            context=_opportunities_context(
                request, error=str(error), form_data=form_data
            ),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_opportunities").include_query_params(
            saved="opportunity"
        ),
        status_code=303,
    )


@router.get(
    "/income/opportunities/{opportunity_id}",
    response_class=HTMLResponse,
    name="income_opportunity",
)
async def income_opportunity(
    request: Request, opportunity_id: str, saved: str = ""
) -> HTMLResponse:
    notice = {
        "evidence": "公开证据已记录。",
        "verification": "需求与反诈结论已更新。",
        "plan": "最小验证预测已冻结。",
        "retro": "实际结果与复盘已记录。",
    }.get(saved, "")
    try:
        context = _opportunity_context(request, opportunity_id, notice=notice)
    except LookupError:
        return not_found(request, "income")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="income_opportunity.html",
        context=context,
    )


@router.post(
    "/income/opportunities/{opportunity_id}/evidence",
    name="create_income_evidence",
)
async def create_income_evidence(
    request: Request,
    opportunity_id: str,
    source_url: str = Form(...),
    source_title: str = Form(...),
    source_kind: str = Form(...),
    published_at: str = Form(default=""),
    checked_at: str = Form(default=""),
    note: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).add_evidence(
            opportunity_id,
            source_url=source_url,
            source_title=source_title,
            source_kind=source_kind,
            published_at=published_at,
            checked_at=checked_at,
            note=note,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_opportunity.html",
            context=_opportunity_context(request, opportunity_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for(
            "income_opportunity", opportunity_id=opportunity_id
        ).include_query_params(saved="evidence"),
        status_code=303,
    )


@router.post(
    "/income/opportunities/{opportunity_id}/verification",
    name="update_income_opportunity_verification",
)
async def update_income_opportunity_verification(
    request: Request,
    opportunity_id: str,
    status: str = Form(...),
    verdict: str = Form(...),
    hard_flags: list[str] = Form(default=[]),
    suspect_flags: list[str] = Form(default=[]),
    money_flow: str = Form(...),
    signal_summary: str = Form(default=""),
    freshness_note: str = Form(default=""),
    cross_check: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).update_opportunity_verification(
            opportunity_id,
            status=status,
            verdict=verdict,
            hard_flags=tuple(hard_flags),
            suspect_flags=tuple(suspect_flags),
            money_flow=money_flow,
            signal_summary=signal_summary,
            freshness_note=freshness_note,
            cross_check=cross_check,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_opportunity.html",
            context=_opportunity_context(request, opportunity_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for(
            "income_opportunity", opportunity_id=opportunity_id
        ).include_query_params(saved="verification"),
        status_code=303,
    )


@router.post(
    "/income/opportunities/{opportunity_id}/plan",
    name="update_income_opportunity_plan",
)
async def update_income_opportunity_plan(
    request: Request,
    opportunity_id: str,
    validation_step: str = Form(...),
    two_week_plan: str = Form(default=""),
    income_expectation: str = Form(default=""),
    stop_loss: str = Form(...),
    ai_leverage: str = Form(default=""),
    predicted_hours: str = Form(default=""),
    predicted_first_income_days: str = Form(default=""),
    predicted_min: str = Form(default=""),
    predicted_max: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).update_opportunity_plan(
            opportunity_id,
            validation_step=validation_step,
            two_week_plan=two_week_plan,
            income_expectation=income_expectation,
            stop_loss=stop_loss,
            ai_leverage=ai_leverage,
            predicted_hours=_optional_count(predicted_hours, "预计工时"),
            predicted_first_income_days=_optional_count(
                predicted_first_income_days, "预计首笔收入天数"
            ),
            predicted_min_fen=_optional_fen(predicted_min),
            predicted_max_fen=_optional_fen(predicted_max),
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_opportunity.html",
            context=_opportunity_context(request, opportunity_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for(
            "income_opportunity", opportunity_id=opportunity_id
        ).include_query_params(saved="plan"),
        status_code=303,
    )


@router.post(
    "/income/opportunities/{opportunity_id}/retro",
    name="create_income_opportunity_retro",
)
async def create_income_opportunity_retro(
    request: Request,
    opportunity_id: str,
    actual_hours: str = Form(default="0"),
    actual_income: str = Form(default="0"),
    first_income_at: str = Form(default=""),
    red_flags_seen: str = Form(default=""),
    blockers: str = Form(default=""),
    decision: str = Form(...),
    lesson: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).add_retro(
            opportunity_id,
            actual_hours=_count(actual_hours, "实际工时"),
            actual_income_fen=_fen(actual_income or "0", allow_zero=True),
            first_income_at=first_income_at,
            red_flags_seen=red_flags_seen,
            blockers=blockers,
            decision=decision,
            lesson=lesson,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_opportunity.html",
            context=_opportunity_context(request, opportunity_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for(
            "income_opportunity", opportunity_id=opportunity_id
        ).include_query_params(saved="retro"),
        status_code=303,
    )


@router.get(
    "/income/products/{product_id}",
    response_class=HTMLResponse,
    name="income_product",
)
async def income_product(
    request: Request, product_id: str, saved: str = ""
) -> HTMLResponse:
    notice = {
        "product": "产品状态已更新。",
        "metric": "漏斗快照已记录。",
        "validation": "首单验证状态已更新。",
        "role": "收入职责已更新。",
    }.get(saved, "")
    try:
        context = _product_context(request, product_id, notice=notice)
    except LookupError:
        return not_found(request, "income")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="income_product.html",
        context=context,
    )


@router.post("/income/products/{product_id}", name="update_income_product")
async def update_income_product(
    request: Request,
    product_id: str,
    package_version: str = Form(...),
    current_stage: str = Form(...),
    github_url: str = Form(default=""),
    article_url: str = Form(default=""),
    store_url: str = Form(default=""),
    next_action: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).update_product(
            product_id,
            package_version=package_version,
            current_stage=current_stage,
            github_url=github_url,
            article_url=article_url,
            store_url=store_url,
            next_action=next_action,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_product.html",
            context=_product_context(request, product_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_product", product_id=product_id).include_query_params(
            saved="product"
        ),
        status_code=303,
    )


@router.post(
    "/income/products/{product_id}/metrics",
    name="create_product_metric",
)
async def create_product_metric(
    request: Request,
    product_id: str,
    observed_at: str = Form(default=""),
    impressions: str = Form(default="0"),
    store_clicks: str = Form(default="0"),
    paid_orders: str = Form(default="0"),
    delivered_orders: str = Form(default="0"),
    refunds: str = Form(default="0"),
) -> HTMLResponse:
    try:
        _repository(request).add_metric_snapshot(
            product_id,
            observed_at=observed_at,
            impressions=_count(impressions, "展示量"),
            store_clicks=_count(store_clicks, "商品点击"),
            paid_orders=_count(paid_orders, "付款订单"),
            delivered_orders=_count(delivered_orders, "自动交付"),
            refunds=_count(refunds, "退款"),
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_product.html",
            context=_product_context(request, product_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_product", product_id=product_id).include_query_params(
            saved="metric"
        ),
        status_code=303,
    )


@router.post(
    "/income/products/{product_id}/validation",
    name="update_revenue_validation",
)
async def update_revenue_validation(
    request: Request,
    product_id: str,
    income_entry_id: str = Form(...),
    unfamiliar_buyer: bool = Form(default=False),
    no_direct_sales: bool = Form(default=False),
    third_party_payment: bool = Form(default=False),
    automatic_delivery: bool = Form(default=False),
    refund_window_ended: bool = Form(default=False),
    no_refund: bool = Form(default=False),
) -> HTMLResponse:
    try:
        _repository(request).record_validation(
            product_id,
            income_entry_id=income_entry_id,
            unfamiliar_buyer=unfamiliar_buyer,
            no_direct_sales=no_direct_sales,
            third_party_payment=third_party_payment,
            automatic_delivery=automatic_delivery,
            refund_window_ended=refund_window_ended,
            no_refund=no_refund,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_product.html",
            context=_product_context(request, product_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_product", product_id=product_id).include_query_params(
            saved="validation"
        ),
        status_code=303,
    )


@router.post(
    "/income/products/{product_id}/roles/{role_key}",
    name="update_revenue_role",
)
async def update_revenue_role(
    request: Request,
    product_id: str,
    role_key: str,
    status: str = Form(...),
    observable_result: str = Form(default=""),
    next_action: str = Form(default=""),
    requires_confirmation: bool = Form(default=False),
) -> HTMLResponse:
    try:
        _repository(request).update_role(
            product_id,
            role_key,
            status=status,
            observable_result=observable_result,
            next_action=next_action,
            requires_confirmation=requires_confirmation,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_product.html",
            context=_product_context(request, product_id, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_product", product_id=product_id).include_query_params(
            saved="role"
        ),
        status_code=303,
    )


@router.get("/income/entries", response_class=HTMLResponse, name="income_entries")
async def income_entries(request: Request, saved: str = "") -> HTMLResponse:
    notice = {
        "entry": "收支记录已保存，确认后才进入实际数据。",
        "confirmed": "收支记录已确认。",
        "void": "待确认记录已作废。",
    }.get(saved, "")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="income_entries.html",
        context=_entries_context(request, notice=notice),
    )


@router.post("/income/entries", name="create_income_entry")
async def create_income_entry(
    request: Request,
    source_key: str = Form(...),
    entry_type: str = Form(...),
    gross: str = Form(...),
    platform_fee: str = Form(default="0"),
    occurred_at: str = Form(default=""),
    note: str = Form(default=""),
) -> HTMLResponse:
    form_data = {
        "source_key": source_key,
        "entry_type": entry_type,
        "gross": gross,
        "platform_fee": platform_fee,
        "occurred_at": occurred_at,
        "note": note,
    }
    try:
        _repository(request).add_entry(
            source_key=source_key,
            entry_type=entry_type,
            gross_fen=_fen(gross),
            platform_fee_fen=_fen(platform_fee or "0", allow_zero=True),
            occurred_at=occurred_at,
            note=note,
        )
    except (LookupError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_entries.html",
            context=_entries_context(request, error=str(error), form_data=form_data),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_entries").include_query_params(saved="entry"),
        status_code=303,
    )


@router.post("/income/entries/{entry_id}/confirm", name="confirm_income_entry")
async def confirm_income_entry(request: Request, entry_id: str) -> HTMLResponse:
    try:
        _repository(request).confirm_entry(entry_id)
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_entries.html",
            context=_entries_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_entries").include_query_params(saved="confirmed"),
        status_code=303,
    )


@router.post("/income/entries/{entry_id}/void", name="void_income_entry")
async def void_income_entry(request: Request, entry_id: str) -> HTMLResponse:
    try:
        _repository(request).void_entry(entry_id)
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income_entries.html",
            context=_entries_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income_entries").include_query_params(saved="void"),
        status_code=303,
    )


@router.post("/income/sources/{source_key}", name="update_income_source")
async def update_income_source(
    request: Request,
    source_key: str,
    status: str = Form(...),
    current_product: str = Form(default=""),
    price_note: str = Form(default=""),
    sales_url: str = Form(default=""),
    next_action: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).update_source(
            source_key,
            status=status,
            current_product=current_product,
            price_note=price_note,
            sales_url=sales_url,
            next_action=next_action,
        )
    except LookupError:
        return not_found(request, "income")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="income.html",
            context=_dashboard_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("income").include_query_params(saved="source"),
        status_code=303,
    )
