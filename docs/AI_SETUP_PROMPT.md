# 用 AI 在 Windows 上跑通 OCR 代理

把下面这段话完整发给任意可执行命令的 AI 编程助手（Codex、Cursor、Cline、Windsurf 等）。

```text
请帮我在这台 Windows 电脑上跑通本仓库的 OCR 代理，让支持 OpenAI-compatible API 的 agent 可以把图片先 OCR 成文字再交给 GLM-5.3。

环境与前提：
1. 我已有一个可访问的上游 OpenAI-compatible 服务，例如 EasyCLIProxyAPI、公司网关或其他兼容服务；请先让我提供它的根地址，不要猜测。
2. 我使用的 agent 配置文件路径、provider 名称和 base_url 请先读取我的实际配置，不要直接覆盖整个文件。
3. 不要要求我提供或提交 API key；代理只转发请求头，不需要读取密钥。
4. 请只做本仓库范围内的安装、配置和验证，不要修改无关系统设置。

请按以下顺序执行：
1. 克隆仓库：https://github.com/wds520/ocr-proxy-desktop
2. 进入仓库目录。
3. 用 Python 3.11+ 创建虚拟环境，并安装 requirements-runtime.txt。
4. 启动 `python src/app.py`。
5. 在界面里配置：
   - 上游地址：我的上游服务根地址，不要带 `/v1`
   - 本地监听端口：默认 8318
   - Codex 配置路径：我的实际配置文件
   - provider：我实际使用的 provider
   - 模型规则：`glm-*`
6. 点击“运行自动诊断”，确认：
   - 配置读取成功
   - 本地 8318 服务可用
   - 上游 HTTP 可达
   - 内置 OCR 能识别测试数字
7. 点击“启用 OCR 代理”，确认所选 provider 的 base_url 已改为 `http://127.0.0.1:8318/v1`。
8. 重启或重新打开我的 agent 客户端，发一张包含文字的图片给 GLM-5.3，验证模型能基于 OCR 文本回答。
9. 测试完成后，点击“关闭 OCR 代理”或正常退出应用，确认 base_url 已恢复为原上游地址。

验收标准：
- 启用前后只修改所选 provider 的 base_url，其他配置保持不变。
- 图片请求会被转换为 `[图片OCR内容开始]...[图片OCR内容结束]` 的文本。
- 非图片请求和未匹配模型的请求按原样转发。
- 关闭代理后连接恢复正常。

如果遇到问题，请先检查端口占用、上游地址、provider 名称、模型规则和 Python 版本，再向我说明具体错误，不要猜测性修改配置。
```
