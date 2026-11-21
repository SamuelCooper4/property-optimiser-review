"""Phone reporting for the isolated illustrative model. Money is GBP.

The search uses the dashboard's finite deposit grid and its full-horizon funding
test. Only the exact explored penny is added to that grid. No interpolation,
annual-return shortcut, or alternative mortgage recurrence is used for ranking.
"""
from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal as D, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

import model as m
from quotes import coverage


VERSION = 'bp-phone-provider-2026-11-21-v2'
FIXTURE = json.loads(Path(__file__).with_name('phone-fixture.json').read_text(encoding='utf-8-sig'))
DATES = (24, 60, 120, 240, 420)
QUOTE = 'quotes'
ZERO = m.ZERO
PENNY = m.PENNY
POUND = D(1)


def _inputs(raw: dict) -> m.Inputs:
    inputs = m.parse({**FIXTURE['inputs'], **raw})
    if inputs.deals or inputs.stress_month:
        raise ValueError('The phone example holds the opening rate and house value constant.')
    if inputs.bands != tuple((D(a), D(b)) for a, b in FIXTURE['inputs']['bands']):
        raise ValueError('Use the dated opening-rate fixture or exact synthetic quotes.')
    if any(q.scope != 'exact' for q in inputs.quotes):
        raise ValueError('Enter each synthetic quote with its exact deposit, term and price.')
    if inputs.pricing_mode == QUOTE and len(inputs.quotes) == 1:
        inputs = replace(inputs, quote_id=inputs.quotes[0].id)
    quote = m.active_quote(inputs)
    if quote and quote.rate is not None:
        # The fixed period governs the known allowance. Beyond it, the example
        # assumes the opening rate continues and uses the future allowance.
        inputs = replace(inputs, continuation=quote.rate)
    return inputs


def _source(i: m.Inputs) -> dict:
    if i.pricing_mode == QUOTE:
        if len(i.quotes) > 1:
            return dict(kind='quote', name='Your quotes', count=len(i.quotes), date='', fixed_months=None)
        quote = m.active_quote(i)
        return dict(kind='quote', name=(quote.name or 'Synthetic quote') if quote else 'Your quotes',
                    quote_id=quote.id if quote else None, date=quote.obtained if quote else '',
                    fixed_months=quote.fixed_months if quote else None)
    return FIXTURE['source'].copy()


def _bounds(i: m.Inputs) -> tuple[D, D]:
    return i.lisa+i.gift, min(i.total-i.reserve-i.costs, i.price)


@lru_cache(maxsize=256)
def _regions(i: m.Inputs, term: int, month: int) -> tuple:
    """Full-horizon funded inclusive penny ranges in one repayment term."""
    if i.pricing_mode == QUOTE and len(i.quotes) > 1:
        regions = tuple((dep, dep, plan['rate']) for dep in _quote_deposits(i, term)
                        if (plan := _plan(i, term, dep, month))['status'] == 'funded')
    else:
        regions = m.regions(i, term, penny_edges=True)
    # A cash purchase uses no quoted mortgage, even when evidence for loans is sparse.
    if i.pricing_mode == QUOTE and _bounds(i)[1] == i.price and not i.lisa:
        loans = (region for region in regions if region[0] < i.price)
        return (*loans, (i.price, i.price, ZERO))
    return regions


def _quote_deposits(i: m.Inputs, term: int) -> list[D]:
    return sorted({q.deposit for q in i.quotes if q.price == i.price and q.term_years == term
                   and q.deposit is not None and q.deposit < i.price})


@lru_cache(maxsize=64)
def _market_bands(i: m.Inputs) -> tuple:
    bands = []
    upper = i.price-PENNY
    for ltv, rate in i.bands:
        low = (i.price*(1-ltv)).quantize(PENNY, rounding=ROUND_CEILING)
        bands.append(dict(low=low, high=upper, max_ltv=ltv, rate=rate, deposit_share=1-ltv))
        upper = low-PENNY
    return tuple(reversed(bands))


def _bands(i: m.Inputs, term: int, regions: tuple, month: int) -> list:
    if i.pricing_mode == QUOTE:
        bands = []
        for dep in _quote_deposits(i, term):
            plan = _plan(i, term, dep, month)
            if plan['rate'] is not None:
                bands.append(dict(low=dep, high=dep, rate=plan['rate'], reachable=plan['status']=='funded',
                                  deposit_share=dep/i.price, max_ltv=(i.price-dep)/i.price))
        return bands
    return [dict(band, reachable=any(max(a, band['low']) <= min(b, band['high']) for a,b,_ in regions))
            for band in _market_bands(i)]


