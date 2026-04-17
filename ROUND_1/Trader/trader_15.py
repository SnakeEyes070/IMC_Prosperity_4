# trader.py - Optimized Hybrid (Target: 6,000+)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # =========================================================================
        # ENHANCED CONFIGURATION
        # =========================================================================
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "ema_alpha": 0.12,            # Slightly faster adaptation
                "base_offset": 3,             # Tight for stable asset
                "base_size": 16,              # Slightly larger (safe due to range)
                "max_size": 24,               # Cap for high-confidence signals
                "mean_rev_thresh": 40,        # Tighter fade for quicker scalps
                "momentum_thresh": 1.8,       # More sensitive breakout detection
                "imbalance_thresh": 0.20,     # Lower threshold for imbalance
                "volatility_window": 25,
                "levels": 3,                  # Added a third level for more fills
                "max_spread": 18              # Safety filter
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_alpha": 0.10,
                "base_offset": 4,             # Tighter (spread allows)
                "base_size": 14,              # Increased based on successful logs
                "max_size": 20,
                "mean_rev_thresh": 250,       # Slightly tighter fade
                "momentum_thresh": 2.2,
                "imbalance_thresh": 0.20,
                "volatility_window": 25,
                "levels": 2,
                "max_spread": 22
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
            spread = best_ask - best_bid
            cfg = CONFIG[product]

            # ----- SAFETY FILTER: Skip if spread is dangerously wide -----
            if spread > cfg["max_spread"]:
                result[product] = []
                continue

            limit = LIMITS[product]
            pos = state.position.get(product, 0)

            # ----- 1. MICRO-PRICE (Volume-Weighted Fair Value) -----
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                micro_mid = (best_bid + best_ask) / 2.0

            # ----- 2. ADAPTIVE FAIR VALUE (EMA of micro-price) -----
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * micro_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            # ----- 3. ORDER BOOK IMBALANCE -----
            imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

            # ----- 4. VOLATILITY ESTIMATION -----
            price_hist = data[f"{product}_price_history"]
            price_hist.append(micro_mid)
            if len(price_hist) > cfg["volatility_window"]:
                price_hist.pop(0)
            if len(price_hist) >= 5:
                diffs = [price_hist[i] - price_hist[i-1] for i in range(1, len(price_hist))]
                mean_diff = sum(diffs) / len(diffs)
                variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
                data[f"{product}_volatility"] = math.sqrt(variance) if variance > 0 else 1.0
            vol = data[f"{product}_volatility"]

            # ----- 5. MOMENTUM (Rate of Change) -----
            momentum = micro_mid - fair

            orders = []

            # ----- END-GAME FLATTENING -----
            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # ----- 6. DYNAMIC OFFSET (Volatility & Position Scaled) -----
            vol_ratio = vol / 5.0
            vol_ratio = max(0.6, min(vol_ratio, 2.2))
            position_ratio = abs(pos) / limit
            dynamic_offset = int(cfg["base_offset"] * vol_ratio * (1 + position_ratio * 0.4))
            dynamic_offset = max(2, min(dynamic_offset, spread - 2))

            # ----- 7. DYNAMIC SIZE (Confidence Scaled) -----
            # Base size scales with available capacity
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / cfg["base_size"], sell_cap / cfg["base_size"])
            base_size = max(4, int(cfg["base_size"] * size_factor))

            # ----- 8. BREAKOUT DETECTION (Momentum + Imbalance) -----
            is_breakout = abs(momentum) > cfg["momentum_thresh"] * vol
            imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]

            # ----- 9. OPPORTUNISTIC MEAN REVERSION -----
            if not is_breakout:
                # Buy cheap
                if best_ask < fair - cfg["mean_rev_thresh"] and imbalance > -cfg["imbalance_thresh"]:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, base_size + 6)
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                # Sell expensive
                if best_bid > fair + cfg["mean_rev_thresh"] and imbalance < cfg["imbalance_thresh"]:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, base_size + 6)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # ----- 10. MOMENTUM TRADING (Breakout Confirmation) -----
            elif is_breakout and imbalance_ok:
                if momentum > 0 and imbalance > 0:  # Strong upward pressure
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, cfg["max_size"])
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                elif momentum < 0 and imbalance < 0:  # Strong downward pressure
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, cfg["max_size"])
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # ----- 11. CORE MARKET MAKING (Multi-Level Ladder) -----
            if not orders:
                for level in range(cfg["levels"]):
                    level_offset = dynamic_offset + level * 2
                    level_size = max(2, base_size // (level + 1))

                    # Buy orders
                    if buy_cap > 0:
                        buy_price = max(1, int(fair - level_offset))
                        if buy_price < best_ask:
                            qty = min(level_size, buy_cap)
                            orders.append(Order(product, buy_price, qty))
                            buy_cap -= qty

                    # Sell orders
                    if sell_cap > 0:
                        sell_price = int(fair + level_offset)
                        if sell_price > best_bid:
                            qty = min(level_size, sell_cap)
                            orders.append(Order(product, sell_price, -qty))
                            sell_cap -= qty

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data