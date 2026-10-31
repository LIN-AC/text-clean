cmake_minimum_required(VERSION 3.16)
project(text_clean VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

if(MSVC)
  add_compile_options(/utf-8 /W4)
else()
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(TC_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)
set(TC_DATA_DIR ${CMAKE_CURRENT_SOURCE_DIR}/data)

add_library(tc_utf8 INTERFACE)
target_include_directories(tc_utf8 INTERFACE ${TC_INCLUDE_DIR})

function(tc_library name)
  add_library(${name} STATIC ${ARGN})
  target_include_directories(${name} PUBLIC ${TC_INCLUDE_DIR})
endfunction()

# Each algorithm lives in its own library. Only the pipeline links them together.
tc_library(tc_ac src/ac_automaton.cpp)
tc_library(tc_pinyin_index src/pinyin_index.cpp)

add_library(tc_edit_distance INTERFACE)
target_include_directories(tc_edit_distance INTERFACE ${TC_INCLUDE_DIR})

tc_library(tc_pinyin_dict src/pinyin_dict.cpp)
target_link_libraries(tc_pinyin_dict PUBLIC tc_utf8)

tc_library(tc_lexicon src/lexicon.cpp)
target_link_libraries(tc_lexicon PUBLIC tc_utf8)

tc_library(tc_word_maintaining src/word_maintaining.cpp)
target_link_libraries(tc_word_maintaining PUBLIC tc_utf8)

tc_library(tc_text_split src/text_split.cpp)
target_link_libraries(tc_text_split PUBLIC tc_utf8)

tc_library(tc_word_review src/word_review.cpp)
target_link_libraries(tc_word_review
  PUBLIC tc_word_maintaining tc_text_split tc_utf8)

tc_library(tc_pipeline src/text_cleaner.cpp)
target_link_libraries(tc_pipeline
  PUBLIC tc_ac tc_pinyin_index tc_edit_distance tc_pinyin_dict tc_lexicon tc_utf8)

add_executable(text_clean src/main.cpp)
target_link_libraries(text_clean
  PRIVATE tc_pipeline tc_word_maintaining tc_text_split tc_word_review)
target_compile_definitions(text_clean PRIVATE TC_DATA_DIR="${TC_DATA_DIR}")
if(WIN32)
  target_link_libraries(text_clean PRIVATE shell32)
endif()

enable_testing()

function(tc_test name)
  add_executable(${name} tests/${name}.cpp)
  target_link_libraries(${name} PRIVATE ${ARGN})
  target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
  add_test(NAME ${name} COMMAND ${name})
endfunction()

tc_test(test_utf8 tc_utf8)
tc_test(test_ac_automaton tc_ac)
tc_test(test_pinyin_index tc_pinyin_index)
tc_test(test_edit_distance tc_edit_distance)
tc_test(test_pinyin_dict tc_pinyin_dict)
target_compile_definitions(test_pinyin_dict PRIVATE TC_DATA_DIR="${TC_DATA_DIR}")
tc_test(test_lexicon tc_lexicon)
tc_test(test_word_maintaining tc_word_maintaining)
tc_test(test_text_split tc_text_split)
tc_test(test_word_review tc_word_review)
tc_test(test_text_cleaner tc_pipeline)
