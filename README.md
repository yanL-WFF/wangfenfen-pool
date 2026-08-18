# 王粉粉选题池 · 部署包

紫色酷感选题管理 App,支持:四大分类、链接 AI 识别、双栏同步、已用勾选、延伸内容、每周分析、手机 PWA 安装。

## 极简部署(3 步)

1. **注册 GitHub**:打开 https://github.com → Sign up(免费,需邮箱/手机验证)
2. **新建仓库**:右上角 + → New repository → 名字填 `wangfenfen-pool` → 点 Create(别勾任何选项)
3. **上传代码**:把本包所有文件**直接拖进**新建仓库的页面 → 写个标题 "init" → Commit
4. **连 Render**:打开 https://dashboard.render.com → New → Blueprint → 选你的仓库 → Deploy

## 让数据永久不丢(可选但推荐)

部署后在 Render 的 Environment 里加两个变量:
- `TURSO_URL` = 你的 Turso 数据库地址
- `TURSO_TOKEN` = 你的 Turso 令牌

(免费申请见 DEPLOY.md) 不配也能跑,只是数据存在 Render 临时盘。

详细图文见 DEPLOY.md。
