
# Adaptive Crypto Trading Bot (Phase 1)
*Initial commit generated 2025-06-20*

This repository contains the first two fully‑functional blocks:

1. **Data Bus** – real‑time feed normalisation and Redis publication  
2. **Trend‑TF Agent** – trend‑following strategy operating on m5 bars  

Each block includes:
* production‑ready Python module (under `src/`)
* detailed technical description (in `docs/`)
* unit‑tests (`tests/`)
* minimal configuration in `config.yaml`

Subsequent commits will add Mean‑Revert, VWAP‑Sweep, StatArb, Market‑Making, Execution Kernel, Meta‑Learner, and Monitoring.

> **How to run**  
```bash
python -m pip install -r requirements.txt
python src/core/data_bus.py     # starts feed normaliser
python src/agents/trend_tf.py   # runs Trend‑TF agent (dummy back‑feed)
pytest tests/                   # run unit tests
```


## Phase 2 Added
* Mean‑Revert Agent
* VWAP‑Sweep Agent
