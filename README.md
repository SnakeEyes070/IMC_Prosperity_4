# IMC Prosperity 4 - Round 1 Algorithm

This repository contains the final submission for Round 1 of the IMC Prosperity 4 algorithmic trading challenge. The algorithm achieved a peak profit of **6,294 XIRECs** and provides a robust foundation for future rounds.

## Repository Structure
.
├── trader.py # Final Round 1 trading algorithm
├── datamodel.py # Official IMC data structures
├── analysis.py # Product classification and data analysis
├── test.py # Local backtesting harness
├── requirements.txt # Python dependencies
├── data/ # Sample data capsule (CSV files)
│ ├── prices_round_1_day_0.csv
│ ├── prices_round_1_day_-1.csv
│ └── prices_round_1_day_-2.csv
└── scout/ # Seed mapping scripts and logs (optional)

text

## Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/SnakeEyes070/IMC_Prosperity_4.git
cd IMC_Prosperity_4
2. Set Up a Virtual Environment
bash
python -m venv .venv
source .venv/bin/activate      # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
3. Run Local Backtest
bash
python test.py
This simulates the algorithm on the provided sample data and outputs the final PnL along with a performance graph.

Strategy Overview
The algorithm uses a dual-asset approach tailored to each product's observed market behavior.

INTARIAN PEPPER ROOT (Trend Following)
Market Behavior: Linear uptrend with a slope of 0.001 points per timestamp (+100 points per day). Opening spread averages 16 ticks.

Strategy: Detects new days via timestamp reset. On each new day, it immediately accumulates a maximum long position of +50 by sweeping the ask side with a wide tolerance. Holds across days and unwinds gradually on the final day (starting at timestamp 96,500) using limit orders to minimize slippage.

ASH-COATED OSMIUM (Market Making + Mean Reversion)
Market Behavior: Stable mean-reversion around 10,000, with a standard deviation of approximately 5 ticks and an average spread of 16 ticks.

Strategy: Employs a three-level passive quote ladder with dynamic offsets that adapt to the current spread. Aggressively mean-reverts when price deviates by 8 ticks from fair value. Inventory-skewed sizes keep the position neutral.

Round 1 Performance
Metric	Value
Final Algorithmic PnL	6,294 XIRECs
Manual Trading PnL	~587,500 XIRECs
Total Round 1	>593,000 XIRECs
Goal (200,000 XIRECs)	Exceeded by 3x
Future Rounds
The modular structure of trader.py is designed for easy extension:

Round 2: ETF / Basket Arbitrage

Round 3: Black-Scholes Options Pricing

Round 4: Locational Arbitrage (Conversions)

Round 5: Mixed Strategies with Informed Trader Tracking

License
This project is for educational purposes as part of the IMC Prosperity 4 competition.
