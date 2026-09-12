# project-reader

> 一个基于 AI 的项目阅读与分析交互工具。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Model](https://img.shields.io/badge/Model-DeepSeek-purple.svg)](https://api.deepseek.com)

## 📖 简介

**project-reader** 是一个命令行交互式 AI 助手，专门用于阅读、分析和理解项目源码与文档。它通过 OpenAI 兼容接口调用 DeepSeek 大模型，并配备一系列文件系统工具，让 AI 能够直接"看到"你的项目文件并做出智能回答。

## ✨ 核心特性

- 🔧 **9 个内置工具** — 让 AI 能够浏览目录、读取文件、搜索内容、获取文件信息等
- 🧠 **深度推理** — 支持思考链 (Chain of Thought)，推理过程可视化，思考强度可切换（low / high / max）
- 🛡️ **安全沙箱** — 路径遍历、glob 逃逸与符号链接防护，操作限制在项目根目录内；二进制文件自动识别
- 🎨 **富文本终端** — 使用 Rich 库渲染彩色输出，思考/回答/工具调用分区展示
- 📝 **会话日志** — 每次对话自动记录到 `log/` 目录，便于回溯
- 📚 **长对话摘要** — 上下文超限时自动摘要压缩，保留关键信息
- ⚙️ **灵活配置** — 模型、工作区、上下文上限等参数支持配置持久化与会话内切换；配置模型不可用时自动回退到可用模型
- 💬 **交互式命令** — 10 个会话命令（`/new`、`/model`、`/workspace` 等），支持 Tab 自动补全
- 🌐 **编码兼容** — 自动探测文件编码（UTF-8、UTF-8 BOM 与 UTF-16），告别乱码烦恼

## 🚀 快速开始

### 前置要求

- Python 3.10+
- DeepSeek API Key（[申请地址](https://platform.deepseek.com/)）

### 安装步骤

```bash
# 1. 克隆仓库
git clone <your-repo-url> project-reader
cd project-reader

# 2. 安装依赖
pip install -r requirements.txt
```

### 配置

编辑 `.env` 文件，填入你的 API Key：

```env
DEEPSEEK_API_KEY=your-api-key-here
```

其他运行参数可编辑同目录的 `reader.config`（启动时自动加载，修改后自动保存）：

```json
{
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "api_key": "DEEPSEEK_API_KEY",
    "reasoning_effort": "high",
    "limit": 750000,
    "last": 3,
    "summary": 8196,
    "work_space": "."
}
```

> 说明：
> - `api_key` 字段填写的是 API Key 的**环境变量名**，而不是密钥本身。
> - `reasoning_effort` 可选 `low` / `high` / `max`。
> - `limit`、`last`、`summary` 分别对应会话 token 上限、摘要保留最近轮数与摘要请求最大 token。

### 运行

```bash
# 在当前目录运行
python reader.py

# 指定分析的目标项目路径
python reader.py /path/to/target/project
```

不带参数运行时，程序使用 `reader.config` 中 `work_space` 指定的路径（默认为当前目录）。

启动后你将看到：

```
──────────────────── 项目路径 ────────────────────
项目路径: /path/to/your/project
──────────────────── 会话帮助 ────────────────────
  /help               返回该会话帮助。
  /new                创建新的会话。
  /repeat             重复上一次提问。
  /model [名称]       查看或设置模型。
  /effort [强度]      查看或设置思考强度。
  /workspace [路径]   查看或设置工作区。
  /limit [数值]       查看或设置会话token上限。
  /keep [数值]        查看或设置摘要保留最近轮数。
  /summary [数值]     查看或设置摘要请求最大token。
  /quit               退出程序。

────────────────────── 提问 ──────────────────────
>
```
在 `>` 提示符后输入你的问题即可。例如：

- "这个项目的入口文件是什么？"
- "帮我看看 src/ 目录下有哪些 Python 文件"
- "分析一下 main 函数的逻辑"
- "找到所有 TODO 注释"

## 📋 会话命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示帮助信息 |
| `/new` | 清空对话历史，开始新会话 |
| `/repeat` | 重复上一次提问 |
| `/model [名称]` | 查看或切换模型（不带参数时列出可用模型） |
| `/effort [强度]` | 查看或切换思考强度（low / high / max） |
| `/workspace [路径]` | 查看或切换工作区 |
| `/limit [数值]` | 查看或设置会话 token 上限 |
| `/keep [数值]` | 查看或设置摘要保留的最近轮数 |
| `/summary [数值]` | 查看或设置摘要请求的最大 token |
| `/quit` | 退出程序 |

支持 Tab 自动补全命令。

## 🛠️ AI 工具清单

AI 可调用的 9 个函数：

| 工具名 | 功能 | 关键参数 |
|---|---|---|
| `get_current_time` | 获取当前时间与时区 | — |
| `list_directory` | 列出目录内容 | `dir`, `start`, `n` |
| `read_text_file` | 读取文件指定行范围 | `file`, `start`, `n` |
| `search_files` | 按正则搜索目录下的文件内容 | `pattern`, `glob`, `dir`, `limit` |
| `search_content` | 在文件内搜索匹配行 | `pattern`, `file`, `start`, `n`, `limit`, `context` |
| `find_files` | 按 glob 模式查找文件 | `glob`, `dir`, `limit` |
| `get_path_info` | 获取文件/目录详情 | `path` |
| `get_project_root` | 获取项目根路径 | — |
| `get_self_path` | 获取 reader.py 自身路径 | — |

## 🎯 使用示例

```
> 这个项目是做什么的？

  （AI 会读取项目文件并分析回答）
  思考...
  ──────── 回答 ────────
  这是一个 Web 应用项目，主要功能包括...

> 找出所有定义路由的地方

  ──────── 工具 ────────
  search_files pattern:"@app.route|@router" ...
  （AI 搜索后整理结果返回）

> /model
  当前模型: deepseek-flash
  可用模型: [...]

> /workspace ../another-project
  切换项目路径: ...

> /new
  新建会话  （清空上下文，开始全新对话）
```

## 🔒 安全机制

1. **路径沙箱** — 所有文件操作限制在项目根目录内，绝对路径、`..` 遍历与符号链接逃逸会被拒绝
2. **二进制检测** — 自动检测文件是否为二进制，降低对非文本文件的操作概率
3. **编码容错** — 支持 UTF-8 BOM / UTF-16 / chardet 探测，失败时回退 UTF-8 + `replace` 策略，不会崩溃
4. **工具调用上限** — 单次对话最多 1024 轮工具调用，防止无限循环

## ⚠️ 注意事项

> **上传公开仓库前请删除 `.env` 中的 API Key！**
>
> 该项目已在 `.gitignore` 中排除了 `.env`、`log/`、`*.code-workspace`，但仍请在上传前确认。

## 📄 许可证

MIT License © 2026 Tony Chen Smith

详见 [LICENSE](./LICENSE) 文件。

## 👤 作者

**Tony Chen Smith**