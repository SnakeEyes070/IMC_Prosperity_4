# trader.py - YOLO Gambit (Target: 12k+ or Bust)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        for product, od in state.order_depths.items():
            if product == "INTARIAN_PEPPER_ROOT":
                result[product] = []   # Disable Pepper completely
                continue

            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            orders = []

            # Endgame: dump everything
            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # Ultra‑tight market making at 9999 / 10001
            fair = 10000
            offset = 1
            size = 40   # Maximum aggression

            buy_cap = limit - pos
            sell_cap = limit + pos

            if buy_cap > 0:
                buy_price = fair - offset
                if buy_price < best_ask:
                    qty = min(size, buy_cap)
                    orders.append(Order(product, buy_price, qty))

            if sell_cap > 0:
                sell_price = fair + offset
                if sell_price > best_bid:
                    qty = min(size, sell_cap)
                    orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        return result, 0, ""