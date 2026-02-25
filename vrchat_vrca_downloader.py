import os
import re
import threading
import time
import io
import base64
import webbrowser
import hashlib
import sys
import subprocess
import tempfile
import json
import shutil
from datetime import datetime
from http.cookies import SimpleCookie
from concurrent.futures import ThreadPoolExecutor

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

try:
    import webview as embedded_webview
except ImportError:
    embedded_webview = None

API_URL = "https://api.vrchat.cloud/api/1/files"
AVATAR_URL = "https://api.vrchat.cloud/api/1/avatars"
LOGIN_URL = "https://vrchat.com/home/login"
USER_AGENT = "VRChatVRCADownloader/1.3"
MAX_WORKERS = 3
STALL_SECONDS = 25
AVATAR_CACHE_DIR = os.path.join("cache", "avatar_images")
THUMB_SIZE = (64, 64)
PREVIEW_IMAGE_SIZE = (360, 360)
THUMB_PREFETCH_WORKERS = 4
CHECK_OFF_TEXT = "选择"
CHECK_ON_TEXT = "已选"


def sanitize_filename(name):
    sanitized = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
    return sanitized or "Unknown"


def extract_short_avatar_name(raw_name):
    text = (raw_name or "").strip()
    if not text:
        return "Unknown"
    # Typical VRChat export pattern:
    # Avatar - <DisplayName> - Asset bundle - ...
    match = re.match(r"^\s*Avatar\s*-\s*(.*?)\s*-\s*Asset\s*bundle\s*-", text, re.IGNORECASE)
    if match:
        short_name = match.group(1).strip()
        if short_name:
            return short_name
    return text


def build_custom_filename(template, avatar):
    created_at = str(avatar.get("created_at", "") or "")
    date_text = created_at[:10] if len(created_at) >= 10 else datetime.now().strftime("%Y-%m-%d")
    context = {
        "name": str(avatar.get("name", "Unknown")),
        "short_name": extract_short_avatar_name(str(avatar.get("name", "Unknown"))),
        "version": str(avatar.get("version", "0")),
        "id": str(avatar.get("file_id", "unknown")),
        "date": date_text,
    }
    base_template = (template or "").strip() or "{short_name}"

    def replacer(match):
        key = match.group(1).strip()
        return context.get(key, key)

    rendered = re.sub(r"\{([^{}]+)\}", replacer, base_template)
    rendered = sanitize_filename(rendered)
    if rendered.lower().endswith(".vrca"):
        return rendered
    return f"{rendered}.vrca"


def extract_cookie_tokens(raw_cookie):
    text = raw_cookie or ""
    tokens = {"auth": None, "twoFactorAuth": None}
    for key in ("auth", "twoFactorAuth"):
        match = re.search(rf"{key}=([^;\s]+)", text)
        if match:
            tokens[key] = match.group(1).strip()
    return tokens


def extract_file_id_from_url(url):
    if not isinstance(url, str):
        return None
    match = re.search(r"/file/(file_[^/]+)/", url)
    if match:
        return match.group(1)
    return None


def build_avatar_image_map(avatars):
    mapping = {}
    for avatar in avatars or []:
        image_url = avatar.get("imageUrl") or avatar.get("thumbnailImageUrl")
        if not isinstance(image_url, str) or not image_url.startswith("http"):
            continue
        for package in avatar.get("unityPackages", []):
            file_id = extract_file_id_from_url(package.get("assetUrl"))
            if file_id:
                mapping[file_id] = image_url
    return mapping


def build_avatar_cache_filename(file_id, image_url):
    safe_file_id = re.sub(r'[\\/:*?"<>|]+', "_", (file_id or "").strip())
    url_hash = hashlib.sha1((image_url or "").encode("utf-8")).hexdigest()[:16]
    if safe_file_id:
        return f"{safe_file_id}_{url_hash}.img"
    return f"url_{url_hash}.img"


def build_cookie_helper_command(is_frozen, executable_path, script_path, output_path):
    if is_frozen:
        return [executable_path, "--cookie-helper", output_path]
    return [executable_path, script_path, "--cookie-helper", output_path]


def extract_auth_from_webview_cookies(cookies):
    for cookie in cookies or []:
        name, value = _parse_cookie_name_value(cookie)
        if name == "auth" and value:
            return value
    return None


def _parse_cookie_name_value(cookie):
    if isinstance(cookie, SimpleCookie):
        for key, morsel in cookie.items():
            return str(key).strip(), str(morsel.value).strip()
        return "", ""
    if hasattr(cookie, "key") and hasattr(cookie, "value"):
        return str(getattr(cookie, "key", "")).strip(), str(getattr(cookie, "value", "")).strip()
    if isinstance(cookie, dict):
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", "")).strip()
        return name, value
    if hasattr(cookie, "name") and hasattr(cookie, "value"):
        return str(getattr(cookie, "name", "")).strip(), str(getattr(cookie, "value", "")).strip()
    text = str(cookie)
    if "=" in text:
        name, value = text.split("=", 1)
        return name.strip(), value.strip()
    return "", ""


def build_cookie_header_from_webview_cookies(cookies):
    pairs = []
    seen = set()
    for cookie in cookies or []:
        name, value = _parse_cookie_name_value(cookie)
        if not name or value is None or value == "":
            continue
        if name in seen:
            continue
        seen.add(name)
        pairs.append((name, value))
    if not pairs:
        return ""
    return "; ".join(f"{name}={value}" for name, value in pairs) + ";"


def should_finalize_auth_capture(auth_value, is_verified):
    return bool(auth_value) and bool(is_verified)


def is_auth_user_response_valid(status_code, payload):
    if status_code != 200 or not isinstance(payload, dict):
        return False
    if payload.get("requiresTwoFactorAuth"):
        return False
    return bool(payload.get("id") or payload.get("displayName"))


def verify_auth_cookie(auth_value):
    if not auth_value:
        return False
    headers = {"User-Agent": USER_AGENT, "Cookie": f"auth={auth_value};"}
    endpoints = [
        "https://vrchat.com/api/1/auth/user",
        "https://api.vrchat.cloud/api/1/auth/user",
    ]
    for endpoint in endpoints:
        try:
            response = requests.get(endpoint, headers=headers, timeout=8)
            payload = response.json()
            if is_auth_user_response_valid(response.status_code, payload):
                return True
        except Exception:
            continue
    return False


def format_bytes(size):
    if not size:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def compute_aggregate_progress(tasks):
    downloaded_sum = 0
    total_sum = 0
    for task in tasks:
        total = int(task.get("total", 0))
        if total > 0:
            downloaded_sum += int(task.get("downloaded", 0))
            total_sum += total
    percent = 0.0
    if total_sum > 0:
        percent = round((downloaded_sum / total_sum) * 100, 2)
    return percent, downloaded_sum, total_sum


