# 模型连接实际接口与运行约定

后端根路径 `/api/v1/agent`；前端统一 `/api/backend` 同源白名单代理，诊断走 AI SDK 协议适配器。

| 方法与路径 | 行为 |
| --- | --- |
| GET model-services | 返回项目千问预设、自定义 Chat Completions 预设；地区未确认则不展示 |
| GET model-connections | 返回用户连接、只读系统连接、独立全局默认 |
| GET model-connections/{id} | 返回无密钥详情，系统连接只读 |
| POST model-connections | name/provider_id/protocol/endpoint/default_model/timeout_seconds/api_key；保存未验证连接 |
| PATCH model-connections/{id} | 同上并携带 expected_version；省略或空密钥保留旧值，留空地址保留原地址 |
| DELETE model-connections/{id} | expected_version/replacement_id；null 表示无默认，正在使用的连接返回409 |
| PUT model-connections/default | connection_id/model_id/expected_version；独立于保存及工作台选择 |
| POST model-connections/{id}/catalog | expected_version；目录ready/empty/unsupported/failed区分，来源/时间/版本绑定 |
| POST model-connections/{id}/validation | expected_version/model_id；四项验证和模型级 ready 状态 |
| POST diagnosis[/stream] | 兼容 description，新增可选 connection_id/model_id/expected_version |
| GET runs/{id} | 新增可空 model_config；旧 Run 不推断补齐 |

读取白名单不返回 API Key，也不返回含路径的完整接口地址。编辑保留原地址无需回读；更换地址使用输入的新值。输入校验错误只返回字段路径，不回显 Pydantic 的输入值。供应商异常正文及网络异常原文不返回浏览器。模型连接最多100个，目录最多1000项，前端过滤最多展示100个匹配项。

目录/验证在短事务之外执行，完成后按配置版本 CAS 保存。重复验证同一个连接版本与模型返回409，并发供应商操作最多4个。编辑密钥、地址、协议、默认模型或超时使验证和目录失效；只改连接名会保留能力但升级版本。模型目录、推荐项与手填都不代表账号权限或 Agent ready。

每个 Run 使用独立组装的 Agent/Runtime。管理服务在开始前固定连接副本、模型和版本，并登记删除租约；后续修改/默认切换不影响原 Run。快照包含 connection_id/connection_name/provider_id/model_id/requested_model_id/config_version，记录供应商实际返回的模型 ID。快照不含凭据或地址。开始事件与持久化终态事件含无密钥配置，SSE ID、sequence、取消和重放规则保持原样。

模型连接配置库使用独立 SQLite，加密保存凭据；Run 模型快照随报告、证据与终态事件保存到诊断数据库。安装版诊断存储支持 SQLite 与 PostgreSQL，开发内存模式没有历史。连接删除不删除已归档的 Run 快照；查询历史依赖诊断数据库，不把模型配置库当作诊断档案库。

确定性回归使用隔离 MockTransport。真实账号的模型权限、第三方服务兼容性和网络可达性由用户显式验证按钮确认，可能产生少量费用。当前为本机单用户模型连接管理，Embedding/Rerank 不由本页面配置，多用户鉴权/租户与远程部署未实现。自定义出站主机必须由服务端管理员加入白名单，默认 HTTPS、不跟随重定向、不使用环境代理。
