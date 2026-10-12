# EvidenceOps 本机安装与数据存储

新客户无需先安装数据库。安装入口默认创建 SQLite，诊断历史、报告、证据摘要、执行事件与运行时模型快照均保存在磁盘。Windows 默认数据目录为 `%LOCALAPPDATA%\EvidenceOps`，与程序目录分离；不要在升级程序时删除数据目录。

## 准备与启动

当前交付是源码安装方案，不是已打包的安装程序。已验证环境为 Python 3.14、Node.js、PowerShell 7。先在项目根目录准备运行依赖：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
pwsh -File scripts/start_installed.ps1
```

打开 `http://127.0.0.1:3013`。首次设置依次检查存储、模型和数据来源；现有工具查询仓库样例，不会因为输入了客户故障描述就自动读取客户主机日志。使用 Mock 不产生模型费用；用户模型仅在主动验证或诊断时调用。

完成安装与构建后，日常启动只需在仓库根目录执行 `pwsh -File scripts/start_installed.ps1`，它同时启动前后端，无需另外运行前端命令。保持启动终端运行，按 `Ctrl+C` 停止；再次执行该命令可使用原数据目录启动。脚本不配置开机自启。常见启动问题见[项目快速启动](README.zh-CN.md#快速启动)。

可指定 `-DataDirectory D:/EvidenceOpsData -ApiPort 8014 -WebPort 3013`。两端必须由同一运行账号访问同一数据目录。入口限制本机访问，必须使用单 API worker。同一个数据目录或 SQLite 文件不能启动第二个实例。

原开发入口 `evidenceops.api.agent_app:app` 继续保留，其环境变量行为未被安装版替换。客户安装必须使用 `evidenceops.api.installed_app:app`，否则不会出现可用的存储管理接口。

## 存储与维护

“数据与存储”显示真实存储状态、版本和备份。SQLite 自动初始化并迁移；既有数据库升级前保留副本。连接 PostgreSQL 时应使用管理员准备的专用数据库和账号，页面可检查连接，再明确初始化或升级。程序不会安装 Docker、创建企业数据库账号或自动部署 PostgreSQL。

已有运行或模型验证期间，维护等待其结束并拒绝新的诊断，不自动取消付费调用。切换先备份，向空目标导入，校验内容后发布新配置。失败时保留原库并尝试恢复服务；数据库故障时管理页面仍可访问，诊断暂停，不自动降级为内存。中断的维护不会自动重做，重启后会标明失败；恢复连接配置的中断通过本机日志回滚。

配置版本和请求身份防止旧页面覆盖或重复维护。PostgreSQL 密码加密保存，读取接口只返回已配置标识。浏览器不保存密码、密钥或管理令牌；同源 Next 服务读取安装目录的令牌后转发维护请求。

## 备份与换机

页面可创建、下载、导入与恢复逻辑备份，上限 100 MB。恢复需要输入“恢复备份”；本机恢复使用新 SQLite 文件，原文件保留。PostgreSQL 恢复目标必须为空，禁止自动覆盖或合并已有档案。运行 ID、事件顺序、证据引用和运行时模型配置按备份保留。

默认备份不包含 API Key；恢复后需补填密钥并重新验证模型。可显式选择携带凭据，以至少 12 字符的独立口令加密。口令不保存在备份或操作记录中；遗失口令无法恢复凭据。换机后目标账号重新加密密钥。Windows 本机密钥由当前用户 DPAPI 保护，直接复制密钥文件到不同用户不等同于可用的凭据迁移。

备份仍含客户描述、证据摘要和历史报告，应保存到客户认可的位置。校验和用于检测损坏，不代表文件来源可信。大规模存储请使用数据库管理员的原生备份方案。备份不包含未接入的原始日志或外部附件。

## 当前边界

- 本机、单租户、单 API 实例；没有远程登录、多人权限或企业身份认证。
- 数据源仍为样例 Connector，没有客户数据源配置向导。
- 没有定时备份、自动保留策略、自动清理或原始日志归档。
- Embedding 和未来 Rerank 独立配置，诊断模型切换不重建索引。
- 安装脚本监督服务进程；停止脚本会终止子进程，下次启动会恢复并收尾未完成的运行，不自动再次调用模型。需要长期后台运行时应另行配置受管理的服务和关停策略。

## 验证

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -o pythonpath=src -q
cd frontend
npm test
npm run build
```

测试默认隔离模型连接与临时数据库，不读取客户密钥，不调用真实供应商。PostgreSQL 集成测试需明确设置 `EVIDENCEOPS_TEST_POSTGRES=1` 和测试数据库连接；测试使用独立 schema/锁，不能拿客户库作为临时实验目标。
