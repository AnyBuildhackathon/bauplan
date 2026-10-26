# SparkBench bridge

`circuit_design` turns a build's chosen parts into a real circuit with [SparkBench](https://github.com/dennisonbertram/sparkbench): pins on an ESP32 or a Raspberry Pi Pico, a KiCad schematic, a breadboard plan, a parts list and MicroPython firmware, checked by SparkBench's design checks and run in its simulator against its acceptance tests.
SparkBench is a TypeScript app, so AnyBuild runs it headless in its own Node process instead of importing it.
This folder holds the bridge script and its one dependency, `tsx`, which runs TypeScript directly.

## Install

```bash
bash agent/scripts/setup_sparkbench.sh
```

The script needs Node.js 20 or newer and the network once.
It clones SparkBench at the pinned commit `6dd92371aeb2ae6cc5c2dbe04a1fc84a448d315a` into `~/.cache/anybuild/sparkbench/<commit>`, installs its npm packages without running their install scripts, and installs `tsx` here (`node_modules` is ignored by git).
`SPARKBENCH_DIR` puts the checkout somewhere else; the backend reads the same variable.
The checkout and its packages take about 250 MB; remove the folder to uninstall.
Without it, `circuit_design` answers that SparkBench is not installed and the run goes on.

## How a run works

1. `agent/src/pai_agent/tools/circuit.py` reads the chosen parts, picks the board from the controller, turns the parts SparkBench builds in into its feature kinds and lists what it cannot model.
2. `agent/src/pai_agent/sparkbench.py` writes the request as JSON and starts `node node_modules/tsx/dist/cli.mjs bridge.ts <request.json>` in the checkout, with no keys in its environment and a 60 s limit.
3. `bridge.ts` builds SparkBench's `DesignSpec`, wires it with `buildProject`, adds library parts by part number with `withCustomPart`, then runs `runChecks`, `deriveTests` with `runTests`, and a 5 s simulation, and writes the files the way SparkBench's `scripts/build-project.ts` does, plus `result.json`.
4. The backend copies the files flat into the session folder as `circuit-v<n>-*`, zips the KiCad project and the firmware, caches the result in `agent/runs/cache/circuits` and emits the `circuit` event (see `docs/events.md`).

The same request gives the same files: the dates come from the request, and the simulator's sensor noise from a fixed seed.

## Run it by hand

```bash
cat > /tmp/request.json <<'EOF'
{"name": "Desk lamp", "board": "esp32", "date": "2026-10-26", "out": "/tmp/circuit",
 "parts": [{"key": "ring", "label": "Lamp ring", "text": "WS2812B LED ring 12 LEDs", "qty": 1, "feature": {"kind": "neopixel", "props": {"pixels": 12}}},
           {"key": "driver", "label": "Servo driver", "text": "PCA9685 16-channel servo driver", "qty": 1}]}
EOF
SB="${SPARKBENCH_DIR:-$HOME/.cache/anybuild/sparkbench/6dd92371aeb2ae6cc5c2dbe04a1fc84a448d315a}"
(cd "$SB" && node "$OLDPWD/agent/sparkbench/node_modules/tsx/dist/cli.mjs" "$OLDPWD/agent/sparkbench/bridge.ts" /tmp/request.json)
```

Run it from the repository root; the files and `result.json` land in `/tmp/circuit`.

## Limits

- Boards: the ESP32 DevKit V1 and the Raspberry Pi Pico; the ESP32-S3, camera boards, Arduinos, Raspberry Pis and flight controllers are refused with the reason.
- Firmware: SparkBench writes `main.py` for its built-in parts; a library part (an MG996R, a PCA9685) gets its driver file but no code in `main.py`.
- Servos behind a PCA9685 stay out of the circuit with their channel in `gaps`: SparkBench's PCA9685 has no channel pins.
- SparkBench powers the board over USB; batteries, regulators and power switches are listed in `gaps`.
