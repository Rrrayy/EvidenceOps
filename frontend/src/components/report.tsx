// 负责展示诊断报告、证据引用和分析边界。
"use client";
import { FileText,Gauge,SlidersHorizontal,ArrowUpRight,ShieldCheck,AlertCircle } from "lucide-react";
import type { Evidence,RunResult } from "@/lib/contracts";
import { source_labels } from "@/lib/contracts";
import { evidence_number } from "@/lib/evidence";
export function EvidenceIcon({ source }: { source: string }) {

	const Icon=source==="log"? FileText:source==="metric"? Gauge:SlidersHorizontal;
	return <Icon size={17} aria-hidden="true" />;
}
export function Report({ result,on_evidence }: { result: RunResult; on_evidence: (item: Evidence) => void }) {

	const report=result.report;
	const demo=result.model_config?.provider_id==="mock";
	function citations(ids: string[]) {

		return (
			<div className="citations">
				{ids.map((id) => {
					const item=result.evidences.find((evidence) => evidence.evidence_id===id);
					return item? (
						<button key={id} className="citation" aria-label={`${source_labels[item.source]??item.source}证据 ${evidence_number(result.evidences,id)}`} title={`核对证据 ${id}`} onClick={() => on_evidence(item)}>
							<span className="citation-number">{evidence_number(result.evidences,id)}</span>
							<EvidenceIcon source={item.source} />
							{source_labels[item.source]??item.source}
							<ArrowUpRight size={12} />
						</button>
					):(
						<span key={id} className="missing-citation">
							引用无法定位
						</span>
					);
				})}
			</div>
		);
	}
	if(!report) {
		return (
			<div className="no-report">
				<AlertCircle size={30} />
				<h2>
					{result.status==="cancelled"
						? "诊断已取消"
						:result.status==="running"||result.status==="pending"
							? "诊断仍在执行"
							:"本次未生成报告"}
				</h2>
				<p>{result.error_detail?.message??result.error_code??"已归档的证据和过程仍可查看。"}</p>
				<p className="muted">{result.evidences.length} 条证据已保留</p>
			</div>
		);
	}
	return (
		<article className="report">

			<div className="report-heading">
				<span className="report-mark">
					<ShieldCheck size={18} />
					{demo? "Mock 演示报告":"证据诊断报告"}
				</span>
				<span className="confidence">
					{demo? "样例置信度":"模型置信度"} <strong>{Math.round(report.confidence*100)}%</strong>
					<span className="sr-only">，不是统计正确率</span>
				</span>
			</div>
			{demo&&<div className="error-banner" role="note">本次使用 Mock：报告与证据为固定演示样例，不是针对输入的真实故障结论。请在模型选择器选择已验证的真实模型连接。</div>}

			<section className="root-cause">
				<span className="section-label">根因判断</span>
				<h2>{report.root_cause.text}</h2>
				{citations(report.root_cause.evidence_ids)}
			</section>

			<section className="recommendations">
				<h3>下一步排查</h3>
				{report.recommendations.map((claim,index) => (
					<div className="recommendation" key={index}>
						<span className="step-number">{index+1}</span>
						<div>
							<p>{claim.text}</p>
							{citations(claim.evidence_ids)}
						</div>
					</div>
				))}
			</section>

			<section className="limitations">
				<AlertCircle size={18} />
				<div>
					<h3>分析边界</h3>
					<p>{report.limitations}</p>
					<small>置信度是模型自评，不代表结论已经被独立验证。</small>
				</div>
			</section>

		</article>
	);
}