def _unpriced(i: m.Inputs, deposit: D, term: int, issues: list) -> tuple[str,str]:
    low, high = _bounds(i)
    if not low <= deposit <= high or deposit == i.price and i.lisa:
        return 'unavailable', issues[0]
    if i.pricing_mode == QUOTE:
        state, reason = coverage(m.active_quote(i), i.price, deposit, term, i.as_of)
        if state != 'supplied':
            return 'unknown', reason
    if m.rate_for(i, deposit, term) is None:
        return 'unknown', 'No dated fixture rate covers this deposit.'
    return 'unavailable', ' '.join(issues)


def _monthly(i: m.Inputs, first: dict, fallback_destination: str) -> dict:
    """Opening monthly cash flows plus reconciled display pounds for planned and applied uses."""
    actual = dict(investment=first['invest_add'], cash=first['cash_add'],
                  overpay=first['overpay'], spend=first['spend'])
    budget = i.monthly.quantize(POUND, rounding=ROUND_HALF_UP)
    payment = first['payment'].quantize(POUND, rounding=ROUND_HALF_UP)
    surplus = budget - payment
    displayed = m.display_split(actual, surplus, POUND)
    if first['fallback_add']:
        # Undo the redirect already booked in the ledger to show the buyer's request.
        requested = {**actual, 'overpay':first['requested_overpay']}
        requested[fallback_destination] -= first['fallback_add']
        requested_display = m.display_split(requested, surplus, POUND)
    else:
        requested_display = displayed.copy()
    display = dict(budget=budget, payment=payment, surplus=surplus, requested=requested_display,
                   fallback=D(requested_display['overpay'])-D(displayed['overpay']), **displayed)
    return dict(budget=i.monthly, payment=first['payment'], surplus=first['surplus'], **actual,
                requested_overpay=first['requested_overpay'], fallback=first['fallback_add'],
                reason=first['redirect_reason'], display=display)


@lru_cache(maxsize=6144)
def _plan(i: m.Inputs, term: int, deposit: D, month: int) -> dict:
    """Read opening, flow and objective fields from the same Decimal projection."""
    # Equal Decimal cache keys can arrive from exact entry, preview or the grid.
    # Keep the same money representation in the returned plan whichever runs first.
    deposit = deposit.quantize(PENNY)
    if i.pricing_mode == QUOTE and len(i.quotes) > 1:
        # Narrow to one product before evaluating: rates, fees, allowances and
        # the assumed continuation all belong to that specific quote.
        matching = [q for q in i.quotes if (q.price, q.deposit, q.term_years) == (i.price, deposit, term)
                    and deposit < i.price]
        if not matching:
            return _plan(replace(i, quotes=(), quote_id=''), term, deposit, month)
        plans = [_plan(replace(i, quotes=(q,), quote_id=q.id, continuation=q.rate or ZERO),
                       term, deposit, month) for q in matching]
        # Distinct products at an identical point still represent one deposit/term pair.
        priority = {'funded': 3, 'over_budget': 2, 'unavailable': 1, 'unknown': 0}
        return max(plans, key=lambda p: (priority[p['status']], p['position'] or ZERO,
                                         p['source'].get('quote_id') == i.quote_id))
    plan = m.project(i, deposit, term, objective_month=month, through_month=month)
    source = _source(i)
    result = dict(deposit=deposit, term_years=term, source=source,
                  position=None, equity=None, cash=None, investment=None, house_and_cash=None,
                  opening_debt=None, opening_investment=None, first_payment=None, monthly=None,
                  first_redirect=None, ledger=[], fee=None, costs=i.costs, opening_cash=i.reserve,
                  rate=m.rate_for(i, deposit, term), fixed_months=source['fixed_months'], band_low=None)
    if not plan['rows']:
        status, reason = _unpriced(i, deposit, term, plan['issues'])
        if status == 'unknown':
            result['source'] = dict(kind='unknown', name='Rate unknown', date='')
        return dict(result, status=status, reason=reason)

    start, first, objective = plan['rows'][0], plan['rows'][1], plan['rows'][-1]
    if deposit == i.price:
        result.update(source=dict(kind='cash', name='Cash purchase', date=''), fixed_months=None)
    elif i.pricing_mode == QUOTE:
        result['band_low'] = deposit
    else:
        result['band_low'] = next(b['low'] for b in _market_bands(i) if b['low'] <= deposit <= b['high'])
    fallback_destination = 'cash' if plan['quote_id'] else i.fallback
    flows = _monthly(i, first, fallback_destination)
    redirect = next((row for row in plan['rows'][1:] if row['fallback_add'] > ZERO), None)
    result.update(monthly=flows, opening_debt=start['debt'], opening_investment=start['investment'],
                  first_payment=plan['first_payment'], opening_cash=start['cash'],
                  ledger=plan['ledger'], fee=plan['product_fee'], fee_mode=plan['fee_mode'])
    if redirect:
        result['first_redirect'] = dict(
            month=redirect['month'], amount=redirect['fallback_add'], reason=redirect['redirect_reason'],
            destination=fallback_destination)
    shortfall = plan['first_shortfall']
    # The plotted date can precede a later funding gap. Grid points already
    # carry the model's full-horizon region check. Inspect other exact pennies
    # directly before presenting their early balance as a comparable result.
    if shortfall is None and month < m.HORIZON_MONTHS and not any(
            low <= deposit <= high for low, high, _ in _regions(i, term, month)):
        shortfall = m.project(i, deposit, term, detailed=False)['first_shortfall']
    if shortfall:
        return dict(result, status='over_budget', reason=(
            f"The required payment exceeds the monthly budget in month {shortfall['month']} "
            f"by £{m.money(shortfall['amount'])}."))
    result.update(status='funded', reason='', position=objective['position'], equity=objective['equity'],
                  cash=objective['cash'], investment=objective['investment'],
                  house_and_cash=objective['equity']+objective['cash'])
    return result


