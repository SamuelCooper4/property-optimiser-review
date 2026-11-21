"""Phone reporting for the isolated illustrative model. Money is GBP.

The search uses the dashboard's finite deposit grid and its full-horizon funding
test. The exact explored penny also participates. The original monthly mortgage
recurrence evaluates every ranked point, including estimated mortgage bands.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal as D, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP, localcontext
from functools import lru_cache
from pathlib import Path

import model as m
from phone_savings import apply_lisa_policy, savings_report
import phone_calibration as cal


VERSION = 'bp-phone-provider-2026-11-21-calibrated-v2'
FIXTURE = json.loads(Path(__file__).with_name('phone-fixture.json').read_text(encoding='utf-8-sig'))
DATES = (24, 60, 120, 240, 420)
QUOTE = 'quotes'
ZERO = m.ZERO
PENNY = m.PENNY
POUND = D(1)
QUOTE_PROMPT_RATE_WINDOW = D('.005')  # 0.5 percentage points below the estimated annual rate.
BREAK_EVEN_RATE_WIDTH = D('.00000001')  # One millionth of a percentage point.
BREAK_EVEN_POSITION_ERROR = PENNY/100  # Match the projected position within a hundredth of a penny.
BREAK_EVEN_MIN_WIDTH = D('1e-15')  # Detect a funding discontinuity at a much finer rate interval.
FIXED_PERIOD_REQUEST = 'Choose which fixed period to compare in Mortgage rates.'


@dataclass(frozen=True)
class PhoneInputs(m.Inputs):
    """Keep the selected product for a band with several quotes."""

    pinned_quote_id: str = ''
    lisa_charge: D = ZERO
    fixed_periods: tuple[int, ...] = ()
    comparison_fixed_months: int | None = None

    def period_selection(self) -> dict:
        """Report the available quote periods while preserving the buyer's saved quote list."""
        return dict(fixed_periods=self.fixed_periods, comparison_fixed_months=self.comparison_fixed_months,
                    needs_fixed_period=len(self.fixed_periods)>1 and self.comparison_fixed_months is None)


def _inputs(raw: dict, *, allow_pending: bool = False) -> PhoneInputs:
    parsed = m.parse(cal.prepare_quotes({**FIXTURE['inputs'], **raw}))
    pin = raw.get('pinned_quote_id', '')
    if not isinstance(pin, str):
        raise ValueError('The adopted quote needs a valid reference.')
    periods = ()
    comparison = None
    if parsed.pricing_mode == QUOTE:
        for q in parsed.quotes:
            cal.quote_band(parsed,q)
        periods = tuple(sorted({q.fixed_months for q in parsed.quotes}))
        requested = raw.get('comparison_fixed_months')
        if requested not in ('',None):
            number = D(str(requested))
            if not number.is_finite() or number!=number.to_integral_value() or not 1<=number<=120:
                raise ValueError('Choose a fixed period from your saved quotes.')
            comparison = int(number) if number in periods else None
        if len(periods)==1:
            comparison = periods[0]
        if comparison is None and not allow_pending:
            raise ValueError(FIXED_PERIOD_REQUEST)
        active = tuple(q for q in parsed.quotes if q.fixed_months==comparison)
        parsed = replace(parsed, quotes=active, quote_id=parsed.quote_id if any(
            q.id==parsed.quote_id for q in active) else '')
    inputs = PhoneInputs(**vars(parsed), fixed_periods=periods, comparison_fixed_months=comparison,
                         pinned_quote_id=pin if any(q.id == pin for q in parsed.quotes) else '')
    if inputs.deals and inputs.deals != ((FIXTURE['source']['fixed_months'], None),):
        raise ValueError('Choose one renewal rate after the opening fix.')
    if inputs.bands != tuple((D(a), D(b)) for a, b in FIXTURE['inputs']['bands']):
        raise ValueError('Use the dated market bands and add your quotes in the rates sheet.')
    if not allow_pending:
        cal.curve(inputs)
    return apply_lisa_policy(inputs)


def _source(i: m.Inputs, band: cal.Band | None = None) -> dict:
    if band and band.product:
        q = band.product
        return dict(kind=band.source_kind, name='Your quote' if band.source_kind=='quote' else 'Estimate',
                    quote_id=q.id, date=q.obtained, fixed_months=q.fixed_months, max_ltv=band.max_ltv)
    if i.pricing_mode == QUOTE:
        return dict(kind='mixed', name='Your quotes and estimates', count=len(i.quotes),
                    date=i.as_of, fixed_months=None)
    return FIXTURE['source'].copy()


