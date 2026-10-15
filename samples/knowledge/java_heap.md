# Java 堆内存不足排查

适用范围：Java 服务出现 java.lang.OutOfMemoryError: Java heap space。本文为 EvidenceOps 原创排障练习摘要。Java heap space、Metaspace、Direct buffer memory、unable to create native thread 和容器 OOMKilled 需要分别诊断，不能看到 OOM 就认定堆泄漏。

Java heap space 表示 JVM 在堆上分配对象失败。可能与存活对象规模、分配突增、大对象、堆配置或对象被意外长期引用有关。先收集完整异常、JDK 版本、JVM 参数、进程与容器内存限制、GC 日志、故障时间和业务流量；仅凭异常不能证明内存泄漏。

Java 堆排查应观察 GC 前后堆占用与 Full GC 后存活对象的趋势，结合已有 heap dump、对象数量和引用链检查保留路径。持续增长可以提供线索，但需要结合工作负载确认。采集 dump 可能造成停顿、磁盘压力且包含敏感信息，必须由有权限的人评估后操作。

Java OOM 处置不能只提高 -Xmx：增大堆要与容器和宿主机内存预算、非堆及本地内存需求一起考虑。若已有对象保留问题，扩堆只能延后失败；若是合法工作集过大，则需容量评估、限流或分批处理。应区分临时缓解和已验证的根因修复。

资料不足时应补充 Java 完整 OOM 类型、GC 时间线和对象保留证据，不应把 RPC 重试、数据库连接池或 Python 缺包结论直接套用到 Java heap space。本文参考 Oracle JDK 故障排查文档 https://docs.oracle.com/en/java/javase/21/troubleshoot/troubleshooting-memory-leaks.html ，适用版本需核对。
