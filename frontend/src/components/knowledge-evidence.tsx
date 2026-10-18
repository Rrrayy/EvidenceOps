// 负责展示运行归档中的知识片段及检索来源；正文始终按纯文本渲染。
import type { Evidence } from "@/lib/contracts";

export function KnowledgeEvidence({ evidence }: { evidence: Evidence }){
	const metadata=evidence.source_metadata;
	const heading=metadata?.heading_path?.join(" / ")||"知识片段";
	const identities=[
		["文档标识",metadata?.document_id],
		["原资料来源",metadata?.source_ref],
		["片段标识",metadata?.chunk_id],
		["切分集合",metadata?.chunk_set_id],
		["编码集合",metadata?.embedding_set_id],
		["配置身份",metadata?.config_fingerprint],
		["检索方法",metadata?.retrieval_method]
	];
	const retrieval=metadata?.retrieval_details;
	const branches=retrieval?.branches;
	const branch_entries=branches&&typeof branches==="object"?Object.entries(branches as Record<string,unknown>):[];
	const retrieval_method=metadata?.retrieval_method??"";
	return <section className="knowledge-evidence" aria-label="知识片段与来源">
		<p className="notice">知识资料提供背景与检查方法，不是本次故障的现场观测，也不单独证明根因。</p>
		<h3>{heading}</h3>
		{evidence.content_snapshot==null?<p className="muted">本次运行未记录片段原文。</p>:<pre className="knowledge-snapshot">{evidence.content_snapshot}</pre>}
		<details className="knowledge-details">
			<summary>检索来源与追溯信息</summary>
			<dl className="evidence-metadata">
			{identities.map(([label,value])=><div className="knowledge-metadata-row" key={label}><dt>{label}</dt><dd><code>{value??"未记录"}</code></dd></div>)}
			<dt>原文字符范围</dt><dd>{metadata?.start_offset!=null&&metadata?.end_offset!=null?`[${metadata.start_offset}, ${metadata.end_offset})`:"未记录"}</dd>
			<dt>检索排名</dt><dd>{metadata?.rank??"未记录"}</dd>
			<dt>检索评分</dt><dd>{metadata?.score??"未记录"}（不是准确率或置信度）</dd>
			</dl>
			{retrieval&&<section className="retrieval-audit" aria-label="检索审计">
				<strong>检索审计</strong>
				<p>{retrieval_method.includes("bm25")?"本片段来自词法检索或混合检索。":"本片段来自向量检索或后端声明的检索方法。"} 分数仅用于本次排序。</p>
				{typeof retrieval.score_kind==="string"&&<p>评分类型：<code>{retrieval.score_kind}</code></p>}
				{typeof retrieval.vector_candidates==="number"&&<p>向量候选：<code>{retrieval.vector_candidates}</code></p>}
				{typeof retrieval.keyword_candidates==="number"&&<p>关键词候选：<code>{retrieval.keyword_candidates}</code></p>}
				{typeof retrieval.bm25_candidates==="number"&&<p>BM25 候选：<code>{retrieval.bm25_candidates}</code></p>}
				{branch_entries.length>0&&<div className="retrieval-branches">{branch_entries.map(([name,value])=><span key={name}><b>{name}</b> {typeof value==="object"&&value!==null?JSON.stringify(value):String(value)}</span>)}</div>}
			</section>}
			<p className="drawer-note">字符范围按 Python 字符计数，左闭右开。内容版本不代表适用的软件版本；来源标识不作为链接打开。</p>
		</details>
	</section>;
}
