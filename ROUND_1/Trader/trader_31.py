# trader.py - Fixed & Optimized (Round 1 Final)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        # =========================================================================
        # MASTER CONFIGURATION – Calibrated from peak 5,023 run
        # =========================================================================
        CONFIG = {
            "ASH_COATED_OSMIUM": {
                "fair_initial": 9984,
                "ema_alpha": 0.15,
                "mm_offset": 2,
                "mm_size": 22,
                "max_size": 30,
                "mean_rev_thresh": 40,
                "stop_loss_ticks": 10,
                "momentum_thresh": 1.8,
                "imbalance_thresh": 0.20,
                "volatility_window": 15,
                "levels": 3,
                "max_spread": 20
            },
            "INTARIAN_PEPPER_ROOT": {
                "fair_initial": 11479,
                "ema_fast_alpha": 0.15,
                "ema_slow_alpha": 0.05,
                "trend_confirm_thresh": 40,
                "trend_size": 18,
                "trailing_stop_ticks": 50,
                "pullback_entry": True,
                "mm_offset": 4,
                "mm_size": 10,
                "max_spread": 25,
                "inventory_cap": 0.35
            }
        }

        ENDGAME = 194000

        # =========================================================================
        # PERSISTENT STATE (traderData) – FIXED INITIALIZATION
        # =========================================================================
        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except:
                pass

        for product, cfg in CONFIG.items():
            # ----- Osmium (Range‑Bound) -----
            if product == "ASH_COATED_OSMIUM":
                if f"{product}_ema" not in data:
                    data[f"{product}_ema"] = cfg["fair_initial"]
                if f"{product}_price_history" not in data:
                    data[f"{product}_price_history"] = []
                if f"{product}_volatility" not in data:
                    data[f"{product}_volatility"] = 5.0
                if f"{product}_position_entry" not in data:
                    data[f"{product}_position_entry"] = None

            # ----- Pepper (Trending) -----
            else:  # INTARIAN_PEPPER_ROOT
                if f"{product}_fast_ema" not in data:
                    data[f"{product}_fast_ema"] = cfg["fair_initial"]
                if f"{product}_slow_ema" not in data:
                    data[f"{product}_slow_ema"] = cfg["fair_initial"]
                if f"{product}_trend_position" not in data:
                    data[f"{product}_trend_position"] = 0
                if f"{product}_position_entry" not in data:
                    data[f"{product}_position_entry"] = None
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

            if spread > cfg["max_spread"]:
                result[product] = []
                continue

            limit = LIMITS[product]
            pos = state.position.get(product, 0)

            # ----- Micro‑price (volume‑weighted) -----
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                micro_mid = (best_bid + best_ask) / 2.0

            orders = []

            # ----- End‑game flattening -----
            if state.timestamp >= ENDGAME:
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

            # ===== ASH_COATED_OSMIUM: Aggressive Range‑Bound =====
            if product == "ASH_COATED_OSMIUM":
                key_ema = f"{product}_ema"
                data[key_ema] = cfg["ema_alpha"] * micro_mid + (1 - cfg["ema_alpha"]) * data[key_ema]
                fair = data[key_ema]

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

                imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0
                momentum = micro_mid - fair

                # Stop‑loss
                entry = data[f"{product}_position_entry"]
                if pos != 0 and entry is not None:
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
                vol_ratio = vol / 5.0
                vol_ratio = max(0.5, min(vol_ratio, 2.0))
                position_ratio = abs(pos) / limit
                dynamic_offset = int(cfg["mm_offset"] * vol_ratio * (1 + position_ratio * 0.3))
                dynamic_offset = max(1, min(dynamic_offset, spread - 1))

                buy_cap = limit - pos
                sell_cap = limit + pos
                size_factor = min(1.0, buy_cap / cfg["mm_size"], sell_cap / cfg["mm_size"])
                base_size = max(5, int(cfg["mm_size"] * size_factor))

                is_breakout = abs(momentum) > cfg["momentum_thresh"] * vol
                imbalance_ok = abs(imbalance) > cfg["imbalance_thresh"]

                # Mean reversion
                if not is_breakout:
                    if best_ask < fair - cfg["mean_rev_thresh"] and imbalance > -cfg["imbalance_thresh"]:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, base_size + 6)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            if pos == 0:
                                data[f"{product}_position_entry"] = best_ask
                    if best_bid > fair + cfg["mean_rev_thresh"] and imbalance < cfg["imbalance_thresh"]:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, base_size + 6)
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            if pos == 0:
                                data[f"{product}_position_entry"] = best_bid

                # Breakout
                elif is_breakout and imbalance_ok:
                    if momentum > 0 and imbalance > 0:
                        available = -od.sell_orders.get(best_ask, 0)
                        qty = min(available, limit - pos, cfg["max_size"])
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                    elif momentum < 0 and imbalance < 0:
                        available = od.buy_orders.get(best_bid, 0)
                        qty = min(available, limit + pos, cfg["max_size"])
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))

                # Core market making (multi‑level)
                if not orders:
                    for level in range(cfg["levels"]):
                        level_offset = dynamic_offset + level
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

            # ===== INTARIAN_PEPPER_ROOT: Pure Trend Following =====
            else:
                fast_key = f"{product}_fast_ema"
                slow_key = f"{product}_slow_ema"
                data[fast_key] = cfg["ema_fast_alpha"] * micro_mid + (1 - cfg["ema_fast_alpha"]) * data[fast_key]
                data[slow_key] = cfg["ema_slow_alpha"] * micro_mid + (1 - cfg["ema_slow_alpha"]) * data[slow_key]

                fast_ema = data[fast_key]
                slow_ema = data[slow_key]
                trend_up = fast_ema > slow_ema + cfg["trend_confirm_thresh"]
                trend_down = fast_ema < slow_ema - cfg["trend_confirm_thresh"]
                trend_position = data[f"{product}_trend_position"]
                entry_price = data[f"{product}_position_entry"]

                # Exit
                if trend_position == 1:
                    if trend_down or (entry_price and micro_mid < entry_price - cfg["trailing_stop_ticks"]):
                        qty = min(pos, od.buy_orders.get(best_bid, 0))
                        if qty > 0:
                            orders.append(Order(product, best_bid, -qty))
                            data[f"{product}_trend_position"] = 0
                            data[f"{product}_position_entry"] = None
                elif trend_position == -1:
                    if trend_up or (entry_price and micro_mid > entry_price + cfg["trailing_stop_ticks"]):
                        qty = min(-pos, -od.sell_orders.get(best_ask, 0))
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            data[f"{product}_trend_position"] = 0
                            data[f"{product}_position_entry"] = None

                # Entry
                if trend_position == 0:
                    if trend_up:
                        if cfg["pullback_entry"]:
                            if best_ask <= fast_ema:
                                available = -od.sell_orders.get(best_ask, 0)
                                qty = min(available, limit - pos, cfg["trend_size"])
                                if qty > 0:
                                    orders.append(Order(product, best_ask, qty))
                                    data[f"{product}_trend_position"] = 1
                                    data[f"{product}_position_entry"] = best_ask
                        else:
                            available = -od.sell_orders.get(best_ask, 0)
                            qty = min(available, limit - pos, cfg["trend_size"])
                            if qty > 0:
                                orders.append(Order(product, best_ask, qty))
                                data[f"{product}_trend_position"] = 1
                                data[f"{product}_position_entry"] = best_ask
                    elif trend_down:
                        if cfg["pullback_entry"]:
                            if best_bid >= fast_ema:
                                available = od.buy_orders.get(best_bid, 0)
                                qty = min(available, limit + pos, cfg["trend_size"])
                                if qty > 0:
                                    orders.append(Order(product, best_bid, -qty))
                                    data[f"{product}_trend_position"] = -1
                                    data[f"{product}_position_entry"] = best_bid
                        else:
                            available = od.buy_orders.get(best_bid, 0)
                            qty = min(available, limit + pos, cfg["trend_size"])
                            if qty > 0:
                                orders.append(Order(product, best_bid, -qty))
                                data[f"{product}_trend_position"] = -1
                                data[f"{product}_position_entry"] = best_bid

                # Fallback market making
                if not orders and trend_position == 0:
                    offset = cfg["mm_offset"]
                    size = cfg["mm_size"]
                    buy_cap = limit - pos
                    sell_cap = limit + pos

                    if buy_cap > 0:
                        buy_price = max(1, int(micro_mid - offset))
                        if buy_price < best_ask:
                            qty = min(size, buy_cap)
                            orders.append(Order(product, buy_price, qty))
                    if sell_cap > 0:
                        sell_price = int(micro_mid + offset)
                        if sell_price > best_bid:
                            qty = min(size, sell_cap)
                            orders.append(Order(product, sell_price, -qty))

            result[product] = orders

        trader_data = json.dumps(data)
        return result, 0, trader_data