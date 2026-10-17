cmake_minimum_required(VERSION 3.20)
project(log_evidence_engine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(log_engine_contract
	src/log_event.cpp
	src/bounded_reader.cpp
	src/zookeeper_parser.cpp
	src/glog_parser.cpp
	src/muduo_parser.cpp
	src/plain_parser.cpp
	src/json_output.cpp
	src/engine.cpp
)

target_include_directories(log_engine_contract PUBLIC include)
add_executable(log_evidence_cli src/main.cpp)
target_link_libraries(log_evidence_cli PRIVATE log_engine_contract)

if(MSVC)
	target_compile_options(log_engine_contract PRIVATE /W4 /permissive-)
else()
	target_compile_options(log_engine_contract PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
endif()

add_executable(log_engine_contract_test
	tests/log_event_test.cpp
)

target_link_libraries(log_engine_contract_test PRIVATE log_engine_contract)

add_executable(log_engine_reader_test
	tests/bounded_reader_test.cpp
)

target_link_libraries(log_engine_reader_test PRIVATE log_engine_contract)

enable_testing()
find_package(Python3 COMPONENTS Interpreter REQUIRED)
add_test(NAME log_engine_cli_test COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/cli_test.py $<TARGET_FILE:log_evidence_cli>)
add_executable(log_engine_plain_test tests/plain_parser_test.cpp)
target_link_libraries(log_engine_plain_test PRIVATE log_engine_contract)
add_test(NAME log_engine_plain_test COMMAND log_engine_plain_test)
add_executable(log_engine_muduo_test tests/muduo_parser_test.cpp)
target_link_libraries(log_engine_muduo_test PRIVATE log_engine_contract)
add_test(NAME log_engine_muduo_test COMMAND log_engine_muduo_test)
add_executable(log_engine_glog_test tests/glog_parser_test.cpp)
target_link_libraries(log_engine_glog_test PRIVATE log_engine_contract)
add_test(NAME log_engine_glog_test COMMAND log_engine_glog_test)
add_executable(log_engine_zookeeper_test tests/zookeeper_parser_test.cpp)
target_link_libraries(log_engine_zookeeper_test PRIVATE log_engine_contract)
add_test(NAME log_engine_zookeeper_test COMMAND log_engine_zookeeper_test)
add_test(NAME log_engine_contract_test COMMAND log_engine_contract_test)
add_test(NAME log_engine_reader_test COMMAND log_engine_reader_test)
foreach(test_target log_engine_contract_test log_engine_reader_test log_engine_plain_test log_engine_muduo_test log_engine_glog_test log_engine_zookeeper_test)
	if(MSVC)
		target_compile_options(${test_target} PRIVATE /UNDEBUG)
	else()
		target_compile_options(${test_target} PRIVATE -UNDEBUG)
	endif()
endforeach()
