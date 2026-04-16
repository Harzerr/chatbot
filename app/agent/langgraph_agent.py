import operator
from typing import Annotated, TypedDict, Literal, Sequence, List, Optional, Dict

try:
    from typing import Required  # Python 3.11+
except ImportError:  # pragma: no cover - compatibility for Python <=3.10
    from typing_extensions import Required

from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph, START
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from app.core.config import settings
from app.mcp_client.client import get_mcp_client
from app.services.skill_registry import SkillRegistry, create_default_skill_registry
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class MCPToolSetup:
    def __init__(self, client_name: Literal["Researcher", "Scrapper"], tools):
        self.client_name = client_name
        self.tools = tools


class MCPConfig(TypedDict):
    client_name: Required[Literal["Researcher", "Scrapper"]]
    server_url: Required[str]


class MCPTools:
    def __init__(self, mcp_configs: List[MCPConfig]):
        self.mcp_configs = mcp_configs or []
        self.tools = []
        self.mcp_clients = []

    async def setup_mcp_tools(self) -> List[MCPToolSetup]:
        setups = []
        all_tools = []

        for config in self.mcp_configs:
            client_name = config.get("client_name")
            server_url = config.get("server_url")

            logger.info(f"Creating MCP client {client_name} connecting to server at {server_url}")

            client, tools = await get_mcp_client(server_url, client_name)

            if client:
                self.mcp_clients.append(client)

                if tools:
                    logger.info(f"Loaded {len(tools)} tools from {server_url}")
                    all_tools.extend(tools)
                    setups.append(MCPToolSetup(tools=tools, client_name=client_name))
                else:
                    logger.warning(f"No tools were loaded from {server_url}")
            else:
                logger.warning(f"Could not establish connection to {server_url}")

        if all_tools:
            self.tools = all_tools
            logger.info(f"MCP client created successfully with {len(all_tools)} tools")
        else:
            logger.error("No tools were loaded from any server, agent cannot be created")

        return setups

    async def cleanup(self) -> None:
        clients_to_close = list(reversed(self.mcp_clients))
        for client in clients_to_close:
            if client:
                try:
                    await client.close()
                except Exception as e:
                    logger.error(f"Error closing client: {str(e)}")

        logger.info(f"Closed {len(self.mcp_clients)} MCP client connections")
        self.mcp_clients = []


_graph: CompiledStateGraph | None = None
_mcp_tools: MCPTools | None = None
_skill_registry: SkillRegistry | None = None


