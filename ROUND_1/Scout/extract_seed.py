# extract_seed.py - Reconstruct the full Round 1 seed from scout logs
import os
import json
import base64
import zlib
import re

def extract_from_log(filepath):
    """Extract the seed data from a single scout log."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the traderData string
    match = re.search(r'"traderData":\s*"([^"]+)"', content)
    if not match:
        print(f"❌ No traderData found in {filepath}")
        return {}
    
    b64_str = match.group(1)
    try:
        compressed = base64.b64decode(b64_str)
        decompressed = zlib.decompress(compressed)
        data = json.loads(decompressed.decode('utf-8'))
        return data
    except Exception as e:
        print(f"❌ Failed to decode {filepath}: {e}")
        return {}

def main():
    all_ticks = {}  # timestamp -> {product: {"bid": x, "ask": y}}
    
    log_files = [f for f in os.listdir('logs') if f.endswith('.log')]
    print(f"Found {len(log_files)} log files")
    
    for log_file in log_files:
        filepath = os.path.join('logs', log_file)
        data = extract_from_log(filepath)
        
        if 'ticks' in data:
            for tick in data['ticks']:
                ts = tick['ts']
                if ts not in all_ticks:
                    all_ticks[ts] = {}
                for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
                    if product in tick and tick[product] is not None:
                        all_ticks[ts][product] = tick[product]
            print(f"✅ {log_file}: {len(data['ticks'])} ticks")
    
    # Convert to sorted list
    sorted_ticks = []
    for ts in sorted(all_ticks.keys()):
        tick_data = {"ts": ts}
        tick_data.update(all_ticks[ts])
        sorted_ticks.append(tick_data)
    
    # Save the full seed
    full_seed = {"ticks": sorted_ticks}
    with open("full_seed.json", "w") as f:
        json.dump(full_seed, f)
    
    print(f"\n🎯 Merged {len(sorted_ticks)} unique timestamps into full_seed.json")

if __name__ == "__main__":
    main()