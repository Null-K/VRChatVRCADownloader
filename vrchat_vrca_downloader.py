import requests
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import time
import os

API_URL = "https://api.vrchat.cloud/api/1/files"
USER_AGENT = "VRChatVRCADownloader/1.2"

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
    def fetch_all_files(cookie, progress_callback):
        headers = {"User-Agent": USER_AGENT, "Cookie": cookie}
        offset, n = 0, 100
        all_files = []

        while True:
            progress_callback(f"正在加载文件列表: {offset}")
            try:
                r = requests.get(
                    API_URL,
                    headers=headers,
                    params={"n": n, "offset": offset},
                    timeout=15
                )
                if r.status_code == 401:
                    raise Exception("Cookie 无效或已过期")
                r.raise_for_status()
                
                data = r.json()
                if not data:
                    break
                all_files.extend(data)
                offset += n
                time.sleep(0.05) 
            except requests.exceptions.RequestException as e:
                raise Exception(f"网络请求失败: {e}")

        return all_files

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VRChat VRCA Downloader")
        self.geometry("1040x700")
        
        self.minsize(1025, 500)

        self.cookie_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.auto_rip_var = tk.BooleanVar(value=False)

        self.rip_port_var = tk.StringVar(value="")
        self.vcmd = (self.register(self._validate_port), '%P')

        self.all_avatars = []
        self.is_downloading = False
        
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Cookie:").pack(side="left")
        self.cookie_entry = ttk.Entry(top, textvariable=self.cookie_var, width=40, show="•")
        self.cookie_entry.pack(side="left", padx=5)

        self.btn_refresh = ttk.Button(top, text="获取模型", command=self.load_files)
        self.btn_refresh.pack(side="left", padx=5)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(top, text="搜索:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=25).pack(side="left", padx=5)
        self.search_var.trace_add("write", lambda *_: self.render_list())

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        self.check_rip = ttk.Checkbutton(top, text="下载后自动解包", variable=self.auto_rip_var)
        self.check_rip.pack(side="left", padx=5)

        ttk.Label(top, text="端口:").pack(side="left", padx=(5, 0))
        self.port_entry = ttk.Entry(
            top, 
            textvariable=self.rip_port_var, 
            width=8,
            validate="key", 
            validatecommand=self.vcmd
        )
        self.port_entry.pack(side="left", padx=5)

        ttk.Button(top, text="关于软件", width=10, command=self.show_about).pack(side="left", padx=5)

        list_container = ttk.Frame(self)
        list_container.pack(fill="both", expand=True, padx=10)

        columns = ("name", "version", "date", "size")
        self.tree = ttk.Treeview(list_container, columns=columns, show="headings", selectmode="browse")
        
        self.tree.heading("name", text="模型名称", command=lambda: self._sort_column("name", False))
        self.tree.heading("version", text="迭代版本")
        self.tree.heading("date", text="最后更新")
        self.tree.heading("size", text="操作")
        
        self.tree.column("name", width=400)
        self.tree.column("version", width=80, anchor="center")
        self.tree.column("date", width=150, anchor="center")
        self.tree.column("size", width=100, anchor="center")

        scroll = ttk.Scrollbar(list_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.start_download())

        self.status_bar = ttk.Frame(self, padding=10, relief="sunken")
        self.status_bar.pack(fill="x")
        
        self.status_title = ttk.Label(self.status_bar, text="准备就绪", font=("Segoe UI", 9, "bold"))
        self.status_title.pack(anchor="w")

        self.progress = ttk.Progressbar(self.status_bar, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", pady=5)

        self.status_path = ttk.Label(self.status_bar, text="双击列表项即可下载对应模型 vrca 文件", foreground="gray")
        self.status_path.pack(anchor="w")

        ttk.Label(self.status_bar, text="By: PuddingKC", font=("Segoe UI", 8), foreground="#bbbbbb").pack(side="right")

    def show_about(self):
        about_text = (
            "VRChat VRCA Downloader v1.2\n"

            "\n作者: PuddingKC\n"
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

    def load_files(self):
        cookie = VRChatAPI.format_cookie(self.cookie_var.get())
        if not cookie:
            messagebox.showwarning("获取失败", "请输入有效的 Cookie (auth_...)")
            return

        self.btn_refresh.config(state="disabled")
        self.status_title.config(text="正在连接 VRChat 服务器...")
        
        def task():
            try:
                raw_data = VRChatAPI.fetch_all_files(cookie, 
                    lambda s: self.after(0, self.status_title.config, {"text": s}))
                
                avatars = []
                for f in raw_data:
                    if f.get("extension") == ".vrca" and f.get("versions"):
                        latest_v = sorted(f["versions"], key=lambda x: x["version"])[-1]
                        if latest_v.get("file", {}).get("url"):
                            avatars.append({
                                "name": f.get("name", "Unknown"),
                                "version": latest_v.get("version"),
                                "created_at": latest_v.get("created_at"),
                                "url": latest_v["file"]["url"]
                            })
                
                avatars.sort(key=lambda x: x["created_at"], reverse=True)
                self.all_avatars = avatars
                self.after(0, self.render_list)
                self.after(0, self.status_title.config, {"text": f"同步完成: 找到 {len(avatars)} 个资源"})
            except Exception as e:
                self.after(0, messagebox.showerror, "获取失败", str(e))
            finally:
                self.after(0, self.btn_refresh.config, {"state": "normal"})

        threading.Thread(target=task, daemon=True).start()

    def render_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        search_key = self.search_var.get().lower()
        for a in self.all_avatars:
            if search_key and search_key not in a["name"].lower():
                continue
            
            dt = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
            self.tree.insert("", "end", values=(
                a["name"], 
                f"v{a['version']}", 
                dt.strftime("%Y-%m-%d %H:%M"),
                "[ 双击下载 ]"
            ), tags=(a["url"],))

    def start_download(self):
        if self.is_downloading:
            messagebox.showwarning("请稍候", "当前已有下载任务正在进行")
            return

        selected = self.tree.selection()
        if not selected:
            return
            
        item = self.tree.item(selected[0])
        name = item['values'][0]
        url = item['tags'][0]
        version = item['values'][1]

        path = filedialog.asksaveasfilename(
            defaultextension=".vrca",
            filetypes=[("VRChat Avatar", "*.vrca")],
            initialfile=f"{name}_{version}.vrca"
        )
        if not path:
            return

        self.is_downloading = True
        self.status_path.config(text=f"保存至: {path}")
        
        def task():
            try:
                headers = {"User-Agent": USER_AGENT, "Cookie": VRChatAPI.format_cookie(self.cookie_var.get())}
                with requests.get(url, headers=headers, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    
                    self.after(0, self.status_title.config, {"text": f"正在下载: {name}"})
                    
                    downloaded = 0
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size:
                                    percent = (downloaded / total_size) * 100
                                    self.after(0, self.progress.config, {"value": percent})

                if self.auto_rip_var.get():
                    self._trigger_assetripper(path, name)
                else:
                    self.after(0, messagebox.showinfo, "下载成功", f"{name} 下载完成")
            except Exception as e:
                self.after(0, messagebox.showerror, "下载失败", str(e))
            finally:
                self.is_downloading = False
                self.after(0, self.progress.config, {"value": 0})
                self.after(0, self.status_title.config, {"text": "准备就绪"})

        threading.Thread(target=task, daemon=True).start()

    def _sort_column(self, col, reverse):
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    def _validate_port(self, P):
        if P == "": return True
        return P.isdigit() and len(P) <= 5

    def _trigger_assetripper(self, vrca_path, name):
        output_dir = os.path.splitext(vrca_path)[0] 
        if not os.path.exists(output_dir): os.makedirs(output_dir)

        current_port = self.rip_port_var.get().strip()
        if not current_port:
            self.after(0, messagebox.showinfo, "下载成功", f"{name} 下载完成\n\nAssetRipper 软件端口未填写, 跳过自动解包")
            return

        dynamic_ripper_api = f"http://127.0.0.1:{current_port}"

        def api_task():
            self.after(0, self.status_title.config, {"text": "正在向 AssetRipper 发送解包请求..."})
            try:
                try: requests.post(f"{dynamic_ripper_api}/Reset", timeout=2)
                except: pass

                requests.post(f"{dynamic_ripper_api}/LoadFile", data={'path': vrca_path}, timeout=20)
                res = requests.post(f"{dynamic_ripper_api}/Export/UnityProject", data={'path': output_dir}, timeout=30)
                
                if 200 <= res.status_code < 400:
                    self.after(0, messagebox.showinfo, "下载成功", f"{name} 下载完成\n\n自动解包请求已发送, 目录: {output_dir}")
                else:
                    self.after(0, messagebox.showinfo, "下载成功", f"{name} 下载完成\n\n解包指令已发送但响应异常({res.status_code}), 请检查 AssetRipper 控制台")
            
            except requests.exceptions.ConnectionError:
                self.after(0, messagebox.showinfo, "下载成功", f"{name} 下载完成\n\nAssetRipper 未运行, 跳过自动解包")
            except Exception as e:
                self.after(0, messagebox.showerror, "解包错误", f"{e}")

        threading.Thread(target=api_task, daemon=True).start()

if __name__ == "__main__":
    app = App()
    style = ttk.Style()
    style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
    app.mainloop()