class AgentState(TypedDict):
    """State for the multi-agent system."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next: str
    task_completed: bool
    iterations: int
    max_iterations: int
    interview_mode: bool
    active_skill: Optional[str]
    previous_interviewer_question: Optional[str]
    relevant_docs: List[dict]
    context: str
    interview_role: Optional[str]
    interview_level: Optional[str]
    interview_type: Optional[str]
    target_company: Optional[str]
    jd_content: Optional[str]
    resume_content: Optional[str]
    evaluation: Optional[dict]
    is_finished: bool


class RouteResponse(BaseModel):
    """Response from supervisor agent."""
    next: Literal["Researcher", "Scrapper", "FINISH"]
    reasoning: str
    response: Optional[str] = None


async def agent_node(state, agent, name):
    """Process the state through an agent and return the updated state."""
    try:
        logger.info(f"Invoking {name} agent with state: {state.get('messages', [])[-1].content if state.get('messages') else 'No messages'}")

        result = await agent.ainvoke(state)
        logger.info(f"Agent {name} result: {result}")

        iterations = state.get("iterations", 0) + 1
        return {
            "messages": [AIMessage(content=result["messages"][-1].content, name=name)],
            "iterations": iterations
        }
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in {name} agent node: {str(e)}\n{error_details}")

        return {
            "messages": [AIMessage(content=f"I encountered an issue while processing your request. {str(e)}", name=name)],
            "iterations": state.get("iterations", 0) + 1
        }


async def supervisor_agent(state: AgentState) -> Dict:
    """Supervisor agent that decides which agent to use next."""
    messages = state["messages"]
    iterations = state["iterations"]
    max_iterations = state["max_iterations"]

    if _skill_registry is not None:
        requested_skill = state.get("active_skill")
        if isinstance(requested_skill, str) and requested_skill and _skill_registry.get(requested_skill) is None:
            return {
                "next": "FINISH",
                "task_completed": True,
                "direct_response": f"未找到已注册的 skill：{requested_skill}",
                "messages": messages + [AIMessage(content=f"未找到已注册的 skill：{requested_skill}", name="Supervisor")],
            }

        skill_definition = _skill_registry.resolve(state)
        if skill_definition is not None:
            logger.info("Supervisor dispatching to registered skill: %s", skill_definition.name)
            return {
                "next": "SkillRunner",
                "active_skill": skill_definition.name,
                "task_completed": False,
            }

    if state.get("interview_mode", False):
        logger.warning("interview_mode requested but interview-skills is not registered")
        return {
            "next": "FINISH",
            "task_completed": True,
            "direct_response": "面试 skill 暂不可用，请稍后重试。",
        }

    conversation_summary = "\n".join([f"{msg.type}: {msg.content}" for msg in messages[-5:]])
    
    members = ["Researcher", "Scrapper"]
    options = members + ["FINISH"]
    available_skills = _skill_registry.available_skills_prompt() if _skill_registry else "No registered skills."
    
    system_prompt = f"""You are the Supervisor Agent that coordinates specialized AI agents to answer user queries.
        
        YOUR ROLE:
        - Analyze user questions and determine which agent to use
        - Route tasks to the most appropriate specialized agent
        - Decide when enough information has been gathered to finish
        - For simple queries that don't require specialized knowledge, provide a direct response
        
        WHEN TO USE RESEARCHER:
        - User asks about facts, data, or general information
        - Questions about current events or trends
        - Need for background information on a topic
        - Queries requiring internet search
        
        WHEN TO USE SCRAPPER:
        - Need to extract specific information from websites
        - Researcher found relevant URLs that need deeper analysis
        - User mentioned specific websites to analyze
        
        REGISTERED SKILLS:
        {available_skills}

        WHEN TO USE REGISTERED SKILLS:
        - Registered skills are handled before this routing prompt when their metadata or trigger words match.
        - If a user asks for a skill that is not active, ask for the missing setup information or provide a direct response.

        WHEN TO FINISH:
        - Question is fully answered with sufficient detail
        - All necessary information has been gathered
        - User's needs are met with current information
        - Maximum iterations reached ({max_iterations})
        
        WHEN TO PROVIDE DIRECT RESPONSE:
        - User makes a simple statement that doesn't require research
        - User asks a basic question that doesn't need specialized tools
        - User provides information about themselves
        - User makes a greeting or farewell
        - User asks about your capabilities
        
        CONVERSATION CONTEXT:
        {conversation_summary}
        
        CURRENT STATUS:
        - Iterations completed: {iterations}/{max_iterations}
        - Available agents: {", ".join(members)}
        
        INSTRUCTIONS:
        - If insufficient information exists, choose the most suitable agent
        - If Researcher provided URLs/sources that need detailed analysis, use Scrapper
        - If general information is needed, use Researcher first
        - If the task matches a registered skill but the skill was not activated, ask for the missing setup information
        - Only FINISH when you have comprehensive information to answer the user
        - Provide clear reasoning for your decision
        - Consider the iteration count to avoid infinite loops
        - If you need more information from the user, have the agent ask a clear question
        - For simple queries, provide a direct response in the 'response' field
        """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        (
            "system",
            """Based on the conversation above, analyze what's needed and decide:

            1. Is the current information sufficient to fully answer the user's question?
            2. What additional information or verification is needed?
            3. Which agent should act next, or should we finish?
            4. For simple queries, can you provide a direct response without using specialized agents?

            Respond with your decision from: {options}
            The 'next' field must be exactly one of: Researcher, Scrapper, FINISH.
            Do not return translated labels, descriptive phrases, or custom route names.

            Provide reasoning for your choice and assess the task status.
            If this is a simple query that doesn't require specialized agents, include a direct response.""",
        ),
    ]).partial(options=str(options), members=", ".join(members))

    # llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=settings.OPENAI_API_KEY)
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
    )
    supervisor_chain = prompt | llm.with_structured_output(RouteResponse)
    result = await supervisor_chain.ainvoke(state)

    valid_routes = {"Researcher", "Scrapper", "FINISH"}
    next_route = result.next if result.next in valid_routes else None

    if next_route is None:
        logger.warning(
            "Supervisor returned unexpected route '%s'; falling back safely",
            result.next,
        )
        next_route = "FINISH" if result.response else "Researcher"

    if iterations >= max_iterations and next_route != "FINISH":
        logger.warning(f"Maximum iterations ({max_iterations}) reached, forcing finish")
        return {
            "next": "FINISH",
            "task_completed": True
        }

    logger.info(f"Supervisor decision (iteration {iterations}): {next_route} - {result.reasoning}")
    
    response_dict = {
        "next": next_route,
        "task_completed": next_route == "FINISH"
    }

    if result.response:
        logger.info(f"Supervisor provided direct response: {result.response[:50]}...")
        response_dict["direct_response"] = result.response
        response_dict["messages"] = messages + [AIMessage(content=result.response, name="Supervisor")]

    return response_dict


