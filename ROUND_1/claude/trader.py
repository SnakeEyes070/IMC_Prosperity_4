import json
import math
from typing import Dict, List, Optional

from ROUND_1.datamodel import OrderDepth, TradingState, Order


class Trader:

    PEPPER = "INTARIAN_PEPPER_ROOT"
    OSMIUM = "ASH_COATED_OSMIUM"

    LIMIT = 50

    # CRITICAL CHANGE 1: Lower tolerance to 8 (was 15).
    # Log shows open asks at 12006/12009 vs mid ~11998.5.
    # Anchoring to VWAP-mid lets us use a tighter tolerance while still sweeping.
    PEPPER_BUY_TOL   = 8
    PEPPER_SLOPE     = 0.001

    # CRITICAL CHANGE 2: Start unwind earlier (90000 vs 99000) and sell faster.
    # Log shows only day 0 contributed well; days 1+2 leaked exit value badly.
    ENDGAME_START    = 90_000
    ENDGAME_SELL_MULTIPLIER = 3  # sell 3× the minimum pace to front-load exits

    OSM_FAIR_FALLBACK = 10_000

    # CRITICAL CHANGE 3: Faster EMA (0.04 vs 0.015) + micro-price fair value.
    # Slow EMA caused stale quotes; micro-price better weights where volume sits.
    OSM_EMA_ALPHA    = 0.04

    # Tighter L1 at ±3 to capture more fills; MR threshold lowered to 6.
    OSM_L1_OFFSET    = 3
    OSM_L2_OFFSET    = 6
    OSM_L3_OFFSET    = 10

    OSM_L1_SIZE      = 18
    OSM_L2_SIZE      = 14
    OSM_L3_SIZE      = 8

    # Lower MR threshold fires more often on the ±10-20 tick swings seen in log.
    OSM_MR_THRESH    = 6
    OSM_MR_MAX_QTY   = 20

    OSM_SKEW_FACTOR  = 0.05

    ROUND_DAYS       = 3
    MAX_TS           = 99_900
    NEW_DAY_THRESH   = 10_000

    def run(self, state: TradingState):
        try:
            data: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            data = {}

        ts      = state.timestamp
        prev_ts = data.get("last_ts", -1)
        day     = data.get("day", 0)

        if prev_ts > self.NEW_DAY_THRESH and ts < self.NEW_DAY_THRESH:
            day += 1
            data["day"] = day
            data.pop("pepper_anchor", None)

        # CRITICAL CHANGE 1: Anchor to VWAP-weighted mid of open book, not just best ask.
        # This gives a fairer cost basis and lets the tighter tolerance still sweep the book.
        if "pepper_anchor" not in data:
            data["pepper_anchor"] = self._pepper_open_price(state)

        pepper_fair = data["pepper_anchor"] + self.PEPPER_SLOPE * ts

        is_last_day = (day >= self.ROUND_DAYS - 1)
        is_endgame  = is_last_day and (ts >= self.ENDGAME_START)

        orders: Dict[str, List[Order]] = {}

        pepper_ords = self._pepper_orders(state, ts, pepper_fair, is_endgame)
        if pepper_ords:
            orders[self.PEPPER] = pepper_ords

        osmium_ords = self._osmium_orders(state, data)
        if osmium_ords:
            orders[self.OSMIUM] = osmium_ords

        data["last_ts"] = ts
        return orders, 0, json.dumps(data)

    # ── PEPPER ────────────────────────────────────────────────────────────────

    def _pepper_open_price(self, state: TradingState) -> float:
        """
        CRITICAL CHANGE 1: Use VWAP of best 2 ask levels as anchor instead of
        just best ask. This gives a fair-value anchor ≈ mid rather than ≈ ask,
        so our tolerance budget is spent efficiently.
        """
        od = state.order_depths.get(self.PEPPER, OrderDepth())
        if od.sell_orders:
            sorted_asks = sorted(od.sell_orders.keys())
            total_vol = 0
            total_val = 0.0
            for px in sorted_asks[:3]:
                vol = abs(od.sell_orders[px])
                total_vol += vol
                total_val += px * vol
            if total_vol > 0:
                ask_vwap = total_val / total_vol
            else:
                ask_vwap = float(sorted_asks[0])

            if od.buy_orders:
                best_bid = float(max(od.buy_orders.keys()))
                # Anchor to mid between best bid and ask VWAP
                return (best_bid + ask_vwap) / 2.0
            return ask_vwap - 8.0

        if od.buy_orders:
            return float(max(od.buy_orders.keys()))
        return 12_000.0

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

                # Resting order at best ask to catch any fills next tick
                if buy_cap > 0 and od.sell_orders:
                    best_ask = min(od.sell_orders.keys())
                    orders.append(Order(self.PEPPER, best_ask, buy_cap))

        else:
            # CRITICAL CHANGE 2: Earlier and faster endgame unwind.
            # Start at ts=90000 (900 ticks before end) with 3× pace multiplier.
            # This ensures we exit near peak price rather than dumping in last 10 ticks.
            if pos > 0 and od.buy_orders:
                ticks_left = max(1, (self.MAX_TS - ts) // 100 + 1)
                per_tick_base = math.ceil(pos / ticks_left)
                to_sell = min(pos, per_tick_base * self.ENDGAME_SELL_MULTIPLIER)

                remaining = to_sell
                for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                    if remaining <= 0:
                        break
                    vol = min(remaining, od.buy_orders[bid_px])
                    if vol > 0:
                        orders.append(Order(self.PEPPER, bid_px, -vol))
                        remaining -= vol

                # Force-sell everything in final 200 ticks
                if ts >= self.MAX_TS - 200 and pos > 0:
                    leftover = pos - to_sell + remaining
                    if leftover > 0 and od.buy_orders:
                        best_bid = max(od.buy_orders.keys())
                        orders.append(Order(self.PEPPER, best_bid, -leftover))

        return orders

    # ── OSMIUM ────────────────────────────────────────────────────────────────

    def _osmium_orders(self, state: TradingState, data: dict) -> List[Order]:
        od  = state.order_depths.get(self.OSMIUM, OrderDepth())
        pos = state.position.get(self.OSMIUM, 0)
        orders: List[Order] = []

        best_bid: Optional[int] = max(od.buy_orders.keys())  if od.buy_orders  else None
        best_ask: Optional[int] = min(od.sell_orders.keys()) if od.sell_orders else None

        # CRITICAL CHANGE 3: Micro-price fair value instead of simple mid.
        # Weights mid toward the side with more volume, giving a better signal.
        if best_bid is not None and best_ask is not None:
            bid_vol = od.buy_orders[best_bid]
            ask_vol = abs(od.sell_orders[best_ask])
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                # Micro-price: weight toward the ask when ask volume is larger
                raw_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
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

        buy_cap  = self.LIMIT - pos
        sell_cap = self.LIMIT + pos

        # Aggressive mean-reversion with lower threshold (6 vs 8)
        if od.sell_orders and buy_cap > 0:
            for ask_px in sorted(od.sell_orders.keys()):
                if ask_px > fair - self.OSM_MR_THRESH:
                    break
                vol = min(buy_cap, -od.sell_orders[ask_px], self.OSM_MR_MAX_QTY)
                if vol > 0:
                    orders.append(Order(self.OSMIUM, ask_px, vol))
                    buy_cap -= vol

        if od.buy_orders and sell_cap > 0:
            for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                if bid_px < fair + self.OSM_MR_THRESH:
                    break
                vol = min(sell_cap, od.buy_orders[bid_px], self.OSM_MR_MAX_QTY)
                if vol > 0:
                    orders.append(Order(self.OSMIUM, bid_px, -vol))
                    sell_cap -= vol

        # Inventory-skewed 3-level passive ladder
        skew = int(max(-5, min(5, pos * self.OSM_SKEW_FACTOR)))

        levels = [
            (self.OSM_L1_OFFSET, self.OSM_L1_SIZE),
            (self.OSM_L2_OFFSET, self.OSM_L2_SIZE),
            (self.OSM_L3_OFFSET, self.OSM_L3_SIZE),
        ]

        for offset, base_size in levels:
            if buy_cap <= 0 and sell_cap <= 0:
                break

            bid_px = fair - offset - skew
            ask_px = fair + offset - skew

            if bid_px >= ask_px:
                bid_px = fair - 1
                ask_px = fair + 1

            long_bias = pos / self.LIMIT

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