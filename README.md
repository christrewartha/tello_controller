# Tello Controller

Fly a DJI/Ryze Tello from your PC with the **keyboard or an Xbox controller**, and
have it **lock on to a face**: the drone holds its position relative to you
(turning, rising/falling and moving in or out as you move) so it's obvious it
has seen you and is responding. It nods when it first locks on.

Built on [djitellopy](https://github.com/damiafuentes/DJITelloPy), OpenCV
(YuNet face detection + SFace recognition) and pygame.

## Setup

Requires [uv](https://docs.astral.sh/uv/) (it installs the right Python for you).

```sh
uv sync
```

Face models (~40 MB) are downloaded into `models/` on first run.

## Running

```sh
uv run tello --wifi          # switch to the TELLO-xxxx Wi-Fi, fly, restore Wi-Fi on exit
uv run tello                 # already connected to the drone's Wi-Fi
uv run tello --sim           # no drone: simulator with synthetic video
uv run tello --sim --webcam  # simulator using your webcam as the "drone camera"
```

With `--wifi`, you can start the app before switching the drone on. It
rescans every few seconds until a `TELLO-xxxx` network appears, then joins it.
If more than one Tello is visible it asks which one. Pass `--wifi TELLO-XXXXXX`
to wait for a specific drone.

`--sim --webcam` is the best way to try face lock-on at your desk: the HUD
sticks show exactly what commands would be sent to the drone.

Press **H** in the app for the control reference.

### Controls

| Action | Keyboard | Xbox controller |
|---|---|---|
| Forward/back, left/right | W/S, A/D | Right stick |
| Climb/descend | Up/Down | Left stick up/down |
| Yaw | Left/Right | Left stick left/right |
| Take off / land | E / Q | Menu / View |
| Toggle face lock-on | F | Y |
| Hover (cancels lock-on) | Space | B |
| Flip forward/back/left/right | I/K/J/L | Hold A + D-pad |
| Snapshot | Z | X |
| Start/stop recording | R | RB |
| Enrol the current face | N | – |
| Boost / precision | Shift / Ctrl | RT (analog) / LB |
| **Emergency motor stop** | Backspace | Click **both** sticks |
| Drone info + status LED guide | Tab | – |
| Quit (lands first) | Esc | – |

Manual input always wins: during lock-on, any stick or key you touch overrides
that axis, and the lock-on resumes when you let go.

> ⚠ Emergency stop cuts the motors immediately and the drone **will fall**.
> Use it only when hitting something is worse than dropping.

## Face lock-on

1. Take off and press **F** / **Y**. The drone hovers until it sees a face.
2. When it locks on, it captures where your face is in the frame and how big it
   is. That's the setpoint: it then keeps your face centred, at the same height
   and the same size (= same distance). The cyan crosshair on the HUD shows
   the setpoint.
3. If it loses you it coasts briefly, then hovers and keeps looking. After 8 s
   it gives up and returns to manual.

The setpoint distance is clamped to roughly 0.6 m to 1.7 m. Tune everything in
[config.py](src/tello_controller/config.py) (`LockOnConfig`).

### Recognising a specific person

With nobody enrolled, it locks on to the largest face. Once anyone is enrolled
it will **only** lock on to known people, and it re-checks who it's following
every few frames.

```sh
uv run tello-enroll --name chris     # enrol from your webcam
```

…or press **N** in the app to enrol the face currently on screen (name via
`--name`). Enrolments are stored in `data/faces/` (git-ignored).

## Status LED and battery health

The Tello doesn't report its LED state or error codes over Wi-Fi. Press
**Tab** for the official LED table (with animated blink patterns to match by eye)
next to the live telemetry that explains the common causes. **Red is never
normal:** slow blinking = low battery, fast = critically low, solid = critical error.

While flying, the app measures how fast the battery % drops. A healthy battery
drains ~7–8 %/min (about 13 minutes of flight). Fast drain, or the % suddenly
falling by 5 or more within a few seconds, usually means a worn battery. You
get a one-time warning in flight, and the details stay on the Tab screen. These
thresholds are rules of thumb, not official specs. Tune them in
[diagnostics.py](src/tello_controller/diagnostics.py).

## Recording

**R** / **RB** records to `recordings/<timestamp>/`:

- `video.mp4`: clean camera frames (no HUD)
- `frames.csv`: one row per frame with a timestamp, telemetry (height, ToF,
  attitude, velocities, battery) and the RC command sent

This is the input for the 3D mapping work below.

## Development

```sh
uv run pytest
```

The tests include headless runs of the full app against the simulator.

```
src/tello_controller/
  app.py       main loop, mode arbitration, safety, CLI
  drone.py     TelloDrone (djitellopy) and SimDrone
  inputs.py    keyboard + Xbox controller -> ControlInput
  faces.py     YuNet detector, SFace recogniser, face gallery
  lock_on.py   target tracking + PID lock-on controller
  hud.py       pygame overlay
  recorder.py  video + telemetry recording, snapshots
  network.py   optional Wi-Fi switching (Windows netsh / Linux nmcli)
  config.py    every tunable in one place
```

## Roadmap: 3D mapping (SLAM)

The Tello is a hard SLAM platform: one camera, no depth sensor, compressed
video over Wi-Fi with latency, and no published camera calibration. The plan:

1. **Offline reconstruction.** Record flights (done), then build a 3D model with
   COLMAP / Gaussian splatting. Needs a camera calibration step (checkerboard).
2. **Live monocular SLAM.** Run a dense learned SLAM system (e.g. MASt3R-SLAM) on
   the GPU, fed by the video stream. Use the ToF/height telemetry to recover
   real-world scale.
3. **Live map view + follow mode.** Show the point cloud and drone pose next to
   the video. Then use the map for a true "follow me" that can plan around
   obstacles.
