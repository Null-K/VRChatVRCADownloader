use anyhow::Result;
use futures_util::StreamExt;
use reqwest::{header, Client};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tauri::Emitter;
use tokio::{fs, io::AsyncWriteExt};

use crate::api::AuthState;

const USER_AGENT: &str = "VRChatVRCADownloader/2.0";
const STALL_SECS: u64 = 25;

// ── 任务数据 ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum TaskStatus {
    Queued,
    Running,
    Success,
    Failed,
    Timeout,
    Cancelled,
}

#[derive(Debug, Clone, Serialize)]
pub struct TaskSnapshot {
    pub id: u32,
    pub name: String,
    pub status: TaskStatus,
    pub downloaded: u64,
    pub total: u64,
    pub speed: f64,
    pub error: String,
    pub save_path: String,
}

#[derive(Debug)]
pub struct DownloadTask {
    pub id: u32,
    pub name: String,
    pub url: String,
    pub save_path: String,
    pub status: TaskStatus,
    pub downloaded: u64,
    pub total: u64,
    pub speed: f64,
    pub error: String,
    pub cancel_tx: Option<tokio::sync::oneshot::Sender<()>>,
}

impl DownloadTask {
    pub fn snapshot(&self) -> TaskSnapshot {
        TaskSnapshot {
            id: self.id,
            name: self.name.clone(),
            status: self.status.clone(),
            downloaded: self.downloaded,
            total: self.total,
            speed: self.speed,
            error: self.error.clone(),
            save_path: self.save_path.clone(),
        }
    }
}

// ── 下载管理器 ─────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct DownloadManager {
    pub tasks: Arc<Mutex<HashMap<u32, DownloadTask>>>,
    pub next_id: Arc<Mutex<u32>>,
}

impl DownloadManager {
    pub fn new() -> Self {
        Self {
            tasks: Arc::new(Mutex::new(HashMap::new())),
            next_id: Arc::new(Mutex::new(1)),
        }
    }
}

fn resolve_path(path: &str) -> String {
    if !std::path::Path::new(path).exists() {
        return path.to_string();
    }
    let p = std::path::Path::new(path);
    let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("file");
    let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("vrca");
    let parent = p.parent().map(|p| p.to_str().unwrap_or("")).unwrap_or("");
    let stamp = chrono::Local::now().format("%Y%m%d_%H%M%S");
    let mut candidate = format!("{}/{}_{}.{}", parent, stem, stamp, ext);
    let mut idx = 1;
    while std::path::Path::new(&candidate).exists() {
        candidate = format!("{}/{}_{}_{}.{}", parent, stem, stamp, idx, ext);
        idx += 1;
    }
    candidate
}

#[allow(dead_code)]
fn format_bytes(n: u64) -> String {
    if n < 1024 { return format!("{} B", n); }
    if n < 1024 * 1024 { return format!("{:.1} KB", n as f64 / 1024.0); }
    if n < 1024 * 1024 * 1024 { return format!("{:.1} MB", n as f64 / 1024.0 / 1024.0); }
    format!("{:.2} GB", n as f64 / 1024.0 / 1024.0 / 1024.0)
}

// ── Tauri 命令 ────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn cmd_start_download(
    name: String,
    url: String,
    save_path: String,
    dm: tauri::State<'_, DownloadManager>,
    auth_state: tauri::State<'_, Mutex<AuthState>>,
    window: tauri::Window,
) -> Result<u32, String> {
    let (auth_cookie, proxy) = {
        let s = auth_state.lock().unwrap();
        (s.auth_cookie.clone(), s.proxy.clone())
    };

    let task_id = {
        let mut nid = dm.next_id.lock().unwrap();
        let id = *nid;
        *nid += 1;
        id
    };

    let final_path = resolve_path(&save_path);
    let (cancel_tx, cancel_rx) = tokio::sync::oneshot::channel::<()>();

    {
        let mut tasks = dm.tasks.lock().unwrap();
        tasks.insert(task_id, DownloadTask {
            id: task_id,
            name: name.clone(),
            url: url.clone(),
            save_path: final_path.clone(),
            status: TaskStatus::Queued,
            downloaded: 0,
            total: 0,
            speed: 0.0,
            error: String::new(),
            cancel_tx: Some(cancel_tx),
        });
    }

    emit_task(&window, &dm, task_id);

    let dm_clone = dm.inner().clone();
    let window_clone = window.clone();
    tokio::spawn(async move {
        run_download(task_id, name, url, final_path, auth_cookie, proxy,
                     cancel_rx, dm_clone, window_clone).await;
    });

    Ok(task_id)
}

