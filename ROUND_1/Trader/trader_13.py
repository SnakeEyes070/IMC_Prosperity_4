# trader.py - Final Ascent (Target: 6,000 - 7,000)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "ema_alpha": 0.1,
                "base_offset": 3,            # Sweet spot
                "base_size": 15,             # Sweet spot
                "max_size": 22,              # Cap for wide spreads
                "spread_threshold": 8,       # Spread width to trigger larger size
                "mean_rev_thresh": 50,
                "momentum_thresh": 2.0,
                "imbalance_thresh": 0.25,
                "volatility_window": 20,
                "levels": 2
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_alpha": 0.08,
                "base_offset": 5,            # Sweet spot
                "base_size": 12,             # Sweet spot
                "max_size": 18,
                "spread_threshold": 10,
                "mean_rev_thresh": 300,
                "momentum_thresh": 2.5,
                "imbalance_thresh": 0.25,
                "volatility_window": 20,
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
                data[f"{product}_volatility"] = 5.0

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            spread = best_ask - best_bid
            limit = LIMITS[product]
            pos = state.position.get(product, 0)
            cfg = CONFIG[product]

            # Synthetic fair value
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                synthetic_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                synthetic_mid = (best_bid + best_ask) / 2.0

            # Update EMA
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * synthetic_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            # Imbalance
            imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

            # Volatility
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

            momentum = synthetic_mid - fair
            orders = []

            # Endgame
            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            # Dynamic sizing based on spread
            spread_factor = min(1.5, max(0.8, spread / cfg["spread_threshold"]))
            dynamic_size = int(cfg["base_size"] * spread_factor)
            dynamic_size = min(dynamic_size, cfg["max_size"])

            # Position-based scaling
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / dynamic_size, sell_cap / dynamic_size)
            final_size = max(3, int(dynamic_size * size_factor))

            # Dynamic offset (volatility-adjusted)
            vol_ratio = vol / 5.0
            vol_ratio = max(0.5, min(vol_ratio, 2.0))
            dynamic_offset = int(cfg["base_offset"] * vol_ratio)
            dynamic_offset = max(2, min(dynamic_offset, spread - 2))

            # Breakout detection
            is_breakout = abs(momentum) > cfg["momentum_thresh"] * vol
            imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]

            # Mean reversion (only if not breakout)
            if not is_breakout:
                if best_ask < fair - cfg["mean_rev_thresh"] and imbalance > -cfg["imbalance_thresh"]:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, final_size + 5)
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                if best_bid > fair + cfg["mean_rev_thresh"] and imbalance < cfg["imbalance_thresh"]:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, final_size + 5)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # Momentum trading (breakout)
            elif is_breakout and imbalance_ok:
                if momentum > 0 and imbalance > 0:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, final_size + 8)
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                elif momentum < 0 and imbalance < 0:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, final_size + 8)
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # Core market making
            if not orders:
                for level in range(cfg["levels"]):
                    level_offset = dynamic_offset + level * 2
                    level_size = max(2, final_size // (level + 1))

                    if buy_cap > 0:
                        buy_price = max(1, int(fair - level_offset))
                        if buy_price < best_ask:
                            qty = min(level_size, buy_cap)
                            orders.append(Order(product, buy_price, qty))
                            buy_cap -= qty

                    if sell_cap > 0:
                        sell_price = int(fair + level_offset)
                        if sell_price > best_bid:
                            qty = min(level_size, sell_cap)
                            orders.append(Order(product, sell_price, -qty))
                            sell_cap -= qty

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data