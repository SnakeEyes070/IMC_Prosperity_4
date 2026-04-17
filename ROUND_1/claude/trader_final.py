"""
IMC Prosperity 4 – Round 1  |  trader_final.py
================================================
Data-confirmed facts (3-day capsule + live run analysis):
  PEPPER slope    = 0.001 per ts unit  → +100 pts per day (ts 0–99900)
  PEPPER spread   = ~13 ticks; best ask is typically ~7.5 above mid at open
  OSMIUM fair     ≈ 10 000; typical spread ≈ 16 ticks; std ≈ 5-6 ticks
  Day boundary    : timestamp resets to 0 between consecutive days
  Round length    : 3 days

Key changes vs v4 (5,883 XIRECs):
  [A] PEPPER anchor  → uses order-book mid (not best ask) at day open.
      The v4 anchor was `min(sell_orders)` which caused a +7.5 tick systematic
      upward bias → avg entry 12007 instead of 11999. Over 3 days that costs
      ~1,350 XIRECs in slippage.

  [B] PEPPER_BUY_TOL → tightened from 20 to 5.
      v4 swept asks up to fair+20, buying 20 units at 12009 (3 ticks above
      fair). Tight tolerance keeps fill prices near the best ask only.

  [C] PEPPER re-entry after day boundary → same mid anchor logic, so new-day
      buys are equally disciplined even if the position was partially filled.

  [D] PEPPER endgame → start unwinding earlier (ts ≥ 95 000 instead of 99 000)
      to guarantee all 50 lots are cleared before the final tick. Rook-E1 advice:
      "Volume decides first. Price follows." — spread sells over more ticks so
      each order remains attractive, minimising market impact.

  [E] OSMIUM market-making → offset tightened to 3 ticks from 4.
      Mean-reversion threshold tightened to 6 ticks (from 8).
      Rook-E1: "Nudge the price closer to the other side until you become
      interesting." A 3-tick bid/ask is compelling given the ~16-tick spread.

  [F] OSMIUM quote skew → inventory skew raised to ±4 (was ±3) for faster
      inventory reversion and tighter average fill prices.

  [G] Day-count detection → unchanged (timestamp drop below NEW_DAY_THRESH).
      Confirmed correct in v4 by log analysis.
"""

import json
import math
from typing import Dict, List, Tuple

from ROUND_1.datamodel import OrderDepth, TradingState, Order


