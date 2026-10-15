# SQLAlchemy 连接池耗尽排查

适用范围：Python SQLAlchemy QueuePool 报 QueuePool limit of size ... overflow ... reached, connection timed out。本文是 EvidenceOps 原创练习摘要，不能把应用连接池超时、PostgreSQL 服务端连接上限和模型调用超时混成同一种故障。

SQLAlchemy QueuePool 超时表示调用方未在 pool_timeout 内获得可用连接。需要核对 pool_size、max_overflow、pool_timeout、应用进程数量和实际数据库操作并发；所有进程的连接预算之和应与服务端容量一起评估，单个池的大小不等于全服务连接总数。

SQLAlchemy 池耗尽可能来自会话或连接未释放、长事务、慢查询、锁等待，也可能是正常负载超过连接预算。先查连接检出/归还、事务持续时间、数据库活动查询与锁、应用请求并发。不能仅凭 QueuePool 错误就断定发生连接泄漏。

在 Agent 应用中，SQLAlchemy Session 不能跨越耗时的模型请求或多轮工具等待来长期持有数据库连接。读取必要配置后关闭 Session，在事务外调用模型或 Embedding，再以短事务保存结果；异常应回滚并关闭会话。上下文管理器负责资源边界，但仍需确认代码没有把连接或 Session 泄漏到边界外。

处理 SQLAlchemy 池超时时，先修复资源生命周期与慢事务，再基于并发、数据库承载能力调整池配置。不要直接把 max_overflow 改为无限、无限重试或把 pool_timeout 拉得很长；这会把压力转移到数据库和请求队列。缺少连接生命周期与数据库观测时，应返回证据不足并列出待补信息。

参考来源（2026-10-15 核对）：SQLAlchemy 官方 QueuePool 错误说明 https://docs.sqlalchemy.org/en/20/errors.html#queuepool-limit-of-size-x-overflow-y-reached-connection-timed-out-timeout-z 。本文示例面向同步 QueuePool，异步池需核对实际引擎类型。
