# Spoof‑Sim

A **self‑contained simulator** that continuously places and cancels “spoof”
orders so that you can feed realistic order‑flow into a *spoofing‑detection*
algorithm.

The project contains:

* **spoof.py** – in‑memory matching engine (`SimExchange`) plus a dry‑run
  wrapper for a real venue (`LiveExchange`).
* CLI that lets you switch between simulation (`--mode sim`, default) and
  paper‑trading on a live venue (`--mode live`).

---

## Spoofing explained

Spoofing is a type of market manipulation where a trader:

1. Rapidly submits large visible orders away from the current price to create
   the illusion of strong buying or selling pressure.
2. Induces other participants (or algos) to adjust their own orders/pricing.
3. Executes a genuine trade on the opposite side at a more favourable price.
4. Quickly cancels the spoof orders before they are matched.

Because the deceptive orders never intend to trade, the spoofer **misleads
price‑discovery**, nudging the market in a direction that benefits their
hidden intent.  
The advantage is unfair because legitimate participants react to *false*
liquidity, incur transaction costs, or provide better prices than they would
have offered had the book reflected authentic interest.

Regulators classify spoofing as market abuse; penalties include fines and
trading bans.  This repository exists solely to **test and benchmark detection
algorithms** without sending manipulative orders to a real venue.

## Quick start

```bash
# run the pure in‑memory simulation
python spoof.py --mode sim

# talk to a live venue in *paper* mode
export EX_KEY=your_key
export EX_SECRET=your_secret
export EX_PAPER=true        # safety guard (default)
python spoof.py --mode live --symbol BTC/USDT --layers 4
```

### Important CLI flags

| flag            | default | description                           |
|-----------------|---------|---------------------------------------|
| `--layers`      | 3       | how many spoof price levels to post   |
| `--layer-size`  | 5.0     | size per spoof level                  |
| `--offset`      | 0.5     | price ticks away from best bid/ask    |
| `--hold`        | 0.2 s   | how long spoof orders stay on book    |
| `--delay`       | 0.05 s  | pause before the “real” order         |
| `--pause`       | 2 s     | sleep between spoofing cycles         |

---

## How the script works

1. Read top‑of‑book (`bid` / `ask`) from the chosen `Exchange`.
2. Place a *stack* of limit orders on one side of the book (the “spoof”
   layers).
3. After `--delay`, submit one *real* order on the opposite side.
4. Hold the spoof layers for `--hold` seconds.
5. Cancel all spoof orders and repeat after `--pause`.

In **simulation** mode the in‑memory book matches orders instantly, giving you
fills and cancels to analyse.  
In **live** mode the implementation is a *stub*: it logs orders instead of
sending them unless you replace the `LiveExchange` methods and remove
`EX_PAPER=true`.

---

