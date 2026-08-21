import { prepareUploadedFactReview } from './CareerStudio';

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
