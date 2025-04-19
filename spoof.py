"""
Spoofing *simulation* script – production‑style scaffolding
===========================================================

Designed for *testing* spoof‑detection algorithms, **not** for executing
illegal market behaviour on a real venue.

Usage
-----
# sim mode (default)
python spoof.py --mode sim

# live dry‑run (orders are logged, not sent)
python spoof.py --mode live --symbol BTC/USDT --layers 3

Environment variables (.env)
----------------------------
EX_KEY, EX_SECRET : API credentials (only used in --mode live)
EX_PAPER          : "true"  # Forces dry‑run even in live mode
LOG_LEVEL         : INFO | DEBUG | WARNING
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import logging
import os
import signal
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Literal, Optional

###############################################################################
# Logging
###############################################################################
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
log = logging.getLogger("spoof-sim")

###############################################################################
# Common data structures
###############################################################################
class Side(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class Order:
    id: str
    side: Side
    price: float
    size: float
    filled: float = 0.0
    status: Literal["open", "filled", "cancelled"] = "open"
    ts: float = field(default_factory=time.time)


###############################################################################
# Exchange interface (simple home‑grown)
###############################################################################
class Exchange:
    """
    Minimal async interface.  Implementations:
    1. SimExchange – in‑memory book.
    2. LiveExchange – wraps an external SDK (ccxt / vendor) but defaults to
       *paper* mode for safety.  Only skeleton is provided; fill with your own
       venue calls if needed.
    """

    async def connect(self) -> None: ...

    async def get_top(self, symbol: str) -> Dict[str, float]: ...

    async def place_limit(
        self, symbol: str, side: Side, price: float, size: float, cid: str
    ) -> str: ...

    async def cancel(self, order_id: str) -> None: ...


###############################################################################
# 1) Simulation exchange
###############################################################################
class SimExchange(Exchange):
    def __init__(self) -> None:
        self.book: Dict[Side, Deque[Order]] = {
            Side.BUY: deque(),
            Side.SELL: deque(),
        }
        self.trades: List[Dict] = []

    async def connect(self) -> None:
        log.info("SimExchange ready.")

    async def get_top(self, _symbol: str) -> Dict[str, float]:
        bid = self.book[Side.BUY][0].price if self.book[Side.BUY] else 49_999.5
        ask = self.book[Side.SELL][0].price if self.book[Side.SELL] else 50_000.5
        return {"bid": bid, "ask": ask}

    async def place_limit(
        self, symbol: str, side: Side, price: float, size: float, cid: str
    ) -> str:
        order = Order(id=cid, side=side, price=price, size=size)
        self._insert(order)
        self._match()
        return order.id

    async def cancel(self, order_id: str) -> None:
        for q in self.book.values():
            for o in list(q):
                if o.id == order_id and o.status == "open":
                    o.status = "cancelled"
                    q.remove(o)
                    return

    # ---------- internal ----------
    def _insert(self, order: Order) -> None:
        q = self.book[order.side]
        cmp = (lambda p1, p2: p1 > p2) if order.side == Side.BUY else (lambda p1, p2: p1 < p2)
        idx = 0
        while idx < len(q) and cmp(q[idx].price, order.price):
            idx += 1
        q.insert(idx, order)

    def _match(self) -> None:
        while self.book[Side.BUY] and self.book[Side.SELL]:
            buy = self.book[Side.BUY][0]
            sell = self.book[Side.SELL][0]
            if buy.price < sell.price:
                break
            qty = min(buy.size - buy.filled, sell.size - sell.filled)
            px = (buy.price + sell.price) / 2
            self.trades.append({"price": px, "size": qty, "ts": time.time()})
            buy.filled += qty
            sell.filled += qty
            if buy.filled >= buy.size:
                buy.status = "filled"
                self.book[Side.BUY].popleft()
            if sell.filled >= sell.size:
                sell.status = "filled"
                self.book[Side.SELL].popleft()


###############################################################################
# 2) Live exchange *stub* – defaults to DRY‑RUN (paper)
###############################################################################
class LiveExchange(Exchange):
    def __init__(self, api_key: str, api_secret: str, paper: bool = True) -> None:
        self.key = api_key
        self.secret = api_secret
        self.paper = paper

    async def connect(self) -> None:
        if self.paper:
            log.info("LiveExchange running in DRY‑RUN mode – no real orders sent.")
        else:
            raise RuntimeError(
                "Live trading disabled in this stub. Enable paper mode or "
                "implement real API calls at your own risk."
            )

    async def get_top(self, symbol: str) -> Dict[str, float]:
        # Replace with vendor SDK / REST call
        raise NotImplementedError("Fill with venue top‑of‑book request")

    async def place_limit(
        self, symbol: str, side: Side, price: float, size: float, cid: str
    ) -> str:
        if self.paper:
            log.debug(f"[DRY‑RUN] place {side} {size}@{price} cid={cid}")
            return cid
        raise RuntimeError("Live order placement not implemented")

    async def cancel(self, order_id: str) -> None:
        if self.paper:
            log.debug(f"[DRY‑RUN] cancel {order_id}")
            return
        raise RuntimeError("Live cancel not implemented")


###############################################################################
# Spoofing Scenario
###############################################################################
async def spoof_cycle(
    ex: Exchange,
    symbol: str,
    layers: int,
    layer_size: float,
    price_offset: float,
    hold: float,
    exec_delay: float,
) -> None:
    top = await ex.get_top(symbol)
    bid, ask = top["bid"], top["ask"]
    log.info("Top: bid %.2f | ask %.2f", bid, ask)

    spoof_ids: List[str] = []
    # 1) bulk spoof bids
    for i in range(layers):
        px = bid - price_offset * (i + 1)
        cid = f"sp_bid_{uuid.uuid4().hex[:8]}"
        await ex.place_limit(symbol, Side.BUY, px, layer_size, cid)
        spoof_ids.append(cid)

    await asyncio.sleep(exec_delay)

    # 2) Place “real” small sell
    real_cid = f"real_{uuid.uuid4().hex[:8]}"
    await ex.place_limit(symbol, Side.SELL, bid, 0.01, real_cid)

    # 3) hold then cancel spoof
    await asyncio.sleep(hold)
    await asyncio.gather(*(ex.cancel(oid) for oid in spoof_ids))
    log.info("Cycle complete.")


###############################################################################
# Runner helpers
###############################################################################
@asynccontextmanager
async def cancellation_scope():
    loop = asyncio.get_running_loop()
    cancel = asyncio.Event()

    def _handler(sig):
        log.info("Signal %s received.  Shutting down …", sig.name)
        cancel.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, _handler, s)

    try:
        yield cancel
    finally:
        loop.remove_signal_handler(signal.SIGINT)
        loop.remove_signal_handler(signal.SIGTERM)


async def run_strategy(args):
    if args.mode == "sim":
        ex: Exchange = SimExchange()
    else:
        ex = LiveExchange(
            os.getenv("EX_KEY", ""),
            os.getenv("EX_SECRET", ""),
            paper=os.getenv("EX_PAPER", "true").lower() == "true",
        )

    await ex.connect()

    async with cancellation_scope() as cancel_flag:
        while not cancel_flag.is_set():
            try:
                await spoof_cycle(
                    ex,
                    symbol=args.symbol,
                    layers=args.layers,
                    layer_size=args.layer_size,
                    price_offset=args.offset,
                    hold=args.hold,
                    exec_delay=args.delay,
                )
            except Exception as e:
                log.exception("Cycle error: %s", e)
                await asyncio.sleep(5.0)
            await asyncio.sleep(args.pause)


###############################################################################
# CLI
###############################################################################
def parse_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Spoof‑sim test harness")
    p.add_argument("--mode", choices=["sim", "live"], default="sim")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--layers", type=int, default=3)
    p.add_argument("--layer-size", type=float, default=5.0)
    p.add_argument("--offset", type=float, default=0.5)
    p.add_argument("--hold", type=float, default=0.2)
    p.add_argument("--delay", type=float, default=0.05)
    p.add_argument("--pause", type=float, default=2.0, help="pause between cycles")
    return p.parse_args()


###############################################################################
# Entry‑point
###############################################################################
def main() -> None:
    args = parse_cli()
    try:
        asyncio.run(run_strategy(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()