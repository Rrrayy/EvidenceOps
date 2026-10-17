	#include "log_engine/zookeeper_parser.hpp"

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
	if(text.size()!=23)return false;
	for(std::size_t index=0;index<text.size();++index){
		char separator='\0';
		if(index==4||index==7)separator='-';
		else if(index==10)separator=' ';
		else if(index==13||index==16)separator=':';
		else if(index==19)separator=',';
		if(separator!='\0'){
			if(text[index]!=separator)return false;
		}else if(text[index]<'0'||text[index]>'9'){
			return false;
		}
	}
	std::uint64_t year=0,month=0,day=0,hour=0,minute=0,second=0;
	if(!parse_number(text.substr(0,4),year)||!parse_number(text.substr(5,2),month)
		||!parse_number(text.substr(8,2),day)||!parse_number(text.substr(11,2),hour)
		||!parse_number(text.substr(14,2),minute)||!parse_number(text.substr(17,2),second))return false;
	if(year==0||month<1||month>12||hour>23||minute>59||second>59)return false;
	const unsigned days[]={31,28,31,30,31,30,31,31,30,31,30,31};
	const bool leap=year%4==0&&(year%100!=0||year%400==0);
	const auto maximum=days[month-1]+(month==2&&leap?1U:0U);
	return day>=1&&day<=maximum;
}

bool valid_thread(std::string_view text){
	if(text.size()<3||text[0]!='0'||(text[1]!='x'&&text[1]!='X'))return false;
	for(std::size_t index=2;index<text.size();++index){
		const char character=text[index];
		if(!((character>='0'&&character<='9')||(character>='a'&&character<='f')
			||(character>='A'&&character<='F')))return false;
	}
	return true;
}

LineParseResult malformed(std::string message){
	return {LineParseStatus::malformed,std::nullopt,{std::move(message)}};
}

} // namespace

LineParseResult parse_zookeeper_line(const InputLine& input){
	const std::string_view text=input.text;
	if(text.size()<10||text[4]!='-'||text[7]!='-')return {};
	std::size_t marker=std::string_view::npos;
	for(std::size_t index=10;index+5<=text.size();++index){
		if(text[index]==':'&&normalize_token(text.substr(index+1,4))=="zoo_"){
			marker=index;
			break;
		}
	}
	if(marker==std::string_view::npos)return {};
	if(input.line_number==0)return malformed("input line number must be positive");
	if(text.size()<24||!valid_time(text.substr(0,23))||text[23]!=':')
		return malformed("invalid ZooKeeper date or time header");
	const auto open=text.find('(',24);
	if(open==std::string_view::npos||open>=marker||marker==0||text[marker-1]!=')')
		return malformed("invalid ZooKeeper process/thread header");
	std::uint64_t process_id=0;
	if(!parse_number(text.substr(24,open-24),process_id))
		return malformed("invalid or overflowing ZooKeeper process id");
	const auto thread=text.substr(open+1,marker-open-2);
	if(!valid_thread(thread))return malformed("invalid ZooKeeper hexadecimal thread id");
	const auto first_at=text.find('@',marker+1);
	if(first_at==std::string_view::npos)return malformed("missing ZooKeeper level separator");
	const auto second_at=text.find('@',first_at+1);
	if(second_at==std::string_view::npos||second_at==first_at+1)
		return malformed("missing ZooKeeper function or code line separator");
	const auto message_separator=text.find(':',second_at+1);
	if(message_separator==std::string_view::npos)return malformed("missing ZooKeeper message separator");
	std::uint64_t code_line=0;
	if(!parse_number(text.substr(second_at+1,message_separator-second_at-1),code_line)||code_line==0)
		return malformed("invalid or overflowing ZooKeeper code line");
	const auto raw_level=text.substr(marker+1,first_at-marker-1);
	if(raw_level.size()<=4)return malformed("missing ZooKeeper level name");
	LogEvent event;
	event.format=LogFormat::zookeeper;
	event.raw_time=std::string(text.substr(0,23));
	event.raw_level=std::string(raw_level);
	event.level=parse_log_level(raw_level.substr(4));
	event.process_id=process_id;
	event.thread_id=std::string(thread);
	event.code_function=std::string(text.substr(first_at+1,second_at-first_at-1));
	event.code_line=code_line;
	event.line_start=input.line_number;
	event.line_end=input.line_number;
	event.raw_text=input.text;
	auto message_start=message_separator+1;
	if(message_start<text.size()&&text[message_start]==' ')++message_start;
	event.message=std::string(text.substr(message_start));
	event.warnings.push_back("event timezone is unknown; timestamp was not generated");
	if(event.level==LogLevel::unknown)event.warnings.push_back("unrecognized ZooKeeper log level");
	return {LineParseStatus::parsed,std::move(event),{}};
}

} // namespace evidenceops::log_engine
