from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class Batch:
    """
    A batch of parts moving through the production floor.
    Each cell receives a batch, processes it, and outputs a (possibly
    differently-sized) batch to the next stage.
    """
    id: int                             # Unique batch identifier
    quantity: int                       # Number of parts in this batch
    origin_cell: int                    # Cell id that created / first processed it
    created_at: float = field(default_factory=time.time)
    history: List[dict] = field(default_factory=list)  # one entry per cell visited

    def record(self, cell_id: int, durations: dict, output_quantity: int):
        """Append a processing record after a cell finishes this batch."""
        self.history.append({
            "cell_id": cell_id,
            "input_quantity": self.quantity,
            "output_quantity": output_quantity,
            "durations": durations,
            "timestamp": time.time(),
        })
        self.quantity = output_quantity  # update quantity as it leaves the cell


@dataclass
class CellConfig:
    """Configuration for a single robot cell."""
    id: int                         # Unique cell index (0-based)
    speed: float = 1.0              # Robot speed override (0.0 to 1.0)
    perception_time: float = 1.5    # Seconds to simulate perception/sensing
    machine_time: float = 2.0       # Seconds to simulate machine operation
    batch_input_size: int = 12      # Number of parts the cell expects per cycle
    batch_output_size: int = 12     # Number of parts the cell produces per cycle

    # The cell WON'T start a new cycle until a full batch_input_size is available.
    # If the upstream cell produces smaller batches they will accumulate in the
    # input_queue until enough parts arrive (handled by FloorSimulation).

    robot_ip: str = "127.0.0.1"

    @property
    def web_port(self) -> int:
        return 8080 + self.id

    @property
    def speed_port(self) -> int:
        return 30003 + self.id * 1000

    @property
    def rtde_port(self) -> int:
        return 30004 + self.id * 1000

    @property
    def dashboard_port(self) -> int:
        return 29999 + self.id

    @property
    def socket_port(self) -> int:
        """Port this cell's Python server listens on (robot connects back here)."""
        return 50001 + self.id

    @property
    def log_filename(self) -> str:
        return f"robot_logs_cell_{self.id}.txt"

    @property
    def container_name(self) -> str:
        return f"ursim-cell-{self.id}"


@dataclass
class TransportLink:
    """A conveyor connection between two cells."""
    from_id: int                # Source cell id
    to_id: int                  # Destination cell id
    transport_time: float       # Seconds to move a batch from source to destination
    buffer_size: int = 0        # Max batches the buffer between cells can hold.
                                # 0 = unbounded (no bottleneck).
                                # When full, the upstream conveyor blocks until
                                # the downstream cell consumes a batch.


@dataclass
class FloorConfig:
    """Complete production floor layout."""
    cells: List[CellConfig]
    links: List[TransportLink]
    iterations: int = 5         # Total input batches introduced into the system (fed by the Feeder)
    t_feeding: float = 5.0      # Seconds between each new batch fed into entry cells
    t_output: float = 2.0       # Seconds to remove a finished batch from exit cells (packing delay)

    def get_cell(self, cell_id: int) -> CellConfig:
        for c in self.cells:
            if c.id == cell_id:
                return c
        raise ValueError(f"No cell with id={cell_id}")
