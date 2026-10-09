# Eval CLI 人工审核

在项目根目录的 PowerShell 中执行。审核命令只读取已有结果，不调用模型或数据库。

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode mock --output eval_result_20_mock.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review eval_result_20_mock.json
```

`--output` 由 Python 直接以 UTF-8 保存 JSON，避免 Windows PowerShell 管道把中文错误解码、破坏字符串引号。不传该参数时仍输出完整 JSON 到 stdout。新示例使用新文件名，旧的三案例审核结果可以保留；重跑同一输出路径会替换该文件，包括之前的审核状态。

每条 pending 案例按“案例编号 → 诊断请求 → 模型根因 → 编号建议与证据ID → 证据局限 → 规则检查 → 审核标准”分段显示。失败案例展示状态、错误码和错误说明。段落按终端宽度折行（最多100列），中文按双列估算；终端字体对特殊Unicode字符的宽度处理可能有差异。输入 `y` 表示符合全部审核标准，`n` 表示不符合，再输入可留空的 comment。

每完成一条审核，原文件的 `semantic_review.status`、`comment` 和 `summary` 都会更新。Ctrl+C 中断后重新执行同一命令，只继续 pending 案例；当前尚未输入完 comment 的案例保持 pending。已审核案例默认不重复询问。

三项指标的分母都是全部案例数量：

| 指标 | 分子 |
| --- | --- |
| rule_pass_rate | rule_passed=true 的案例数量 |
| semantic_pass_rate | semantic_review.status=passed 的案例数量 |
| final_pass_rate | 规则通过且人工审核通过的案例数量 |

pending 不计为通过，另用 semantic_review_pending 显示未审核数量。例如三个案例分别为“规则通过/人工通过”“规则通过/人工失败”“规则失败/人工通过”，三项通过率为 2/3、2/3、1/3。预期失败案例按自己的审核标准判断，不因没有根因报告就自动失败。

规则全部通过不代表诊断语义正确，Mock 人工审核通过也不代表真实模型质量。只有审核了真实模型生成的报告，才有对应的人工语义评价结果。

## 20个案例的覆盖范围

原有前三个案例保留，新增17个。全部复用现有日志、指标与两版配置文件，原始样本不变；每个案例绑定原始文件的SHA-256指纹。无需启动HTTP服务或PostgreSQL。

| 分组 | case_id | 核心检查 |
| --- | --- | --- |
| 正常查询 | correlated-timeout | 日志、指标、配置联合诊断，区分相关性与因果 |
| 正常查询 | logs-only | 日志字段不冒充独立指标证据 |
| 正常查询 | metrics-only | 指标变化不证明RPC超时或下游故障 |
| 正常查询 | logs-metrics | 同窗口交叉分析，不虚构配置 |
| 正常查询 | symptom-keywords | 不依赖错误枚举，保留症状与关键词过滤 |
| 无数据/证据不足 | empty-log-window | 无匹配日志不代表服务健康 |
| 无数据/证据不足 | empty-log-keyword | 关键词过滤无结果，不偷换查询条件 |
| 无数据/证据不足 | empty-metric-window | 查询成功但无指标采样，证据转换拒绝生成报告 |
| 无数据/证据不足 | healthy-metric-sample | 40/64、无排队的单个采样不代表服务全面健康 |
| 配置/时间边界 | missing-config | 未生效时刻拒绝伪造配置 |
| 配置/时间边界 | config-only-v1 | 配置容量、超时、重试规则不能当成运行事实 |
| 配置/时间边界 | config-switch-boundary | 切换前v1、切换时v2，左闭右开 |
| 配置/时间边界 | config-utc-equivalence | UTC时刻与北京时间等价，正确选v2 |
| 参数/服务边界 | invalid-time | 非法时间不得被模型擅自纠正 |
| 参数/服务边界 | invalid-limit | limit=0被拒绝 |
| 参数/服务边界 | overlong-window | 31分钟查询被拒绝，不缩短或拆分 |
| 参数/服务边界 | unknown-service | 不替换陌生服务名，不读取其他服务 |
| 截断/推断边界 | truncated-logs | 匹配2条、返回1条，不能使用未返回记录推断趋势 |
| 截断/推断边界 | truncated-metrics | 匹配3条、返回1条，不能声称完整趋势 |
| 截断/推断边界 | disjoint-windows | 异窗口指标不能证明超时发生时的线程状态 |

每个案例的 `tool_calls` 是预期调用条件；真实模式中由模型自行选择工具与参数，评测器只检查，不替模型填入这些条件。症状和关键词没有保存在生产执行记录中，Eval通过包裹工具校验函数，在校验前临时捕获实际参数，再核对预期；不会扩展生产记录的敏感字段白名单。

`evidence_checks` 额外核对证据摘要中的数量、截断状态与配置版本，避免只检查工具名就算通过。空指标案例的工具执行记录是 succeeded，但 Run 为 failed，外层错误码是 `EVIDENCE_COLLECTION_FAILED`，内层原因是 `NO_METRIC_SAMPLES`；用 `expected_failure_stage=collection` 和 `expected_error_detail_code` 区分失败阶段，不要求成功查询工具伪装成失败。

Mock最终答案根据工具实际返回的数量、采样及配置生成模板摘要，不再对零匹配、正常采样等情况统一输出“超时与饱和同期出现”。Mock仍不是诊断能力的评测对象，语义状态保持pending，须由审核者决定。

## 运行真实模型

先在当前PowerShell设置 `EVIDENCEOPS_MODEL_BASE_URL`、`EVIDENCEOPS_MODEL_API_KEY` 和 `EVIDENCEOPS_MODEL_NAME`，再执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode real --output eval_result_20_real.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review eval_result_20_real.json
```

20个案例依次运行，每个案例可能调用多轮模型，会产生API费用；模型调用超时与轮次预算沿用当前设置。异常案例仍计入分母。真实模型若拒绝发出非法参数调用、纠正了实验参数或追加了不允许的工具，当前严格的参数边界实验会判规则失败，应检查实际记录后区分“模型没有遵循实验要求”和“Runtime校验失效”，不可混为一谈。

评测命令退出码：规则全部通过为0，有规则失败为1，结果写入失败为2。review成功保存返回0，不代表所有案例审核通过。三个通过率的定义与分母保持不变，样本20条单次通过也不能推出生产准确率。

保存使用同目录临时文件写完后原子替换，避免写入失败截断原 JSON。如果提示权限或文件占用错误，请关闭占用程序后重试。不要同时用多个 review 进程审核同一文件；当前 CLI 不提供多审核人协作或文件锁。
