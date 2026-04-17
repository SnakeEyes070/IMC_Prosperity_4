# trader.py - Rook‑E1 Enhanced (Target: 12,000+)
# Lesson 1 (Spotting Trends): Commit early to Pepper's linear pattern.
# Lesson 2 (Strategic Orders): Make your Osmium quotes the logical choice.
# Lesson 3 (Auction Dynamics): Unwind gradually with limit orders.

from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except Exception:
                pass

        PEPPER = "INTARIAN_PEPPER_ROOT"
        OSMIUM = "ASH_COATED_OSMIUM"

        # Timestamp scale: 0 → 99,900 per day, steps of 100
        ENDGAME_START = 97_000      # Start unwinding a bit earlier to be gradual
        MAX_TIMESTAMP = 99_900
        TREND_RATE = 0.001001       # ~100 pts per day
        DAY_GAP_THRESHOLD = 80      # Pepper gaps down ~100 pts at day reset

        # =====================================================================
        # PEPPER – Commit Early, Hold, Unwind Gradually
        # =====================================================================
        # Rook‑E1: "You do not need to predict every outcome. You only need to
        # rule out enough of them." Pepper's trend is reliable – commit fully.

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

                # ----- Robust Day Detection -----
                last_ts_key = "pepper_last_ts"
                last_mid_key = "pepper_last_mid"
                anchor_key = "pepper_anchor"
                anchor_ts_key = "pepper_anchor_ts"
                day_count_key = "pepper_day_count"

                if anchor_key not in data:
                    data[anchor_key] = mid
                    data[anchor_ts_key] = ts
                    data[last_ts_key] = ts
                    data[last_mid_key] = mid
                    data[day_count_key] = 0

                # New day if timestamp reset OR price gapped down significantly
                if ts < data[last_ts_key] or mid < data[last_mid_key] - DAY_GAP_THRESHOLD:
                    data[anchor_key] = mid
                    data[anchor_ts_key] = ts
                    data[day_count_key] += 1

                data[last_ts_key] = ts
                data[last_mid_key] = mid

                anchor_price = data[anchor_key]
                anchor_ts    = data[anchor_ts_key]
                fair = anchor_price + TREND_RATE * (ts - anchor_ts)

                # ----- Endgame Unwind (Final Day Only) -----
                # Rook‑E1: "Your order is the final move. It affects the clearing
                # price itself." Unwind gradually with limit orders to avoid
                # distorting the auction.
                is_final_day = (data[day_count_key] >= 2)   # 0-indexed: 0,1,2 → 3 days total
                is_endgame = is_final_day and ts >= ENDGAME_START

                if is_endgame:
                    if pos > 0:
                        # Gradual: target ~2 units per tick on average
                        ticks_left = max(1, (MAX_TIMESTAMP - ts) // 100 + 1)
                        target_sell = min(pos, math.ceil(pos / ticks_left) * 2)
                        sell_left = target_sell
                        for price in sorted(od.buy_orders.keys(), reverse=True):
                            if sell_left <= 0:
                                break
                            vol = min(sell_left, od.buy_orders[price])
                            if vol > 0:
                                orders.append(Order(PEPPER, price, -vol))
                                sell_left -= vol
                else:
                    # ----- Instant Max Long Accumulation -----
                    # Wide tolerance (20) ensures we fill 50 units immediately.
                    # The tiny slippage is irrelevant compared to missing the trend.
                    buy_cap = limit - pos
                    if buy_cap > 0:
                        # Lift the best ask aggressively
                        qty = min(buy_cap, ask_vol, 30)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))
                            buy_cap -= qty

                        # Attractive passive bid (Rook‑E1: "Make your bid worth accepting now")
                        if buy_cap > 0:
                            passive_bid = int(fair - 2)
                            if passive_bid < best_ask:
                                qty2 = min(buy_cap, 15)
                                orders.append(Order(PEPPER, passive_bid, qty2))

                    # Trim only if wildly overbought (unlikely)
                    if pos > 0 and best_bid > fair + 30:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # OSMIUM – Ultra‑Competitive Quotes
        # =====================================================================
        # Rook‑E1: "Nudge the price closer to the other side until you become
        # interesting." With avg spread ~16, offset 2 makes us the logical choice.

        OSM_FAIR        = 10000.0
        OSM_MM_OFFSET   = 2       # Ultra‑tight: we are the best quote
        OSM_MM_SIZE     = 16      # Larger passive size
        OSM_REV_ENTRY   = 5       # Take mispricings aggressively
        OSM_REV_SIZE    = 28      # Large size on mean reversion
        OSM_UNWIND_FRAC = 0.6

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

                # Volume‑weighted micro‑price for better fair value
                total_vol = bid_vol + ask_vol
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol if total_vol > 0 else mid

                osm_ema_key = "osm_ema"
                data[osm_ema_key] = 0.02 * micro_mid + 0.98 * data.get(osm_ema_key, OSM_FAIR)
                fair = data[osm_ema_key]

                # Endgame flattening (same as Pepper)
                if ts >= ENDGAME_START:
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

                    # Aggressive mean reversion (take mispriced quotes)
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
                        # Core market making – ultra‑tight, inventory‑skewed
                        inventory_skew = int(pos / limit * 2)
                        for level in range(2):
                            offset = OSM_MM_OFFSET + level * 3   # 2 and 5
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

                    # Inventory pressure
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