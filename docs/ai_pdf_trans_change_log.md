# AI_PDF_Trans 当前变更记录

## 近期修复重点

### 1. TeX 数学包装收口
- 文件：`src/core/tex_generator.py`
- 处理：
  - `_sanitize_math_tex()` 先剥离 `\begin{equation}`、`\[...\]`、`$$...$$`、`\(...\)` 等外层数学包装。
  - `_format_equation()` 不再额外加 `$...$`，避免生成层与模板层重复包装。
- 目的：修复 `Display math should end with $$`。

### 2. 字体族名与字体文件路径分离
- 文件：`src/utils/font_utils.py`
- 处理：
  - 按语言选择字体候选列表。
  - 对 TeX 提供字体族名，对文件系统只返回正斜杠路径。
  - 中文回退字体统一为 `SimSun`。
- 目的：避免把 Windows 字体路径直接写进 TeX，减少 `C:/WINDOWS/Fonts \simsun.ttc` 类 warning。

### 3. 模板前导区补齐数学算子
- 文件：
  - `templates/general.tex.j2`
  - `templates/academic.tex.j2`
  - `templates/report.tex.j2`
- 处理：
  - 添加 `\DeclareMathOperator*{\argmin}{arg\,min}`。
- 目的：避免 `\argmin` 触发 `Undefined control sequence`。

## 验证结果
- `My_Projects/AI_PDF_Trans/tests/test_tex_compiler.py`：通过
- `My_Projects/AI_PDF_Trans/tests/test_pipeline.py`：通过
- 最近一次 focused run：`39 passed`

## 后续要点
- 继续观察是否还有数学块在 `pdf_parser.py` 里被误判后进入生成层。
- 若再次出现字体 warning，优先检查 `tex_compiler.py` 的 fontconfig 输出，而不是直接往 TeX 层补路径处理。
