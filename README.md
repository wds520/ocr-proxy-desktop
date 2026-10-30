# OCR 代理助手 · Windows 绿色便携版

如要把整套流程交给其他人或让 AI 帮忙配置，请直接使用 `docs/AI_SETUP_PROMPT.md` 中的提示词。

解压整个压缩包，双击 `OCRProxyDesktop.exe`。无需安装 Python、Node.js 或下载 OCR 模型，无需管理员权限，不写注册表，不添加开机启动。适用 Windows 10/11 x64。程序未做商业代码签名；公司若禁止运行未签名程序，仍须按公司的应用审批规则处理。

**必须保留 EXE 同级的 `_internal` 文件夹，不能单独拷贝 EXE。** 选择可写目录解压；不要直接在压缩包内运行。

## 它是做什么的

它在本机启动一个 OpenAI 兼容的本地 HTTP 服务（默认 `http://127.0.0.1:8318`）。把 Agent（WorkBuddy、opencode、zcode、Codex 等任何支持 OpenAI 兼容 `base_url` 的工具）的 `base_url` 指向这个本地地址后，匹配规则的模型请求中的图片会先在本机 OCR 成文字，再把文字交给上游大模型。它**不修改任何 Agent 的配置文件**；关闭应用即停止代理，不影响 Agent 原有配置。

## 第一次使用

1. 确认上游服务可用。默认上游是 `https://gateway.onewo.com/v1`，可在 **连接设置** 中修改。
2. 打开 `OCRProxyDesktop.exe`，在 **连接设置** 检查上游地址与本地 OCR 端口（默认 `8318`）。
3. **模型规则** 每行填一条，例如 `GC-*`、`glm-*`、`deepseek-*`。支持 `*`（任意字符）和 `?`（单个字符），忽略大小写。输入模型名称可预览是否匹配。保存设置。
4. 点击 **启用 OCR 代理**，然后把 Agent 的 OpenAI 兼容 `base_url` 指向 `http://127.0.0.1:8318`（端口以界面显示为准），重开 Agent 会话。
5. 在 **自动诊断** 点击“运行自动诊断”，检查设置、本地端口、上游 HTTP 与本地 OCR 实际识别。上游返回 401/403 表示 HTTP 服务已响应但需要鉴权，诊断不会读取密钥。
6. 代理运行期间请保持本应用打开；关闭代理或退出应用即停止中转。

## 各 Agent 怎么接

应用不改任何 Agent 配置，只需把 Agent 的 OpenAI 兼容 `base_url` 指向本地地址：

- WorkBuddy / opencode / zcode / Codex 等：在各自配置里把 OpenAI 兼容接口地址设为 `http://127.0.0.1:8318`（或界面显示的本地地址）。
- 使用完成后，把地址改回原上游即可；本应用不会自动修改或恢复这些配置。

## 模型规则的含义

```text
Agent → 本地 OCR 代理（127.0.0.1:8318）→ 上游服务（默认 gateway.onewo.com/v1）→ 模型
                  ├─ 匹配规则：图片 → 本机 OCR → 文本
                  └─ 未匹配：原始请求和图片直接转发至上游
```

模型列表控制**哪些模型的图片会转成文字**。这是 OCR API 中转工具，不是系统 HTTP / SOCKS 网络代理，不会更改系统网络代理设置。它不让上游自动具备图片理解能力：OCR 能读取截图文字、文档、报错；图表关系、颜色和画面细节应交给支持视觉的模型。

支持 OpenAI Responses API 的 `input_image` 和 Chat Completions 的 `image_url`；支持流式 SSE。图片优先使用 `data:image/...;base64,...`。文件 ID 不支持。远程图片 URL 默认不下载，遇到会明确报错；如有需要，在连接设置中启用后由本机下载识别。此请求不会携带上游 API 鉴权信息。

## 配置与数据

- 便携设置与滚动日志：EXE 同级 `data/`，首次运行自动创建；OCR 缓存只在内存，不保存图片和识别内容。
- `data/settings.json`：上游地址、本地端口、模型规则与远程图片开关。
- 修改上游、端口或模型规则前先关闭代理，再保存、重新启用。应用不自动启动代理，不驻留托盘，不安装系统服务。

## 自动诊断能证明什么

诊断会检查设置格式、便携目录写入、本地服务状态与端口冲突、上游 `/v1/models` 的 HTTP 响应、内置 OCR 模型的实际数字识别。可导出脱敏文本报告。

诊断不调用付费大模型，不读取 API 密钥。HTTP 可达与 OCR 通过不能证明上游账号鉴权、某模型权限、真实会话已成功。真实业务请求仍由客户端提供的认证头转发至上游。

## 开发与验证

源码在 `src/`。构建环境：Python 3.13 x64；依赖版本见 `requirements-runtime.txt` 和 `requirements-build.txt`。将依赖装入开发虚拟环境后运行 `build.ps1 -Python <python.exe>`。

可使用 EXE 内置的隔离自检：

```powershell
# 写报告到指定的可写路径；只使用临时测试配置与本地模拟上游，不改真实 Agent 配置。
& .\OCRProxyDesktop.exe --verify-bundle 'D:\Temp\ocr-check.json'
```

如输出路径含空格，请按 PowerShell 参数规则给路径加引号。源码与 EXE 的测试报告放在交付项目的 `verification-*.json`。依赖许可见 `licenses/` 与 `THIRD_PARTY_NOTICES.md`。