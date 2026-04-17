# trader.py - Championship Techniques for Round 1 (Target: 7,500+)
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

        # ----- PEPPER: Wall‑Based Anchor + Informed Bias -----
        if PEPPER in state.order_depths:
            od = state.order_depths[PEPPER]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                pos = state.position.get(PEPPER, 0)
                ts = state.timestamp
                orders = []

                # --- Wall‑Based Anchor (More stable than simple best ask) ---
                # Find the price with the largest volume on the ask side
                ask_wall = best_ask
                max_vol = 0
                for price, vol in od.sell_orders.items():
                    if abs(vol) > max_vol:
                        max_vol = abs(vol)
                        ask_wall = price

                if "anchor" not in data:
                    data["anchor"] = ask_wall
                    data["anchor_ts"] = ts
                    data["last_ts"] = ts

                if ts < data["last_ts"]:
                    data["anchor"] = ask_wall
                    data["anchor_ts"] = ts

                data["last_ts"] = ts
                fair = data["anchor"] + TREND_RATE * (ts - data["anchor_ts"])

                # --- Informed Bias: Check for large market trades ---
                # If a big buyer just showed up, we might delay selling a bit
                informed_bias = 0
                for trade in state.market_trades.get(PEPPER, []):
                    if trade.quantity > 15:
                        if trade.buyer == "SUBMISSION":
                            pass  # our own trade
                        elif trade.buyer != "":
                            informed_bias = 1   # Someone is buying aggressively
                        elif trade.seller != "":
                            informed_bias = -1  # Someone is selling aggressively

                if ts >= ENDGAME_TS:
                    # Unwind: slightly slower if informed bias is bullish
                    sell_pace = 6 if informed_bias > 0 else 8
                    if pos > 0:
                        qty = min(pos, od.buy_orders.get(best_bid, 0), sell_pace)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))
                else:
                    buy_cap = LIMITS[PEPPER] - pos
                    if buy_cap > 0:
                        qty = min(buy_cap, -od.sell_orders.get(best_ask, 0), 30)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_ask, qty))

                result[PEPPER] = orders

        # ----- OSMIUM: Overbidding + Imbalance Filter -----
        if OSMIUM in state.order_depths:
            od = state.order_depths[OSMIUM]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                pos = state.position.get(OSMIUM, 0)
                limit = LIMITS[OSMIUM]
                orders = []

                # Imbalance filter
                bid_vol = sum(od.buy_orders.values())
                ask_vol = sum(abs(v) for v in od.sell_orders.values())
                total_vol = bid_vol + ask_vol
                imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

                fair = 10000
                base_offset = 3
                size = 18

                # --- Overbidding: Tighten by 1 tick if large volume at best bid/ask ---
                buy_offset = base_offset
                sell_offset = base_offset

                # If there's a large buy wall, we can afford to bid higher (jump queue)
                if od.buy_orders.get(best_bid, 0) > 10:
                    buy_offset = base_offset - 1
                # If there's a large sell wall, we can afford to ask lower
                if abs(od.sell_orders.get(best_ask, 0)) > 10:
                    sell_offset = base_offset - 1

                buy_cap = limit - pos
                sell_cap = limit + pos

                if buy_cap > 0 and imbalance > -0.3:
                    buy_price = fair - max(1, buy_offset)
                    if buy_price < best_ask:
                        qty = min(size, buy_cap)
                        orders.append(Order(OSMIUM, buy_price, qty))

                if sell_cap > 0 and imbalance < 0.3:
                    sell_price = fair + max(1, sell_offset)
                    if sell_price > best_bid:
                        qty = min(size, sell_cap)
                        orders.append(Order(OSMIUM, sell_price, -qty))

                result[OSMIUM] = orders

        return result, 0, json.dumps(data)