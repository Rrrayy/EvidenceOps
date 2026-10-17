#include "log_engine/engine.hpp"

#include <charconv>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

using namespace evidenceops::log_engine;

namespace {

std::uint64_t positive_number(const std::string& text){
	std::uint64_t value=0;
	const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
	if(result.ec!=std::errc{}||result.ptr!=text.data()+text.size()||value==0)
		throw std::invalid_argument("limits must be positive decimal integers");
	return value;
}

} // namespace

int main(int argument_count,char* arguments[]){
	try{
#ifdef _WIN32
		_setmode(_fileno(stdout),_O_BINARY);
#endif
		EngineOptions options;
		std::set<std::string> seen;
		for(int index=1;index<argument_count;++index){
			const std::string name=arguments[index];
			if(name=="--help"){
				std::cerr<<"Usage: log_evidence_cli --input FILE --source-id ID [--role server|client|unknown] [--service NAME] [--environment NAME] [--max-input-bytes N] [--max-line-bytes N] [--max-events N] [--max-output-bytes N] [--bom accept|reject]\n";
				return 0;
			}
			if(!seen.insert(name).second||index+1>=argument_count)throw std::invalid_argument("duplicate option or missing option value");
			const std::string value=arguments[++index];
			if(name=="--input")options.input_path=value;
			else if(name=="--source-id")options.source.source_id=value;
			else if(name=="--role"){
				const auto role=normalize_token(value);
				if(role!="server"&&role!="client"&&role!="unknown")throw std::invalid_argument("invalid source role");
				options.source.source_role=parse_source_role(value);
			}else if(name=="--service")options.source.service_name=value;
			else if(name=="--environment")options.source.environment=value;
			else if(name=="--max-input-bytes")options.reader_limits.max_input_bytes=positive_number(value);
			else if(name=="--max-line-bytes")options.reader_limits.max_line_bytes=positive_number(value);
			else if(name=="--max-events")options.max_events=positive_number(value);
			else if(name=="--max-output-bytes")options.max_output_bytes=positive_number(value);
			else if(name=="--bom"){
				if(value!="accept"&&value!="reject")throw std::invalid_argument("BOM policy must be accept or reject");
				options.reader_limits.accept_utf8_bom=value=="accept";
			}else throw std::invalid_argument("unknown command line option");
		}
		if(options.input_path.empty()||options.source.source_id.empty())throw std::invalid_argument("--input and --source-id are required");
		const auto output=run_engine(options);
		std::cout.write(output.json.data(),static_cast<std::streamsize>(output.json.size()));
		std::cout.flush();
		if(!std::cout)throw std::runtime_error("failed to write stdout");
		if(output.exit_code!=0)std::cerr<<"input processing did not complete; inspect JSON status and stop_reason\n";
		return output.exit_code;
	}catch(const std::invalid_argument& error){
		std::cerr<<error.what()<<'\n';return 3;
	}catch(const std::exception& error){
		std::cerr<<error.what()<<'\n';return 1;
	}catch(...){
		std::cerr<<"unexpected internal failure\n";return 1;
	}
}
