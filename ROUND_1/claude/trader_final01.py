"""
IMC Prosperity 4 – Round 1  |  Optimised Trader  (trader_final.py)
===================================================================

DATA-CONFIRMED FACTS (from 3-day DataCapsule + active-log analysis):
---------------------------------------------------------------------
INTARIAN PEPPER ROOT
  • Timestamp scale  : 0 → 99 900 per day (step = 100, 1 000 ticks/day)
  • Price trend      : +100 pts per 1 000-tick day (slope = 0.001 pts/ts)
  • 3-day total rise : ≈ +300 pts  →  50 × 300 = 15 000 gross PnL
  • Opening spread   : ask ≈ mid + 8,  bid ≈ mid - 8   (avg spread ≈ 16)
  • Strategy         : buy max long (+50) IMMEDIATELY on day 0, HOLD every
                       day, sell only in the final ~100 ticks of the round.

ASH-COATED OSMIUM
  • Fair value       : ≈ 10 000, mean-reverting, stdev ≈ 5, max dev ≈ ±23
  • Spread           : avg 16 ticks,  range 5–22
  • Market volume    : ≈ 411 trades × avg 5.3 units ≈ 2 158 units/full day
    (live 1 000-tick day ≈ ~215 units traded by others)
  • v4 baseline      : 1 198 PnL / 1 000-tick day at fair±4
  • Improvement      : 3-level book + tighter quotes + smarter inventory mgmt

ROUND STRUCTURE (assumed):
  • 3 days, each 1 000 ticks (ts 0 → 99 900)
  • Position CARRIES across days via traderData
  • New day is detected when ts resets to a value < NEW_DAY_THRESH

PnL TARGETS:
  Pepper  : 3 days × ~5 000 = ~15 000
  Osmium  : 3 days × ~1 400 = ~4 200
  Total   : ~19 200   (well above the 12 000 target)
"""

import json
import math
from typing import Dict, List, Optional

from ROUND_1.datamodel import OrderDepth, TradingState, Order


