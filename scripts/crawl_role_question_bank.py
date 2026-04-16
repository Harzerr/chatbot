import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from firecrawl import FirecrawlApp
from langchain_openai import ChatOpenAI
from tavily import TavilyClient

from app.core.config import settings
from app.services.role_question_bank_loader import ROLE_QUESTION_BANK_PATH, load_role_question_bank


ROLE_QUERY_TOPICS = {
    "Java后端工程师": [
        "项目面 Redis MySQL Spring 高并发",
        "八股 JVM 并发 事务",
        "场景题 秒杀 分布式 一致性",
        "系统设计 微服务 缓存 消息队列",
        "行为面 线上故障 性能优化 团队协作",
    ],
    "C++开发工程师": [
        "智能指针 多线程 网络编程",
        "项目面 性能优化 崩溃排查",
        "场景题 epoll 线程模型",
        "STL 对象模型 RAII 移动语义",
        "行为面 底层治理 工程优化",
    ],
    "测试工程师": [
        "接口测试 自动化 缺陷定位",
        "场景题 性能测试 发布质量",
        "行为面 质量推动",
        "测试设计 边界值 状态迁移",
        "测开 CI Mock 日志排查",
    ],
    "Web前端工程师": [
        "React JavaScript 浏览器 性能优化",
        "项目面 监控 工程化",
        "场景题 后台系统 架构设计",
        "TypeScript 状态管理 渲染机制",
        "行为面 协作 需求变化 技术债",
    ],
    "Python算法工程师": [
        "机器学习 深度学习 项目面",
        "场景题 数据不平衡 模型评估",
        "行为面 模型上线",
        "误差分析 特征工程 交叉验证",
        "PyTorch 训练 优化器 推理部署",
    ],
}

QUERY_SUFFIXES = [
    "牛客",
    "CSDN",
    "博客园",
    "掘金",
    "知乎",
    "面经",
    "真题",
    "总结",
    "高频题",
    "附答案",
]