def _bounds(i: m.Inputs) -> tuple[D, D]:
    return i.lisa+i.gift, min(i.total-i.reserve-i.costs, i.price)


@lru_cache(maxsize=256)
def _regions(i: m.Inputs, term: int, month: int) -> tuple:
    """Full-horizon funded inclusive penny ranges in one repayment term."""
    if i.pricing_mode != QUOTE:
        return m.regions(i, term, penny_edges=True)
    regions = [region for band in cal.curve(i)
               for region in m.regions(cal.projection_inputs(i, band), term, penny_edges=True)]
    if _bounds(i)[1] == i.price and not i.lisa:
        regions.append((i.price, i.price, ZERO))
    return tuple(regions)


def _bands(i: m.Inputs, regions: tuple = ()) -> list[dict]:
    return [dict(band.report(FIXTURE['source']['fixed_months']),
                 reachable=any(max(a,band.low)<=min(b,band.high) for a,b,_ in regions))
            for band in cal.curve(i)]


def _unpriced(i: m.Inputs, deposit: D, term: int, issues: list) -> tuple[str,str]:
    low, high = _bounds(i)
    if not low <= deposit <= high or deposit == i.price and i.lisa:
        return 'unavailable', issues[0]
    if deposit != i.price and not cal.at_deposit(i,deposit):
        return 'unknown', 'This deposit is outside the available mortgage bands.'
    return 'unavailable', ' '.join(issues)


def _choice_inputs(i: m.Inputs, selected: dict) -> m.Inputs:
    """Apply the same product used for this deposit to the detailed projection."""
    return cal.projection_inputs(i,cal.at_deposit(i,selected['deposit']))


