// 负责离线评测文件导入、统计和案例审核结果展示。
"use client";
import { useEffect,useRef,useState } from "react";
import { FileJson,Upload,Check,X,ChevronDown } from "lucide-react"; // 展示真实规则状态。
import { evaluation_schema,type Evaluation } from "@/lib/evaluation"; // 验证仓库评测 JSON。
export function Evaluations() {
	// 只读查看已有离线评测，不制造在线执行能力。
	const input=useRef<HTMLInputElement>(null);
	const [data,set_data]=useState<Evaluation|null>(null);
	const [error,set_error]=useState(""); // 区分尚未导入与失败。
	const generation=useRef(0);
	useEffect(()=>()=>{generation.current++;},[]);
	async function load_file(file: File) {
		const token=++generation.current;
		// 导入限制大小的 JSON。
		try {
			if(file.size>10_000_000) {
				throw new Error("评测文件不能超过 10 MB");
			}
			const result=evaluation_schema.parse(JSON.parse(await file.text()));
			if(token!==generation.current){return;}
			set_data(result);
			set_error("");
		} catch(reason) {
			if(token!==generation.current){return;}
			set_error(reason instanceof Error? `无法读取评测：${reason.message}`:"评测文件格式无效");
		} // 保留上一份有效结果。
	} // 结束导入。
	return (
		<section className="evaluation-page">
			<div className="page-heading">
				<div>
										<h1>评测结果</h1>
					<p>查看离线评测中的自动规则和待审核案例。</p>
				</div>
				<button className="primary-button" onClick={() => input.current?.click()}>
					<Upload size={16} />
					导入评测结果
				</button>
				<input
					ref={input}
					className="sr-only"
					type="file"
					accept=".json,application/json"
					aria-label="选择评测 JSON"
					onChange={(event) => {
						const file=event.target.files?.[0];
						if(file) {
							void load_file(file);
						}
						event.target.value="";
					}}
				/>
			</div>
			{/* 操作只读取用户选择的文件。 */}
			{error&&(
				<div role="alert" className="error-banner">
					{error}
				</div>
			)}
			{/* 数据损坏不显示成功。 */}
			{!data? (
				<div className="eval-empty">
					<FileJson size={40} />
					<h2>导入离线评测文件</h2>
					<p>支持仓库中的 eval_result*.json。文件在当前浏览器中读取，不上传到服务端。</p>
					<div className="eval-format">
						<span>自动规则</span>
						<span>证据引用</span>
						<span>人工审核状态</span>
					</div>
					<p className="muted">规则通过不等于根因正确；语义质量仍需独立审核。</p>
				</div>
			):(
				<>
					<div className="eval-summary">
						<div>
							<span>评测案例</span>
							<strong>{data.summary.case_count}</strong>
						</div>
						<div>
							<span>规则通过</span>
							<strong>
								{data.summary.rule_passed_count}
								<small> / {data.summary.case_count}</small>
							</strong>
						</div>
						<div>
							<span>待语义审核</span>
							<strong>{data.summary.semantic_review_pending}</strong>
						</div>
						<div>
							<span>执行错误</span>
							<strong>{data.summary.execution_error_count}</strong>
						</div>
					</div>
					<p className="eval-batch">
						{data.mode} 模式 <code>{data.batch_id}</code>
					</p>
					<div className="eval-cases">
						{data.results.map((item) => {
							const passed=item.checks.length>0&&item.checks.every((check) => check.passed);
							return (
								<details key={item.case_id}>
									<summary>
										<span className={passed? "good":"bad"}>
											{passed? <Check size={17} />:<X size={17} />}
										</span>
										<strong>{item.case_id}</strong>
										<span>{passed? "规则通过":"规则未通过"}</span>
										<ChevronDown size={15} />
									</summary>
									<div className="check-grid">
										{item.checks.map((check) => (
											<div key={check.name}>
												<span className={check.passed? "good":"bad"}>
													{check.passed? <Check size={14} />:<X size={14} />}
												</span>
												<code>{check.name}</code>
											</div>
										))}
									</div>
									<div className="review-detail">
										<h3>
											语义审核：
											{item.semantic_review.status==="pending"
												? "待审核"
												:item.semantic_review.status==="passed"
													? "已通过"
													:"未通过"}
										</h3>
										<ul>
											{item.semantic_review.criteria.map((criterion) => (
												<li key={criterion}>{criterion}</li>
											))}
										</ul>
										{item.semantic_review.notes&&<p>{item.semantic_review.notes}</p>}
										{typeof item.wall_duration_ms==="number"&&(
											<p>实际执行耗时 {(item.wall_duration_ms/1000).toFixed(3)}s</p>
										)}
										{item.execution_error&&<p className="bad">{item.execution_error}</p>}
									</div>
									{/* 审核标准与结果来自导入文件。 */}
								</details>
							);
						})}
					</div>
					<p className="notice">
						这里展示自动规则结果，不能据此宣称诊断准确率。人工审核数据保留在导入文件中。
					</p>
				</>
			)}
			{/* 只显示文件中可验证的指标。 */}
		</section>
	); // 结束评测页面。
} // 结束组件。
