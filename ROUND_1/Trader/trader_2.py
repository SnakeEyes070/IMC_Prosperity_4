# trader.py - Round 1 Maximum Profit Edition
# Target: 10,000+ PnL
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import math

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}

        # =========================================================================
        # CONFIGURATION (Calibrated for top-tier performance)
        # =========================================================================
        LIMITS = {
            "ASH_COATED_OSMIUM": 50,
            "INTARIAN_PEPPER_ROOT": 50
        }

        CONFIG = {
    "ASH_COATED_OSMIUM": {
        "fair_initial": 9984,
        "ema_alpha": 0.15,               # Moderate adaptation
        "spread_alpha": 0.25,
        "base_offset": 5,                # Between 3 and 8
        "base_size": 10,                 # Between 8 and 15
        "take_thresh": 250,              # Between 80 and 400
        "momentum_thresh": 60,           # Stronger filter
        "inventory_cap": 0.25,           # Between 0.20 and 0.35
        "endgame_start": 192000
    },
    "INTARIAN_PEPPER_ROOT": {
        "fair_initial": 11479,
        "ema_alpha": 0.18,
        "spread_alpha": 0.30,
        "base_offset": 6,                # Between 4 and 9
        "base_size": 9,                  # Between 6 and 12
        "take_thresh": 500,              # Between 200 and 800
        "momentum_thresh": 100,
        "inventory_cap": 0.22,
        "endgame_start": 192000
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
            if f"{product}_spread_ema" not in data:
                data[f"{product}_spread_ema"] = 10.0
            if f"{product}_last_mid" not in data:
                data[f"{product}_last_mid"] = cfg["fair_initial"]

        # =========================================================================
        # MAIN LOOP
        # =========================================================================
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                result[product] = []
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            
            # Micro-price: volume-weighted mid price (more accurate fair value)
            bid_vol = sum(od.buy_orders.values())
            ask_vol = sum(abs(v) for v in od.sell_orders.values())
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                micro_mid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
            else:
                micro_mid = (best_bid + best_ask) / 2.0
            
            mid = micro_mid
            current_spread = best_ask - best_bid

            limit = LIMITS.get(product, 50)
            pos = state.position.get(product, 0)
            cfg = CONFIG.get(product, CONFIG["ASH_COATED_OSMIUM"])

            orders = []

            # -----------------------------------------------------------------
            # END-GAME FLATTENING (Intelligent limit orders, not market)
            # -----------------------------------------------------------------
            if state.timestamp >= cfg["endgame_start"]:
                # Gradually reduce position to zero using attractive limit orders
                target_pos = 0
                pos_diff = target_pos - pos
                if pos_diff < 0:  # Need to sell
                    sell_qty = min(-pos_diff, limit + pos)
                    # Place sell orders at progressively better prices
                    for i in range(3):
                        price = best_bid + i * 2
                        qty = min(sell_qty // 3 + 1, od.buy_orders.get(price, 0))
                        if qty > 0:
                            orders.append(Order(product, price, -qty))
                elif pos_diff > 0:  # Need to buy
                    buy_qty = min(pos_diff, limit - pos)
                    for i in range(3):
                        price = best_ask - i * 2
                        qty = min(buy_qty // 3 + 1, -od.sell_orders.get(price, 0))
                        if qty > 0:
                            orders.append(Order(product, price, qty))
                result[product] = orders
                continue

            # -----------------------------------------------------------------
            # STATE UPDATES (EMA fair value, volatility, momentum)
            # -----------------------------------------------------------------
            alpha = cfg["ema_alpha"]
            key_ema = f"{product}_ema"
            data[key_ema] = alpha * mid + (1 - alpha) * data[key_ema]
            fair = data[key_ema]

            # Spread EMA (volatility proxy)
            spread_alpha = cfg["spread_alpha"]
            key_spread = f"{product}_spread_ema"
            data[key_spread] = spread_alpha * current_spread + (1 - spread_alpha) * data[key_spread]
            avg_spread = data[key_spread]

            # Short-term momentum (mid - EMA)
            momentum = mid - fair

            # -----------------------------------------------------------------
            # DYNAMIC PARAMETERS
            # -----------------------------------------------------------------
            position_ratio = abs(pos) / limit
            
            # Offset widens with inventory and volatility
            inventory_skew = 1.0 + position_ratio * 1.5
            volatility_factor = avg_spread / 10.0  # Normalize
            dynamic_offset = int(cfg["base_offset"] * inventory_skew * volatility_factor)
            dynamic_offset = max(2, min(dynamic_offset, current_spread - 2))

            # Size scales down near limits, but stays aggressive
            buy_cap = limit - pos
            sell_cap = limit + pos
            size_factor = min(1.0, buy_cap / cfg["base_size"], sell_cap / cfg["base_size"])
            dynamic_size = max(5, int(cfg["base_size"] * size_factor))

            take_thresh = cfg["take_thresh"]
            mom_thresh = cfg["momentum_thresh"]

            # -----------------------------------------------------------------
            # OPPORTUNISTIC MEAN-REVERSION TAKING (With momentum filter)
            # -----------------------------------------------------------------
            # Buy if price is cheap AND not in a strong downtrend
            if best_ask < fair - take_thresh and momentum > -mom_thresh:
                available = -od.sell_orders.get(best_ask, 0)
                qty = min(available, buy_cap, dynamic_size + 6)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))

            # Sell if price is expensive AND not in a strong uptrend
            if best_bid > fair + take_thresh and momentum < mom_thresh:
                available = od.buy_orders.get(best_bid, 0)
                qty = min(available, sell_cap, dynamic_size + 6)
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))

            # -----------------------------------------------------------------
            # AGGRESSIVE SKIMMING (Capture mispriced orders that cross our quotes)
            # -----------------------------------------------------------------
            our_bid = int(fair - dynamic_offset)
            our_ask = int(fair + dynamic_offset)

            if not orders:
                if best_ask < our_bid:
                    available = -od.sell_orders.get(best_ask, 0)
                    qty = min(available, buy_cap, dynamic_size + 3)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

                if best_bid > our_ask:
                    available = od.buy_orders.get(best_bid, 0)
                    qty = min(available, sell_cap, dynamic_size + 3)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))

            # -----------------------------------------------------------------
            # CORE MARKET MAKING (Multiple levels for higher fill rate)
            # -----------------------------------------------------------------
            if not orders:
                # Place two levels on each side to increase fill probability
                if buy_cap > 0:
                    for level in range(2):
                        buy_price = max(1, int(fair - dynamic_offset * (1 + level * 0.5)))
                        if buy_price < best_ask:
                            qty = min(dynamic_size // (level + 1), buy_cap)
                            if qty > 0:
                                orders.append(Order(product, buy_price, qty))
                                buy_cap -= qty

                if sell_cap > 0:
                    for level in range(2):
                        sell_price = int(fair + dynamic_offset * (1 + level * 0.5))
                        if sell_price > best_bid:
                            qty = min(dynamic_size // (level + 1), sell_cap)
                            if qty > 0:
                                orders.append(Order(product, sell_price, -qty))
                                sell_cap -= qty

            # -----------------------------------------------------------------
            # INVENTORY PRESSURE (Graduated but stronger)
            # -----------------------------------------------------------------
            inv_ratio = abs(pos) / limit
            if inv_ratio > cfg["inventory_cap"]:
                intensity = (inv_ratio - cfg["inventory_cap"]) / (1.0 - cfg["inventory_cap"])
                pressure_qty = int(dynamic_size * intensity * 2.0)
                if pos > 0:
                    for price in sorted(od.buy_orders.keys(), reverse=True):
                        qty = min(pos, od.buy_orders[price], pressure_qty)
                        if qty > 0:
                            orders.append(Order(product, price, -qty))
                            pressure_qty -= qty
                            if pressure_qty <= 0:
                                break
                elif pos < 0:
                    for price in sorted(od.sell_orders.keys()):
                        qty = min(-pos, -od.sell_orders[price], pressure_qty)
                        if qty > 0:
                            orders.append(Order(product, price, qty))
                            pressure_qty -= qty
                            if pressure_qty <= 0:
                                break

            result[product] = orders

        # =========================================================================
        # SAVE STATE
        # =========================================================================
        trader_data = json.dumps(data)
        return result, 0, trader_data