@lru_cache(maxsize=192)
def _sample(i: m.Inputs, term: int, month: int) -> tuple:
    """Keep funded points in separate pricing regions to preserve discontinuities."""
    return tuple(tuple(_plan(i, term, deposit, month) for deposit in m.sample_deposits(low, high))
                 for low, high, _ in _regions(i, term, month))


def _explanation(i: m.Inputs, month: int) -> dict | None:
    """Two opening allocations for this household with the same repayment term."""
    for term in reversed(m.TERMS):
        regions = _regions(i, term, month)
        if regions and regions[0][0] < regions[-1][1]:
            return dict(smaller=_plan(i, term, regions[0][0], month),
                        larger=_plan(i, term, regions[-1][1], month))
    return None


def _missing_example(i: m.Inputs, term: int, month: int) -> dict:
    low, high = _bounds(i)
    if i.pricing_mode == QUOTE and len(i.quotes) > 1:
        examples = [_plan(i, term, dep, month) for dep in _quote_deposits(i, term)]
        if examples:
            return next((plan for plan in examples if plan['status'] == 'over_budget'), examples[0])
    quote = m.active_quote(i)
    if quote and quote.deposit is not None:
        return _plan(i, term, quote.deposit, month)
    if high == i.price and i.lisa and low < high:
        high -= PENNY
    return _plan(i, term, high, month)


def _allocation_preview(i: m.Inputs, term: int | None, deposit: D | None, month: int) -> dict:
    """Show the current case, or one affordable opening example before the search."""
    if deposit is not None:
        plan = _plan(i, term, deposit, month)
    else:
        # Prefer a quoted case for a household using quotes. For averages, try
        # the largest opening deposit at the longest term in the fixture.
        candidates = []
        if i.pricing_mode == QUOTE:
            for years in reversed(m.TERMS):
                if term is None or years == term:
                    candidates.extend((years, dep) for dep in reversed(_quote_deposits(i, years)))
        years = term or FIXTURE['term_years']
        low, high = _bounds(i)
        if high == i.price and i.lisa and low < high:
            high -= PENNY
        candidates.append((years, high))
        plan = None
        for years, dep in candidates:
            evaluated = _plan(i, years, dep, month)
            if plan is None or evaluated['status'] == 'funded':
                plan = evaluated
            if plan['status'] == 'funded':
                break
    return {key:plan[key] for key in ('deposit','term_years','status','reason','monthly')}


