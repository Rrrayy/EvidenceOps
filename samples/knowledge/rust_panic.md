# Rust panic 与越界排查

适用范围：Rust 程序出现 thread panicked、index out of bounds，或 called Result::unwrap() on an Err value。本文为 EvidenceOps 原创练习摘要。panic 不等同内存不安全，也不能仅凭退出就断言发生数据竞争。

Rust panic 排查首先保留完整 panic 消息、源码位置、输入和调用路径，确认是数组或切片索引越界、unwrap/expect 触发，还是显式 panic。不同 panic 信息指向不同检查方向，不能把所有 panic 都归因于 unwrap。

在受控环境下可设置 RUST_BACKTRACE=1 重现以获取回溯；回溯信息受构建配置、符号与运行环境影响，栈不能单独证明是哪一个外部依赖造成错误。保留原始错误和输入范围，比只查看顶层崩溃位置更有助于定位。

Rust index out of bounds 应核对索引计算、长度和输入边界，按业务选择显式校验或 get 返回的 Option；unwrap 失败则应检查 Err 或 None 的实际来源，用 match、错误传播或有依据的降级处理。不能用无条件 catch_unwind 替代错误处理，也不能承诺编译通过就没有运行时 panic。

没有 Rust 完整 panic 文本、调用路径和最小输入时，应明确资料不足，不应套用 Java OOM、Python 缺包或 RPC 线程池结论。参考 Rust 官方 panic 与回溯说明 https://doc.rust-lang.org/book/ch09-01-unrecoverable-errors-with-panic.html 。修复建议需由开发者结合代码验证。
