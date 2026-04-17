# trader.py - Final Round 1 (Imbalance‑Aware Osmium)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json

class Trader:
    def run(self, state: TradingState):
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except:
                pass

        PEPPER = "INTARIAN_PEPPER_ROOT"
        OSMIUM = "ASH_COATED_OSMIUM"

        ENDGAME_TS = 95_000
        TREND_RATE = 0.001

        # ----- PEPPER: Unchanged, proven optimal -----
        if PEPPER in state.order_depths:
            od = state.order_depths[PEPPER]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                pos = state.position.get(PEPPER, 0)
                ts = state.timestamp
                orders = []

                if "anchor" not in data:
                    data["anchor"] = best_ask
                    data["anchor_ts"] = ts
                    data["last_ts"] = ts

                if ts < data["last_ts"]:
                    data["anchor"] = best_ask
                    data["anchor_ts"] = ts

                data["last_ts"] = ts
                fair = data["anchor"] + TREND_RATE * (ts - data["anchor_ts"])

                if ts >= ENDGAME_TS:
                    if pos > 0:
                        qty = min(pos, od.buy_orders.get(best_bid, 0), 8)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))
                else:
                    buy_cap = LIMITS[PEPPER] - pos
                    if buy_cap > 0:
                        qty = min(buy_cap, -od.sell_orders.get(best_ask, 0), 30)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))

                result[PEPPER] = orders

        # ----- OSMIUM: Market Making + Imbalance Filter -----
        if OSMIUM in state.order_depths:
            od = state.order_depths[OSMIUM]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                pos = state.position.get(OSMIUM, 0)
                limit = LIMITS[OSMIUM]
                orders = []

                # Order book imbalance (lightweight)
                bid_vol = sum(od.buy_orders.values())
                ask_vol = sum(abs(v) for v in od.sell_orders.values())
                total_vol = bid_vol + ask_vol
                imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

                fair = 10000
                offset = 3
                size = 18

                buy_cap = limit - pos
                sell_cap = limit + pos

                # Only place passive orders if imbalance is not extreme
                # Skip if strong selling pressure (imbalance < -0.3) when buying
                # Skip if strong buying pressure (imbalance > 0.3) when selling
                if buy_cap > 0 and imbalance > -0.3:
                    buy_price = fair - offset
                    if buy_price < best_ask:
                        qty = min(size, buy_cap)
                        orders.append(Order(OSMIUM, buy_price, qty))

                if sell_cap > 0 and imbalance < 0.3:
                    sell_price = fair + offset
                    if sell_price > best_bid:
                        qty = min(size, sell_cap)
                        orders.append(Order(OSMIUM, sell_price, -qty))

                result[OSMIUM] = orders

        return result, 0, json.dumps(data)