# AI PDF Trans
本项目由 AI 辅助编程。

AI 驱动的 PDF 教材翻译工具。将英文 PDF 教材完整翻译为中文 PDF，保持原有排版、数学公式和图表。

注意：AI翻译排版等不可控，有可能会出现多次翻译效果不同的情况。

安卓远程：https://github.com/Hjdd14/ai-pdf-trans-apk
## 功能

- 基于 LLM Agent 的智能翻译，自动解析 PDF 结构
- 支持多页 PDF 的完整翻译
- 数学公式保持 LaTeX 格式原样保留
- 图表/表格自动提取并在翻译后 PDF 中保持位置
- 支持多种 LLM API（OpenAI、Anthropic、DeepSeek 等，通过 LiteLLM）
- 中文 CJK 字体自动配置
- Flet 桌面 GUI 界面

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动应用

```bash
python main.py
```

### 3. 设置

1. 打开 **Settings** 标签页
2. 配置 API（服务商、模型名称、API Key、API URL）
3. 点击 **Download Tectonic** 下载 LaTeX 编译器
4. 设置源语言和目标语言

### 4. 翻译

1. 切换到 **Translate** 标签页
2. 选择源 PDF 文件
3. 选择输出路径
4. 点击开始翻译

## 系统要求

- **Python** >= 3.10
- **Windows** / **macOS** / **Linux**
- **CJK 字体**（目标语言为中文/日文/韩文时需要）
  - Windows：自动使用系统字体（宋体/MS Gothic/Malgun Gothic）
  - Linux：`sudo apt install fonts-noto-cjk`
  - macOS：系统自带
- **pdfimages**（可选，用于更精确的图片提取）
  - Windows：`conda install -c conda-forge poppler`
  - Linux：`sudo apt install poppler-utils`
  - macOS：`brew install poppler`
  - 如果未安装，将自动回退到 PyMuPDF 提取

## 打包为 exe

```bash
python build_exe.py
```

输出在 `dist/AI_PDF_Trans.exe`

## 依赖项

核心依赖（详见 `requirements.txt`）：
- `flet` — GUI 框架
- `litellm` — 多 LLM API 统一接口
- `PyMuPDF` — PDF 解析
- `Pillow` — 图片处理

## 项目结构

```
src/
├── agent_runtime/     # LLM Agent 执行引擎
│   ├── tools.py       # 15 个 PDF 工具函数
│   ├── loop.py        # ReAct Agent 循环
│   ├── prompts.py     # System Prompt
│   └── tool_defs.py   # 工具定义
├── core/
│   └── tex_compiler.py # Tectonic LaTeX 编译器
├── utils/             # 工具模块
├── pages/             # Flet UI 页面
├── models/            # 配置模型
└── locale.py          # 多语言支持
tests/                 # 测试（92 个）
```

## 配置

配置保存在 `%LOCALAPPDATA%/AI_PDF_Trans/config.json`（Windows）或 `~/.config/AI_PDF_Trans/config.json`（Linux/macOS）。

API Key 使用 DPAPI（Windows）或 base64 编码存储。

## 远程访问（移动端连接）

桌面端内置了 HTTP 服务器，手机 APP 可通过局域网或跨网络连接到桌面端投递翻译任务。

### 局域网连接（同一 WiFi）

1. 启动 AI PDF Trans
2. 进入 **Settings** → **Remote Access**
3. 开启 **Enable remote server access**
4. 手机打开 AI PDF Trans Mobile APP，扫描屏幕上显示的二维码
5. 连接成功后即可选择 PDF 开始翻译

### 跨网络连接（Tailscale — 推荐）

两台设备不在同一 WiFi 时（如电脑在家、手机在户外用 4G），通过 Tailscale 实现安全直连。

#### 设置步骤

##### 1. 电脑端安装 Tailscale

访问 [tailscale.com/download](https://tailscale.com/download) 下载 Windows 版本，安装后用 Google/GitHub/Microsoft 账号登录。

##### 2. 手机端安装 Tailscale

Google Play 搜索 "Tailscale" 安装，登录**同一个账号**。

##### 3. 确认连接

电脑上运行 `ipconfig`，应能看到一个 Tailscale 适配器，IP 地址为 `100.x.x.x`。手机上打开 Tailscale APP，应显示同一网段内的设备。

##### 4. 连接使用

- 启动桌面端 AI PDF Trans 的远程服务器
- 软件的设置页面会自动检测到 Tailscale IP 并显示独立的二维码
- 手机扫码或手动输入 `http://100.x.x.x:8654` 即可连接

> Tailscale 免费版支持最多 100 台设备、3 个用户，完全满足个人使用。

### 其他方案

- **ZeroTier**：功能类似 Tailscale，Android 端搜索 "ZeroTier One" 安装
- **VPN 同网**：手机连接同一 VPN 后也可直接通过 VPN 内网 IP 连接

## License

MIT
