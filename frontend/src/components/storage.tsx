// 负责首次安装引导、存储配置、维护进度及备份恢复页面。
"use client";
import { useEffect,useRef,useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Archive,ArrowRight,Check,Database,Download,HardDrive,LoaderCircle,RefreshCw,Upload,X } from "lucide-react";
import { storage_request,storage_schema,type StorageStatus,type StorageOperation } from "@/lib/storage";
const storage_labels:Record<string,string>={ready:"正常",initializing:"正在初始化",maintenance:"维护中",needs_upgrade:"需要升级",uninitialized:"尚未初始化",degraded:"存储不可用",failed:"启动失败",unsupported_version:"版本不兼容"};
type StorageAction="initialize"|"switch"|"backup"|"restore";
export function Storage({on_models,on_complete,on_changed}: {on_models:()=>void;on_complete:()=>void;on_changed:()=>void}){
	const [status,set_status]=useState<StorageStatus|null>(null);
	const [loading,set_loading]=useState(true);
	const [error,set_error]=useState("");
	const [step,set_step]=useState(0);
	const [action,set_action]=useState<StorageAction|null>(null);
	const [mode,set_mode]=useState("sqlite");
	const [host,set_host]=useState("127.0.0.1");
	const [port,set_port]=useState("5433");
	const [database,set_database]=useState("evidenceops");
	const [user,set_user]=useState("evidenceops");
	const [password,set_password]=useState("");
	const [portable,set_portable]=useState(false);
	const [passphrase,set_passphrase]=useState("");
	const [backup_id,set_backup_id]=useState("");
	const [confirmation,set_confirmation]=useState("");
	const [check_result,set_check_result]=useState("");
	const [busy,set_busy]=useState(false);
	const [operation,set_operation]=useState<StorageOperation|null>(null);
	const [dirty,set_dirty]=useState(false);
	const [model_note,set_model_note]=useState("正在检查已配置模型…");
	const request=useRef<AbortController|null>(null);
	const generation=useRef(0);
	const lock=useRef(false);
	const input=useRef<HTMLInputElement>(null);
	const mounted=useRef(true);
	async function refresh(signal?:AbortSignal,synchronize=true){
		try{const data=storage_schema.parse(await storage_request("storage/status",undefined,signal));if(signal?.aborted||!mounted.current){return;}set_status(data);set_error("");if(synchronize){set_operation(current=>data.operations.find(item=>item.status==="running"||item.status==="waiting")??data.operations.find(item=>item.id===current?.id)??null);}return data;}
		catch(reason){if(!signal?.aborted&&mounted.current){set_error(reason instanceof Error?reason.message:"存储状态读取失败");}}
		finally{if(!signal?.aborted&&mounted.current){set_loading(false);}}
	}
	useEffect(()=>{
		mounted.current=true;const controller=new AbortController();
		void refresh(controller.signal);
		storage_request("model-connections",undefined,controller.signal).then(data=>{if(controller.signal.aborted){return;}const ready=data.items?.filter((item:{status:string})=>item.status==="ready").length??0;set_model_note(ready?`${ready} 个用户连接已验证，可在工作台选择。`:data.system?.mock?"当前可使用系统 Mock 演示；接入自己的模型后才能进行真实模型分析。":"系统模型已配置，也可以添加自己的模型连接。");}).catch(()=>{if(!controller.signal.aborted){set_model_note("模型连接暂不可读取，请到模型连接页检查。");}});
		return()=>{mounted.current=false;controller.abort();request.current?.abort();};
	},[]);
	useEffect(()=>{
		const protect=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();}};
		window.addEventListener("beforeunload",protect);return()=>window.removeEventListener("beforeunload",protect);
	},[dirty]);
	useEffect(()=>{
		if(!operation||["succeeded","failed"].includes(operation.status)){return;}
		const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
		const poll=async()=>{
			try{const result=await storage_request(`storage/operations/${encodeURIComponent(operation.id)}`,undefined,controller.signal);if(controller.signal.aborted){return;}if(result.status==="succeeded"||result.status==="failed"){await refresh(controller.signal,false);if(controller.signal.aborted){return;}set_operation(result);on_changed();if(result.status==="succeeded"){set_action(null);set_dirty(false);set_password("");set_passphrase("");if(result.action==="complete_setup"){on_complete();}}else{set_error(result.message);set_dirty(true);}return;}set_operation(result);} // 先刷新存储再发布终态，避免 effect 清理取消状态刷新。
			catch(reason){if(!controller.signal.aborted){set_error(reason instanceof Error?reason.message:"维护进度读取失败；任务可能仍在执行");}}
			if(!controller.signal.aborted){timer=setTimeout(poll,800);}
		};timer=setTimeout(poll,400);return()=>{controller.abort();clearTimeout(timer);};
	},[operation?.id,operation?.status]);
	const pending=operation?.status==="waiting"||operation?.status==="running"||status?.state==="maintenance";
	function changed(){generation.current++;request.current?.abort();set_check_result("");set_dirty(true);}
	function open(value:StorageAction,identity=""){
		set_action(value);set_mode(value==="restore"?"sqlite":status?.mode??"sqlite");set_host(status?.postgres.host??"127.0.0.1");set_port(String(status?.postgres.port??5433));set_database(status?.postgres.database??"evidenceops");set_user(status?.postgres.user??"evidenceops");set_password("");set_passphrase("");set_portable(false);set_backup_id(identity);set_confirmation("");set_check_result("");set_error("");set_dirty(false);
	}
	function close(){
		if(busy||pending){return;}
		if(dirty&&!window.confirm("放弃未提交的存储配置？密码草稿不会保留。")){return;}
		generation.current++;request.current?.abort();set_action(null);set_dirty(false);set_password("");set_passphrase("");
	}
	function storage_input(){return{mode,host,port:Number(port),database,user,password:password||undefined};}
	async function check(){
		if(lock.current){return;}lock.current=true;set_busy(true);set_error("");const current=++generation.current;request.current?.abort();const controller=new AbortController();request.current=controller;
		try{const result=await storage_request("storage/check",storage_input(),controller.signal);if(current===generation.current){set_check_result(result.message);}} // 响应绑定当前表单。
		catch(reason){if(current===generation.current&&!controller.signal.aborted){set_error(reason instanceof Error?reason.message:"连接检查失败");}}
		finally{lock.current=false;set_busy(false);}
	}
	async function submit(value:StorageAction|"complete_setup"){
		if(lock.current||pending||!status){return;}lock.current=true;set_busy(true);set_error("");
		try{const result=await storage_request("storage/operations",{action:value,expected_version:status.version,request_id:crypto.randomUUID(),storage:value==="switch"||value==="initialize"||value==="restore"?storage_input():undefined,backup_id:value==="restore"?backup_id:undefined,passphrase:value==="restore"||portable?passphrase||undefined:undefined,confirmation:value==="restore"?confirmation:undefined});set_operation(result);set_dirty(false);}
		catch(reason){set_error(reason instanceof Error?reason.message:"维护请求失败，请检查后重试");}
		finally{lock.current=false;set_busy(false);}
	}
	async function import_file(file:File){
		if(lock.current||pending){return;}lock.current=true;set_busy(true);set_error("");
		try{if(file.size>100*1024*1024){throw new Error("备份不能超过 100 MB");}await storage_request("storage/backups/import",await file.text(),undefined,true);await refresh();} // 原文本保留浮点数表示，后端负责哈希和结构验证。
		catch(reason){set_error(reason instanceof Error?reason.message:"备份无法导入");}
		finally{lock.current=false;set_busy(false);}
	}
	return(<section className="storage-page">
		<div className="page-heading"><div><h1>{status&&!status.setup_completed?"首次安装设置":"数据与存储"}</h1><p>{status&&!status.setup_completed?"准备存储与模型，确认诊断的数据来源。":"检查诊断存储，管理备份与恢复。"}</p></div><button className="icon-button" aria-label="刷新存储状态" disabled={busy} onClick={()=>void refresh()}><RefreshCw size={18}/></button></div>
		{error&&<div className="error-banner" role="alert">{error}</div>}{loading&&!status&&<p className="loading-state" role="status">正在检查安装与存储…</p>}
		{status&&<>
			{!status.setup_completed&&<div className="setup-panel"><ol className="setup-steps" aria-label="首次安装步骤">{["保存诊断历史","接入诊断模型","确认数据来源"].map((label,index)=><li key={label}><button aria-current={step===index?"step":undefined} onClick={()=>set_step(index)}><span>{index+1}</span>{label}</button></li>)}</ol>
				{step===0?<div><h2>{status.state==="ready"?"诊断历史已开启":"先准备诊断存储"}</h2><p>{status.state==="ready"?"关闭或重启应用后仍可查看报告、证据和执行记录。":"下方可以检查存储配置并初始化，完成后继续。"}</p><button className="primary-button" disabled={status.state!=="ready"||pending} onClick={()=>set_step(1)}>继续配置模型<ArrowRight size={16}/></button></div>:step===1?<div><h2>选择诊断模型</h2><p>{model_note}</p><div className="storage-actions"><button className="secondary-button" onClick={on_models}>管理模型连接</button><button className="primary-button" onClick={()=>set_step(2)}>继续确认数据来源<ArrowRight size={16}/></button></div></div>:<div><h2>当前使用内置样例数据</h2><p>日志、指标和配置来自 EvidenceOps 样例，不会自动读取客户业务系统。输入故障文本也不会自动接入客户日志。</p><p className="field-note">客户数据源配置尚未开放。本次可以先体验样例诊断，后续按实际 Connector 能力接入。</p><button className="primary-button" disabled={busy||pending||status.state!=="ready"} onClick={()=>void submit("complete_setup")}>确认并进入工作台<ArrowRight size={16}/></button></div>}
			</div>}
			<div className={`storage-overview ${status.state==="ready"?"ready":"attention"}`} role="status"><div className="storage-overview-icon">{status.mode==="sqlite"?<HardDrive size={24}/>:<Database size={24}/>}</div><div><h2>{status.mode==="sqlite"?"本机存储":"PostgreSQL"}<span className="storage-state">{storage_labels[status.state]??status.state}</span></h2><p>{status.message}</p></div><button className="secondary-button" disabled={busy||pending} onClick={()=>open(status.state==="ready"?"switch":"initialize")}>{status.state==="ready"?"更改存储方式":"检查与初始化"}</button></div>
			<dl className="storage-facts storage-health"><div><dt>诊断准入</dt><dd>{status.state==="ready"&&!pending?"可开始诊断":"暂时暂停"}</dd></div><div><dt>当前诊断</dt><dd>{status.active_runs}<span> 个运行</span></dd></div><div><dt>最近备份记录</dt><dd className={!status.backups.length?"storage-no-backup":""}>{status.backups.length?new Date(status.backups.at(-1)!.created_at).toLocaleString("zh-CN"):"尚未备份"}</dd></div></dl>
			<details className="storage-location"><summary>存储位置与版本<span>{status.mode==="sqlite"?"SQLite":"PostgreSQL"} · {status.schema_version??"尚未就绪"}</span></summary><dl><div><dt>当前数据库</dt><dd><code>{status.database_display}</code></dd></div><div><dt>数据目录</dt><dd><code>{status.data_location}</code></dd></div><div><dt>数据库版本</dt><dd><code>{status.schema_version??"尚未就绪"}</code></dd></div></dl><p>程序升级保留此目录。备份不包含未接入的原始日志。</p></details>
			{operation&&<div className={`storage-operation ${operation.status}`} role="status">{pending?<LoaderCircle size={18} className="spin"/>:operation.status==="succeeded"?<Check size={18}/>:<X size={18}/>}<div><strong>{operation.message}</strong><p>{pending?"当前维护禁止新诊断，已有诊断不会被自动取消。关闭页面后操作继续。":"任务状态已由后端记录。"}</p><code>{operation.id}</code></div></div>}
			<div className="storage-section-heading"><div><h2>备份与恢复</h2><p>恢复前自动保留当前档案；模型连接需重新验证。</p></div><div className="storage-actions"><button className="secondary-button" disabled={busy||pending} onClick={()=>input.current?.click()}><Upload size={15}/>导入备份</button><button className="primary-button" disabled={status.state!=="ready"||busy||pending} onClick={()=>open("backup")}><Archive size={15}/>创建备份</button></div><input className="sr-only" ref={input} type="file" accept=".json,application/json" aria-label="选择诊断备份" onChange={event=>{const file=event.target.files?.[0];if(file){void import_file(file);}event.target.value="";}}/></div>
			{status.backups.length?<div className="table-wrap"><table><thead><tr><th>备份</th><th>创建时间</th><th>大小</th><th>凭据</th><th>操作</th></tr></thead><tbody>{[...status.backups].reverse().map(item=><tr key={item.id}><td><span className="backup-name"><Archive size={15}/>{item.label}</span><code className="history-id" title={item.id}>{item.id}</code></td><td className="nowrap">{new Date(item.created_at).toLocaleString("zh-CN")}</td><td>{(item.size_bytes/1024).toFixed(1)} KB</td><td>{item.credentials_included?"口令加密":"不含密钥"}</td><td><div className="storage-actions"><a className="text-button" href={`/api/backend/storage/backups/${encodeURIComponent(item.id)}`} download><Download size={14}/>下载</a><button className="text-button" disabled={busy||pending} onClick={()=>open("restore",item.id)}>恢复</button></div></td></tr>)}</tbody></table></div>:<div className="storage-empty"><Archive size={20}/><p>还没有备份。建议在升级或换机前创建一份。</p></div>}
			<details className="storage-advanced"><summary>高级说明与部署边界</summary><p>当前为本机、单租户、单 API 实例。PostgreSQL 不自动开启远程访问或多人权限；未实现自动定时备份与自动历史清理。逻辑备份上限 100 MB，大型数据库请使用管理员数据库备份。</p><p>默认备份不包含可迁移密钥；恢复后需要重新填写 API Key。选择携带凭据时，备份以独立口令加密，换机后由目标账号重新保护。仅有本机 Windows 密钥文件并不保证能在其他账号解密。</p><p>现有证据档案保存摘要、来源和哈希，不含未接入的原始日志或外部附件。Embedding 与 Rerank 仍独立管理。</p></details>
		</>}
		<Dialog.Root open={action!==null} onOpenChange={value=>{if(!value){close();}}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="connection-drawer storage-drawer" onInteractOutside={event=>{event.preventDefault();close();}} onEscapeKeyDown={event=>{event.preventDefault();close();}}>
			<div className="drawer-heading"><span className="section-label">数据与存储</span><button className="icon-button" aria-label="关闭存储表单" disabled={busy||pending} onClick={close}><X size={20}/></button></div><Dialog.Title className="drawer-title">{action==="backup"?"创建诊断备份":action==="restore"?"恢复诊断备份":action==="initialize"?"检查与初始化存储":"更改存储方式"}</Dialog.Title><Dialog.Description className="drawer-description">{action==="restore"?"恢复会替换当前历史与模型连接，先保留当前档案副本。已有运行不会被自动取消。":action==="backup"?"备份包括诊断历史、证据摘要、执行事件和模型连接配置。":"等待已有诊断与验证结束，再备份、检查目标并执行维护。"}</Dialog.Description>
			<form className="connection-form" onSubmit={event=>{event.preventDefault();if(action){void submit(action);}}}>
				{(action==="switch"||action==="initialize"||action==="restore")&&<><label htmlFor="storage-mode">存储方式</label><select id="storage-mode" value={mode} disabled={busy||pending} onChange={event=>{set_mode(event.target.value);changed();}}><option value="sqlite">本机存储 · 不需要安装数据库</option><option value="postgres">连接 PostgreSQL</option></select>{mode==="postgres"?<><label htmlFor="storage-host">数据库主机</label><input id="storage-host" value={host} disabled={busy||pending} required maxLength={253} onChange={event=>{set_host(event.target.value);changed();}}/><label htmlFor="storage-port">端口</label><input id="storage-port" type="number" min={1} max={65535} value={port} disabled={busy||pending} required onChange={event=>{set_port(event.target.value);changed();}}/><label htmlFor="storage-database">数据库名称</label><input id="storage-database" value={database} disabled={busy||pending} required maxLength={128} onChange={event=>{set_database(event.target.value);changed();}}/><label htmlFor="storage-user">数据库账号</label><input id="storage-user" value={user} autoComplete="username" disabled={busy||pending} required maxLength={128} onChange={event=>{set_user(event.target.value);changed();}}/><label htmlFor="storage-password">数据库密码</label><input id="storage-password" type="password" value={password} autoComplete="new-password" disabled={busy||pending} placeholder={status?.postgres.password_configured?"密码已配置，留空保留":"填写数据库密码"} onChange={event=>{set_password(event.target.value);changed();}}/><button className="secondary-button" type="button" disabled={busy||pending} onClick={()=>void check()}>检查数据库连接</button><p className="field-note" role="status">{check_result||"连接检查不会修改业务数据；初始化时才执行迁移与真实读写验证。目标已有诊断数据时，不会自动覆盖或合并。"}</p></>:<p className="field-note">数据保存在安装目录以外的本机数据目录。切换时先迁移并校验原档案，不删除原存储文件。</p>}</>}
				{action==="backup"&&<><label className="storage-checkbox"><input type="checkbox" checked={portable} disabled={busy||pending} onChange={event=>{set_portable(event.target.checked);changed();}}/>包含可迁移的模型凭据</label><p className="field-note">默认不含 API Key。勾选后用独立备份口令加密，请妥善保管。</p>{portable&&<><label htmlFor="backup-passphrase">备份口令</label><input id="backup-passphrase" type="password" value={passphrase} autoComplete="new-password" minLength={12} required disabled={busy||pending} onChange={event=>{set_passphrase(event.target.value);changed();}}/></>}</>}
				{action==="restore"&&<><p className="notice">恢复到本机存储时采用新文件，原数据库保留。PostgreSQL 恢复要求目标业务库为空。旧报告引用保持原样，模型能力需要重新验证。</p>{status?.backups.find(item=>item.id===backup_id)?.credentials_included&&<><label htmlFor="restore-passphrase">备份口令</label><input id="restore-passphrase" type="password" value={passphrase} autoComplete="off" required disabled={busy||pending} onChange={event=>{set_passphrase(event.target.value);changed();}}/></>}<label htmlFor="restore-confirmation">输入“恢复备份”确认替换</label><input id="restore-confirmation" value={confirmation} autoComplete="off" required disabled={busy||pending} onChange={event=>{set_confirmation(event.target.value);changed();}}/></>}
				{error&&<p className="connection-error" role="alert">{error}</p>}{pending&&<p className="notice" role="status">{operation?.message??"后台维护正在执行"}</p>}
				<div className="connection-form-footer"><button className="text-button" type="button" disabled={busy||pending} onClick={close}>取消</button><button className="primary-button" disabled={busy||pending||(action==="restore"&&confirmation!=="恢复备份")}>{busy||pending?<><LoaderCircle size={15} className="spin"/>处理中…</>:action==="backup"?"创建并校验备份":action==="restore"?"确认恢复":action==="initialize"?"初始化并启用":"备份并切换"}</button></div>
			</form>
		</Dialog.Content></Dialog.Portal></Dialog.Root>
	</section>);
}
