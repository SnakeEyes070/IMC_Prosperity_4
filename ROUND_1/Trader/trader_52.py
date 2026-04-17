# trader.py - Quantitative Models for Round 1 (Target: 7,000+)
from ROUND_1.datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math

class Trader:
    def run(self, state: TradingState):
        result = {}
        LIMITS = {"ASH_COATED_OSMIUM": 50, "INTARIAN_PEPPER_ROOT": 50}

        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except:
                pass

        PEPPER = "INTARIAN_PEPPER_ROOT"
        OSMIUM = "ASH_COATED_OSMIUM"

        ENDGAME_TS = 95_000

        # ----- PEPPER: Dynamic Linear Regression Model -----
        if PEPPER in state.order_depths:
            od = state.order_depths[PEPPER]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                mid = (best_bid + best_ask) / 2.0
                pos = state.position.get(PEPPER, 0)
                ts = state.timestamp
                orders = []

                # Maintain price history for regression (last 20 points)
                if "price_history" not in data:
                    data["price_history"] = []
                    data["time_history"] = []
                
                data["price_history"].append(mid)
                data["time_history"].append(ts)
                
                # Keep last 30 points (enough for stable regression)
                if len(data["price_history"]) > 30:
                    data["price_history"].pop(0)
                    data["time_history"].pop(0)
                
                # Compute linear regression slope if enough points
                slope = 0.001  # default fallback
                intercept = best_ask
                if len(data["price_history"]) >= 5:
                    n = len(data["price_history"])
                    t_vals = data["time_history"]
                    p_vals = data["price_history"]
                    
                    # Simple linear regression: p = a + b * t
                    sum_t = sum(t_vals)
                    sum_p = sum(p_vals)
                    sum_tp = sum(t * p for t, p in zip(t_vals, p_vals))
                    sum_t2 = sum(t * t for t in t_vals)
                    
                    slope = (n * sum_tp - sum_t * sum_p) / (n * sum_t2 - sum_t * sum_t) if (n * sum_t2 - sum_t * sum_t) != 0 else 0.001
                    intercept = (sum_p - slope * sum_t) / n
                
                # Day boundary detection (timestamp reset)
                if "last_ts" not in data:
                    data["last_ts"] = ts
                if ts < data["last_ts"]:
                    # New day – reset history and anchor
                    data["price_history"] = [mid]
                    data["time_history"] = [ts]
                    intercept = best_ask
                    slope = 0.001
                data["last_ts"] = ts
                
                # Fair value from regression
                fair = intercept + slope * ts
                
                if ts >= ENDGAME_TS:
                    if pos > 0:
                        qty = min(pos, od.buy_orders.get(best_bid, 0), 8)
                        if qty > 0:
                            orders.append(Order(PEPPER, best_bid, -qty))
                else:
                    buy_cap = LIMITS[PEPPER] - pos
                    if buy_cap > 0:
                        # Only buy if ask is not too far above regression fair
                        if best_ask <= fair + 10:
                            qty = min(buy_cap, -od.sell_orders.get(best_ask, 0), 30)
                            if qty > 0:
                                orders.append(Order(PEPPER, best_ask, qty))

                result[PEPPER] = orders

        # ----- OSMIUM: Ornstein-Uhlenbeck Mean Reversion Model -----
        if OSMIUM in state.order_depths:
            od = state.order_depths[OSMIUM]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                mid = (best_bid + best_ask) / 2.0
                pos = state.position.get(OSMIUM, 0)
                limit = LIMITS[OSMIUM]
                orders = []

                # Maintain price history for OU parameter estimation
                if "osm_history" not in data:
                    data["osm_history"] = []
                data["osm_history"].append(mid)
                if len(data["osm_history"]) > 50:
                    data["osm_history"].pop(0)
                
                # Estimate OU parameters: long-term mean (mu), mean-reversion speed (theta), volatility (sigma)
                mu = 10000.0  # long-term mean
                theta = 0.1   # mean-reversion speed (higher = faster reversion)
                if len(data["osm_history"]) >= 10:
                    # Calculate mean of recent prices
                    mu = sum(data["osm_history"]) / len(data["osm_history"])
                    # Estimate theta from autocorrelation
                    if len(data["osm_history"]) >= 2:
                        diffs = [data["osm_history"][i] - data["osm_history"][i-1] for i in range(1, len(data["osm_history"]))]
                        prev = data["osm_history"][:-1]
                        # Simple AR(1) regression: dx = theta * (mu - x) * dt + noise
                        # Approximate theta from lag-1 autocorrelation
                        if len(diffs) > 1:
                            autocorr = sum((diffs[i] - sum(diffs)/len(diffs)) * (prev[i] - mu) for i in range(len(diffs))) / (len(diffs) * (sum((p - mu)**2 for p in prev)/len(prev) + 1e-6))
                            theta = max(0.05, min(0.3, -math.log(abs(autocorr) + 1e-6) / 100))
                
                # Dynamic mean-reversion threshold based on OU half-life
                # Half-life = ln(2) / theta. If theta is large, price reverts quickly → tighter threshold.
                half_life = math.log(2) / theta if theta > 0 else 10
                mr_threshold = max(4, min(12, int(half_life / 10)))
                
                # Imbalance filter
                bid_vol = sum(od.buy_orders.values())
                ask_vol = sum(abs(v) for v in od.sell_orders.values())
                total_vol = bid_vol + ask_vol
                imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0
                
                # Market making with OU-informed fair value
                fair = int(mu)
                base_offset = 3
                size = 18
                
                # Overbidding adjustment
                buy_offset = base_offset
                sell_offset = base_offset
                if od.buy_orders.get(best_bid, 0) > 10:
                    buy_offset = max(1, base_offset - 1)
                if abs(od.sell_orders.get(best_ask, 0)) > 10:
                    sell_offset = max(1, base_offset - 1)
                
                # Mean-reversion take (OU model says price will revert to mu)
                if best_ask < fair - mr_threshold and pos < limit:
                    qty = min(limit - pos, -od.sell_orders.get(best_ask, 0), 20)
                    if qty > 0:
                        orders.append(Order(OSMIUM, best_ask, qty))
                elif best_bid > fair + mr_threshold and pos > -limit:
                    qty = min(limit + pos, od.buy_orders.get(best_bid, 0), 20)
                    if qty > 0:
                        orders.append(Order(OSMIUM, best_bid, -qty))
                else:
                    # Passive market making
                    buy_cap = limit - pos
                    sell_cap = limit + pos
                    
                    if buy_cap > 0 and imbalance > -0.3:
                        buy_price = fair - buy_offset
                        if buy_price < best_ask:
                            qty = min(size, buy_cap)
                            orders.append(Order(OSMIUM, buy_price, qty))
                    
                    if sell_cap > 0 and imbalance < 0.3:
                        sell_price = fair + sell_offset
                        if sell_price > best_bid:
                            qty = min(size, sell_cap)
                            orders.append(Order(OSMIUM, sell_price, -qty))

                result[OSMIUM] = orders

        return result, 0, json.dumps(data)