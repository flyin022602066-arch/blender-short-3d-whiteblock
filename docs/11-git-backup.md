# Git 代码备份

专属远程仓库：https://github.com/flyin022602066-arch/blender-short-3d-whiteblock.git

此仓库备份应用源代码、桌面启动脚本、测试、JSON Schema、需求文档、技术方案和现有诊断报告。

## 保留在本地的内容

- 整个 output/、library/、_smoke/：包含原片、项目 JSON、白模工程、预览视频、模型、缓存、日志及旧备份。
- .venv-pose/ 等 Python 环境、第三方依赖和 Python 缓存。
- .env、config.json、secrets、credentials、私钥、数据库和本地配置文件。
- Windows 用户目录下的 Whiteblock/config.json 与 Whiteblock/secrets.bin；后者是 DPAPI 加密的用户凭证，不应复制到仓库。

源码 whiteblock/config.py 只定义默认配置和凭证读写逻辑，应当备份。填写好的 API Key 不是源码的一部分。

## 恢复时注意

克隆仓库只能恢复代码和文档，不能恢复上述被排除的数据。原视频、现有白模和 output/models/ 模型需另行做本地或离线备份。新环境仍需配置 Python、Blender、ffmpeg、姿态依赖和模型，并在软件设置页重新填写 API Key。

## 后续提交

先检查 git status 和 git diff --cached，确认只包含所需源文件，再提交并推送。不要使用 git add -f 上传被忽略的用户配置、原片、输出或凭证。新增源代码目录或根目录文件时，需同步更新 .gitignore 的允许列表。

敏感信息过滤依靠路径排除和提交内容复核，不能把 .gitignore 当成密钥扫描器。任何已提交过的真实密钥都应撤销并轮换；只删除工作区文件并不能从 Git 历史中移除它。
