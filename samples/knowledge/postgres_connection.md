# PostgreSQL 连接失败排查

适用范围：应用连接 PostgreSQL 时出现 connection refused、连接超时、password authentication failed、database does not exist 或 too many connections。本文为 EvidenceOps 原创练习资料；资料描述可能原因，不代表已经探测了用户网络或读取了数据库日志。

PostgreSQL connection refused 优先核对目标主机、端口、实例进程和监听地址。容器内部端口与宿主机映射端口可能不同；在本项目本地演示中是宿主机 5433 映射容器 5432，这不是所有部署的默认值。容器内的 127.0.0.1 指向该容器自身，不能直接当作宿主机或另一容器。

PostgreSQL 连接超时不等同密码错误。需要在实际应用运行位置检查 DNS、路由、防火墙、端口可达性和服务器响应，记录连接阶段与耗时。不要通过关闭防火墙、对公网开放数据库或无限延长超时来掩盖问题；仅凭连接超时不能断言数据库一定宕机。

PostgreSQL password authentication failed 应核对目标实例、用户名、数据库、凭据来源和认证配置，避免连错实例或环境变量仍保留旧密码。日志、诊断描述和截图中不得打印密码或完整含密钥连接串。认证失败不应当作查无数据或正常查询返回 None。

PostgreSQL too many connections 应结合服务端连接总数、应用实例数、连接池大小、空闲及长事务连接定位。max_connections 控制服务端并发连接上限，提高它会增加相关资源需求，不能盲目调大；需优先检查连接是否释放、池预算是否合理。缺少数据库与应用侧连接观测时不能确认为连接泄漏。

参考来源（2026-10-15 核对）：PostgreSQL 官方连接与认证配置 https://www.postgresql.org/docs/current/runtime-config-connection.html 。版本和部署环境需人工确认；本资料不提供自动修改认证或重启数据库的工具。
