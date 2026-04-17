# trader.py - Final Proven Strategy (Target: 5,500+)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}
        
        # =====================================================================
        # PROVEN CONFIGURATION – NO TREND PREDICTIONS, JUST SPREAD CAPTURE
        # =====================================================================
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair": 10000,
                "offset": 4,
                "size": 18,
                "endgame": 990000
            },
            "INTARIAN_PEPPER_ROOT": {
                "offset": 6,
                "size": 8,
                "endgame": 990000
            }
        }

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue
                
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            cfg = CONFIG[product]
            orders = []
            
            # Endgame flattening
            if state.timestamp >= cfg["endgame"]:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue
            
            # Core market making
            if product == "ASH_COATED_OSMIUM":
                fair = cfg["fair"]
                offset = cfg["offset"]
                size = cfg["size"]
                
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
            
            else:  # Pepper – pure market making around mid
                mid = (best_bid + best_ask) / 2.0
                offset = cfg["offset"]
                size = cfg["size"]
                
                buy_cap = limit - pos
                sell_cap = limit + pos
                
                if buy_cap > 0:
                    buy_price = int(mid - offset)
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