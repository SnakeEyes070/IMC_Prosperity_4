# analysis_fixed.py - Robust Product Classifier (Handles flat periods)
import pandas as pd
import numpy as np
import os

DATA_DIR = "DATA"
PRICE_FILES = [
    "prices_round_1_day_0.csv",
    "prices_round_1_day_-1.csv",
    "prices_round_1_day_-2.csv"
]

def load_all_prices():
    all_dfs = []
    for fname in PRICE_FILES:
        fpath = os.path.join(DATA_DIR, fname)
        try:
            df = pd.read_csv(fpath, delimiter=';')
            print(f"✅ Loaded {fname} ({len(df)} rows)")
            all_dfs.append(df)
        except FileNotFoundError:
            print(f"⚠️ Warning: {fpath} not found, skipping.")
    if not all_dfs:
        raise FileNotFoundError("No price files found.")
    return pd.concat(all_dfs, ignore_index=True)

def robust_autocorr(series, lag=1):
    """Calculate autocorrelation safely, returning 0 if variance is zero."""
    series = series.dropna()
    if len(series) < lag + 5:
        return 0.0
    # Use price differences instead of returns to avoid division by zero
    diff = series.diff().dropna()
    if diff.std() == 0:
        return 0.0  # No movement = no autocorrelation
    # Manual lag correlation
    x = diff[:-lag]
    y = diff[lag:]
    if len(x) < 5:
        return 0.0
    return np.corrcoef(x, y)[0, 1]

def classify_product(df, product_name):
    product_df = df[df['product'] == product_name].copy()
    if product_df.empty:
        return None
    
    product_df['mid_price'] = pd.to_numeric(product_df['mid_price'], errors='coerce')
    product_df = product_df.dropna(subset=['mid_price'])
    
    if len(product_df) < 10:
        return None
    
    # Calculate spread
    if 'ask_price_1' in product_df.columns and 'bid_price_1' in product_df.columns:
        product_df['spread'] = product_df['ask_price_1'] - product_df['bid_price_1']
        mean_spread = product_df['spread'].mean()
    else:
        mean_spread = 10
    
    mean_price = product_df['mid_price'].mean()
    std_price = product_df['mid_price'].std()
    
    # Robust autocorrelation on price differences
    autocorr = robust_autocorr(product_df['mid_price'], lag=1)
    
    # Volatility ratio (helps detect mean reversion vs trend)
    if len(product_df) > 20:
        short_vol = product_df['mid_price'].diff().rolling(5).std().mean()
        long_vol = product_df['mid_price'].diff().rolling(20).std().mean()
        vol_ratio = short_vol / long_vol if long_vol > 0 else 1.0
    else:
        vol_ratio = 1.0
    
    # Classification logic
    if std_price < 10 and abs(autocorr) < 0.2:
        classification = "STABLE_ANCHOR"
        strategy = "Fixed Fair Value Market Making"
        fair_value = int(round(mean_price, -2))
        offset = max(2, int(mean_spread // 3))
        size = 20
        params = {"fair": fair_value, "offset": offset, "size": size}
    elif autocorr < -0.1:
        classification = "VOLATILE_MEAN_REVERTING"
        strategy = "Adaptive EMA Mean Reversion"
        offset = max(3, int(mean_spread // 2))
        size = 12
        params = {"alpha": 0.1, "offset": offset, "size": size, "take_thresh": int(std_price * 0.5)}
    elif autocorr > 0.1:
        classification = "TRENDING_MOMENTUM"
        strategy = "Momentum Following"
        params = {"alpha": 0.2, "threshold": max(3, std_price * 0.5), "size": 15}
    else:
        classification = "RANDOM_WALK"
        strategy = "Pure Market Making (No Prediction)"
        offset = max(3, int(mean_spread // 2))
        size = 10
        params = {"offset": offset, "size": size}
    
    return {
        "product": product_name,
        "mean": mean_price,
        "std": std_price,
        "spread": mean_spread,
        "autocorr": autocorr,
        "classification": classification,
        "strategy": strategy,
        "params": params
    }

def main():
    print("=" * 70)
    print("IMC Prosperity Round 1 - Robust Product Analysis")
    print("=" * 70)
    
    df = load_all_prices()
    products = df['product'].unique()
    print(f"\n📦 Products found: {list(products)}\n")
    
    results = []
    for product in products:
        result = classify_product(df, product)
        if result:
            results.append(result)
            print(f"{'─' * 50}")
            print(f"📌 {result['product']}")
            print(f"   Mean Price : {result['mean']:.2f}")
            print(f"   Std Dev    : {result['std']:.2f}")
            print(f"   Avg Spread : {result['spread']:.2f}")
            print(f"   Autocorr   : {result['autocorr']:.4f}")
            print(f"   ➜ Classification: {result['classification']}")
            print(f"   ➜ Strategy: {result['strategy']}")
            print(f"   ➜ Params: {result['params']}")
    
    print(f"\n{'=' * 70}")
    print("✅ Analysis complete.")
    
    stable = {}
    volatile = {}
    trending = {}
    for r in results:
        if r['classification'] == "STABLE_ANCHOR":
            stable[r['product']] = r['params']
        elif r['classification'] == "VOLATILE_MEAN_REVERTING":
            volatile[r['product']] = r['params']
        elif r['classification'] == "TRENDING_MOMENTUM":
            trending[r['product']] = r['params']
    
    print("\n📝 UPDATED PYTHON DICTIONARIES:")
    print(f"STABLE_ANCHOR = {stable}")
    print(f"VOLATILE_MEAN_REVERTING = {volatile}")
    print(f"TRENDING_MOMENTUM = {trending}")

if __name__ == "__main__":
    main()