async def create_graph():
    """Create the multi-agent workflow graph."""
    global _skill_registry

    # llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=settings.OPENAI_API_KEY)
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
    )

    await _mcp_tools.setup_mcp_tools()

    researcher_system_message = SystemMessage(content="""You are a Research Specialist with access to web search tools.
        YOUR ROLE:
        - Conduct thorough internet research on any topic
        - Find current information, news, trends, and facts
        - Provide comprehensive background information
        - Search for multiple sources and perspectives
        - Retrieve real-time data like weather forecasts, stock prices, and news

        WHEN TO USE YOUR TOOLS:
        - User asks about current events, trends, or recent information
        - Need to find general information about topics
        - Looking for statistics, facts, or data
        - Researching background information
        - Finding multiple sources on a subject
        - Retrieving current weather information for specific locations
        - Searching for time-sensitive information

        RESPONSE FORMAT:
        - Provide detailed, well-researched information
        - Include sources and links when available
        - Mention if specific websites were found that might need detailed scraping
        - For weather queries: include temperature, conditions, and forecast when available
        
        IMPORTANT:
        - If you need more information from the user, ask clearly and wait for their response
        - Be specific about what information you need
        - For weather queries, always specify the location and time period (today, tomorrow, etc.)
        - ALWAYS use your web_search tool when asked about weather, current events, or factual information
        - Make multiple search queries if needed to get comprehensive information""")

    researcher_tools = filter_mcp_tools(_mcp_tools, "Researcher")
    researcher_agent = create_react_agent(
        llm,
        tools=researcher_tools.tools,
        prompt=researcher_system_message
    )
    
    async def research_node(state):
        return await agent_node(state, agent=researcher_agent, name="Researcher")

    scrapper_system_message = SystemMessage(content="""You are a Web Scraping Specialist with access to Firecrawl tools.
        YOUR ROLE:
        - Extract detailed content from websites
        - Scrape structured data from web pages
        - Analyze the content of specific URLs
        - Get full page content and details

        WHEN TO USE YOUR TOOLS:
        - Specific websites or URLs need detailed analysis
        - Need to extract structured data from pages
        - Researcher found relevant sources that need deeper investigation
        - User provided specific URLs to analyze
        - Need full content from particular pages
        
        IMPORTANT:
        - If you need more information from the user, ask clearly and wait for their response
        - Be specific about what information you need

        RESPONSE FORMAT:
        - Provide detailed extracted content
        - Structure the information clearly
        - Highlight key findings from the scraped data
        - Mention the source URL and extraction timestamp""")

    scrapper_tools = filter_mcp_tools(_mcp_tools, "Scrapper")
    scrapper_agent = create_react_agent(
        llm,
        tools=scrapper_tools.tools,
        prompt=scrapper_system_message
    )
    
    async def scrapper_node(state):
        return await agent_node(state, agent=scrapper_agent, name="Scrapper")

    skill_llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0.35,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
    )
    _skill_registry = create_default_skill_registry(skill_llm)

    async def skill_node(state: AgentState):
        try:
            if _skill_registry is None:
                raise RuntimeError("No skill registry has been initialized")

            skill_definition = _skill_registry.resolve(state)
            if skill_definition is None:
                raise RuntimeError("No registered skill matched the current request")

            result = await skill_definition.runner.run(state)
            return {
                "messages": [AIMessage(content=result.response, name=result.agent_name)],
                "iterations": state.get("iterations", 0) + 1,
                "evaluation": result.evaluation,
                "is_finished": result.is_finished,
                "task_completed": True,
                "active_skill": skill_definition.name,
            }
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error in SkillRunner node: {str(e)}\n{error_details}")
            return {
                "messages": [AIMessage(content=f"Skill 执行时出现问题：{str(e)}", name="SkillRunner")],
                "iterations": state.get("iterations", 0) + 1,
                "evaluation": None,
                "is_finished": False,
                "task_completed": True,
            }

    workflow = StateGraph(AgentState)

    workflow.add_node("Researcher", research_node)
    workflow.add_node("Scrapper", scrapper_node)
    workflow.add_node("SkillRunner", skill_node)
    workflow.add_node("Supervisor", supervisor_agent)

    members = ["Researcher", "Scrapper"]
    for member in members:
        workflow.add_edge(member, "Supervisor")
    workflow.add_edge("SkillRunner", END)

    conditional_map = {k: k for k in members}
    conditional_map["SkillRunner"] = "SkillRunner"
    conditional_map["FINISH"] = END
    workflow.add_conditional_edges("Supervisor", lambda x: x["next"], conditional_map)

    workflow.add_edge(START, "Supervisor")

    checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


