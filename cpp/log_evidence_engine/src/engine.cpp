#include "log_engine/engine.hpp"
#include "log_engine/glog_parser.hpp"
#include "log_engine/muduo_parser.hpp"
#include "log_engine/plain_parser.hpp"
#include "log_engine/zookeeper_parser.hpp"
#include "log_engine/json_output.hpp"

#include <stdexcept>
#include <utility>

namespace evidenceops::log_engine {

LineParseResult parse_line(const InputLine& input){
	for(const auto parser:{parse_zookeeper_line,parse_glog_line,parse_muduo_line,parse_plain_line}){
		auto result=parser(input);
		if(result.status!=LineParseStatus::not_matched)return result;
	}
	return {};
}

EngineOutput run_engine(const EngineOptions& options){
	if(options.source.source_id.empty()||options.max_events==0||options.max_output_bytes==0
		||options.reader_limits.max_input_bytes==0||options.reader_limits.max_line_bytes==0)
		throw std::invalid_argument("source id and positive resource limits are required");
	ParseStatistics statistics;
	std::string status="complete",error,events;
	int exit_code=0;
	// Reserve a bounded envelope before collecting events, including worst-case counters.
	ParseStatistics maximum;
	maximum.input_bytes=maximum.event_count=maximum.unrecognized_count=maximum.warning_count=maximum.skipped_blank_lines=UINT64_MAX;
	maximum.stopped_early=true;
	maximum.stop_reason=std::string(128,'x');
	const auto reserve=result_envelope(options.source,maximum,"partial",std::string(256,'x'),options.max_output_bytes).size()+2;
	if(reserve>options.max_output_bytes)throw std::length_error("output limit cannot hold the minimum result envelope");
	const auto event_budget=options.max_output_bytes-reserve;
	BoundedReader reader(options.input_path,options.reader_limits);
	while(true){
		auto result=reader.next();
		statistics.input_bytes=reader.bytes_read();
		if(std::holds_alternative<EndOfInput>(result))break;
		if(const auto* failure=std::get_if<ReaderError>(&result)){
			const bool limited=failure->code==ReaderErrorCode::input_too_large||failure->code==ReaderErrorCode::line_too_long;
			status=limited?"partial":"failed";
			exit_code=limited?2:1;
			error=failure->message+" at input line "+std::to_string(failure->line_number);
			statistics.stopped_early=true;
			switch(failure->code){
				case ReaderErrorCode::input_too_large:statistics.stop_reason="input_limit";break;
				case ReaderErrorCode::line_too_long:statistics.stop_reason="line_limit";break;
				case ReaderErrorCode::invalid_utf8:statistics.stop_reason="invalid_utf8";break;
				case ReaderErrorCode::invalid_bom:statistics.stop_reason="invalid_bom";break;
				case ReaderErrorCode::file_open_failed:statistics.stop_reason="file_open_failed";break;
				case ReaderErrorCode::invalid_limits:statistics.stop_reason="invalid_limits";break;
				default:statistics.stop_reason="file_read_failed";break;
			}
			break;
		}
		const auto& line=std::get<InputLine>(result);
		if(line.text.find_first_not_of(" \t\r\n\v\f")==std::string::npos){
			++statistics.skipped_blank_lines;
			continue;
		}
		if(statistics.event_count>=options.max_events){
			status="partial";exit_code=2;statistics.stopped_early=true;statistics.stop_reason="event_limit";break;
		}
		auto parsed=parse_line(line);
		auto event=parsed.event?std::move(*parsed.event):std::move(*make_unknown_event(line));
		event.warnings.insert(event.warnings.end(),parsed.warnings.begin(),parsed.warnings.end());
		event.event_index=statistics.event_count+1;
		std::string encoded;
		try{
			const auto comma=events.empty()?0U:1U;
			if(event_budget-events.size()<comma)throw std::length_error("event budget exhausted");
			encoded=event_json(event,event_budget-events.size()-comma);
		}catch(const std::length_error&){
			status="partial";exit_code=2;statistics.stopped_early=true;statistics.stop_reason="output_limit";break;
		}
		if(!events.empty())events+=',';
		events+=encoded;
		++statistics.event_count;
		if(event.format==LogFormat::unknown)++statistics.unrecognized_count;
		statistics.warning_count+=event.warnings.size();
	}
	std::string output=result_envelope(options.source,statistics,status,error,options.max_output_bytes);
	if(output.size()+events.size()+2>options.max_output_bytes)throw std::length_error("result exceeds output limit");
	output+=events;output+="]}";
	return {std::move(output),exit_code};
}

} // namespace evidenceops::log_engine