def resolve_conflict_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base}_{stamp}{ext}"
    index = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{stamp}_{index}{ext}"
        index += 1
    return candidate


def is_stalled(last_progress_ts, now_ts, stall_seconds):
    return now_ts - last_progress_ts >= stall_seconds


def build_proxy_dict(proxy_text):
    value = (proxy_text or "").strip()
    if not value:
        return None
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ValueError("代理地址格式无效，请使用 http:// 或 https:// 开头")
    return {"http": value, "https": value}


def delete_dir_with_retry(path, retries=5, delay=0.12):
    if not path:
        return
    for _ in range(max(1, retries)):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            return
        except OSError:
            time.sleep(delay)


def _find_first_image_url(value):
    if isinstance(value, dict):
        for nested in value.values():
            result = _find_first_image_url(nested)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _find_first_image_url(nested)
            if result:
                return result
    elif isinstance(value, str):
        lower = value.lower()
        if lower.startswith("http") and any(ext in lower for ext in (".png", ".jpg", ".jpeg", ".webp")):
            return value
    return None


def extract_avatar_image_url(file_item, latest_version):
    candidate_keys = (
        "imageUrl",
        "imageURL",
        "thumbnailImageUrl",
        "thumbnailUrl",
        "iconUrl",
        "previewImageUrl",
    )
    for key in candidate_keys:
        value = file_item.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
        value = latest_version.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value

    for container in (file_item, latest_version):
        found = _find_first_image_url(container)
        if found:
            return found
    return None


class VRChatAPI:
    @staticmethod
    def format_cookie(raw_cookie):
        raw_cookie = raw_cookie.strip()
        if not raw_cookie:
            return ""
        if "auth=" not in raw_cookie:
            return f"auth={raw_cookie};"
        return raw_cookie

    @staticmethod
    def fetch_all_files(cookie, progress_callback, proxies=None):
        headers = {"User-Agent": USER_AGENT, "Cookie": cookie}
        offset, n = 0, 100
        all_files = []

        while True:
            progress_callback(f"正在加载文件列表: {offset}")
            try:
                response = requests.get(
                    API_URL,
                    headers=headers,
                    params={"n": n, "offset": offset},
                    timeout=15,
                    proxies=proxies,
                )
                if response.status_code == 401:
                    raise Exception("Cookie 无效或已过期")
                response.raise_for_status()

                data = response.json()
                if not data:
                    break
                all_files.extend(data)
                offset += n
                time.sleep(0.05)
            except requests.exceptions.RequestException as exc:
                raise Exception(f"网络请求失败: {exc}") from exc

        return all_files

    @staticmethod
    def fetch_user_avatars(cookie, progress_callback, proxies=None):
        headers = {"User-Agent": USER_AGENT, "Cookie": cookie}
        offset, n = 0, 100
        all_avatars = []
        while True:
            progress_callback(f"正在加载 Avatar 图像映射: {offset}")
            response = requests.get(
                AVATAR_URL,
                headers=headers,
                params={"n": n, "offset": offset, "releaseStatus": "all"},
                timeout=15,
                proxies=proxies,
            )
            if response.status_code == 401:
                raise Exception("Cookie 无效或已过期")
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            all_avatars.extend(data)
            offset += n
            time.sleep(0.05)
        return all_avatars

    @staticmethod
    def test_proxy_connectivity(proxies):
        start = time.time()
        response = requests.get(
            "https://api.vrchat.cloud/api/1/config",
            headers={"User-Agent": USER_AGENT},
            timeout=10,
            proxies=proxies,
        )
        response.raise_for_status()
        elapsed_ms = int((time.time() - start) * 1000)
        return response.status_code, elapsed_ms


def run_cookie_helper_mode(output_path):
    if embedded_webview is None:
        return 2

    state = {"captured": False}
    window = embedded_webview.create_window("VRChat 登录", LOGIN_URL, width=1000, height=760)

    def on_loaded():
        def auto_accept_cookie_banner():
            # Best-effort: common cookie-consent button selectors.
            script = """
                (function() {
                  const selectors = [
                    'button[mode="primary"]',
                    'button#accept-all',
                    'button[data-testid="accept-all"]',
                    'button[aria-label*="Accept"]',
                    'button[aria-label*="同意"]',
                    'button'
                  ];
                  for (const sel of selectors) {
                    const nodes = document.querySelectorAll(sel);
                    for (const el of nodes) {
                      const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                      if (txt.includes('accept') || txt.includes('agree') || txt.includes('同意') || txt.includes('允许')) {
                        el.click();
                        return true;
                      }
                    }
                  }
                  return false;
                })();
            """
            try:
                window.evaluate_js(script)
            except Exception:
                pass

        def poll():
            last_verified_auth = ""
            last_verified_result = False
            last_verify_ts = 0.0
            while not state["captured"]:
                try:
                    auto_accept_cookie_banner()
                    cookies = window.get_cookies()
                    auth_value = extract_auth_from_webview_cookies(cookies)
                    now = time.time()
                    if auth_value != last_verified_auth or (now - last_verify_ts) >= 2.5:
                        last_verified_auth = auth_value
                        last_verified_result = verify_auth_cookie(auth_value)
                        last_verify_ts = now

                    if should_finalize_auth_capture(auth_value, last_verified_result):
                        payload = {"auth": auth_value}
                        with open(output_path, "w", encoding="utf-8") as file_handle:
                            json.dump(payload, file_handle, ensure_ascii=False)
                        state["captured"] = True
                        try:
                            window.evaluate_js("alert('已获取 Cookie，点击确定后将自动关闭窗口。');")
                        except Exception:
                            pass
                        for item in list(embedded_webview.windows):
                            item.destroy()
                        break
                except Exception:
                    pass
                time.sleep(1.0)

        threading.Thread(target=poll, daemon=True).start()

    window.events.loaded += on_loaded
    embedded_webview.start()
    return 0


class DownloadTask:
    TERMINAL_STATUS = {"success", "failed", "timeout", "cancelled"}

    def __init__(self, task_id, name, url, version, save_path):
        self.task_id = task_id
        self.name = name
        self.url = url
        self.version = version
        self.save_path = save_path
        self.temp_path = f"{save_path}.part"
        self.status = "queued"
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0
        self.error = ""
        self.retry_count = 0
        self.created_ts = time.time()
        self.started_ts = None
        self.last_progress_ts = None
        self.cancel_event = threading.Event()

    def snapshot(self):
        return {
            "task_id": self.task_id,
            "name": self.name,
            "url": self.url,
            "version": self.version,
            "save_path": self.save_path,
            "status": self.status,
            "downloaded": self.downloaded,
            "total": self.total,
            "speed": self.speed,
            "error": self.error,
            "retry_count": self.retry_count,
        }


