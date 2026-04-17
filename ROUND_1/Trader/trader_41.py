# trader.py - Multi-Day Trend Reset (Target: 12,000+)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json

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

        # Day boundary detection threshold (Pepper gaps down ~100 points at day reset)
        DAY_GAP_THRESHOLD = 80
        TREND_RATE = 0.001001

        # Endgame window: start unwinding at 90% of day, end at 99.9%
        ENDGAME_START = 90000
        ENDGAME_END   = 99900

        # =====================================================================
        # INTARIAN PEPPER ROOT — Multi‑Day Trend Riding
        # =====================================================================
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

                # Initialize state
                anchor_key = "pepper_anchor"
                anchor_ts_key = "pepper_anchor_ts"
                last_mid_key = "pepper_last_mid"

                if anchor_key not in data:
                    data[anchor_key] = mid
                    data[anchor_ts_key] = ts
                    data[last_mid_key] = mid

                # Detect new day: price dropped significantly since last tick
                if mid < data[last_mid_key] - DAY_GAP_THRESHOLD:
                    # New day! Reset anchor to current price
                    data[anchor_key] = mid
                    data[anchor_ts_key] = ts

                data[last_mid_key] = mid

                anchor_price = data[anchor_key]
                anchor_ts    = data[anchor_ts_key]
                fair = anchor_price + TREND_RATE * (ts - anchor_ts)

                # Graduated endgame: linearly reduce target position to zero
                if ts >= ENDGAME_START:
                    progress = min(1.0, (ts - ENDGAME_START) / (ENDGAME_END - ENDGAME_START))
                    target_pos = int(pos * (1 - progress)) if pos > 0 else 0
                    if pos > target_pos:
                        sell_qty = pos - target_pos
                        # Use limit orders at favorable prices
                        for price in sorted(od.buy_orders.keys(), reverse=True):
                            if sell_qty <= 0:
                                break
                            vol = od.buy_orders[price]
                            qty = min(sell_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(PEPPER, price, -qty))
                                sell_qty -= qty
                else:
                    buy_cap = limit - pos

                    # Aggressively go max long
                    if buy_cap > 0:
                        # Lift the ask with max size (up to 30 per tick)
                        qty = min(buy_cap, ask_vol, 30)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))
                            buy_cap -= qty

                        # Tight passive bid to catch any dips
                        if buy_cap > 0:
                            passive_bid = int(fair - 1)
                            if passive_bid < best_ask:
                                qty2 = min(buy_cap, 15)
                                orders.append(Order(PEPPER, passive_bid, qty2))

                    # Trim only if wildly above fair (unlikely)
                    sell_cap = limit + pos
                    if pos > 0 and best_bid > fair + 30 and sell_cap > 0:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — Maximum Safe Aggression
        # =====================================================================
        OSM_FAIR        = 10000.0
        OSM_MM_OFFSET   = 2       # Ultra‑tight for max fills
        OSM_MM_SIZE     = 16      # Larger base size
        OSM_REV_ENTRY   = 8       
        OSM_REV_SIZE    = 30      # Maximum aggression on mean reversion
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

                total_vol = bid_vol + ask_vol
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol if total_vol > 0 else mid

                osm_ema_key = "osm_ema"
                data[osm_ema_key] = 0.02 * micro_mid + 0.98 * data.get(osm_ema_key, OSM_FAIR)
                fair = data[osm_ema_key]

                # Graduated endgame
                if ts >= ENDGAME_START:
                    progress = min(1.0, (ts - ENDGAME_START) / (ENDGAME_END - ENDGAME_START))
                    target_pos = int(pos * (1 - progress)) if pos > 0 else int(pos * (1 - progress))
                    if pos > target_pos:
                        sell_qty = pos - target_pos
                        for price in sorted(od.buy_orders.keys(), reverse=True):
                            if sell_qty <= 0:
                                break
                            vol = od.buy_orders[price]
                            qty = min(sell_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(OSMIUM, price, -qty))
                                sell_qty -= qty
                    elif pos < target_pos:
                        buy_qty = target_pos - pos
                        for price in sorted(od.sell_orders.keys()):
                            if buy_qty <= 0:
                                break
                            vol = abs(od.sell_orders[price])
                            qty = min(buy_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(OSMIUM, price, qty))
                                buy_qty -= qty
                else:
                    buy_cap  = limit - pos
                    sell_cap = limit + pos

                    # Mean reversion
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
                        inventory_skew = int(pos / limit * 2)
                        for level in range(2):
                            offset = OSM_MM_OFFSET + level * 4  # 2 and 6
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