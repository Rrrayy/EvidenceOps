#pragma once

#include <cstdint>
#include <fstream>
#include <optional>
#include <string>
#include <variant>

namespace evidenceops::log_engine {

struct ReaderLimits {
	std::uint64_t max_input_bytes=16*1024*1024;
	std::uint64_t max_line_bytes=256*1024;
	bool accept_utf8_bom=true;
};

struct InputLine {
	std::uint64_t line_number=0;
	std::string text;
	std::uint64_t byte_count=0;
};

struct EndOfInput {};

enum class ReaderErrorCode {
	file_open_failed,
	file_read_failed,
	invalid_utf8,
	line_too_long,
	input_too_large,
	invalid_bom,
	invalid_limits,
};

struct ReaderError {
	ReaderErrorCode code=ReaderErrorCode::file_read_failed;
	std::string message;
	std::uint64_t line_number=0;
	std::uint64_t bytes_read=0;
};

using ReadResult=std::variant<InputLine,EndOfInput,ReaderError>;

class BoundedReader {
public:
	BoundedReader(std::string path,ReaderLimits limits);
	ReadResult next();
	std::uint64_t bytes_read() const noexcept;

private:
	bool prepare_bom();
	bool read_byte(char& value,bool& end_of_input,ReaderErrorCode& failure_code);
	bool valid_utf8(const std::string& text) const noexcept;
	ReaderError make_error(ReaderErrorCode code,std::string message) const;
	ReadResult fail(ReaderErrorCode code,std::string message);
	ReadResult finish_line();

	std::string path_;
	ReaderLimits limits_;							//读取策略
	std::ifstream stream_;							
	std::string prefix_;							//检查BOM时预读的正文 
	std::size_t prefix_offset_=0;					//预读正文消费
	std::string current_line_;						
	std::uint64_t bytes_read_=0;
	std::uint64_t line_number_=1;
	std::optional<ReaderError> initial_error_;
	bool bom_checked_=false;
	bool finished_=false;
};

} // namespace evidenceops::log_engine
