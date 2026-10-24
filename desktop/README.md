# Bauplan for Mac

A Tauri 2 window around the same web dashboard as `web/`.
The browser app (`cd web && npm run dev`, then http://localhost:5180) stays the primary demo path; this app is the same build in a native window.

## Setup

Needs Rust (cargo) and the web dependencies.

```sh
cd web && npm install
cd ../desktop && npm install
```

## Develop

```sh
cd desktop
npm run dev
```

`tauri dev` starts the Vite dev server of `web/` on http://localhost:5180 and opens the window on it.
Vite proxies `/api` and `/files` to the backend on http://localhost:8100, exactly as in the browser.
Stop any other `npm run dev` in `web/` first, because both want port 5180.

## Build the app

```sh
cd desktop
npm run build
```

This runs `npm run build:desktop` in `web/` (output in `web/dist-desktop`, with `VITE_API_BASE=http://localhost:8100` from `web/.env.desktop`) and bundles it into:

```
desktop/src-tauri/target/release/bundle/macos/Bauplan.app
```

Open it with `open desktop/src-tauri/target/release/bundle/macos/Bauplan.app`.

## How it reaches the backend

The release app serves the bundled dashboard on http://localhost:5180 and the dashboard calls the backend on http://localhost:8100 directly.
The backend's CORS rule already allows the origin http://localhost:5180, so no backend change is needed.
Because of that port, quit the Vite dev server before opening the release app.
Start the backend (`agent/`, port 8100) before or after the app; the dashboard reconnects on its own.
Without a backend, switch to Demo in the top bar to play the recorded story.
