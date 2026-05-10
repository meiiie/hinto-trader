// Hinto - Tauri backend bridge
// Cross-platform: Desktop + Mobile
// The desktop shell connects to the configured Hinto API.

use tauri::Emitter;
#[cfg(desktop)]
use tauri::Manager;
use std::sync::Mutex;

// Track if startup is complete
struct StartupState(Mutex<bool>);

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

// Desktop-only: Close splash and show main window
#[cfg(desktop)]
#[tauri::command]
fn close_splash(window: tauri::Window, state: tauri::State<StartupState>) {
    *state.0.lock().unwrap() = true;

    if let Some(splash) = window.get_webview_window("splashscreen") {
        let _ = splash.close();
    }
    if let Some(main) = window.get_webview_window("main") {
        let _ = main.set_skip_taskbar(false);
        let _ = main.show();
        let _ = main.set_focus();
    }
}

// Mobile version: Just update state
#[cfg(mobile)]
#[tauri::command]
fn close_splash(_window: tauri::Window, state: tauri::State<StartupState>) {
    *state.0.lock().unwrap() = true;
}

// Desktop-only: Routing with window management
#[cfg(desktop)]
#[tauri::command]
fn start_routing(app_handle: tauri::AppHandle, state: tauri::State<StartupState>) {
    println!("[STARTUP] Splash ready, routing to Main App (EC2 backend)");

    *state.0.lock().unwrap() = true;

    if let Some(splash) = app_handle.get_webview_window("splashscreen") {
        let _ = splash.close();
    }
    if let Some(main) = app_handle.get_webview_window("main") {
        let _ = main.set_skip_taskbar(false);
        let _ = main.show();
        let _ = main.set_focus();
    }
}

// Mobile version: Just update state
#[cfg(mobile)]
#[tauri::command]
fn start_routing(_app_handle: tauri::AppHandle, state: tauri::State<StartupState>) {
    println!("[STARTUP] Splash ready, routing to Main App (EC2 backend)");
    *state.0.lock().unwrap() = true;
}

// Quit application command
#[tauri::command]
fn quit_app(app_handle: tauri::AppHandle) {
    app_handle.exit(0);
}

// Desktop-specific setup
#[cfg(desktop)]
fn setup_desktop(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    use tauri::{
        menu::{Menu, MenuItem},
        tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    };

    // Hide main window initially
    if let Some(main_window) = app.get_webview_window("main") {
        let _ = main_window.hide();
        let _ = main_window.set_skip_taskbar(true);
    }

    // Create system tray
    let quit_i = MenuItem::with_id(app, "quit", "Quit Hinto", true, None::<&str>)?;
    let show_i = MenuItem::with_id(app, "show", "Show Dashboard", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

    let _tray = TrayIconBuilder::with_id("tray")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "quit" => {
                println!("User requested quit from tray");
                app.exit(0);
            }
            "show" => {
                let state = app.state::<StartupState>();
                if *state.0.lock().unwrap() {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| match event {
            TrayIconEvent::Click { button: MouseButton::Left, .. } => {
                let app = tray.app_handle();
                let state = app.state::<StartupState>();
                if *state.0.lock().unwrap() {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
            _ => {}
        })
        .icon(app.default_window_icon().unwrap().clone())
        .build(app)?;

    Ok(())
}

// Desktop-specific window event handler
#[cfg(desktop)]
fn handle_window_event(window: &tauri::Window, event: &tauri::WindowEvent) {
    use tauri::WindowEvent;

    if let WindowEvent::CloseRequested { api, .. } = event {
        if window.label() == "main" {
            api.prevent_close();
            let _ = window.hide();
        }
    }
}

// Mobile-specific window event handler (no-op)
#[cfg(mobile)]
fn handle_window_event(_window: &tauri::Window, _event: &tauri::WindowEvent) {
    // Mobile doesn't need special window handling
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(StartupState(Mutex::new(false)));

    // Add window-state plugin only on desktop
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_window_state::Builder::default().build());

    builder
        .setup(|app| {
            // Desktop-specific setup
            #[cfg(desktop)]
            setup_desktop(app)?;

            // Send startup events
            let _ = app.emit("startup_progress", serde_json::json!({
                "stage": "init",
                "progress": 20,
                "message": "Khởi động ứng dụng..."
            }));

            let _ = app.emit("startup_progress", serde_json::json!({
                "stage": "connecting",
                "progress": 60,
                "message": "Kết nối tới server..."
            }));

            let _ = app.emit("startup_complete", serde_json::json!({
                "has_config": true,
                "progress": 100,
                "message": "Đã sẵn sàng!"
            }));

            println!("[STARTUP] Complete. EC2 Edition - no local backend.");

            Ok(())
        })
        .on_window_event(|window, event| {
            handle_window_event(window, event);
        })
        .invoke_handler(tauri::generate_handler![greet, close_splash, start_routing, quit_app])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
