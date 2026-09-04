import asyncio
import hashlib
import time
from time import perf_counter
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
from app.services.conversation_context import render_history_context, select_history_context
from app.services.conversation_summary import get_conversation_summary
from app.services.vector_store import MultiTenantVectorStore
from app.utils.logger import setup_logger
from app.services.metrics import record_ai_metric
from app.services.llm_usage import extract_token_usage
from app.services.career_knowledge import evidence_context_stats
from app.services.task_queue import (
    QueueUnavailable,
    enqueue_conversation_summary_job,
    enqueue_evaluation_job,
)
from app.services.stream_context import StreamCallback, current_stream_callback

logger = setup_logger(__name__)


def _tenant_user_scope(tenant_id: str, user_id: str) -> str:
    """Stable, opaque namespace for all durable AI memory operations."""
    tenant_digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    return f"tenant-{tenant_digest}:user-{user_id}"


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
        if getattr(self, "_initialized", False):
            return

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
            #         "model": "deepseek/deepseek-v4-flash",
            #         "temperature": 0.1,
            #         "max_tokens": 2000,
            #         "api_key": settings.OPENAI_API_KEY
            #     }
            # },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": settings.MEMORY_LLM_MODEL,
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
        self.__persistence_tasks: set[asyncio.Task] = set()
        self._initialized = True

    def __build_conversation_history_messages(self, history_context_docs: list[dict]) -> list:
        history_messages = []

        for doc in history_context_docs:
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
        code_execution: dict | None = None,
        knowledge_context: str | None = None,
        evidence_pack: dict | None = None,
        knowledge_context_cache_hit: bool = False,
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
        started_at = perf_counter()

        memory_scope = _tenant_user_scope(tenant_id, user_id)
        memory_started_at = perf_counter()
        memories, relevant_docs, conversation_summary = await asyncio.gather(
            self.__search_memory(question, memory_scope=memory_scope),
            asyncio.to_thread(
                self.__vector_store.get_chat_by_id,
                chat_id=chat_id,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
            asyncio.to_thread(get_conversation_summary, tenant_id, user_id, chat_id),
        )
        logger.info("Interview memory search completed in %.0fms", (perf_counter() - memory_started_at) * 1000)

        history_started_at = perf_counter()
        semantic_history_docs = []
        if len(relevant_docs) > settings.INTERVIEW_HISTORY_RECENT_TURNS:
            try:
                semantic_history_docs = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.__vector_store.search_chat_by_id,
                        query=question,
                        chat_id=chat_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        limit=settings.INTERVIEW_HISTORY_RELEVANT_TURNS,
                    ),
                    timeout=settings.INTERVIEW_HISTORY_SEARCH_TIMEOUT,
                )
            except Exception as history_error:
                logger.warning("Semantic chat-history search failed; using recent turns only: %s", history_error)

        summary_content = str((conversation_summary or {}).get("content") or "").strip()
        summary_evidence_docs = semantic_history_docs
        history_relevant_turns = settings.INTERVIEW_HISTORY_RELEVANT_TURNS
        if summary_content:
            # The summary covers older turns; retain only a small number of raw
            # evidence turns so the model can verify important details.
            summary_evidence_docs = semantic_history_docs[: settings.CONVERSATION_SUMMARY_EVIDENCE_TURNS]
            history_relevant_turns = settings.CONVERSATION_SUMMARY_EVIDENCE_TURNS

        history_context_docs = select_history_context(
            relevant_docs,
            summary_evidence_docs,
            recent_turns=(
                settings.CONVERSATION_SUMMARY_RECENT_TURNS
                if summary_content
                else settings.INTERVIEW_HISTORY_RECENT_TURNS
            ),
            relevant_turns=history_relevant_turns,
            max_chars=settings.INTERVIEW_HISTORY_CONTEXT_MAX_CHARS,
        )

        logger.info(
            "Interview chat-history context built in %.0fms: stored=%s semantic=%s selected=%s",
            (perf_counter() - history_started_at) * 1000,
            len(relevant_docs),
            len(semantic_history_docs),
            len(history_context_docs),
        )
        retrieval_count = len(relevant_docs)
        logger.info("Retrieved %s scoped chat-history records for chat_id=%s", len(relevant_docs), chat_id)
        previous_interviewer_question = relevant_docs[-1].get("assistant_message") if relevant_docs else None
        context = "Relevant information from previous conversations:\n"
        if memories['results']:
            for memory in memories['results']:
                context += f" - {memory['memory']}\n"

        if summary_content:
            context += "\nRolling conversation summary:\n"
            context += summary_content
        
        rendered_history = render_history_context(history_context_docs)
        if rendered_history:
            context += "\nRelevant chat history:\n"
            context += rendered_history


        thread_id = f"{memory_scope}:chat-{chat_id}"

        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": memory_scope,
                "tenant_id": tenant_id,
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
        response_message = None
        evaluation: AnswerEvaluation | None = None
        evaluation_request: dict | None = None
        model_usage: dict | None = None
        answer_counted = False
        workflow_state: dict = {}
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
                history_context_docs=history_context_docs,
                context=context,
                interview_role=interview_role,
                interview_level=interview_level,
                interview_type=interview_type,
                target_company=target_company,
                jd_content=jd_content,
                resume_content=resume_content,
                code_execution=code_execution,
                knowledge_context=knowledge_context,
                evidence_pack=evidence_pack,
                knowledge_context_cache_hit=knowledge_context_cache_hit,
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                chat_id=str(chat_id),
            )
            graph_started_at = perf_counter()
            response_state = await self.__graph.ainvoke(initial_state, config=config)
            logger.info("Interview graph completed in %.0fms", (perf_counter() - graph_started_at) * 1000)

            if "messages" in response_state and response_state["messages"]:
                for msg in reversed(response_state["messages"]):
                    if isinstance(msg, AIMessage) and getattr(msg, "content", ""):
                        response_content = msg.content
                        response_message = msg
                        logger.info("Using skill response from %s", getattr(msg, "name", "AIMessage"))
                        break

            if response_state.get("evaluation"):
                evaluation = AnswerEvaluation.model_validate(response_state["evaluation"])
            evaluation_request = response_state.get("evaluation_request")
            model_usage = response_state.get("model_usage")
            answer_counted = bool(response_state.get("answer_counted", False))
            workflow_state = {
                "phase": response_state.get("interview_phase"),
                "question_mode": response_state.get("question_mode"),
                "follow_up_count": int(response_state.get("follow_up_count") or 0),
                "max_follow_ups": int(response_state.get("max_follow_ups") or 0),
                "question_grounded": bool(response_state.get("question_grounded", False)),
                "question_grounding_version": response_state.get("question_grounding_version"),
                "question_evidence_ids": list(response_state.get("question_evidence_ids") or []),
                "question_evidence_items": list(response_state.get("question_evidence_items") or []),
            }
        else:
            history_messages = self.__build_conversation_history_messages(history_context_docs)
            messages = [
                SystemMessage(content=f"""You are a helpful AI assistant.

                    CONTEXT AWARENESS:
                    {context}

                    Use the above context (if provided) to personalize your responses based on the user's previous interactions and preferences, but don't explicitly reference that you're using this context.
                """),
                *history_messages,
                HumanMessage(content=question)
            ]

            initial_state = create_initial_state(
                messages,
                max_iterations=1,
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                chat_id=str(chat_id),
            )
            response_state = await self.__graph.ainvoke(initial_state, config=config)

            if "direct_response" in response_state:
                response_content = response_state["direct_response"]
                logger.info("Using direct response from supervisor")
            elif "messages" in response_state and response_state["messages"]:
                for msg in reversed(response_state["messages"]):
                    if isinstance(msg, AIMessage) and getattr(msg, "content", ""):
                        response_content = msg.content
                        response_message = msg
                        logger.info(f"Using agent response from {msg.name}")
                        break

        final_response = response_content

        usage = model_usage or extract_token_usage(response_message)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
        estimated_cost = (prompt_tokens * settings.LLM_INPUT_USD_PER_1M + completion_tokens * settings.LLM_OUTPUT_USD_PER_1M) / 1_000_000
        evidence_stats = evidence_context_stats(knowledge_context)
        await record_ai_metric(
            user_id=int(user_id),
            tenant_id=tenant_id,
            operation="interview_question" if use_interview_mode else "chat",
            model=settings.INTERVIEW_LLM_MODEL if use_interview_mode else settings.LLM_MODEL,
            success=1,
            latency_ms=(perf_counter() - started_at) * 1000,
            model_latency_ms=float(usage.get("model_latency_ms") or 0),
            retrieval_count=retrieval_count,
            evidence_retrieval_count=evidence_stats["retrieval_count"],
            evidence_context_chars=evidence_stats["context_chars"],
            evidence_cache_hit=int(knowledge_context_cache_hit),
            evidence_retrieval_method=evidence_stats["retrieval_method"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
        )

        # Do not emit SSE [DONE] until the recoverable chat payload is durable.
        # Optional Mem0 and embedding enrichment continue in the background.
        persistence_task = asyncio.create_task(self.__persist_turn(
            question=question,
            answer=final_response,
            memory_scope=memory_scope,
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            active_skill=active_skill,
            interview_role=interview_role,
            interview_level=interview_level,
            interview_type=interview_type,
            target_company=target_company,
            jd_content=jd_content,
            resume_content=resume_content,
            code_execution=code_execution,
            knowledge_context=knowledge_context,
            evidence_pack=evidence_pack,
            knowledge_context_cache_hit=knowledge_context_cache_hit,
            evaluation=evaluation,
            evaluation_request=evaluation_request,
            answer_counted=answer_counted,
            workflow_state=workflow_state,
            history_turn_count=len(relevant_docs) + 1,
        ))
        self.__persistence_tasks.add(persistence_task)
        persistence_task.add_done_callback(self.__persistence_tasks.discard)
        # Keep the write alive if the browser refreshes after receiving the
        # answer but before the SSE connection emits its final marker.
        await asyncio.shield(persistence_task)

        return {"messages": [final_response]}

    async def ask_stream(self, *, on_chunk: StreamCallback, **kwargs) -> dict:
        callback_token = current_stream_callback.set(on_chunk)
        try:
            return await self.ask(**kwargs)
        finally:
            current_stream_callback.reset(callback_token)

    async def __persist_turn(
        self,
        question: str,
        answer: str,
        memory_scope: str,
        tenant_id: str,
        user_id: str,
        chat_id: str,
        active_skill: str | None,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
        target_company: str | None,
        jd_content: str | None,
        resume_content: str | None,
        code_execution: dict | None,
        knowledge_context: str | None,
        evidence_pack: dict | None,
        knowledge_context_cache_hit: bool,
        evaluation: AnswerEvaluation | None,
        evaluation_request: dict | None,
        answer_counted: bool,
        workflow_state: dict,
        history_turn_count: int,
    ) -> None:
        async def persist_optional_memory() -> None:
            try:
                await self.__add_memory(
                    question,
                    answer,
                    memory_scope=memory_scope,
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                logger.warning("mem0 add failed in background: %s", exc)

        asyncio.create_task(persist_optional_memory())
        point_ids = await asyncio.to_thread(
            self.__vector_store.store_conversation,
            question=question,
            answer=answer,
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
                "code_execution": code_execution,
                "knowledge_context": knowledge_context,
                "evidence_pack": evidence_pack,
                "knowledge_context_cache_hit": knowledge_context_cache_hit,
                "evaluation": evaluation.model_dump() if evaluation else None,
                "evaluation_status": "completed" if evaluation else ("queued" if evaluation_request else None),
                "answer_counted": answer_counted,
                "interview_phase": workflow_state.get("phase"),
                "question_mode": workflow_state.get("question_mode"),
                "follow_up_count": workflow_state.get("follow_up_count", 0),
                "max_follow_ups": workflow_state.get("max_follow_ups", 0),
                "question_grounded": bool(workflow_state.get("question_grounded", False)),
                "question_grounding_version": workflow_state.get("question_grounding_version"),
                "question_evidence_ids": workflow_state.get("question_evidence_ids", []),
                "question_evidence_items": workflow_state.get("question_evidence_items", []),
            },
        )
        if not point_ids:
            raise RuntimeError("Conversation persistence returned no Qdrant point ID")

        async def enrich_embedding() -> None:
            try:
                await asyncio.to_thread(
                    self.__vector_store.enrich_conversation_embedding,
                    str(point_ids[0]),
                    f"User: {question}\nAssistant: {answer}",
                )
            except Exception as exc:
                logger.warning(
                    "Conversation embedding enrichment failed; durable history remains available: chat_id=%s point_id=%s error=%s",
                    chat_id,
                    point_ids[0],
                    exc,
                )

        asyncio.create_task(enrich_embedding())

        if evaluation_request:
            job_payload = {
                "point_id": str(point_ids[0]),
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "chat_id": str(chat_id),
                "request": evaluation_request,
                "queued_at": time.time(),
            }
            try:
                job = await asyncio.to_thread(enqueue_evaluation_job, job_payload)
                await asyncio.to_thread(
                    self.__vector_store.set_conversation_evaluation_job_id,
                    point_id=str(point_ids[0]),
                    tenant_id=str(tenant_id),
                    user_id=str(user_id),
                    chat_id=str(chat_id),
                    job_id=job.id,
                )
                logger.info("Interview evaluation queued: chat_id=%s job_id=%s", chat_id, job.id)
            except QueueUnavailable as exc:
                logger.warning("Interview evaluation queue unavailable: chat_id=%s error=%s", chat_id, exc)
                await asyncio.to_thread(
                    self.__vector_store.update_conversation_evaluation,
                    point_id=str(point_ids[0]),
                    tenant_id=str(tenant_id),
                    user_id=str(user_id),
                    chat_id=str(chat_id),
                    status="failed",
                    error_message=str(exc),
                )

        summary_trigger = settings.CONVERSATION_SUMMARY_TRIGGER_TURNS
        summary_batch = max(1, settings.CONVERSATION_SUMMARY_BATCH_TURNS)
        should_enqueue_summary = (
            history_turn_count >= summary_trigger
            and (history_turn_count - summary_trigger) % summary_batch == 0
        )
        if should_enqueue_summary:
            try:
                job = await asyncio.to_thread(
                    enqueue_conversation_summary_job,
                    {
                        "tenant_id": str(tenant_id),
                        "user_id": str(user_id),
                        "chat_id": str(chat_id),
                    },
                )
                logger.info("Conversation summary queued: chat_id=%s job_id=%s", chat_id, job.id)
            except QueueUnavailable as exc:
                logger.warning("Conversation summary queue unavailable: chat_id=%s error=%s", chat_id, exc)

    async def __add_memory(self, question, response, memory_scope: str, tenant_id: str):
        payload = f"User: {question}\nAssistant: {response}"
        retries = max(0, settings.MEM0_ADD_RETRIES)
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self.__memory.add,
                        payload,
                        user_id=memory_scope,
                        metadata={"app_id": self.__app_id, "tenant_id": tenant_id},
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

    async def __search_memory(self, query, memory_scope: str):
        try:
            related_memories = await asyncio.wait_for(
                asyncio.to_thread(
                    self.__memory.search,
                    query,
                    user_id=memory_scope,
                ),
                timeout=settings.MEM0_SEARCH_TIMEOUT,
            )
            return related_memories
        except Exception as memory_error:
            logger.warning("mem0 search failed, continuing with empty memories: %s", memory_error)
            return {"results": []}
