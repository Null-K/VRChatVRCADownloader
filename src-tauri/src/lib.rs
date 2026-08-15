use std::sync::Mutex;

mod api;
mod download;

use api::AuthState;
use download::DownloadManager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
