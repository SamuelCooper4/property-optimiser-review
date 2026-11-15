"""Bounded local introduction adapter over the shared illustrative provider.

No mortgage or growth formulas are implemented here. Source-scene presentation
fields are derived from model.project and the owner-approved shared example.
"""
from __future__ import annotations

import json
from dataclasses import fields, replace
from decimal import Decimal as D, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

import model as m

EXAMPLE = json.loads(Path(__file__).with_name('example.json').read_text(encoding='utf-8'))
VERSION = 'bp-local-intro-adapter-2026-11-14-clarity'
EXAMPLE_DEPOSITS = (D('67500'), D('90000'))
GROWTH_SETTINGS = (D('.08'), D('.03'))
LESSON_RATE = D('.05')
DEFAULT_DEPOSIT = D('67500')
CHART_MAX_GBP = D('400000')
TERM_YEARS = EXAMPLE['term_years']
OBJECTIVE_MONTH = EXAMPLE['objective_month']
# Addressing resolution for the prepared chart, not a financial approximation.
CHART_DEPOSIT_STEP_GBP = D('10')


@m.fixed
def educational_point(deposit: D) -> list:
    """Return actual opening facts, even where the later budget cannot fund them."""
    plan = m.project(example_inputs(GROWTH_SETTINGS[0]), deposit, TERM_YEARS, through_month=1)
    p = m.present(plan)
    row = p['rows'][1]
    return [format(deposit, 'f'), *[p[k] for k in ('opening_debt', 'opening_investment', 'rate', 'ltv', 'first_payment')],
            *[row[k] for k in ('surplus', 'invest_add', 'cash_add', 'overpay', 'spend', 'redirect_reason', 'fallback_add')],
            p['ltv_label'], *interest_facts(deposit).values(), plan['valid']]


@lru_cache(maxsize=1)
@m.fixed
def education_response() -> dict:
    """Prepare the 10%-deposit borrowing lesson independently of affordability."""
    i = example_inputs(GROWTH_SETTINGS[0])
    low = i.price * (1 - i.bands[-1][0])
    high = i.total - i.reserve - i.costs
    minimum = minimum_deposit(i)
    edges = {i.price * (1 - bound) for bound, _ in i.bands}
    deposits = {D(n) for n in range(int(low), int(high) + 1)}
    deposits.update(edge + penny for edge in edges | {minimum, high}
                    for penny in (-m.PENNY, m.ZERO, m.PENNY) if low <= edge + penny <= high)
    return dict(status='ok', version=VERSION, low=str(low), high=str(high), step='1',
                points=[educational_point(d) for d in sorted(deposits)],
                edges=[str(e) for e in sorted(edges) if low < e < high], segments=[],
                minimum_affordable_deposit=str(minimum))


@lru_cache(maxsize=1)
@m.fixed
def prepared_comparison() -> dict:
    """Cache directly projected monthly paths; the browser selects, never interpolates.

    A GBP10 pointer grid is subpixel at the intended slider width. Exact funded
    endpoints, rate-edge pennies and arbitrary exact-entry requests remain exact.
    Both growth cases use the same stable, explicitly nonzero chart scale.
    """
    i = example_inputs(GROWTH_SETTINGS[0])
    low, high = minimum_deposit(i), EXAMPLE_DEPOSITS[-1]
    deposits = {low, high, *EXAMPLE_DEPOSITS}
    deposits.update(D(n) * CHART_DEPOSIT_STEP_GBP for n in range(
        int((low / CHART_DEPOSIT_STEP_GBP).to_integral_value(rounding=ROUND_CEILING)),
        int(high / CHART_DEPOSIT_STEP_GBP) + 1))
    for bound, _ in i.bands:
        edge = i.price * (1 - bound)
        deposits.update(edge + p for p in (-m.PENNY, m.ZERO, m.PENNY) if low <= edge + p <= high)
    cases = {}
    for growth in GROWTH_SETTINGS:
        inputs = example_inputs(growth)
        reference = m.project(inputs, high, TERM_YEARS, through_month=OBJECTIVE_MONTH)
        entries = []
        for deposit in sorted(deposits):
            plan = m.project(inputs, deposit, TERM_YEARS, through_month=OBJECTIVE_MONTH)
            entries.append(dict(deposit=str(deposit), positions=[m.money(row['position']) for row in plan['rows']],
                                comparison=m.comparison_display(plan, reference, OBJECTIVE_MONTH)))
        cases[str(growth)] = entries
    return dict(status='ok', version=VERSION, cases=cases, step=str(CHART_DEPOSIT_STEP_GBP))


