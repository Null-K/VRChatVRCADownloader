# VRChat VRCA Downloader
**VRChat VRCA Downloader** 是一款专为 VRChat 玩家设计的模型下载工具。  
通过 VRChat 官方 API 访问文件列表，帮助用户下载自己账号下的 Avatar 模型文件（.vrca），并可选配合第三方工具进行本地解包。

## 软件亮点
- 完全合规：使用 `Auth Cookie` 进行身份验证，不保存用户密码，所有请求均通过 VRChat 官方 API 接口完成。
- 模型同步：一键获取账号下所有已上传的 Avatar 列表，仅显示每个模型的最新版本，支持名称搜索。
- 自动解包：可在下载完成后，调用已安装的 AssetRipper 对文件进行解包（需用户自行配置）。

## 使用方法
1. 下载并运行 ``vrchat_vrca_downloader.exe``
2. 在顶部 Cookie 输入框中输入你的 ``Auth Cookie``
3. 点击 ``获取模型`` 按钮刷新列表

## 注意事项
- 使用自动解包功能前，需要用户自行下载、安装并运行 [AssetRipper](https://github.com/AssetRipper/AssetRipper/releases) 。

## 免责声明
本工具为第三方辅助工具，仅用于个人账号资产的管理与下载。  
所有数据请求均通过 VRChat 官方公开 API 接口完成。  
本工具不会修改、伪造或干预任何服务器数据。

本工具：
- 不提供、也不支持任何形式的破解、绕过权限或非法访问行为
- 不包含对 VRChat 客户端、服务器或资源的逆向、注入或篡改
- 不存储、不上传、不分享用户的账号信息或 Cookie