EXTRACTION_PROMPT = """
你是一个严谨的技术面试题库构建助手。

任务：
1. 根据给定网页内容，提炼出适合目标岗位的真实面试题。
2. 输出结构化 JSON 数组。
3. 题目必须是岗位面试题，不要输出泛化知识摘要。
4. 不要照抄网页原文，不要长段复制；请基于内容进行提炼和重写。
5. 如果网页内容和目标岗位相关性弱，返回空数组。

每个元素格式如下：
{
  "role": "岗位名",
  "category": "技术面/项目面/场景题/行为面/系统设计/手撕代码/算法面 之一",
  "question": "面试题",
  "focus_points": ["考察点1", "考察点2"],
  "answer_framework": "参考回答方向，简洁具体"
}

要求：
- question 要像真实面试官提问
- focus_points 保持 3 到 6 个
- answer_framework 写成回答框架，不要展开成长答案全文
- 最多提取 10 题
- 如果网页主要是目录、广告、导航、无效内容，返回 []
- 只返回 JSON 数组
- 不要输出 markdown 代码块
- 不要输出解释文字
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl role interview questions and merge into role_question_bank.json")
    parser.add_argument("--roles", nargs="*", default=list(ROLE_QUERY_TOPICS.keys()), help="Roles to crawl")
    parser.add_argument("--max-results", type=int, default=4, help="Max Tavily search results per query")
    parser.add_argument("--max-pages-per-role", type=int, default=120, help="Max scraped pages per role")
    parser.add_argument("--min-items-per-role", type=int, default=500, help="Minimum newly crawled items per role target")
    parser.add_argument("--search-timeout", type=int, default=20, help="Timeout in seconds for Tavily search requests")
    parser.add_argument("--search-retries", type=int, default=3, help="Retry attempts for Tavily search")
    parser.add_argument("--search-depth", default="basic", choices=["basic", "advanced"], help="Tavily search depth")
    parser.add_argument("--model", default=settings.LLM_MODEL, help="LLM model for extracting structured questions")
    parser.add_argument("--replace", action="store_true", help="Replace existing JSON instead of merging")
    return parser.parse_args()


def build_role_queries(role: str) -> list[str]:
    queries: list[str] = []
    for topic in ROLE_QUERY_TOPICS.get(role, []):
        queries.append(f"{role} 面试题 {topic}")
        for suffix in QUERY_SUFFIXES:
            queries.append(f"{role} 面试题 {topic} {suffix}")
    return queries


def get_search_results(
    role: str,
    max_results: int,
    search_timeout: int,
    search_retries: int,
    search_depth: str,
) -> list[dict[str, Any]]:
    tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    deduped: list[dict[str, Any]] = []
    seen = set()

    for query in build_role_queries(role):
        print(f"[{role}] searching query: {query}", flush=True)
        response = None
        for attempt in range(1, search_retries + 1):
            try:
                response = tavily_client.search(
                    query=query,
                    max_results=max_results,
                    search_depth=search_depth,
                    timeout=search_timeout,
                )
                break
            except Exception as exc:
                print(
                    f"[{role}] search attempt {attempt}/{search_retries} failed: {query} -> {exc}",
                    flush=True,
                )
                if attempt < search_retries:
                    time.sleep(min(2 * attempt, 6))
        if response is None:
            print(f"[{role}] skip query after retries: {query}", flush=True)
            continue
        for item in response.get("results", []):
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(item)

    return deduped


def scrape_markdown(url: str) -> str:
    print(f"[scrape] start: {url}", flush=True)
    firecrawl = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
    result = firecrawl.scrape_url(url, formats=["markdown"])
    markdown = ""

    if isinstance(result, dict):
        markdown = result.get("markdown") or ""
    else:
        markdown = getattr(result, "markdown", "") or ""
        if not markdown and hasattr(result, "data"):
            data = getattr(result, "data") or {}
            markdown = data.get("markdown") or ""

    trimmed = markdown[:50000]
    print(f"[scrape] done: {url} (chars={len(trimmed)})", flush=True)
    return trimmed


def split_markdown_into_chunks(markdown: str, chunk_size: int = 12000, overlap: int = 1200) -> list[str]:
    normalized = markdown.strip()
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(normalized)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = normalized[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= text_length:
            break
        start = max(end - overlap, start + 1)

    return chunks


def parse_json_array(content: str) -> list[dict[str, Any]] | None:
    normalized = content.strip()

    try:
        data = json.loads(normalized)
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        pass

    unfenced = re.sub(r"^```json\s*", "", normalized, flags=re.IGNORECASE)
    unfenced = re.sub(r"^```\s*", "", unfenced)
    unfenced = re.sub(r"\s*```$", "", unfenced)

    try:
        data = json.loads(unfenced)
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", unfenced)
    if match:
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, list) else None
        except json.JSONDecodeError:
            return None

    return None


def extract_questions(
    llm: ChatOpenAI,
    role: str,
    source_name: str,
    source_url: str,
    markdown: str,
) -> list[dict[str, Any]]:
    if not markdown.strip():
        print(f"[extract] skip empty markdown: {source_url}", flush=True)
        return []

    chunks = split_markdown_into_chunks(markdown)
    print(f"[extract] start: {source_url} (chunks={len(chunks)})", flush=True)

    all_normalized: list[dict[str, Any]] = []
    seen_questions = set()

    for index, chunk in enumerate(chunks, start=1):
        prompt = f"""
目标岗位：{role}
来源名称：{source_name}
来源链接：{source_url}
当前分块：{index}/{len(chunks)}

