# trader.py - Calibrated Claude Algorithm (Target: 6,500–7,000)
# Adjusted: L1 offset 2→3, L2 offset 4→5, sizes reduced, MR threshold 6→7, Pepper endgame 97,000

import json
import math
from typing import Dict, List, Optional

from ROUND_1.datamodel import OrderDepth, TradingState, Order

class Trader:
    PEPPER = "INTARIAN_PEPPER_ROOT"
    OSMIUM = "ASH_COATED_OSMIUM"
    LIMIT = 50

    PEPPER_SLOPE   = 0.001
    PEPPER_BUY_TOL = 18          # Slightly wider

    OSM_ALPHA      = 0.01
    OSM_FALLBACK   = 10_000
    OSM_MR_THRESH  = 7           # Less aggressive
    OSM_MR_MAX     = 20

    # Adjusted offsets and sizes
    OSM_LEVELS     = [(3, 14), (5, 12), (7, 10), (10, 8)]

    OSM_INV_SCALE  = 0.65

    ROUND_DAYS     = 3
    MAX_TS         = 99_900
    ENDGAME_START  = 97_000      # Earlier unwind
    DAY_RESET_THRESH = 10_000

    def run(self, state: TradingState):
        try:
            data: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            data = {}

        ts      = state.timestamp
        prev_ts = data.get("last_ts", -1)
        day     = data.get("day", 0)

        if prev_ts > self.DAY_RESET_THRESH and ts < self.DAY_RESET_THRESH:
            day += 1
            data["day"] = day
            data.pop("pepper_anchor", None)

        if "pepper_anchor" not in data:
            data["pepper_anchor"] = self._pepper_anchor(state)

        pepper_fair = data["pepper_anchor"] + self.PEPPER_SLOPE * ts

        is_last_day = (day >= self.ROUND_DAYS - 1)
        is_endgame  = is_last_day and (ts >= self.ENDGAME_START)

        orders: Dict[str, List[Order]] = {}

        p_ords = self._pepper_orders(state, ts, pepper_fair, is_endgame)
        if p_ords:
            orders[self.PEPPER] = p_ords

        o_ords = self._osmium_orders(state, data)
        if o_ords:
            orders[self.OSMIUM] = o_ords

        data["last_ts"] = ts
        return orders, 0, json.dumps(data)

    def _pepper_anchor(self, state: TradingState) -> float:
        od = state.order_depths.get(self.PEPPER, OrderDepth())
        if od.sell_orders:
            total_val = 0.0
            total_vol = 0
            for px in sorted(od.sell_orders.keys())[:3]:
                vol = -od.sell_orders[px]
                total_val += px * vol
                total_vol += vol
            if total_vol > 0:
                return total_val / total_vol
            return float(min(od.sell_orders.keys()))
        if od.buy_orders:
            return float(max(od.buy_orders.keys()))
        return 12_000.0

    def _pepper_orders(self, state: TradingState, ts: int, fair: float, is_endgame: bool) -> List[Order]:
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
                if buy_cap > 0:
                    best_ask = min(od.sell_orders.keys())
                    orders.append(Order(self.PEPPER, best_ask, buy_cap))
        else:
            if pos > 0 and od.buy_orders:
                ticks_left = max(1, (self.MAX_TS - ts) // 100 + 1)
                per_tick = math.ceil(pos / ticks_left)
                to_sell = min(pos, per_tick * 2)
                remaining = to_sell
                for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                    if remaining <= 0:
                        break
                    vol = min(remaining, od.buy_orders[bid_px])
                    if vol > 0:
                        orders.append(Order(self.PEPPER, bid_px, -vol))
                        remaining -= vol
                if ts >= self.MAX_TS - 100 and pos > 0:
                    leftover = pos - to_sell + remaining
                    if leftover > 0:
                        best_bid = max(od.buy_orders.keys())
                        orders.append(Order(self.PEPPER, best_bid, -leftover))
        return orders

    def _osmium_orders(self, state: TradingState, data: dict) -> List[Order]:
        od  = state.order_depths.get(self.OSMIUM, OrderDepth())
        pos = state.position.get(self.OSMIUM, 0)
        orders: List[Order] = []

        best_bid: Optional[int] = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask: Optional[int] = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            bv = od.buy_orders[best_bid]
            av = -od.sell_orders[best_ask]
            raw_mid = (best_bid * av + best_ask * bv) / (bv + av) if (bv + av) > 0 else (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            raw_mid = float(best_bid) + self.OSM_LEVELS[0][0]
        elif best_ask is not None:
            raw_mid = float(best_ask) - self.OSM_LEVELS[0][0]
        else:
            raw_mid = float(self.OSM_FALLBACK)

        ema  = data.get("osm_ema", float(self.OSM_FALLBACK))
        ema += self.OSM_ALPHA * (raw_mid - ema)
        data["osm_ema"] = ema
        fair = round(ema)

        buy_cap  = self.LIMIT - pos
        sell_cap = self.LIMIT + pos

        # Mean reversion
        if od.sell_orders and buy_cap > 0:
            for ask_px in sorted(od.sell_orders.keys()):
                if ask_px > fair - self.OSM_MR_THRESH:
                    break
                vol = min(buy_cap, -od.sell_orders[ask_px], self.OSM_MR_MAX)
                if vol > 0:
                    orders.append(Order(self.OSMIUM, ask_px, vol))
                    buy_cap -= vol

        if od.buy_orders and sell_cap > 0:
            for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                if bid_px < fair + self.OSM_MR_THRESH:
                    break
                vol = min(sell_cap, od.buy_orders[bid_px], self.OSM_MR_MAX)
                if vol > 0:
                    orders.append(Order(self.OSMIUM, bid_px, -vol))
                    sell_cap -= vol

        long_bias = pos / self.LIMIT
        for offset, base_size in self.OSM_LEVELS:
            if buy_cap <= 0 and sell_cap <= 0:
                break
            bid_px = fair - offset
            ask_px = fair + offset
            if bid_px >= ask_px:
                bid_px = fair - 1
                ask_px = fair + 1
            buy_sz  = max(1, round(base_size * (1.0 - max(0.0,  long_bias) * self.OSM_INV_SCALE)))
            sell_sz = max(1, round(base_size * (1.0 - max(0.0, -long_bias) * self.OSM_INV_SCALE)))
            if buy_cap > 0 and bid_px > 0:
                vol = min(buy_sz, buy_cap)
                orders.append(Order(self.OSMIUM, bid_px, vol))
                buy_cap -= vol
            if sell_cap > 0:
                vol = min(sell_sz, sell_cap)
                orders.append(Order(self.OSMIUM, ask_px, -vol))
                sell_cap -= vol

        return orders