// 负责运行历史的搜索、筛选、分页及存储不可用状态。
"use client";
import { useEffect,useState } from "react";
import { ArrowUpRight,Search,ChevronLeft,ChevronRight,RefreshCw,Archive } from "lucide-react";
import { history_schema,status_labels,type RunStatus,type RunResult } from "@/lib/contracts";
import { run_error_message } from "@/lib/run-errors";
import { run_error_code_message } from "@/lib/run-errors";
type HistoryItem={
	run_id: string;
	description?: string;
	status: RunStatus;
	created_at: string;
	started_at: string|null;
	finished_at: string|null;
	error_code: string|null;
	error_detail?: RunResult["error_detail"];
};
export function History({ on_open,disabled,on_storage }: { on_open: (id: string) => void; disabled: boolean; on_storage?:()=>void }) {

	const [items,set_items]=useState<HistoryItem[]>([]);
	const [search,set_search]=useState("");
	const [query,set_query]=useState("");
	const [status,set_status]=useState("");
	const [offset,set_offset]=useState(0);
	const [has_more,set_has_more]=useState(false);
	const [loading,set_loading]=useState(true);
	const [error,set_error]=useState("");
	const [unavailable,set_unavailable]=useState(false);
	const [storage_unready,set_storage_unready]=useState(false);
	const [revision,set_revision]=useState(0);
	useEffect(() => {

		const controller=new AbortController();
		set_loading(true);
		set_error("");
		set_unavailable(false);
		set_storage_unready(false);
		const params=new URLSearchParams({ limit: "12",offset: String(offset),search: query });
		if(status) {
			params.set("status",status);
		}
		fetch(`/api/backend/runs?${params}`,{ signal: controller.signal })
			.then(async (response) => {
				const data=await response.json();
				if(controller.signal.aborted) { return; }
				if(data?.error_code==="PERSISTENCE_DISABLED"||data?.error_code==="STORAGE_NOT_READY") {
					set_storage_unready(data.error_code==="STORAGE_NOT_READY");
					set_unavailable(true);
					set_items([]);
					set_has_more(false);
					return;
				}
				if(!response.ok) {
					throw new Error(data?.message??"历史读取失败");
				}
				const listing=history_schema.parse(data);
				set_items(listing.items);
				set_has_more(listing.has_more);
			})
			.catch((reason) => {
				if(!controller.signal.aborted) {
					set_error(run_error_message(reason));
					set_items([]);
					set_has_more(false);
				}
			})
			.finally(() => {
				if(!controller.signal.aborted) {
					set_loading(false);
				}
			});
		return () => controller.abort();
	},[offset,status,query,revision]);
	return (
		<section className="history-page">
			<div className="page-heading">
				<div>
					<h1>运行历史</h1>
					<p>按故障、状态和运行 ID 检索诊断档案。</p>
				</div>
				<button className="icon-button" aria-label="刷新历史" onClick={() => set_revision(revision+1)}>
					<RefreshCw size={18} />
				</button>
			</div>

			<form
				className="history-filters"
				onSubmit={(event) => {
					event.preventDefault();
					set_offset(0);
					set_query(search.trim());
				}}
			>
				<label className="search-field">
					<Search size={17} />
					<input
						aria-label="搜索诊断"
						disabled={unavailable||loading}
						placeholder="搜索故障描述或运行 ID"
						value={search}
						maxLength={200}
						onChange={(event) => set_search(event.target.value)}
					/>
				</label>
				<select
					aria-label="筛选运行状态"
					disabled={unavailable||loading}
					value={status}
					onChange={(event) => {
						set_status(event.target.value);
						set_offset(0);
					}}
				>
					<option value="">全部状态</option>
					{Object.entries(status_labels).map(([value,label]) => (
						<option key={value} value={value}>
							{label}
						</option>
					))}
				</select>
				<button className="secondary-button" type="submit" disabled={unavailable||loading}>
					搜索
				</button>
			</form>

			{disabled&&<p className="notice">当前诊断仍在执行；确认终态后可打开其他档案。</p>}

			{unavailable? (
				<div className="persistence-notice" role="status">
					<h2>{storage_unready?"诊断存储尚未就绪":"运行历史尚未启用"}</h2>
					<p>{storage_unready?"存储不可用或正在维护，历史查询与新诊断暂时暂停。请到数据与存储查看状态，原数据不会自动替换为内存档案。":"当前服务使用内存模式，诊断仍可执行。启用持久化后，新运行才会保存到历史；此前未保存的诊断无法补回。"}</p>
					{storage_unready?<button className="secondary-button" onClick={on_storage}>打开数据与存储</button>:<details>
						<summary>如何启用数据库持久化</summary>
						<ol>
							<li>在项目 .env 中配置 POSTGRES_PASSWORD，并在后端终端载入同一密码。</li>
							<li>启动项目 PostgreSQL，等待数据库健康后执行迁移。</li>
							<li>停止当前 API，以持久化模式重新启动；保持前端代理指向该 API。</li>
						</ol>
						<pre>{"docker compose up -d postgres\n$env:PYTHONPATH='src'\n$env:EVIDENCEOPS_PERSISTENCE='postgres'\n.\\.venv\\Scripts\\python.exe -m alembic upgrade head\n.\\.venv\\Scripts\\python.exe -m uvicorn evidenceops.api.agent_app:app --app-dir src --host 127.0.0.1 --port 8014"}</pre>
						<p>这是服务启动配置，没有网页开关。重启后点击右上角刷新，重新检查历史是否可用。</p>
					</details>}
				</div>
			):error? (
				<div role="alert" className="error-banner">
					{error}
					<button className="secondary-button" onClick={()=>set_revision(value=>value+1)}>重试</button>
				</div>
			):loading? (
				<div className="loading-state" role="status">正在读取运行档案…</div>
			):items.length===0? (
				<div className="empty-panel">
					<Archive size={34} />
					<h2>{query||status?"没有匹配的运行记录":"这里还没有运行记录"}</h2>
					<p>{query||status?"请调整搜索内容或状态筛选后重试。":"完成诊断后，启用持久化的运行会出现在这里。"}</p>
				</div>
			):(
				<div className="table-wrap">
					<table>
						<thead>
							<tr>
								<th>故障描述</th>
								<th>状态</th>
								<th>开始时间</th>
								<th>耗时</th>
								<th>
									<span className="sr-only">打开</span>
								</th>
							</tr>
						</thead>
						<tbody>
							{items.map((item) => (
								<tr key={item.run_id}>
									<td>
										<button
											className="history-title"
											disabled={disabled}
											onClick={() => on_open(item.run_id)}
										>
											{item.description||"未记录故障描述"}
										</button>
										<code className="history-id">{item.run_id}</code>
									</td>
									<td>
										<span className={`status-badge ${item.status}`}>
											{item.status==="failed"&&item.error_code==="EVIDENCE_INSUFFICIENT"?"证据不足":status_labels[item.status]}
										</span>
										{(run_error_code_message(item.error_code)??item.error_detail?.message)&&<p className="history-error-detail">{run_error_code_message(item.error_code)??item.error_detail?.message}</p>}
									</td>
									<td className="nowrap">
										{new Date(item.started_at??item.created_at).toLocaleString("zh-CN",{
											month: "2-digit",
											day: "2-digit",
											hour: "2-digit",
											minute: "2-digit"
										})}
									</td>
									<td>
										{item.finished_at&&item.started_at
											? `${Math.max(0,(Date.parse(item.finished_at)-Date.parse(item.started_at))/1000).toFixed(1)}s`
											:"—"}
									</td>
									<td>
										<button
											className="icon-button"
											disabled={disabled}
											aria-label={`打开 ${item.run_id}`}
											onClick={() => on_open(item.run_id)}
										>
											<ArrowUpRight size={17} />
										</button>
									</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			)}

			{!unavailable&&!error&&items.length>0&&<div className="pagination">
				<span>第 {Math.floor(offset/12)+1} 页</span>
				<button
					className="icon-button"
					disabled={offset===0||loading}
					aria-label="上一页"
					onClick={() => set_offset(Math.max(0,offset-12))}
				>
					<ChevronLeft size={17} />
				</button>
				<button
					className="icon-button"
					disabled={!has_more||loading||Boolean(error)}
					aria-label="下一页"
					onClick={() => set_offset(offset+12)}
				>
					<ChevronRight size={17} />
				</button>
			</div>}

		</section>
	);
}
