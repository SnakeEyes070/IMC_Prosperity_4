# trader.py - Multi-Signal Hybrid Strategy (Target: 3000+)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # =========================================================================
        # ADVANCED CONFIGURATION
        # =========================================================================
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "ema_alpha": 0.1,
                "mm_offset": 3,            # Base market making offset
                "mm_size": 15,             # Base market making size
                "mean_rev_thresh": 50,     # Min deviation for mean reversion
                "momentum_thresh": 2.0,    # Volatility multiple for breakout
                "imbalance_thresh": 0.3,   # Min order book imbalance to act
                "volatility_window": 20
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_alpha": 0.08,
                "mm_offset": 5,
                "mm_size": 10,
                "mean_rev_thresh": 300,
                "momentum_thresh": 2.5,
                "imbalance_thresh": 0.25,
                "volatility_window": 20
            }
        }

        # =========================================================================
        # PERSISTENT STATE
        # =========================================================================
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
                data[f"{product}_volatility"] = 5.0

        # =========================================================================
        # MAIN LOOP
        # =========================================================================
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            cfg = CONFIG[product]

            # --- 1. Update State & Calculate Advanced Metrics ---
            # Synthetic Fair Value (Volume-Weighted Mid-Price)
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                synthetic_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                synthetic_mid = (best_bid + best_ask) / 2.0
            
            # Update EMA of the synthetic mid
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * synthetic_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair_value = data[key_ema]

            # Order Book Imbalance
            imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

            # Price History & Volatility
            price_hist = data[f"{product}_price_history"]
            price_hist.append(synthetic_mid)
            if len(price_hist) > cfg["volatility_window"]:
                price_hist.pop(0)
            
            if len(price_hist) >= 5:
                diffs = [price_hist[i] - price_hist[i-1] for i in range(1, len(price_hist))]
                mean_diff = sum(diffs) / len(diffs)
                variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
                data[f"{product}_volatility"] = math.sqrt(variance) if variance > 0 else 1.0
            vol = data[f"{product}_volatility"]

            # Simple Momentum (Rate of Change)
            momentum = synthetic_mid - data[f"{product}_ema"]

            orders = []

            # --- 2. End-Game Flattening ---
            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # --- 3. Dynamic Strategy Selection & Execution ---
            
            # Determine if we are in a breakout (momentum) regime
            is_breakout = abs(momentum) > cfg["momentum_thresh"] * vol
            
            # Only trade aggressively if order book imbalance confirms our direction
            imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]
            
            # --- 3a. Opportunistic Mean Reversion (Fading Extremes) ---
            # We use this primarily for the volatile asset when NOT in a breakout.
            if not is_breakout:
                # Buy if price is significantly below fair value and imbalance isn't heavily selling
                if best_ask < fair_value - cfg["mean_rev_thresh"] and imbalance > -cfg["imbalance_thresh"]:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, cfg["mm_size"] + 5)
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                
                # Sell if price is significantly above fair value and imbalance isn't heavily buying
                if best_bid > fair_value + cfg["mean_rev_thresh"] and imbalance < cfg["imbalance_thresh"]:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, cfg["mm_size"] + 5)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # --- 3b. Momentum/Breakout Trading ---
            # If in a breakout and imbalance confirms, trade with the trend.
            elif is_breakout and imbalance_ok:
                if momentum > 0 and imbalance > 0: # Strong upward pressure
                    # Buy aggressively
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, cfg["mm_size"] + 8)
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                elif momentum < 0 and imbalance < 0: # Strong downward pressure
                    # Sell aggressively
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, cfg["mm_size"] + 8)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # --- 3c. Core Market Making (Always On) ---
            # Adjust spread based on volatility: wider when volatile, tighter when calm.
            vol_ratio = vol / 5.0
            vol_ratio = max(0.5, min(vol_ratio, 2.0))
            dynamic_offset = int(cfg["mm_offset"] * vol_ratio)
            dynamic_offset = max(2, dynamic_offset)

            # Adjust size based on position (reduce as we approach limits)
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / cfg["mm_size"], sell_cap / cfg["mm_size"])
            dynamic_size = max(3, int(cfg["mm_size"] * size_factor))

            # Place market making orders if we haven't already placed aggressive ones
            if not orders:
                # Buy Order
                if buy_cap > 0:
                    buy_price = max(1, int(fair_value - dynamic_offset))
                    if buy_price < best_ask:
                        qty = min(dynamic_size, buy_cap)
                        orders.append(Order(product, buy_price, qty))
                
                # Sell Order
                if sell_cap > 0:
                    sell_price = int(fair_value + dynamic_offset)
                    if sell_price > best_bid:
                        qty = min(dynamic_size, sell_cap)
                        orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        # =========================================================================
        # SAVE STATE AND RETURN
        # =========================================================================
        trader_data = json.dumps(data)
        return result, 0, trader_data