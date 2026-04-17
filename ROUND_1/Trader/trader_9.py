# trader.py - 12k Breakthrough Edition
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # =========================================================================
        # HIGH-PERFORMANCE CONFIGURATION
        # =========================================================================
        CONFIG = {
    "ASH_COATED_OSMIUM": {
        "base_offset": 6,      # Proven 1888 sweet spot
        "base_size": 10,       # Proven size
        "ema_alpha": 0.1,
        "trend_bias": False
    },
    "INTARIAN_PEPPER_ROOT": {
        "base_offset": 7,      # Getting fills consistently
        "base_size": 7,        # Safe size
        "ema_alpha": 0.05,
        "trend_bias": True
    }
}
        

        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass

        for product, cfg in CONFIG.items():
            if f"{product}_ema" not in data:
                data[f"{product}_ema"] = cfg["fair_initial"]
            if f"{product}_spread_history" not in data:
                data[f"{product}_spread_history"] = []
            if f"{product}_last_mid" not in data:
                data[f"{product}_last_mid"] = cfg["fair_initial"]

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid

            # Micro-price (volume-weighted) for better fair value
            if CONFIG[product]["use_micro_price"]:
                bid_vol = sum(od.buy_orders.values())
                ask_vol = sum(abs(v) for v in od.sell_orders.values())
                total_vol = bid_vol + ask_vol
                if total_vol > 0:
                    mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol

            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            cfg = CONFIG[product]

            # Update EMA
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            # Volatility estimation (spread EMA)
            spread_key = f"{product}_spread_history"
            data[spread_key].append(spread)
            if len(data[spread_key]) > cfg["volatility_window"]:
                data[spread_key].pop(0)
            avg_spread = sum(data[spread_key]) / len(data[spread_key]) if data[spread_key] else spread
            volatility_factor = avg_spread / 10.0  # Normalized

            orders = []

            # End-game flattening
            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # Dynamic offset: tighten when calm, widen when volatile or heavily positioned
            position_ratio = abs(pos) / limit
            dynamic_offset = int(cfg["base_offset"] * (1 + position_ratio * 0.5) * volatility_factor)
            dynamic_offset = max(1, min(dynamic_offset, spread - 2))

            # Size scaling: smaller as we approach limits
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / cfg["max_size"], sell_cap / cfg["max_size"])
            base_size = max(5, int(cfg["max_size"] * size_factor))

            # Multi-level market making
            for level in range(cfg["levels"]):
                level_offset = dynamic_offset + level * 2
                level_size = max(3, base_size // (level + 1))

                # Buy orders
                if buy_cap > 0:
                    buy_price = max(1, int(fair - level_offset))
                    if buy_price < best_ask:
                        qty = min(level_size, buy_cap)
                        orders.append(Order(product, buy_price, qty))
                        buy_cap -= qty

                # Sell orders
                if sell_cap > 0:
                    sell_price = int(fair + level_offset)
                    if sell_price > best_bid:
                        qty = min(level_size, sell_cap)
                        orders.append(Order(product, sell_price, -qty))
                        sell_cap -= qty

            # Aggressive inventory pressure: cut positions that exceed cap
            if position_ratio > cfg["inventory_cap"]:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0), base_size)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0), base_size)
                    if qty > 0: orders.append(Order(product, best_ask, qty))

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data