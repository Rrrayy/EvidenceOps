import { readdir,readFile,writeFile } from "node:fs/promises"; // 仅格式化项目源码，不访问环境配置。
import path from "node:path"; // 构造跨平台源码路径。
import prettier from "prettier"; // 拆开过长 JSX，保留现有解释性注释。
import typescript from "typescript"; // 使用语法感知格式器恢复项目紧凑运算符风格。
async function format_directory(directory){ // 递归处理前端自有源码。
	for(const item of await readdir(directory,{withFileTypes:true})){ // 不遍历依赖与构建目录。
		const filename=path.join(directory,item.name); // 精确定位文件。
		if(item.isDirectory()){await format_directory(filename);continue;} // 仅递归源码子目录。
		if(!/\.(tsx?|css)$/.test(filename)){continue;} // 只处理 TypeScript 与样式。
		let source=await prettier.format(await readFile(filename,"utf8"),{filepath:filename,useTabs:true,tabWidth:4,printWidth:120,trailingComma:"none"}); // 长表达式按阅读宽度折行。
		if(/\.tsx?$/.test(filename)){ // TypeScript 运算符保持无空格。
			const host={getCompilationSettings:()=>({}),getScriptFileNames:()=>[filename],getScriptVersion:()=>"0",getScriptSnapshot:()=>typescript.ScriptSnapshot.fromString(source),getCurrentDirectory:()=>process.cwd(),getDefaultLibFileName:()=>"",fileExists:()=>true,readFile:()=>source}; // 单文件格式化无需加载依赖。
			const service=typescript.createLanguageService(host); // 用语法信息区别文本与运算符。
			const edits=service.getFormattingEditsForDocument(filename,{indentSize:4,tabSize:4,convertTabsToSpaces:false,newLineCharacter:"\n",insertSpaceBeforeAndAfterBinaryOperators:false,insertSpaceAfterCommaDelimiter:false,insertSpaceAfterKeywordsInControlFlowStatements:false,placeOpenBraceOnNewLineForFunctions:false,placeOpenBraceOnNewLineForControlBlocks:false}); // 不修改 JSX 文本中的空格。
			for(const edit of edits.sort((first,second)=>second.span.start-first.span.start)){source=source.slice(0,edit.span.start)+edit.newText+source.slice(edit.span.start+edit.span.length);} // 倒序应用避免偏移变化。
			service.dispose(); // 释放格式化服务。
		} // 结束语法格式恢复。
		await writeFile(filename,source,"utf8"); // 保持原文件名，不绕过文件占用错误。
	} // 结束文件遍历。
} // 结束格式化函数。
await format_directory("src"); // 仅对前端源码执行。
