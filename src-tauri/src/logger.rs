//! 轻量级文件日志
//! - 单文件追加写入，超过 5MB 自动轮转为 `.old`

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

const LOG_FILE_NAME: &str = "VRChatDownloader.log";
const MAX_LOG_SIZE: u64 = 5 * 1024 * 1024;

static LOG_PATH: OnceLock<PathBuf> = OnceLock::new();

/// 初始化日志
pub fn init(fallback_dir: Option<PathBuf>) {
    if LOG_PATH.get().is_some() {
        return;
    }

    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(d) = exe_dir {
        candidates.push(d);
    }
    if let Some(d) = fallback_dir {
        candidates.push(d);
    }

    for dir in candidates {
        let path = dir.join(LOG_FILE_NAME);
        let writable = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .is_ok();
        if !writable {
            continue;
        }
        rotate_if_needed(&path);
        let _ = LOG_PATH.set(path);
        return;
    }
}

fn rotate_if_needed(path: &Path) {
    let too_big = std::fs::metadata(path)
        .map(|m| m.len() > MAX_LOG_SIZE)
        .unwrap_or(false);
    if !too_big {
        return;
    }
    let old = path.with_extension("log.old");
    let _ = std::fs::remove_file(&old);
    let _ = std::fs::rename(path, &old);
}

pub fn info(msg: impl AsRef<str>) {
    write("INFO", msg.as_ref());
}

pub fn warn(msg: impl AsRef<str>) {
    write("WARN", msg.as_ref());
}

pub fn error(msg: impl AsRef<str>) {
    write("ERROR", msg.as_ref());
}

fn write(level: &str, msg: &str) {
    let Some(path) = LOG_PATH.get() else { return };
    let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f");
    let line = format!("[{timestamp}] [{level}] {}\n", msg.replace('\n', " "));

    #[cfg(debug_assertions)]
    {
        let _ = std::io::stderr().write_all(line.as_bytes());
    }

    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = f.write_all(line.as_bytes());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_and_write() {
        // 测试
        init(None);
        assert!(LOG_PATH.get().is_some(), "日志路径应初始化成功");
        info("单元测试日志条目");
        let path = LOG_PATH.get().unwrap();
        let content = std::fs::read_to_string(path).unwrap();
        assert!(content.contains("[INFO] 单元测试日志条目"));
    }
}
