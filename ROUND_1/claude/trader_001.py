# trader.py - Dynamic Osmium Spread Capture (Target: 12,000+ XIRECs)
import json
import math
from typing import Dict, List, Optional
from ROUND_1.datamodel import OrderDepth, TradingState, Order

class Trader:
    PEPPER = "INTARIAN_PEPPER_ROOT"
    OSMIUM = "ASH_COATED_OSMIUM"
    LIMIT  = 50

    # Pepper parameters
    PEPPER_SLOPE        = 0.001
    PEPPER_BUY_TOL      = 8       # tightened from 15 -> reduces entry slippage
    PEPPER_PASSIVE_TOL  = 3       # place a passive limit this many ticks above fair

    # Osmium parameters
    OSM_FAIR_FALLBACK   = 10_000
    OSM_EMA_ALPHA       = 0.04    # faster EMA (was 0.015) for tighter fair value tracking
    OSM_L1_SIZE         = 15
    OSM_L2_SIZE         = 12
    OSM_L3_SIZE         = 8
    OSM_MR_THRESH       = 6       # tightened from 8 -> more frequent mean-reversion fills
    OSM_MR_MAX_QTY      = 20
    OSM_SKEW_FACTOR     = 0.06

    # Timing
    ROUND_DAYS          = 3
    MAX_TS              = 99_900
    ENDGAME_START       = 95_000  # start unwinding earlier (was 97_000)
    NEW_DAY_THRESH      = 10_000

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

        if "pepper_anchor" not in data:
            data["pepper_anchor"] = self._pepper_anchor(state)

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

    def _pepper_anchor(self, state: TradingState) -> float:
        """
        VWAP of best 3 ask levels for a more representative anchor price.
        Falls back to best ask, then best bid, then default.
        """
        od = state.order_depths.get(self.PEPPER, OrderDepth())
        if od.sell_orders:
            total_val = 0.0
            total_vol = 0
            for px in sorted(od.sell_orders.keys()):
                vol = abs(od.sell_orders[px])
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
            if buy_cap <= 0:
                return orders

            # Phase 1: aggressive sweep of asks within tolerance
            if od.sell_orders:
                for ask_px in sorted(od.sell_orders.keys()):
                    if buy_cap <= 0:
                        break
                    if ask_px <= fair + self.PEPPER_BUY_TOL:
                        vol = min(buy_cap, -od.sell_orders[ask_px])
                        if vol > 0:
                            orders.append(Order(self.PEPPER, ask_px, vol))
                            buy_cap -= vol

            # Phase 2: if still not full, place a passive limit just above fair
            # to get filled without chasing too far
            if buy_cap > 0:
                passive_px = int(math.floor(fair + self.PEPPER_PASSIVE_TOL))
                # only post if it doesn't cross into the market aggressively
                best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
                if best_ask is None or passive_px < best_ask:
                    orders.append(Order(self.PEPPER, passive_px, buy_cap))
                else:
                    # cross at best ask as last resort (was original fallback)
                    orders.append(Order(self.PEPPER, best_ask, buy_cap))
        else:
            if pos > 0 and od.buy_orders:
                ticks_left    = max(1, (self.MAX_TS - ts) // 100 + 1)
                # sell faster: use ceil and a higher multiplier (3x instead of 2x)
                per_tick_sell = math.ceil(pos / ticks_left)
                to_sell       = min(pos, per_tick_sell * 3)
                remaining = to_sell
                for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                    if remaining <= 0:
                        break
                    vol = min(remaining, od.buy_orders[bid_px])
                    if vol > 0:
                        orders.append(Order(self.PEPPER, bid_px, -vol))
                        remaining -= vol

                # emergency dump: ensure full exit well before last tick
                if ts >= self.MAX_TS - 500 and pos > 0:
                    leftover = pos - (to_sell - remaining)
                    if leftover > 0 and od.buy_orders:
                        best_bid = max(od.buy_orders.keys())
                        orders.append(Order(self.PEPPER, best_bid, -leftover))
        return orders

    def _osmium_orders(self, state: TradingState, data: dict) -> List[Order]:
        od  = state.order_depths.get(self.OSMIUM, OrderDepth())
        pos = state.position.get(self.OSMIUM, 0)
        orders: List[Order] = []

        best_bid: Optional[int] = max(od.buy_orders.keys())  if od.buy_orders  else None
        best_ask: Optional[int] = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            # micro-price: weight mid by opposite-side depth for a less noisy fair
            bid_vol = od.buy_orders[best_bid]
            ask_vol = abs(od.sell_orders[best_ask])
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                raw_mid = (best_ask * bid_vol + best_bid * ask_vol) / total_vol
            else:
                raw_mid = (best_bid + best_ask) / 2.0
            current_spread = best_ask - best_bid
        elif best_bid is not None:
            raw_mid        = best_bid + 4
            current_spread = 16
        elif best_ask is not None:
            raw_mid        = best_ask - 4
            current_spread = 16
        else:
            raw_mid        = float(self.OSM_FAIR_FALLBACK)
            current_spread = 16

        prev_ema = data.get("osm_ema", float(self.OSM_FAIR_FALLBACK))
        ema      = prev_ema + self.OSM_EMA_ALPHA * (raw_mid - prev_ema)
        data["osm_ema"] = ema
        fair     = round(ema)

        buy_cap  = self.LIMIT - pos
        sell_cap = self.LIMIT + pos

        # Mean-reversion: take mispriced liquidity
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

        skew = int(max(-6, min(6, pos * self.OSM_SKEW_FACTOR)))

        # Dynamic offsets based on current spread
        spread_factor = current_spread / 16.0
        dyn_l1 = max(2, min(4, round(3 * spread_factor)))   # tighter L1 (was 4*sf, floor 3)
        dyn_l2 = max(4, min(8, round(6 * spread_factor)))   # tighter L2 (was 7*sf, floor 5)
        dyn_l3 = max(8, min(12, round(10 * spread_factor)))  # tighter L3 (was 11*sf, floor 9)

        levels = [
            (dyn_l1, self.OSM_L1_SIZE),
            (dyn_l2, self.OSM_L2_SIZE),
            (dyn_l3, self.OSM_L3_SIZE),
        ]

        long_bias = pos / self.LIMIT

        for offset, base_size in levels:
            if buy_cap <= 0 and sell_cap <= 0:
                break

            bid_px = fair - offset - skew
            ask_px = fair + offset - skew

            if bid_px >= ask_px:
                bid_px = fair - 1
                ask_px = fair + 1

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