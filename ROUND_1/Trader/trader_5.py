# trader.py - 12k Target Edition (Aggressive Scaling)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}

        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # AGGRESSIVE SCALING - calibrated from winning log
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "base_offset": 4,      # Tighter: more fills (was 6)
                "base_size": 14,       # Larger: more profit per fill (was 9)
                "ema_alpha": 0.1,
                "trend_bias": False
            },
            "INTARIAN_PEPPER_ROOT": {
                "base_offset": 7,      # Slightly tighter: capture some spread (was 9)
                "base_size": 8,        # Larger (was 6)
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
                data[f"{product}_ema"] = 9984 if "OSMIUM" in product else 11479

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

            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            offset = cfg["base_offset"]
            size = cfg["base_size"]
            orders = []

            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            buy_offset = offset
            sell_offset = offset
            if cfg.get("trend_bias", False):
                trend = mid - fair
                if trend > 20:
                    buy_offset = max(3, offset - 1)
                    sell_offset = offset + 1
                elif trend < -20:
                    buy_offset = offset + 1
                    sell_offset = max(3, offset - 1)

            buy_cap = limit - pos
            sell_cap = limit + pos

            if buy_cap > 0:
                buy_price = max(1, int(mid - buy_offset))
                if buy_price < best_ask:
                    qty = min(size, buy_cap)
                    orders.append(Order(product, buy_price, qty))

            if sell_cap > 0:
                sell_price = int(mid + sell_offset)
                if sell_price > best_bid:
                    qty = min(size, sell_cap)
                    orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data