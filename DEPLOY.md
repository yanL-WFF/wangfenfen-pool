# 部署「王粉粉选题池」到常驻服务器（长期稳定）

沙箱里分享的 `*.agentos-app.net` 链接依赖当前沙箱会话，沙箱休眠就会断开。要让它**长期稳定、任何时间都能打开**，需要把后端部署到真正的常驻服务器。下面是最省钱的方案：**Render 免费部署 + Turso 免费云端数据库**。

## 一、准备云端数据库（Turso，免费、永久持久、SQLite 兼容）

> 不接 Turso 也能跑（会用服务器本地 SQLite），但本地 SQLite 在免费实例重启后可能清空。接 Turso 后数据永不丢，且与本机互通。

1. 打开 https://turso.tech ，用 GitHub 登录。
2. 创建一个数据库（名字随便，如 `wff-pool`）。
3. 进入该数据库，复制：
   - **Database URL**：形如 `https://xxxx.turso.io`
   - 在 `Tokens` 里 **Generate token**，复制令牌（一长串）。
4. 把这两个值填到部署平台的环境变量：`TURSO_URL`、`TURSO_TOKEN`。

后端已内置 Turso 客户端（`turso.py`），检测到这两个环境变量就会自动用云端库，**无需改代码**。

## 二、一键部署到 Render

1. 把本目录推到你的 GitHub 仓库（需要包含：`server.py`、`turso.py`、`选题库.html`、`requirements.txt`、`render.yaml`）。
2. 打开 https://dashboard.render.com → **New** → **Blueprint** → 选择该仓库 → **Deploy**。
3. 在部署的 **Environment** 里添加环境变量：
   - `TURSO_URL` = 你复制的 Database URL
   - `TURSO_TOKEN` = 你复制的 Token
   - （`DATA_DIR` 和 `PYTHON_VERSION` 已在 render.yaml 里设好，不用管）
4. 部署完成后，Render 给你一个固定域名（如 `https://wff-topic-pool.onrender.com`），**这就是长期稳定的地址**。

## 三、手机当 App 用

用手机浏览器打开上面的固定域名 → 点分享 → **添加到主屏幕** → 主屏出现「选题池」图标，点开即全屏 App。

## 四、本地自测

```bash
pip install -r requirements.txt
python3 server.py            # 默认 http://localhost:3001
# 或接 Turso 自测：
TURSO_URL=https://xxxx.turso.io TURSO_TOKEN=xxxx python3 server.py
```

## 说明

- 免费 Render 实例在 15 分钟无访问后会休眠，下次访问约 30 秒冷启动；接了 Turso 数据依然在云上，不丢。
- 想要完全不休眠：把 `render.yaml` 里的 `plan` 改成 `starter`（付费，约 $7/月），或使用任意常驻 VPS（同理部署）。
- 不要把 `sync.db` 提交到 Git（那是本地数据文件）。
