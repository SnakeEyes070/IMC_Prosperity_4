# trader.py - ALL-IN 12k ATTEMPT (HIGH RISK)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # Extreme aggression + microstructure exploitation
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "levels": 5,               # Multi-level quotes
                "base_offset": 2,          # Ultra-tight
                "base_size": 18,           # Near max size
                "imbalance_thresh": 0.3,   # Trade only when volume imbalance >30%
                "inventory_turnover": True # Aggressively cycle inventory
            },
            "INTARIAN_PEPPER_ROOT": {
                "levels": 3,
                "base_offset": 4,
                "base_size": 12,
                "imbalance_thresh": 0.25,
                "inventory_turnover": True
            }
        }

        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
            limit = LIMITS.get(product, 50)
            pos = state.position.get(product, 0)
            cfg = CONFIG.get(product, CONFIG["ASH_COATED_OSMIUM"])

            # Order book imbalance signal
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

            orders = []

            # Endgame flattening (market orders for speed)
            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # Skip if imbalance is against us
            if abs(imbalance) < cfg["imbalance_thresh"]:
                result[product] = []
                continue

            # Multi-level quoting with inventory turnover
            for level in range(cfg["levels"]):
                offset = cfg["base_offset"] + level * 2
                size = max(3, cfg["base_size"] // (level + 1))

                # Buy side
                buy_cap = limit - pos
                if buy_cap > 0:
                    buy_price = max(1, int(mid - offset))
                    if buy_price < best_ask:
                        qty = min(size, buy_cap)
                        orders.append(Order(product, buy_price, qty))
                        buy_cap -= qty

                # Sell side
                sell_cap = limit + pos
                if sell_cap > 0:
                    sell_price = int(mid + offset)
                    if sell_price > best_bid:
                        qty = min(size, sell_cap)
                        orders.append(Order(product, sell_price, -qty))
                        sell_cap -= qty

            # Extreme inventory turnover: if holding > 5 units, aggressively exit
            if cfg.get("inventory_turnover", False):
                if pos > 10:
                    qty = min(pos // 2, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < -10:
                    qty = min(-pos // 2, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))

            result[product] = orders

        return result, 0, ""