# trader.py - Restored Peak + Safe Anchor Upgrade (Target: 6,000+)
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

        ENDGAME_TS = 99_000          # Restored – captures full trend
        TREND_RATE = 0.001001

        # =====================================================================
        # PEPPER – Proven 5,883 Logic (Restored)
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

                # Day detection via timestamp reset (proven reliable)
                last_ts_key = "pepper_last_ts"
                anchor_key = "pepper_anchor"
                anchor_ts_key = "pepper_anchor_ts"

                if anchor_key not in data:
                    # SAFE UPGRADE: Volume‑weighted anchor for better fair value
                    total_vol = bid_vol + ask_vol
                    if total_vol > 0:
                        wmid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
                    else:
                        wmid = mid
                    data[anchor_key] = wmid
                    data[anchor_ts_key] = ts
                    data[last_ts_key] = ts

                if ts < data[last_ts_key]:
                    # New day – reset anchor
                    total_vol = bid_vol + ask_vol
                    if total_vol > 0:
                        wmid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
                    else:
                        wmid = mid
                    data[anchor_key] = wmid
                    data[anchor_ts_key] = ts

                data[last_ts_key] = ts

                anchor_price = data[anchor_key]
                anchor_ts    = data[anchor_ts_key]
                fair = anchor_price + TREND_RATE * (ts - anchor_ts)

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
                        # WIDE TOLERANCE (20) – Restored for instant max long
                        qty = min(buy_cap, ask_vol, 30)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))
                            buy_cap -= qty

                        if buy_cap > 0:
                            passive_bid = int(fair - 2)
                            if passive_bid < best_ask:
                                qty2 = min(buy_cap, 15)
                                orders.append(Order(PEPPER, passive_bid, qty2))

                    sell_cap = limit + pos
                    if pos > 0 and best_bid > fair + 20 and sell_cap > 0:
                        qty = min(pos, bid_vol, 10)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))

                result[PEPPER] = orders

        # =====================================================================
        # OSMIUM – Proven 5,883 Parameters (Unchanged)
        # =====================================================================
        OSM_FAIR        = 10000.0
        OSM_MM_OFFSET   = 3
        OSM_MM_SIZE     = 14
        OSM_REV_ENTRY   = 8
        OSM_REV_SIZE    = 24
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