// 负责模型连接管理表单和诊断工作台的模型选择。
"use client";
import { useEffect,useRef,useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowRight,ChevronDown,Eye,EyeOff,KeyRound,Plus,RefreshCw,Settings2,X } from "lucide-react";
import { connection_labels,safe_endpoint,token_limits_error } from "@/lib/model-connections";
type Selection={ connection_id: string; model_id: string; expected_version?: number };
type Validation={
	status: "ready"|"partial"|"failed";
	config_version: number;
	model_id: string;
	verified_at: string;
	message?: string;
	checks: { name: string; status: string; message?: string }[];
};
type Catalog={ status: string; items: { id: string; source: string }[]; updated_at: string; message?: string };
type Connection={
	id: string;
	name: string;
	provider_id: string;
	default_model: string;
	config_version: number;
	status: keyof typeof connection_labels;
	endpoint_display?: string;
	timeout_seconds: number;
	verified_at: string|null;
	is_default: boolean;
	key_configured?: boolean;
	validations: Record<string,Validation>;
	catalog: Catalog|null;
	context_window_tokens?: number|null;
	max_output_tokens?: number|null;
	safety_margin_tokens?: number|null;
	max_run_tokens?: number|null;
	limits_source?: string|null;
	limits_verified_at?: string|null;
};
type Listing={ items: Connection[]; system: Connection; default: Selection|null };
type Service={ id: string; name: string; endpoint: string; recommended_models: string[] };
async function api(path: string,method="GET",body?: unknown,signal?: AbortSignal) {

	const response=await fetch(`/api/backend/${path}`,{
		method,
		signal,
		cache: "no-store",
		headers: body? { "Content-Type": "application/json" }:undefined,
		body: body? JSON.stringify(body):undefined
	});
	const result=await response.json().catch(() => null);
	if(!response.ok) {
		throw new Error(result?.message??`请求失败（${response.status}）`);
	}
	return result;
}
export function ModelConnections() {

	const [listing,set_listing]=useState<Listing|null>(null);
	const [services,set_services]=useState<Service[]>([]);
	const [loading,set_loading]=useState(true);
	const [retry,set_retry]=useState(0);
	const [list_error,set_list_error]=useState("");
	const [open,set_open]=useState(false);
	const [editing,set_editing]=useState<Connection|null>(null);
	const [step,set_step]=useState(0);
	const [name,set_name]=useState("");
	const [provider,set_provider]=useState("custom");
	const [endpoint,set_endpoint]=useState("");
	const [model,set_model]=useState("");
	const [key,set_key]=useState("");
	const [replace_key,set_replace_key]=useState(false);
	const [visible,set_visible]=useState(false);
	const [timeout,set_timeout]=useState("60");
	const [context_window,set_context_window]=useState("");
	const [max_output,set_max_output]=useState("");
	const [safety_margin,set_safety_margin]=useState("");
	const [max_run,set_max_run]=useState("");
	const [dirty,set_dirty]=useState(false);
	const [discard,set_discard]=useState(false);
	const [busy,set_busy]=useState("");
	const [error,set_error]=useState("");
	const [notice,set_notice]=useState("");
	const [catalog,set_catalog]=useState<Catalog|null>(null);
	const [validation,set_validation]=useState<Validation|null>(null);
	const [remove,set_remove]=useState<Connection|null>(null);
	const [replacement,set_replacement]=useState("");
	const [search,set_search]=useState("");
	const [options_open,set_options_open]=useState(false);
	const [option_index,set_option_index]=useState(0);
	const generation=useRef(0);
	const controller=useRef<AbortController|null>(null);
	const alive=useRef(true);
	const refresh=() => set_retry((value) => value+1);
	useEffect(() => {
		const request=new AbortController();
		set_loading(true);
		set_list_error("");
		Promise.all([
			api("model-connections","GET",undefined,request.signal),
			api("model-services","GET",undefined,request.signal)
		])
			.then(([data,directory]) => {
				if(!request.signal.aborted) {
					set_listing(data);
					set_services(directory.items);
					set_loading(false);
				}
			})
			.catch((reason) => {
				if(!request.signal.aborted) {
					set_list_error(reason.message);
					set_loading(false);
				}
			});
		return () => request.abort();
	},[retry]);
	useEffect(() => {
		alive.current=true;
		return () => {
			alive.current=false;
			generation.current++;
			controller.current?.abort();
		};
	},[]);
	useEffect(() => {
		const protect=(event: BeforeUnloadEvent) => {
			if(open&&dirty) {
				event.preventDefault();
				event.returnValue="";
			}
		};
		window.addEventListener("beforeunload",protect);
		return () => window.removeEventListener("beforeunload",protect);
	},[open,dirty]);
	function changed(invalidate: boolean|"model"=true) {
		generation.current++;
		controller.current?.abort();
		set_busy("");
		set_dirty(true);
		set_error("");
		if(invalidate) {
			set_validation(null);
			if(invalidate!=="model") {
				set_catalog(null);
			}
		}
	}
	function launch(item: Connection|null) {
		generation.current++;
		set_editing(item);
		set_name(item?.name??"");
		set_provider(item?.provider_id??"custom");
		set_endpoint("");
		set_model(item?.default_model??"");
		set_timeout(String(item?.timeout_seconds??60));
		set_context_window(item?.context_window_tokens==null?"":String(item.context_window_tokens));
		set_max_output(item?.max_output_tokens==null?"":String(item.max_output_tokens));
		set_safety_margin(item?.safety_margin_tokens==null?"":String(item.safety_margin_tokens));
		set_max_run(item?.max_run_tokens==null?"":String(item.max_run_tokens));
		set_key("");
		set_replace_key(item?.key_configured===false);
		set_visible(false);
		set_step(item? 1:0);
		set_dirty(false);
		set_discard(false);
		set_error("");
		set_notice("");
		set_busy("");
		set_search("");
		set_catalog(item?.catalog??null);
		set_validation(item?.validations?.[item.default_model]??null);
		set_open(true);
	}
	function finish_close() {
		generation.current++;
		controller.current?.abort();
		set_open(false);
		set_discard(false);
		set_key("");
		set_visible(false);
		set_dirty(false);
		set_busy("");
		set_options_open(false);
	}
	function close() {
		if(busy) {
			set_error("操作进行中，请等待结果后关闭");
		} else if(dirty) {
			set_discard(true);
		} else {
			finish_close();
		}
	}
	async function persist(token:number) {

		if(!name.trim()) {
			throw new Error("请填写连接名称");
		}
		if((!editing&&!endpoint.trim())||(endpoint&&safe_endpoint(endpoint)==="地址格式无效")) {
			throw new Error("请填写有效接口地址");
		}
		if(!model.trim()) {
			throw new Error("请填写模型 ID，也可手动输入");
		}
		if((!editing||replace_key)&&!key.trim()) {
			throw new Error("请填写 API Key");
		}
		if(!Number.isFinite(Number(timeout))||Number(timeout)<1||Number(timeout)>300) {
			throw new Error("超时时间需为 1 到 300 秒");
		}
		const token_fields={context_window_tokens:context_window,max_output_tokens:max_output,safety_margin_tokens:safety_margin,max_run_tokens:max_run};
		const token_error=token_limits_error({context_window,max_output,safety_margin,max_run});
		if(token_error) throw new Error(token_error);
		if(editing&&!dirty) {
			return editing;
		}
		const result=await api(
			editing? `model-connections/${editing.id}`:"model-connections",
			editing? "PATCH":"POST",
			{
				name: name.trim(),
				provider_id: provider,
				protocol: "chat_completions",
				default_model: model.trim(),
				timeout_seconds: Number(timeout),
				endpoint: endpoint.trim()||undefined,
				api_key: !editing||replace_key? key:undefined,
				context_window_tokens: context_window? Number(context_window):undefined,
				max_output_tokens: max_output? Number(max_output):undefined,
				safety_margin_tokens: safety_margin? Number(safety_margin):undefined,
				max_run_tokens: max_run? Number(max_run):undefined,
				expected_version: editing?.config_version
			},
			controller.current?.signal
		);
		if(token===generation.current&&alive.current) {
			set_editing(result);
			set_dirty(false);
			set_key("");
			set_replace_key(false);
			set_endpoint("");
			refresh();
		}
		return result as Connection;
	}
	async function operation(action: "save"|"validation"|"catalog") {

		if(busy) {
			return;
		}
		const token=++generation.current;
		controller.current=new AbortController();
		set_busy(action);
		set_error("");
		set_notice("");
		try {
			const saved=await persist(token);
			if(token!==generation.current||!alive.current) {
				return;
			}
			if(action==="save") {
				finish_close();
				return;
			}
			set_notice("配置已保存，正在请求模型服务…");
			const result=await api(
				`model-connections/${saved.id}/${action}`,
				"POST",
				{ expected_version: saved.config_version,model_id: model.trim() },
				controller.current.signal
			);
			if(token!==generation.current||!alive.current) {
				return;
			}
			if(action==="validation") {
				set_validation(result);
				set_notice(result.status==="ready"? "连接成功，Agent 能力通过":"配置已保存，模型尚未就绪");
			} else {
				set_catalog(result);
				set_notice("");
			}
			refresh();
		} catch(reason) {
			if(token===generation.current&&alive.current) {
				set_error(reason instanceof Error? reason.message:"操作失败，请重试");
			}
		} finally {
			if(token===generation.current&&alive.current) {
				set_busy("");
			}
		}
	}
	async function set_default(item: Connection) {
		if(busy) {
			return;
		}
		set_busy("default");
		try {
			await api("model-connections/default","PUT",{
				connection_id: item.id,
				model_id: item.default_model,
				expected_version: item.config_version
			});
			refresh();
		} catch(reason) {
			set_list_error(reason instanceof Error? reason.message:"设置失败");
		} finally {
			set_busy("");
		}
	}
	async function delete_connection() {
		if(!remove||busy) {
			return;
		}
		set_busy("delete");
		try {
			await api(`model-connections/${remove.id}`,"DELETE",{
				expected_version: remove.config_version,
				replacement_id: replacement||null
			});
			set_remove(null);
			refresh();
		} catch(reason) {
			set_list_error(reason instanceof Error? reason.message:"删除失败");
		} finally {
			set_busy("");
		}
	}
	const preset=services.find((service) => service.id===provider);
	const options=Array.from(
		new Set([...(catalog?.items??[]).map((item) => item.id),...(preset?.recommended_models??[])])
	)
		.filter((item) => item.toLowerCase().includes(model.toLowerCase()))
		.slice(0,100);
	return (
		<section className="connections-page">
			<div className="page-heading">
				<div>
										<h1>模型连接</h1>
					<p>保存你的模型服务，在诊断时选择合适的模型。</p>
				</div>
				<button className="primary-button" disabled={!listing||loading} onClick={() => launch(null)}>
					<Plus size={17} />
					添加模型连接
				</button>
			</div>
			{list_error&&(
				<div className="error-banner" role="alert">
					<span>{list_error}</span>
					<button className="text-button" onClick={refresh}>
						重试
					</button>
				</div>
			)}
			{loading? (
				<div className="connection-unavailable" role="status">
					正在读取模型连接…
				</div>
			):listing? (
				<>
					<div className="connection-status">
						<Settings2 size={19} />
						<div>
							<strong>{listing.system.name}</strong>
							<p>{listing.system.default_model} · 后端环境提供，密钥不可查看或编辑。</p>
						</div>
						<button
							className="text-button"
							disabled={Boolean(busy)||!listing.default||listing.default.connection_id==="system"}
							onClick={() => void set_default(listing.system)}
						>
							{!listing.default||listing.default.connection_id==="system"? "当前默认":"设为默认"}
						</button>
					</div>
					<div className="connection-list-placeholder">
						<div className="connection-table-head">
							<span>连接 / 供应商</span>
							<span>默认模型</span>
							<span>容量限制</span>
							<span>验证状态</span>
							<span>操作</span>
						</div>
						{listing.items.length? (
							listing.items.map((item) => (
								<article className="connection-row" key={item.id}>
									<div>
										<strong>{item.name}</strong>
										{item.is_default&&<small className="default-badge">默认</small>}
										<p>
											{services.find((service) => service.id===item.provider_id)?.name??
												item.provider_id}
										</p>
										<small>{item.endpoint_display}</small>
									</div>
									<div className="connection-model-value">
										{item.default_model}
										<small>Chat Completions</small>
									</div>
									<div className="connection-limits">
													{item.context_window_tokens? `${item.context_window_tokens.toLocaleString("zh-CN")} 上下文` : "上下文未记录"}
													<small>{item.limits_source==="legacy_compatibility"? "兼容默认值":item.limits_source||"来源未记录"}</small>
									</div>
									<div>
										<span className={`connection-state ${item.status}`}>{connection_labels[item.status]}</span>
										<small>
											{item.verified_at
												? new Date(item.verified_at).toLocaleString("zh-CN")
												:"尚未验证"}
										</small>
									</div>
									<div className="connection-actions">
										<button
											className="text-button"
											disabled={Boolean(busy)}
											onClick={() => launch(item)}
										>
											编辑 / 验证
										</button>
										<button
											className="text-button"
											disabled={Boolean(busy)||item.is_default}
											onClick={() => void set_default(item)}
										>
											{item.is_default? "当前默认":"设为默认"}
										</button>
										<button
											className="text-button"
											disabled={Boolean(busy)}
											onClick={() => {
												set_remove(item);
												set_replacement("");
												set_list_error("");
											}}
										>
											删除
										</button>
									</div>
								</article>
							))
						):(
							<div className="connection-unavailable">
								<KeyRound size={30} />
								<h2>接入你的第一个模型连接</h2>
								<p>同一供应商可以保存多个账号与接口，保存后验证 Agent 能力。</p>
								<button className="secondary-button" onClick={() => launch(null)}>
									添加模型连接
									<ArrowRight size={16} />
								</button>
							</div>
						)}
					</div>
				</>
			):(
				<div className="connection-unavailable">连接未读取成功，请重试。原有诊断仍可使用。</div>
			)}
			<div className="connection-boundaries">
				<div>
					<h3>验证通过后用于 Agent</h3>
					<p>工具调用与报告格式分别验证。模型目录不代表账号有调用权限。</p>
				</div>
				<details>
					<summary>高级说明</summary>
					<p>本页仅管理诊断模型。Embedding 与 Rerank 独立管理，不随诊断模型切换。</p>
				</details>
			</div>
			<Dialog.Root
				open={open}
				onOpenChange={(value) => {
					if(!value) {
						close();
					}
				}}
			>
				<Dialog.Portal>
					<Dialog.Overlay className="dialog-overlay" />
					<Dialog.Content
						className="connection-drawer"
						onInteractOutside={(event) => {
							event.preventDefault();
							close();
						}}
					>
						<div className="drawer-heading">
							<span className="section-label">模型连接</span>
							<button className="icon-button" aria-label="关闭连接表单" onClick={close}>
								<X size={20} />
							</button>
						</div>
						<Dialog.Title className="drawer-title">
							{editing? "编辑模型连接":"添加模型连接"}
						</Dialog.Title>
						<Dialog.Description className="drawer-description">
							密钥由后端加密保存。配置改变需重新验证，正在运行的诊断保持原配置。
						</Dialog.Description>
						{!editing&&(
							<ol className="connection-steps" aria-label="添加步骤">
								{["选择服务","连接信息","选择模型","验证与保存"].map((label,index) => (
									<li key={label} aria-current={index===step? "step":undefined}>
										<span>{index+1}</span>
										{label}
									</li>
								))}
							</ol>
						)}
						<form
							className="connection-form"
							onSubmit={(event) => {
								event.preventDefault();
								if(editing||step===3) {
									void operation("save");
								} else {
									set_step(step+1);
								}
							}}
						>
							{step===0&&!editing? (
								<>
									<label htmlFor="service-search">搜索服务</label>
									<input
										id="service-search"
										value={search}
										onChange={(event) => set_search(event.target.value)}
									/>
									{services
										.filter((service) => service.name.toLowerCase().includes(search.toLowerCase()))
										.map((service) => (
											<button
												type="button"
												className={`service-choice service-choice-button ${provider===service.id? "chosen":""}`}
												aria-pressed={provider===service.id}
												key={service.id}
												onClick={() => {
													set_provider(service.id);
													set_endpoint(service.endpoint);
													set_model(service.recommended_models[0]??"");
													changed();
												}}
											>
												<Settings2 size={22} />
												<span>
													<strong>{service.name}</strong>
													<small>Chat Completions</small>
												</span>
											</button>
										))}
								</>
							):(
								<>
									{(editing||step===1)&&(
										<>
											<label htmlFor="connection-name">连接名称</label>
											<input
												id="connection-name"
												value={name}
												maxLength={80}
												disabled={Boolean(busy)}
												onChange={(event) => {
													set_name(event.target.value);
													changed(false);
												}}
												aria-describedby="connection-error"
											/>
											<label htmlFor="connection-key">API Key</label>
											{editing&&!replace_key? (
												<div className="key-configured">
													<span>密钥已配置</span>
													<button
														type="button"
														className="text-button"
														disabled={Boolean(busy)}
														onClick={() => {
															set_replace_key(true);
															changed();
														}}
													>
														替换密钥
													</button>
												</div>
											):(
												<div className="key-input">
													<input
														id="connection-key"
														type={visible? "text":"password"}
														value={key}
														autoComplete="new-password"
														spellCheck={false}
														maxLength={4096}
														disabled={Boolean(busy)}
														placeholder="粘贴 API Key"
														onChange={(event) => {
															set_key(event.target.value);
															changed();
														}}
														aria-describedby="connection-error"
													/>
													<button
														type="button"
														className="icon-button"
														aria-label={visible? "隐藏密钥":"显示密钥"}
														onClick={() => set_visible((value) => !value)}
													>
														{visible? <EyeOff size={17} />:<Eye size={17} />}
													</button>
												</div>
											)}
											<p className="field-note">
												读取接口不返回密钥。编辑时保留已有密钥，只有明确替换才提交新值。
											</p>
											<p>协议：Chat Completions</p>
											<details
												className="connection-advanced"
												open={!editing&&provider==="custom"? true:undefined}
											>
												<summary>高级设置</summary>
												<label htmlFor="connection-endpoint">接口地址</label>
												<input
													id="connection-endpoint"
													value={endpoint}
													maxLength={2048}
													disabled={Boolean(busy)}
													placeholder={
														editing
															? `留空保留已有地址（${editing.endpoint_display}）`
															:"服务提供方的完整兼容地址"
													}
													onChange={(event) => {
														set_endpoint(event.target.value);
														changed();
													}}
													aria-describedby="connection-error"
												/>
												<label htmlFor="connection-timeout">超时时间（秒）</label>
												<input id="connection-timeout" type="number" min={1} max={300} value={timeout} disabled={Boolean(busy)} onChange={(event) => {set_timeout(event.target.value);changed();}} />
												<div className="token-settings" aria-label="Token 容量限制">
													<div className="token-setting-field">
														<label htmlFor="context-window">上下文窗口 Token</label>
														<input id="context-window" type="number" min={1} max={10000000} step={1} value={context_window} disabled={Boolean(busy)} onChange={(event) => {set_context_window(event.target.value);changed();}} aria-describedby="connection-error token-settings-note" />
													</div>
													<div className="token-setting-field">
														<label htmlFor="max-output">单次输出上限 Token</label>
														<input id="max-output" type="number" min={1} max={1000000} step={1} value={max_output} disabled={Boolean(busy)} onChange={(event) => {set_max_output(event.target.value);changed();}} aria-describedby="connection-error token-settings-note" />
													</div>
													<div className="token-setting-field">
														<label htmlFor="safety-margin">上下文安全余量 Token</label>
														<input id="safety-margin" type="number" min={0} max={1000000} step={1} value={safety_margin} disabled={Boolean(busy)} onChange={(event) => {set_safety_margin(event.target.value);changed();}} aria-describedby="connection-error token-settings-note" />
													</div>
													<div className="token-setting-field">
														<label htmlFor="max-run">单次诊断预算 Token</label>
														<input id="max-run" type="number" min={1} max={10000000} step={1} value={max_run} disabled={Boolean(busy)} onChange={(event) => {set_max_run(event.target.value);changed();}} aria-describedby="connection-error token-settings-note" />
													</div>
												</div>
												<p id="token-settings-note" className="field-note">{editing? "留空表示保留已有值。":"留空时由后端应用保守默认值。"} 容量以 Token 计，实际供应商限制请以服务配置为准。</p>
											</details>
										</>
									)}
									{(editing||step===2)&&(
										<>
											<label htmlFor="connection-model">模型 ID</label>
											<div className="model-combobox">
												<input
													id="connection-model"
													role="combobox"
													aria-autocomplete="list"
													aria-expanded={options_open}
													aria-controls="model-options"
													aria-activedescendant={
														options_open&&options[option_index]
															? `model-option-${option_index}`
															:undefined
													}
													value={model}
													maxLength={200}
													disabled={Boolean(busy)}
													onFocus={() => set_options_open(true)}
													onBlur={() => set_options_open(false)}
													onChange={(event) => {
														set_model(event.target.value);
														set_option_index(0);
														set_options_open(true);
														changed("model");
													}}
													onKeyDown={(event) => {
														if(event.key==="Escape") {
															event.preventDefault();
															event.stopPropagation();
															set_options_open(false);
														}
														if(event.key==="ArrowDown"||event.key==="ArrowUp") {
															event.preventDefault();
															set_options_open(true);
															set_option_index((value) =>
																Math.max(
																	0,
																	Math.min(
																		options.length-1,
																		value+(event.key==="ArrowDown"? 1:-1)
																	)
																)
															);
														}
														if(
															event.key==="Enter"&&
															options_open&&
															options[option_index]
														) {
															event.preventDefault();
															set_model(options[option_index]);
															changed("model");
															set_options_open(false);
														}
													}}
													aria-describedby="connection-error"
												/>
												{options_open&&(
													<div
														className="model-options"
														id="model-options"
														role="listbox"
														aria-label="模型目录"
													>
														{options.length? (
															options.map((identity,index) => (
																<button
																	type="button"
																	role="option"
																	aria-selected={index===option_index}
																	id={`model-option-${index}`}
																	key={identity}
																	onMouseDown={(event) => event.preventDefault()}
																	onClick={() => {
																		set_model(identity);
																		changed("model");
																		set_options_open(false);
																	}}
																>
																	<span>{identity}</span>
																	<small>
																		{catalog?.items.some(
																			(item) => item.id===identity
																		)
																			? "接口目录"
																			:"推荐，不代表账号权限"}
																	</small>
																</button>
															))
														):(
															<p>无匹配项，可继续手动输入</p>
														)}
													</div>
												)}
											</div>
											<p className="field-note">
												{catalog?.items.some((item) => item.id===model)
													? "接口目录"
													:preset?.recommended_models.includes(model)
														? "推荐，不代表账号权限"
														:"自定义，待验证"}
											</p>
											<button
												className="secondary-button"
												type="button"
												disabled={Boolean(busy)}
												onClick={() => void operation("catalog")}
											>
												<RefreshCw size={14} />
												{busy==="catalog"? "读取中":"保存配置并刷新模型列表"}
											</button>
											<p className="field-note">
												{catalog
													? `${catalog.status==="ready"? "接口目录":catalog.status==="empty"? "接口目录为空":catalog.status==="unsupported"? "服务不支持模型目录":"目录获取失败"} · ${new Date(catalog.updated_at).toLocaleString("zh-CN")} ${catalog.message??""}`
													:"目录未加载，仍可手动填写。输入时不会请求供应商。"}
											</p>
										</>
									)}
									{(editing||step===3)&&(
										<>
											<h3>验证诊断所需能力</h3>
											<ul className="verification-checks">
												{(
													validation?.checks??
													[
														"认证与连接",
														"指定模型调用",
														"工具调用及结果关联",
														"结构化报告输出"
													].map((name) => ({ name,status: "pending",message: undefined }))
												).map((check) => (
													<li key={check.name}>
														<span>
															{check.name}
															{check.message&&(
																<small className="field-note">{check.message}</small>
															)}
														</span>
														<span>
															{check.status==="passed"
																? "已通过"
																:check.status==="failed"
																	? "未通过"
																	:"待验证"}
														</span>
													</li>
												))}
											</ul>
											<button
												className="secondary-button"
												type="button"
												disabled={Boolean(busy)}
												onClick={() => void operation("validation")}
											>
												{busy==="validation"? "验证中…":"保存配置并验证模型"}
											</button>
											<p className="field-note">
												可能产生少量模型调用费用。最多三次探针调用，不在输入时自动验证。
											</p>
											{validation&&(
												<p
													role="status"
													className={
														validation.status==="ready"? "good":"connection-error"
													}
												>
													{connection_labels[validation.status]}
													{validation.message? `：${validation.message}`:""}
												</p>
											)}
										</>
									)}
								</>
							)}
							<p id="connection-error" className="connection-error" role="alert">
								{error}
							</p>
							<p role="status" className="field-note">
								{notice}
							</p>
							<div className="connection-form-footer">
								<button
									type="button"
									className="text-button"
									disabled={Boolean(busy)}
									onClick={() => {
										if(!editing&&step) {
											set_step(step-1);
										} else {
											close();
										}
									}}
								>
									{!editing&&step? "上一步":"取消"}
								</button>
								<button className="primary-button" disabled={Boolean(busy)}>
									{busy? "处理中…":editing||step===3? "保存连接":"下一步"}
									<ArrowRight size={16} />
								</button>
							</div>
						</form>
						{discard&&(
							<div className="discard-confirm" role="alert">
								<strong>放弃未保存的连接信息？</strong>
								<p>草稿与未提交密钥不会保留。</p>
								<button className="secondary-button" onClick={() => set_discard(false)}>
									继续编辑
								</button>
								<button className="text-button" onClick={finish_close}>
									放弃并关闭
								</button>
							</div>
						)}
					</Dialog.Content>
				</Dialog.Portal>
			</Dialog.Root>
			<Dialog.Root
				open={Boolean(remove)}
				onOpenChange={(value) => {
					if(!value&&!busy) {
						set_remove(null);
					}
				}}
			>
				<Dialog.Portal>
					<Dialog.Overlay className="dialog-overlay" />
					<Dialog.Content className="lookup-dialog">
						<Dialog.Title>删除模型连接？</Dialog.Title>
						<Dialog.Description>
							删除“{remove?.name}”后，历史快照保持不变。如果连接正在使用，后端将拒绝删除。
						</Dialog.Description>
						{remove?.is_default&&(
							<>
								<label htmlFor="replacement-connection">删除默认连接后的选择</label>
								<select
									id="replacement-connection"
									value={replacement}
									onChange={(event) => set_replacement(event.target.value)}
								>
									<option value="">无默认连接（省略选择时使用系统配置）</option>
									{listing?.items
										.filter((item) => item.id!==remove.id)
										.map((item) => (
											<option key={item.id} value={item.id}>
												{item.name}
											</option>
										))}
								</select>
							</>
						)}
						{list_error&&(
							<p className="connection-error" role="alert">
								{list_error}
							</p>
						)}
						<div className="connection-form-footer">
							<Dialog.Close className="secondary-button" disabled={Boolean(busy)}>
								取消
							</Dialog.Close>
							<button
								className="primary-button"
								disabled={Boolean(busy)}
								onClick={() => void delete_connection()}
							>
								确认删除
							</button>
						</div>
					</Dialog.Content>
				</Dialog.Portal>
			</Dialog.Root>
		</section>
	);
}
export function ModelSelector({
	mode,
	on_manage,
	selection,
	on_select
}: {
	mode: string|undefined;
	on_manage: () => void;
	selection?: Selection;
	on_select: (value: Selection) => void;
}) {

	const [listing,set_listing]=useState<Listing|null>(null);
	const [error,set_error]=useState("");
	const [open,set_open]=useState(false);
	const [search,set_search]=useState("");
	useEffect(() => {
		const request=new AbortController();
		api("model-connections","GET",undefined,request.signal)
			.then((data) => {
				if(!request.signal.aborted) {
					set_listing(data);
					set_error("");
					if(!selection) {
						const chosen=data.default??{ connection_id: "system",model_id: data.system.default_model };
						const item=
							chosen.connection_id==="system"
								? data.system
								:data.items.find((item: Connection) => item.id===chosen.connection_id);
						if(item) {
							on_select({ ...chosen,expected_version: item.config_version });
						}
					}
				}
			})
			.catch((reason) => {
				if(!request.signal.aborted) {
					set_error(reason.message);
				}
			});
		return () => request.abort();
	},[open]);
	const chosen=
		selection??
		listing?.default??
		(listing? { connection_id: "system",model_id: listing.system.default_model }:undefined);
	const current=
		chosen?.connection_id==="system"
			? listing?.system
			:listing?.items.find((item) => item.id===chosen?.connection_id);
	return (
		<Dialog.Root open={open} onOpenChange={set_open}>
			<Dialog.Trigger className="model-selector">
				<Settings2 size={15} />
				<span>
					{current
						? `${current.name} · ${chosen?.model_id}`
						:selection&&listing
							? "所选连接已删除，请重新选择"
							:mode==="mock"
								? "后端原有配置 · Mock 演示"
								:"后端原有配置"}
				</span>
				<ChevronDown size={14} />
			</Dialog.Trigger>
			<Dialog.Portal>
				<Dialog.Overlay className="dialog-overlay" />
				<Dialog.Content className="lookup-dialog model-selector-dialog">
					<Dialog.Title>选择本次诊断模型</Dialog.Title>
					<Dialog.Description>本次选择不改变默认值。开始诊断后配置固定。</Dialog.Description>
					{error? (
						<p className="connection-error" role="alert">
							{error}；仍可使用后端原有配置。
						</p>
					):listing? (
						<>
							<label htmlFor="selector-search">搜索连接或模型</label>
							<input
								id="selector-search"
								value={search}
								onChange={(event) => set_search(event.target.value)}
							/>
							<div className="selector-options">
								{[listing.system,...listing.items].flatMap((item) => {
									const models=
										item.id==="system"
											? [item.default_model]
											:Array.from(
												new Set([
													item.default_model,
													...Object.keys(item.validations??{})
												])
											);
									return models
										.filter((model) =>
											`${item.name} ${model}`.toLowerCase().includes(search.toLowerCase())
										)
										.map((model) => {
											const ready=
												item.id==="system"||item.validations?.[model]?.status==="ready";
											return (
												<button
													className="selector-option"
													key={`${item.id}:${model}`}
													disabled={!ready}
													onClick={() => {
														on_select({
															connection_id: item.id,
															model_id: model,
															expected_version: item.config_version
														});
														set_open(false);
													}}
												>
													<strong>{item.name}</strong>
													<span>{model}</span>
													<small>
														{ready
															? item.id==="system"
																? "系统连接"
																:"Agent 能力已验证"
															:"未就绪，请先验证"}
													</small>
												</button>
											);
										});
								})}
							</div>
							{!listing.items.some((item) =>
								Object.values(item.validations??{}).some((value) => value.status==="ready")
							)&&(
									<p className="field-note">暂无已验证的用户连接，可配置自己的服务；系统连接继续可用。</p>
								)}
						</>
					):(
						<p role="status">正在读取连接…</p>
					)}
					<Dialog.Close className="secondary-button" onClick={on_manage}>
						管理模型连接
						<ArrowRight size={15} />
					</Dialog.Close>
					<Dialog.Close className="dialog-close icon-button" aria-label="关闭模型选择">
						<X size={18} />
					</Dialog.Close>
				</Dialog.Content>
			</Dialog.Portal>
		</Dialog.Root>
	);
}
