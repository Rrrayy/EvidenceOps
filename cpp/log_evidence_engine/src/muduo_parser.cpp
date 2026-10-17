#include "log_engine/muduo_parser.hpp"

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

bool leap_year(std::int64_t year){
	return year%4==0&&(year%100!=0||year%400==0);
}

std::optional<MicrosecondTime> parse_utc(std::string_view text){
	if(text.size()!=25||text[24]!='Z')return std::nullopt;
	for(std::size_t index=0;index<24;++index){
		char separator='\0';
		if(index==8)separator=' ';
		else if(index==11||index==14)separator=':';
		else if(index==17)separator='.';
		if(separator!='\0'){
			if(text[index]!=separator)return std::nullopt;
		}else if(text[index]<'0'||text[index]>'9'){
			return std::nullopt;
		}
	}
	std::uint64_t year=0,month=0,day=0,hour=0,minute=0,second=0,microsecond=0;
	if(!parse_number(text.substr(0,4),year)||!parse_number(text.substr(4,2),month)
		||!parse_number(text.substr(6,2),day)||!parse_number(text.substr(9,2),hour)
		||!parse_number(text.substr(12,2),minute)||!parse_number(text.substr(15,2),second)
		||!parse_number(text.substr(18,6),microsecond))return std::nullopt;
	if(year==0||month<1||month>12||hour>23||minute>59||second>59)return std::nullopt;
	const unsigned month_days[]={31,28,31,30,31,30,31,31,30,31,30,31};
	const auto signed_year=static_cast<std::int64_t>(year);
	if(day<1||day>month_days[month-1]+(month==2&&leap_year(signed_year)?1U:0U))return std::nullopt;
	const auto days_before_year=[](std::int64_t current_year){
		const auto previous=current_year-1;
		return previous*365+previous/4-previous/100+previous/400;
	};
	std::int64_t days=days_before_year(signed_year)-days_before_year(1970);
	for(std::uint64_t current_month=1;current_month<month;++current_month){
		days+=month_days[current_month-1];
		if(current_month==2&&leap_year(signed_year))++days;
	}
	days+=static_cast<std::int64_t>(day)-1;
	const auto seconds=days*86400+static_cast<std::int64_t>(hour)*3600
		+static_cast<std::int64_t>(minute)*60+static_cast<std::int64_t>(second);
	return MicrosecondTime{std::chrono::microseconds{seconds*1000000+static_cast<std::int64_t>(microsecond)}};
}

bool horizontal_space(char character){
	return character==' '||character=='\t';
}

LineParseResult malformed(std::string message){
	return {LineParseStatus::malformed,std::nullopt,{std::move(message)}};
}

} // namespace

LineParseResult parse_muduo_line(const InputLine& input){
	const std::string_view text=input.text;
	if(text.size()<12||text[8]!=' '||text[11]!=':')return {};
	for(std::size_t index=0;index<8;++index){
		if(text[index]<'0'||text[index]>'9')return {};
	}
	if(input.line_number==0)return malformed("input line number must be positive");
	if(text.size()<26)return malformed("incomplete muduo UTC header");
	const auto timestamp=parse_utc(text.substr(0,25));
	if(!timestamp)return malformed("invalid or unsupported muduo UTC time; expected YYYYMMDD HH:MM:SS.ffffffZ");
	if(!horizontal_space(text[25]))return malformed("missing muduo thread separator");
	std::size_t cursor=25;
	while(cursor<text.size()&&horizontal_space(text[cursor]))++cursor;
	const auto thread_start=cursor;
	while(cursor<text.size()&&!horizontal_space(text[cursor]))++cursor;
	const auto thread=text.substr(thread_start,cursor-thread_start);
	std::uint64_t thread_number=0;
	if(!parse_number(thread,thread_number))return malformed("invalid or overflowing muduo thread id");
	while(cursor<text.size()&&horizontal_space(text[cursor]))++cursor;
	const auto level_start=cursor;
	while(cursor<text.size()&&!horizontal_space(text[cursor]))++cursor;
	const auto raw_level=text.substr(level_start,cursor-level_start);
	if(raw_level.empty()||cursor==text.size())return malformed("missing muduo level or message separator");
	for(const char character:raw_level){
		if(!((character>='A'&&character<='Z')||(character>='a'&&character<='z')))
			return malformed("invalid muduo level token");
	}
	const auto level=parse_log_level(raw_level);
	const auto level_width=raw_level.size()<5?5:raw_level.size();
	const auto padding=level_width-raw_level.size()+1;
	for(std::size_t count=0;count<padding;++count){
		if(cursor>=text.size()||text[cursor]!=' ')return malformed("invalid muduo level padding");
		++cursor;
	}
	const auto location_separator=text.rfind(" - ");
	if(location_separator==std::string_view::npos||location_separator<cursor)
		return malformed("missing muduo source location suffix");
	const auto location=text.substr(location_separator+3);
	const auto colon=location.rfind(':');
	if(colon==std::string_view::npos||colon==0)return malformed("missing muduo source file or code line");
	std::uint64_t code_line=0;
	if(!parse_number(location.substr(colon+1),code_line)||code_line==0)
		return malformed("invalid or overflowing muduo code line");
	LogEvent event;
	event.format=LogFormat::muduo;
	event.raw_time=std::string(text.substr(0,25));
	event.timestamp=timestamp;
	event.time_basis=TimeBasis::explicit_timezone;
	event.level=level;
	event.raw_level=std::string(raw_level);
	event.thread_id=std::string(thread);
	event.code_file=std::string(location.substr(0,colon));
	event.code_line=code_line;
	event.message=std::string(text.substr(cursor,location_separator-cursor));
	event.line_start=input.line_number;
	event.line_end=input.line_number;
	event.raw_text=input.text;
	if(level==LogLevel::unknown)event.warnings.push_back("unrecognized muduo log level");
	return {LineParseStatus::parsed,std::move(event),{}};
}

} // namespace evidenceops::log_engine