@m.fixed
def percentage(value: D) -> str:
    """Format a decimal fraction as a concise percentage for existing labels."""
    result = format(value * 100, 'f')
    return (result.rstrip('0').rstrip('.') if '.' in result else result) + '%'


@lru_cache(maxsize=2)
def example_inputs(growth: D) -> m.Inputs:
    """Read the shared fixture without mutating the dashboard's historical defaults."""
    return m.parse({**EXAMPLE['inputs'], 'investment_return': str(growth)})


@lru_cache(maxsize=2)
@m.fixed
def minimum_deposit(i: m.Inputs) -> D:
    """Return the first whole-pound funded selection for the introduction slider."""
    minimum = min(low for low, _, _ in m.regions(i, TERM_YEARS))
    return minimum


@lru_cache(maxsize=128)
@m.fixed
def funded_rate_reference(i: m.Inputs, deposit: D, rate: D) -> dict:
    """Project a fully serviced rate-only lesson; monthly investment is irrelevant."""
    required = m.repayment(i.price - deposit, rate, TERM_YEARS * 12)
    return m.project(replace(i, bands=((D(1), rate),), monthly=max(i.monthly, required)), deposit, TERM_YEARS)


@m.fixed
def interest_facts(deposit: D, lesson_rate: D | None = None) -> dict:
    """Prepare GBP lifetime interest for the fixed, fully repaid 30-year fixture.

    Total contractual payments less principal equals interest. Use the existing
    Decimal repayment authority, never rounded monthly payments. This shortcut is
    confined to this zero-fee, fixed-rate fixture, and tested against all 360 rows.
    """
    i = example_inputs(GROWTH_SETTINGS[0])
    principal = i.price - deposit
    rate = m.rate_for(i, deposit, TERM_YEARS)
    months = TERM_YEARS * 12
    lesson_rate = i.bands[-1][1] if lesson_rate is None else lesson_rate
    return dict(interest=m.money(m.repayment(principal, rate, months) * months - principal),
                lesson_interest=m.money(m.repayment(principal, lesson_rate, months) * months - principal))


@lru_cache(maxsize=1)
@m.fixed
def opening_response() -> dict:
    """Add independently prepared interest to immutable opening lookup copies."""
    lookup = m.opening_lookup(example_inputs(GROWTH_SETTINGS[0]), TERM_YEARS)
    return {**lookup, 'points': [row + list(interest_facts(D(row[0])).values()) for row in lookup['points']]}


