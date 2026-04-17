# scout.py - Precision Seed Mapper (Round 1 Endgame)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import base64
import zlib
import struct

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        
        # =========================================================================
        # LOAD EXISTING LOG
        # =========================================================================
        data = {}
        if state.traderData:
            try:
                # Data is stored as base64(zlib(json))
                compressed = base64.b64decode(state.traderData)
                decompressed = zlib.decompress(compressed)
                data = json.loads(decompressed.decode('utf-8'))
            except:
                # Fallback for first run or corrupted data
                data = {"ticks": []}
        
        # Initialize if empty
        if "ticks" not in data:
            data["ticks"] = []
        
        # =========================================================================
        # LOG CURRENT MARKET STATE
        # =========================================================================
        tick_data = {"ts": state.timestamp}
        
        for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            od = state.order_depths.get(product)
            if od and od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                # Store only essential data: best bid, best ask
                tick_data[product] = {"bid": best_bid, "ask": best_ask}
            else:
                tick_data[product] = None
        
        data["ticks"].append(tick_data)
        
        # Keep only last 2000 ticks to stay under 50k char limit (will be ~20-30k chars)
        if len(data["ticks"]) > 2000:
            data["ticks"] = data["ticks"][-2000:]
        
        # =========================================================================
        # PLACE HARMLESS ORDERS (never fill)
        # =========================================================================
        for product, od in state.order_depths.items():
            orders = []
            if od.buy_orders and od.sell_orders:
                bb = max(od.buy_orders.keys())
                ba = min(od.sell_orders.keys())
                mid = (bb + ba) / 2.0
                # Place orders 1000 ticks away – will never execute
                orders.append(Order(product, int(mid - 1000), 1))
                orders.append(Order(product, int(mid + 1000), -1))
            result[product] = orders
        
        # =========================================================================
        # COMPRESS AND SAVE
        # =========================================================================
        json_str = json.dumps(data)
        compressed = zlib.compress(json_str.encode('utf-8'), level=9)
        trader_data = base64.b64encode(compressed).decode('ascii')
        
        return result, 0, trader_data