class DownloadManager:
    def __init__(self, app, worker_count=MAX_WORKERS, stall_seconds=STALL_SECONDS):
        self.app = app
        self.worker_count = max(1, worker_count)
        self.stall_seconds = stall_seconds
        self.lock = threading.Lock()
        self.tasks = []
        self.next_task_id = 1
        self.workers = []

        for _ in range(self.worker_count):
            worker = threading.Thread(target=self._worker_loop, daemon=True)
            worker.start()
            self.workers.append(worker)

    def add_task(self, name, url, version, save_path):
        with self.lock:
            final_path = resolve_conflict_path(save_path)
            task = DownloadTask(self.next_task_id, name, url, version, final_path)
            self.next_task_id += 1
            self.tasks.append(task)
        self._notify_task_updated(task)
        return task.task_id

    def cancel_tasks(self, task_ids):
        affected = 0
        with self.lock:
            for task in self.tasks:
                if task.task_id not in task_ids:
                    continue
                if self._cancel_task_locked(task):
                    affected += 1
                    self._notify_task_updated(task)
        return affected

    def cancel_all_tasks(self):
        affected = 0
        with self.lock:
            for task in self.tasks:
                if self._cancel_task_locked(task):
                    affected += 1
                    self._notify_task_updated(task)
        return affected

    def retry_failed_tasks(self):
        retried = 0
        with self.lock:
            for task in self.tasks:
                if task.status in {"failed", "timeout", "cancelled"}:
                    self._reset_task_for_retry(task)
                    retried += 1
                    self._notify_task_updated(task)
        return retried

    def clear_finished_tasks(self):
        with self.lock:
            self.tasks = [t for t in self.tasks if t.status not in DownloadTask.TERMINAL_STATUS]

    def get_snapshots(self):
        with self.lock:
            return [task.snapshot() for task in self.tasks]

    def _reset_task_for_retry(self, task):
        task.downloaded = 0
        task.total = 0
        task.speed = 0.0
        task.error = ""
        task.status = "queued"
        task.retry_count += 1
        task.cancel_event.clear()
        task.started_ts = None
        task.last_progress_ts = None
        task.save_path = resolve_conflict_path(task.save_path)
        task.temp_path = f"{task.save_path}.part"

    @staticmethod
    def _cancel_task_locked(task):
        if task.status == "queued":
            task.status = "cancelled"
            task.error = "用户手动终止"
            return True
        if task.status == "running":
            task.cancel_event.set()
            return True
        return False

    def _pick_next_queued_task(self):
        with self.lock:
            for task in self.tasks:
                if task.status == "queued":
                    task.status = "running"
                    task.started_ts = time.time()
                    task.last_progress_ts = task.started_ts
                    task.error = ""
                    task.cancel_event.clear()
                    return task
        return None

    def _worker_loop(self):
        while True:
            task = self._pick_next_queued_task()
            if not task:
                time.sleep(0.15)
                continue

            self._notify_task_updated(task)
            self._download_task(task)
            self._notify_task_updated(task)

            if task.status == "success":
                self.app.after(0, self.app.on_task_success, task.snapshot())

    def _download_task(self, task):
        cookie = VRChatAPI.format_cookie(self.app.cookie_var.get())
        headers = {"User-Agent": USER_AGENT, "Cookie": cookie}
        last_ui_push = 0.0

        try:
            proxies = self.app.get_proxy_config()
            with requests.get(
                task.url,
                headers=headers,
                stream=True,
                timeout=(15, self.stall_seconds),
                proxies=proxies,
            ) as response:
                if response.status_code == 401:
                    raise Exception("Cookie 无效或已过期")
                response.raise_for_status()
                task.total = int(response.headers.get("content-length", 0))
                task.downloaded = 0

                save_dir = os.path.dirname(task.save_path)
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                with open(task.temp_path, "wb") as file_handle:
                    for chunk in response.iter_content(chunk_size=65536):
                        now = time.time()
                        if task.cancel_event.is_set():
                            task.status = "cancelled"
                            task.error = "用户手动终止"
                            raise InterruptedError(task.error)
                        if not chunk:
                            if task.last_progress_ts and is_stalled(task.last_progress_ts, now, self.stall_seconds):
                                task.status = "timeout"
                                task.error = f"连续 {self.stall_seconds}s 无进度，已自动终止"
                                raise TimeoutError(task.error)
                            continue

                        file_handle.write(chunk)
                        task.downloaded += len(chunk)
                        task.last_progress_ts = now

                        elapsed = max(0.1, now - (task.started_ts or now))
                        task.speed = task.downloaded / elapsed

                        if now - last_ui_push >= 0.2:
                            last_ui_push = now
                            self._notify_task_updated(task)

            if task.cancel_event.is_set():
                task.status = "cancelled"
                task.error = "用户手动终止"
                raise InterruptedError(task.error)

            os.replace(task.temp_path, task.save_path)
            task.status = "success"
            task.speed = 0.0
        except requests.exceptions.ReadTimeout:
            task.status = "timeout"
            task.error = f"连续 {self.stall_seconds}s 无进度，已自动终止"
            self._cleanup_temp(task)
        except InterruptedError:
            self._cleanup_temp(task)
        except TimeoutError:
            self._cleanup_temp(task)
        except Exception as exc:
            if task.status not in {"cancelled", "timeout"}:
                task.status = "failed"
                task.error = str(exc)
            self._cleanup_temp(task)

    @staticmethod
    def _cleanup_temp(task):
        if task.temp_path and os.path.exists(task.temp_path):
            try:
                os.remove(task.temp_path)
            except OSError:
                pass

    def _notify_task_updated(self, task):
        self.app.after(0, self.app.on_task_updated, task.snapshot())


