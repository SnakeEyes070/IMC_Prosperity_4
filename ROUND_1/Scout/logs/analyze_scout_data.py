# analyze_scout_data.py
import pandas as pd

df = pd.read_csv('merged_scout_data.csv', delimiter=';')
df['timestamp'] = df['timestamp'].astype(int)
df['mid_price'] = pd.to_numeric(df['mid_price'], errors='coerce')

pepper = df[df['product'] == 'INTARIAN_PEPPER_ROOT'].copy()
osmium = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()

print("=" * 60)
print("🔍 Live Seed Analysis (from Scout Logs)")
print("=" * 60)

# ── PEPPER ─────────────────────────────────────────────────────────────
if not pepper.empty:
    opening_asks = []
    for ts in sorted(pepper['timestamp'].unique())[:5]:
        row = pepper[pepper['timestamp'] == ts].iloc[0]
        if pd.notna(row['ask_price_1']):
            opening_asks.append(float(row['ask_price_1']))
    
    avg_open_ask = sum(opening_asks) / len(opening_asks) if opening_asks else 12000
    
    pepper_sorted = pepper.sort_values('timestamp')
    first_mid = pepper_sorted.iloc[0]['mid_price']
    last_mid = pepper_sorted.iloc[-1]['mid_price']
    first_ts = pepper_sorted.iloc[0]['timestamp']
    last_ts = pepper_sorted.iloc[-1]['timestamp']
    
    live_slope = (last_mid - first_mid) / (last_ts - first_ts) if last_ts > first_ts else 0.001
    
    endgame_df = pepper[pepper['timestamp'] >= 90000]
    endgame_std = endgame_df['mid_price'].std() if len(endgame_df) > 10 else 0
    
    print("\n📈 INTARIAN PEPPER ROOT")
    print(f"   Average opening ask: {avg_open_ask:.2f}")
    print(f"   Live slope: {live_slope:.6f} (baseline 0.001)")
    print(f"   Endgame std dev: {endgame_std:.2f}")
    
    print("\n   🔧 Suggested Adjustments:")
    if avg_open_ask > 12008:
        print(f"      → Increase PEPPER_BUY_TOL to 18")
    elif avg_open_ask < 12004:
        print(f"      → Decrease PEPPER_BUY_TOL to 12")
    else:
        print(f"      → Keep PEPPER_BUY_TOL = 15")
    
    if live_slope < 0.00095:
        print(f"      → Reduce PEPPER_SLOPE to 0.00095")
    elif live_slope > 0.00105:
        print(f"      → Increase PEPPER_SLOPE to 0.00105")
    else:
        print(f"      → Keep PEPPER_SLOPE = 0.001")
    
    if endgame_std > 8:
        print(f"      → Final day is choppy → market‑making pivot RECOMMENDED")
    else:
        print(f"      → Final day is stable → trend‑following can continue")

# ── OSMIUM ─────────────────────────────────────────────────────────────
if not osmium.empty:
    osmium['spread'] = osmium['ask_price_1'] - osmium['bid_price_1']
    avg_spread = osmium['spread'].mean()
    max_spread = osmium['spread'].max()
    
    osmium_sorted = osmium.sort_values('timestamp')
    fair_estimate = osmium_sorted['mid_price'].mean()
    min_mid = osmium_sorted['mid_price'].min()
    max_mid = osmium_sorted['mid_price'].max()
    true_range = max_mid - min_mid
    
    print("\n📊 ASH‑COATED OSMIUM")
    print(f"   Average spread: {avg_spread:.2f} ticks")
    print(f"   Maximum spread: {max_spread:.2f} ticks")
    print(f"   Fair value (mean): {fair_estimate:.2f}")
    print(f"   True range (max-min): {true_range:.2f} ticks")
    
    print("\n   🔧 Suggested Adjustments:")
    if avg_spread < 14:
        print(f"      → Tighten OSM_L1_OFFSET to 3")
    elif avg_spread > 18:
        print(f"      → Widen OSM_L1_OFFSET to 5")
    else:
        print(f"      → Keep OSM_L1_OFFSET = 4")
    
    if true_range < 15:
        print(f"      → Reduce OSM_MR_THRESH to 5")
    elif true_range > 25:
        print(f"      → Increase OSM_MR_THRESH to 8")
    else:
        print(f"      → Keep OSM_MR_THRESH = 7")

print("\n" + "=" * 60)
print("✅ Analysis complete.")