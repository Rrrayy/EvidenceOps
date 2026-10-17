// 负责展示后端声明的受控来源，辅助填写描述，不提供文件注册或上传操作。
import { FileText,Check,Plus } from "lucide-react";
export function LogSources({capability,error,selected,on_retry,on_source}:{
	capability:{parsed_logs?:boolean;parsed_log_sources?:string[]}|null;
	error:string;selected:string[];on_retry:()=>void;on_source:(identity:string)=>void;
}){
	const sources=[...new Set(capability?.parsed_log_sources??[])];
	return <section className="log-sources" aria-label="受控日志来源">
		<div className="log-sources-heading">
			<h2>日志来源</h2>
			<span>{!capability?error?"能力读取失败":"正在读取能力":capability.parsed_logs?"已接入解析引擎":"未启用解析引擎"}</span>
		</div>
		{!capability?<>
			<p role="status">{error?"请检查诊断服务后重试。":"正在查询后端已注册来源。"}</p>
			{error&&<button type="button" className="text-button" onClick={on_retry}>重试读取日志来源</button>}
		</>:capability.parsed_logs&&sources.length?<>
			<div className="log-source-actions">{sources.map(identity=><button type="button" key={identity} aria-pressed={selected.includes(identity)} title={`选择日志来源 ${identity}`} onClick={()=>on_source(identity)}>
				<FileText size={14}/><code>{identity}</code>{selected.includes(identity)?<Check size={14}/>:<Plus size={14}/>}
			</button>)}</div>
			<p>选择来源将在提交时附加来源信息，不改变输入正文；不保证模型必定调用。此处不上传文件。</p>
		</>:<p>{capability.parsed_logs?"解析引擎已声明可用，但未返回可选来源 ID。请检查后端来源配置。":"由部署者配置受控来源清单后重启后端；导入文本只填写描述，不会注册日志来源。"}</p>}
	</section>;
}
