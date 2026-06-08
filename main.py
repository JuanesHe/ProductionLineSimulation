"""
Production Floor Simulation - Entry Point
==========================================
Edit the FLOOR_CONFIG section below to define your cell layout.
Then run:
    C:/Users/jehm/Documents/Simulation/.venv/Scripts/python.exe main.py

Make sure all Docker containers are running first:
    docker compose up -d
"""

import asyncio
import logging
from floor_config import CellConfig, TransportLink, FloorConfig
from floor import FloorSimulation

# ── LOGGING ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ── FLOOR CONFIG ───────────────────────────────────────────────────────────────
# Each CellConfig maps to one Docker container.
# Ports are auto-derived from the cell id:
#   Web UI      → http://localhost:{8080 + id}
#   Speed cmd   → 127.0.0.1:{30003 + id*1000}
#   RTDE        → 127.0.0.1:{30004 + id*1000}
#   Socket srv  → 0.0.0.0:{50001 + id}   (robot connects back here)
#
# URScript for each cell must connect to:
#   socket_open("host.docker.internal", {50001 + id}, "socketMT")

FLOOR_CONFIG = FloorConfig(
    iterations=3,       # Total input batches introduced into the system
    t_feeding=5.0,      # Seconds between new batches fed into entry cells
    t_output=2.0,       # Seconds for packing station to clear each output batch
    cells=[
        CellConfig(
            id=0,
            speed=0.5,
            perception_time=1.5,
            machine_time=2.0,
            batch_input_size=2,    # receives 12 parts per cycle
            batch_output_size=2,   # outputs 12 processed parts
        ),
        CellConfig(
            id=1,
            speed=0.8,
            perception_time=0.5,
            machine_time=3.0,
            batch_input_size=2,    # receives 12 parts from cell_0
            batch_output_size=2,   # outputs 12 finished parts for packing
        ),
    ],
    links=[
        # cell_0 output → 2.5s transport → cell_1 input (buffer holds max 2 waiting batches)
        TransportLink(from_id=0, to_id=1, transport_time=2.5, buffer_size=4),
    ],
)

# ── RUN ────────────────────────────────────────────────────────────────────────
async def main():
    print("\n" + "="*60)
    print("  Production Floor Simulation")
    print("="*60)
    for cell in FLOOR_CONFIG.cells:
        print(
            f"  Cell {cell.id}: speed={cell.speed}  "
            f"perception={cell.perception_time}s  machine={cell.machine_time}s  "
            f"batch {cell.batch_input_size}\u2192{cell.batch_output_size} parts  "
            f"socket_port={cell.socket_port}"
        )
    for link in FLOOR_CONFIG.links:
        buf = f"buffer={link.buffer_size}" if link.buffer_size else "buffer=unlimited"
        print(f"  Link: cell_{link.from_id} -> cell_{link.to_id}  transport={link.transport_time}s  {buf}")
    print(f"  Input batches (iterations): {FLOOR_CONFIG.iterations}")
    print(f"  Feeder interval (t_feeding): {FLOOR_CONFIG.t_feeding}s")
    print(f"  Packing delay  (t_output):   {FLOOR_CONFIG.t_output}s")
    print("="*60 + "\n")

    floor = FloorSimulation(FLOOR_CONFIG)
    results = await floor.run()

    print("\n" + "="*60)
    print("  RESULTS")
    print("="*60)
    for batch in results:
        path = " → ".join(f"cell_{h['cell_id']}({h['output_quantity']}pcs)" for h in batch.history)
        print(f"  Batch {batch.id:>2} | {path}")
        for entry in batch.history:
            dur_str = "  ".join(f"{k}={v:.2f}s" for k, v in entry['durations'].items())
            print(f"           cell_{entry['cell_id']}: {dur_str}")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSimulation stopped by user.")
    finally:
        # Force-release all ports by killing any remaining tasks
        import sys
        sys.exit(0)
