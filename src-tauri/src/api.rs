use base64::{engine::general_purpose::STANDARD as B64, Engine};
use reqwest::{Client, header};
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::Emitter;
use tauri::Manager;

type AnyResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

const USER_AGENT: &str = "VRChatVRCADownloader/2.0";
const AUTH_URL: &str = "https://api.vrchat.cloud/api/1/auth/user";
const FILES_URL: &str = "https://api.vrchat.cloud/api/1/files";
const AVATARS_URL: &str = "https://api.vrchat.cloud/api/1/avatars";
const TOTP_URL: &str = "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify";
const EMAIL_OTP_URL: &str = "https://api.vrchat.cloud/api/1/auth/twofactorauth/emailotp/verify";

// ── 全局认证状态 ─────────────────────────────────────────────────────────────

#[derive(Default, Clone)]
pub struct AuthState {
    pub auth_cookie: String,
    pub proxy: Option<String>,
}

// ── 数据结构 ──────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AvatarItem {
    pub name: String,
    pub short_name: String,
    pub version: u32,
    pub created_at: String,
    pub file_id: String,
    pub url: String,
    pub image_url: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LoginResult {
    pub success: bool,
    pub requires_2fa: bool,
    pub fa_methods: Vec<String>,
    pub error: Option<String>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct AuthUserPayload {
    id: Option<String>,
    #[serde(rename = "displayName")]
    display_name: Option<String>,
    #[serde(rename = "requiresTwoFactorAuth")]
    requires_two_factor_auth: Option<serde_json::Value>,
}

// ── HTTP 客户端 ───────────────────────────────────────────────────────────────

fn build_client(proxy: &Option<String>) -> AnyResult<Client> {
    let mut builder = Client::builder()
        .user_agent(USER_AGENT)
        .cookie_store(true)
        .timeout(std::time::Duration::from_secs(20));
    if let Some(p) = proxy {
        builder = builder.proxy(reqwest::Proxy::all(p)?);
    }
    Ok(builder.build()?)
}

fn cookie_header(auth_cookie: &str) -> header::HeaderValue {
    header::HeaderValue::from_str(auth_cookie).unwrap_or_else(|_| header::HeaderValue::from_static(""))
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

pub fn extract_short_name(raw: &str) -> String {
    let text = raw.trim();
    if text.is_empty() {
        return "Unknown".to_string();
    }
    let re = regex::Regex::new(r"(?i)^\s*Avatar\s*-\s*(.*?)\s*-\s*Asset\s*bundle\s*-").unwrap();
    if let Some(cap) = re.captures(text) {
        let s = cap[1].trim().to_string();
        if !s.is_empty() {
            return s;
        }
    }
    text.to_string()
}

fn extract_image_url(file_item: &serde_json::Value, latest: &serde_json::Value) -> Option<String> {
    let keys = ["imageUrl", "imageURL", "thumbnailImageUrl", "thumbnailUrl", "iconUrl"];
    for key in &keys {
        for container in &[file_item, latest] {
            if let Some(v) = container.get(key).and_then(|v| v.as_str()) {
                if v.starts_with("http") {
                    return Some(v.to_string());
                }
            }
        }
    }
    None
}

fn extract_file_id_from_url(url: &str) -> Option<String> {
    let re = regex::Regex::new(r"/file/(file_[^/]+)/").unwrap();
    re.captures(url).map(|c| c[1].to_string())
}

// ── Tauri 命令 ────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn cmd_login(
    username: String,
    password: String,
    proxy: Option<String>,
    state: tauri::State<'_, Mutex<AuthState>>,
) -> Result<LoginResult, String> {
    let cred = B64.encode(format!("{}:{}", username, password));
    let client = build_client(&proxy).map_err(|e| e.to_string())?;

    let resp = client
        .get(AUTH_URL)
        .header(header::AUTHORIZATION, format!("Basic {}", cred))
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if resp.status() == 401 {
        return Ok(LoginResult {
            success: false,
            requires_2fa: false,
            fa_methods: vec![],
            error: Some("用户名或密码错误".to_string()),
        });
    }

    // 从响应头提取 Set-Cookie 中的 auth
    let auth_value = resp
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .find_map(|v| {
            let s = v.to_str().ok()?;
            if s.starts_with("auth=") {
                let val = s.split(';').next()?.trim_start_matches("auth=");
                Some(val.to_string())
            } else {
                None
            }
        });

    let payload: AuthUserPayload = resp.json().await.map_err(|e| e.to_string())?;

    // 检查 2FA
    let requires_2fa = payload.requires_two_factor_auth.as_ref().map_or(false, |v| {
        match v {
            serde_json::Value::Array(arr) => !arr.is_empty(),
            serde_json::Value::Bool(b) => *b == true,
            _ => false,
        }
    });

    let fa_methods: Vec<String> = payload
        .requires_two_factor_auth
        .as_ref()
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
        .unwrap_or_default();

    let Some(auth_val) = auth_value else {
        return Ok(LoginResult {
            success: false,
            requires_2fa: false,
            fa_methods: vec![],
            error: Some("登录失败：未获取到 auth cookie".to_string()),
        });
    };

    let auth_cookie = format!("auth={};", auth_val);

    // 保存 auth + proxy 到状态
    {
        let mut s = state.lock().unwrap();
        s.auth_cookie = auth_cookie.clone();
        s.proxy = proxy.clone();
    }

    if requires_2fa {
        return Ok(LoginResult {
            success: false,
            requires_2fa: true,
            fa_methods,
            error: None,
        });
    }

    Ok(LoginResult {
        success: true,
        requires_2fa: false,
        fa_methods: vec![],
        error: None,
    })
}

#[tauri::command]
pub async fn cmd_verify_2fa(
    code: String,
    method: String,
    state: tauri::State<'_, Mutex<AuthState>>,
) -> Result<LoginResult, String> {
    let (auth_cookie, proxy) = {
        let s = state.lock().unwrap();
        (s.auth_cookie.clone(), s.proxy.clone())
    };

    let url = if method == "emailotp" { EMAIL_OTP_URL } else { TOTP_URL };
    let client = build_client(&proxy).map_err(|e| e.to_string())?;

    let resp = client
        .post(url)
        .header(header::COOKIE, cookie_header(&auth_cookie))
        .header(header::CONTENT_TYPE, "application/json")
        .json(&serde_json::json!({ "code": code.trim() }))
        .send()
        .await
        .map_err(|e| e.to_string())?;

    let data: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    if data.get("verified").and_then(|v| v.as_bool()).unwrap_or(false) {
        Ok(LoginResult { success: true, requires_2fa: false, fa_methods: vec![], error: None })
    } else {
        Ok(LoginResult {
            success: false,
            requires_2fa: false,
            fa_methods: vec![],
            error: Some("2FA 验证失败，请检查验证码".to_string()),
        })
    }
}

#[tauri::command]
pub async fn cmd_fetch_avatars(
    state: tauri::State<'_, Mutex<AuthState>>,
    window: tauri::Window,
) -> Result<Vec<AvatarItem>, String> {
    let (auth_cookie, proxy) = {
        let s = state.lock().unwrap();
        (s.auth_cookie.clone(), s.proxy.clone())
    };

    let client = build_client(&proxy).map_err(|e| e.to_string())?;

    // Step 1: fetch all .vrca files
    let _ = window.emit("fetch-progress", "正在加载文件列表...");
    let mut all_files: Vec<serde_json::Value> = vec![];
    let mut offset = 0usize;
    loop {
        let _ = window.emit("fetch-progress", format!("正在加载文件列表: 已获取 {} 条", offset));
        let resp = client
            .get(FILES_URL)
            .header(header::COOKIE, cookie_header(&auth_cookie))
            .query(&[("n", "100"), ("offset", &offset.to_string())])
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if resp.status() == 401 { return Err("登录已过期，请重新登录".to_string()); }
        let data: Vec<serde_json::Value> = resp.json().await.map_err(|e| e.to_string())?;
        if data.is_empty() { break; }
        offset += data.len();
        all_files.extend(data);
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }

    // Step 2: fetch avatar image map
    let _ = window.emit("fetch-progress", "正在加载封面图映射...");
    let mut avatar_image_map: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    let mut av_offset = 0usize;
    loop {
        let _ = window.emit("fetch-progress", format!("正在加载封面图映射: 已获取 {} 个", av_offset));
        let resp = client
            .get(AVATARS_URL)
            .header(header::COOKIE, cookie_header(&auth_cookie))
            .query(&[("n", "100"), ("offset", &av_offset.to_string()), ("releaseStatus", "all")])
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if resp.status() == 401 { break; }
        let data: Vec<serde_json::Value> = resp.json().await.map_err(|e| e.to_string())?;
        if data.is_empty() { break; }
        av_offset += data.len();
        for av in &data {
            let img = av.get("imageUrl").or_else(|| av.get("thumbnailImageUrl"))
                .and_then(|v| v.as_str()).filter(|s| s.starts_with("http"));
            if let Some(img_url) = img {
                if let Some(pkgs) = av.get("unityPackages").and_then(|v| v.as_array()) {
                    for pkg in pkgs {
                        if let Some(asset_url) = pkg.get("assetUrl").and_then(|v| v.as_str()) {
                            if let Some(fid) = extract_file_id_from_url(asset_url) {
                                avatar_image_map.insert(fid, img_url.to_string());
                            }
                        }
                    }
                }
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }

    // Step 3: build avatar list
    let mut avatars: Vec<AvatarItem> = vec![];
    for fi in &all_files {
        if fi.get("extension").and_then(|v| v.as_str()) != Some(".vrca") { continue; }
        let versions = match fi.get("versions").and_then(|v| v.as_array()) {
            Some(v) if !v.is_empty() => v,
            _ => continue,
        };
        let latest = versions.iter().max_by_key(|v| v.get("version").and_then(|x| x.as_u64()).unwrap_or(0));
        let Some(latest) = latest else { continue };
        let url = latest.get("file").and_then(|f| f.get("url")).and_then(|v| v.as_str());
        let Some(url) = url else { continue };

        let name = fi.get("name").and_then(|v| v.as_str()).unwrap_or("Unknown").to_string();
        let file_id = fi.get("id").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
        let version = latest.get("version").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
        let created_at = latest.get("created_at").and_then(|v| v.as_str()).unwrap_or("").to_string();

        let image_url = extract_image_url(fi, latest)
            .or_else(|| avatar_image_map.get(&file_id).cloned());

        avatars.push(AvatarItem {
            short_name: extract_short_name(&name),
            name,
            version,
            created_at,
            file_id,
            url: url.to_string(),
            image_url,
        });
    }

    avatars.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    let _ = window.emit("fetch-progress", format!("加载完成: {} 个资源", avatars.len()));
    Ok(avatars)
}

#[tauri::command]
pub async fn cmd_fetch_image_bytes(
    url: String,
    #[allow(unused_variables)] thumb: Option<bool>,
    state: tauri::State<'_, Mutex<AuthState>>,
    app: tauri::AppHandle,
) -> Result<Vec<u8>, String> {
    // 磁盘缓存 key：url 的 sha1
    let cache_key = {
        use sha1::{Sha1, Digest};
        let mut h = Sha1::new();
        h.update(url.as_bytes());
        hex::encode(h.finalize())
    };

    let cache_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("img_cache");
    tokio::fs::create_dir_all(&cache_dir).await.map_err(|e| e.to_string())?;
    let cache_path = cache_dir.join(&cache_key);

    // 命中磁盘缓存直接返回
    if let Ok(data) = tokio::fs::read(&cache_path).await {
        return Ok(data);
    }

    // 网络拉取原图
    let (auth_cookie, proxy) = {
        let s = state.lock().unwrap();
        (s.auth_cookie.clone(), s.proxy.clone())
    };
    let client = build_client(&proxy).map_err(|e| e.to_string())?;
    let resp = client
        .get(&url)
        .header(header::COOKIE, cookie_header(&auth_cookie))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    let bytes = resp.bytes().await.map_err(|e| e.to_string())?.to_vec();

    // 异步写磁盘缓存
    let _ = tokio::fs::write(&cache_path, &bytes).await;

    Ok(bytes)
}

// ── 会话持久化 ────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
struct SessionFile {
    auth_cookie: String,
    proxy: Option<String>,
    display_name: String,
    saved_at: i64, // Unix 时间戳（秒）
}

fn session_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app.path().app_data_dir().map_err(|e| e.to_string())?.join("session.json"))
}

// 保存登录会话到磁盘
#[tauri::command]
pub async fn cmd_save_session(
    display_name: String,
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AuthState>>,
) -> Result<(), String> {
    let (auth_cookie, proxy) = {
        let s = state.lock().unwrap();
        (s.auth_cookie.clone(), s.proxy.clone())
    };
    if auth_cookie.is_empty() { return Ok(()); }

    let session = SessionFile {
        auth_cookie,
        proxy,
        display_name,
        saved_at: chrono::Utc::now().timestamp(),
    };
    let json = serde_json::to_string(&session).map_err(|e| e.to_string())?;
    let path = session_path(&app)?;
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
    }
    tokio::fs::write(&path, json).await.map_err(|e| e.to_string())?;
    Ok(())
}

