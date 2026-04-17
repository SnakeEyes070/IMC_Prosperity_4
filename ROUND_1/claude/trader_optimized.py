# trader_optimized.py  —  Target: 12,000+ profit
#
# KEY FINDINGS FROM DATA ANALYSIS:
#
# INTARIAN_PEPPER_ROOT (the money-maker):
#   - Rises EXACTLY ~1,001 points per day, linearly (+0.001001 per timestamp unit)
#   - Day -2: 10000 → 11001 | Day -1: 11000 → 12000 | Day 0: 12000 → 13000
#   - Deviation from linear trend: std=2.0, max=11.5 (very predictable!)
#   - True fair value = first_observed_mid + 0.001001 * timestamp
#   - Optimal strategy: HOLD MAX LONG (+50) ALL DAY → ~49,000 PnL/day
#   - Current algo problem: EMA lags badly, treats uptrend as "above fair" → SELLS
#
# ASH_COATED_OSMIUM (supporting):
#   - Mean-reverts tightly around 10,000 (std=5, max dev=±23)
#   - Avg spread = 16 ticks, half-spread = 8 — decent MM edge
#   - Optimal: tight market making + aggressive mean reversion at ±10 from 10000
#   - Stop-loss and momentum logic are mostly dead weight given the tight range
#
# COMBINED 3-DAY THEORETICAL MAX (pepper alone): ~147,850
# Realistic target accounting for execution slippage: 12,000–15,000+

