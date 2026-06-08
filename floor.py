import asyncio
import logging
import time
from typing import List
from floor_config import FloorConfig, TransportLink, Batch
from robot_cell import RobotCell

logger = logging.getLogger(__name__)


class FloorSimulation:
    """
    Orchestrates N robot cells connected by transport conveyors.

    Every cell is connected to something on both ends:
      - Entry cells  → fed automatically every t_feeding seconds (Feeder)
      - Middle cells → connected via TransportLink conveyors
      - Exit cells   → output removed automatically after t_output seconds (Packer)

    The simulation runs for `iterations` batches end-to-end.
    """

    def __init__(self, config: FloorConfig):
        self.config = config
        # Pass each cell's input buffer size (from its incoming TransportLink)
        input_buffer_sizes = {link.to_id: link.buffer_size for link in config.links}
        self.cells: dict[int, RobotCell] = {
            c.id: RobotCell(c, input_buffer_size=input_buffer_sizes.get(c.id, 0))
            for c in config.cells
        }
        self._batch_counter = 0

    def _next_batch_id(self) -> int:
        self._batch_counter += 1
        return self._batch_counter

    # ------------------------------------------------------------------
    # Feeder: automatically feeds entry cells every t_feeding seconds
    # ------------------------------------------------------------------
    async def _feeder(self, cell_id: int, iterations: int):
        """
        Simulates a raw-material feeder for an entry cell.
        Waits t_feeding seconds, then delivers a new batch.
        Repeats exactly `iterations` times.
        """
        cell_cfg = self.config.get_cell(cell_id)
        cell = self.cells[cell_id]

        for i in range(iterations):
            if i > 0:
                # Wait before re-feeding (first batch delivered immediately)
                logger.info(
                    f"[Feeder → Cell {cell_id}] "
                    f"Next batch in {self.config.t_feeding}s..."
                )
                await asyncio.sleep(self.config.t_feeding)

            batch = Batch(
                id=self._next_batch_id(),
                quantity=cell_cfg.batch_input_size,
                origin_cell=cell_id,
            )
            await cell.input_queue.put(batch)
            logger.info(
                f"[Feeder -> Cell {cell_id}] "
                f"Batch {batch.id} delivered ({batch.quantity} parts)"
            )
            with open(cell_cfg.log_filename, "a") as f:
                f.write(
                    f"{time.ctime()}: [Batch {batch.id}] FED INTO cell_{cell_id} "
                    f"({batch.quantity} parts)\n"
                )

    # ------------------------------------------------------------------
    # Conveyor: moves batches between two cells with transport delay
    # ------------------------------------------------------------------
    async def _conveyor(self, link: TransportLink, iterations: int):
        """
        Moves `iterations` batches from source cell to destination cell,
        sleeping transport_time seconds to simulate conveyor delay.
        """
        source = self.cells[link.from_id]
        dest = self.cells[link.to_id]

        for _ in range(iterations):
            batch: Batch = await source.output_queue.get()
            src_cfg = self.config.get_cell(link.from_id)
            dst_cfg = self.config.get_cell(link.to_id)
            logger.info(
                f"[Conveyor {link.from_id}->{link.to_id}] "
                f"Batch {batch.id} ({batch.quantity} parts) in transit "
                f"({link.transport_time}s)"
            )
            # Log departure from source cell
            with open(src_cfg.log_filename, "a") as f:
                f.write(
                    f"{time.ctime()}: [Batch {batch.id}] LEFT cell_{link.from_id} "
                    f"-> cell_{link.to_id} (transport {link.transport_time}s)\n"
                )
            await asyncio.sleep(link.transport_time)
            # If buffer is full this blocks until the downstream cell frees a slot
            buf_info = f" [buffer {dest.input_queue.qsize()}/{link.buffer_size}]" if link.buffer_size else ""
            if link.buffer_size and dest.input_queue.full():
                logger.warning(
                    f"[Conveyor {link.from_id}->{link.to_id}] "
                    f"Buffer FULL ({link.buffer_size} batches) - upstream stalled"
                )
            await dest.input_queue.put(batch)
            source.output_queue.task_done()
            # Log arrival at destination cell
            with open(dst_cfg.log_filename, "a") as f:
                f.write(
                    f"{time.ctime()}: [Batch {batch.id}] ARRIVED at cell_{link.to_id} "
                    f"from cell_{link.from_id} ({batch.quantity} parts){buf_info}\n"
                )
            logger.info(
                f"[Conveyor {link.from_id}->{link.to_id}] "
                f"Batch {batch.id} delivered to cell {link.to_id}{buf_info}"
            )

    # ------------------------------------------------------------------
    # Packer: automatically removes finished batches from exit cells
    # ------------------------------------------------------------------
    async def _packer(self, cell_id: int, iterations: int) -> List[Batch]:
        """
        Simulates a packing/output station for an exit cell.
        Picks up finished batches and waits t_output seconds to clear them.
        """
        cell = self.cells[cell_id]
        results = []

        for _ in range(iterations):
            batch: Batch = await cell.output_queue.get()
            cell_cfg = self.config.get_cell(cell_id)
            logger.info(
                f"[Packer <- Cell {cell_id}] "
                f"Batch {batch.id} ({batch.quantity} parts) clearing in "
                f"{self.config.t_output}s..."
            )
            with open(cell_cfg.log_filename, "a") as f:
                f.write(
                    f"{time.ctime()}: [Batch {batch.id}] TAKEN OUT of cell_{cell_id} "
                    f"-> packing ({batch.quantity} parts)\n"
                )
            await asyncio.sleep(self.config.t_output)
            cell.output_queue.task_done()
            results.append(batch)
            path = " -> ".join(f"cell_{h['cell_id']}" for h in batch.history)
            with open(cell_cfg.log_filename, "a") as f:
                f.write(
                    f"{time.ctime()}: [Batch {batch.id}] PACKED. Path: {path}\n"
                )
            logger.info(
                f"[Packer <- Cell {cell_id}] "
                f"Batch {batch.id} packed. Path: {path}"
            )

        return results

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    async def run(self) -> List[Batch]:
        """
        Starts all feeders, cells, conveyors and packers concurrently.
        Returns finished batches from all exit cells.
        """
        iterations = self.config.iterations

        destination_ids = {link.to_id for link in self.config.links}
        source_ids = {link.from_id for link in self.config.links}

        entry_cell_ids = [c.id for c in self.config.cells if c.id not in destination_ids]
        exit_cell_ids  = [c.id for c in self.config.cells if c.id not in source_ids]

        tasks = []

        # Feeders (entry cells)
        for cell_id in entry_cell_ids:
            tasks.append(self._feeder(cell_id, iterations))

        # Robot cells
        for cell in self.cells.values():
            tasks.append(cell.run(iterations))

        # Conveyors (middle links)
        for link in self.config.links:
            tasks.append(self._conveyor(link, iterations))

        # Packers (exit cells) — run separately to collect results
        packer_tasks = [self._packer(cell_id, iterations) for cell_id in exit_cell_ids]

        gathered = await asyncio.gather(*tasks, *packer_tasks, return_exceptions=True)

        # Last len(packer_tasks) items are the packer results
        all_results = []
        for item in gathered[-len(packer_tasks):]:
            if isinstance(item, list):
                all_results.extend(item)
            elif isinstance(item, Exception):
                logger.error(f"[Floor] Packer raised: {item}")

        logger.info(f"[Floor] Simulation complete. {len(all_results)} batches packed.")
        return all_results


        logger.info(f"[Floor] Simulation complete. {len(all_results)} batches finished.")
        return all_results
