# trader.py - Enhanced with Stop-Loss and Trend Bias
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
                "mm_offset": 4,            # Slightly wider to reduce false signals
                "mm_size": 14,             # Conservative base size
                "max_size": 20,            # Cap for high-confidence
                "mean_rev_thresh": 60,     # Wider: only fade significant dips
                "stop_loss_ticks": 8,      # Exit if position moves against us by 8 ticks
                "momentum_thresh": 2.2,
                "imbalance_thresh": 0.25,
                "volatility_window": 20,
                "levels": 2,
                "max_spread": 20
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_alpha": 0.08,
                "mm_offset": 5,
                "mm_size": 10,
                "max_size": 15,
                "trend_bias": True,        # Only trade in trend direction
                "trend_thresh": 50,         # Min EMA slope to consider trending
                "mean_rev_thresh": 350,     # Wider due to volatility
                "momentum_thresh": 2.8,
                "imbalance_thresh": 0.25,
                "volatility_window": 20,
                "levels": 2,
                "max_spread": 25
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
            if f"{product}_position_entry" not in data:
                data[f"{product}_position_entry"] = None  # Track entry price for stop-loss

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            spread = best_ask - best_bid
            cfg = CONFIG[product]

            if spread > cfg["max_spread"]:
                result[product] = []
                continue

            limit = LIMITS[product]
            pos = state.position.get(product, 0)

            # Micro-price
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                micro_mid = (best_bid + best_ask) / 2.0

            # EMA
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * micro_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            # Imbalance
            imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

            # Volatility
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

            momentum = micro_mid - fair
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

            # Stop-Loss for mean reversion positions (Osmium)
            if product == "ASH_COATED_OSMIUM" and pos != 0:
                entry = data[f"{product}_position_entry"]
                if entry is not None:
                    if pos > 0 and micro_mid < entry - cfg["stop_loss_ticks"]:
                        # Cut long position
                        qty = min(pos, od.buy_orders.get(best_bid, 0))
                        if qty > 0: orders.append(Order(product, best_bid, -qty))
                        data[f"{product}_position_entry"] = None
                    elif pos < 0 and micro_mid > entry + cfg["stop_loss_ticks"]:
                        # Cover short position
                        qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                        if qty > 0: orders.append(Order(product, best_ask, qty))
                        data[f"{product}_position_entry"] = None

            # Dynamic offset & size
            vol_ratio = vol / 5.0
            vol_ratio = max(0.5, min(vol_ratio, 2.0))
            position_ratio = abs(pos) / limit
            dynamic_offset = int(cfg["mm_offset"] * vol_ratio * (1 + position_ratio * 0.4))
            dynamic_offset = max(2, min(dynamic_offset, spread - 2))

            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / cfg["mm_size"], sell_cap / cfg["mm_size"])
            base_size = max(4, int(cfg["mm_size"] * size_factor))

            # Breakout detection
            is_breakout = abs(momentum) > cfg["momentum_thresh"] * vol
            imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]

            # Trend bias for Pepper
            trend_direction = 0
            if cfg.get("trend_bias", False):
                ema_slope = data[key_ema] - data.get(f"{product}_prev_ema", data[key_ema])
                if ema_slope > cfg["trend_thresh"]:
                    trend_direction = 1   # Uptrend: only long
                elif ema_slope < -cfg["trend_thresh"]:
                    trend_direction = -1  # Downtrend: only short
                data[f"{product}_prev_ema"] = data[key_ema]

            # Mean Reversion (only if not breakout and trend allows)
            if not is_breakout:
                if (best_ask < fair - cfg["mean_rev_thresh"] and imbalance > -cfg["imbalance_thresh"]):
                    if trend_direction != -1:  # Not in downtrend
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, base_size + 4)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            if product == "ASH_COATED_OSMIUM" and pos == 0:
                                data[f"{product}_position_entry"] = best_ask
                if (best_bid > fair + cfg["mean_rev_thresh"] and imbalance < cfg["imbalance_thresh"]):
                    if trend_direction != 1:  # Not in uptrend
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, base_size + 4)
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            if product == "ASH_COATED_OSMIUM" and pos == 0:
                                data[f"{product}_position_entry"] = best_bid

            # Momentum Trading (Breakout)
            elif is_breakout and imbalance_ok:
                if momentum > 0 and imbalance > 0:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, limit - pos, cfg["max_size"])
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                elif momentum < 0 and imbalance < 0:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, limit + pos, cfg["max_size"])
                    if qty > 0: orders.append(Order(product, best_bid, -qty))

            # Core Market Making (if no alpha trades)
            if not orders:
                for level in range(cfg["levels"]):
                    level_offset = dynamic_offset + level * 2
                    level_size = max(2, base_size // (level + 1))

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