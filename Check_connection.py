import sys
import os

# Use the pure-Python RTDE library bundled with the PolyScopeX SDK (no compilation needed)
SDK_RTDE_PATH = os.path.join(
    os.path.dirname(__file__),
    "polyscopex-sdk-0.20.49", "polyscopex-1", "samples", "rtde-sample",
    "rtde-communication-backend", "RTDE_Python_Client_Library"
)
sys.path.insert(0, SDK_RTDE_PATH)

import rtde.rtde as rtde
import rtde.rtde_config as rtde_config

ROBOT_HOST = "127.0.0.1"
ROBOT_PORT = 30004

print(f"Connecting to URSim PolyScopeX at {ROBOT_HOST}:{ROBOT_PORT} ...")
try:
    con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
    con.connect()
    version = con.get_controller_version()
    print(f"Success! Connected to URSim PolyScopeX.")
    print(f"Controller version: {version}")

    # Request actual joint positions (output recipe)
    con.send_output_setup(["actual_q"], ["VECTOR6D"], frequency=10)
    con.send_start()

    state = con.receive()
    if state:
        print(f"Actual Joint Angles (rad): {state.actual_q}")
    else:
        print("Connected but could not receive state data yet.")

    con.send_pause()
    con.disconnect()
except Exception as e:
    print(f"Connection failed: {e}")
    print("Make sure the URSim container is running:  docker ps")
    raise