async fn run_download(
    task_id: u32,
    _name: String,
    url: String,
    save_path: String,
    auth_cookie: String,
    proxy: Option<String>,
    mut cancel_rx: tokio::sync::oneshot::Receiver<()>,
    dm: DownloadManager,
    window: tauri::Window,
) {
    {
        let mut tasks = dm.tasks.lock().unwrap();
        if let Some(t) = tasks.get_mut(&task_id) {
            t.status = TaskStatus::Running;
        }
    }
    emit_task(&window, &dm, task_id);

    let result = do_download(task_id, &url, &save_path, &auth_cookie, &proxy,
                              &mut cancel_rx, &dm, &window).await;

    let mut tasks = dm.tasks.lock().unwrap();
    if let Some(t) = tasks.get_mut(&task_id) {
        match result {
            Ok(()) => {
                t.status = TaskStatus::Success;
                t.speed = 0.0;
            }
            Err(e) if t.status == TaskStatus::Cancelled => {
                t.error = e.to_string();
            }
            Err(e) if t.status == TaskStatus::Timeout => {
                t.error = e.to_string();
            }
            Err(e) => {
                t.status = TaskStatus::Failed;
                t.error = e.to_string();
            }
        }
    }
    drop(tasks);
    emit_task(&window, &dm, task_id);
}

