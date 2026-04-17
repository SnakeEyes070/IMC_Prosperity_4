# trader.py - The Final Modular Trading Engine for IMC Prosperity
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}

        # =========================================================================
        # CONFIGURATION - The Playbook: Modify this for each new round
        # =========================================================================
        LIMITS = {
            "ASH_COATED_OSMIUM": 50,
            "INTARIAN_PEPPER_ROOT": 50
        }

        STRATEGY_CONFIG = {
            "ASH_COATED_OSMIUM": {
                "type": "STABLE", # Options: STABLE, VOLATILE, TRENDING, ARBITRAGE
                "fair_value": 9984,
                "market_making_offset": 3,
                "base_order_size": 16,
                "max_order_size": 24,
                "take_threshold": 60
            },
            "INTARIAN_PEPPER_ROOT": {
                "type": "TRENDING", # This has been our biggest challenge
                "fair_value_ema_alpha": 0.08,
                "trend_ema_alpha": 0.15,
                "trend_filter_threshold": 50,
                "market_making_offset": 5,
                "base_order_size": 12,
                "max_order_size": 18
            }
        }

        ENDGAME_TIMESTAMP = 194000
        MAX_SPREAD_PCT = 0.05 # Safety filter: skip if spread is > 5% of fair value

        # =========================================================================
        # PERSISTENT STATE (Memory)
        # =========================================================================
        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass

        # Initialize memory for each product based on its strategy type
        for product, cfg in STRATEGY_CONFIG.items():
            if cfg["type"] == "TRENDING":
                if f"{product}_fast_ema" not in data:
                    data[f"{product}_fast_ema"] = state.order_depths[product].get_mid_price() if product in state.order_depths else 11479
                if f"{product}_slow_ema" not in data:
                    data[f"{product}_slow_ema"] = data[f"{product}_fast_ema"]
            elif cfg["type"] in ["STABLE", "VOLATILE"]:
                 if f"{product}_position_entry" not in data:
                    data[f"{product}_position_entry"] = None

        # =========================================================================
        # MAIN LOOP
        # =========================================================================
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            cfg = STRATEGY_CONFIG.get(product, {})
            strategy_type = cfg.get("type", "STABLE")

            # ----- Safety Filters -----
            # 1. Skip if spread is dangerously wide (illiquid)
            fair_val_est = cfg.get("fair_value", mid_price)
            if spread > fair_val_est * MAX_SPREAD_PCT:
                result[product] = []
                continue

            # 2. End-game flattening (lock in profit)
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            orders = []

            if state.timestamp >= ENDGAME_TIMESTAMP:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # ----- Strategy Execution based on Type -----
            if strategy_type == "STABLE":
                fair = cfg["fair_value"]
                offset = cfg["market_making_offset"]
                size = cfg["base_order_size"]
                take_thresh = cfg["take_threshold"]

                # Opportunistic Taking (Buy cheap, Sell expensive)
                if best_ask < fair - take_thresh:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, size + 4)
                    if qty > 0: orders.append(Order(product, best_ask, qty))

                if best_bid > fair + take_thresh:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, size + 4)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

                # Core Market Making
                if not orders:
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

            elif strategy_type == "TRENDING":
                # Update EMAs
                fast_ema_key = f"{product}_fast_ema"
                slow_ema_key = f"{product}_slow_ema"
                data[fast_ema_key] = cfg["trend_ema_alpha"] * mid_price + (1 - cfg["trend_ema_alpha"]) * data[fast_ema_key]
                data[slow_ema_key] = cfg["fair_value_ema_alpha"] * mid_price + (1 - cfg["fair_value_ema_alpha"]) * data[slow_ema_key]

                fast_ema = data[fast_ema_key]
                slow_ema = data[slow_ema_key]
                trend_up = fast_ema > slow_ema + cfg["trend_filter_threshold"]
                trend_down = fast_ema < slow_ema - cfg["trend_filter_threshold"]

                # Trade only in direction of confirmed trend
                if trend_up and pos < limit:
                    # Buy on pullbacks to the fast EMA
                    if best_ask < fast_ema:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, cfg["base_order_size"])
                        if qty > 0: orders.append(Order(product, best_ask, qty))
                elif trend_down and pos > -limit:
                    # Sell on rallies to the fast EMA
                    if best_bid > fast_ema:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, cfg["base_order_size"])
                        if qty > 0: orders.append(Order(product, best_bid, -qty))
                else:
                    # No clear trend: conservative market making
                    offset = cfg["market_making_offset"] + 2
                    size = cfg["base_order_size"] // 2
                    if pos < limit:
                        buy_price = int(mid_price - offset)
                        if buy_price < best_ask:
                            qty = min(size, limit - pos)
                            orders.append(Order(product, buy_price, qty))
                    if pos > -limit:
                        sell_price = int(mid_price + offset)
                        if sell_price > best_bid:
                            qty = min(size, limit + pos)
                            orders.append(Order(product, sell_price, -qty))

            # If no strategy matched, do nothing
            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data