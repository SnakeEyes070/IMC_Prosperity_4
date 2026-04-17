# trader.py - Endgame Optimized (Target: 6,000+ final PnL)
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

        # Endgame window: start unwinding at 90,000 (90% of day)
        ENDGAME_START = 90000
        ENDGAME_END   = 99900
        TREND_RATE = 0.001001

        # =====================================================================
        # INTARIAN PEPPER ROOT — Aggressive Accumulation, Gradual Unwind
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

                # Graduated endgame: linearly reduce target position to zero
                if ts >= ENDGAME_START:
                    # Calculate fraction of endgame completed (0 to 1)
                    progress = min(1.0, (ts - ENDGAME_START) / (ENDGAME_END - ENDGAME_START))
                    # Target position goes from current max down to 0
                    target_pos = int(pos * (1 - progress)) if pos > 0 else int(pos * (1 - progress))
                    # Only place orders to move toward target
                    if pos > target_pos:
                        # Need to sell
                        sell_qty = pos - target_pos
                        # Use limit orders at favorable prices
                        for price in sorted(od.buy_orders.keys(), reverse=True):
                            if sell_qty <= 0: break
                            vol = od.buy_orders[price]
                            qty = min(sell_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(PEPPER, price, -qty))
                                sell_qty -= qty
                    elif pos < target_pos:
                        # Need to buy (unlikely in uptrend, but for safety)
                        buy_qty = target_pos - pos
                        for price in sorted(od.sell_orders.keys()):
                            if buy_qty <= 0: break
                            vol = abs(od.sell_orders[price])
                            qty = min(buy_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(PEPPER, price, qty))
                                buy_qty -= qty
                else:
                    # Normal aggressive accumulation
                    buy_cap = limit - pos
                    if buy_cap > 0:
                        qty = min(buy_cap, ask_vol, 20)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))
                            buy_cap -= qty

                        if buy_cap > 0:
                            passive_bid = int(fair - 2)
                            if passive_bid < best_ask:
                                qty2 = min(buy_cap, 10)
                                orders.append(Order(PEPPER, passive_bid, qty2))

                    sell_cap = limit + pos
                    if pos > 0 and best_bid > fair + 20 and sell_cap > 0:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — Enhanced Aggression with Graduated Unwind
        # =====================================================================
        OSM_FAIR        = 10000.0
        OSM_MM_OFFSET   = 3
        OSM_MM_SIZE     = 15
        OSM_REV_ENTRY   = 8       
        OSM_REV_SIZE    = 25
        OSM_UNWIND_FRAC = 0.7

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
                            if sell_qty <= 0: break
                            vol = od.buy_orders[price]
                            qty = min(sell_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(OSMIUM, price, -qty))
                                sell_qty -= qty
                    elif pos < target_pos:
                        buy_qty = target_pos - pos
                        for price in sorted(od.sell_orders.keys()):
                            if buy_qty <= 0: break
                            vol = abs(od.sell_orders[price])
                            qty = min(buy_qty, vol, 10)
                            if qty > 0:
                                orders.append(Order(OSMIUM, price, qty))
                                buy_qty -= qty
                else:
                    buy_cap  = limit - pos
                    sell_cap = limit + pos

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
                            offset = OSM_MM_OFFSET + level * 4
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