//! AnyBuild as a Mac app: a window around the same web dashboard as the browser.
//!
//! In development the window loads the Vite dev server on http://localhost:5180,
//! which proxies /api and /files to the backend. A release build serves the bundled
//! dashboard itself on http://localhost:5180 and the dashboard calls the backend at
//! http://localhost:8100 directly; the backend's CORS rule already allows that
//! origin. So the browser and the Mac app talk to the backend the same way.

use tauri::{WebviewUrl, WebviewWindowBuilder};

/// Port of the dashboard. Matches the backend's allowed CORS origin.
#[cfg(not(dev))]
const DASHBOARD_PORT: u16 = 5180;

pub fn run() {
    let builder = tauri::Builder::default();

    #[cfg(not(dev))]
    let builder = builder.plugin(tauri_plugin_localhost::Builder::new(DASHBOARD_PORT).build());

    builder
        .setup(|app| {
            #[cfg(dev)]
            let url = WebviewUrl::App("index.html".into());
            #[cfg(not(dev))]
            let url = WebviewUrl::External(
                format!("http://localhost:{DASHBOARD_PORT}")
                    .parse()
                    .expect("valid dashboard URL"),
            );

            WebviewWindowBuilder::new(app, "main", url)
                .title("AnyBuild")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1280.0, 800.0)
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running AnyBuild");
}
