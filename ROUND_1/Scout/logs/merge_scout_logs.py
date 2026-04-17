# merge_scout_logs.py
# Place this in the Scout folder (where the 'logs' directory is located)
import os
import json
import csv

def extract_activities(log_file):
    with open(log_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('activitiesLog', '')

def parse_csv(csv_string):
    lines = csv_string.strip().split('\n')
    if not lines:
        return []
    reader = csv.DictReader(lines, delimiter=';')
    return list(reader)

def main():
    all_rows = []
    
    # Determine logs directory – if we're inside 'logs', use current dir
    if os.path.basename(os.getcwd()) == 'logs':
        log_dir = '.'
    else:
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            print(f"❌ '{log_dir}' folder not found. Make sure you're in the correct directory.")
            return
    
    for filename in os.listdir(log_dir):
        if filename.endswith('.log'):
            filepath = os.path.join(log_dir, filename)
            try:
                csv_str = extract_activities(filepath)
                rows = parse_csv(csv_str)
                all_rows.extend(rows)
                print(f"✅ {filename}: {len(rows)} rows")
            except Exception as e:
                print(f"❌ {filename}: {e}")

    all_rows.sort(key=lambda x: int(x['timestamp']))
    
    with open('merged_scout_data.csv', 'w', newline='', encoding='utf-8') as f:
        if all_rows:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys(), delimiter=';')
            writer.writeheader()
            writer.writerows(all_rows)
    
    print(f"\n🎯 Merged {len(all_rows)} rows into merged_scout_data.csv")

if __name__ == "__main__":
    main()