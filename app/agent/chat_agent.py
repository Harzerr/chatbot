import asyncio
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from mem0 import Memory
from qdrant_client import QdrantClient

from app.agent.langgraph_agent import get_graph, create_initial_state
from app.core.config import settings
from app.schemas.chat import AnswerEvaluation
from app.services.embedding_provider import get_mem0_embedder_config
from app.services.vector_store import MultiTenantVectorStore
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class AISupport:
    _instance = None

    def __new__(cls, vector_store: MultiTenantVectorStore):
        if cls._instance is None:
            cls._instance = super(AISupport, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, vector_store: MultiTenantVectorStore):
        """
        Initialize the AI Support with Memory Configuration and Langchain OpenAI Chat Model.
        """
        if not hasattr(self, '_initialized') or not self._initialized:
            self._initialized = True

        custom_prompt = """
                Please extract relevant entities containing user information, preferences, context, and important facts that would help personalize future interactions. 
                Here are some few shot examples:

                Input: Hi.
                Output: {{"facts" : []}}

                Input: The weather is nice today.
                Output: {{"facts" : []}}

                Input: I'm a software developer working on Python projects and I prefer using FastAPI.
                Output: {{"facts" : ["User is a software developer", "Works with Python", "Prefers FastAPI framework"]}}

                Input: My name is John Smith, I live in New York and I'm interested in machine learning.
                Output: {{"facts" : ["User name: John Smith", "Lives in New York", "Interested in machine learning"]}}

                Input: I usually work late hours and prefer getting notifications in the evening.
                Output: {{"facts" : ["Works late hours", "Prefers evening notifications"]}}

                Input: I have experience with React and Node.js, but I'm new to TypeScript.
                Output: {{"facts" : ["Experienced with React", "Experienced with Node.js", "New to TypeScript"]}}

                Input: I'm planning a trip to Japan next month and need help with travel recommendations.
                Output: {{"facts" : ["Planning trip to Japan", "Trip scheduled for next month", "Needs travel recommendations"]}}

                Input: I'm a vegetarian and I'm allergic to nuts.
                Output: {{"facts" : ["User is vegetarian", "Allergic to nuts"]}}

                Input: I prefer dark mode interfaces and I use VS Code as my main editor.
                Output: {{"facts" : ["Prefers dark mode interfaces", "Uses VS Code editor"]}}

                Return the facts and user information in a json format as shown above.
                """

        client = QdrantClient(
            settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=settings.QDRANT_TIMEOUT,
        )

        config = {
            # "llm": {
            #     "provider": "openai",
            #     "config": {
            #         "model": "gpt-4.1-mini",
            #         "temperature": 0.1,
            #         "max_tokens": 2000,
            #         "api_key": settings.OPENAI_API_KEY
            #     }
            # },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": settings.LLM_MODEL,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "api_key": settings.OPENROUTER_API_KEY,
                    "openai_base_url": settings.OPENROUTER_API_BASE,
                }
            },
            # "embedder": {
            #     "provider": "ollama",
            #     "config": {
            #         "model": "nomic-embed-text:latest",
            #         "ollama_base_url": "http://localhost:11434"
            #     }
            # },
            "embedder": get_mem0_embedder_config(),
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "general_chat_history",
                    "embedding_model_dims": 768,
                    "client": client
                }
            },
            "custom_prompt": custom_prompt,
            "version": "v1.1",
        }

        self.__memory = Memory.from_config(config)
        self.__app_id = "AI-general-chatbot"
        self.__vector_store = vector_store
        self.__graph: CompiledStateGraph = get_graph()

    def __build_conversation_history_messages(self, relevant_docs: list[dict]) -> list:
        history_messages = []

        for doc in relevant_docs[-6:]:
            question_text = (doc.get("user_message") or "").strip()
            answer_text = (doc.get("assistant_message") or "").strip()

            if question_text:
                history_messages.append(HumanMessage(content=question_text))

            if answer_text:
                history_messages.append(AIMessage(content=answer_text, name="Interviewer"))

        return history_messages

    def __should_use_interview_mode(
        self,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
    ) -> bool:
        return any([interview_role, interview_level, interview_type])

    async def ask(
        self,
        question: str,
        user_id: str,
        chat_id: str,
        tenant_id: str,
        skill_name: str | None = None,
        interview_role: str | None = None,
        interview_level: str | None = None,
        interview_type: str | None = None,
        target_company: str | None = None,
        jd_content: str | None = None,
        resume_content: str | None = None,
    ) -> dict:
        """Process a user question and return an AI response.
        
        Args:
            question: The user's question
            user_id: User identifier for personalization
            chat_id: Chat session identifier
            tenant_id: Tenant identifier for multi-tenant isolation
            
        Returns:
            Dictionary containing the AI response messages
        """
        logger.info("Self ID: {}".format(id(self)))

        memories = await self.__search_memory(question, user_id=user_id)

        relevant_docs = self.__vector_store.get_chat_by_id(
            chat_id=chat_id, 
            user_id=user_id, 
            tenant_id=tenant_id
        )
        logger.info(f"Retrieved {relevant_docs}")
        previous_interviewer_question = relevant_docs[-1].get("assistant_message") if relevant_docs else None
        context = "Relevant information from previous conversations:\n"
        if memories['results']:
            for memory in memories['results']:
                context += f" - {memory['memory']}\n"
        
        if relevant_docs:
            context += "\nRelevant chat history:\n"
            for i, doc in enumerate(relevant_docs):
                question_text = doc.get("user_message", "")
                answer_text = doc.get("assistant_message", "")

                context += f" - User: {question_text}\n"
                context += f" - Assistant: {answer_text}\n"


        thread_id = f"user_{user_id}_chat_{chat_id}"

        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                "chat_id": chat_id
            }
        }
        use_interview_mode = self.__should_use_interview_mode(
            interview_role=interview_role,
            interview_level=interview_level,
            interview_type=interview_type,
        )
        active_skill = skill_name or ("interview-skills" if use_interview_mode else None)
        use_skill_mode = bool(active_skill)

        response_content = ""
        evaluation: AnswerEvaluation | None = None
        if use_skill_mode:
            logger.info("Using graph-dispatched skill mode skill=%s chat_id=%s", active_skill, chat_id)
            skill_messages = [
                HumanMessage(content=question)
            ]
            initial_state = create_initial_state(
                skill_messages,
                max_iterations=1,
                interview_mode=use_interview_mode,
                active_skill=active_skill,
                previous_interviewer_question=previous_interviewer_question,
                relevant_docs=relevant_docs,
                context=context,
                interview_role=interview_role,
                interview_level=interview_level,
                interview_type=interview_type,
                target_company=target_company,
                jd_content=jd_content,
                resume_content=resume_content,
            )
            response_state = await self.__graph.ainvoke(initial_state, config=config)

            if "messages" in response_state and response_state["messages"]:
                for msg in reversed(response_state["messages"]):
                    if isinstance(msg, AIMessage) and getattr(msg, "content", ""):
                        response_content = msg.content
                        logger.info("Using skill response from %s", getattr(msg, "name", "AIMessage"))
                        break

            if response_state.get("evaluation"):
                evaluation = AnswerEvaluation.model_validate(response_state["evaluation"])
        else:
            history_messages = self.__build_conversation_history_messages(relevant_docs)
            messages = [
                SystemMessage(content=f"""You are a helpful AI assistant.

                    CONTEXT AWARENESS:
                    {context}

                    Use the above context (if provided) to personalize your responses based on the user's previous interactions and preferences, but don't explicitly reference that you're using this context.
                """),
                *history_messages,
                HumanMessage(content=question)
            ]

            initial_state = create_initial_state(messages, max_iterations=1)
            response_state = await self.__graph.ainvoke(initial_state, config=config)

            if "direct_response" in response_state:
                response_content = response_state["direct_response"]
                logger.info("Using direct response from supervisor")
            elif "messages" in response_state and response_state["messages"]:
                for msg in reversed(response_state["messages"]):
                    if isinstance(msg, AIMessage) and getattr(msg, "content", ""):
                        response_content = msg.content
                        logger.info(f"Using agent response from {msg.name}")
                        break

        final_response = response_content

        try:
            await self.__add_memory(question, final_response, user_id=user_id)
        except Exception as memory_error:
            logger.warning("mem0 add failed, continuing without blocking response: %s", memory_error)

        try:
            self.__vector_store.store_conversation(
                question=question,
                answer=final_response,
                tenant_id=tenant_id,
                metadata={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "timestamp": str(datetime.now()),
                    "skill_name": active_skill,
                    "interview_role": interview_role,
                    "interview_level": interview_level,
                    "interview_type": interview_type,
                    "target_company": target_company,
                    "jd_content": jd_content,
                    "resume_content": resume_content,
                    "evaluation": evaluation.model_dump() if evaluation else None,
                }
            )
        except Exception as vector_store_error:
            logger.warning(
                "vector store write failed, continuing without blocking response: %s",
                vector_store_error,
            )

        return {"messages": [final_response]}

    async def __add_memory(self, question, response, user_id=None):
        payload = f"User: {question}\nAssistant: {response}"
        retries = max(0, settings.MEM0_ADD_RETRIES)
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self.__memory.add,
                        payload,
                        user_id=user_id,
                        metadata={"app_id": self.__app_id},
                    ),
                    timeout=settings.MEM0_ADD_TIMEOUT,
                )
                return
            except asyncio.TimeoutError as exc:
                last_error = TimeoutError(
                    f"mem0 add timed out after {settings.MEM0_ADD_TIMEOUT}s (attempt {attempt + 1}/{retries + 1})"
                )
                if attempt < retries:
                    logger.warning("%s, retrying once", last_error)
                    continue
            except Exception as exc:
                last_error = exc
                if attempt < retries and "timed out" in str(exc).lower():
                    logger.warning("mem0 add failed due to timeout-like error, retrying once: %s", exc)
                    continue
                break

        if last_error:
            raise last_error

    async def __search_memory(self, query, user_id=None):
        try:
            related_memories = await asyncio.wait_for(
                asyncio.to_thread(
                    self.__memory.search,
                    query,
                    user_id=user_id,
                ),
                timeout=settings.MEM0_SEARCH_TIMEOUT,
            )
            return related_memories
        except Exception as memory_error:
            logger.warning("mem0 search failed, continuing with empty memories: %s", memory_error)
            return {"results": []}
