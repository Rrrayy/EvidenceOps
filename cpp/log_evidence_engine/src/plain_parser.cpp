#include "log_engine/plain_parser.hpp"

#include <charconv>
#include <string_view>
#include <system_error>
#include <utility>

namespace evidenceops::log_engine {

namespace {

bool starts_with(std::string_view text,std::string_view prefix){
	return text.size()>=prefix.size()&&text.substr(0,prefix.size())==prefix;
}

bool blank(std::string_view text){
	return text.find_first_not_of(" \t\r\n\v\f")==std::string_view::npos;
}

template<typename Number>
bool parse_number(std::string_view text,Number& value){
	if(text.empty())return false;
	const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
	return result.ec==std::errc{}&&result.ptr==text.data()+text.size();
}

LogEvent base_event(const InputLine& input){
	LogEvent event;
	event.message=input.text;
	event.raw_text=input.text;
	event.line_start=input.line_number;
	event.line_end=input.line_number;
	event.warnings.push_back("event time is unknown; timestamp was not generated");
	return event;
}

LineParseResult malformed(std::string message){
	return {LineParseStatus::malformed,std::nullopt,{std::move(message)}};
}

} // namespace

std::optional<LogEvent> make_unknown_event(const InputLine& input){
	if(input.line_number==0||blank(input.text))return std::nullopt;
	auto event=base_event(input);
	event.warnings.push_back("unrecognized log format");
	return event;
}

LineParseResult parse_plain_line(const InputLine& input){
	const std::string_view text=input.text;
	const std::string_view duration_prefix="CallMethod returned in ";
	const std::string_view async_prefix="async rpc completed, errcode=";
	const std::string_view batch_prefix="Async batch completed=";
	const bool duration=starts_with(text,"CallMethod returned in");
	const bool async=starts_with(text,"async rpc completed,");
	const bool batch=starts_with(text,"Async batch");
	if(!duration&&!async&&!batch)return {};
	if(input.line_number==0)return malformed("input line number must be positive");
	auto event=base_event(input);
	event.format=LogFormat::plain;
	if(duration){
		if(!starts_with(text,duration_prefix)||text.size()<duration_prefix.size()+3
			||text.substr(text.size()-3)!=" us")return malformed("invalid CallMethod duration structure");
		std::uint64_t duration_us=0;
		if(!parse_number(text.substr(duration_prefix.size(),text.size()-duration_prefix.size()-3),duration_us))
			return malformed("invalid or overflowing CallMethod duration");
		event.event_kind="call_return";
		event.attributes.emplace("duration_us",duration_us);
	}else if(async){
		std::int64_t errcode=0;
		if(!starts_with(text,async_prefix)||!parse_number(text.substr(async_prefix.size()),errcode))
			return malformed("invalid or overflowing async RPC error code");
		event.event_kind="async_result";
		event.attributes.emplace("errcode",errcode);
	}else{
		if(!starts_with(text,batch_prefix))return malformed("invalid async batch structure");
		const std::string_view separators[]={" failed="," expected="," finished="};
		std::uint64_t values[4]={};
		std::size_t cursor=batch_prefix.size();
		for(std::size_t index=0;index<3;++index){
			const auto end=text.find(separators[index],cursor);
			if(end==std::string_view::npos||!parse_number(text.substr(cursor,end-cursor),values[index]))
				return malformed("invalid or overflowing async batch count");
			cursor=end+separators[index].size();
		}
		if(!parse_number(text.substr(cursor),values[3])||values[3]>1)
			return malformed("async batch finished must be 0 or 1");
		event.event_kind="async_batch";
		event.attributes.emplace("completed",values[0]);
		event.attributes.emplace("failed",values[1]);
		event.attributes.emplace("expected",values[2]);
		event.attributes.emplace("finished",values[3]==1);
	}
	return {LineParseStatus::parsed,std::move(event),{}};
}

} // namespace evidenceops::log_engine
