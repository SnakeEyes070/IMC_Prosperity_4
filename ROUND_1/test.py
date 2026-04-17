# test.py - Robust Local Simulation with Debug Output
import csv
from collections import defaultdict
from typing import Dict, List, Tuple
from ROUND_1.datamodel import OrderDepth, Listing, Observation, TradingState, Order

DATA_DIR = "DATA"
PRICE_FILES = ["prices_round_1_day_0.csv", "prices_round_1_day_-1.csv", "prices_round_1_day_-2.csv"]

LIMITS = {
    "ASH_COATED_OSMIUM": 50,
    "INTARIAN_PEPPER_ROOT": 50
}

def load_prices() -> Dict[int, Dict[str, OrderDepth]]:
    data = defaultdict(lambda: defaultdict(OrderDepth))
    for fname in PRICE_FILES:
        path = f"{DATA_DIR}/{fname}"
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    ts = int(row['timestamp'])
                    product = row['product']
                    od = data[ts][product]
                    for i in range(1, 4):
                        bid_p = row.get(f'bid_price_{i}')
                        bid_v = row.get(f'bid_volume_{i}')
                        if bid_p and bid_v:
                            price = int(bid_p)
                            vol = int(bid_v)
                            od.buy_orders[price] = od.buy_orders.get(price, 0) + vol
                        ask_p = row.get(f'ask_price_{i}')
                        ask_v = row.get(f'ask_volume_{i}')
                        if ask_p and ask_v:
                            price = int(ask_p)
                            vol = int(ask_v)
                            od.sell_orders[price] = od.sell_orders.get(price, 0) - vol
        except FileNotFoundError:
            print(f"Warning: {path} not found")
    return dict(data)

def main():
    print("=" * 60)
    print("IMC Prosperity Round 1 - Debug Simulation")
    print("=" * 60)
    
    all_prices = load_prices()
    sorted_ts = sorted(all_prices.keys())
    print(f"Loaded {len(sorted_ts)} timestamps")
    print(f"First 5 timestamps: {sorted_ts[:5]}")
    
    # Inspect first timestamp's order book
    first_ts = sorted_ts[0]
    print(f"\n--- First Timestamp ({first_ts}) Order Books ---")
    for product, od in all_prices[first_ts].items():
        print(f"{product}: Best Bid = {max(od.buy_orders.keys()) if od.buy_orders else 'N/A'}, Best Ask = {min(od.sell_orders.keys()) if od.sell_orders else 'N/A'}")
    
    from trader_21 import Trader
    trader = Trader()
    
    position = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
    cash = 0.0
    pnl_history = []
    trader_data = ""
    
    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "XIRECS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "XIRECS")
    }
    
    print("\n" + "=" * 60)
    print("Starting simulation loop...")
    print("=" * 60)
    
    for i, ts in enumerate(sorted_ts):
        ods = all_prices[ts]
        
        state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings=listings,
            order_depths=ods,
            own_trades={},
            market_trades={},
            position=position.copy(),
            observations=Observation({}, {})
        )
        
        result, _, new_trader_data = trader.run(state)
        trader_data = new_trader_data
        
        # Execute orders
        for product, orders in result.items():
            if product not in ods:
                continue
            od = ods[product]
            limit = LIMITS.get(product, 50)
            for order in orders:
                price = order.price
                qty = order.quantity
                if qty > 0:  # Buy
                    if od.sell_orders:
                        best_ask = min(od.sell_orders.keys())
                        if price >= best_ask:
                            available = -od.sell_orders[best_ask]
                            exec_qty = min(qty, available, limit - position[product])
                            if exec_qty > 0:
                                position[product] += exec_qty
                                cash -= exec_qty * best_ask
                                od.sell_orders[best_ask] += exec_qty
                                if od.sell_orders[best_ask] == 0:
                                    del od.sell_orders[best_ask]
                                if i < 5:  # Debug first 5 timestamps
                                    print(f"  EXECUTED BUY: {exec_qty} {product} @ {best_ask}")
                else:  # Sell
                    qty = -qty
                    if od.buy_orders:
                        best_bid = max(od.buy_orders.keys())
                        if price <= best_bid:
                            available = od.buy_orders[best_bid]
                            exec_qty = min(qty, available, limit + position[product])
                            if exec_qty > 0:
                                position[product] -= exec_qty
                                cash += exec_qty * best_bid
                                od.buy_orders[best_bid] -= exec_qty
                                if od.buy_orders[best_bid] == 0:
                                    del od.buy_orders[best_bid]
                                if i < 5:
                                    print(f"  EXECUTED SELL: {exec_qty} {product} @ {best_bid}")
        
        # Mark-to-market
        mtm = 0.0
        for product, pos in position.items():
            if product in ods:
                od = ods[product]
                if od.buy_orders and od.sell_orders:
                    best_bid = max(od.buy_orders.keys())
                    best_ask = min(od.sell_orders.keys())
                    mid = (best_bid + best_ask) / 2.0
                    mtm += pos * mid
        
        total_pnl = cash + mtm
        pnl_history.append((ts, total_pnl))
        
        if i < 5:
            print(f"TS {ts}: cash={cash:.2f}, mtm={mtm:.2f}, total={total_pnl:.2f}, pos={position}")
        
        if (i+1) % 2000 == 0 or ts == sorted_ts[-1]:
            print(f"TS {ts:6d} | PnL: {total_pnl:12.2f} | Osmium: {position['ASH_COATED_OSMIUM']:3d} | Pepper: {position['INTARIAN_PEPPER_ROOT']:3d}")
    
    final_pnl = pnl_history[-1][1] if pnl_history else 0
    peak_pnl = max(p for _, p in pnl_history) if pnl_history else 0
    print(f"\n✅ FINAL PnL: {final_pnl:.2f}")
    print(f"📈 PEAK PnL: {peak_pnl:.2f}")

if __name__ == "__main__":
    main()