# trader.py - Calibrated for Maximum Trend Capture (Target: 12,000+)
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

        # =====================================================================
        # INTARIAN PEPPER ROOT — MAXIMUM TREND CAPTURE
        # =====================================================================
        PEPPER = "INTARIAN_PEPPER_ROOT"
        OSMIUM = "ASH_COATED_OSMIUM"
        ENDGAME_TS = 995000      # Hold even longer for maximum trend profit
        TREND_RATE = 0.001001    # empirically measured ticks-per-timestamp

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

                # ---------- ENDGAME: flatten position very late ----------
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
                    # ---------- CORE: Aggressively get to max long and stay there ----------
                    buy_capacity = limit - pos

                    # 1. Immediate aggressive entry: lift any reasonable ask
                    if buy_capacity > 0:
                        # Buy aggressively if ask is near or below fair value
                        if best_ask <= fair + 5:
                            qty = min(buy_capacity, ask_vol, 30)  # Increased size to 30
                            if qty > 0:
                                orders.append(Order(PEPPER, best_ask, qty))
                                buy_capacity -= qty

                        # 2. Tight passive bid to capture any dips immediately
                        if buy_capacity > 0:
                            passive_bid = int(fair - 2)  # Tighter bid for faster fills
                            if passive_bid < best_ask:
                                qty = min(buy_capacity, 20)  # Increased passive size
                                orders.append(Order(PEPPER, passive_bid, qty))

                    # 3. Only trim if price has massively deviated (unlikely in this trend)
                    if pos > 0 and best_bid > fair + 30:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — ENHANCED MARKET MAKING
        # =====================================================================
        OSM_FAIR = 10000.0
        OSM_MM_OFFSET = 4          # Slightly tighter for more fills (was 5)
        OSM_MM_SIZE   = 14         # Slightly larger (was 12)
        OSM_REV_ENTRY = 12
        OSM_REV_SIZE  = 20

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
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol if total_vol > 0 else mid

                # Slight EMA blend for stability
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
                        # ---- Core market making (2 levels) with tighter offset ----
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