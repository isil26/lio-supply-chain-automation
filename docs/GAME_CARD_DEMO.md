# Game card recovery demo

Run from the repository root with the Python dependencies in the README installed.

```sh
SOONY_LLM_PROVIDER=none CHASER_REAL_SMTP=0 \
  python3 -m src.orchestrator --demo --game-card-replay --data case-data --port 8796
```

Open [Game card recovery](http://127.0.0.1:8796/game-cards). Start a fresh process for each rehearsal. The baseline comes from the 19:25 case snapshot, and the replay stages one minimized ERP receipt row from the later portal update.

1. Select **Process goods receipt**. Hamburg received 28,000 game cards. The planning engine reconciles the receipt with the air waybill and moves all 28,000 from inbound to on-hand stock.
2. Point to **6,800 cards still short**. The 500-run median moves from 614,650 to 639,100 for Standard and from 62,550 to 66,100 for Collector’s. Both editions still miss their targets in all 500 trials. The 20,000-card supplier balance is due after launch.
3. Select **Simulate approval** on the single game-card recovery action. PP-07 routes it to Felix Brunner. The replay records his simulated decision and prepares an internal recovery message. The approval covers tracking the remaining shortage and escalating a documented recovery option.

The runtime cites the goods receipt and shipping advice. Approval takes place in the disposable local replay database in dry-run mode.
