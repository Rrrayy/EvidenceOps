#include "log_engine/log_event.hpp"

#include <cctype>

namespace evidenceops::log_engine {

std::string normalize_token(std::string_view value){
	std::string normalized;
	normalized.reserve(value.size());
	std::size_t start=0;
	std::size_t end=value.size();
	while(start<end&&std::isspace(static_cast<unsigned char>(value[start]))){
		++start;
	}
	while(end>start&&std::isspace(static_cast<unsigned char>(value[end-1]))){
		--end;
	}
	for(std::size_t index=start;index<end;++index){
		const unsigned char character=static_cast<unsigned char>(value[index]);
		normalized.push_back(static_cast<char>(std::tolower(character)));
	}
	return normalized;
}

std::string to_string(LogFormat value){
	switch(value){
		case LogFormat::glog:return "glog";
		case LogFormat::zookeeper:return "zookeeper";
		case LogFormat::muduo:return "muduo";
		case LogFormat::plain:return "plain";
		case LogFormat::unknown:return "unknown";
	}
	return "unknown";
}

std::string to_string(LogLevel value){
	switch(value){
		case LogLevel::trace:return "trace";
		case LogLevel::debug:return "debug";
		case LogLevel::info:return "info";
		case LogLevel::warning:return "warning";
		case LogLevel::error:return "error";
		case LogLevel::fatal:return "fatal";
		case LogLevel::unknown:return "unknown";
	}
	return "unknown";
}

std::string to_string(TimeBasis value){
	switch(value){
		case TimeBasis::explicit_timezone:return "explicit_timezone";
		case TimeBasis::input_timezone:return "input_timezone";
		case TimeBasis::unknown:return "unknown";
	}
	return "unknown";
}

std::string to_string(SourceRole value){
	switch(value){
		case SourceRole::server:return "server";
		case SourceRole::client:return "client";
		case SourceRole::unknown:return "unknown";
	}
	return "unknown";
}

LogFormat parse_log_format(std::string_view value){
	const std::string normalized=normalize_token(value);
	if(normalized=="glog")return LogFormat::glog;
	if(normalized=="zookeeper")return LogFormat::zookeeper;
	if(normalized=="muduo")return LogFormat::muduo;
	if(normalized=="plain")return LogFormat::plain;
	return LogFormat::unknown;
}

LogLevel parse_log_level(std::string_view value){
	const std::string normalized=normalize_token(value);
	if(normalized=="trace")return LogLevel::trace;
	if(normalized=="debug")return LogLevel::debug;
	if(normalized=="info"||normalized=="i")return LogLevel::info;
	if(normalized=="warning"||normalized=="warn"||normalized=="w")return LogLevel::warning;
	if(normalized=="error"||normalized=="e")return LogLevel::error;
	if(normalized=="fatal"||normalized=="f")return LogLevel::fatal;
	return LogLevel::unknown;
}

SourceRole parse_source_role(std::string_view value){
	const std::string normalized=normalize_token(value);
	if(normalized=="server")return SourceRole::server;
	if(normalized=="client")return SourceRole::client;
	return SourceRole::unknown;
}

bool LogEvent::is_valid() const noexcept{
	if(line_start==0||line_end<line_start)return false;
	if(raw_text.empty())return false;
	for(const std::string& warning:warnings){
		if(warning.empty())return false;
	}
	return true;
}

} // namespace evidenceops::log_engine
