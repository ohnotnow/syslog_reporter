from datetime import datetime
import os
import streamlit as st
import argparse
import time
import json
from gepetto import gpt, gemini
from main import get_log_stats, load_config, scan_logfile, issues_list_to_report, resolutions_to_report, output_final_report
import logreader
import pandas as pd
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain_openai import ChatOpenAI

def setup_agent(df):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_pandas_dataframe_agent(
        llm,
        df,
        agent_type="tool-calling",
        verbose=True,
        allow_dangerous_code=True
    )
    if 'df' not in st.session_state:
        st.session_state.df = df
    if 'agent' not in st.session_state:
        st.session_state.agent = agent
    return agent

def get_syslog(file):
    # Pull syslog from the Linux system
    try:
        syslog_contents = os.popen('sudo dmesg').read()
        if not syslog_contents:
            return "Failed to retrieve system logs"
    except Exception as e:
        return f"An error occurred while retrieving system logs: {e}"

    # Save the syslog contents to the specified file
    with open(file, 'w') as f:
        f.write(syslog_contents)

    with open(file, 'r') as f:
        log_contents = f.read()
    return log_contents

def output_final_report_for_chat_app(cost, log_length, number_of_issues, model, total_time):
    today_string = datetime.now().strftime("%Y-%m-%d")
    seconds = round(total_time % 60)
    minutes = round((total_time // 60) % 60)
    final_report = f"## Log Report @ {today_string} {number_of_issues} (issues)\n\n"
    final_report += f"- Cost: US${cost:.3f} for {log_length} processed lines using {model} in {minutes:02d}m {seconds:02d}s_\n\n"
    return final_report

def generate_report(issue_model, suggestion_model, resolutions, dry_count,
                     remove_duplicates, config_file, show_log, overrides):
    start_time = time.time()
    # file = "/tmp/syslog.log"
    file = "syslog.log"
    # Read log contents
    # log_contents = get_syslog(file)
    # with open(file, 'r') as f:
    #     log_contents = f.read()
        
    config = load_config(config_file, overrides)

    log_contents = logreader.read_logfile(file, config.ignore_list, config.match_list, config.replacement_map, config.regex_ignore_list)
    if len(log_contents) == 0:
        return "No log entries found"

    if remove_duplicates:
        log_contents = logreader.filter_duplicate_logs(log_contents, max_occurrences=3, normalise_map=config.normalise_map)

    # if show_log:
    #     st.text_area("Log Contents", log_contents, height=300)

    #if dry_count:
    #         # st.warning("Dry count is enabled. No suggestions will be generated.")
    #     log_length, token_length = get_log_stats(log_contents, issue_model)
    #     st.text_area(f"Length: {log_length} lines")
    #     st.text_area(f"Tokens: {token_length} tokens")

    # Scan logfile
    issues, cost = scan_logfile(log_contents, config.log_scan_prompt, config.log_merge_prompt, line_chunk_size=500, model=issue_model)
    issues_list = [{"id": key, **value} for key, value in issues.items()]
    with open('issues.json', 'w') as json_file:
        json.dump(issues_list, json_file, indent=4)

    # Store issues in a pandas DataFrame
    df = pd.DataFrame(issues_list)
    if df.empty:
            return("No issues found. Fetch & Generate the report after some time")

    setup_agent(df)
    # report = agent.run("Summarize the issues with all the details in a tabular format")
   
    end_time = time.time()
    total_time = end_time - start_time
    number_of_issues = len(issues_list)
    final_report = output_final_report_for_chat_app(cost, len(log_contents),number_of_issues,issue_model, total_time)
    return final_report



def clear_chat_history():
    st.session_state.messages = [{"role": "assistant", "content": "How may I assist you today?"}]

def main():
    st.title("Syslog Analyser Chat bot")
    issue_model = gpt.Model.GPT_4_OMNI_MINI.value[0]
    suggestion_model = gpt.Model.GPT_4_OMNI_MINI.value[0]
    generate_button = False
    config_file = "prompts"
    show_log = False
    overrides = "local_overrides.py"
    # Settings in left sidebar
    with st.sidebar:
        st.header("Settings")
        
        # Check if API key exists in environment variables
        if 'OPENAI_API_KEY' in st.secrets:
            st.success('API key already provided!', icon='✅')
            openai_api = st.secrets['OPENAI_API_KEY']
        else:
            openai_api = st.text_input('Enter OpenAI API token:', type='password')
        
        os.environ['OPENAI_API_KEY'] = openai_api
        resolutions = st.checkbox("Resolutions", value=False)
        dry_count = st.checkbox("Dry Count", value=False)
        remove_duplicates = st.checkbox("Remove Duplicates", value=True)

        generate_button = st.sidebar.button('Fetch & analyse syslog')
        st.sidebar.button('Clear Chat History', on_click=clear_chat_history)
    
    if not openai_api:
        st.warning("Please provide OpenAI API key to enable chat interface")
        return

    if not (openai_api.startswith('sk-')):
        st.warning('OPENAI_API_KEY is not a valid one (does not start with sk-).. Please enter correct Key!', icon='⚠️')
        return
            
    if 'df' in st.session_state:
        st.dataframe(st.session_state.df, use_container_width=True)
    
    if 'agent' in st.session_state:
        agent = st.session_state.agent
    elif os.path.exists("issues.json"):
        date_list = json.load(open("issues.json"))
        df = pd.DataFrame(date_list)
        if df.empty:
            st.warning("No old issues found. Fetch & Generate the report")
            return
        else:
            agent = setup_agent(df)
            st.dataframe(st.session_state.df, use_container_width=True)
    else:
        if not generate_button:
            st.warning("No old issues found. Fetch & Generate the report")
            return

    # Store LLM generated responses
    if "messages" not in st.session_state.keys():
        st.session_state.messages = [{"role": "assistant", "content": "How may I assist you today?"}]
    
    # Display or clear chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    
    if prompt := st.chat_input(disabled=not openai_api):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

    # Generate a new response if last message is not from assistant
    if generate_button or st.session_state.messages[-1]["role"] != "assistant":
        with st.chat_message("assistant"):
            if generate_button:
                with st.spinner("Analysing... it will take around a minute"):
                    response = generate_report(issue_model, suggestion_model, resolutions, dry_count,
                     remove_duplicates, config_file, show_log, overrides)
            else:
                with st.spinner("Thinking.."):
                    response = agent.run(prompt)
            placeholder = st.empty()
            full_response = ''
            for item in response:
                full_response += item
                placeholder.markdown(full_response)
            placeholder.markdown(full_response)
        message = {"role": "assistant", "content": full_response}
        st.session_state.messages.append(message)
        if generate_button and 'df' in st.session_state:
            # Display the DataFrame using st.dataframe
            st.dataframe(st.session_state.df, use_container_width=True)

if __name__ == "__main__":
    main()