from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # =====================================================================
        # PERSISTENT STATE
        # =====================================================================
        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except Exception:
                pass

        # =====================================================================
        # INTARIAN PEPPER ROOT  —  Trend-Riding Strategy
        # =====================================================================
        # The price rises ~0.001001 per timestamp unit every single day.
        # We anchor the fair value on the FIRST mid-price we observe each day
        # and ride the linear trend upward at max long (+50).
        # We flatten only in the final 1% of the day to avoid overnight gap risk.

        PEPPER = "INTARIAN_PEPPER_ROOT"
        OSMIUM = "ASH_COATED_OSMIUM"
        ENDGAME_TS = 990000   # 99% through the day — start closing
        TREND_RATE = 0.001001  # empirically measured ticks-per-timestamp

        if PEPPER in state.order_depths:
            od = state.order_depths[PEPPER]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                bid_vol  = od.buy_orders[best_bid]
                ask_vol  = abs(od.sell_orders[best_ask])
                mid      = (best_bid + best_ask) / 2.0
                pos      = state.position.get(PEPPER, 0)
                limit    = LIMITS[PEPPER]
                ts       = state.timestamp
                orders   = []

                # Anchor fair value at start of each "day" block
                # We detect a new day if EMA anchor is far from current price
                anchor_key = "pepper_anchor"
                if anchor_key not in data:
                    data[anchor_key] = mid

                # If price jumped >800 from anchor, we're in a new day → re-anchor
                if abs(mid - data[anchor_key]) > 800:
                    data[anchor_key] = mid
                    data["pepper_anchor_ts"] = ts

                anchor_ts    = data.get("pepper_anchor_ts", 0)
                anchor_price = data[anchor_key]
                fair = anchor_price + TREND_RATE * (ts - anchor_ts)

                # ---------- ENDGAME: flatten position ----------
                if ts >= ENDGAME_TS:
                    if pos > 0:
                        qty = min(pos, bid_vol)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))
                    elif pos < 0:
                        qty = min(-pos, ask_vol)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))

                else:
                    # ---------- CORE: stay max long ----------
                    # Buy aggressively if below fair (trend dip) or just accumulate
                    buy_capacity = limit - pos

                    if buy_capacity > 0:
                        # Aggressive: lift the ask if ask is at or below fair+2
                        if best_ask <= fair + 2:
                            qty = min(buy_capacity, ask_vol, 20)
                            if qty > 0:
                                orders.append(Order(PEPPER, best_ask, qty))
                                buy_capacity -= qty

                        # Passive: post a buy just below fair to accumulate
                        if buy_capacity > 0:
                            passive_bid = int(fair - 3)
                            if passive_bid < best_ask:
                                qty = min(buy_capacity, 15)
                                orders.append(Order(PEPPER, passive_bid, qty))

                    # Trim only if we're way above fair (price dipped behind trend)
                    sell_capacity = limit + pos
                    if pos > 0 and best_bid > fair + 15:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM  —  Tight Market Making + Mean Reversion
        # =====================================================================
        # Price oscillates around 10,000 with std≈5, max deviation ±23.
        # Spread is wide (~16 ticks) so MM edge is large.
        # True fair value is simply ~10,000 (stable across all 3 days).

        OSM_FAIR = 10000.0
        OSM_MM_OFFSET = 5          # quote 5 ticks inside fair
        OSM_MM_SIZE   = 12         # lots per level
        OSM_REV_ENTRY = 12         # buy/sell when price is 12 ticks off fair
        OSM_REV_SIZE  = 20         # aggressive size on mean reversion
        OSM_TAKE_PROFIT = 8        # take profit when position has moved 8 ticks

        if OSMIUM in state.order_depths:
            od = state.order_depths[OSMIUM]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                bid_vol  = od.buy_orders[best_bid]
                ask_vol  = abs(od.sell_orders[best_ask])
                mid      = (best_bid + best_ask) / 2.0
                spread   = best_ask - best_bid
                pos      = state.position.get(OSMIUM, 0)
                limit    = LIMITS[OSMIUM]
                ts       = state.timestamp
                orders   = []

                # Volume-weighted micro-price
                total_vol = bid_vol + ask_vol
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol if total_vol > 0 else mid

                # Use static fair = 10000 (empirically stable)
                # Slight EMA blend to handle any slow drift
                osm_ema_key = "osm_ema"
                data[osm_ema_key] = 0.02 * micro_mid + 0.98 * data.get(osm_ema_key, OSM_FAIR)
                fair = data[osm_ema_key]

                # ---------- ENDGAME ----------
                if ts >= ENDGAME_TS:
                    if pos > 0:
                        qty = min(pos, bid_vol)
                        if qty > 0:
                            orders.append(Order(OSMIUM, best_bid, -qty))
                    elif pos < 0:
                        qty = min(-pos, ask_vol)
                        if qty > 0:
                            orders.append(Order(OSMIUM, best_ask, qty))

                else:
                    buy_cap  = limit - pos
                    sell_cap = limit + pos

                    # ---- Mean reversion: aggressive on big deviations ----
                    if best_ask <= fair - OSM_REV_ENTRY:
                        # Price is cheap → buy hard
                        qty = min(buy_cap, ask_vol, OSM_REV_SIZE)
                        if qty > 0:
                            orders.append(Order(OSMIUM, best_ask, qty))
                            buy_cap -= qty

                    elif best_bid >= fair + OSM_REV_ENTRY:
                        # Price is expensive → sell hard
                        qty = min(sell_cap, bid_vol, OSM_REV_SIZE)
                        if qty > 0:
                            orders.append(Order(OSMIUM, best_bid, -qty))
                            sell_cap -= qty

                    else:
                        # ---- Core market making (2 levels) ----
                        # Skew quotes based on inventory
                        inventory_skew = int(pos / limit * 2)

                        for level in range(2):
                            offset = OSM_MM_OFFSET + level * 4
                            size   = max(3, OSM_MM_SIZE // (level + 1))

                            buy_price  = int(fair - offset - inventory_skew)
                            sell_price = int(fair + offset - inventory_skew)

                            # Don't cross the spread
                            if buy_price >= best_ask:
                                buy_price = best_ask - 1
                            if sell_price <= best_bid:
                                sell_price = best_bid + 1

                            if buy_cap > 0 and buy_price > 0:
                                qty = min(size, buy_cap)
                                orders.append(Order(OSMIUM, buy_price, qty))
                                buy_cap -= qty

                            if sell_cap > 0:
                                qty = min(size, sell_cap)
                                orders.append(Order(OSMIUM, sell_price, -qty))
                                sell_cap -= qty

                    # ---- Inventory pressure: unwind if too skewed ----
                    if abs(pos) >= limit * 0.7:
                        if pos > 0 and bid_vol > 0:
                            qty = min(pos, bid_vol, 8)
                            if qty > 0:
                                orders.append(Order(OSMIUM, best_bid, -qty))
                        elif pos < 0 and ask_vol > 0:
                            qty = min(-pos, ask_vol, 8)
                            if qty > 0:
                                orders.append(Order(OSMIUM, best_ask, qty))

                result[OSMIUM] = orders

        trader_data = json.dumps(data)
        conversions = 0
        return result, conversions, trader_data
