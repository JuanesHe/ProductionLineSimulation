import asyncio
import socket
import time
import logging
from floor_config import CellConfig, Batch

logger = logging.getLogger(__name__)


class RobotCell:
    """
    Manages communication with a single UR robot simulator container.

    Batch lifecycle:
      - Waits on input_queue until a Batch with enough parts arrives
      - Processes the batch (robot runs one full cycle)
      - Outputs a new Batch with batch_output_size parts to output_queue
      - Will NOT start again until the next batch arrives
    """

    def __init__(self, config: CellConfig, input_buffer_size: int = 0):
        self.config = config
        # input_buffer_size > 0 limits how many batches can wait before this cell.
        # When the buffer is full the upstream conveyor blocks (backpressure).
        self.input_queue: asyncio.Queue = asyncio.Queue(maxsize=input_buffer_size)
        self.output_queue: asyncio.Queue = asyncio.Queue()
        self._server_socket: socket.socket | None = None

    # ------------------------------------------------------------------
    # Speed control
    # ------------------------------------------------------------------
    def set_speed(self):
        """Send speed override to the robot via realtime client interface (port 30003)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.config.robot_ip, self.config.speed_port))
                s.sendall(f"set speed {self.config.speed}\n".encode('utf-8'))
            logger.info(f"[Cell {self.config.id}] Speed set to {self.config.speed}")
        except Exception as e:
            logger.warning(f"[Cell {self.config.id}] Could not set speed: {e}")

    # ------------------------------------------------------------------
    # Single session (one batch / one robot iteration)
    # ------------------------------------------------------------------
    async def _run_session(self, conn: socket.socket, batch: Batch, part_num: int) -> dict:
        """
        Handles one robot cycle for a single part within a batch.
        Returns the durations dict for this part.
        """
        loop = asyncio.get_running_loop()
        process_start_times: dict = {}
        durations: dict = {}

        # --- Send init + timing parameters + batch size ---
        try:
            logger.info(
                f"[Cell {self.config.id}] Processing batch {batch.id} "
                f"({batch.quantity} parts in → {self.config.batch_output_size} out)"
            )
            await loop.sock_sendall(conn, b"init\n")
            await loop.sock_sendall(conn, f"{self.config.perception_time}\n".encode())
            await loop.sock_sendall(conn, f"{self.config.machine_time}\n".encode())
        except Exception as e:
            logger.error(f"[Cell {self.config.id}] Failed to send init: {e}")
            batch.record(self.config.id, {}, batch.quantity)
            return batch

        # --- Log batch start ---
        with open(self.config.log_filename, "a") as f:
            f.write(
                f"{time.ctime()}: [Batch {batch.id}] "
                f"input={batch.quantity} parts\n"
            )


        # --- Receive messages until "finish" ---
        buffer = ""
        try:
            while True:
                data = await loop.sock_recv(conn, 1024)
                if not data:
                    break

                buffer += data.decode('utf-8')
                # Handle both socket_send_line (\n delimited) and
                # socket_send_string (no newline — sends one complete message per call)
                while True:
                    if "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                    elif buffer.strip():
                        # No newline: socket_send_string — treat whole buffer as one message
                        line = buffer
                        buffer = ""
                    else:
                        break

                    message = line.strip()
                    if not message:
                        continue

                    timestamp = time.time()
                    logger.info(f"[Cell {self.config.id}] Received: {message}")

                    # Log every raw message with timestamp
                    with open(self.config.log_filename, "a") as f:
                        f.write(f"{time.ctime(timestamp)}: {message}\n")

                    if message.endswith("_started"):
                        process_name = message[: -len("_started")]
                        process_start_times[process_name] = timestamp

                    elif message.endswith("_finished"):
                        process_name = message[: -len("_finished")]
                        start = process_start_times.pop(process_name, None)
                        if start:
                            duration = timestamp - start
                            durations[process_name] = round(duration, 2)
                            # Duration line matches robot_logs3.txt format exactly
                            with open(self.config.log_filename, "a") as f:
                                f.write(f"Process '{process_name}' duration: {duration:.2f}s\n")

                    elif message.lower() == "finish":
                        logger.info(
                            f"[Cell {self.config.id}] Batch {batch.id} "
                            f"part {part_num} done."
                        )
                        return durations

        except Exception as e:
            logger.error(f"[Cell {self.config.id}] Session error: {e}")
            return {}

        return durations

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------
    async def run(self, iterations: int):
        """
        Opens one persistent server socket.
        For each batch: processes batch.quantity parts one at a time
        (one robot connection per part). Only outputs the batch when
        all parts are done — the cell will not accept the next batch
        until the current one is fully complete.
        """
        self.set_speed()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", self.config.socket_port))
            server.listen(1)
            server.setblocking(False)

            logger.info(
                f"[Cell {self.config.id}] Listening on port {self.config.socket_port}"
            )

            loop = asyncio.get_running_loop()

            for i in range(iterations):
                # Block until a batch arrives
                logger.info(f"[Cell {self.config.id}] Waiting for batch...")
                batch: Batch = await self.input_queue.get()
                logger.info(
                    f"[Cell {self.config.id}] Batch {batch.id} received "
                    f"({batch.quantity} parts). Processing one part at a time."
                )

                with open(self.config.log_filename, "a") as f:
                    f.write(
                        f"{time.ctime()}: [Batch {batch.id}] "
                        f"STARTED — {batch.quantity} parts to process\n"
                    )

                all_durations: dict = {}

                # --- Process each part one at a time ---
                for part_num in range(1, batch.quantity + 1):
                    conn, addr = await loop.sock_accept(server)
                    conn.setblocking(False)
                    logger.info(
                        f"[Cell {self.config.id}] Robot connected for "
                        f"batch {batch.id} part {part_num}/{batch.quantity}"
                    )
                    await asyncio.sleep(0.3)
                    try:
                        part_durations = await self._run_session(conn, batch, part_num)
                        # Accumulate durations across parts
                        for k, v in part_durations.items():
                            all_durations.setdefault(k, []).append(v)
                    finally:
                        conn.close()
                    await asyncio.sleep(0.2)

                # --- Batch complete: record and output ---
                # Average durations across all parts
                avg_durations = {k: round(sum(v)/len(v), 2) for k, v in all_durations.items()}
                batch.record(self.config.id, avg_durations, self.config.batch_output_size)

                with open(self.config.log_filename, "a") as f:
                    f.write(
                        f"{time.ctime()}: [Batch {batch.id}] "
                        f"COMPLETE — {self.config.batch_output_size} parts output\n"
                    )

                logger.info(
                    f"[Cell {self.config.id}] Batch {batch.id} complete. "
                    f"All {batch.quantity} parts processed."
                )

                await self.output_queue.put(batch)
                self.input_queue.task_done()
                await asyncio.sleep(0.5)

            logger.info(f"[Cell {self.config.id}] All {iterations} batches complete.")