@m.fixed
def scene_plan(i: m.Inputs, plan: dict) -> dict:
    """Adapt a projected opening choice to the preserved StoryScene plan contract."""
    deposit = plan['deposit']; debt = plan['opening_debt']; rate = plan['rate']
    investment = plan['opening_investment']; payment = plan['first_payment']
    cash = plan['rows'][0]['cash']; ltv = plan['ltv']
    available = i.total - i.reserve - i.costs
    interest = plan['rows'][TERM_YEARS * 12]['interest_total']
    index = next(n for n, (bound, _) in enumerate(i.bands) if ltv <= bound)
    old_rate = i.bands[min(index + 1, len(i.bands) - 1)][1]
    old_interest = funded_rate_reference(i, deposit, old_rate)['rows'][TERM_YEARS * 12]['interest_total']
    baseline_interest = funded_rate_reference(i, deposit, i.bands[-1][1])['rows'][TERM_YEARS * 12]['interest_total']
    first = plan['rows'][1]; displayed_first = m.present(plan)['rows'][1]
    ltv_rounded = ltv.quantize(D('.001'), rounding=ROUND_HALF_UP)
    ltv_text = ('>' if any(ltv_rounded == b and ltv > b for b, _ in i.bands) else '') + percentage(ltv_rounded)
    return dict(
        deposit_exact=str(deposit), debt_exact=str(debt), investment_exact=str(investment), cash_exact=str(cash),
        deposit=m.money(deposit), debt=m.money(debt), retained=m.money(available - deposit),
        lesson_interest=interest_facts(deposit)['lesson_interest'],
        outside_at_purchase=m.money(cash + investment), investment=m.money(investment), cash=m.money(cash),
        rate=str(rate), rate_label=percentage(rate), ltv=str(ltv), ltv_label=ltv_text, ltv_exact_label=percentage(ltv),
        affordable=plan['valid'], payment=m.money(payment), payment_exact=str(payment),
        contribution=displayed_first['invest_add'], contribution_exact=str(first['invest_add']),
        next_threshold=int(next((i.price * (1 - b) for b, _ in reversed(i.bands) if i.price * (1 - b) > deposit), available)),
        rate_comparison=dict(principal=m.money(debt), term_months=TERM_YEARS * 12,
                             old_rate=str(old_rate), old_rate_label=percentage(old_rate),
                             old_interest=m.money(old_interest), new_interest=m.money(interest), saving=m.money(old_interest - interest)),
        reserve=m.money(i.reserve),
        first_payment=dict(interest=m.money(first['interest_total']),
                           principal=m.money(D(m.money(payment)) - D(m.money(first['interest_total']))),
                           interest_fraction=str(first['interest_total'] / payment)),
        interest=m.money(interest), baseline_interest=m.money(baseline_interest),
        deposit_fraction=str(deposit / i.price), retained_fraction=str((available - deposit) / available),
        payment_fraction=str(payment / i.monthly), interest_fraction=str(interest / baseline_interest),
        max_investment=int(available - deposit))


@m.fixed
def scene_rows(plan: dict) -> list[dict]:
    """Preserve provider rows and add names used by the local introduction chart."""
    result = m.present(plan)['rows'][:OBJECTIVE_MONTH + 1]
    for raw, row in zip(plan['rows'], result):
        row.update(net_position=row['position'], net_exact=str(raw['position']),
                   investment_value=row['investment'], cash_value=row['cash'],
                   contribution_month=row['invest_add'], contribution_exact=str(raw['invest_add']),
                   payment_exact=str(raw['payment']), contributions=row['contributed'],
                   interest_paid=row['interest_total'], outside_total=m.money(raw['cash'] + raw['investment']))
    result[0].update(opening_value=result[0]['investment'], later_value='0.00')
    return result


@lru_cache(maxsize=2)
@m.fixed
def comparison_examples(growth: D) -> list[dict]:
    """Reuse the two fixed reference trajectories; request serialization is read-only."""
    i = example_inputs(growth)
    return [dict(deposit=m.money(amount), plan=scene_plan(i, plan), rows=scene_rows(plan))
            for amount in EXAMPLE_DEPOSITS
            for plan in [m.project(i, amount, TERM_YEARS)]]


