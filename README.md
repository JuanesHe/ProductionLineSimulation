# UR Robot Production Floor Simulation

A Python simulation of modular production cells, each controlled by a Universal Robots arm running inside Docker. Cells are connected by configurable conveyors with transport delays and optional buffers, modelling real production floor bottlenecks.

## Architecture

```
[Feeder] ──t_feeding──► Cell 0 ──conveyor──► Cell 1 ──t_output──► [Packer]
                        (UR robot)  buffer    (UR robot)
```

- Each **cell** is a UR robot simulator running in its own Docker container
- The robot processes **one part at a time** until a full batch is complete
- Batches move between cells via configurable conveyors with transport delays
- A **Feeder** automatically supplies entry cells; a **Packer** clears exit cells
- All events and process durations are logged per cell

## Requirements

- Python 3.10+
- Docker Desktop (Windows/Mac/Linux)
- UR PolyScopeX simulator image (see below)

## Getting the UR Simulator Image

The UR simulator is **not included** in this repository due to licensing restrictions.

1. Register at the [Universal Robots Developer Portal](https://www.universal-robots.com/developer/)
2. Download the **PolyScopeX SDK** (`web-simulator-external-*.zip`) from the portal
3. Pull the Docker image:

```bash
docker pull universalrobots/ursim_polyscopex:0.18.96
```

> The image is publicly available on Docker Hub. No login required to pull it.

## Setup

### 1. Install Python dependencies

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install ur_rtde           # optional, only needed for Check_connection.py
```

The main simulation uses only the Python standard library — no extra packages needed.

### 2. Start the robot containers

```bash
docker compose up -d
```

This starts two robot cells:
| Cell | Web UI | Socket port | Speed port |
|------|--------|-------------|------------|
| 0    | http://localhost:8080 | 50001 | 30003 |
| 1    | http://localhost:8081 | 50002 | 31003 |

Wait ~60 seconds for all inner services to start, then verify:
```bash
docker exec ursim-cell-0 docker ps
```
You should see `root-urcontrol-primary-1` listed as healthy.

### 3. Load the URScript on each robot

A ready-to-use robot program is included in this repository: **`mt1_0.urpx`**.

1. Open the robot's web UI (`http://localhost:8080` for cell 0, `http://localhost:8081` for cell 1)
2. Go to **Programs** → **Upload** and load `mt1_0.urpx`
3. Open the program and find the **Init Communication** node
4. **Change the port number** to match the cell:
   - Cell 0 → `50001`
   - Cell 1 → `50002`
   - Cell N → `50001 + N`
5. Save and press **Play**

The relevant line in the URScript looks like this — only the port number needs to change:

```urscript
while (socket_open("host.docker.internal", 50001, "socketMT")) == False:
end
```

If you prefer to write the script from scratch:

**Cell 0 — port 50001:**
```urscript
# Connect to Python simulation server
while (socket_open("host.docker.internal", 50001, "socketMT")) == False:
end

# Wait for init signal
line = 0
while line == 0:
  line1 = socket_read_line("socketMT")
  if line1 == "init":
    line = 1
  end
end

# Receive timing parameters
PerceptionTime = to_num(socket_read_line("socketMT", timeout=5))
MachineTime    = to_num(socket_read_line("socketMT", timeout=5))

# --- Your robot task here ---
socket_send_string("YourTask_started", "socketMT")
sleep(PerceptionTime)
# ... robot moves ...
sleep(MachineTime)
socket_send_string("YourTask_finished", "socketMT")

socket_send_string("finish", "socketMT")
socket_close("socketMT")
```

**Cell 1:** same script but change port to `50002`.

### 4. Configure the floor layout

Edit `main.py` — the `FLOOR_CONFIG` section:

```python
FLOOR_CONFIG = FloorConfig(
    iterations=3,        # Number of batches to introduce into the system
    t_feeding=5.0,       # Seconds between each new batch fed into entry cells
    t_output=2.0,        # Seconds for packing station to clear each output batch
    cells=[
        CellConfig(
            id=0,
            speed=0.5,              # Robot speed override (0.0 to 1.0)
            perception_time=1.5,    # Passed to URScript as PerceptionTime
            machine_time=2.0,       # Passed to URScript as MachineTime
            batch_input_size=12,    # Parts per incoming batch
            batch_output_size=12,   # Parts per outgoing batch
        ),
        CellConfig(id=1, speed=0.8, perception_time=0.5, machine_time=3.0,
                   batch_input_size=12, batch_output_size=12),
    ],
    links=[
        # buffer_size=0 means unlimited; buffer_size=2 means max 2 batches waiting
        TransportLink(from_id=0, to_id=1, transport_time=2.5, buffer_size=2),
    ],
)
```

### 5. Run the simulation

```bash
python main.py
```

Press **Play** on each robot in its web UI. The simulation will:
1. Feed batches into Cell 0 every `t_feeding` seconds
2. Cell 0 processes each part (one robot connection per part)
3. After the full batch is done it travels via conveyor to Cell 1
4. Cell 1 processes all parts, then the Packer clears it

### 6. View logs

Each cell writes a continuous event log:
- `robot_logs_cell_0.txt`
- `robot_logs_cell_1.txt`

Format:
```
Mon Jun  8 18:35:04 2026: [Batch 1] STARTED — 12 parts to process
Mon Jun  8 18:35:04 2026: [Batch 1 part 1/12]
Mon Jun  8 18:35:06 2026: GraspObjectTask_started
Mon Jun  8 18:35:11 2026: GraspObjectTask_finished
Process 'GraspObjectTask' duration: 5.17s
Mon Jun  8 18:35:11 2026: finish
Mon Jun  8 18:35:11 2026: [Batch 1] LEFT cell_0 -> cell_1 (transport 2.5s)
```

## Adding More Cells

1. Add a new service block in `docker-compose.yml` (copy `cell_1`, replace `31xxx` → `32xxx`, `8081` → `8082`)
2. Add a volume block for the new cell
3. Add `CellConfig(id=2, ...)` to `FLOOR_CONFIG.cells` in `main.py`
4. Add a `TransportLink(from_id=1, to_id=2, ...)` to `FLOOR_CONFIG.links`
5. Load the URScript on the new robot (port `50003`)

Port formula for cell `id`:
| Interface | Host port |
|-----------|-----------|
| Web UI    | `8080 + id` |
| Speed (30003) | `30003 + id × 1000` |
| RTDE (30004)  | `30004 + id × 1000` |
| Socket server | `50001 + id` |

## File Overview

| File | Description |
|------|-------------|
| `main.py` | Entry point — define your floor layout here |
| `floor_config.py` | `CellConfig`, `TransportLink`, `FloorConfig`, `Batch` dataclasses |
| `floor.py` | `FloorSimulation` — orchestrates cells, conveyors, feeder, packer |
| `robot_cell.py` | `RobotCell` — manages one robot container (socket server + logging) |
| `docker-compose.yml` | Starts N robot simulator containers |
| `mt1_0.urpx` | Robot program to upload to each UR simulator (change port in Init Communication node) |
| `Check_connection.py` | Quick RTDE connection test |

## Stopping

Press `Ctrl+C` in the terminal running `main.py`. To force-kill all containers:

```bash
docker compose down
```