class App(tk.Tk):
    STATUS_LABELS = {
        "queued": "排队中",
        "running": "下载中",
        "success": "已完成",
        "failed": "失败",
        "timeout": "超时终止",
        "cancelled": "已终止",
    }

    def __init__(self):
        super().__init__()
        self.title("VRChat VRCA Downloader")
        self.geometry("1360x860")
        self.minsize(1200, 720)

        self.cookie_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.proxy_var = tk.StringVar()
        self.filename_template_var = tk.StringVar(value="{short_name}")
        self.auto_rip_var = tk.BooleanVar(value=False)
        self.rip_port_var = tk.StringVar(value="")
        self.vcmd = (self.register(self._validate_port), "%P")

        self.all_avatars = []
        self.avatar_lookup = {}
        self.checked_rows = set()
        self.task_rows = {}
        self.preview_cache = {}
        self.preview_photo = None
        self.preview_request_id = 0
        self.avatar_thumb_cache = {}
        self.avatar_cache_lock = threading.Lock()
        self.avatar_placeholder = self._create_placeholder_image()
        self.cookie_helper_process = None
        self.cookie_helper_output = ""
        self.cookie_helper_deadline = 0.0
        self.thumb_pool = ThreadPoolExecutor(max_workers=THUMB_PREFETCH_WORKERS)
        self.thumb_prefetch_generation = 0
        os.makedirs(AVATAR_CACHE_DIR, exist_ok=True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        self.download_manager = DownloadManager(self, worker_count=MAX_WORKERS, stall_seconds=STALL_SECONDS)

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 6))
        top.pack(fill="x")

        top_row_1 = ttk.Frame(top)
        top_row_1.pack(fill="x", pady=(0, 4))
        top_row_2 = ttk.Frame(top)
        top_row_2.pack(fill="x")

        ttk.Label(top_row_1, text="Cookie:").pack(side="left")
        self.cookie_entry = ttk.Entry(top_row_1, textvariable=self.cookie_var, width=42, show="*")
        self.cookie_entry.pack(side="left", padx=5)
        ttk.Button(top_row_1, text="内置登录", width=9, command=self.open_embedded_login).pack(side="left", padx=3)
        self.btn_refresh = ttk.Button(top_row_1, text="获取模型", command=self.load_files)
        self.btn_refresh.pack(side="left", padx=5)
        ttk.Separator(top_row_1, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(top_row_1, text="搜索:").pack(side="left")
        ttk.Entry(top_row_1, textvariable=self.search_var, width=24).pack(side="left", padx=5)
        self.search_var.trace_add("write", lambda *_: self.render_list())
        ttk.Button(top_row_1, text="关于软件", width=10, command=self.show_about).pack(side="right", padx=5)

        ttk.Label(top_row_2, text="网络代理:").pack(side="left")
        ttk.Entry(top_row_2, textvariable=self.proxy_var, width=22).pack(side="left", padx=5)
        ttk.Button(top_row_2, text="测试代理", command=self.test_proxy).pack(side="left", padx=3)
        ttk.Separator(top_row_2, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(top_row_2, text="文件名:").pack(side="left")
        ttk.Entry(top_row_2, textvariable=self.filename_template_var, width=20).pack(side="left", padx=5)
        ttk.Label(top_row_2, text="变量:{short_name}{name}{version}{id}{date}", foreground="gray").pack(
            side="left", padx=(2, 8)
        )
        ttk.Separator(top_row_2, orient="vertical").pack(side="left", fill="y", padx=8)
        self.check_rip = ttk.Checkbutton(top_row_2, text="自动调用 AssetRipper", variable=self.auto_rip_var)
        self.check_rip.pack(side="left", padx=5)
        ttk.Label(top_row_2, text="端口:").pack(side="left", padx=(5, 0))
        self.port_entry = ttk.Entry(
            top_row_2,
            textvariable=self.rip_port_var,
            width=8,
            validate="key",
            validatecommand=self.vcmd,
        )
        self.port_entry.pack(side="left", padx=5)

        controls = ttk.Frame(self, padding=(10, 0, 10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="全选", command=self.select_all_rows).pack(side="left")
        ttk.Button(controls, text="取消全选", command=self.clear_all_checks).pack(side="left", padx=6)
        ttk.Button(controls, text="批量下载选中项", command=self.queue_selected_downloads).pack(side="left")
        ttk.Button(controls, text="终止选中任务", command=self.terminate_selected_tasks).pack(side="left", padx=6)
        ttk.Button(controls, text="一键终止全部任务", command=self.terminate_all_tasks).pack(side="left", padx=6)
        ttk.Button(controls, text="重试失败任务", command=self.retry_failed_tasks).pack(side="left", padx=6)
        ttk.Button(controls, text="清理已结束任务", command=self.clear_finished_tasks).pack(side="left", padx=6)

        main_pane = ttk.PanedWindow(self, orient="vertical")
        main_pane.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        upper_frame = ttk.Frame(main_pane)
        lower_frame = ttk.Frame(main_pane)
        main_pane.add(upper_frame, weight=3)
        main_pane.add(lower_frame, weight=2)

        list_left = ttk.Frame(upper_frame)
        list_left.pack(side="left", fill="both", expand=True)
        list_right = ttk.Frame(upper_frame, width=430)
        list_right.pack(side="right", fill="y", padx=(8, 0))
        list_right.pack_propagate(False)

        columns = ("check", "name", "version", "date", "action")
        self.tree = ttk.Treeview(list_left, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="预览")
        self.tree.heading("check", text="选择")
        self.tree.heading("name", text="模型名称", command=lambda: self._sort_column("name", False))
        self.tree.heading("version", text="迭代版本")
        self.tree.heading("date", text="最后更新")
        self.tree.heading("action", text="操作")
        self.tree.column("#0", width=92, anchor="center", stretch=False)
        self.tree.column("check", width=78, anchor="center", stretch=False)
        self.tree.column("name", width=420)
        self.tree.column("version", width=90, anchor="center")
        self.tree.column("date", width=170, anchor="center")
        self.tree.column("action", width=120, anchor="center")

        scroll = ttk.Scrollbar(list_left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.start_download())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.on_avatar_selection_changed())
        self.tree.bind("<Button-1>", self.on_tree_click_toggle_check, add="+")
        self.tree.tag_configure("checked", background="#7EC8FF", foreground="#0D1B2A")

        ttk.Label(list_right, text="Avatar 预览", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.preview_canvas = tk.Canvas(
            list_right,
            width=PREVIEW_IMAGE_SIZE[0],
            height=PREVIEW_IMAGE_SIZE[1],
            bg="#1f1f1f",
            highlightthickness=1,
            highlightbackground="#404040",
        )
        self.preview_canvas.pack(fill="x", expand=False)
        self.preview_image_item = self.preview_canvas.create_image(
            PREVIEW_IMAGE_SIZE[0] // 2,
            PREVIEW_IMAGE_SIZE[1] // 2,
            image="",
        )
        self.preview_text_item = self.preview_canvas.create_text(
            PREVIEW_IMAGE_SIZE[0] // 2,
            PREVIEW_IMAGE_SIZE[1] // 2,
            text="未选择 Avatar",
            fill="#d7d7d7",
            font=("Segoe UI", 11),
        )
        self.preview_meta = ttk.Label(
            list_right,
            text="",
            foreground="gray",
            justify="left",
            wraplength=400,
        )
        self.preview_meta.pack(anchor="w", fill="x", pady=(8, 0))
        task_label = ttk.Label(lower_frame, text="下载任务", padding=(0, 0))
        task_label.pack(anchor="w")
        task_container = ttk.Frame(lower_frame)
        task_container.pack(fill="both", expand=True, pady=(4, 0))
        task_columns = ("name", "status", "progress", "speed", "error", "action")
        self.task_tree = ttk.Treeview(task_container, columns=task_columns, show="headings", selectmode="extended")
        self.task_tree.heading("name", text="任务名")
        self.task_tree.heading("status", text="状态")
        self.task_tree.heading("progress", text="进度")
        self.task_tree.heading("speed", text="速度")
        self.task_tree.heading("error", text="错误信息")
        self.task_tree.heading("action", text="操作")

        self.task_tree.column("name", width=260)
        self.task_tree.column("status", width=110, anchor="center")
        self.task_tree.column("progress", width=240, anchor="center")
        self.task_tree.column("speed", width=100, anchor="center")
        self.task_tree.column("error", width=300)
        self.task_tree.column("action", width=90, anchor="center")

        task_scroll = ttk.Scrollbar(task_container, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=task_scroll.set)
        self.task_tree.pack(side="left", fill="both", expand=True)
        task_scroll.pack(side="right", fill="y")
        self.task_tree.bind("<Button-1>", self.on_task_tree_click, add="+")

        self.status_bar = ttk.Frame(self, padding=10, relief="sunken")
        self.status_bar.pack(fill="x", pady=(6, 0))
        self.status_title = ttk.Label(self.status_bar, text="准备就绪", font=("Segoe UI", 9, "bold"))
        self.status_title.pack(anchor="w")
        self.progress = ttk.Progressbar(self.status_bar, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", pady=5)
        self.status_path = ttk.Label(self.status_bar, text="支持多选下载、任务终止、失败重试", foreground="gray")
        self.status_path.pack(anchor="w")
        ttk.Label(self.status_bar, text="By: PuddingKC", font=("Segoe UI", 8), foreground="#bbbbbb").pack(side="right")

    def show_about(self):
        about_text = (
            "VRChat VRCA Downloader v1.4\n"
            "\n作者: PuddingKC & Sakura1618\n"
            "GitHub: github.com/Null-K/VRChatVRCADownloader\n"
            "GitHub: github.com/AssetRipper/AssetRipper\n"
            "\n免责声明\n"
            "本工具为第三方辅助工具，仅用于个人账号模型资产的下载。\n"
            "所有数据请求均通过 VRChat 官方公开 API 接口完成，\n"
            "本工具不会修改、伪造或干预任何服务器数据。\n"
            "\n本工具:\n"
            "不提供、也不支持任何形式的破解、绕过权限或非法访问行为\n"
            "不包含对 VRChat 客户端、服务器或资源的逆向、注入或篡改\n"
            "不存储、不上传、不分享用户的账号信息或 Cookie\n"
        )
        messagebox.showinfo("关于", about_text)

    def open_embedded_login(self):
        if self.cookie_helper_process and self.cookie_helper_process.poll() is None:
            messagebox.showinfo("提示", "内置浏览器已打开，请先完成登录")
            return

        file_fd, output_path = tempfile.mkstemp(prefix="vrc_cookie_", suffix=".json")
        os.close(file_fd)
        command = build_cookie_helper_command(
            is_frozen=bool(getattr(sys, "frozen", False)),
            executable_path=sys.executable,
            script_path=os.path.abspath(sys.argv[0]),
            output_path=output_path,
        )
        try:
            self.cookie_helper_process = subprocess.Popen(command)
            self.cookie_helper_output = output_path
            self.cookie_helper_deadline = time.time() + 300
            self.status_path.config(text="内置浏览器已启动，请登录后等待自动抓取 auth")
            self.after(800, self._poll_cookie_helper_result)
        except Exception as exc:
            messagebox.showerror("启动失败", f"内置浏览器启动失败: {exc}")
            try:
                os.remove(output_path)
            except OSError:
                pass

    def _poll_cookie_helper_result(self):
        process = self.cookie_helper_process
        output_path = self.cookie_helper_output

        if output_path and os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as file_handle:
                    payload = json.load(file_handle)
                auth_value = payload.get("auth")
                if auth_value:
                    self.cookie_var.set(f"auth={auth_value};")
                    self.status_path.config(text="已从内置浏览器自动抓取 auth")
                    self._cleanup_cookie_helper()
                    return
            except Exception:
                pass

        if process and process.poll() is not None:
            self.status_path.config(text="内置浏览器已关闭，未捕获到 auth")
            self._cleanup_cookie_helper()
            return

        if time.time() > self.cookie_helper_deadline:
            if process and process.poll() is None:
                process.terminate()
            self.status_path.config(text="内置浏览器抓取超时，请重试")
            self._cleanup_cookie_helper()
            return

        self.after(800, self._poll_cookie_helper_result)

    def _cleanup_cookie_helper(self):
        path = self.cookie_helper_output
        self.cookie_helper_process = None
        self.cookie_helper_output = ""
        self.cookie_helper_deadline = 0.0
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _clear_runtime_cache(self):
        cache_dirs = set()
        cache_dirs.add(os.path.abspath(os.path.join(AVATAR_CACHE_DIR, os.pardir)))
        cache_dirs.add(os.path.abspath(os.path.join(os.getcwd(), "cache")))
        cache_dirs.add(os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), "cache")))
        cache_dirs.add(os.path.abspath(os.path.join(os.path.dirname(sys.executable), "cache")))
        for cache_dir in cache_dirs:
            delete_dir_with_retry(cache_dir)

    def on_app_close(self):
        process = self.cookie_helper_process
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass
        self._cleanup_cookie_helper()
        try:
            self.thumb_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self._clear_runtime_cache()
        self.destroy()

    def test_proxy(self):
        try:
            proxies = self.get_proxy_config()
        except ValueError as exc:
            messagebox.showwarning("代理配置错误", str(exc))
            return

        if not proxies:
            messagebox.showinfo("代理测试", "当前未配置代理地址")
            return

        self.status_title.config(text="正在测试代理连通性...")

        def task():
            try:
                status_code, elapsed_ms = VRChatAPI.test_proxy_connectivity(proxies)
                self.after(
                    0,
                    messagebox.showinfo,
                    "代理测试成功",
                    f"代理可用\nHTTP: {status_code}\n延迟: {elapsed_ms} ms",
                )
                self.after(0, self.status_title.config, {"text": f"代理可用，延迟 {elapsed_ms} ms"})
            except Exception as exc:
                self.after(0, messagebox.showerror, "代理测试失败", str(exc))
                self.after(0, self.status_title.config, {"text": "代理测试失败"})

        threading.Thread(target=task, daemon=True).start()

    def load_files(self):
        cookie = VRChatAPI.format_cookie(self.cookie_var.get())
        if not cookie:
            messagebox.showwarning("获取失败", "请输入有效的 Cookie (auth_...)")
            return
        try:
            proxies = self.get_proxy_config()
        except ValueError as exc:
            messagebox.showwarning("代理配置错误", str(exc))
            return

        self.btn_refresh.config(state="disabled")
        self.status_title.config(text="正在连接 VRChat 服务器...")

        def task():
            try:
                raw_data = VRChatAPI.fetch_all_files(
                    cookie,
                    lambda text: self.after(0, self.status_title.config, {"text": text}),
                    proxies=proxies,
                )
                avatars = []
                for file_item in raw_data:
                    if file_item.get("extension") != ".vrca" or not file_item.get("versions"):
                        continue
                    latest = sorted(file_item["versions"], key=lambda item: item["version"])[-1]
                    file_url = latest.get("file", {}).get("url")
                    if not file_url:
                        continue
                    avatars.append(
                        {
                            "name": file_item.get("name", "Unknown"),
                            "version": latest.get("version"),
                            "created_at": latest.get("created_at"),
                            "file_id": file_item.get("id", "unknown"),
                            "url": file_url,
                            "image_url": extract_avatar_image_url(file_item, latest),
                        }
                    )

                avatars.sort(key=lambda item: item["created_at"], reverse=True)
                self.all_avatars = avatars
                self.after(0, self.render_list)
                self.after(0, self.status_title.config, {"text": f"基础同步完成: {len(avatars)} 个资源，正在加载头像图..."})
                self._preload_avatar_thumbnails(avatars)
                self._fetch_avatar_image_map_async(cookie, proxies)
            except Exception as exc:
                self.after(0, messagebox.showerror, "获取失败", str(exc))
                self.after(0, self.status_title.config, {"text": "准备就绪"})
            finally:
                self.after(0, self.btn_refresh.config, {"state": "normal"})

        threading.Thread(target=task, daemon=True).start()

    def render_list(self):
        previous_selected = self._selected_avatars(include_checked=False)
        preferred_file_id = ""
        if previous_selected:
            preferred_file_id = str(previous_selected[0].get("file_id") or "")

        for row in self.tree.get_children():
            self.tree.delete(row)
        self.avatar_lookup = {}
        self.checked_rows = set()

        search_key = self.search_var.get().lower().strip()
        row_id = 0
        first_row_id = ""
        restored_row_id = ""
        for avatar in self.all_avatars:
            avatar_name = str(avatar.get("name") or "").strip() or "Unknown"
            if search_key and search_key not in avatar_name.lower():
                continue
            avatar_date = str(avatar.get("created_at") or "").strip()
            if not avatar_date:
                continue
            try:
                date_obj = datetime.fromisoformat(avatar_date.replace("Z", "+00:00"))
            except ValueError:
                continue
            row_key = str(row_id)
            self.avatar_lookup[row_key] = avatar
            self.tree.insert(
                "",
                "end",
                iid=row_key,
                text="",
                image=self.avatar_placeholder,
                values=(
                    CHECK_OFF_TEXT,
                    avatar_name,
                    f"v{avatar['version']}",
                    date_obj.strftime("%Y-%m-%d %H:%M"),
                    "[ 下载 ]",
                ),
            )
            if not first_row_id:
                first_row_id = row_key
            if preferred_file_id and str(avatar.get("file_id") or "") == preferred_file_id and not restored_row_id:
                restored_row_id = row_key
            row_id += 1

        target_row = restored_row_id or first_row_id
        if target_row and self.tree.exists(target_row):
            self.tree.selection_set(target_row)
            self.tree.focus(target_row)
            self.tree.see(target_row)
            self.on_avatar_selection_changed()
        else:
            self._set_preview_placeholder("未选择 Avatar", "")

    def on_tree_click_toggle_check(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#1":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.toggle_row_check(row_id)
        return "break"

    def toggle_row_check(self, row_id):
        checked = row_id not in self.checked_rows
        self._apply_row_check_state(row_id, checked)

    def select_all_rows(self):
        for row_id in self.tree.get_children():
            self._apply_row_check_state(row_id, True)

    def clear_all_checks(self):
        for row_id in list(self.checked_rows):
            if self.tree.exists(row_id):
                self._apply_row_check_state(row_id, False)
        self.checked_rows.clear()

    def _apply_row_check_state(self, row_id, checked):
        if not self.tree.exists(row_id):
            return
        if checked:
            self.checked_rows.add(row_id)
            self.tree.set(row_id, "check", CHECK_ON_TEXT)
            self.tree.item(row_id, tags=("checked",))
        else:
            self.checked_rows.discard(row_id)
            self.tree.set(row_id, "check", CHECK_OFF_TEXT)
            self.tree.item(row_id, tags=())

    def _create_placeholder_image(self):
        # Use a minimal single-pixel placeholder and let tree row height provide spacing.
        return tk.PhotoImage(width=1, height=1)

    def _fetch_avatar_image_map_async(self, cookie, proxies):
        def worker():
            try:
                avatar_rows = VRChatAPI.fetch_user_avatars(
                    cookie,
                    lambda text: self.after(0, self.status_title.config, {"text": text}),
                    proxies=proxies,
                )
                avatar_image_map = build_avatar_image_map(avatar_rows)
                self.after(0, self._apply_avatar_image_map, avatar_image_map)
            except Exception:
                self.after(0, self.status_title.config, {"text": "同步完成（头像图映射加载失败，不影响下载）"})

        threading.Thread(target=worker, daemon=True).start()

    def _apply_avatar_image_map(self, avatar_image_map):
        updated = []
        for avatar in self.all_avatars:
            if avatar.get("image_url"):
                continue
            file_id = avatar.get("file_id")
            if file_id in avatar_image_map:
                avatar["image_url"] = avatar_image_map[file_id]
                updated.append(avatar)
        if updated:
            self._preload_avatar_thumbnails(updated)
            self.status_title.config(text=f"同步完成: 找到 {len(self.all_avatars)} 个资源（已补充 {len(updated)} 个头像图）")
            self.on_avatar_selection_changed()
        else:
            self.status_title.config(text=f"同步完成: 找到 {len(self.all_avatars)} 个资源")

    def _preload_avatar_thumbnails(self, avatars):
        self.thumb_prefetch_generation += 1
        generation = self.thumb_prefetch_generation
        for avatar in avatars:
            self.thumb_pool.submit(self._prefetch_one_thumb, avatar, generation)

    def _prefetch_one_thumb(self, avatar, generation):
        if generation != self.thumb_prefetch_generation:
            return
        file_id = avatar.get("file_id") or ""
        image_url = avatar.get("image_url")
        if not image_url:
            return
        with self.avatar_cache_lock:
            if file_id in self.avatar_thumb_cache:
                return
        thumb = self._load_thumb_from_cache_or_network(file_id, image_url)
        if thumb is not None and generation == self.thumb_prefetch_generation:
            self.after(0, self._store_thumb_image, file_id, thumb)

    def _load_thumb_from_cache_or_network(self, file_id, image_url):
        cache_name = build_avatar_cache_filename(file_id, image_url)
        cache_path = os.path.join(AVATAR_CACHE_DIR, cache_name)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as file_handle:
                    data = file_handle.read()
                return self._decode_thumb_image(data)
            except OSError:
                pass

        try:
            headers = {"User-Agent": USER_AGENT, "Cookie": VRChatAPI.format_cookie(self.cookie_var.get())}
            proxies = self.get_proxy_config()
            response = requests.get(image_url, headers=headers, timeout=20, proxies=proxies)
            response.raise_for_status()
            data = response.content
            try:
                with open(cache_path, "wb") as file_handle:
                    file_handle.write(data)
            except OSError:
                pass
            return self._decode_thumb_image(data)
        except Exception:
            return None

    def _decode_thumb_image(self, data):
        if Image and ImageTk:
            try:
                image = Image.open(io.BytesIO(data)).convert("RGB")
                image.thumbnail(THUMB_SIZE)
                return ImageTk.PhotoImage(image)
            except Exception:
                return None
        return None

    def _store_thumb_image(self, file_id, thumb):
        with self.avatar_cache_lock:
            self.avatar_thumb_cache[file_id] = thumb
        for row_id, avatar in self.avatar_lookup.items():
            if avatar.get("file_id") == file_id and self.tree.exists(row_id):
                self.tree.item(row_id, image=thumb)

    def on_avatar_selection_changed(self):
        # Preview should always follow current row selection, not checked set.
        avatars = self._selected_avatars(include_checked=False)
        if not avatars:
            self._set_preview_placeholder("未选择 Avatar", "")
            return
        avatar = avatars[0]
        image_url = avatar.get("image_url")
        meta_text = f"{avatar['name']}\n版本: v{avatar['version']}"
        if not image_url:
            self._set_preview_placeholder("无可用预览图", meta_text)
            return
        self._load_preview_async(avatar, meta_text)

    def _set_preview_placeholder(self, title_text, meta_text):
        self.preview_photo = None
        self.preview_canvas.itemconfigure(self.preview_image_item, image="")
        self.preview_canvas.itemconfigure(self.preview_text_item, text=title_text, state="normal")
        self.preview_meta.configure(text=meta_text)

    def _load_preview_async(self, avatar, meta_text):
        image_url = avatar.get("image_url")
        if image_url in self.preview_cache:
            self.preview_photo = self.preview_cache[image_url]
            self.preview_canvas.itemconfigure(self.preview_image_item, image=self.preview_photo)
            self.preview_canvas.itemconfigure(self.preview_text_item, text="", state="hidden")
            self.preview_meta.configure(text=meta_text)
            return

        self.preview_request_id += 1
        request_id = self.preview_request_id
        file_id = avatar.get("file_id") or ""
        with self.avatar_cache_lock:
            quick_thumb = self.avatar_thumb_cache.get(file_id)
        if quick_thumb is not None:
            # Instant switch: show cached thumbnail first, then replace with full preview.
            self.preview_photo = quick_thumb
            self.preview_canvas.itemconfigure(self.preview_image_item, image=self.preview_photo)
            self.preview_canvas.itemconfigure(self.preview_text_item, text="", state="hidden")
            self.preview_meta.configure(text=meta_text)
        else:
            self._set_preview_placeholder("加载预览图中...", meta_text)

        def worker():
            try:
                headers = {"User-Agent": USER_AGENT, "Cookie": VRChatAPI.format_cookie(self.cookie_var.get())}
                proxies = self.get_proxy_config()
                response = requests.get(image_url, headers=headers, timeout=20, proxies=proxies)
                response.raise_for_status()
                image_obj = self._decode_image_bytes(response.content)
                if image_obj is None:
                    self.after(0, self._apply_preview_failure, request_id, meta_text, "预览图格式不受支持")
                    return
                self.after(0, self._apply_preview_success, request_id, image_url, image_obj, meta_text)
            except Exception:
                self.after(0, self._apply_preview_failure, request_id, meta_text, "预览图加载失败")

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _decode_image_bytes(data):
        if Image and ImageTk:
            try:
                image = Image.open(io.BytesIO(data)).convert("RGB")
                image.thumbnail(PREVIEW_IMAGE_SIZE)
                return ImageTk.PhotoImage(image)
            except Exception:
                return None
        try:
            encoded = base64.b64encode(data)
            return tk.PhotoImage(data=encoded)
        except Exception:
            return None

    def _apply_preview_success(self, request_id, image_url, image_obj, meta_text):
        if request_id != self.preview_request_id:
            return
        self.preview_cache[image_url] = image_obj
        self.preview_photo = image_obj
        self.preview_canvas.itemconfigure(self.preview_image_item, image=self.preview_photo)
        self.preview_canvas.itemconfigure(self.preview_text_item, text="", state="hidden")
        self.preview_meta.configure(text=meta_text)

    def _apply_preview_failure(self, request_id, meta_text, reason):
        if request_id != self.preview_request_id:
            return
        self._set_preview_placeholder(reason, meta_text)

    def _selected_avatars(self, include_checked=True):
        selected_rows = list(self.tree.selection())
        row_ids = []
        seen = set()
        for row_id in selected_rows:
            if row_id not in seen:
                seen.add(row_id)
                row_ids.append(row_id)
        if include_checked:
            for row_id in self.tree.get_children():
                if row_id in self.checked_rows and row_id not in seen:
                    seen.add(row_id)
                    row_ids.append(row_id)
        avatars = []
        for row_id in row_ids:
            avatar = self.avatar_lookup.get(row_id)
            if avatar:
                avatars.append(avatar)
        return avatars

    def start_download(self):
        avatars = self._selected_avatars(include_checked=False)
        if not avatars:
            return

        avatar = avatars[0]
        default_name = build_custom_filename(self.filename_template_var.get(), avatar)
        target = filedialog.asksaveasfilename(
            defaultextension=".vrca",
            filetypes=[("VRChat Avatar", "*.vrca")],
            initialfile=default_name,
        )
        if not target:
            return

        self.download_manager.add_task(avatar["name"], avatar["url"], avatar["version"], target)
        self.status_path.config(text=f"已加入任务: {target}")

    def queue_selected_downloads(self):
        avatars = self._selected_avatars(include_checked=True)
        if not avatars:
            messagebox.showinfo("提示", "请先在资源列表中选择至少一个模型")
            return

        output_dir = filedialog.askdirectory(title="选择批量下载目录")
        if not output_dir:
            return

        count = 0
        for avatar in avatars:
            filename = build_custom_filename(self.filename_template_var.get(), avatar)
            full_path = os.path.join(output_dir, filename)
            self.download_manager.add_task(avatar["name"], avatar["url"], avatar["version"], full_path)
            count += 1

        self.status_path.config(text=f"已加入 {count} 个下载任务，保存目录: {output_dir}")

    def terminate_selected_tasks(self):
        rows = self.task_tree.selection()
        if not rows:
            messagebox.showinfo("提示", "请先在任务列表中选择要终止的任务")
            return
        task_ids = set()
        for row_id in rows:
            try:
                task_ids.add(int(row_id))
            except ValueError:
                continue
        affected = self.download_manager.cancel_tasks(task_ids)
        self.status_path.config(text=f"已请求终止 {affected} 个任务")

    def terminate_all_tasks(self):
        affected = self.download_manager.cancel_all_tasks()
        if affected == 0:
            messagebox.showinfo("提示", "当前没有可终止的排队/下载中任务")
            return
        self.status_path.config(text=f"已一键终止 {affected} 个任务")

    def retry_failed_tasks(self):
        retried = self.download_manager.retry_failed_tasks()
        if retried == 0:
            messagebox.showinfo("提示", "当前没有可重试的失败/超时/终止任务")
            return
        self.status_path.config(text=f"已重试 {retried} 个任务")

    def clear_finished_tasks(self):
        self.download_manager.clear_finished_tasks()
        for row in self.task_tree.get_children():
            self.task_tree.delete(row)
        self.task_rows = {}
        for snapshot in self.download_manager.get_snapshots():
            self.on_task_updated(snapshot)
        self._refresh_overall_progress()

    def on_task_success(self, task_snapshot):
        self.status_path.config(text=f"完成: {task_snapshot['save_path']}")
        if self.auto_rip_var.get():
            self._trigger_assetripper(task_snapshot["save_path"], task_snapshot["name"])

    def on_task_updated(self, task_snapshot):
        task_id = str(task_snapshot["task_id"])
        self.task_rows[task_id] = task_snapshot

        status_label = self.STATUS_LABELS.get(task_snapshot["status"], task_snapshot["status"])
        progress_text = f"{format_bytes(task_snapshot['downloaded'])} / {format_bytes(task_snapshot['total'])}"
        speed_text = "-"
        if task_snapshot["status"] == "running":
            speed_text = f"{format_bytes(task_snapshot['speed'])}/s"
        elif task_snapshot["status"] == "success":
            speed_text = "完成"

        error_text = (task_snapshot.get("error") or "").replace("\n", " ")
        if len(error_text) > 80:
            error_text = f"{error_text[:77]}..."

        values = (
            task_snapshot["name"],
            status_label,
            progress_text,
            speed_text,
            error_text,
            "[ 终止 ]" if task_snapshot["status"] in {"queued", "running"} else "-",
        )
        if self.task_tree.exists(task_id):
            self.task_tree.item(task_id, values=values)
        else:
            self.task_tree.insert("", "end", iid=task_id, values=values)
        self._refresh_overall_progress()

    def on_task_tree_click(self, event):
        region = self.task_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.task_tree.identify_column(event.x)
        if col != "#6":
            return
        row_id = self.task_tree.identify_row(event.y)
        if not row_id:
            return
        snapshot = self.task_rows.get(row_id, {})
        if snapshot.get("status") not in {"queued", "running"}:
            return "break"
        affected = self.download_manager.cancel_tasks({int(row_id)})
        if affected > 0:
            self.status_path.config(text=f"已终止任务: {snapshot.get('name', row_id)}")
        return "break"

    def _refresh_overall_progress(self):
        snapshots = self.download_manager.get_snapshots()
        if not snapshots:
            self.progress.config(value=0)
            self.status_title.config(text="准备就绪")
            return

        percent, downloaded, total = compute_aggregate_progress(snapshots)
        status_counter = {
            "queued": 0,
            "running": 0,
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "cancelled": 0,
        }
        for snapshot in snapshots:
            status_counter[snapshot["status"]] = status_counter.get(snapshot["status"], 0) + 1

        self.progress.config(value=percent)
        self.status_title.config(
            text=(
                f"总任务 {len(snapshots)} | 运行 {status_counter['running']} | 排队 {status_counter['queued']} | "
                f"成功 {status_counter['success']} | 失败 {status_counter['failed'] + status_counter['timeout']} | "
                f"终止 {status_counter['cancelled']} | 总进度 {percent:.2f}% "
                f"({format_bytes(downloaded)} / {format_bytes(total)})"
            )
        )

    def _sort_column(self, col, reverse):
        items = [(self.tree.set(key, col), key) for key in self.tree.get_children("")]
        items.sort(reverse=reverse)
        for index, (_, key) in enumerate(items):
            self.tree.move(key, "", index)
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    @staticmethod
    def _validate_port(port_text):
        if port_text == "":
            return True
        return port_text.isdigit() and len(port_text) <= 5

    def get_proxy_config(self):
        return build_proxy_dict(self.proxy_var.get())

    def _trigger_assetripper(self, vrca_path, name):
        output_dir = os.path.splitext(vrca_path)[0]
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        current_port = self.rip_port_var.get().strip()
        if not current_port:
            self.status_path.config(text=f"{name} 下载完成, 未填写 AssetRipper 端口")
            return

        ripper_api = f"http://127.0.0.1:{current_port}"

        def api_task():
            self.after(0, self.status_title.config, {"text": "正在向 AssetRipper 发送请求..."})
            try:
                try:
                    requests.post(f"{ripper_api}/Reset", timeout=2)
                except requests.exceptions.RequestException:
                    pass

                requests.post(f"{ripper_api}/LoadFile", data={"path": vrca_path}, timeout=20)
                response = requests.post(
                    f"{ripper_api}/Export/UnityProject",
                    data={"path": output_dir},
                    timeout=30,
                )

                if 200 <= response.status_code < 400:
                    self.after(
                        0,
                        self.status_path.config,
                        {"text": f"{name} 下载完成，AssetRipper 导出请求已发送: {output_dir}"},
                    )
                else:
                    self.after(
                        0,
                        self.status_path.config,
                        {
                            "text": (
                                f"{name} 下载完成，AssetRipper 响应异常({response.status_code})，"
                                "请检查 AssetRipper 控制台"
                            )
                        },
                    )
            except requests.exceptions.ConnectionError:
                self.after(0, self.status_path.config, {"text": f"{name} 下载完成，AssetRipper 未运行"})
            except Exception as exc:
                self.after(0, messagebox.showerror, "AssetRipper 调用错误", str(exc))

        threading.Thread(target=api_task, daemon=True).start()


if __name__ == "__main__":
    if "--cookie-helper" in sys.argv:
        index = sys.argv.index("--cookie-helper")
        output = ""
        if index + 1 < len(sys.argv):
            output = sys.argv[index + 1]
        if not output:
            output = os.path.join(tempfile.gettempdir(), "vrc_cookie_helper.json")
        raise SystemExit(run_cookie_helper_mode(output))

    app = App()
    style = ttk.Style()
    style.configure("Treeview", rowheight=68, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
    app.mainloop()
