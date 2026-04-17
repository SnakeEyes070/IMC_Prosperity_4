# trader.py - Adaptive Edge Strategy (Target: 8,000+)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math
from collections import deque

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "ema_alpha": 0.1,
                "mm_offset": 3,            # Tight for range
                "base_size": 12,            # Will be scaled by performance
                "max_size": 28,             # Cap when hot
                "min_size": 5,              # Floor when cold
                "volatility_breakout": 2.5, # Std dev multiplier for breakout
                "imbalance_thresh": 0.25,
                "volatility_window": 20,
                "levels": 3,
                "max_spread": 18,
                "stop_loss_ticks": 6
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_alpha": 0.06,          # Slower for trend detection
                "trend_alpha": 0.03,        # Very slow for trend direction
                "mm_offset": 4,
                "base_size": 10,
                "max_size": 22,
                "min_size": 4,
                "trend_thresh": 30,         # Min EMA slope to confirm trend
                "pullback_thresh": 0.5,     # How far price must retrace to enter
                "volatility_window": 20,
                "levels": 2,
                "max_spread": 25
            }
        }

        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass

        # Initialize performance trackers (rolling window of last 20 trade outcomes)
        for product in CONFIG:
            if f"{product}_trade_outcomes" not in data:
                data[f"{product}_trade_outcomes"] = []
            if f"{product}_ema" not in data:
                data[f"{product}_ema"] = CONFIG[product]["fair_initial"]
            if f"{product}_slow_ema" not in data:
                data[f"{product}_slow_ema"] = CONFIG[product]["fair_initial"]
            if f"{product}_price_history" not in data:
                data[f"{product}_price_history"] = []
            if f"{product}_volatility" not in data:
                data[f"{product}_volatility"] = 5.0
            if f"{product}_position_entry" not in data:
                data[f"{product}_position_entry"] = None
            if f"{product}_last_trade_price" not in data:
                data[f"{product}_last_trade_price"] = None

        # Helper function to compute performance multiplier
        def get_performance_multiplier(outcomes, window=20):
            if len(outcomes) < 5:
                return 1.0  # Neutral start
            recent = outcomes[-window:] if len(outcomes) >= window else outcomes
            win_rate = sum(1 for x in recent if x > 0) / len(recent)
            avg_edge = sum(recent) / len(recent) if recent else 0
            # Multiplier: win_rate * (1 + avg_edge/10) capped between 0.5 and 2.0
            mult = win_rate * (1 + avg_edge / 20)
            return max(0.6, min(2.0, mult))

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

            # EMAs
            key_ema = f"{product}_ema"
            data[key_ema] = cfg["ema_alpha"] * micro_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
            fair = data[key_ema]

            slow_key = f"{product}_slow_ema"
            if "trend_alpha" in cfg:
                data[slow_key] = cfg["trend_alpha"] * micro_mid + (1 - cfg["trend_alpha"]) * data[slow_key]
            else:
                data[slow_key] = fair

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

            # Performance-based size multiplier
            outcomes = data[f"{product}_trade_outcomes"]
            perf_mult = get_performance_multiplier(outcomes)
            dynamic_size = int(cfg["base_size"] * perf_mult)
            dynamic_size = max(cfg["min_size"], min(dynamic_size, cfg["max_size"]))

            # Position-based capacity scaling
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / dynamic_size, sell_cap / dynamic_size)
            final_size = max(3, int(dynamic_size * size_factor))

            orders = []
            momentum = micro_mid - fair

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

            # Stop-Loss (Osmium)
            if product == "ASH_COATED_OSMIUM" and pos != 0:
                entry = data[f"{product}_position_entry"]
                if entry is not None:
                    if pos > 0 and micro_mid < entry - cfg["stop_loss_ticks"]:
                        qty = min(pos, od.buy_orders.get(best_bid, 0))
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            # Record loss
                            loss_per_unit = micro_mid - entry
                            outcomes.append(loss_per_unit)
                            if len(outcomes) > 50: outcomes.pop(0)
                            data[f"{product}_position_entry"] = None
                    elif pos < 0 and micro_mid > entry + cfg["stop_loss_ticks"]:
                        qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            loss_per_unit = entry - micro_mid
                            outcomes.append(loss_per_unit)
                            if len(outcomes) > 50: outcomes.pop(0)
                            data[f"{product}_position_entry"] = None

            # ----- PRODUCT-SPECIFIC STRATEGIES -----
            if product == "ASH_COATED_OSMIUM":
                # Osmium: Range-bound with volatility breakout
                is_breakout = abs(momentum) > cfg["volatility_breakout"] * vol
                imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]

                if is_breakout and imbalance_ok:
                    # Ride the breakout with larger size
                    breakout_size = min(cfg["max_size"], final_size + 8)
                    if momentum > 0 and imbalance > 0:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, breakout_size)
                        if qty > 0: orders.append(Order(product, best_ask, qty))
                    elif momentum < 0 and imbalance < 0:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, breakout_size)
                        if qty > 0: orders.append(Order(product, best_bid, -qty))
                else:
                    # Core market making (multi-level)
                    vol_ratio = vol / 5.0
                    vol_ratio = max(0.5, min(vol_ratio, 2.0))
                    dynamic_offset = int(cfg["mm_offset"] * vol_ratio)
                    dynamic_offset = max(2, min(dynamic_offset, spread - 2))

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

            else:  # INTARIAN_PEPPER_ROOT
                # Pepper: Trend-following with pullback entries
                slow_ema = data[slow_key]
                trend_up = micro_mid > slow_ema + cfg["trend_thresh"]
                trend_down = micro_mid < slow_ema - cfg["trend_thresh"]

                if trend_up:
                    # Uptrend: only long positions on pullbacks
                    pullback_target = slow_ema + (micro_mid - slow_ema) * cfg["pullback_thresh"]
                    if best_ask < pullback_target and pos < limit:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, final_size)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            data[f"{product}_position_entry"] = best_ask
                    # Take profit on existing longs
                    if pos > 0 and best_bid > micro_mid:
                        qty = min(pos, od.buy_orders.get(best_bid, 0), final_size)
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            profit_per_unit = best_bid - data[f"{product}_position_entry"] if data[f"{product}_position_entry"] else 0
                            outcomes.append(profit_per_unit)
                            if len(outcomes) > 50: outcomes.pop(0)
                            data[f"{product}_position_entry"] = None

                elif trend_down:
                    # Downtrend: only short positions on rallies
                    pullback_target = slow_ema - (slow_ema - micro_mid) * cfg["pullback_thresh"]
                    if best_bid > pullback_target and pos > -limit:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, final_size)
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            data[f"{product}_position_entry"] = best_bid
                    # Take profit on existing shorts
                    if pos < 0 and best_ask < micro_mid:
                        qty = min(-pos, -od.sell_orders.get(best_ask, 0), final_size)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            profit_per_unit = data[f"{product}_position_entry"] - best_ask if data[f"{product}_position_entry"] else 0
                            outcomes.append(profit_per_unit)
                            if len(outcomes) > 50: outcomes.pop(0)
                            data[f"{product}_position_entry"] = None

                else:
                    # No clear trend: conservative market making
                    offset = cfg["mm_offset"] + 2  # Wider when uncertain
                    if not orders:
                        if pos < limit:
                            buy_price = max(1, int(fair - offset))
                            if buy_price < best_ask:
                                qty = min(cfg["min_size"], limit - pos)
                                orders.append(Order(product, buy_price, qty))
                        if pos > -limit:
                            sell_price = int(fair + offset)
                            if sell_price > best_bid:
                                qty = min(cfg["min_size"], limit + pos)
                                orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data