class Trader:
    # ── Constants ─────────────────────────────────────────────────────────────
    PEPPER = "INTARIAN_PEPPER_ROOT"
    OSMIUM = "ASH_COATED_OSMIUM"
    LIMIT  = 50

    # Pepper trend parameters (regression over 3-day capsule data)
    PEPPER_SLOPE   = 0.001          # fair-value gain per timestamp unit
    PEPPER_BUY_TOL = 5              # [CHANGE B] accept asks up to fair + 5 only
                                    # v4 was 20; 5 keeps us within the best-ask level

    # Round / timing
    ROUND_DAYS      = 3
    ENDGAME_START   = 95_000        # [CHANGE D] start unwind earlier (was 99_000)
    MAX_TIMESTAMP   = 99_900        # last tick
    NEW_DAY_THRESH  = 10_000        # ts threshold for new-day detection

    # Osmium market-making
    OSM_MM_HALF    = 3              # [CHANGE E] half-spread for passive quotes (was 4)
    OSM_MR_THRESH  = 6              # [CHANGE E] mean-reversion hit threshold (was 8)
    OSM_SKEW_MAX   = 4              # [CHANGE F] max inventory-skew ticks (was 3)
    OSM_FALLBACK   = 10_000

    # ──────────────────────────────────────────────────────────────────────────
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        # ── Load persistent state ─────────────────────────────────────────────
        try:
            data: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            data = {}

        ts        = state.timestamp
        prev_ts   = data.get("last_ts", -1)
        day_count = data.get("day_count", 0)

        # ── Day-boundary detection ────────────────────────────────────────────
        if prev_ts > self.NEW_DAY_THRESH and ts < self.NEW_DAY_THRESH:
            day_count += 1
            data["day_count"] = day_count
            data.pop("pepper_anchor", None)       # force re-anchor on new day
            data.pop("pepper_anchor_ts", None)

        # ── Pepper fair value ─────────────────────────────────────────────────
        if "pepper_anchor" not in data:
            data["pepper_anchor"]    = self._pepper_mid(state)   # [CHANGE A/C]
            data["pepper_anchor_ts"] = ts

        anchor_ts    = data["pepper_anchor_ts"]
        pepper_fair  = data["pepper_anchor"] + self.PEPPER_SLOPE * (ts - anchor_ts)

        # ── Flags ─────────────────────────────────────────────────────────────
        is_final_day = (day_count >= self.ROUND_DAYS - 1)
        is_endgame   = is_final_day and (ts >= self.ENDGAME_START)

        # ── Generate orders ───────────────────────────────────────────────────
        orders: Dict[str, List[Order]] = {}

        pepper_orders = self._trade_pepper(state, ts, pepper_fair, is_endgame)
        if pepper_orders:
            orders[self.PEPPER] = pepper_orders

        osmium_orders = self._trade_osmium(state)
        if osmium_orders:
            orders[self.OSMIUM] = osmium_orders

        data["last_ts"] = ts
        return orders, 0, json.dumps(data)

    # ══════════════════════════════════════════════════════════════════════════
    # PEPPER helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _pepper_mid(self, state: TradingState) -> float:
        """
        [CHANGE A] Anchor to order-book mid, not the best ask.
        v4 used min(sell_orders) as the anchor, which adds a systematic upward
        bias equal to the half-spread (~7.5 ticks). Using mid ensures our
        fair-value model starts at the true market consensus.
        """
        od = state.order_depths.get(self.PEPPER, OrderDepth())
        best_bid = max(od.buy_orders.keys())  if od.buy_orders  else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        if best_ask is not None:
            return float(best_ask)
        if best_bid is not None:
            return float(best_bid)
        return 12_000.0

    def _trade_pepper(
        self,
        state: TradingState,
        ts: int,
        fair: float,
        is_endgame: bool,
    ) -> List[Order]:
        od  = state.order_depths.get(self.PEPPER, OrderDepth())
        pos = state.position.get(self.PEPPER, 0)
        orders: List[Order] = []

        if not is_endgame:
            # ── ACCUMULATE: buy up to +50, only pay up to fair + TOL ─────────
            # [CHANGE B] TOL=5 ensures we only hit the best ask (and 1 level above
            # at most). v4's TOL=20 swept 3 levels including 12009 (3 ticks dear).
            buy_cap = self.LIMIT - pos
            if buy_cap > 0 and od.sell_orders:
                for ask_price in sorted(od.sell_orders.keys()):
                    if buy_cap <= 0:
                        break
                    if ask_price <= fair + self.PEPPER_BUY_TOL:
                        vol = min(buy_cap, -od.sell_orders[ask_price])
                        if vol > 0:
                            orders.append(Order(self.PEPPER, ask_price, vol))
                            buy_cap -= vol

                # If still not full (e.g., thin book), post a passive bid just
                # below the ask so the next inbound sell fills us at a better price.
                # [Rook-E1: "Your order must be attractive enough to be matched."]
                if buy_cap > 0 and od.sell_orders:
                    best_ask = min(od.sell_orders.keys())
                    passive_bid = best_ask - 1
                    # Only post if it's within tolerance of fair
                    if passive_bid >= fair - self.PEPPER_BUY_TOL:
                        orders.append(Order(self.PEPPER, passive_bid, buy_cap))

        else:
            # ── ENDGAME UNWIND ────────────────────────────────────────────────
            # [CHANGE D] Earlier start (ts ≥ 95_000 vs 99_000) gives 50 ticks
            # instead of 9. That lets us sell ~1 lot/tick at the bid, which is
            # less disruptive than dumping everything in the last few ticks.
            #
            # [Rook-E1: "Your order is the final one. It affects the clearing
            # price itself. Volume decides first. Price follows."]
            if pos > 0 and od.buy_orders:
                ticks_remaining = max(1, (self.MAX_TIMESTAMP - ts) // 100 + 1)
                # Sell 1.5× the per-tick quota to clear with a small buffer.
                per_tick = math.ceil(pos / ticks_remaining)
                to_sell  = min(pos, per_tick + max(1, per_tick // 2))

                sell_left = to_sell
                for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                    if sell_left <= 0:
                        break
                    vol = min(sell_left, od.buy_orders[bid_price])
                    if vol > 0:
                        orders.append(Order(self.PEPPER, bid_price, -vol))
                        sell_left -= vol

                # Safety: on very last tick force-sell everything remaining.
                if ts >= self.MAX_TIMESTAMP - 100 and pos > 0 and od.buy_orders:
                    best_bid = max(od.buy_orders.keys())
                    leftover = pos - to_sell + sell_left
                    if leftover > 0:
                        orders.append(Order(self.PEPPER, best_bid, -leftover))

        return orders

    # ══════════════════════════════════════════════════════════════════════════
    # OSMIUM market maker
    # ══════════════════════════════════════════════════════════════════════════

    def _trade_osmium(self, state: TradingState) -> List[Order]:
        od  = state.order_depths.get(self.OSMIUM, OrderDepth())
        pos = state.position.get(self.OSMIUM, 0)
        orders: List[Order] = []

        best_bid = max(od.buy_orders.keys())  if od.buy_orders  else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        # Fair value: mid-price or fallback
        if best_bid is not None and best_ask is not None:
            fair = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            fair = best_bid + self.OSM_MM_HALF
        elif best_ask is not None:
            fair = best_ask - self.OSM_MM_HALF
        else:
            fair = float(self.OSM_FALLBACK)

        fair_int = round(fair)
        buy_cap  = self.LIMIT - pos
        sell_cap = self.LIMIT + pos

        # ── AGGRESSIVE TAKE: mean reversion ──────────────────────────────────
        # [CHANGE E] Threshold 6 ticks (was 8). With osmium std ≈ 5–6 ticks,
        # 6-tick fills occur regularly; 8-tick fills were too rare.
        # [Rook-E1: "Add volume at the right level and the balance tips."]
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p <= fair_int - self.OSM_MR_THRESH and buy_cap > 0:
                    vol = min(buy_cap, -od.sell_orders[ask_p])
                    if vol > 0:
                        orders.append(Order(self.OSMIUM, ask_p, vol))
                        buy_cap -= vol
                else:
                    break

        if od.buy_orders:
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                if bid_p >= fair_int + self.OSM_MR_THRESH and sell_cap > 0:
                    vol = min(sell_cap, od.buy_orders[bid_p])
                    if vol > 0:
                        orders.append(Order(self.OSMIUM, bid_p, -vol))
                        sell_cap -= vol
                else:
                    break

        # ── PASSIVE MM: inventory-skewed two-sided quotes ─────────────────────
        # [CHANGE E/F] OSM_MM_HALF=3 (tighter spread = more fills).
        # Skew ∈ [–4, +4] instead of [–3, +3] for faster inventory reversion.
        # [Rook-E1: "Nudge the price closer to the other side until you become
        # interesting. Price, size, and timing all influence that balance."]
        skew = round(pos / self.LIMIT * self.OSM_SKEW_MAX)

        mm_bid = fair_int - self.OSM_MM_HALF - skew
        mm_ask = fair_int + self.OSM_MM_HALF - skew

        # Guard: never cross our own quotes or the live market
        if mm_bid >= mm_ask:
            mm_bid = fair_int - 1
            mm_ask = fair_int + 1

        # Don't post inside the live spread (that would be a marketable order —
        # we want passive fills, not aggressive takes at MM prices).
        if best_ask is not None and mm_bid >= best_ask:
            mm_bid = best_ask - 1
        if best_bid is not None and mm_ask <= best_bid:
            mm_ask = best_bid + 1

        if buy_cap > 0:
            orders.append(Order(self.OSMIUM, mm_bid,  buy_cap))
        if sell_cap > 0:
            orders.append(Order(self.OSMIUM, mm_ask, -sell_cap))

        return orders