# ══════════════════════════════════════════════════════════════════════════════
class Trader:

    # ── Product names ─────────────────────────────────────────────────────────
    PEPPER = "INTARIAN_PEPPER_ROOT"
    OSMIUM = "ASH_COATED_OSMIUM"

    # ── Position limit (both products) ────────────────────────────────────────
    LIMIT = 50

    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER PARAMETERS
    # ─────────────────────────────────────────────────────────────────────────
    # Confirmed slope from regression across 3 DataCapsule days:
    #   Day -2: +1 003 pts over 999 900 ts  → 0.001 003 / ts
    #   Day -1: +999.5 pts over 999 900 ts  → 0.001 000 / ts
    #   Day  0: +1 001.5 pts over 999 900 ts → 0.001 002 / ts
    #   Live 1 000-tick env: slope unchanged, each day ≈ +100 pts.
    PEPPER_SLOPE     = 0.001          # pts per timestamp unit

    # Maximum premium we will pay above our own fair-value estimate.
    # Set wide (= 15) so the very first tick always fills the full book.
    PEPPER_BUY_TOL   = 15

    # ─────────────────────────────────────────────────────────────────────────
    # OSMIUM PARAMETERS
    # ─────────────────────────────────────────────────────────────────────────
    OSM_FAIR_FALLBACK = 10_000        # fallback when book is empty

    # EMA of mid-price used as fair-value estimate.
    # α = 0.015 → responds within ~66 ticks; slow enough to dampen noise.
    OSM_EMA_ALPHA    = 0.015

    # Passive quote offsets from fair (ticks).  3-level ladder.
    OSM_L1_OFFSET    = 4              # ±4  →  captures 8 ticks / round-trip
    OSM_L2_OFFSET    = 7              # ±7  →  captures 14 ticks / round-trip
    OSM_L3_OFFSET    = 11             # ±11 →  deep backstop / mean-reversion

    # Sizes at each passive level (sum ≤ 50).
    OSM_L1_SIZE      = 15
    OSM_L2_SIZE      = 12
    OSM_L3_SIZE      = 8

    # Aggressive mean-reversion: take any ask ≤ fair − MR_THRESH (or bid ≥ fair + MR_THRESH).
    # DataCapsule shows max deviation ≈ ±23.  Threshold=8 fires on ~9% of ticks.
    OSM_MR_THRESH    = 8
    OSM_MR_MAX_QTY   = 20             # max aggressive take per tick

    # Inventory-skew dampening: each unit of skew shifts both quotes by this many ticks.
    OSM_SKEW_FACTOR  = 0.06           # skew (ticks) = pos * SKEW_FACTOR

    # ─────────────────────────────────────────────────────────────────────────
    # TIMING
    # ─────────────────────────────────────────────────────────────────────────
    ROUND_DAYS       = 3              # total days in the competition round
    MAX_TS           = 99_900         # last timestamp of each day
    ENDGAME_START    = 99_000         # begin pepper unwind on final day
    NEW_DAY_THRESH   = 10_000         # ts drop below this signals new day

    # ══════════════════════════════════════════════════════════════════════════
    def run(self, state: TradingState):

        # ── 1.  Restore persistent state ─────────────────────────────────────
        try:
            data: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            data = {}

        ts       = state.timestamp
        prev_ts  = data.get("last_ts", -1)
        day      = data.get("day", 0)          # 0-indexed current day

        # ── 2.  Day-boundary detection ────────────────────────────────────────
        # ts resets to 0 at the start of each new day.
        if prev_ts > self.NEW_DAY_THRESH and ts < self.NEW_DAY_THRESH:
            day += 1
            data["day"] = day
            # Invalidate pepper anchor so it re-anchors to the new day's book.
            data.pop("pepper_anchor", None)

        # ── 3.  Pepper fair-value for this tick ───────────────────────────────
        # Anchor is set once per day to the best ask at day-open (ts ≈ 0).
        # Using the ask (rather than mid) means fair ≈ the price we pay →
        # our position is immediately break-even on a mark-to-ask basis,
        # and any later price appreciation is pure profit.
        if "pepper_anchor" not in data:
            data["pepper_anchor"] = self._pepper_open_price(state)

        pepper_fair = data["pepper_anchor"] + self.PEPPER_SLOPE * ts

        # ── 4.  Round-phase flags ─────────────────────────────────────────────
        is_last_day = (day >= self.ROUND_DAYS - 1)
        is_endgame  = is_last_day and (ts >= self.ENDGAME_START)

        # ── 5.  Generate orders ───────────────────────────────────────────────
        orders: Dict[str, List[Order]] = {}

        pepper_ords = self._pepper_orders(state, ts, pepper_fair, is_endgame)
        if pepper_ords:
            orders[self.PEPPER] = pepper_ords

        osmium_ords = self._osmium_orders(state, data)
        if osmium_ords:
            orders[self.OSMIUM] = osmium_ords

        # ── 6.  Persist state ─────────────────────────────────────────────────
        data["last_ts"] = ts
        return orders, 0, json.dumps(data)

    # ══════════════════════════════════════════════════════════════════════════
    #  PEPPER
    # ══════════════════════════════════════════════════════════════════════════

    def _pepper_open_price(self, state: TradingState) -> float:
        """Best ask at day-open, or fallback to mid / hardcoded default."""
        od = state.order_depths.get(self.PEPPER, OrderDepth())
        if od.sell_orders:
            return float(min(od.sell_orders.keys()))
        if od.buy_orders:
            return float(max(od.buy_orders.keys()))
        return 12_000.0   # conservative fallback; never needed in practice

    def _pepper_orders(
        self,
        state: TradingState,
        ts: int,
        fair: float,
        is_endgame: bool,
    ) -> List[Order]:

        od  = state.order_depths.get(self.PEPPER, OrderDepth())
        pos = state.position.get(self.PEPPER, 0)
        orders: List[Order] = []

        # ── ACCUMULATION PHASE (all days except endgame) ─────────────────────
        # Fill up to +50 by sweeping the ask side.  We accept any ask price up
        # to fair + PEPPER_BUY_TOL.  At day-open this always clears the book
        # immediately (opening asks are ≈ fair + 8, well within tolerance).
        if not is_endgame:
            buy_cap = self.LIMIT - pos
            if buy_cap > 0 and od.sell_orders:
                for ask_px in sorted(od.sell_orders.keys()):
                    if buy_cap <= 0:
                        break
                    if ask_px <= fair + self.PEPPER_BUY_TOL:
                        vol = min(buy_cap, -od.sell_orders[ask_px])
                        if vol > 0:
                            orders.append(Order(self.PEPPER, ask_px, vol))
                            buy_cap -= vol

                # Safety: if still short of limit, post a resting buy at the
                # current best ask so any incoming seller fills us next tick.
                if buy_cap > 0 and od.sell_orders:
                    best_ask = min(od.sell_orders.keys())
                    orders.append(Order(self.PEPPER, best_ask, buy_cap))

        # ── ENDGAME UNWIND (final day, ts ≥ 99 000) ──────────────────────────
        # Spread the 50-unit sale over the remaining ticks using limit orders
        # at the current best bid.  This avoids crashing our own exit.
        else:
            if pos > 0 and od.buy_orders:
                ticks_left    = max(1, (self.MAX_TS - ts) // 100 + 1)
                # Sell at a pace that guarantees full exit with 2× headroom.
                per_tick_sell = math.ceil(pos / ticks_left)
                to_sell       = min(pos, per_tick_sell * 2)

                remaining = to_sell
                for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                    if remaining <= 0:
                        break
                    vol = min(remaining, od.buy_orders[bid_px])
                    if vol > 0:
                        orders.append(Order(self.PEPPER, bid_px, -vol))
                        remaining -= vol

                # Absolute last tick: force-sell anything still open.
                if ts >= self.MAX_TS - 100 and pos > 0:
                    leftover = pos - to_sell + remaining
                    if leftover > 0 and od.buy_orders:
                        best_bid = max(od.buy_orders.keys())
                        orders.append(Order(self.PEPPER, best_bid, -leftover))

        return orders

    # ══════════════════════════════════════════════════════════════════════════
    #  OSMIUM
    # ══════════════════════════════════════════════════════════════════════════

    def _osmium_orders(self, state: TradingState, data: dict) -> List[Order]:
        od  = state.order_depths.get(self.OSMIUM, OrderDepth())
        pos = state.position.get(self.OSMIUM, 0)
        orders: List[Order] = []

        # ── Fair-value estimate (slow EMA of mid-price) ───────────────────────
        best_bid: Optional[int] = max(od.buy_orders.keys())  if od.buy_orders  else None
        best_ask: Optional[int] = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            raw_mid = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            raw_mid = best_bid + self.OSM_L1_OFFSET
        elif best_ask is not None:
            raw_mid = best_ask - self.OSM_L1_OFFSET
        else:
            raw_mid = float(self.OSM_FAIR_FALLBACK)

        prev_ema = data.get("osm_ema", float(self.OSM_FAIR_FALLBACK))
        ema = prev_ema + self.OSM_EMA_ALPHA * (raw_mid - prev_ema)
        data["osm_ema"] = ema
        fair = round(ema)

        # ── Capacity after endgame (osmium has no endgame – always active) ────
        buy_cap  = self.LIMIT - pos
        sell_cap = self.LIMIT + pos

        # ── AGGRESSIVE TAKE: mean reversion ──────────────────────────────────
        # Lift cheap asks (ask ≤ fair − threshold) and hit rich bids (bid ≥ fair + threshold).
        if od.sell_orders and buy_cap > 0:
            for ask_px in sorted(od.sell_orders.keys()):
                if ask_px > fair - self.OSM_MR_THRESH:
                    break
                vol = min(buy_cap, -od.sell_orders[ask_px], self.OSM_MR_MAX_QTY)
                if vol > 0:
                    orders.append(Order(self.OSMIUM, ask_px, vol))
                    buy_cap  -= vol

        if od.buy_orders and sell_cap > 0:
            for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                if bid_px < fair + self.OSM_MR_THRESH:
                    break
                vol = min(sell_cap, od.buy_orders[bid_px], self.OSM_MR_MAX_QTY)
                if vol > 0:
                    orders.append(Order(self.OSMIUM, bid_px, -vol))
                    sell_cap -= vol

        # ── PASSIVE MM: inventory-skewed 3-level ladder ───────────────────────
        # Skew both sides toward flat: long → quote lower (easier to sell),
        # short → quote higher (easier to buy).  Capped at ±6 ticks total.
        skew = int(max(-6, min(6, pos * self.OSM_SKEW_FACTOR)))

        levels = [
            (self.OSM_L1_OFFSET, self.OSM_L1_SIZE),
            (self.OSM_L2_OFFSET, self.OSM_L2_SIZE),
            (self.OSM_L3_OFFSET, self.OSM_L3_SIZE),
        ]

        for offset, base_size in levels:
            if buy_cap <= 0 and sell_cap <= 0:
                break

            # Inventory-skewed prices: being long pushes our quotes down,
            # which makes sells more attractive and buys less so.
            bid_px = fair - offset - skew
            ask_px = fair + offset - skew

            # Never post crossed or touching quotes.
            if bid_px >= ask_px:
                bid_px = fair - 1
                ask_px = fair + 1

            # Scale size: reduce by inventory exposure fraction so we don't
            # pile on in the direction we're already leaning.
            pos_frac = abs(pos) / self.LIMIT      # 0..1
            long_bias  = pos / self.LIMIT          # −1..+1

            # Long position: reduce buy size, increase sell size.
            buy_size  = max(1, round(base_size * (1 - max(0,  long_bias) * 0.6)))
            sell_size = max(1, round(base_size * (1 - max(0, -long_bias) * 0.6)))

            if buy_cap > 0 and bid_px > 0:
                vol = min(buy_size, buy_cap)
                orders.append(Order(self.OSMIUM, bid_px, vol))
                buy_cap -= vol

            if sell_cap > 0:
                vol = min(sell_size, sell_cap)
                orders.append(Order(self.OSMIUM, ask_px, -vol))
                sell_cap -= vol

        return orders
