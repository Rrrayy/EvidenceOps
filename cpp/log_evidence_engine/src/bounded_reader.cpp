#include "log_engine/bounded_reader.hpp"

#include <array>
#include <limits>
#include <utility>

namespace evidenceops::log_engine {

BoundedReader::BoundedReader(std::string path,ReaderLimits limits)
	:path_(std::move(path)),limits_(limits){
	if(limits_.max_input_bytes==0||limits_.max_line_bytes==0){
		initial_error_=make_error(ReaderErrorCode::invalid_limits,"input and line limits must be positive");
		return;
	}
	stream_.open(path_,std::ios::binary);
	if(!stream_){
		initial_error_=make_error(ReaderErrorCode::file_open_failed,"input file could not be opened");
	}
}

ReadResult BoundedReader::next(){
	if(initial_error_){
		ReaderError error=std::move(*initial_error_);
		initial_error_.reset();
		finished_=true;
		return error;
	}
	if(finished_){
		return EndOfInput{};
	}
	if(!bom_checked_){
		if(!prepare_bom()){
			return fail(ReaderErrorCode::file_read_failed,"failed while checking the file prefix");
		}
		if(initial_error_){
			ReaderError error=std::move(*initial_error_);
			initial_error_.reset();
			finished_=true;
			return error;
		}
	}

	while(true){
		char value='\0';
		bool end_of_input=false;
		ReaderErrorCode failure_code=ReaderErrorCode::file_read_failed;
		if(!read_byte(value,end_of_input,failure_code)){
			const std::string message=failure_code==ReaderErrorCode::input_too_large
				?"input exceeded the configured byte limit":"failed while reading the input file";
			return fail(failure_code,message);
		}
		if(end_of_input){
			finished_=true;
			if(current_line_.empty()){
				return EndOfInput{};
			}
			return finish_line();
		}
		if(value=='\n'){
			if(!current_line_.empty()&&current_line_.back()=='\r'){
				current_line_.pop_back();
			}
			return finish_line();
		}
		current_line_.push_back(value);
		const bool possible_crlf=current_line_.size()>limits_.max_line_bytes
			&&current_line_.back()=='\r'
			&&current_line_.size()-1<=limits_.max_line_bytes;
		if(current_line_.size()>limits_.max_line_bytes&&!possible_crlf){
			return fail(ReaderErrorCode::line_too_long,"line exceeded the configured byte limit");
		}
	}
}

std::uint64_t BoundedReader::bytes_read() const noexcept{
	return bytes_read_;
}

bool BoundedReader::prepare_bom(){
	std::array<char,3> prefix{};
	std::size_t prefix_size=0;
	while(prefix_size<prefix.size()){
		char value='\0';
		bool end_of_input=false;
		ReaderErrorCode failure_code=ReaderErrorCode::file_read_failed;
		if(!read_byte(value,end_of_input,failure_code)){
			const std::string message=failure_code==ReaderErrorCode::input_too_large
				?"input exceeded the configured byte limit":"failed while checking the file prefix";
			initial_error_=make_error(failure_code,message);
			return true;
		}
		if(end_of_input){
			break;
		}
		prefix[prefix_size++]=value;
	}
	const bool has_bom=prefix_size==3
		&&static_cast<unsigned char>(prefix[0])==0xEF
		&&static_cast<unsigned char>(prefix[1])==0xBB
		&&static_cast<unsigned char>(prefix[2])==0xBF;
	if(has_bom&&!limits_.accept_utf8_bom){
		initial_error_=make_error(ReaderErrorCode::invalid_bom,"UTF-8 BOM is not accepted");
		return true;
	}
	if(!has_bom){
		prefix_.assign(prefix.data(),prefix_size);
	}
	bom_checked_=true;
	return true;
}

bool BoundedReader::read_byte(char& value,bool& end_of_input,ReaderErrorCode& failure_code){
	if(prefix_offset_<prefix_.size()){
		value=prefix_[prefix_offset_++];
		return true;
	}
	if(bytes_read_>=limits_.max_input_bytes){
		const auto next=stream_.peek();
		if(next==std::char_traits<char>::eof()){
			if(stream_.bad()){
				failure_code=ReaderErrorCode::file_read_failed;
				return false;
			}
			end_of_input=true;
			return true;
		}
		failure_code=ReaderErrorCode::input_too_large;
		return false;
	}
	if(!stream_.get(value)){
		if(stream_.bad()){
			failure_code=ReaderErrorCode::file_read_failed;
			return false;
		}
		end_of_input=true;
		return true;
	}
	++bytes_read_;
	return true;
}

bool BoundedReader::valid_utf8(const std::string& text) const noexcept{
	std::size_t index=0;
	while(index<text.size()){
		const auto first=static_cast<unsigned char>(text[index]);
		if(first<=0x7F){
			++index;
			continue;
		}
		std::size_t length=0;
		std::uint32_t codepoint=0;
		if(first>=0xC2&&first<=0xDF){
			length=2;
			codepoint=first&0x1F;
		}else if(first>=0xE0&&first<=0xEF){
			length=3;
			codepoint=first&0x0F;
		}else if(first>=0xF0&&first<=0xF4){
			length=4;
			codepoint=first&0x07;
		}else{
			return false;
		}
		if(index+length>text.size()){
			return false;
		}
		for(std::size_t offset=1;offset<length;++offset){
			const auto continuation=static_cast<unsigned char>(text[index+offset]);
			if((continuation&0xC0)!=0x80){
				return false;
			}
			codepoint=(codepoint<<6)|(continuation&0x3F);
		}
		if((length==2&&codepoint<0x80)||(length==3&&codepoint<0x800)||(length==4&&codepoint<0x10000)){
			return false;
		}
		if(codepoint>0x10FFFF||(codepoint>=0xD800&&codepoint<=0xDFFF)){
			return false;
		}
		index+=length;
	}
	return true;
}

ReaderError BoundedReader::make_error(ReaderErrorCode code,std::string message) const{
	return ReaderError{code,std::move(message),line_number_,bytes_read_};
}

ReadResult BoundedReader::fail(ReaderErrorCode code,std::string message){
	finished_=true;
	return make_error(code,std::move(message));
}

ReadResult BoundedReader::finish_line(){
	if(current_line_.size()>limits_.max_line_bytes){
		return fail(ReaderErrorCode::line_too_long,"line exceeded the configured byte limit");
	}
	if(!valid_utf8(current_line_)){
		return fail(ReaderErrorCode::invalid_utf8,"input line is not valid UTF-8");
	}
	InputLine line{line_number_,std::move(current_line_),0};
	line.byte_count=static_cast<std::uint64_t>(line.text.size());
	current_line_.clear();
	++line_number_;
	return line;
}

} // namespace evidenceops::log_engine