@lru_cache(maxsize=128)
@m.fixed
def build_response(growth: D, deposit: D) -> dict:
    """Build one scene and three common-date comparisons from existing projections."""
    i = example_inputs(growth)
    plan = m.project(i, deposit, TERM_YEARS)
    if not plan['valid']:
        return dict(status='infeasible', issues=plan['issues'] or ['This deposit exceeds the monthly budget.'])
    fixed = m.project(replace(i, bands=((D(1), LESSON_RATE),)), deposit, TERM_YEARS)
    # The interest graphic's upper bound is the source 90%-LTV/6% loan,
    # fully serviced rather than silently capped by the household budget.
    scale_plan = funded_rate_reference(i, i.price * (1 - i.bands[-1][0]), i.bands[-1][1])
    data = dict(status='ok', version=VERSION, facts_version=m.VERSION,
                interest_scale_gbp=m.money(scale_plan['rows'][TERM_YEARS * 12]['interest_total']),
                scale_gbp=m.money(CHART_MAX_GBP), graph_scale_gbp=m.money(CHART_MAX_GBP),
                pricing_bands=[dict(threshold=int(i.price * (1 - b)), ltv=percentage(b), rate=str(r), label=percentage(r)) for b, r in reversed(i.bands)],
                minimum_affordable_deposit=m.money(minimum_deposit(i)), minimum_display=m.money(minimum_deposit(i).to_integral_value(rounding=ROUND_CEILING)),
                budget_gbp=m.money(i.monthly), budget_exact=str(i.monthly),
                teaching=dict(deposit=int(DEFAULT_DEPOSIT), investment=int(i.total - i.reserve - i.costs - DEFAULT_DEPOSIT), version=EXAMPLE['version']),
                effective_from=i.as_of, plan=scene_plan(i, plan), fixed_rate_plan=scene_plan(i, fixed),
                total_resources=m.money(i.total), available_resources=m.money(i.total - i.reserve - i.costs),
                reserve_gbp=m.money(i.reserve), ledger=m.serial(plan['ledger']),
                excluded_sources=dict(lisa='0.00', home_equity='0.00'), issues=[], rows=scene_rows(plan))
    examples = comparison_examples(growth)
    return dict(status='ok', version=VERSION, data=data, examples=examples,
                comparison=m.comparison_display(plan, m.project(i, EXAMPLE_DEPOSITS[-1], TERM_YEARS), OBJECTIVE_MONTH),
                chart=dict(min_gbp='0.00', max_gbp=m.money(CHART_MAX_GBP), max_month=OBJECTIVE_MONTH),
                assumptions=dict(example_version=EXAMPLE['version'], source=EXAMPLE['source'], model_version=m.VERSION,
                                 inputs=m.serial({f.name:getattr(i, f.name) for f in fields(i)}),
                                 term_years=TERM_YEARS, objective_month=OBJECTIVE_MONTH,
                                 cost_convention=EXAMPLE['cost_convention'], continuation_convention=EXAMPLE['continuation_convention'],
                                 exclusions=['Purchase costs', 'Product fees', 'Investment fees and tax', 'Inflation'],
                                 growth_convention='Annual compound equity investment growth with reinvested dividends; illustrative, not guaranteed.'))


@m.fixed
def respond(request: dict) -> dict:
    """Validate a bounded growth/deposit request and preserve expected input errors."""
    try:
        if not isinstance(request, dict):
            raise ValueError('The example request must be an object.')
        if request.get('operation') == 'compatible':
            from compatible_intro import respond as compatible_response
            return compatible_response(request)
        if request.get('operation') == 'opening':
            return opening_response()
        if request.get('operation') == 'education':
            return education_response()
        if request.get('operation') == 'comparison-cache':
            return prepared_comparison()
        if request.get('operation') == 'opening-choice':
            deposit = D(str(request.get('deposit')))
            if not deposit.is_finite() or deposit != deposit.quantize(m.PENNY) or not D('45000') <= deposit <= EXAMPLE_DEPOSITS[-1]:
                raise ValueError('Choose a deposit from £45,000 to £90,000 in pounds and pence.')
            return dict(status='ok', point=educational_point(deposit))
        growth = D(str(request.get('growth', '0.08')))
        if not growth.is_finite() or growth not in GROWTH_SETTINGS:
            raise ValueError('Choose investment growth of 8% or 3%.')
        raw = request.get('deposit', DEFAULT_DEPOSIT)
        i = example_inputs(growth)
        deposit = minimum_deposit(i) if raw == 'minimum' else D(str(raw))
        if not deposit.is_finite() or deposit != deposit.quantize(m.PENNY):
            raise ValueError('Use a finite deposit in pounds and pence.')
        if not minimum_deposit(i) <= deposit <= EXAMPLE_DEPOSITS[-1]:
            raise ValueError('Choose a deposit within the funded example range.')
        return build_response(growth, deposit)
    except (ValueError, TypeError, InvalidOperation, KeyError, OverflowError) as exc:
        return dict(status='invalid', version=VERSION, issues=[str(exc) or 'Check the example inputs.'])