def _difference(highest: dict | None, selected: dict | None) -> D | None:
    if highest is None or selected is None or selected['position'] is None:
        return None
    return highest['position']-selected['position']


def _gaps(i: m.Inputs, term: int, month: int, domain: dict, regions: tuple, bands: list) -> list:
    """Partition missing coverage and over-budget areas without joining them."""
    low, high = domain['low'], domain['high']
    cuts = {low, high+PENNY}
    intervals = [_bounds(i), *((a,b) for a,b,_ in regions), *((b['low'],b['high']) for b in bands)]
    for left, right in intervals:
        cuts.update(v for v in (left,right+PENNY) if low <= v <= high)
    ordered = sorted(cuts)
    gaps = []
    for a, end in zip(ordered, ordered[1:]):
        if any(x <= a <= y for x,y,_ in regions):
            continue
        state = _plan(i, term, a, month)
        reason = ('Required mortgage payments exceed the monthly budget in this range.'
                  if state['status'] == 'over_budget' else state['reason'])
        b = end-PENNY
        if (gaps and gaps[-1]['status'] == state['status'] and gaps[-1]['reason'] == reason
                and gaps[-1]['high']+PENNY == a):
            gaps[-1]['high'] = b
        else:
            gaps.append(dict(low=a, high=b, status=state['status'], reason=reason))
    return gaps


def _calculate(i: m.Inputs, month: int, chosen_term: int | None, deposit: D | None) -> dict:
    term_data, all_leaders = [], []
    selected_groups = None
    # Include an exact typed choice just once and only in its own region.
    for term in m.TERMS:
        groups = _sample(i, term, month)
        if term == chosen_term:
            augmented = []
            for region, group in zip(_regions(i, term, month), groups):
                if deposit is not None and region[0] <= deposit <= region[1] and not any(
                        p['deposit'] == deposit for p in group):
                    group = tuple(sorted((*group, _plan(i, term, deposit, month)), key=lambda p:p['deposit']))
                augmented.append(group)
            groups = selected_groups = tuple(augmented)
        points = [point for group in groups for point in group if point['status'] == 'funded']
        highest = max((point['position'] for point in points), default=None)
        winners = [p for p in points if p['position'] == highest]
        lead = (next((p for p in winners if term == chosen_term and p['deposit'] == deposit), None)
                or (winners[0] if winners else None))
        state = lead or _missing_example(i, term, month)
        term_data.append(dict(term_years=term, status=state['status'], reason=state['reason'],
                              highest=lead, tie_count=len(winners), count=len(points),
                              tied_deposits=[p['deposit'] for p in winners]))
        all_leaders.extend(winners)

    maximum = max((p['position'] for p in all_leaders), default=None)
    overall_ties = [p for p in all_leaders if p['position'] == maximum]
    # A stable starting pair even when the explored choice ties it.
    global_lead = min(overall_ties, key=lambda p:(p['deposit'], p['term_years']), default=None)
    term = chosen_term or (global_lead['term_years'] if global_lead else m.TERMS[-1])
    groups = selected_groups if chosen_term else _sample(i, term, month)
    current = next(row for row in term_data if row['term_years'] == term)
    term_lead = current['highest']
    selected = (_plan(i, term, deposit, month) if deposit is not None else
                term_lead or _missing_example(i, term, month))

    def annotated(plan: dict | None, leader: dict | None) -> dict | None:
        return ({**plan, 'difference_to_term': _difference(leader, plan),
                 'difference_to_global': _difference(global_lead, plan)} if plan else None)

    regions = _regions(i, term, month)
    bands = _bands(i, term, regions, month)
    low, high = _bounds(i)
    if regions and i.pricing_mode != QUOTE:
        low, high = regions[0][0], regions[-1][1]
    if deposit is not None:
        low, high = min(low, deposit), max(high, deposit)
    domain = dict(low=low, high=high)
    segments, drag_points, jumps = [], [], []
    previous = None
    for (a,b,rate), group in zip(regions, groups):
        points = [p for p in group if p['status'] == 'funded']
        if not points:
            continue
        segments.append(dict(low=a, high=b, rate=rate,
                             points=[dict(deposit=p['deposit'], position=p['position']) for p in points]))
        drag_points.extend(annotated(p, term_lead) for p in points)
        at = points[0]
        if i.pricing_mode != QUOTE and previous and previous['deposit']+PENNY == a and previous['rate'] > rate:
            jumps.append(dict(below=previous, at=at,
                              position_difference=at['position']-previous['position'],
                              payment_difference=previous['first_payment']-at['first_payment']))
        previous = points[-1]
    step = min(jumps, key=lambda j:abs(j['at']['deposit']-selected['deposit']), default=None)
    for row in term_data:
        leader = row['highest']
        row['difference_to_global'] = _difference(global_lead, leader)
        row['highest'] = annotated(leader, leader)
    count = sum(t['count'] for t in term_data)
    noun = 'combination' if count == 1 else 'combinations'
    term_range = f'{min(m.TERMS)} to {max(m.TERMS)} years'
    description = (f'{count:,} affordable deposit-and-term {noun} evaluated across repayment '
                   f'terms of {term_range} at {month//12} years. Each funded rate band is sampled '
                   f'at {m.GRID_INTERVALS} equal intervals, its endpoints and their adjacent pennies. '
                   'An affordable exact entry is also included.')
    if i.pricing_mode == QUOTE:
        description = (f'{count:,} affordable priced {noun} across the {len(m.TERMS)} repayment terms '
                       f'from {term_range}. Each quote covers its confirmed house price, deposit and term. '
                       'Where quotes cover the same case, the highest funded outcome represents that pair.')
    reason = ''
    if not global_lead:
        # If the quote is known but unaffordable, distinguish that case from the
        # remaining 20 terms for which there is no price.
        issue = next((r for r in term_data if r['status'] == 'over_budget'), current)
        reason = issue['reason']
        if any(r['status'] == 'unknown' for r in term_data) and issue['status'] != 'unknown':
            reason += ' Other terms have no rate coverage.'
    return dict(status='ok', version=VERSION, model_version=m.VERSION, fixture_version=FIXTURE['version'],
                objective_month=month, objective_year=month//12, source=_source(i), reason=reason,
                selected=annotated(selected, term_lead), term_highest=annotated(term_lead, term_lead),
                global_highest=annotated(global_lead, global_lead), terms=term_data,
                difference_to_term=_difference(term_lead, selected), difference_to_global=_difference(global_lead, selected),
                scope=dict(count=count, description=description, funding_horizon_months=m.HORIZON_MONTHS,
                           grid_intervals=m.GRID_INTERVALS),
                ties={'term': current['tied_deposits'], 'global': [
                    dict(deposit=p['deposit'], term_years=p['term_years']) for p in overall_ties]},
                bands=bands, domain=domain, drag_points=drag_points,
                curve=dict(segments=segments, gaps=_gaps(i, term, month, domain, regions, bands), step=step),
                explanation=_explanation(i, month))