网页内容：
{chunk}
"""
        print(f"[extract] chunk {index}/{len(chunks)} start: {source_url}", flush=True)
        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response = llm.invoke(messages)

        content = response.content if hasattr(response, "content") else str(response)
        print(f"[extract] chunk {index} raw output preview: {content[:500]}", flush=True)
        data = parse_json_array(content)

        if data is None:
            retry_messages = [
                {
                    "role": "system",
                    "content": EXTRACTION_PROMPT + "\n再次强调：只返回合法 JSON 数组本体，不要加任何解释和 markdown。",
                },
                {"role": "user", "content": prompt},
            ]
            retry_response = llm.invoke(retry_messages)
            retry_content = retry_response.content if hasattr(retry_response, "content") else str(retry_response)
            print(f"[extract] chunk {index} retry raw output preview: {retry_content[:500]}", flush=True)
            data = parse_json_array(retry_content)

        if data is None:
            print(f"[extract] chunk {index} invalid json: {source_url}", flush=True)
            continue

        chunk_count = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            question = (item.get("question") or "").strip()
            category = (item.get("category") or "技术面").strip()
            focus_points = [str(point).strip() for point in item.get("focus_points", []) if str(point).strip()]
            answer_framework = (item.get("answer_framework") or "").strip()
            question_key = (role, category, question)
            if not question or len(question) < 8 or question_key in seen_questions:
                continue
            seen_questions.add(question_key)
            all_normalized.append(
                {
                    "role": role,
                    "category": category,
                    "question": question,
                    "focus_points": focus_points[:6],
                    "answer_framework": answer_framework,
                    "source": "web_crawled",
                    "source_name": source_name,
                    "source_url": source_url,
                }
            )
            chunk_count += 1

        print(f"[extract] chunk {index}/{len(chunks)} done: {source_url} (+{chunk_count})", flush=True)

    print(f"[extract] done: {source_url} (+{len(all_normalized)})", flush=True)
    return all_normalized


def merge_records(existing: list[dict[str, Any]], new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {(item.get("role"), item.get("category"), item.get("question")) for item in merged}

    for item in new_records:
        key = (item.get("role"), item.get("category"), item.get("question"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


def print_latest_samples_by_role(records: list[dict[str, Any]], roles: list[str]) -> None:
    print("\n=== Latest Unique Sample Per Role ===")
    for role in roles:
        sample = next((item for item in reversed(records) if item.get("role") == role), None)
        if not sample:
            print(f"[{role}] no new unique records")
            continue
        print(f"[{role}] {sample.get('category')} | {sample.get('question')}")
        print(f"  focus: {'、'.join(sample.get('focus_points', []))}")
        print(f"  answer: {sample.get('answer_framework', '')}")
        print(f"  source: {sample.get('source_url', '')}")


def main() -> None:
    args = parse_args()
    print("[main] crawler start", flush=True)
    print(f"[main] roles={args.roles}", flush=True)
    print(
        f"[main] max_results={args.max_results}, max_pages_per_role={args.max_pages_per_role}, min_items_per_role={args.min_items_per_role}",
        flush=True,
    )
    print(
        f"[main] search_timeout={args.search_timeout}, search_retries={args.search_retries}, search_depth={args.search_depth}",
        flush=True,
    )
    print(f"[main] model={args.model}", flush=True)
    llm = ChatOpenAI(
        model=args.model,
        temperature=0,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
    )
    print("[main] llm client ready", flush=True)

    existing = [] if args.replace else load_role_question_bank()
    print(f"[main] existing records={len(existing)}", flush=True)
    crawled_records: list[dict[str, Any]] = []

    existing_keys = {(item.get("role"), item.get("category"), item.get("question")) for item in existing}
    newly_added_by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in args.roles}

    for role in args.roles:
        print(f"[{role}] role start", flush=True)
        pages_collected = 0
        search_results = get_search_results(
            role,
            args.max_results,
            args.search_timeout,
            args.search_retries,
            args.search_depth,
        )
        print(f"[{role}] search results: {len(search_results)}", flush=True)

        for item in search_results:
            if pages_collected >= args.max_pages_per_role:
                break
            if len(newly_added_by_role[role]) >= args.min_items_per_role:
                break

            source_url = item.get("url") or ""
            source_name = item.get("title") or source_url
            try:
                markdown = scrape_markdown(source_url)
                extracted = extract_questions(llm, role, source_name, source_url, markdown)
            except Exception as exc:
                print(f"[{role}] failed: {source_url} -> {exc}", flush=True)
                continue

            if not extracted:
                continue

            unique_extracted = []
            for record in extracted:
                key = (record.get("role"), record.get("category"), record.get("question"))
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                unique_extracted.append(record)

            if not unique_extracted:
                continue

            crawled_records.extend(unique_extracted)
            newly_added_by_role[role].extend(unique_extracted)
            pages_collected += 1
            print(
                f"[{role}] +{len(unique_extracted)} unique questions from {source_url} "
                f"(current new total: {len(newly_added_by_role[role])})",
                flush=True,
            )

    merged = merge_records(existing, crawled_records)
    ROLE_QUESTION_BANK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROLE_QUESTION_BANK_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"existing: {len(existing)}", flush=True)
    print(f"crawled: {len(crawled_records)}", flush=True)
    print(f"final: {len(merged)}", flush=True)
    print(f"output: {ROLE_QUESTION_BANK_PATH}", flush=True)
    for role in args.roles:
        print(f"{role}: newly added {len(newly_added_by_role[role])}", flush=True)
    print_latest_samples_by_role(crawled_records, args.roles)


if __name__ == "__main__":
    main()