def create_initial_state(messages: List[BaseMessage], max_iterations: int, **kwargs) -> AgentState:
    """Create an initial state for the workflow."""
    return {
        "messages": messages,
        "next": "",
        "task_completed": False,
        "iterations": 0,
        "max_iterations": max_iterations,
        "interview_mode": kwargs.get("interview_mode", False),
        "active_skill": kwargs.get("active_skill"),
        "previous_interviewer_question": kwargs.get("previous_interviewer_question"),
        "relevant_docs": kwargs.get("relevant_docs", []),
        "context": kwargs.get("context", ""),
        "interview_role": kwargs.get("interview_role"),
        "interview_level": kwargs.get("interview_level"),
        "interview_type": kwargs.get("interview_type"),
        "target_company": kwargs.get("target_company"),
        "jd_content": kwargs.get("jd_content"),
        "resume_content": kwargs.get("resume_content"),
        "evaluation": kwargs.get("evaluation"),
        "is_finished": kwargs.get("is_finished", False),
    }


async def initialize_graph():
    """Initialize the graph with MCP tools."""
    global _graph
    global _mcp_tools
    if _graph is None:
        _mcp_tools = MCPTools(mcp_configs=[
            MCPConfig(client_name="Researcher", server_url="http://127.0.0.1:7861/sse"),
            MCPConfig(client_name="Scrapper", server_url=f"http://127.0.0.1:7860/sse") # http://127.0.0.1:7860/sse or https://mcp.firecrawl.dev/{settings.FIRECRAWL_API_KEY}/sse
        ])
        _graph = await create_graph()
        logger.info("LangGraph with MCP tools initialized successfully")
    return _graph


async def close_graph():
    """Close the graph and clean up MCP connections."""
    global _mcp_tools
    if _mcp_tools is not None:
        await _mcp_tools.cleanup()
        logger.info("LangGraph with MCP tools closed successfully")


def get_graph():
    """Get the compiled graph instance."""
    if _graph is None:
        raise RuntimeError("Graph not initialized. Call initialize_graph() first.")
    return _graph


def filter_mcp_tools(
        mcp_tools: MCPTools,
        client_name: Literal["Researcher", "Scrapper"]
) -> MCPTools:
    """Filter MCP tools by client name."""
    filtered_configs = [
        config for config in mcp_tools.mcp_configs
        if config["client_name"] == client_name
    ]
    new_mcp_tools = MCPTools(mcp_configs=filtered_configs)
    new_mcp_tools.tools = [tool for tool in mcp_tools.tools if hasattr(tool, 'name')]
    return new_mcp_tools
