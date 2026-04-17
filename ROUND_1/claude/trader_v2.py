# trader_v2.py  —  Optimized from log analysis of submission 197739
#
# LOG ANALYSIS FINDINGS:
#
# TIMESTAMP SCALE (CRITICAL FIX):
#   - Day runs ts=0 to ts=99900 in steps of 100 → 1,000 ticks per day total
#   - Previous ENDGAME_TS = 990,000 was 10x too large → endgame NEVER fired
#   - Fix: ENDGAME_TS = 99000
#
# INTARIAN_PEPPER_ROOT (the big fix):
#   - Price rises ~101 ticks over the full day (11998 → 12099)
#   - TREND_RATE = 0.001001 per timestamp is confirmed correct
#   - BUG: condition "best_ask <= fair + 2" NEVER triggered in early timestamps
#     because ask = mid + 8 ticks (half of 16-tick spread) = always > fair+2
#     Result: algo only reached +50 at ts=41300 (41% through the day!)
#     Every timestamp of delay cost us ~0.05 ticks/unit of missed appreciation
#   - FIX: Remove the fair+2 gate. Just lift the ask aggressively until +50.
#     Ask volume is 8-20 units per step, so we hit +50 in 3-6 timestamps.
#
# ASH_COATED_OSMIUM (minor tuning):
#   - Mean reversion is working fine (max deviation confirmed at ±8.5 from 10000)
#   - Market spread avg=16.3, our fills avg buy=9994 avg sell=10004 → 10 tick edge
#   - TUNE: Slightly tighter quoting (±4 ticks instead of ±5) to increase fill rate
#   - REV_ENTRY threshold lowered from 12 to 8 (max dev is only 8.5, 12 rarely hits)

from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json


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

        PEPPER = "INTARIAN_PEPPER_ROOT"
        OSMIUM = "ASH_COATED_OSMIUM"

        # FIXED: Day runs 0→99900 (100k ticks). Endgame at 99% = ts 99000.
        ENDGAME_TS = 99000
        TREND_RATE = 0.001001  # confirmed: ~100 ticks rise per 100k timestamps

        # =====================================================================
        # INTARIAN PEPPER ROOT — Aggressive Accumulation + Trend Hold
        # =====================================================================
        # Strategy:
        #   Phase 1 (ts < ENDGAME_TS): Get to +50 ASAP by lifting asks.
        #                               Once at +50, hold. Trim ONLY if very far above fair.
        #   Phase 2 (ts >= ENDGAME_TS): Flatten position by hitting bids.
        #
        # KEY FIX: No "fair+2" gate on buys. We want +50 from the first few timestamps.
        # The ask is always ~8 ticks above mid due to spread — gating on fair+2 was
        # preventing ALL fills early on.

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

                # Anchor fair value to first observed mid each day.
                # Re-anchor if price has jumped >200 ticks (new day detected).
                anchor_key = "pepper_anchor"
                anchor_ts_key = "pepper_anchor_ts"
                if anchor_key not in data:
                    data[anchor_key] = mid
                    data[anchor_ts_key] = ts
                if abs(mid - data[anchor_key]) > 200:
                    data[anchor_key] = mid
                    data[anchor_ts_key] = ts

                anchor_price = data[anchor_key]
                anchor_ts    = data[anchor_ts_key]
                fair = anchor_price + TREND_RATE * (ts - anchor_ts)

                # ---------- ENDGAME: flatten ----------
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
                    buy_cap = limit - pos

                    if buy_cap > 0:
                        # FIXED: Always lift the ask aggressively — no fair+2 gate.
                        # The ask is always ~8 ticks above mid, gating on fair+2 was
                        # preventing fills until ts=41300 (41% through the day).
                        # Cap at 20 per order to stay within typical ask_vol.
                        qty = min(buy_cap, ask_vol, 20)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))
                            buy_cap -= qty

                        # Secondary passive bid to catch any extra volume
                        if buy_cap > 0:
                            passive_bid = int(fair - 2)
                            if passive_bid < best_ask:
                                qty2 = min(buy_cap, 10)
                                orders.append(Order(PEPPER, passive_bid, qty2))

                    # Trim only if wildly above fair (price collapsed behind trend)
                    # Threshold raised to 20 to avoid premature sells
                    sell_cap = limit + pos
                    if pos > 0 and best_bid > fair + 20 and sell_cap > 0:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — Tight Market Making + Mean Reversion
        # =====================================================================
        # Log confirms: max deviation = ±8.5 from 10000, avg spread = 16.3 ticks.
        # TUNED: REV_ENTRY lowered from 12 → 8 to actually trigger on real extremes.
        #        MM offset tightened from 5 → 4 to increase fill frequency.
        #        Second level at 8 (was 9) for same reason.

        OSM_FAIR        = 10000.0
        OSM_MM_OFFSET   = 4       # quote 4 ticks from fair (was 5)
        OSM_MM_SIZE     = 12
        OSM_REV_ENTRY   = 8       # mean revert at ±8 from fair (was 12; max dev = 8.5)
        OSM_REV_SIZE    = 20
        OSM_UNWIND_FRAC = 0.7     # unwind pressure at 70% of limit (unchanged)

        if OSMIUM in state.order_depths:
            od = state.order_depths[OSMIUM]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                bid_vol  = od.buy_orders[best_bid]
                ask_vol  = abs(od.sell_orders[best_ask])
                mid      = (best_bid + best_ask) / 2.0
                pos      = state.position.get(OSMIUM, 0)
                limit    = LIMITS[OSMIUM]
                ts       = state.timestamp
                orders   = []

                # Volume-weighted micro-price
                total_vol = bid_vol + ask_vol
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol \
                            if total_vol > 0 else mid

                # Blend slow EMA toward stable 10000 fair
                osm_ema_key = "osm_ema"
                data[osm_ema_key] = 0.02 * micro_mid + 0.98 * data.get(osm_ema_key, OSM_FAIR)
                fair = data[osm_ema_key]

                # ---------- ENDGAME: flatten ----------
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

                    # ---- Mean reversion on extreme deviations ----
                    if best_ask <= fair - OSM_REV_ENTRY:
                        qty = min(buy_cap, ask_vol, OSM_REV_SIZE)
                        if qty > 0:
                            orders.append(Order(OSMIUM, best_ask, qty))
                            buy_cap -= qty

                    elif best_bid >= fair + OSM_REV_ENTRY:
                        qty = min(sell_cap, bid_vol, OSM_REV_SIZE)
                        if qty > 0:
                            orders.append(Order(OSMIUM, best_bid, -qty))
                            sell_cap -= qty

                    else:
                        # ---- Market making: 2 levels, inventory-skewed ----
                        inventory_skew = int(pos / limit * 2)

                        for level in range(2):
                            offset = OSM_MM_OFFSET + level * 4  # 4, 8 (was 5, 9)
                            size   = max(3, OSM_MM_SIZE // (level + 1))

                            buy_price  = int(fair - offset - inventory_skew)
                            sell_price = int(fair + offset - inventory_skew)

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

                    # ---- Inventory pressure: unwind when too skewed ----
                    if abs(pos) >= limit * OSM_UNWIND_FRAC:
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
