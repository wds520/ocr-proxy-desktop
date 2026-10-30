# 用 AI 在 Windows 上跑通 OCR 代理

把下面这段话完整发给任意可执行命令的 AI 编程助手（Codex、Cursor、Cline、Windsurf、WorkBuddy、opencode 等）。

```text
请帮我在这台 Windows 电脑上跑通本仓库的 OCR 代理，让支持 OpenAI 兼容 API 的 agent 可以把图片先在本机 OCR 成文字，再交给不能直接看图的大模型（例如 GLM-5.3）。

环境与前提：
1. 我已有一个可访问的上游 OpenAI 兼容服务，默认是 https://gateway.onewo.com/v1；如需更换，请先让我确认地址，不要猜测。
2. 我使用的 agent 是 WorkBuddy / opencode / zcode / Codex 等任意支持 OpenAI 兼容 base_url 的工具；应用不会修改 agent 的配置文件，只在本机启动一个本地代理服务。
3. 不要要求我提供或提交 API key；代理只转发请求头，不需要读取密钥。
4. 请只做本仓库范围内的安装、配置和验证，不要修改无关系统设置。

请按以下顺序执行：
1. 克隆仓库：https://github.com/wds520/ocr-proxy-desktop
2. 进入仓库目录。
3. 用 Python 3.11+ 创建虚拟环境，并安装 requirements-runtime.txt。
4. 启动 `python src/app.py`。
5. 在界面里配置：
   - 上游服务地址：默认 https://gateway.onewo.com/v1
   - 本地 OCR 端口：默认 8318
   - 模型规则：`GC-*`、`glm-*`、`deepseek-*`
6. 点击“运行自动诊断”，确认设置格式、本地端口、上游 HTTP 可达、内置 OCR 能识别测试数字。
7. 点击“启用 OCR 代理”，把界面显示的 Agent base_url（默认 http://127.0.0.1:8318，不带 /v1）配置到我使用的 agent 的 OpenAI 兼容接口地址。
8. 重启或重新打开 agent 客户端，发一张包含文字的图片给 GLM-5.3，验证模型能基于 OCR 文本回答。
9. 测试完成后，关闭代理或正常退出应用；如需还原，把 agent 的 base_url 改回原上游地址。

验收标准：
- 图片请求会被转换为 `[图片OCR内容开始]...[图片OCR内容结束]` 的文本后交给上游模型。
- 非图片请求和未匹配模型的请求按原样转发。
- 应用不修改 agent 配置文件；关闭代理即停止中转。

如果遇到问题，请先检查端口占用、上游地址、模型规则和 Python 版本，再向我说明具体错误，不要猜测性修改配置。
```