async fn do_download(
    task_id: u32,
    url: &str,
    save_path: &str,
    auth_cookie: &str,
    proxy: &Option<String>,
    cancel_rx: &mut tokio::sync::oneshot::Receiver<()>,
    dm: &DownloadManager,
    window: &tauri::Window,
) -> Result<(), String> {
    let mut builder = Client::builder()
        .user_agent(USER_AGENT)
        .timeout(Duration::from_secs(30));
    if let Some(p) = proxy {
        builder = builder.proxy(reqwest::Proxy::all(p).map_err(|e| e.to_string())?);
    }
    let client = builder.build().map_err(|e| e.to_string())?;

    let resp = client
        .get(url)
        .header(header::COOKIE,
            header::HeaderValue::from_str(auth_cookie).unwrap_or_else(|_| header::HeaderValue::from_static("")))
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if resp.status() == 401 {
        return Err("登录已过期，请重新登录".to_string());
    }
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }

    let total = resp.content_length().unwrap_or(0);
    {
        let mut tasks = dm.tasks.lock().unwrap();
        if let Some(t) = tasks.get_mut(&task_id) { t.total = total; }
    }

    if let Some(parent) = std::path::Path::new(save_path).parent() {
        fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
    }

    let temp_path = format!("{}.part", save_path);
    let mut file = fs::File::create(&temp_path).await.map_err(|e| e.to_string())?;
    let mut stream = resp.bytes_stream();

    let mut downloaded: u64 = 0;
    let start = Instant::now();
    let mut last_push = Instant::now();
    let mut last_progress = Instant::now();

    loop {
        tokio::select! {
            _ = &mut *cancel_rx => {
                drop(file);
                let _ = fs::remove_file(&temp_path).await;
                let mut tasks = dm.tasks.lock().unwrap();
                if let Some(t) = tasks.get_mut(&task_id) {
                    t.status = TaskStatus::Cancelled;
                    t.error = "用户手动终止".to_string();
                }
                return Ok(());
            }
            chunk = stream.next() => {
                match chunk {
                    None => break,
                    Some(Err(e)) => {
                        drop(file);
                        let _ = fs::remove_file(&temp_path).await;
                        return Err(e.to_string());
                    }
                    Some(Ok(bytes)) => {
                        if bytes.is_empty() {
                            if last_progress.elapsed().as_secs() >= STALL_SECS {
                                drop(file);
                                let _ = fs::remove_file(&temp_path).await;
                                let mut tasks = dm.tasks.lock().unwrap();
                                if let Some(t) = tasks.get_mut(&task_id) {
                                    t.status = TaskStatus::Timeout;
                                    t.error = format!("连续 {}s 无进度，已自动终止", STALL_SECS);
                                }
                                return Ok(());
                            }
                            continue;
                        }
                        file.write_all(&bytes).await.map_err(|e| e.to_string())?;
                        downloaded += bytes.len() as u64;
                        last_progress = Instant::now();
                        let elapsed = start.elapsed().as_secs_f64().max(0.001);
                        let speed = downloaded as f64 / elapsed;

                        if last_push.elapsed() >= Duration::from_millis(200) {
                            last_push = Instant::now();
                            let mut tasks = dm.tasks.lock().unwrap();
                            if let Some(t) = tasks.get_mut(&task_id) {
                                t.downloaded = downloaded;
                                t.speed = speed;
                            }
                            drop(tasks);
                            emit_task(window, dm, task_id);
                        }
                    }
                }
            }
        }
    }

    file.flush().await.map_err(|e| e.to_string())?;
    drop(file);
    fs::rename(&temp_path, save_path).await.map_err(|e| e.to_string())?;

    {
        let mut tasks = dm.tasks.lock().unwrap();
        if let Some(t) = tasks.get_mut(&task_id) {
            t.downloaded = downloaded;
            t.total = downloaded;
        }
    }
    Ok(())
}

fn emit_task(window: &tauri::Window, dm: &DownloadManager, task_id: u32) {
    let snap = dm.tasks.lock().unwrap().get(&task_id).map(|t| t.snapshot());
    if let Some(s) = snap {
        let _ = window.emit("task-updated", s);
    }
}

