# trader.py - Final Adaptive Strategy (Round 1 Endgame)
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
                "mm_offset_calm": 2,       # Tight when calm
                "mm_offset_volatile": 5,   # Wide when volatile
                "mm_size_calm": 20,        # Aggressive when calm
                "mm_size_volatile": 8,     # Defensive when volatile
                "volatility_thresh": 8.0,  # Switch threshold
                "stop_loss_ticks": 8,
                "mean_rev_thresh": 50,
                "momentum_thresh": 2.5,
                "imbalance_thresh": 0.25,
                "volatility_window": 15,
                "levels": 2,
                "max_spread": 20
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_fast": 0.15,          # 20-period equivalent
                "ema_slow": 0.05,          # 50-period equivalent
                "trend_size": 12,
                "trailing_stop": 40,       # Exit if price moves against by 40 ticks
                "mm_offset": 6,            # Fallback market making
                "mm_size": 6,
                "max_spread": 25
            }
        }

        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass

        for product in CONFIG:
            if f"{product}_ema" not in data:
                data[f"{product}_ema"] = CONFIG[product]["fair_initial"]
            if f"{product}_price_history" not in data:
                data[f"{product}_price_history"] = []
            if f"{product}_volatility" not in data:
                data[f"{product}_volatility"] = 5.0
            if f"{product}_position_entry" not in data:
                data[f"{product}_position_entry"] = None
            if product == "INTARIAN_PEPPER_ROOT":
                if f"{product}_fast_ema" not in data:
                    data[f"{product}_fast_ema"] = CONFIG[product]["fair_initial"]
                if f"{product}_slow_ema" not in data:
                    data[f"{product}_slow_ema"] = CONFIG[product]["fair_initial"]
                if f"{product}_trend_position" not in data:
                    data[f"{product}_trend_position"] = 0  # 1=long, -1=short, 0=neutral

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

            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                micro_mid = (best_bid + best_ask) / 2.0

            orders = []

            if state.timestamp >= 194000:
                if pos > 0:
                    qty = min(pos, od.buy_orders.get(best_bid, 0))
                    if qty > 0: orders.append(Order(product, best_bid, -qty))
                elif pos < 0:
                    qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                    if qty > 0: orders.append(Order(product, best_ask, qty))
                result[product] = orders
                continue

            if product == "ASH_COATED_OSMIUM":
                # ===== OSMIIUM: Volatility-Adaptive Hybrid =====
                key_ema = f"{product}_ema"
                data[key_ema] = cfg["ema_alpha"] * micro_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
                fair = data[key_ema]

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

                # Regime detection
                is_volatile = vol > cfg["volatility_thresh"]
                mm_offset = cfg["mm_offset_volatile"] if is_volatile else cfg["mm_offset_calm"]
                mm_size = cfg["mm_size_volatile"] if is_volatile else cfg["mm_size_calm"]

                imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0
                momentum = micro_mid - fair

                # Stop-loss
                if pos != 0:
                    entry = data[f"{product}_position_entry"]
                    if entry is not None:
                        if pos > 0 and micro_mid < entry - cfg["stop_loss_ticks"]:
                            qty = min(pos, od.buy_orders.get(best_bid, 0))
                            if qty > 0:
                                orders.append(Order(product, best_bid, -qty))
                                data[f"{product}_position_entry"] = None
                        elif pos < 0 and micro_mid > entry + cfg["stop_loss_ticks"]:
                            qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                            if qty > 0:
                                orders.append(Order(product, best_ask, qty))
                                data[f"{product}_position_entry"] = None

                # Dynamic offset & size
                position_ratio = abs(pos) / limit
                dynamic_offset = int(mm_offset * (1 + position_ratio * 0.3))
                dynamic_offset = max(2, min(dynamic_offset, spread - 2))

                buy_cap = limit - pos
                sell_cap = limit + pos
                size_factor = min(1.0, buy_cap / mm_size, sell_cap / mm_size)
                base_size = max(4, int(mm_size * size_factor))

                is_breakout = abs(momentum) > cfg["momentum_thresh"] * vol
                imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]

                if not is_breakout:
                    if best_ask < fair - cfg["mean_rev_thresh"] and imbalance > -cfg["imbalance_thresh"]:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, base_size + 4)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            if pos == 0:
                                data[f"{product}_position_entry"] = best_ask
                    if best_bid > fair + cfg["mean_rev_thresh"] and imbalance < cfg["imbalance_thresh"]:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, base_size + 4)
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            if pos == 0:
                                data[f"{product}_position_entry"] = best_bid

                elif is_breakout and imbalance_ok:
                    if momentum > 0 and imbalance > 0:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, base_size + 6)
                        if qty > 0: orders.append(Order(product, best_ask, qty))
                    elif momentum < 0 and imbalance < 0:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, base_size + 6)
                        if qty > 0: orders.append(Order(product, best_bid, -qty))

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

            else:
                # ===== PEPPER: Pure Trend Following =====
                fast_key = f"{product}_fast_ema"
                slow_key = f"{product}_slow_ema"
                data[fast_key] = cfg["ema_fast"] * micro_mid + (1 - cfg["ema_fast"]) * data[fast_key]
                data[slow_key] = cfg["ema_slow"] * micro_mid + (1 - cfg["ema_slow"]) * data[slow_key]

                fast_ema = data[fast_key]
                slow_ema = data[slow_key]
                trend_up = fast_ema > slow_ema
                trend_down = fast_ema < slow_ema
                trend_position = data[f"{product}_trend_position"]

                # Entry logic
                if trend_position == 0:
                    if trend_up and micro_mid < fast_ema:  # Pullback in uptrend
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, cfg["trend_size"])
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            data[f"{product}_trend_position"] = 1
                            data[f"{product}_position_entry"] = best_ask
                    elif trend_down and micro_mid > fast_ema:  # Rally in downtrend
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, cfg["trend_size"])
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            data[f"{product}_trend_position"] = -1
                            data[f"{product}_position_entry"] = best_bid

                # Exit logic
                elif trend_position == 1:  # Long
                    entry = data[f"{product}_position_entry"]
                    # Exit if trend reverses or trailing stop hit
                    if trend_down or (entry and micro_mid < entry - cfg["trailing_stop"]):
                        qty = min(pos, od.buy_orders.get(best_bid, 0))
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            data[f"{product}_trend_position"] = 0
                            data[f"{product}_position_entry"] = None
                elif trend_position == -1:  # Short
                    entry = data[f"{product}_position_entry"]
                    if trend_up or (entry and micro_mid > entry + cfg["trailing_stop"]):
                        qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            data[f"{product}_trend_position"] = 0
                            data[f"{product}_position_entry"] = None

                # Fallback market making if no trend position
                if not orders and trend_position == 0:
                    offset = cfg["mm_offset"]
                    size = cfg["mm_size"]
                    if pos < limit:
                        buy_price = max(1, int(micro_mid - offset))
                        if buy_price < best_ask:
                            qty = min(size, limit - pos)
                            orders.append(Order(product, buy_price, qty))
                    if pos > -limit:
                        sell_price = int(micro_mid + offset)
                        if sell_price > best_bid:
                            qty = min(size, limit + pos)
                            orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data