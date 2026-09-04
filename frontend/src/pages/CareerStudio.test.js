import { mergeKnowledgeDocument, pollMarkdownFactJob, prepareUploadedFactReview } from './CareerStudio';

const uploadedFact = (title, highlights) => ({
  fact_type: 'experience',
  title: '实习单位',
  content: {
    projects: [{
      title,
      highlights,
      tech_stack: ['C++', 'Python'],
      evidence_map: [{ claim: highlights[0], source_chunk_ids: ['source:test:1'] }],
    }],
  },
  source_file: { name: `${title}.md` },
  source_document: { project_metadata: { title } },
  quality: { extraction_source: 'resume-project-extractor' },
  client_draft_key: `draft-${title}`,
});

test('merges a deduplicated upload by document id instead of rendering a copy', () => {
  const original = [
    { id: 7, title: '旧标题' },
    { id: 8, title: '其他文档' },
  ];

  expect(mergeKnowledgeDocument(original, { id: 7, title: '已复用文档', deduplicated: true })).toEqual([
    { id: 7, title: '已复用文档', deduplicated: true },
    { id: 8, title: '其他文档' },
  ]);
});

test('fills the editor with the first Skill result and keeps remaining uploads pending', () => {
  const first = uploadedFact('路径记录项目', ['处理定位跳变。', '实现路径滑动窗口。']);
  const second = uploadedFact('标定平台', ['递归解析 DLT 日志。']);

  const review = prepareUploadedFactReview([first, second]);

  expect(review.editor.title).toBe('路径记录项目');
  expect(review.editor.projects[0].highlights).toBe('处理定位跳变。\n实现路径滑动窗口。');
  expect(review.editor.projects[0].evidence_map).toEqual(first.content.projects[0].evidence_map);
  expect(review.editor.source_file).toBe(first.source_file);
  expect(review.editor.quality.extraction_source).toBe('resume-project-extractor');
  expect(review.editor.client_draft_key).toBe('draft-路径记录项目');
  expect(review.draftFacts).toEqual([first, second]);
});

test('keeps polling queued and processing extraction jobs until a draft is ready', async () => {
  const responses = [
    { status: 'queued' },
    { status: 'processing' },
    { status: 'draft', facts: [uploadedFact('通用项目', ['完成接口验证。'])] },
  ];
  const getJob = jest.fn(async () => responses.shift());

  const result = await pollMarkdownFactJob({
    jobId: 'job-1',
    getJob,
    intervalMs: 0,
    timeoutMs: 1000,
    sleep: async () => {},
  });

  expect(result.status).toBe('draft');
  expect(getJob).toHaveBeenCalledTimes(3);
});
