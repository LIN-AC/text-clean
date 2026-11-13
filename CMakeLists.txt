cmake_minimum_required(VERSION 3.16)
project(text_clean VERSION 1.2.3 LANGUAGES CXX)

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

tc_library(tc_word_frequency src/word_frequency.cpp)
target_link_libraries(tc_word_frequency PUBLIC tc_utf8)

tc_library(tc_text_split src/text_split.cpp)
target_link_libraries(tc_text_split PUBLIC tc_utf8)

tc_library(tc_word_review src/word_review.cpp)
target_link_libraries(tc_word_review
  PUBLIC tc_word_maintaining tc_text_split tc_utf8)

tc_library(tc_video_context src/video_context.cpp)
target_link_libraries(tc_video_context PUBLIC tc_ac tc_utf8)

tc_library(tc_vocabulary src/vocabulary.cpp)
target_link_libraries(tc_vocabulary PUBLIC tc_utf8)

tc_library(tc_char_frequency src/char_frequency.cpp)
target_link_libraries(tc_char_frequency PUBLIC tc_utf8)

tc_library(tc_domain_evidence src/domain_evidence.cpp)
target_link_libraries(tc_domain_evidence PUBLIC tc_utf8)

tc_library(tc_pipeline src/text_cleaner.cpp)
tc_library(tc_dictionary_bundle src/dictionary_bundle.cpp)
target_link_libraries(tc_dictionary_bundle PUBLIC tc_lexicon tc_pinyin_dict tc_vocabulary tc_word_maintaining)
target_link_libraries(tc_pipeline
  PUBLIC tc_vocabulary tc_video_context tc_ac tc_pinyin_index tc_edit_distance tc_pinyin_dict tc_lexicon
         tc_word_frequency tc_char_frequency tc_word_maintaining tc_domain_evidence tc_utf8)

add_executable(text_clean src/main.cpp)
target_link_libraries(text_clean
  PRIVATE tc_pipeline tc_dictionary_bundle tc_word_maintaining tc_text_split tc_word_review)
target_compile_definitions(text_clean PRIVATE TC_DATA_DIR="${TC_DATA_DIR}")
if(WIN32)
  target_link_libraries(text_clean PRIVATE shell32)
endif()

enable_testing()

# V2 research retrieval is optional; the V1 executable has no SQLite dependency.
option(TC_BUILD_RETRIEVAL "Build the native V2 evidence retriever" OFF)
if(TC_BUILD_RETRIEVAL)
  find_package(SQLite3 REQUIRED)
  tc_library(tc_retrieval src/retrieval.cpp)
  if(TARGET SQLite3::SQLite3)
    target_link_libraries(tc_retrieval PUBLIC tc_utf8 SQLite3::SQLite3)
  else()
    target_link_libraries(tc_retrieval PUBLIC tc_utf8 SQLite::SQLite3)
  endif()
  add_executable(tc_retrieve src/retrieval_main.cpp)
  target_link_libraries(tc_retrieve PRIVATE tc_retrieval)
endif()

function(tc_test name)
  add_executable(${name} tests/${name}.cpp)
  target_link_libraries(${name} PRIVATE ${ARGN})
  target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
  add_test(NAME ${name} COMMAND ${name})
endfunction()

tc_test(test_utf8 tc_utf8)
tc_test(test_dictionary_bundle tc_dictionary_bundle)
target_compile_definitions(test_dictionary_bundle PRIVATE TC_NEW_DATA_DIR="${TC_DATA_DIR}")
tc_test(test_decision_safety tc_pipeline)
tc_test(test_zipf_scoring tc_pipeline)
tc_test(test_missing_evidence tc_pipeline)
tc_test(test_ac_automaton tc_ac)
tc_test(test_pinyin_index tc_pinyin_index)
tc_test(test_edit_distance tc_edit_distance)
tc_test(test_pinyin_dict tc_pinyin_dict)
target_compile_definitions(test_pinyin_dict PRIVATE TC_DATA_DIR="${TC_DATA_DIR}/old")
tc_test(test_lexicon tc_lexicon)
tc_test(test_word_maintaining tc_word_maintaining)
tc_test(test_word_frequency tc_word_frequency)
tc_test(test_char_frequency tc_char_frequency)
tc_test(test_text_split tc_text_split)
tc_test(test_word_review tc_word_review)
tc_test(test_text_cleaner tc_pipeline)
tc_test(test_legitimacy tc_pipeline)
target_compile_definitions(test_legitimacy PRIVATE TC_DATA_DIR="${TC_DATA_DIR}/old")
tc_test(test_tone_correction tc_pipeline)
target_compile_definitions(test_tone_correction PRIVATE TC_DATA_DIR="${TC_DATA_DIR}/old")

tc_test(test_video_context tc_pipeline)
target_compile_definitions(test_video_context PRIVATE TC_DATA_DIR="${TC_DATA_DIR}/old")

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
  if(TC_BUILD_RETRIEVAL)
    add_test(NAME test_proposal_clean COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_proposal_clean.py $<TARGET_FILE:tc_retrieve>)
  endif()
  add_test(NAME test_rag_clean COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_rag_clean.py)
  add_test(NAME test_cli_bundle COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_cli_bundle.py $<TARGET_FILE:text_clean>)
  add_test(NAME test_ngram_veto COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_ngram_veto.py)
  add_test(NAME test_cli_context COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_cli_context.py $<TARGET_FILE:text_clean>
    ${CMAKE_CURRENT_BINARY_DIR})
endif()

tc_test(test_priority tc_pipeline)
target_compile_definitions(test_priority PRIVATE TC_DATA_DIR="${TC_DATA_DIR}/old")

tc_test(test_word_pronunciation tc_pipeline)
target_compile_definitions(test_word_pronunciation PRIVATE TC_DATA_DIR="${TC_DATA_DIR}/old")
