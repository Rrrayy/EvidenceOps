#include "log_engine/json_output.hpp"

#include <cstdio>
#include <stdexcept>
#include <type_traits>

namespace evidenceops::log_engine {

namespace {

class JsonWriter {
public:
	explicit JsonWriter(std::uint64_t limit):limit_(limit){}
	void append(std::string_view text){
		if(text.size()>limit_-output_.size())throw std::length_error("JSON output budget exceeded");
		output_.append(text);
	}
	void quoted(std::string_view text){
		append("\"");
		const char digits[]="0123456789abcdef";
		for(const char byte_value:text){
			const auto character=static_cast<unsigned char>(byte_value);
			if(character=='"')append("\\\"");
			else if(character=='\\')append("\\\\");
			else if(character<32){
				const char escape[]={'\\','u','0','0',digits[character>>4],digits[character&15]};
				append(std::string_view(escape,6));
			}else{
				const char byte=static_cast<char>(character);
				append(std::string_view(&byte,1));
			}
		}
		append("\"");
	}
	void value(const std::string& text){quoted(text);}
	void value(bool flag){append(flag?"true":"false");}
	template<typename Number> void value(Number number){append(std::to_string(number));}
	template<typename Value> void value(const std::optional<Value>& item){
		if(item)value(*item);else append("null");
	}
	void field(std::string_view name){quoted(name);append(":");}
	std::string take(){return std::move(output_);}
private:
	std::uint64_t limit_;
	std::string output_;
};

std::string utc_text(MicrosecondTime time){
	const auto day=std::chrono::floor<std::chrono::days>(time);
	const std::chrono::year_month_day date{day};
	const std::chrono::hh_mm_ss clock{time-day};
	char buffer[40];
	const int length=std::snprintf(buffer,sizeof(buffer),"%04d-%02u-%02uT%02lld:%02lld:%02lld.%06lldZ",
		static_cast<int>(date.year()),static_cast<unsigned>(date.month()),static_cast<unsigned>(date.day()),
		static_cast<long long>(clock.hours().count()),static_cast<long long>(clock.minutes().count()),
		static_cast<long long>(clock.seconds().count()),static_cast<long long>(clock.subseconds().count()));
	if(length<0||static_cast<std::size_t>(length)>=sizeof(buffer))throw std::runtime_error("UTC formatting failed");
	return std::string(buffer,static_cast<std::size_t>(length));
}

} // namespace

std::string event_json(const LogEvent& event,std::uint64_t limit){
	JsonWriter writer(limit);
	writer.append("{");
	writer.field("event_index");writer.value(event.event_index);
	writer.append(",");writer.field("format");writer.value(to_string(event.format));
	writer.append(",");writer.field("raw_time");writer.value(event.raw_time);
	writer.append(",");writer.field("timestamp");
	if(event.timestamp)writer.value(utc_text(*event.timestamp));else writer.append("null");
	writer.append(",");writer.field("time_basis");writer.value(to_string(event.time_basis));
	writer.append(",");writer.field("level");
	if(event.level)writer.value(to_string(*event.level));else writer.append("null");
	writer.append(",");writer.field("raw_level");writer.value(event.raw_level);
	writer.append(",");writer.field("message");writer.value(event.message);
	writer.append(",");writer.field("event_kind");writer.value(event.event_kind);
	writer.append(",");writer.field("process_id");writer.value(event.process_id);
	writer.append(",");writer.field("thread_id");writer.value(event.thread_id);
	writer.append(",");writer.field("code_file");writer.value(event.code_file);
	writer.append(",");writer.field("code_function");writer.value(event.code_function);
	writer.append(",");writer.field("code_line");writer.value(event.code_line);
	writer.append(",");writer.field("line_start");writer.value(event.line_start);
	writer.append(",");writer.field("line_end");writer.value(event.line_end);
	writer.append(",");writer.field("raw_text");writer.value(event.raw_text);
	writer.append(",");writer.field("attributes");writer.append("{");
	bool first=true;
	for(const auto& [name,value]:event.attributes){
		if(!first)writer.append(",");first=false;
		writer.field(name);
		std::visit([&writer](const auto& item){writer.value(item);},value);
	}
	writer.append("},");writer.field("warnings");writer.append("[");
	first=true;
	for(const auto& warning:event.warnings){
		if(!first)writer.append(",");first=false;writer.value(warning);
	}
	writer.append("]}");
	return writer.take();
}

std::string result_envelope(const SourceInfo& source,const ParseStatistics& statistics,
	std::string_view status,std::string_view error,std::uint64_t limit){
	JsonWriter writer(limit);
	writer.append("{\"schema_version\":\"log-evidence-v1\",\"status\":");writer.quoted(status);
	writer.append(",\"error\":");if(error.empty())writer.append("null");else writer.quoted(error);
	writer.append(",\"source\":{\"source_id\":");writer.value(source.source_id);
	writer.append(",\"source_role\":");writer.value(to_string(source.source_role));
	writer.append(",\"service_name\":");writer.value(source.service_name);
	writer.append(",\"environment\":");writer.value(source.environment);
	writer.append(",\"input_sha256\":null,\"hash_basis\":\"not_computed\"},\"statistics\":{");
	writer.field("input_bytes");writer.value(statistics.input_bytes);
	writer.append(",");writer.field("event_count");writer.value(statistics.event_count);
	writer.append(",");writer.field("unrecognized_count");writer.value(statistics.unrecognized_count);
	writer.append(",");writer.field("warning_count");writer.value(statistics.warning_count);
	writer.append(",");writer.field("skipped_blank_lines");writer.value(statistics.skipped_blank_lines);
	writer.append(",");writer.field("stopped_early");writer.value(statistics.stopped_early);
	writer.append(",");writer.field("stop_reason");writer.value(statistics.stop_reason);
	writer.append("},\"events\":[");
	return writer.take();
}

} // namespace evidenceops::log_engine
