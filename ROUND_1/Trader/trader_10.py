# trader.py - Volatility-Adjusted Breakthrough
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # Base configuration
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "ema_alpha": 0.1,
                "base_offset": 4,          # Middle ground
                "max_size": 18,            # Will be scaled by volatility
                "volatility_window": 30,
                "levels": 2
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_alpha": 0.08,
                "base_offset": 5,
                "max_size": 12,
                "volatility_window": 30,
                "levels": 2
            }
        }

        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass

        for product, cfg in CONFIG.items():
            if f"{product}_ema" not in data:
                data[f"{product}_ema"] = cfg["fair_initial"]
            if f"{product}_price_history" not in data:
                data[f"{product}_price_history"] = []
            if f"{product}_volatility" not in data:
                data[f"{product}_volatility"] = 5.0  # Initial guess

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            cfg = CONFIG[product]

            # Update price history and volatility
            price_hist = data[f"{product}_price_history"]
            price_hist.append(mid)
            if len(price_hist) > cfg["volatility_window"]:
                price_hist.pop(0)
            
            if len(price_hist) >= 5:
                # Volatility = standard deviation of recent price changes
                diffs = [price_hist[i] - price_hist[i-1] for i in range(1, len(price_hist))]
                mean_diff = sum(diffs) / len(diffs)
                variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
                data[f"{product}_volatility"] = math.sqrt(variance) if variance > 0 else 1.0
            vol = data[f"{product}_volatility"]

            # Update EMA
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            # Volatility-adjusted parameters
            vol_ratio = vol / 5.0   # Normalize: typical volatility ~5
            vol_ratio = max(0.5, min(vol_ratio, 2.0))  # Clamp to reasonable range
            
            # When volatility is low, tighten offset and increase size
            if vol_ratio < 0.8:  # Calm market
                dynamic_offset = max(2, cfg["base_offset"] - 2)
                size_multiplier = 1.5
            elif vol_ratio > 1.5:  # Volatile market
                dynamic_offset = cfg["base_offset"] + 2
                size_multiplier = 0.6
            else:  # Normal
                dynamic_offset = cfg["base_offset"]
                size_multiplier = 1.0
            
            # Also widen offset if we're heavily positioned
            position_ratio = abs(pos) / limit
            dynamic_offset = int(dynamic_offset * (1 + position_ratio * 0.5))
            dynamic_offset = max(2, min(dynamic_offset, int((best_ask - best_bid) * 0.8)))

            # Dynamic size
            base_size = int(cfg["max_size"] * size_multiplier)
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / base_size, sell_cap / base_size)
            dynamic_size = max(3, int(base_size * size_factor))

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

            # Multi-level market making with volatility-adjusted offsets
            for level in range(cfg["levels"]):
                level_offset = dynamic_offset + level * 2
                level_size = max(2, dynamic_size // (level + 1))

                # Buy
                if buy_cap > 0:
                    buy_price = max(1, int(fair - level_offset))
                    if buy_price < best_ask:
                        qty = min(level_size, buy_cap)
                        orders.append(Order(product, buy_price, qty))
                        buy_cap -= qty

                # Sell
                if sell_cap > 0:
                    sell_price = int(fair + level_offset)
                    if sell_price > best_bid:
                        qty = min(level_size, sell_cap)
                        orders.append(Order(product, sell_price, -qty))
                        sell_cap -= qty

            # Opportunistic mean reversion only on extreme deviations (safe)
            if product == "INTARIAN_PEPPER_ROOT":
                # If price is far below EMA and volatility is not extreme, buy aggressively
                if best_ask < fair - 300 and vol_ratio < 1.5:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, dynamic_size + 5)
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                # If price is far above EMA, sell
                if best_bid > fair + 300 and vol_ratio < 1.5:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, dynamic_size + 5)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data