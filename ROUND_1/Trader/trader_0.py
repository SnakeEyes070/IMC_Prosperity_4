# trader.py - Ultra-Conservative Round 1 Strategy
# Goal: Stop losses first, then optimize for profit.
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}

        # =========================================================================
        # ULTRA-CONSERVATIVE CONFIGURATION
        # =========================================================================
        LIMITS = {
            "ASH_COATED_OSMIUM": 50,
            "INTARIAN_PEPPER_ROOT": 50
        }

        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "alpha": 0.10,               # Slightly faster to track trends
                "base_offset": 8,            # Wider: safer against adverse selection
                "base_size": 6,              # Smaller size
                "take_thresh": 400,          # Only fade >4% moves (was 150)
                "inventory_cap": 0.20,       # Reduce position very early
                "endgame_start": 190000      # Flatten even later to avoid auction impact
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "alpha": 0.12,               # Faster for potential trends
                "base_offset": 9,            # Significantly wider
                "base_size": 5,              # Minimal size
                "take_thresh": 800,          # Only fade >7% moves (was 400)
                "inventory_cap": 0.15,       # Extremely tight leash
                "endgame_start": 190000
            }
        }

        # =========================================================================
        # PERSISTENT STATE
        # =========================================================================
        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except:
                pass

        for product, cfg in CONFIG.items():
            if f"{product}_ema" not in data:
                data[f"{product}_ema"] = cfg["fair_initial"]
            if f"{product}_fill_rate" not in data:
                data[f"{product}_fill_rate"] = 0.5

        # =========================================================================
        # MAIN LOOP
        # =========================================================================
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
            current_spread = best_ask - best_bid

            limit = LIMITS.get(product, 50)
            pos = state.position.get(product, 0)
            cfg = CONFIG.get(product, CONFIG["ASH_COATED_OSMIUM"])

            orders = []

            # -----------------------------------------------------------------
            # END-GAME FLATTENING (Auction awareness)
            # -----------------------------------------------------------------
            if state.timestamp >= cfg["endgame_start"]:
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

            # -----------------------------------------------------------------
            # SLOW FAIR VALUE ESTIMATION
            # -----------------------------------------------------------------
            alpha = cfg["alpha"]
            key_ema = f"{product}_ema"
            data[key_ema] = alpha * mid + (1 - alpha) * data[key_ema]
            fair = data[key_ema]

            # -----------------------------------------------------------------
            # CONSERVATIVE DYNAMIC OFFSET
            # -----------------------------------------------------------------
            fill_rate = data[f"{product}_fill_rate"]
            position_ratio = abs(pos) / limit

            # Even less aggressive: offset stays wide unless fill rate is extremely low
            attractiveness_factor = 1.0 - (fill_rate * 0.2)  # Range: 0.8 to 1.0
            dynamic_offset = int(cfg["base_offset"] * attractiveness_factor * (1 + position_ratio * 0.2))
            dynamic_offset = max(cfg["base_offset"] - 2, min(dynamic_offset, current_spread - 2))

            # Size scales down aggressively near limits
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / cfg["base_size"], sell_cap / cfg["base_size"])
            dynamic_size = max(2, int(cfg["base_size"] * size_factor))

            take_thresh = cfg["take_thresh"]

            # -----------------------------------------------------------------
            # OPPORTUNISTIC TAKING (Only on extreme moves)
            # -----------------------------------------------------------------
            if best_ask < fair - take_thresh:
                available = -od.sell_orders.get(best_ask, 0)
                qty = min(available, buy_cap, dynamic_size + 2)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
                    data[f"{product}_fill_rate"] = fill_rate * 0.95

            if best_bid > fair + take_thresh:
                available = od.buy_orders.get(best_bid, 0)
                qty = min(available, sell_cap, dynamic_size + 2)
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    data[f"{product}_fill_rate"] = fill_rate * 0.95

            # -----------------------------------------------------------------
            # CORE MARKET MAKING (Attractive but safe quotes)
            # -----------------------------------------------------------------
            if not orders:
                quote_placed = False
                if buy_cap > 0:
                    buy_price = max(1, int(fair - dynamic_offset))
                    if buy_price < best_ask:
                        qty = min(dynamic_size, buy_cap)
                        orders.append(Order(product, buy_price, qty))
                        quote_placed = True

                if sell_cap > 0:
                    sell_price = int(fair + dynamic_offset)
                    if sell_price > best_bid:
                        qty = min(dynamic_size, sell_cap)
                        orders.append(Order(product, sell_price, -qty))
                        quote_placed = True

                if quote_placed:
                    data[f"{product}_fill_rate"] = fill_rate * 0.98 + 0.5 * 0.02

            # -----------------------------------------------------------------
            # AGGRESSIVE INVENTORY PRESSURE
            # -----------------------------------------------------------------
            inv_ratio = abs(pos) / limit
            if inv_ratio > cfg["inventory_cap"]:
                intensity = (inv_ratio - cfg["inventory_cap"]) / (1.0 - cfg["inventory_cap"])
                pressure_qty = int(dynamic_size * intensity * 1.5)  # Stronger pressure
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0), pressure_qty)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0), pressure_qty)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

            result[product] = orders

        # =========================================================================
        # SAVE STATE
        # =========================================================================
        trader_data = json.dumps(data)
        return result, 0, trader_data