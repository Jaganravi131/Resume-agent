from google.adk.agents.llm_agent import Agent
stock_tutor = Agent(
    model='gemini-3.5-flash',
    name='Stock_tutor_agent',
    description='helptudents to learn stock market by guiding them throught teaching  fundamental analysis and technical analysis.',
    instruction='You are a frustrated stock tutor. help students to learn stock market.',
)

root_agent = Agent(
    model='gemini-3.5-flash',
    name='Math_tutor_agent',
    description='help students to learn algebra by guiding them throught problem solving steps.',
    instruction='You are a patient math tutor. help students to learn algebra.',
    sub_agents=[stock_tutor],
)