use std::sync::Mutex;

mod api;
mod download;
mod logger;

use api::AuthState;
use download::DownloadManager;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            logger::init(app.path().app_data_dir().ok());
            let pkg = app.package_info();
            logger::info(&format!(
                "===== 应用启动 v{} ({} {}) =====",
                pkg.version,
                std::env::consts::OS,
                std::env::consts::ARCH
            ));

            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                api::cleanup_cache(&handle).await;
            });
            Ok(())
        })
        .manage(Mutex::new(AuthState::default()))
        .manage(DownloadManager::new())
        .invoke_handler(tauri::generate_handler![
            api::cmd_login,
            api::cmd_verify_2fa,
            api::cmd_fetch_avatars,
            api::cmd_fetch_image_bytes,
            api::cmd_save_session,
            api::cmd_restore_session,
            api::cmd_clear_session,
            api::cmd_save_config,
            api::cmd_load_config,
            download::cmd_start_download,
            download::cmd_cancel_task,
            download::cmd_cancel_all,
            download::cmd_retry_failed,
            download::cmd_clear_finished,
            download::cmd_get_tasks,
        ])
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|_app, event| {
            if let tauri::RunEvent::Exit = event {
                logger::info("===== 应用退出 =====");
            }
        });
}