def _preview_choice(i: m.Inputs, term: int, deposit: D, month: int, request: dict) -> dict:
    """Use an explicitly selected quote for a preview of its calibrated band."""
    quote_id = request.get('preview_quote_id')
    if quote_id is not None:
        if not any(q.id == quote_id for q in i.quotes):
            raise ValueError('Choose a saved quote for this preview.')
        i = replace(i, pinned_quote_id=quote_id)
        band = cal.at_deposit(i,deposit)
        if band is None or band.product is None or band.product.id != quote_id:
            raise ValueError('This quote does not supply the product details for the selected band.')
    return _plan(i, term, deposit, month)


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
    band = cal.at_deposit(i, deposit)
    applied = cal.projection_inputs(i, band)
    plan = m.project(applied, deposit, term, objective_month=month, through_month=month)
    source = _source(i, band)
    result = dict(deposit=deposit, term_years=term, source=source,
                  position=None, equity=None, cash=None, investment=None, house_and_cash=None,
                  opening_debt=None, opening_investment=None, first_payment=None, monthly=None,
                  first_redirect=None, ledger=[], fee=None, costs=i.costs, opening_cash=i.reserve,
                  rate=m.rate_for(applied, deposit, term), fixed_months=source['fixed_months'], band_low=None)
    if not plan['rows']:
        status, reason = _unpriced(i, deposit, term, plan['issues'])
        if status == 'unknown':
            result['source'] = dict(kind='unknown', name='Outside mortgage bands', date='')
        return dict(result, status=status, reason=reason)

    start, first, objective = plan['rows'][0], plan['rows'][1], plan['rows'][-1]
    if deposit == i.price:
        result.update(source=dict(kind='cash', name='Cash purchase', date=''), fixed_months=None)
    elif band:
        result['band_low'] = band.low
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
        shortfall = m.project(applied, deposit, term, detailed=False)['first_shortfall']
    if shortfall:
        return dict(result, status='over_budget', reason=(
            f"The required payment exceeds the monthly budget in month {shortfall['month']} "
            f"by £{m.money(shortfall['amount'])}."))
    result.update(status='funded', reason='', position=objective['position'], equity=objective['equity'],
                  interest=objective['interest_total'], closing_debt=objective['debt'],
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
    if high == i.price and i.lisa and low < high:
        high -= PENNY
    if i.pricing_mode == QUOTE and high < i.price:
        for band in reversed(cal.curve(i)):
            fee = band.product.fee if band.product.fee_mode=='upfront' else ZERO
            candidate = min(high-fee,band.high)
            if candidate >= max(low,band.low):
                return _plan(i,term,candidate,month)
    return _plan(i, term, high, month)


def _allocation_preview(i: m.Inputs, term: int | None, deposit: D | None, month: int) -> dict:
    """Show the current case, or one affordable opening example before the search."""
    if deposit is not None:
        plan = _plan(i, term, deposit, month)
    else:
        # Prefer a supplied deposit for a quick preview, then try the affordable endpoints.
        candidates = []
        if i.pricing_mode == QUOTE:
            candidates.extend((term or q.term_years, q.deposit) for q in reversed(i.quotes)
                              if q.deposit is not None and q.price == i.price)
        years = term or FIXTURE['term_years']
        low, high = _bounds(i)
        if high == i.price and i.lisa and low < high:
            high -= PENNY
        candidates.extend((years,b) for _,b,_ in reversed(_regions(i,years,month)))
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
    with localcontext() as ctx:
        ctx.prec = 150
        return highest['position']-selected['position']


def _terms_at_deposit(i: PhoneInputs, deposit: D, month: int, current: dict | None = None) -> list[dict]:
    """Compare every supported repayment term at one deposit under this future."""
    keys = ('deposit','term_years','status','reason','position','rate','source','first_payment','fixed_months')
    rows = [{key:p[key] for key in keys} for term in m.TERMS
            for p in (current if current and current['term_years'] == term else _plan(i, term, deposit, month),)]
    highest = max((r['position'] for r in rows if r['position'] is not None), default=None)
    for row in rows:
        row['leading'] = highest is not None and row['position'] == highest
    return rows


def _starting_comparison(i: PhoneInputs, leader: dict | None, month: int) -> dict | None:
    """Read the affordable endpoints at the starting pair's term and date."""
    if leader is None:
        return None
    term, deposit = leader['term_years'], leader['deposit']
    regions = _regions(i, term, month)
    low, high = regions[0][0], regions[-1][1]
    def endpoint(amount: D) -> dict:
        return dict(deposit=amount, difference=_difference(leader, _plan(i, term, amount, month)))
    reason = 'compared'
    if low == high:
        reason = 'only'
    elif deposit == low:
        reason = 'smallest'
    elif deposit == high:
        reason = 'largest'
    elif (leader['band_low'] == deposit
          and all(r != leader['rate'] for a, b, r in regions if a < deposit)):
        reason = 'rate_edge'
    return dict(reason_kind=reason, smallest=endpoint(low), largest=endpoint(high))


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


@lru_cache(maxsize=512)
@m.fixed
def _trial_best(i: m.Inputs, band: cal.Band, month: int, rate: D,
                extra_term: int | None, extra_deposit: D | None) -> tuple | None:
    """Best funded deposit/term at a trial rate under the original search and monthly ledger."""
    applied = cal.projection_inputs(i,replace(band,rate=rate))
    product = m.active_quote(applied)
    best = None
    for years in m.TERMS:
        # The first required payment alone excludes larger loans. Retain one extra
        # penny when narrowing the search, then verify funding using the full ledger.
        unit = m.repayment(POUND,rate,years*12)
        opening_cap = (i.monthly/unit).quantize(PENNY,rounding=ROUND_CEILING)+PENNY
        if product.min_loan > opening_cap:
            continue
        loan_cap = min(product.max_loan,opening_cap)
        filtered = replace(applied,quotes=(replace(product,max_loan=loan_cap),))
        for low,high,_ in m.regions(filtered,years,penny_edges=True):
            # With no overpayments, scheduled payments, debt, saved surplus and
            # investment value are affine in opening borrowing within one band.
            # Both endpoints therefore include its maximum. With overpayments,
            # retain every ordinary grid point and the buyer's exact entry.
            amounts = m.sample_deposits(low,high) if i.allocation[2] else (low,high)
            if years==extra_term and extra_deposit is not None and low<=extra_deposit<=high:
                amounts = (*amounts,extra_deposit)
            for amount in dict.fromkeys(amounts):
                plan = m.project(applied,amount,years,detailed=False,objective_month=month,through_month=month)
                position = plan['rows'][0]['position']
                if best is None or position > best[0]:
                    best = position, amount, years
    return best


def _estimated_best(i: m.Inputs, band: cal.Band, month: int,
                    extra_term: int | None, extra_deposit: D | None) -> tuple | None:
    """Reuse the already ranked sample at the estimated rate, including the exact entry."""
    plans = [p for years in m.TERMS for group in _sample(i,years,month) for p in group
             if band.low<=p['deposit']<=band.high and p['status']=='funded']
    if extra_term and extra_deposit is not None and band.low<=extra_deposit<=band.high:
        entered = _plan(i,extra_term,extra_deposit,month)
        if entered['status']=='funded':
            plans.append(entered)
    best = max(plans,key=lambda p:p['position'],default=None)
    return (best['position'],best['deposit'],best['term_years']) if best else None


@lru_cache(maxsize=128)
@m.fixed
def _break_even(i: m.Inputs, band: cal.Band, month: int, target: D,
                extra_term: int | None, extra_deposit: D | None) -> tuple | None:
    """Bracket the band optimum's tie with the leader within the inclusive quote window."""
    high = band.rate
    low = max(band.minimum_rate,high-QUOTE_PROMPT_RATE_WINDOW)
    if low>=high:
        return None
    winner = _trial_best(i,band,month,low,extra_term,extra_deposit)
    if not winner or winner[0]<target:
        return None
    top = _estimated_best(i,band,month,extra_term,extra_deposit)
    if top and top[0]==target:
        return (high,*top[1:]) if winner[0]>target else None
    if winner[0]==target:
        return (low,*winner[1:])
    # Use the projected positions to propose a secant step. Bisection every third
    # iteration guarantees a narrowing bracket across changes in the winning term
    # or affordability. A funding jump cannot be reported as a matching outcome.
    step = 0
    while high-low>BREAK_EVEN_RATE_WIDTH or winner[0]-target>BREAK_EVEN_POSITION_ERROR:
        width = high-low
        if width<BREAK_EVEN_MIN_WIDTH:
            return None
        step += 1
        probe = (low+high)/2
        if top and step%3 and top[0]<target:
            interpolation = low+width*(winner[0]-target)/(winner[0]-top[0])
            distance = min(BREAK_EVEN_RATE_WIDTH/2,width/4)
            probe = min(high-distance,max(low+distance,interpolation))
        trial = _trial_best(i,band,month,probe,extra_term,extra_deposit)
        if trial and trial[0]==target:
            return (probe,*trial[1:])
        if trial and trial[0]>target:
            low, winner = probe, trial
            # Once near the root, a single opposite-side evaluation can certify its width.
            if winner[0]-target<=BREAK_EVEN_POSITION_ERROR and high-low>BREAK_EVEN_RATE_WIDTH:
                nearby = low+BREAK_EVEN_RATE_WIDTH
                edge = _trial_best(i,band,month,nearby,extra_term,extra_deposit)
                if edge and edge[0]==target:
                    return (nearby,*edge[1:])
                if not edge or edge[0]<target:
                    high,top = nearby,edge
                else:
                    low,winner = nearby,edge
        else:
            high, top = probe, trial
    return low,winner[1],winner[2]


def _quote_prompt(i: m.Inputs, leader: dict | None, month: int,
                  extra_term: int | None = None, extra_deposit: D | None = None) -> dict | None:
    """Ask for a leading estimate or the smallest eligible rate improvement to match it."""
    if not leader:
        return None
    amount, years = leader['deposit'], leader['term_years']
    band = cal.at_deposit(i,amount)
    if not band:
        return None
    break_even_rate = None
    if band.source_kind=='quote':
        options = []
        for other in cal.curve(i):
            if other.source_kind!='estimate' or max(i.lisa+i.gift,other.low)>min(_bounds(i)[1],other.high):
                continue
            exact = (extra_term,extra_deposit) if (i.allocation[2] and extra_deposit is not None
                      and other.low<=extra_deposit<=other.high) else (None,None)
            crossing = _break_even(i,other,month,leader['position'],*exact)
            if crossing:
                gap = other.rate-crossing[0]
                options.append((gap,abs(band.max_ltv-other.max_ltv),other.max_ltv,other,crossing))
        if not options:
            return None
        _,_,_,band,(break_even_rate,amount,years) = min(options,key=lambda item:item[:3])
    info = band.report(FIXTURE['source']['fixed_months'])
    loan = i.price-amount
    return dict(deposit=amount,loan=loan,ltv=loan/i.price,term_years=years,break_even_rate=break_even_rate,
                estimated_rate=band.rate,
                **{key:info[key] for key in ('max_ltv','fixed_months','fee','fee_mode','allowance')})


def _calculate(i: m.Inputs, month: int, chosen_term: int | None, deposit: D | None) -> dict:
    term_data, all_leaders = [], []
    chart_points = []
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
        chart_points.extend(points)
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
    bands = _bands(i, regions)
    low, high = _bounds(i)
    if regions:
        low, high = regions[0][0], regions[-1][1]
    if deposit is not None:
        low, high = min(low, deposit), max(high, deposit)
    domain = dict(low=low, high=high)
    segments, jumps = [], []
    previous = None
    # Exact entries participate in ranking and in the available plan previews.
    # Draw the permanent grid so selecting another penny never redraws the curve.
    drag_points = [annotated(p, term_lead) for group in groups for p in group if p['status'] == 'funded']
    for (a,b,rate), group in zip(regions, _sample(i, term, month)):
        points = [p for p in group if p['status'] == 'funded']
        if not points:
            continue
        source_kind = points[0]['source']['kind']
        descending = (len(points)>1 and all(left['position'] >= right['position'] and
                      left['opening_investment'] > right['opening_investment']
                      for left,right in zip(points,points[1:])) and points[0]['position']>points[-1]['position'])
        segments.append(dict(low=a, high=b, rate=rate, source_kind=source_kind, descending_investment=descending,
                             points=[dict(deposit=p['deposit'], position=p['position']) for p in points]))
        at = points[0]
        if (previous and source_kind != 'cash' and previous['source']['kind'] != 'cash'
                and previous['deposit']+PENNY == a and previous['rate'] > rate):
            jumps.append(dict(below=previous, at=at,
                              position_difference=at['position']-previous['position'],
                              payment_difference=previous['first_payment']-at['first_payment']))
        previous = points[-1]
    step = max(jumps, key=lambda j:j['position_difference'], default=None)
    for row in term_data:
        leader = row['highest']
        row['difference_to_global'] = _difference(global_lead, leader)
        row['highest'] = annotated(leader, leader)
    at_deposit = _terms_at_deposit(i, selected['deposit'], month)
    for summary, point in zip(term_data, at_deposit):
        summary['at_deposit'] = point
    count = sum(t['count'] for t in term_data)
    noun = 'combination' if count == 1 else 'combinations'
    term_range = f'{min(m.TERMS)} to {max(m.TERMS)} years'
    description = (f'{count:,} affordable deposit-and-term {noun} evaluated across repayment '
                   f'terms of {term_range} at {month//12} years. Each funded rate band is sampled '
                   f'at {m.GRID_INTERVALS} equal intervals, its endpoints and their adjacent pennies. '
                   'An affordable exact entry is also included.')
    reason = ''
    if not global_lead:
        issue = next((r for r in term_data if r['status'] == 'over_budget'), current)
        reason = issue['reason']
    # Chart bounds summarise already evaluated results; they do not change the search.
    comparison_ranges = {}
    for key in ('deposit', 'rate', 'position', 'interest', 'investment', 'first_payment'):
        values = [point[key] for point in chart_points if point[key] is not None]
        if values:
            comparison_ranges[key] = (min(values), max(values))
    return dict(status='ok', quote_pins=[], quote_prompt=_quote_prompt(i,global_lead,month,chosen_term,deposit), comparison_ranges=comparison_ranges,
                version=VERSION, model_version=m.VERSION, fixture_version=FIXTURE['version'],
                objective_month=month, objective_year=month//12, source=_source(i), reason=reason,
                selected=annotated(selected, term_lead), term_highest=annotated(term_lead, term_lead),
                global_highest=annotated(global_lead, global_lead), terms=term_data,
                starting_comparison=_starting_comparison(i, global_lead, month), terms_at_deposit=at_deposit,
                assumptions=dict(recovery_months=i.recovery_months, recovery_return=i.recovery_return),
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
    selection = {}
    try:
        if not isinstance(request, dict):
            raise ValueError('The phone calculation needs an input object.')
        i = _inputs(request.get('inputs', {}), allow_pending=True)
        selection = i.period_selection()
        if request.get('operation') == 'savings':
            return m.serial(dict(status='ok', version=VERSION, savings_policy=savings_report(i)))
        if request.get('operation') == 'validate':
            bands = [] if selection['needs_fixed_period'] else _bands(i)
            return m.serial(dict(status='ok', version=VERSION, bands=bands, **selection))
        if selection['needs_fixed_period']:
            return m.serial(dict(status='invalid', version=VERSION, issues=[FIXED_PERIOD_REQUEST], **selection))
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
        if request.get('operation') == 'explore':
            page = request.get('page')
            if term is None or deposit is None or type(page) is not int or page not in (4, 5, 6, 8, 9):
                raise ValueError('Choose a page, deposit and repayment term to explore.')
            if page <= 6:
                from phone_ownership import explore
            else:
                from phone_futures import explore
            return m.serial(explore(i, term, deposit, month, request))
        result = _calculate(i, month, term, deposit)
        total_restricted = i.lisa+i.gift
        result.update(**selection, savings_policy=savings_report(i), restricted_deposit=dict(
            lisa=i.lisa, gift=i.gift, total=total_restricted,
            sets_minimum=total_restricted > ZERO and result['domain']['low'] == total_restricted))
        return m.serial(result)
    except (ValueError, TypeError, InvalidOperation, KeyError, OverflowError) as exc:
        return dict(status='invalid', version=VERSION, issues=[str(exc) or 'Check the input values.'], **selection)
