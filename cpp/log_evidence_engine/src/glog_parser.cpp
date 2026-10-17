#include "log_engine/glog_parser.hpp"

#include <charconv>
#include <string_view>
#include <system_error>
#include <utility>

namespace evidenceops::log_engine {

namespace {

bool parse_number(std::string_view text,std::uint64_t& value){
	if(text.empty())return false;
	const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
	return result.ec==std::errc{}&&result.ptr==text.data()+text.size();
}

bool valid_time(std::string_view text){
	if(text.size()!=24)return false;
	for(std::size_t index=0;index<text.size();++index){
		char separator='\0';
		if(index==8)separator=' ';
		else if(index==11||index==14)separator=':';
		else if(index==17)separator='.';
		if(separator!='\0'){
			if(text[index]!=separator)return false;
		}else if(text[index]<'0'||text[index]>'9'){
			return false;
		}
	}
	std::uint64_t year=0,month=0,day=0,hour=0,minute=0,second=0;
	if(!parse_number(text.substr(0,4),year)||!parse_number(text.substr(4,2),month)
		||!parse_number(text.substr(6,2),day)||!parse_number(text.substr(9,2),hour)
		||!parse_number(text.substr(12,2),minute)||!parse_number(text.substr(15,2),second))return false;
	if(year==0||month<1||month>12||hour>23||minute>59||second>59)return false;
	const unsigned days[]={31,28,31,30,31,30,31,31,30,31,30,31};
	const bool leap=year%4==0&&(year%100!=0||year%400==0);
	return day>=1&&day<=days[month-1]+(month==2&&leap?1U:0U);
}

bool horizontal_space(char character){
	return character==' '||character=='\t';
}

LineParseResult malformed(std::string message){
	return {LineParseStatus::malformed,std::nullopt,{std::move(message)}};
}

} // namespace

LineParseResult parse_glog_line(const InputLine& input){
	const std::string_view text=input.text;
	if(text.size()<10)return {};
	const auto level=parse_log_level(text.substr(0,1));
	if(level!=LogLevel::info&&level!=LogLevel::warning&&level!=LogLevel::error&&level!=LogLevel::fatal)return {};
	for(std::size_t index=1;index<=8;++index){
		if(text[index]<'0'||text[index]>'9')return {};
	}
	if(text[9]!=' ')return {};
	if(input.line_number==0)return malformed("input line number must be positive");
	if(text.size()<26||!valid_time(text.substr(1,24))||!horizontal_space(text[25]))
		return malformed("invalid glog date or time header");
	std::size_t cursor=25;
	while(cursor<text.size()&&horizontal_space(text[cursor]))++cursor;
	const auto thread_start=cursor;
	while(cursor<text.size()&&!horizontal_space(text[cursor]))++cursor;
	std::uint64_t thread_number=0;
	const auto thread=text.substr(thread_start,cursor-thread_start);
	if(!parse_number(thread,thread_number))return malformed("invalid or overflowing glog thread id");
	while(cursor<text.size()&&horizontal_space(text[cursor]))++cursor;
	const auto location_start=cursor;
	const auto close=text.find(']',location_start);
	if(close==std::string_view::npos)return malformed("missing glog source location terminator");
	const auto location=text.substr(location_start,close-location_start);
	const auto colon=location.rfind(':');
	if(colon==std::string_view::npos||colon==0)return malformed("missing glog source file or code line");
	std::uint64_t code_line=0;
	if(!parse_number(location.substr(colon+1),code_line)||code_line==0)
		return malformed("invalid or overflowing glog code line");
	auto message_start=close+1;
	if(message_start<text.size()){
		if(text[message_start]!=' ')return malformed("missing glog message separator");
		++message_start;
	}
	LogEvent event;
	event.format=LogFormat::glog;
	event.raw_time=std::string(text.substr(1,24));
	event.level=level;
	event.raw_level=std::string(text.substr(0,1));
	event.thread_id=std::string(thread);
	event.code_file=std::string(location.substr(0,colon));
	event.code_line=code_line;
	event.message=std::string(text.substr(message_start));
	event.line_start=input.line_number;
	event.line_end=input.line_number;
	event.raw_text=input.text;
	event.warnings.push_back("event timezone is unknown; timestamp was not generated");
	return {LineParseStatus::parsed,std::move(event),{}};
}

} // namespace evidenceops::log_engine
