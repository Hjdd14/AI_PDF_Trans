# AI_PDF_Trans 项目与当前修改记录

## 项目概览

AI_PDF_Trans 是一个基于 Python 的 PDF 翻译与重排工具，核心目标是：

- 解析输入 PDF 的文本、图片、表格和公式
- 将正文翻译成目标语言
- 保留原始排版结构、图片位置和表格结构
- 将翻译结果重新生成 TeX，再用 Tectonic 编译为 PDF
- 对数学公式、CJK 字体、Windows 路径、图片路径等做兼容处理

## 主要技术栈

- Python
- PyMuPDF
- Jinja2
- Tectonic / XeLaTeX / xeCJK / fontspec
- pytest

## 当前关注的问题

本轮持续修复的两个核心问题是：

1. `Display math should end with $$`
   - 这是数学内容在解析、生成、模板渲染链路中被重复包装导致的。
2. `warning: accessing absolute path C:/WINDOWS/Fonts \simsun.ttc`
   - 这是 Windows 字体目录解析链路仍然暴露给 Tectonic/fontconfig 导致的 warning。

## 已完成的修改

### 1) 字体选择逻辑收敛

文件：`src/utils/font_utils.py`

已做的修改：

- 按语言维护字体候选列表：
  - 中文：`SimsunExtG.ttf`、`simsun.ttc`、`simsunb.ttf`
  - 日文：`msgothic.ttc`、`meiryo.ttc`、`YuMincho.ttc`
  - 韩文：`malgun.ttf`、`batang.ttc`
- 使用 `Path("C:/Windows/Fonts")` 统一管理 Windows 字体目录
- 通过真实文件存在性判断选用哪个字体
- 对外返回：
  - 字体族名：用于 `\setCJKmainfont{...}`
  - 字体文件路径：仅用于 fontconfig / 存在性检查
- 所有路径输出统一转为正斜杠 `/`

效果：

- 避免把不存在的字体族名写进 TeX
- 减少因字体文件路径拼接不规范导致的问题
- 让 CJK 字体选择更稳定、更可回退

### 2) 数学包装收口

文件：`src/core/tex_generator.py`

已做的修改：

- 引入更严格的数学内容剥壳逻辑
- `_sanitize_math_tex()` 现在会先移除：
  - `$...$`
  - `$$...$$`
  - `\[...\]`
  - `\(...\)`
  - `\begin{equation}...\end{equation}`
  - `\begin{align}...\end{align}`
  - `\begin{eqnarray}...\end{eqnarray}`
- `_format_equation()` 不再主动追加新的 `$...$` 包裹
- 数学的最终 display 包装交给模板统一完成

效果：

- 避免公式在 generator 和 template 两层同时包裹
- 直接针对 `Display math should end with $$` 这个错误根因

### 3) 模板中统一定义数学算子

文件：

- `templates/general.tex.j2`
- `templates/academic.tex.j2`
- `templates/report.tex.j2`

已做的修改：

- 在模板前导区加入：
  - `\DeclareMathOperator*{\argmin}{arg\,min}`

效果：

- 解决 `\argmin` 未定义导致的 `Undefined control sequence`
- 让公共数学算子在所有模板中可用

### 4) 编译与字体配置核对

文件：`src/core/tex_compiler.py`

当前逻辑：

- 生成 `fonts.conf`
- 把 Windows 字体目录写成正斜杠路径
- 使用 fontconfig 给 Tectonic 提供系统字体目录

现状判断：

- `C:/WINDOWS/Fonts \simsun.ttc` 更像是 Tectonic/fontconfig 的系统字体解析 warning
- 不是 TeX 源码里直接写入了反斜杠路径

## 已验证的测试结果

当前已经跑过并通过的测试：

- `My_Projects/AI_PDF_Trans/tests/test_tex_compiler.py`
- `My_Projects/AI_PDF_Trans/tests/test_pipeline.py`

结果：

- `39 passed`

## 当前代码层面的结论

### 关于 `Display math should end with $$`

根因基本明确：

- PDF 解析层会识别 equation-like 内容
- generator 层之前会对公式做二次包装
- 模板层也会继续包 display math

目前已经把“generator 再包一层”的行为去掉，数学最终由模板层统一渲染。

### 关于 Windows 字体 warning

当前判断是：

- 不是 `font_utils.py` 把反斜杠路径直接塞进 TeX
- 而是 Tectonic / fontconfig 在解析 Windows 系统字体目录时仍会输出 warning
- 这种 warning 目前不一定影响编译成功，但说明字体链路仍依赖本机字体目录

## 相关文件索引

- [src/utils/font_utils.py](../src/utils/font_utils.py)
- [src/core/tex_generator.py](../src/core/tex_generator.py)
- [src/core/tex_compiler.py](../src/core/tex_compiler.py)
- [templates/general.tex.j2](../templates/general.tex.j2)
- [templates/academic.tex.j2](../templates/academic.tex.j2)
- [templates/report.tex.j2](../templates/report.tex.j2)
- [tests/test_tex_compiler.py](../tests/test_tex_compiler.py)
- [tests/test_pipeline.py](../tests/test_pipeline.py)
- [src/core/pdf_parser.py](../src/core/pdf_parser.py)

## 后续建议

如果继续收敛，还可以继续做两件事：

1. 进一步收紧 `src/core/pdf_parser.py` 的 equation 识别规则，减少误判。
2. 对 `last_failed_output.tex` 的内容继续回溯，确认是否还有任何数学片段在进入模板前已经带有 display 包装。
