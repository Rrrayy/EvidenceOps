// 负责控制台导航、诊断输入、运行观察和证据详情的页面组装。
"use client";
import { useEffect,useRef,useState } from "react";
import {
	AssistantRuntimeProvider,
	ComposerPrimitive,
	useExternalStoreRuntime,
	type ThreadMessageLike
} from "@assistant-ui/react";
import * as Dialog from "@radix-ui/react-dialog";
import {
	Activity,
	ArrowRight,
	ArrowUpRight,
	Check,
	ChevronRight,
	Clipboard,
	FileText,
	FlaskConical,
	History as HistoryIcon,
	Layers3,
	LoaderCircle,
	PanelRightClose,
	Plus,
	Search,
	ShieldCheck,
	Square,
	Upload,
	WifiOff,
	X
} from "lucide-react";
import { use_diagnosis } from "@/lib/use-diagnosis";
import { example_description,source_labels,status_labels,result_schema,capability_schema,type Evidence } from "@/lib/contracts";
import { EvidenceIcon,Report } from "./report";
import { Trace } from "./trace";
import { KnowledgeEvidence } from "./knowledge-evidence";
import { ParsedLogEvidence } from "./parsed-log-evidence";
import { LogSources } from "./log-sources";
import { is_parsed_log } from "@/lib/parsed-logs";
import { History } from "./history";
import { Evaluations } from "./evaluation";
import { ModelConnections,ModelSelector } from "./model-connections";
import { Storage } from "./storage";
import { evidence_number } from "@/lib/evidence";
import { diagnosis_input_error } from "@/lib/diagnosis-input";
const empty_messages: ThreadMessageLike[]=[];
type View="workspace"|"history"|"evaluation"|"connections"|"storage";
export function Console() {

	const run=use_diagnosis();
	const [model_selection,set_model_selection]=useState<
		{ connection_id: string; model_id: string; expected_version?: number }|undefined
	>(); // 工作台临时选择不修改默认值。
	const [view,set_view]=useState<View>("workspace");
	const [tab,set_tab]=useState("report");
	const [input_text,set_input_text]=useState("");
	const [draft_error,set_draft_error]=useState("");
	const [log_sources,set_log_sources]=useState<string[]>([]);
	const [selected,set_selected]=useState<Evidence|null>(null);
	const [capability,set_capability]=useState<{ persistence: boolean; provider_mode: string; storage_management?: boolean; source_mode?: string; knowledge_search?: boolean; parsed_logs?:boolean; parsed_log_sources?:string[] }|null>(null);
	const [service_revision,set_service_revision]=useState(0);
	const [service_error,set_service_error]=useState("");
	const [lookup,set_lookup]=useState("");
	const [lookup_open,set_lookup_open]=useState(false);
	const [copied,set_copied]=useState(false);
	const [elapsed,set_elapsed]=useState(0);
	const file_input=useRef<HTMLInputElement>(null);
	const evidence_trigger=useRef<HTMLElement|null>(null);
	const assistant_runtime=useExternalStoreRuntime({
		messages: empty_messages,
		convertMessage: (message) => message,
		isRunning: run.busy,
		isSendDisabled: run.active||Boolean(draft_error)||(capability?.storage_management===true&&!capability.persistence),
		onNew: async (message) => {
			const text=message.content
				.filter((part) => part.type==="text")
				.map((part) => (part.type==="text"? part.text:""))
				.join("\n");
			set_input_text(text);
			const input_error=diagnosis_input_error(text);
			set_draft_error(input_error);
			if(input_error){return;}
			const sources=capability?.parsed_logs?log_sources.filter(identity=>capability.parsed_log_sources?.includes(identity)):[];
			const description=sources.length?`${text}\n\n本次请求检查的已注册日志来源 ID：${sources.map(identity=>JSON.stringify(identity)).join("、")}。是否查询由模型根据分析需要决定。`:text;
			await run.start(description,model_selection);
		}
	});
	const status=run.state.result?.status??(run.state.events.some(event=>event.event==="run_started")?"running":null);
	const started_config=result_schema.shape.model_config.safeParse(
		run.state.events.find((event) => event.event==="run_started")?.data.model_config
	);
	const run_model=run.state.result?.model_config??(started_config.success? started_config.data:null); // 后续展示实际响应快照。
	const has_run=Boolean(run.state.run_id)||run.busy;
	useEffect(() => {

		const controller=new AbortController();
		fetch("/api/backend/capabilities",{ signal: controller.signal })
			.then(async (response) => {
				if(!response.ok) {
					throw new Error("诊断服务暂不可用");
				}
				set_capability(capability_schema.parse(await response.json()));
				set_service_error("");
			})
			.catch(() => {
				if(!controller.signal.aborted) {
					set_capability(null);
					set_service_error("诊断服务未连接");
				}
			});
		return () => controller.abort();
	},[service_revision]);
	useEffect(()=>{
		const controller=new AbortController();
		fetch("/api/backend/setup/status",{signal:controller.signal}).then(async response=>{if(!response.ok){return;}const data=await response.json();if(!controller.signal.aborted&&data.supported&&!data.setup_completed&&!window.location.search){set_view("storage");}}).catch(()=>{});
		return()=>controller.abort();
	},[]);
	useEffect(() => {
		// 允许 Strict Mode 清理后重新观察，避免刷新历史时永久停在加载状态。
		const params=new URLSearchParams(window.location.search);
		const initial_view=params.get("view");
		if(initial_view==="history"||initial_view==="evaluation"||initial_view==="connections"||initial_view==="storage") {
			set_view(initial_view);
		}
		const id=params.get("run");
		if(id) {
			void run.observe(id,true);
		}
	},[run.observe]);
	useEffect(() => {
		if(!run.state.run_id) {
			return;
		}
		if(view==="workspace") {
			window.history.replaceState(null,"",`/?run=${encodeURIComponent(run.state.run_id)}`);
		}
	},[run.state.run_id,view]);
	useEffect(() => {

		const start=run.state.result?.started_at??run.state.events[0]?.occurred_at;
		if(!start) {
			set_elapsed(0);
			return;
		}
		const update=() =>
			set_elapsed(
				Math.max(
					0,
					((run.state.result?.finished_at? Date.parse(run.state.result.finished_at):Date.now())-
						Date.parse(start))/
					1000
				)
			);
		update();
		const timer=setInterval(update,1000);
		return () => clearInterval(timer);
	},[run.state.result?.started_at,run.state.result?.finished_at,run.state.events[0]?.occurred_at]);
	function navigate(next: View) {
		set_view(next);
		window.history.replaceState(
			null,
			"",
			next==="workspace"
				? run.state.run_id
					? `/?run=${encodeURIComponent(run.state.run_id)}`
					:"/"
				:`/?view=${next}`
		);
	}
	function fill_draft(text:string){
		assistant_runtime.thread.composer.setText(text);
		set_input_text(text);
		set_draft_error(text?diagnosis_input_error(text):"");
	}
	function new_run() {
		if(run.active) {
			return;
		}
		run.reset();
		fill_draft("");
		set_log_sources([]);
		set_tab("report");
		navigate("workspace");
		window.history.replaceState(null,"","/");
	}
	function open_run(id: string) {
		if(run.active) {
			return;
		}
		set_view("workspace");
		set_tab("report");
		set_lookup_open(false);
		void run.observe(id.trim(),true);
		window.history.replaceState(null,"",`/?run=${encodeURIComponent(id.trim())}`);
	}
	function open_evidence(item:Evidence){
		evidence_trigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
		set_selected(item);
	}
	async function import_text(file: File) {
		try {
			if(file.size>300_000) {
				throw new Error("文本文件不能超过 300 KB");
			}
			if(!/\.(txt|log|json|jsonl|md|py|java|go|js|ts|cpp|c|h)$/i.test(file.name)) {
				throw new Error("请选择纯文本日志、代码或 JSON 文件");
			}
			const text=await file.text();
			if(text.includes("\0")||text.length>100_000) {
				throw new Error("文件包含非文本内容或超过 100000 字符");
			}
			fill_draft(text);
			run.set_error("");
		} catch(reason) {
			run.set_error(reason instanceof Error? reason.message:"文件无法读取");
		}
	}
	async function copy_text(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			set_copied(true);
			setTimeout(() => set_copied(false),1800);
		} catch {
			run.set_error("复制失败，请手动选择文本复制");
		}
	}
	return (
		<AssistantRuntimeProvider runtime={assistant_runtime}>
			<div className="app-shell">

				<aside className="sidebar">
					<a className="brand" href="/" aria-label="EvidenceOps 首页">
						<span className="brand-symbol">
							<Layers3 size={23} />
						</span>
						<span>
							Evidence<span className="brand-weight">Ops</span>
						</span>
					</a>
					<div className="sidebar-caption">故障诊断工作空间</div>
					<button className="new-button" onClick={new_run} disabled={run.active}>
						<Plus size={17} />
						新建诊断
					</button>
					<nav aria-label="主导航">
						<button
							className={view==="workspace"? "nav-item active":"nav-item"}
							onClick={() => navigate("workspace")}
						>
							<Activity size={18} />
							诊断工作台
						</button>
						<button
							className={view==="history"? "nav-item active":"nav-item"}
							onClick={() => navigate("history")}
						>
							<HistoryIcon size={18} />
							运行历史
						</button>
						<button
							className={view==="evaluation"? "nav-item active":"nav-item"}
							onClick={() => navigate("evaluation")}
						>
							<FlaskConical size={18} />
							评测结果
						</button>
					</nav>
					<button
						className={view==="connections"? "nav-item active":"nav-item"}
						onClick={() => navigate("connections")}
					>
						<ShieldCheck size={18} />
						设置 · 模型连接
					</button>
					<button className={view==="storage"?"nav-item active":"nav-item"} onClick={()=>navigate("storage")}><Layers3 size={18}/>数据与存储</button>
					<div className="sidebar-bottom">
						<div className="readonly-note">
							<ShieldCheck size={16} />
							<span>只读证据查询</span>
						</div>
						<p>结论有引用，过程可回查。</p>
						<div className="environment">
							<span className={`service-dot ${capability? "online":""}`} />
							<span>{service_error||(!capability? "连接服务中":"本地诊断服务")}</span>
							<small>{capability? (capability.persistence? "持久化已启用":capability.storage_management?"存储需要配置":"内存模式"):""}</small>
						</div>
					</div>
				</aside>

				<div className="main-shell">
					<header className="topbar">
						<div className="breadcrumb">
							工作空间
							<ChevronRight size={13} />
							<strong>
								{view==="workspace"
									? "诊断工作台"
									:view==="history"
										? "运行历史"
										:view==="connections"
											? "设置 / 模型连接"
											:view==="storage"?"数据与存储":"评测结果"}
							</strong>
						</div>
						<div className="topbar-actions">
							{capability?.source_mode==="samples"&&<span className="sample-badge">样例数据</span>}
							<button
								className="lookup-button"
								onClick={() => set_lookup_open(true)}
								disabled={run.active}
							>
								<Search size={15} />
								查询运行 ID
							</button>
							<span className="workspace-label">
								<span className="workspace-avatar">E</span>EvidenceOps
							</span>
						</div>
					</header>

					<main>
						{view==="storage"? (
							<Storage on_models={()=>navigate("connections")} on_complete={()=>navigate("workspace")} on_changed={()=>set_service_revision(value=>value+1)}/>
						):view==="connections"? (
							<ModelConnections />
						):view==="history"? (
							<History on_open={open_run} disabled={run.active} on_storage={()=>navigate("storage")} />
						):view==="evaluation"? (
							<Evaluations />
						):(
							<div className="workspace">

								<div className="diagnosis-main">
									{!has_run? (
										<>
											<div className="welcome">
												<h1>诊断工作台</h1>
												<p className="welcome-description">描述故障，核对证据，追踪每次调用。</p>
											</div>
											<ModelSelector
												mode={capability?.provider_mode}
												selection={model_selection}
												on_select={set_model_selection}
												on_manage={() => navigate("connections")}
											/>
											<LogSources capability={capability} error={service_error} selected={log_sources} on_retry={()=>set_service_revision(value=>value+1)} on_source={identity=>set_log_sources(current=>current.includes(identity)?current.filter(item=>item!==identity):[...current,identity])}/>
											<ComposerPrimitive.Root className="composer">
												<div className="composer-label">
													<span>
														<FileText size={16} />
														故障描述与上下文
													</span>
													<span>纯文本输入</span>
												</div>
												<ComposerPrimitive.Input
													className="composer-input"
													aria-label="故障描述"
													aria-describedby="diagnosis-input-help"
													aria-invalid={Boolean(draft_error)}
													onChange={(event) => set_draft_error(event.target.value? diagnosis_input_error(event.target.value):"")}
													placeholder={
														"例如：订单服务间歇性超时，发生在今天 10:00–10:10。\n请补充服务、环境、时间窗口，以及相关日志或错误堆栈…"
													}
													submitMode="ctrlEnter"
													minRows={7}
													maxRows={15}
													maxLength={100000}
													addAttachmentOnPaste={false}
												/>
												<p id="diagnosis-input-help" className="muted" aria-live="polite">{draft_error||"请填写故障现象、错误信息或日志；仅有标点或符号不能开始诊断。"}</p>
												<div className="composer-footer">
													<button
														className="text-button"
														type="button"
														onClick={() => file_input.current?.click()}
													>
														<Upload size={15} />
														导入文本
													</button>
													<div>
														<span className="shortcut">Ctrl / ⌘ + Enter</span>
														<ComposerPrimitive.Send className="primary-button">
															开始诊断
															<ArrowRight size={17} />
														</ComposerPrimitive.Send>
													</div>
												</div>
											</ComposerPrimitive.Root>
											<input
												ref={file_input}
												className="sr-only"
												type="file"
												accept=".txt,.log,.json,.jsonl,.md,.py,.java,.go,.js,.ts,.cpp,.c,.h"
												aria-label="选择文本文件"
												onChange={(event) => {
													const file=event.target.files?.[0];
													if(file) {
														void import_text(file);
													}
													event.target.value="";
												}}
											/>
											<div className="example-row">
												<span>先了解诊断过程</span>
												<button
													onClick={() =>
														fill_draft(example_description)
													}
												>
													<span className="example-dot" />
													RPC 超时示例
													<ArrowUpRight size={15} />
												</button>
											</div>
											<div className="input-note">
												<ShieldCheck size={14} />
												<p>
													{model_selection?.connection_id&&
														model_selection.connection_id!=="system"
														? capability?.source_mode==="samples"?"本次使用所选模型分析仓库样例数据；受控日志是否可查询以上方来源声明为准。":"本次使用所选模型连接，未就绪的模型将由后端拒绝执行；证据范围仍限于已接入的数据源。"
														:capability?.provider_mode==="mock"
															? "当前为 Mock 演示模式，返回固定样本诊断；请使用 RPC 超时示例。"
															:"当前查询接入的日志、指标和配置。示例使用仓库本地样本；输入文本不会自动成为已验证证据。"}
												</p>
											</div>
										</>
									):(
										<>
											<div className="run-heading">
												<div>
													<span className="section-label">诊断档案</span>
													<h1>
														{(run.state.result?.description??input_text)===
															example_description
															? "RPC 超时与线程池异常排查"
															:(run.state.result?.description??input_text).slice(
																0,
																60
															)||"故障诊断"}
													</h1>
												</div>
												<span className={`status-badge ${status??"unknown"}`}>
													{status?status==="failed"&&run.state.result?.error_code==="EVIDENCE_INSUFFICIENT"?"证据不足":status_labels[status]:run.error?"状态未确认":run.state.run_id?"正在读取":"正在创建"}
												</span>
											</div>
											<div className="run-meta">
												<button
													className="run-id"
													title="复制运行 ID"
													onClick={() => void copy_text(run.state.run_id??"")}
													disabled={!run.state.run_id}
												>
													<Clipboard size={13} />
													{run.state.run_id??"等待运行 ID"}
												</button>
												<span>{elapsed.toFixed(1)}s</span>
												{copied&&<span className="good">已复制</span>}
											</div>
											<details className="submitted-input">
												<summary>本次模型配置</summary>
												<p>
													供应商：{run_model?.provider_id??run_model?.provider??"未记录"}
													模型 ID：{run_model?.model_id??"未记录"}
												</p>
												<p>
													连接名称：
													{run_model?.connection_name??"未记录"}
													配置版本：
													{run_model?.config_version??"未记录"}
												</p>
												<p className="drawer-note">
													历史以本次运行启动时的配置为准；旧档案缺失的信息显示未记录。
												</p>
											</details>
											<details className="submitted-input">
												<summary>
													<FileText size={15} />
													查看原始输入
												</summary>
												<pre>{run.state.result?.description??input_text}</pre>
											</details>
											<div className="detail-tabs" role="tablist" aria-label="诊断详情">
												{[
													{ id: "report",label: "诊断报告" },
													{
														id: "evidence",
														label: `证据${run.state.result? ` ${run.state.result.evidences.length}`:""}`
													},
													{ id: "trace",label: "执行轨迹" }
												].map((item) => (
													<button
														role="tab"
														aria-selected={tab===item.id}
														tabIndex={tab===item.id? 0:-1}
														onKeyDown={(event) => {
															const ids=["report","evidence","trace"];
															const current=ids.indexOf(tab);
															const next=
																event.key==="ArrowRight"
																	? ids[(current+1)%3]
																	:event.key==="ArrowLeft"
																		? ids[(current+2)%3]
																		:event.key==="Home"
																			? ids[0]
																			:event.key==="End"
																				? ids[2]
																				:null;
															if(next) {
																event.preventDefault();
																set_tab(next);
																document.getElementById(`tab-${next}`)?.focus();
															}
														}}
														aria-controls="detail-panel"
														id={`tab-${item.id}`}
														className={tab===item.id? "selected":""}
														key={item.id}
														onClick={() => set_tab(item.id)}
													>
														{item.label}
													</button>
												))}
											</div>
											<div id="detail-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
												{tab==="trace"? (
													<Trace events={run.state.events} result={run.state.result} />
												):tab==="evidence"? (
													<div className="evidence-list">
														{run.state.result?.evidences.length? (
															run.state.result.evidences.map((item,index) => (
																<button
																	className="evidence-row"
																	key={item.evidence_id}
																	onClick={() => open_evidence(item)}
																>
																	<span className="evidence-type">
																		<span className="evidence-number">{evidence_number(run.state.result?.evidences??[],item.evidence_id)}</span>
																		<EvidenceIcon source={item.source} />
																		{source_labels[item.source]??item.source}{" "}
																	</span>
																	<p>{item.summary}</p>
																	<span>
																		{is_parsed_log(item)?"导入 ":""}{new Date(item.observed_at).toLocaleString(
																			"zh-CN"
																		)}
																		<ArrowUpRight size={16} />
																	</span>
																</button>
															))
														):(
															<div className="empty-panel">
																<FileText size={30} />
																<h2>证据尚未归档</h2>
																<p>
																	完整证据在诊断收尾后提供；工具执行成功不等于证据已经保存。
																</p>
															</div>
														)}
													</div>
												):run.state.result? (
													<Report result={run.state.result} on_evidence={open_evidence} />
												):(
													<div className="working-state">
														<div className="working-symbol">
															<Activity size={28} />
														</div>
														<h2>
															{run.state.connection==="disconnected"
																? "观察连接已中断"
																:status?"正在沿着证据排查":"正在读取运行档案"}
														</h2>
														<p>
															{run.state.connection==="disconnected"
																? "诊断可能仍在后台执行，请恢复观察确认结果。"
																:status?"执行过程在右侧更新，完成后在这里展示报告。":"正在确认已保存的运行状态，不会重新执行诊断。"}
														</p>
													</div>
												)}
											</div>
										</>
									)}

									{run.error&&(
										<div className="error-banner" role="alert">
											<WifiOff size={17} />
											<span>{run.error}</span>
										</div>
									)}
									{run.state.connection==="disconnected"&&(
										<div className="reconnect-banner">
											<span>
												{run.state.run_id
													? "观察已断开，后台状态需回查。"
													:"尚未取得运行 ID，创建结果未知。请查询历史，避免重复提交。"}
											</span>
											{run.state.run_id&&(
												<button
													className="secondary-button"
													disabled={run.busy}
													onClick={() => void run.observe(run.state.run_id!,false)}
												>
													恢复观察
												</button>
											)}
										</div>
									)}

								</div>
								<aside className="execution-panel">
									<div className="execution-heading">
										<span>
											<Activity size={17} />
											执行过程
										</span>
										<span className="live-indicator">
											{run.busy? (
												<>
													<span />
													观察中
												</>
											):has_run? (
												(run.state.connection==="disconnected"?"观察已中断":run.state.result?"已记录":"状态待确认")
											):(
												"等待开始"
											)}
										</span>
									</div>
									{has_run? (
										<>
											<div className="execution-summary">
												<span>{run.state.events.length} 条已接收事件</span>
												{run.active&&run.state.run_id&&(status==="running"||status==="pending")&&(
													<button
														className="cancel-button"
														disabled={run.cancel_pending}
														onClick={() => void run.cancel()}
													>
														{run.cancel_pending? (
															<LoaderCircle size={13} className="spin" />
														):(
															<Square size={11} />
														)}{" "}
														{run.cancel_pending||run.state.cancel_requested
															? "等待取消确认"
															:"取消诊断"}
													</button>
												)}
											</div>
											<Trace events={run.state.events} result={run.state.result} />
										</>
									):(
										<div className="execution-empty">
											<h2>等待诊断开始</h2>
											<p>模型分析、证据查询、耗时与失败位置将在这里按实际调用记录。</p>
										</div>
									)}
									<div className="execution-footnote">
										<ShieldCheck size={14} />
										<p>工具仅进行只读查询。排查建议不会自动执行。</p>
									</div>
								</aside>

							</div>
						)}
					</main>
					<footer className="app-footer">
						<span>EvidenceOps</span>
						<span>基于证据的故障诊断</span>
					</footer>
				</div>

				<Dialog.Root
					open={Boolean(selected)}
					onOpenChange={(open) => {
						if(!open) {
							set_selected(null);
						}
					}}
				>
					<Dialog.Portal>
						<Dialog.Overlay className="dialog-overlay" />
						<Dialog.Content className={`evidence-drawer ${selected&&is_parsed_log(selected)?"log-evidence-drawer":""}`} onCloseAutoFocus={event=>{event.preventDefault();evidence_trigger.current?.focus();}}>
							<div className="drawer-heading">
								<span className="section-label">引用证据</span>
								<Dialog.Close className="icon-button" aria-label="关闭证据">
									<PanelRightClose size={20} />
								</Dialog.Close>
							</div>
							<Dialog.Title className="drawer-title">
								{selected? (
									<>
										<EvidenceIcon source={selected.source} />
										<span className="evidence-number">{evidence_number(run.state.result?.evidences??[],selected.evidence_id)}</span>
										{selected.source==="knowledge"?"知识参考":`${source_labels[selected.source]??selected.source}证据`}
									</>
								):(
									"证据详情"
								)}
							</Dialog.Title>
							<Dialog.Description className="drawer-description">
								{selected?.source==="knowledge"?"运行时检索到的参考资料与片段原文。":"诊断判断引用的实际观测摘要与来源。"}
							</Dialog.Description>
							{selected&&(
								<>
									{selected.source==="knowledge"&&<KnowledgeEvidence evidence={selected} />}
									{is_parsed_log(selected)&&<ParsedLogEvidence key={selected.evidence_id} evidence={selected}/>}
									<div className="evidence-summary">
										<h3>{selected.source==="knowledge"?"参考摘要":"观测摘要"}</h3>
										<p>{selected.summary}</p>
									</div>
									<dl className="evidence-metadata">
										<dt>{selected.source==="knowledge"?"检索时间":is_parsed_log(selected)||selected.source_metadata?.observed_at_basis==="import_time"?"导入观测时间（非事件时间）":"观测时间"}</dt>
										<dd>{new Date(selected.observed_at).toLocaleString("zh-CN")}</dd>
										<dt>来源定位</dt>
										<dd>
											<code>{selected.source_ref}</code>
										</dd>
										<dt>{selected.source==="knowledge"?"内容版本":"来源版本"}</dt>
										<dd>{selected.source_version??"未提供"}</dd>
										<dt>证据 ID</dt>
										<dd>
											<code>{selected.evidence_id}</code>
										</dd>
										<dt>内容哈希</dt>
										<dd>
											<code>{selected.content_hash}</code>
										</dd>
									</dl>
									<button
										className="secondary-button"
										onClick={() => void copy_text(JSON.stringify(selected,null,2))}
									>
										<Clipboard size={15} />
										{copied? "已复制":"复制证据信息"}
									</button>
									<p className="drawer-note">
										{selected.source==="knowledge"?"片段与来源以本次运行归档为准，不受后续知识资料更新影响。":is_parsed_log(selected)?"此处展示本次运行的归档快照，不会重新读取来源文件。证据编号代表整组日志，并非单条事件序号。":"来源定位用于核对样本。当前接口提供摘要，不提供完整原始日志正文。"}
									</p>
								</>
							)}
						</Dialog.Content>
					</Dialog.Portal>
				</Dialog.Root>

				<Dialog.Root open={lookup_open} onOpenChange={set_lookup_open}>
					<Dialog.Portal>
						<Dialog.Overlay className="dialog-overlay" />
						<Dialog.Content className="lookup-dialog">
							<Dialog.Title>查询运行档案</Dialog.Title>
							<Dialog.Description>输入完整运行 ID，读取已有诊断；不会重新调用模型。</Dialog.Description>
							<form
								onSubmit={(event) => {
									event.preventDefault();
									if(lookup.trim()) {
										open_run(lookup);
									}
								}}
							>
								<label htmlFor="run-lookup">运行 ID</label>
								<input
									id="run-lookup"
									placeholder="run-…"
									value={lookup}
									maxLength={200}
									onChange={(event) => set_lookup(event.target.value)}
								/>
								<button className="primary-button" disabled={!lookup.trim()}>
									打开档案
									<ArrowRight size={16} />
								</button>
							</form>
							<Dialog.Close className="dialog-close icon-button" aria-label="关闭查询">
								<X size={18} />
							</Dialog.Close>
						</Dialog.Content>
					</Dialog.Portal>
				</Dialog.Root>

			</div>
		</AssistantRuntimeProvider>
	);
}
