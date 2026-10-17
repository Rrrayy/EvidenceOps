#include "log_engine/bounded_reader.hpp"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <filesystem>
#include <chrono>
#include <random>
#include <stdexcept>
#include <string>
#include <variant>

using namespace evidenceops::log_engine;

namespace {

class TemporaryInputs {
public:
	TemporaryInputs(){
		const auto parent=std::filesystem::temp_directory_path();
		std::random_device random;
		for(int attempt=0;attempt<32;++attempt){
			const auto candidate=parent/("evidenceops-reader-"+std::to_string(random())+"-"+std::to_string(attempt));
			if(std::filesystem::create_directory(candidate)){directory=candidate;return;}
		}
		throw std::runtime_error("could not create isolated test directory");
	}
	~TemporaryInputs(){
		std::error_code error;
		std::filesystem::remove_all(directory,error);
	}
	std::filesystem::path directory;
};

TemporaryInputs& temporary_inputs(){
	static TemporaryInputs inputs;
	return inputs;
}

std::string write_input(const std::string& name,const std::string& bytes){
	const std::string path=(temporary_inputs().directory/name).string();
	std::ofstream output(path,std::ios::binary);
	if(!output)throw std::runtime_error("test input could not be opened");
	output.write(bytes.data(),static_cast<std::streamsize>(bytes.size()));
	output.close();
	if(!output)throw std::runtime_error("test input could not be written");
	return path;
}

ReaderErrorCode read_error(const std::string& path,ReaderLimits limits){
	BoundedReader reader(path,limits);
	const ReadResult result=reader.next();
	assert(std::holds_alternative<ReaderError>(result));
	return std::get<ReaderError>(result).code;
}

}

int main(){
	const auto empty_path=write_input("evidenceops-reader-empty.log","");
	BoundedReader empty_reader(empty_path,ReaderLimits{8,8,true});
	assert(std::holds_alternative<EndOfInput>(empty_reader.next()));

	const auto line_path=write_input("evidenceops-reader-lines.log","one\r\ntwo\n\n");
	BoundedReader line_reader(line_path,ReaderLimits{64,8,true});
	const auto first=line_reader.next();
	assert(std::get<InputLine>(first).line_number==1);
	assert(std::get<InputLine>(first).text=="one");
	const auto second=line_reader.next();
	assert(std::get<InputLine>(second).line_number==2);
	assert(std::get<InputLine>(second).text=="two");
	const auto blank=line_reader.next();
	assert(std::get<InputLine>(blank).line_number==3);
	assert(std::get<InputLine>(blank).text.empty());
	assert(std::holds_alternative<EndOfInput>(line_reader.next()));

	const std::string bom="\xEF\xBB\xBF";
	const auto bom_path=write_input("evidenceops-reader-bom.log",bom+"text");
	BoundedReader bom_reader(bom_path,ReaderLimits{64,8,true});
	assert(std::get<InputLine>(bom_reader.next()).text=="text");
	assert(read_error(bom_path,ReaderLimits{64,8,false})==ReaderErrorCode::invalid_bom);

	const auto invalid_path=write_input("evidenceops-reader-invalid.log",std::string("bad\xFF",4));
	assert(read_error(invalid_path,ReaderLimits{64,8,true})==ReaderErrorCode::invalid_utf8);

	const auto long_path=write_input("evidenceops-reader-long.log","12345\n");
	assert(read_error(long_path,ReaderLimits{64,4,true})==ReaderErrorCode::line_too_long);

	const auto large_path=write_input("evidenceops-reader-large.log","12345\n");
	assert(read_error(large_path,ReaderLimits{4,8,true})==ReaderErrorCode::input_too_large);

	const auto exact_path=write_input("evidenceops-reader-exact.log","1234");
	BoundedReader exact_reader(exact_path,ReaderLimits{4,4,true});
	assert(std::get<InputLine>(exact_reader.next()).text=="1234");
	assert(std::holds_alternative<EndOfInput>(exact_reader.next()));

	const auto crlf_limit_path=write_input("evidenceops-reader-crlf-limit.log","1234\r\n");
	BoundedReader crlf_limit_reader(crlf_limit_path,ReaderLimits{8,4,true});
	assert(std::get<InputLine>(crlf_limit_reader.next()).text=="1234");

	const auto utf8_path=write_input("evidenceops-reader-utf8.log","\xE4\xB8\xAD");
	BoundedReader utf8_reader(utf8_path,ReaderLimits{3,3,true});
	const auto utf8_line=std::get<InputLine>(utf8_reader.next());
	assert(utf8_line.byte_count==3);

	assert(read_error(exact_path,ReaderLimits{0,4,true})==ReaderErrorCode::invalid_limits);

	assert(read_error((temporary_inputs().directory/"missing.log").string(),ReaderLimits{8,8,true})==ReaderErrorCode::file_open_failed);


	const auto partial_path=write_input("evidenceops-reader-partial-limit.log","ab\ncde\n");
	BoundedReader partial_reader(partial_path,ReaderLimits{5,8,true});
	const auto partial_first=partial_reader.next();
	assert(std::holds_alternative<InputLine>(partial_first));
	assert(std::get<InputLine>(partial_first).line_number==1);
	assert(std::get<InputLine>(partial_first).text=="ab");
	assert(std::get<InputLine>(partial_first).byte_count==2);
	const auto partial_second=partial_reader.next();
	assert(std::holds_alternative<ReaderError>(partial_second));
	assert(std::get<ReaderError>(partial_second).code==ReaderErrorCode::input_too_large);
	assert(std::get<ReaderError>(partial_second).line_number==2);
	assert(std::get<ReaderError>(partial_second).bytes_read==5);
	assert(std::holds_alternative<EndOfInput>(partial_reader.next()));

	const auto trailing_cr_path=write_input("trailing-cr.log","ab\r");
	BoundedReader trailing_cr(trailing_cr_path,ReaderLimits{8,8,true});
	assert(std::get<InputLine>(trailing_cr.next()).text=="ab\r");
	BoundedReader trailing_cr_limit(trailing_cr_path,ReaderLimits{8,2,true});
	assert(std::get<ReaderError>(trailing_cr_limit.next()).code==ReaderErrorCode::line_too_long);
	return 0;
}
