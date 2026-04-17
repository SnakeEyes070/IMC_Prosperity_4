# trader.py - Data‑Driven Final (Calibrated from Your Log)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}
        
        # Calibrated from actual log extremes
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "bid_price": 9990,      # Just above historical low (9987)
                "ask_price": 10010,     # Just below historical high (10013)
                "size": 30              # Aggressive but safe within range
            },
            "INTARIAN_PEPPER_ROOT": {
                "bid_price": 12065,     # Just above historical low (12060)
                "ask_price": 12092,     # Just below historical high (12097)
                "size": 20
            }
        }

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue
                
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            cfg = CONFIG[product]
            orders = []
            
            # Endgame: market orders to flatten
            if state.timestamp >= 194000:
                best_bid = max(od.buy_orders.keys()) if od.buy_orders else 0
                best_ask = min(od.sell_orders.keys()) if od.sell_orders else 0
                if pos > 0 and best_bid > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0 and best_ask > 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue
            
            # Place resting orders at calibrated prices
            buy_cap = limit - pos
            sell_cap = limit + pos
            
            if buy_cap > 0:
                qty = min(cfg["size"], buy_cap)
                orders.append(Order(product, cfg["bid_price"], qty))
            
            if sell_cap > 0:
                qty = min(cfg["size"], sell_cap)
                orders.append(Order(product, cfg["ask_price"], -qty))
            
            result[product] = orders
        
        return result, 0, ""