# trader.py - Pure Spread Capture (Trending Market Survival)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}

        LIMITS = {
            "ASH_COATED_OSMIUM": 50,
            "INTARIAN_PEPPER_ROOT": 50
        }

        # Wide offsets to avoid adverse selection in a trend
        OFFSETS = {
            "ASH_COATED_OSMIUM": 8,
            "INTARIAN_PEPPER_ROOT": 10
        }

        SIZES = {
            "ASH_COATED_OSMIUM": 7,
            "INTARIAN_PEPPER_ROOT": 5
        }

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0

            limit = LIMITS.get(product, 50)
            pos = state.position.get(product, 0)
            offset = OFFSETS.get(product, 8)
            size = SIZES.get(product, 5)

            orders = []

            # Endgame flattening (simple market orders)
            if state.timestamp >= 192000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # Pure market making: no fair value, no mean reversion
            buy_cap = limit - pos
            sell_cap = limit + pos

            if buy_cap > 0:
                buy_price = max(1, int(mid - offset))
                if buy_price < best_ask:
                    qty = min(size, buy_cap)
                    orders.append(Order(product, buy_price, qty))

            if sell_cap > 0:
                sell_price = int(mid + offset)
                if sell_price > best_bid:
                    qty = min(size, sell_cap)
                    orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        return result, 0, ""