@m.fixed
def respond(request: dict) -> dict:
    """Handle one phone calculation; return labelled coverage and funding states."""
    try:
        if not isinstance(request, dict):
            raise ValueError('The phone calculation needs an input object.')
        i = _inputs(request.get('inputs', {}))
        if request.get('operation') == 'validate':
            return dict(status='ok', version=VERSION)
        month = request.get('objective_month', FIXTURE['objective_month'])
        term = request.get('term_years')
        if type(month) is not int or month not in DATES:
            raise ValueError('Choose 2, 5, 10, 20 or 35 years to compare.')
        if term is not None and (type(term) is not int or term not in m.TERMS):
            raise ValueError('Choose a whole repayment term from 15 to 35 years.')
        raw_deposit = request.get('deposit')
        deposit = None if raw_deposit is None else D(str(raw_deposit))
        if deposit is not None and (term is None or not deposit.is_finite() or not ZERO <= deposit <= i.price
                                    or deposit != deposit.quantize(PENNY)):
            raise ValueError('Enter an exact deposit in pounds and pence with its repayment term.')
        if request.get('operation') == 'explain':
            return m.serial(dict(status='ok', version=VERSION, source=_source(i), explanation=_explanation(i, month)))
        if request.get('operation') == 'allocation_preview':
            return m.serial(dict(status='ok', version=VERSION, preview=_allocation_preview(i, term, deposit, month)))
        return m.serial(_calculate(i, month, term, deposit))
    except (ValueError, TypeError, InvalidOperation, KeyError, OverflowError) as exc:
        return dict(status='invalid', version=VERSION, issues=[str(exc) or 'Check the input values.'])