#[tauri::command]
pub async fn cmd_cancel_task(
    id: u32,
    dm: tauri::State<'_, DownloadManager>,
    window: tauri::Window,
) -> Result<(), String> {
    let mut tasks = dm.tasks.lock().unwrap();
    if let Some(t) = tasks.get_mut(&id) {
        match t.status {
            TaskStatus::Queued => {
                t.status = TaskStatus::Cancelled;
                t.error = "用户手动终止".to_string();
                let snap = t.snapshot();
                drop(tasks);
                let _ = window.emit("task-updated", snap);
            }
            TaskStatus::Running => {
                if let Some(tx) = t.cancel_tx.take() {
                    let _ = tx.send(());
                }
            }
            _ => {}
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn cmd_cancel_all(
    dm: tauri::State<'_, DownloadManager>,
    window: tauri::Window,
) -> Result<u32, String> {
    let mut count = 0u32;
    let mut tasks = dm.tasks.lock().unwrap();
    let mut snaps = vec![];
    for t in tasks.values_mut() {
        match t.status {
            TaskStatus::Queued => {
                t.status = TaskStatus::Cancelled;
                t.error = "用户手动终止".to_string();
                snaps.push(t.snapshot());
                count += 1;
            }
            TaskStatus::Running => {
                if let Some(tx) = t.cancel_tx.take() { let _ = tx.send(()); }
                count += 1;
            }
            _ => {}
        }
    }
    drop(tasks);
    for s in snaps { let _ = window.emit("task-updated", s); }
    Ok(count)
}

#[tauri::command]
pub async fn cmd_retry_failed(
    dm: tauri::State<'_, DownloadManager>,
    auth_state: tauri::State<'_, Mutex<AuthState>>,
    window: tauri::Window,
) -> Result<u32, String> {
    let retry_ids: Vec<(u32, String, String, String)> = {
        let tasks = dm.tasks.lock().unwrap();
        tasks.values()
            .filter(|t| matches!(t.status, TaskStatus::Failed | TaskStatus::Timeout | TaskStatus::Cancelled))
            .map(|t| (t.id, t.name.clone(), t.url.clone(), t.save_path.clone()))
            .collect()
    };

    let count = retry_ids.len() as u32;
    let (auth_cookie, proxy) = {
        let s = auth_state.lock().unwrap();
        (s.auth_cookie.clone(), s.proxy.clone())
    };

    for (id, name, url, save_path) in retry_ids {
        let new_path = resolve_path(&save_path);
        let (cancel_tx, cancel_rx) = tokio::sync::oneshot::channel::<()>();
        {
            let mut tasks = dm.tasks.lock().unwrap();
            if let Some(t) = tasks.get_mut(&id) {
                t.status = TaskStatus::Queued;
                t.downloaded = 0;
                t.total = 0;
                t.speed = 0.0;
                t.error = String::new();
                t.save_path = new_path.clone();
                t.cancel_tx = Some(cancel_tx);
                let snap = t.snapshot();
                drop(tasks);
                let _ = window.emit("task-updated", snap);
            } else { continue; }
        }
        let dm_clone = dm.inner().clone();
        let win = window.clone();
        let ac = auth_cookie.clone();
        let px = proxy.clone();
        let _n = name.clone();
        let u = url.clone();
        let sp = new_path.clone();
        tokio::spawn(async move {
            {
                let mut tasks = dm_clone.tasks.lock().unwrap();
                if let Some(t) = tasks.get_mut(&id) { t.status = TaskStatus::Running; }
            }
            emit_task(&win, &dm_clone, id);
            let result = do_download(id, &u, &sp, &ac, &px,
                                      &mut tokio::sync::oneshot::channel::<()>().1,
                                      &dm_clone, &win).await;
            let mut tasks = dm_clone.tasks.lock().unwrap();
            if let Some(t) = tasks.get_mut(&id) {
                match result {
                    Ok(()) => { t.status = TaskStatus::Success; t.speed = 0.0; }
                    Err(e) if t.status != TaskStatus::Cancelled && t.status != TaskStatus::Timeout => {
                        t.status = TaskStatus::Failed; t.error = e;
                    }
                    _ => {}
                }
            }
            drop(tasks);
            emit_task(&win, &dm_clone, id);
        });
        drop(cancel_rx);
    }

    Ok(count)
}

#[tauri::command]
pub async fn cmd_clear_finished(
    dm: tauri::State<'_, DownloadManager>,
    window: tauri::Window,
) -> Result<(), String> {
    let removed: Vec<u32> = {
        let mut tasks = dm.tasks.lock().unwrap();
        let ids: Vec<u32> = tasks.values()
            .filter(|t| matches!(t.status,
                TaskStatus::Success | TaskStatus::Failed |
                TaskStatus::Timeout | TaskStatus::Cancelled))
            .map(|t| t.id)
            .collect();
        for id in &ids { tasks.remove(id); }
        ids
    };
    for id in removed {
        let _ = window.emit("task-removed", id);
    }
    Ok(())
}

#[tauri::command]
pub async fn cmd_get_tasks(
    dm: tauri::State<'_, DownloadManager>,
) -> Result<Vec<TaskSnapshot>, String> {
    let tasks = dm.tasks.lock().unwrap();
    let mut snaps: Vec<TaskSnapshot> = tasks.values().map(|t| t.snapshot()).collect();
    snaps.sort_by_key(|s| s.id);
    Ok(snaps)
}