// 尝试恢复上次会话，返回显示名；失败或过期则返回空字符串
#[tauri::command]
pub async fn cmd_restore_session(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AuthState>>,
) -> Result<String, String> {
    let path = session_path(&app)?;
    let json = match tokio::fs::read_to_string(&path).await {
        Ok(s) => s,
        Err(_) => return Ok(String::new()),
    };
    let session: SessionFile = match serde_json::from_str(&json) {
        Ok(s) => s,
        Err(_) => return Ok(String::new()),
    };

    // 超过 30 天视为过期
    let age_days = (chrono::Utc::now().timestamp() - session.saved_at) / 86400;
    if age_days > 30 {
        let _ = tokio::fs::remove_file(&path).await;
        return Ok(String::new());
    }

    // 向 VRChat 验证 cookie 是否仍有效
    let client = build_client(&session.proxy).map_err(|e| e.to_string())?;
    let resp = client
        .get(AUTH_URL)
        .header(header::COOKIE, cookie_header(&session.auth_cookie))
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if resp.status() != 200 {
        // Cookie 已失效，删除本地文件
        let _ = tokio::fs::remove_file(&path).await;
        return Ok(String::new());
    }

    let payload: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;

    // 需要重新 2FA 或响应异常
    if payload.get("requiresTwoFactorAuth").is_some()
        || payload.get("id").is_none()
    {
        let _ = tokio::fs::remove_file(&path).await;
        return Ok(String::new());
    }

    // 取最新显示名
    let display_name = payload
        .get("displayName")
        .and_then(|v| v.as_str())
        .unwrap_or(&session.display_name)
        .to_string();

    // 写入运行时状态
    {
        let mut s = state.lock().unwrap();
        s.auth_cookie = session.auth_cookie;
        s.proxy = session.proxy;
    }

    Ok(display_name)
}

// 清除已保存的会话（退出登录时调用）
#[tauri::command]
pub async fn cmd_clear_session(app: tauri::AppHandle) -> Result<(), String> {
    let path = session_path(&app)?;
    let _ = tokio::fs::remove_file(&path).await;
    Ok(())
}

// ── 配置持久化 ────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct AppConfig {
    pub proxy: Option<String>,
    pub filename_template: Option<String>,
}

fn config_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app.path().app_data_dir().map_err(|e| e.to_string())?.join("config.json"))
}

#[tauri::command]
pub async fn cmd_save_config(
    config: AppConfig,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let json = serde_json::to_string(&config).map_err(|e| e.to_string())?;
    let path = config_path(&app)?;
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
    }
    tokio::fs::write(&path, json).await.map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn cmd_load_config(app: tauri::AppHandle) -> Result<AppConfig, String> {
    let path = config_path(&app)?;
    match tokio::fs::read_to_string(&path).await {
        Ok(json) => serde_json::from_str(&json).map_err(|e| e.to_string()),
        Err(_) => Ok(AppConfig::default()),
    }
}
