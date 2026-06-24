# Git 自动化脚本

> 仓库: `https://github.com/xianganh/stock-chip-quant`
> 分支: `master`
> 认证: SSH (key 已配置在 `~/.ssh/id_ed25519`)

## 📁 脚本清单

| 脚本 | 用途 | 何时使用 |
|------|------|---------|
| `push.bat` / `push.ps1` | 提交并推送到 GitHub | 改完代码后 |
| `pull.bat` / `pull.ps1` | 从 GitHub 拉取最新 | 切换电脑前 / 多人协作时 |
| `status.bat` / `status.ps1` | 查看仓库状态 | 任何时候 |
| `sync.bat` | 双向同步（pull + push） | 跨电脑切换 |
| `start.bat` | 启动 Flask 应用 | 运行项目 |

## 🚀 快速上手

### 1. 推送本地变更

```bash
# CMD
push.bat
push.bat "feat: 添加新的算法指标"

# PowerShell
.\push.ps1
.\push.ps1 -Message "feat: 添加新的算法指标"
.\push.ps1 -NoPush        # 只 commit 不 push
```

### 2. 拉取远端更新

```bash
# CMD
pull.bat                   # 默认 fast-forward only
pull.bat --rebase          # 本地有提交时变基合并
pull.bat --force           # 强制重置 (危险!)

# PowerShell
.\pull.ps1                 # 默认 fast-forward only
.\pull.ps1 -Rebase         # 变基模式
.\pull.ps1 -Force          # 强制重置 (危险!)
```

### 3. 查看状态

```bash
status.bat
.\status.ps1
```

输出示例：
```
=== [1/4] Branch ===
master

=== [2/4] Status ===
## master...origin/master

=== [3/4] Last 5 commits (local) ===
c2c7e93 docs: 更新文档
...

=== [4/4] Sync status with remote ===
0  0
Format: ahead  behind
```

### 4. 双向同步

```bash
sync.bat                   # pull + push
sync.bat --no-push         # 只 pull（如果只想更新不想提交）
```

## 🛡️ 安全特性

| 脚本 | 安全措施 |
|------|---------|
| `push.bat` | 检查是否有变更，无变更跳过；显示 status 后再确认；push 后用 GitHub API 验证 |
| `pull.bat --force` | 要求输入 `YES` 才执行；明确警告会丢失本地未提交变更 |
| `pull.bat` | 优先 ff-only，失败时给出 rebase/force 选项建议 |
| `sync.bat` | pull 失败时中止；不会强制覆盖 |

## 🔧 高级用法

### 跨电脑切换工作流

**电脑 A（先下班的电脑）**:
```bash
status.bat                 # 确认本地状态
sync.bat                   # 推送到 GitHub
```

**电脑 B（接着工作的电脑）**:
```bash
pull.bat                   # 拉取最新代码
# 开始工作...
push.bat                   # 改完后推送
```

### 多人协作场景

电脑 A:
```bash
push.bat "feat: 添加锁仓算法"
```

电脑 B（要拉取新功能）:
```bash
status.bat                 # 查看远程有新提交
pull.bat                   # 拉取
```

电脑 B 也有本地修改时:
```bash
pull.bat --rebase          # 变基合并
# 解决冲突（如有）后：
push.bat
```

### 误操作恢复

**撤销最后一次 commit（保留变更）**:
```bash
git reset --soft HEAD~1
```

**撤销最后一次 commit（丢弃变更）** ⚠️:
```bash
git reset --hard HEAD~1
```

**彻底同步到远程（危险）**:
```bash
pull.bat --force
```

## 📋 脚本约定

### PortableGit 路径

所有脚本统一使用：
```
C:\Users\xanhe\Tools\PortableGit\
```

如需修改，全局替换脚本中的 `C:\Users\xanhe\Tools\PortableGit` 即可。

### 默认配置

| 配置项 | 值 |
|--------|---|
| 分支 | `master` |
| 远程 | `origin` |
| 提交消息前缀 | `update:` / `sync:` |
| 错误退出码 | `1` |

### 脚本风格

- **BAT**: 使用 `@echo off` + `setlocal enabledelayedexpansion`，适合 cmd.exe
- **PS1**: 使用 `param()` + 颜色输出，适合 PowerShell（更易读）
- 两者功能等价，可按偏好选用

## 🔍 故障排查

### "fatal: not a git repository"

**原因**: 项目未初始化为 git 仓库

**解决**:
```bash
git init
git remote add origin https://github.com/xianganh/stock-chip-quant.git
# 或使用 SSH
git remote add origin git@github.com:xianganh/stock-chip-quant.git
```

### "Permission denied (publickey)"

**原因**: SSH key 未配置或未添加到 GitHub

**解决**:
1. 检查 `~/.ssh/id_ed25519` 是否存在
2. 将公钥 `~/.ssh/id_ed25519.pub` 添加到 GitHub Settings → SSH and GPG keys
3. 测试: `ssh -T git@github.com`

### "Could not resolve host: github.com"

**原因**: 网络问题

**解决**: 检查网络连接，或配置代理：
```bash
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
```

### "Your branch is ahead by X commits"

**说明**: 本地有未推送的提交

**解决**: `push.bat` 或 `git push origin master`

### "Your branch is behind by X commits"

**说明**: 远程有新提交，本地未拉取

**解决**: `pull.bat` 或 `git pull`

## 🔗 相关资源

- GitHub 仓库: https://github.com/xianganh/stock-chip-quant
- Git 官方文档: https://git-scm.com/doc
- SSH 配置指南: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
- 项目主页: [README.md](./README.md)

---

**最后更新**: 2026-06-24
**维护**: 自动生成，可按需调整