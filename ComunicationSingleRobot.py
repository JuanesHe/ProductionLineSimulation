import socket
import time
import logging
import asyncio

# --- CONFIGURATION ---
# Bind to all interfaces so the URSim Docker container can connect back to this server.
# From URScript on the simulator, use host.docker.internal as the target IP.
HOST = '0.0.0.0'
PORT = 50002  # Change to 50000 for legacy single-robot mode, 50001+ for multi-cell
LOG_FILENAME = "robot_logs4.txt"
ITERATIONS = 1       # Number of times to repeat the task
PERCEPTION_TIME = 1.5  # Seconds the robot waits to simulate perception (camera/sensor processing)
MACHINE_TIME = 2.0     # Seconds the robot waits to simulate machine operation
ROBOT_IP = '127.0.0.1' # Robot/simulator IP for the speed command (realtime interface port 30003)
ROBOT_SPEED = 0.5      # Speed override: 0.0 (stopped) to 1.0 (full speed)
# ---------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")


def set_robot_speed(speed: float):
    """Send a speed override to the robot via the realtime client interface (port 30003)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((ROBOT_IP, 31003))
            s.sendall(f"set speed {speed}\n".encode('utf-8'))
        logging.info(f"Robot speed set to {speed}")
    except Exception as e:
        logging.warning(f"Could not set robot speed: {e}")


async def log_session(conn, iteration_num, total_iterations):
    """
    Handles a single session (iteration) with the robot.
    """
    loop = asyncio.get_running_loop()
    process_start_times = {}
    
    # Send 'init' then the two timing parameters to the robot
    try:
        logging.info(f"Sending 'init' for iteration {iteration_num}/{total_iterations}")
        logging.info(f"  PerceptionTime={PERCEPTION_TIME}s  MachineTime={MACHINE_TIME}s")
        await loop.sock_sendall(conn, f"init\n".encode('utf-8'))
        await loop.sock_sendall(conn, f"{PERCEPTION_TIME}\n".encode('utf-8'))
        await loop.sock_sendall(conn, f"{MACHINE_TIME}\n".encode('utf-8'))
    except Exception as e:
        logging.error(f"Failed to send init: {e}")
        return

    # Log header for this iteration
    with open(LOG_FILENAME, "a") as log_file:
        log_file.write(f"\n--- STARTING ITERATION {iteration_num} of {total_iterations} ---\n")

    try:
        while True:
            data = await loop.sock_recv(conn, 1024)
            if not data:
                break

            message = data.decode('utf-8').strip()
            timestamp = time.time()
            
            if not message:
                continue

            logging.info(f"[Iter {iteration_num}] Received: {message}")

            # 1. Log the raw message
            with open(LOG_FILENAME, "a") as log_file:
                log_file.write(f"{time.ctime(timestamp)}: {message}\n")

            # 2. Handle process timing logic
            if message.endswith("_started"):
                process_name = message.replace("_started", "")
                process_start_times[process_name] = timestamp

            elif message.endswith("_finished"):
                process_name = message.replace("_finished", "")
                start_time = process_start_times.pop(process_name, None)
                if start_time:
                    duration = timestamp - start_time
                    log_entry = f"Process '{process_name}' duration: {duration:.2f}s\n"
                    with open(LOG_FILENAME, "a") as log_file:
                        log_file.write(log_entry)

            # 3. Control messages
            elif message.lower() == "finish":
                logging.info(f"Iteration {iteration_num} finished.")
                break

    except Exception as e:
        logging.error(f"Error during iteration {iteration_num}: {e}")
    finally:
        with open(LOG_FILENAME, "a") as log_file:
            log_file.write(f"--- END ITERATION {iteration_num} ---\n")

async def main():
    # Set robot speed before starting iterations
    set_robot_speed(ROBOT_SPEED)

    # Create the socket server ONCE
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(1)
        server_socket.setblocking(False)

        logging.info(f"Server listening on {HOST}:{PORT}")
        logging.info(f"Preparing to run {ITERATIONS} iterations.")

        loop = asyncio.get_running_loop()

        # --- REPEAT N TIMES ---
        for i in range(1, ITERATIONS + 1):
            logging.info(f"Waiting for robot connection... (Iteration {i}/{ITERATIONS})")
            
            # Wait for a new connection for this iteration
            conn, addr = await loop.sock_accept(server_socket)
            conn.setblocking(False)
            logging.info(f"Connected to {addr}")

            # Wait briefly for connection stability
            await asyncio.sleep(0.5)

            # Handle the specific session
            await log_session(conn, i, ITERATIONS)

            # Close connection to prepare for the next one
            conn.close()
            logging.info(f"Connection closed. {ITERATIONS - i} iterations remaining.")
            
            # Optional: Short pause between iterations
            await asyncio.sleep(1)

        logging.info("All iterations completed. Exiting.")

if __name__ == "__main__":
    asyncio.run(main())