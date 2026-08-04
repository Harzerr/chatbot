import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Slider,
  Stack,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import FormatItalicRoundedIcon from '@mui/icons-material/FormatItalicRounded';
import FormatListBulletedRoundedIcon from '@mui/icons-material/FormatListBulletedRounded';
import FormatBoldRoundedIcon from '@mui/icons-material/FormatBoldRounded';
import FormatColorTextRoundedIcon from '@mui/icons-material/FormatColorTextRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import TuneRoundedIcon from '@mui/icons-material/TuneRounded';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import careerService from '../services/careerService';
import { useAuth } from '../contexts/AuthContext';

const sectionLabels = {
  education: '教育背景',
  summary: '职业摘要',
  '实习经历': '实习经历',
  '项目经历': '项目经历',
  '专业技能': '专业技能',
  '竞赛与荣誉': '竞赛与荣誉',
};

const styleLabels = {
  summary: '职业摘要',
  education: '教育背景',
  '实习经历': '实习经历',
  '项目经历': '项目经历',
  '专业技能': '专业技能',
  '竞赛与荣誉': '竞赛与荣誉',
};

const defaultSectionStyle = { fontSize: 10, fontWeight: 400, color: '#17202a' };

const clampFontSize = (value, fallback = 10.5, minimum = 9.5, maximum = 16) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(minimum, Math.min(maximum, parsed)) : fallback;
};

const resumeFontFaceCss = `
@font-face { font-family: 'Resume Times'; src: url('/api/v1/fonts/times.ttf') format('truetype'); font-style: normal; font-weight: 400; font-display: swap; }
@font-face { font-family: 'Resume Times'; src: url('/api/v1/fonts/timesbd.ttf') format('truetype'); font-style: normal; font-weight: 700; font-display: swap; }
@font-face { font-family: 'Resume Times'; src: url('/api/v1/fonts/timesi.ttf') format('truetype'); font-style: italic; font-weight: 400; font-display: swap; }
@font-face { font-family: 'Resume SimSun'; src: url('/api/v1/fonts/simsun.ttc') format('truetype'); font-style: normal; font-weight: 400; font-display: swap; }
`;

const clone = (value) => JSON.parse(JSON.stringify(value || {}));

const normalizeContent = (resume, user) => {
  const content = clone(resume?.content);
  content.headline = content.headline || user?.target_role || '目标岗位';
  content.summary = content.summary || '';
  content.education = Array.isArray(content.education) ? content.education : (user?.education || []);
  content.sections = Array.isArray(content.sections) ? content.sections : [];
  return content;
};

const sectionKey = (heading) => heading || 'other';

const projectVisibilityKey = (sectionIndex, entry, entryIndex) => {
  const factIds = Array.isArray(entry?.fact_ids) ? entry.fact_ids.filter(Boolean).join('-') : '';
  const identity = factIds || [entry?.title, entry?.subtitle, entry?.period].filter(Boolean).join('|') || `index-${entryIndex}`;
  return `${sectionIndex}:${identity}`;
};

const updateSection = (content, index, updater) => {
  const next = clone(content);
  next.sections[index] = updater(next.sections[index]);
  return next;
};

const normalizeRichTextHtml = (value) => {
  const source = String(value || '');
  const container = document.createElement('div');
  const appendText = (parent, text) => {
    text.split('\n').forEach((line, index) => {
      if (index) parent.appendChild(document.createElement('br'));
      parent.appendChild(document.createTextNode(line));
    });
  };
  const copyNode = (node, parent) => {
    if (node.nodeType === Node.TEXT_NODE) {
      parent.appendChild(document.createTextNode(node.nodeValue || ''));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tagName = node.tagName.toLowerCase();
    if (tagName === 'br') {
      parent.appendChild(document.createElement('br'));
      return;
    }
    if (tagName === 'strong' || tagName === 'b') {
      const strong = document.createElement('strong');
      [...node.childNodes].forEach((child) => copyNode(child, strong));
      parent.appendChild(strong);
      return;
    }
    if (tagName === 'em' || tagName === 'i') {
      const italic = document.createElement('em');
      [...node.childNodes].forEach((child) => copyNode(child, italic));
      parent.appendChild(italic);
      return;
    }
    if (tagName === 'span' || tagName === 'font') {
      const color = tagName === 'font' ? node.getAttribute('color') : node.style.color;
      const isLabel = tagName === 'span' && node.getAttribute('data-resume-label') === 'true';
      if (isLabel || (color && /^(#?[0-9a-f]{3,8}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))$/i.test(color.trim()))) {
        const colored = document.createElement('span');
        if (isLabel) colored.setAttribute('data-resume-label', 'true');
        if (color) colored.style.color = color.startsWith('#') || color.startsWith('rgb') ? color : `#${color}`;
        [...node.childNodes].forEach((child) => copyNode(child, colored));
        parent.appendChild(colored);
        return;
      }
    }
    if (tagName === 'ul' || tagName === 'ol' || tagName === 'li') {
      const listNode = document.createElement(tagName);
      [...node.childNodes].forEach((child) => copyNode(child, listNode));
      parent.appendChild(listNode);
      return;
    }
    [...node.childNodes].forEach((child) => copyNode(child, parent));
  };
  if (/[<>]/.test(source)) {
    const template = document.createElement('template');
    template.innerHTML = source;
    [...template.content.childNodes].forEach((node) => copyNode(node, container));
  } else {
    appendText(container, source);
  }
  return container.innerHTML;
};

const composeLabeledEditorValue = (label, body, fallbackLabel) => {
  const labelValue = label || fallbackLabel;
  return `<span data-resume-label="true" style="color:#b21f35;font-weight:700">${normalizeRichTextHtml(labelValue)}</span>${body || ''}`;
};

const splitLabeledEditorValue = (value, fallbackLabel) => {
  const container = document.createElement('div');
  container.innerHTML = String(value || '');
  const labelNode = container.firstElementChild;
  if (labelNode?.getAttribute('data-resume-label') === 'true') {
    const label = labelNode.innerHTML || fallbackLabel;
    labelNode.remove();
    return { label, body: container.innerHTML };
  }
  return { label: fallbackLabel, body: container.innerHTML };
};

const editorValueForItem = (item) => {
  const label = String(item?.label || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  return label ? `<strong>${label}：</strong>${item?.text || ''}` : item?.text || '';
};

const RichTextEditor = ({ value, onChange, placeholder = '', activeEditorRef, activeSelectionRef, activeEditorChangeRef, onBackspaceAtStart, containerSx = {}, editorSx = {} }) => {
  const editorRef = useRef(null);
  const captureSelection = () => {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection?.rangeCount || !editor.contains(selection.anchorNode)) return;
    activeEditorRef.current = editor;
    activeSelectionRef.current = selection.getRangeAt(0).cloneRange();
    activeEditorChangeRef.current = onChange;
  };
  const handleKeyDown = (event) => {
    if (event.key !== 'Backspace' || !onBackspaceAtStart) return;
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection?.isCollapsed || !selection.rangeCount || !editor.contains(selection.anchorNode)) return;
    const prefixRange = document.createRange();
    prefixRange.selectNodeContents(editor);
    prefixRange.setEnd(selection.anchorNode, selection.anchorOffset);
    if (!prefixRange.toString()) {
      event.preventDefault();
      onBackspaceAtStart();
    }
  };
  useLayoutEffect(() => {
    if (editorRef.current && document.activeElement !== editorRef.current) {
      editorRef.current.innerHTML = normalizeRichTextHtml(value);
    }
  }, [value]);
  return (
    <Box sx={{ position: 'relative', flex: 1, minWidth: 0, ...containerSx }}>
      <Box
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        onFocus={captureSelection}
        onMouseUp={captureSelection}
        onKeyUp={captureSelection}
        onSelect={captureSelection}
        onKeyDown={handleKeyDown}
        onInput={(event) => onChange(event.currentTarget.innerHTML)}
        data-placeholder={placeholder}
        sx={{ minHeight: '1em', pr: 1, outline: 'none', fontSize: 'inherit', lineHeight: 'inherit', ...editorSx, '&:empty:before': { content: 'attr(data-placeholder)', color: '#94a3b8' }, '& ul, & ol': { m: 0, pl: 2 }, '& li': { m: 0, p: 0 } }}
      />
  </Box>
  );
};

const ResumeBulletMarker = ({ editable, onDelete }) => editable ? (
  <Tooltip title="删除此要点">
    <IconButton aria-label="删除此要点" size="small" onMouseDown={(event) => event.preventDefault()} onClick={onDelete} sx={{ flex: '0 0 12px', width: 12, height: '1em', p: 0, mt: 0.1, color: '#b21f35', fontSize: '0.85em' }}>•</IconButton>
  </Tooltip>
) : <Box component="span" sx={{ flex: '0 0 12px', pt: 0.1, color: '#b21f35', fontSize: '0.85em' }}>•</Box>;

const ResumePaper = ({ content, user, hiddenSections, hiddenProjects, sectionStyles, fontSize, sectionTitleSize, padding, onChange, onFormatSection, showEditTools, activeEditorRef, activeSelectionRef, activeEditorChangeRef }) => {
  const measureRef = useRef(null);
  const [pageGroups, setPageGroups] = useState([]);
  const [pageGroupSignature, setPageGroupSignature] = useState('');
  const getSectionStyle = (key) => {
    const style = { ...defaultSectionStyle, fontSize, ...(sectionStyles[key] || {}) };
    if (key === 'education') style.fontSize = fontSize;
    return { ...style, fontSize: clampFontSize(style.fontSize, fontSize) };
  };

  const updateEntry = (sectionIndex, entryIndex, field, value) => {
    onChange(updateSection(content, sectionIndex, (section) => {
      const next = { ...section, entries: [...(section.entries || [])] };
      next.entries[entryIndex] = { ...next.entries[entryIndex], [field]: value };
      return next;
    }));
  };

  const updateItem = (sectionIndex, itemIndex, value) => {
    onChange(updateSection(content, sectionIndex, (section) => {
      const next = { ...section, items: [...(section.items || [])] };
      next.items[itemIndex] = { ...next.items[itemIndex], text: value };
      return next;
    }));
  };

  const updateLabeledEntry = (sectionIndex, entryIndex, bodyField, labelField, fallbackLabel, value) => {
    const parsed = splitLabeledEditorValue(value, fallbackLabel);
    onChange(updateSection(content, sectionIndex, (section) => {
      const next = { ...section, entries: [...(section.entries || [])] };
      next.entries[entryIndex] = { ...next.entries[entryIndex], [bodyField]: parsed.body, [labelField]: parsed.label };
      return next;
    }));
  };

  const deleteEntry = (sectionIndex, entryIndex) => {
    onChange(updateSection(content, sectionIndex, (section) => ({
      ...section,
      entries: (section.entries || []).filter((_, index) => index !== entryIndex),
    })));
  };

  const deleteItem = (sectionIndex, itemIndex) => {
    onChange(updateSection(content, sectionIndex, (section) => ({
      ...section,
      items: (section.items || []).filter((_, index) => index !== itemIndex),
    })));
  };

  const isProjectHidden = (sectionIndex, entry, entryIndex) => Boolean(entry.hidden || hiddenProjects[projectVisibilityKey(sectionIndex, entry, entryIndex)]);

  const sectionHeading = (heading) => {
    const style = getSectionStyle(sectionKey(heading));
    return (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.7, color: style.color, width: '100%' }}>
        <Box sx={{ width: 3, height: 15, bgcolor: '#b21f35', flex: '0 0 auto' }} />
        <Typography sx={{ fontWeight: 800, fontSize: `${sectionTitleSize}pt`, color: 'inherit', letterSpacing: '0.02em' }}>
          {sectionLabels[heading] || heading || '其他经历'}
        </Typography>
        <Box sx={{ flex: 1, height: '1px', bgcolor: '#cbd5e1' }} />
      </Stack>
    );
  };

  const renderEntry = (sectionIndex, heading, entry, entryIndex) => {
    const style = getSectionStyle(sectionKey(heading));
    const isProject = heading === '项目经历';
    const techStackText = Array.isArray(entry.tech_stack) ? entry.tech_stack.join('、') : (entry.tech_stack || '');
    const summaryLabel = entry.summary_label || '项目简介：';
    const techStackLabel = entry.tech_stack_label || '技术栈：';
    return (
    <Box sx={{ mb: 0.65, p: 0, breakInside: 'avoid', pageBreakInside: 'avoid', fontSize: `${style.fontSize}pt`, fontWeight: style.fontWeight, color: style.color }}>
      <Stack direction="row" spacing={1.2} alignItems="baseline">
        <TextField
          variant="standard"
          value={entry.title || ''}
          onChange={(event) => updateEntry(sectionIndex, entryIndex, 'title', event.target.value)}
          sx={{ flex: 1, minWidth: 0, '& .MuiInputBase-root': { fontWeight: 700, fontSize: 'inherit', p: 0 } }}
        />
        <TextField
          variant="standard"
          value={entry.subtitle || ''}
          onChange={(event) => updateEntry(sectionIndex, entryIndex, 'subtitle', event.target.value)}
          placeholder="角色 / 职位"
          sx={{ width: 150, '& .MuiInputBase-root': { fontWeight: 600, fontSize: '0.94em', color: '#374151', p: 0 }, '& .MuiInputBase-input': { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', textAlign: 'center' } }}
        />
        <TextField
          variant="standard"
          value={entry.period || ''}
          onChange={(event) => updateEntry(sectionIndex, entryIndex, 'period', event.target.value)}
          sx={{ width: 125, '& .MuiInputBase-root': { fontSize: '0.92em', color: '#52606d', p: 0 }, '& .MuiInputBase-input': { whiteSpace: 'nowrap', textAlign: 'right' } }}
        />
        {showEditTools && <Tooltip title={style.fontWeight >= 700 ? '取消加粗' : '整段加粗'}>
          <IconButton size="small" onClick={() => onFormatSection(sectionKey(heading), 'fontWeight', style.fontWeight >= 700 ? 400 : 700)}><FormatBoldRoundedIcon fontSize="small" /></IconButton>
        </Tooltip>}
        {showEditTools && <Tooltip title="删除整段经历">
          <IconButton size="small" color="error" onClick={() => deleteEntry(sectionIndex, entryIndex)}><DeleteOutlineRoundedIcon fontSize="small" /></IconButton>
        </Tooltip>}
      </Stack>
      {(entry.summary || isProject) && (
        <Box sx={{ mt: 0.25, fontSize: '0.92em' }}><RichTextEditor value={composeLabeledEditorValue(summaryLabel, entry.summary, '项目简介：')} placeholder="点击输入项目简介" onChange={(value) => updateLabeledEntry(sectionIndex, entryIndex, 'summary', 'summary_label', '项目简介：', value)} activeEditorRef={activeEditorRef} activeSelectionRef={activeSelectionRef} activeEditorChangeRef={activeEditorChangeRef} /></Box>
      )}
      {(techStackText || isProject) && <Box sx={{ mt: 0.2, color: '#4b5563', fontSize: '0.92em' }}><RichTextEditor value={composeLabeledEditorValue(techStackLabel, techStackText, '技术栈：')} placeholder="点击输入技术栈" onChange={(value) => updateLabeledEntry(sectionIndex, entryIndex, 'tech_stack', 'tech_stack_label', '技术栈：', value)} activeEditorRef={activeEditorRef} activeSelectionRef={activeSelectionRef} activeEditorChangeRef={activeEditorChangeRef} /></Box>}
      {(entry.items || []).map((item, itemIndex) => (
        <Box key={`${sectionIndex}-${entryIndex}-${itemIndex}`} sx={{ position: 'relative', display: 'flex', alignItems: 'flex-start', width: '100%', mt: 0.2 }}>
          <ResumeBulletMarker editable={showEditTools} onDelete={() => deleteItem(sectionIndex, itemIndex)} />
          <RichTextEditor value={editorValueForItem(item)} onChange={(value) => updateEntry(sectionIndex, entryIndex, 'items', (entry.items || []).map((current, index) => index === itemIndex ? { ...current, label: '', text: value } : current))} onBackspaceAtStart={() => deleteItem(sectionIndex, itemIndex)} activeEditorRef={activeEditorRef} activeSelectionRef={activeSelectionRef} activeEditorChangeRef={activeEditorChangeRef} />
          {showEditTools && <Tooltip title="删除要点"><IconButton size="small" color="error" onClick={() => deleteItem(sectionIndex, itemIndex)} sx={{ position: 'absolute', right: -26, top: -4, p: 0.25 }}><DeleteOutlineRoundedIcon fontSize="small" /></IconButton></Tooltip>}
        </Box>
      ))}
    </Box>
    );
  };

  const blocks = [];
  blocks.push({
    key: 'header',
    node: (
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, borderLeft: '3px solid #b21f35', pl: 1.8, mb: 2.2 }}>
        <Avatar src={user?.avatar_url || undefined} alt="证件照" variant="square" sx={{ width: 76, height: 100, flex: '0 0 auto', bgcolor: '#fff', color: '#64748b', border: '1px solid #cbd5e1', boxShadow: 'none', borderRadius: 0, fontSize: 12 }}>证件照</Avatar>
        <Box sx={{ minWidth: 0, pt: 0.2 }}>
          <Typography sx={{ fontSize: `${Math.max(fontSize + 7, 17)}pt`, fontWeight: 800 }}>{user?.full_name || '姓名待确认'}</Typography>
          <Typography sx={{ color: '#b21f35', fontWeight: 700, mt: 0.25 }}>求职意向：{content.headline}</Typography>
          <Typography variant="body2" sx={{ color: '#52606d', mt: 1, lineHeight: 1 }}>{[
            user?.phone && `手机：${user.phone}`,
            user?.email && `邮箱：${user.email}`,
          ].filter(Boolean).join('    ') || '请在个人档案补充联系方式'}</Typography>
        </Box>
      </Box>
    ),
  });
  if (!hiddenSections.education && content.education?.length > 0) {
    const educationStyle = getSectionStyle('education');
    content.education.forEach((item, index) => blocks.push({
      key: `education-${index}`,
      node: <Box sx={{ mb: 0, p: 0, breakInside: 'avoid', pageBreakInside: 'avoid', fontSize: `${educationStyle.fontSize}pt`, fontWeight: educationStyle.fontWeight, color: educationStyle.color }}>{index === 0 && sectionHeading('education')}<Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}><Typography sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 'inherit', lineHeight: 'inherit', fontWeight: 'inherit' }}>{[item.school, item.major, item.degree].filter(Boolean).join(' · ') || item.title || '教育经历'}</Typography><Typography sx={{ flex: '0 0 auto', whiteSpace: 'nowrap', color: '#52606d', fontSize: 'inherit', lineHeight: 'inherit', fontWeight: 'inherit' }}>{[item.start_date, item.end_date].filter(Boolean).join(' - ')}</Typography></Box></Box>,
    }));
  }

  content.sections.forEach((section, sectionIndex) => {
    const key = sectionKey(section.heading);
    if (hiddenSections[key]) return;
    const visibleEntries = (section.entries || []).filter((entry, entryIndex) => key !== '项目经历' || !isProjectHidden(sectionIndex, entry, entryIndex));
    visibleEntries.forEach((entry) => {
      const entryIndex = (section.entries || []).indexOf(entry);
      const style = getSectionStyle(key);
      blocks.push({ key: `${key}-entry-${entryIndex}`, node: <Box sx={{ fontSize: `${style.fontSize}pt`, fontWeight: style.fontWeight, color: style.color }}>{entryIndex === (section.entries || []).indexOf(visibleEntries[0]) && sectionHeading(section.heading)}{renderEntry(sectionIndex, section.heading, entry, entryIndex)}</Box> });
    });
    (section.items || []).forEach((item, itemIndex) => blocks.push({
      key: `${key}-item-${itemIndex}`,
      node: (() => {
        const style = getSectionStyle(key);
        return <Box sx={{ breakInside: 'avoid', pageBreakInside: 'avoid', fontSize: `${style.fontSize}pt`, fontWeight: style.fontWeight, color: style.color }}>{itemIndex === 0 && visibleEntries.length === 0 && sectionHeading(section.heading)}<Box sx={{ position: 'relative', display: 'flex', alignItems: 'flex-start', width: '100%' }}><ResumeBulletMarker editable={showEditTools} onDelete={() => deleteItem(sectionIndex, itemIndex)} /><RichTextEditor value={item.text || item.label || ''} onChange={(value) => updateItem(sectionIndex, itemIndex, value)} onBackspaceAtStart={() => deleteItem(sectionIndex, itemIndex)} activeEditorRef={activeEditorRef} activeSelectionRef={activeSelectionRef} activeEditorChangeRef={activeEditorChangeRef} />{showEditTools && <Tooltip title="删除要点"><IconButton size="small" color="error" onClick={() => deleteItem(sectionIndex, itemIndex)} sx={{ position: 'absolute', right: -26, top: -4, p: 0.25 }}><DeleteOutlineRoundedIcon fontSize="small" /></IconButton></Tooltip>}</Box></Box>;
      })(),
    }));
  });
  const blockSignature = blocks.map((block) => block.key).join('|');
  useLayoutEffect(() => {
    if (!measureRef.current) return;
    const pageHeight = (297 - padding * 2) * (96 / 25.4);
    const measuredBlocks = [...measureRef.current.querySelectorAll('[data-resume-measure-block]')];
    const groups = [];
    let current = [];
    let usedHeight = 0;
    measuredBlocks.forEach((element, index) => {
      const height = element.getBoundingClientRect().height;
      if (current.length && usedHeight + height > pageHeight) {
        groups.push(current);
        current = [];
        usedHeight = 0;
      }
      current.push(index);
      usedHeight += height;
    });
    if (current.length) groups.push(current);
    setPageGroups(groups);
    setPageGroupSignature(blockSignature);
  }, [blockSignature, content, hiddenSections, hiddenProjects, sectionStyles, fontSize, padding, sectionTitleSize, showEditTools]);

  const pageGroupsAreCurrent = pageGroupSignature === blockSignature && pageGroups.every((group) => group.every((blockIndex) => blocks[blockIndex]));
  const groups = pageGroupsAreCurrent ? pageGroups : [blocks.map((_, index) => index)];
  const pageSx = {
    width: '210mm',
    minHeight: '297mm',
    maxWidth: '100%',
    bgcolor: '#fff',
    color: '#17202a',
    p: `${padding}mm`,
    fontSize: `${fontSize}pt`,
    lineHeight: 1,
    overflowWrap: 'anywhere',
    fontFamily: '"Resume Times", "Times New Roman", "Resume SimSun", SimSun, "Songti SC", serif',
    boxSizing: 'border-box',
    '& .MuiInput-underline:before, & .MuiInput-underline:after': { display: 'none' },
    '& .MuiInputBase-input': { lineHeight: 1 },
  };

  return (
    <Box>
      <Typography variant="caption" sx={{ display: 'block', color: '#64748b', mb: 1 }}>A4 分页预览 · 每页 210 × 297 mm · 共 {groups.length} 页</Typography>
      <Box ref={measureRef} sx={{ position: 'absolute', left: '-100000px', top: 0, visibility: 'hidden', pointerEvents: 'none', width: '210mm', ...pageSx, height: 'auto' }}>
        {blocks.map((block) => <Box key={`measure-${block.key}`} data-resume-measure-block>{block.node}</Box>)}
      </Box>
      {groups.map((group, pageIndex) => (
        <Box key={`page-${pageIndex}`} sx={{ ...pageSx, mb: pageIndex < groups.length - 1 ? 1 : 0, boxShadow: '0 16px 40px rgba(15, 23, 42, 0.14)' }}>
          {group.map((blockIndex) => <React.Fragment key={blocks[blockIndex].key}>{blocks[blockIndex].node}</React.Fragment>)}
        </Box>
      ))}
    </Box>
  );
};

const ResumeOptimizer = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentUser, uploadAvatar, deleteAvatar } = useAuth();
  const [resumes, setResumes] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [content, setContent] = useState(null);
  const [title, setTitle] = useState('');
  const [hiddenSections, setHiddenSections] = useState({});
  const [hiddenProjects, setHiddenProjects] = useState({});
  const [sectionStyles, setSectionStyles] = useState({});
  const [styleTarget, setStyleTarget] = useState('education');
  const [visibilityTarget, setVisibilityTarget] = useState('education');
  const [fontSize, setFontSize] = useState(10);
  const [sectionTitleSize, setSectionTitleSize] = useState(12);
  const [showEditTools, setShowEditTools] = useState(false);
  const activeEditorRef = useRef(null);
  const activeSelectionRef = useRef(null);
  const activeEditorChangeRef = useRef(null);
  const [padding, setPadding] = useState(15);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [avatarWorking, setAvatarWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await careerService.listResumes();
      setResumes(data);
      const requestedId = searchParams.get('resumeId');
      setSelectedId((current) => current || requestedId || (data[0] ? String(data[0].id) : ''));
    } catch (err) {
      setError(err.response?.data?.detail || '加载简历版本失败。');
    } finally {
      setLoading(false);
    }
  }, [searchParams]);

  useEffect(() => { load(); }, [load]);

  const selectedResume = useMemo(() => resumes.find((item) => String(item.id) === String(selectedId)), [resumes, selectedId]);

  useEffect(() => {
    if (!selectedResume) {
      setContent(null);
      return;
    }
    const nextContent = normalizeContent(selectedResume, currentUser);
    setContent(nextContent);
    setSectionStyles(nextContent.layout?.sectionStyles || {});
    setHiddenSections(nextContent.layout?.hiddenSections || {});
    setHiddenProjects(nextContent.layout?.hiddenProjects || {});
    const storedFontSize = Number(nextContent.layout?.fontSize);
    const storedSectionTitleSize = Number(nextContent.layout?.sectionTitleFontSize);
    setFontSize(clampFontSize(storedFontSize, 10, 9.5, 14));
    setSectionTitleSize(Number.isFinite(storedSectionTitleSize) ? Math.max(11, Math.min(16, storedSectionTitleSize)) : 12);
    setPadding(nextContent.layout?.padding || 15);
    setTitle(selectedResume.title || '定制简历');
  }, [selectedResume, currentUser]);

  const save = async () => {
    if (!selectedResume || !content) return;
    setWorking(true); setError(''); setNotice('');
    try {
      const contentToSave = {
        ...content,
        layout: {
          ...(content.layout || {}),
          fontSize,
          sectionTitleFontSize: sectionTitleSize,
          padding,
          sectionStyles,
          hiddenSections,
          hiddenProjects,
        },
      };
      const saved = await careerService.updateResume(selectedResume.id, { title: title.trim() || '定制简历', content: contentToSave });
      setContent(contentToSave);
      setResumes((items) => items.map((item) => item.id === saved.id ? saved : item));
      setNotice('当前版本已保存，导出 PDF 会使用最新内容。');
    } catch (err) {
      setError(err.response?.data?.detail || '保存编辑失败。');
    } finally {
      setWorking(false);
    }
  };

  const exportPdf = async () => {
    if (!selectedResume || !content) return;
    setWorking(true); setError('');
    try {
      const contentToSave = {
        ...content,
        layout: {
          ...(content.layout || {}),
          fontSize,
          sectionTitleFontSize: sectionTitleSize,
          padding,
          sectionStyles,
          hiddenSections,
          hiddenProjects,
        },
      };
      const saved = await careerService.updateResume(selectedResume.id, { title: title.trim() || '定制简历', content: contentToSave });
      setContent(contentToSave);
      setResumes((items) => items.map((item) => item.id === saved.id ? saved : item));
      const response = await careerService.downloadResumePdf(selectedResume.id);
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${title || 'tailored-resume'}.pdf`; anchor.click(); URL.revokeObjectURL(url);
      setNotice('PDF 已导出。');
    } catch (err) {
      setError(err.response?.data?.detail || '导出 PDF 失败。');
    } finally {
      setWorking(false);
    }
  };

  const handleAvatarUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setAvatarWorking(true); setError(''); setNotice('');
    try {
      await uploadAvatar(file);
      setNotice('证件照已上传，并会显示在简历预览和 PDF 中。');
    } catch (err) {
      setError(err.response?.data?.detail || '证件照上传失败。');
    } finally {
      setAvatarWorking(false);
      event.target.value = '';
    }
  };

  const handleAvatarDelete = async () => {
    setAvatarWorking(true); setError(''); setNotice('');
    try {
      await deleteAvatar();
      setNotice('证件照已移除。');
    } catch (err) {
      setError(err.response?.data?.detail || '证件照移除失败。');
    } finally {
      setAvatarWorking(false);
    }
  };

  const moveProject = (sectionIndex, entryIndex, direction) => {
    setContent((current) => updateSection(current, sectionIndex, (section) => {
      const entries = [...(section.entries || [])];
      const nextIndex = entryIndex + direction;
      if (nextIndex < 0 || nextIndex >= entries.length) return section;
      [entries[entryIndex], entries[nextIndex]] = [entries[nextIndex], entries[entryIndex]];
      return { ...section, entries };
    }));
  };

  const toggleProjectVisibility = (sectionIndex, entryIndex) => {
    const entry = content?.sections?.[sectionIndex]?.entries?.[entryIndex];
    const key = projectVisibilityKey(sectionIndex, entry || {}, entryIndex);
    const currentlyHidden = Boolean(entry?.hidden || hiddenProjects[key]);
    setHiddenProjects((current) => ({ ...current, [key]: false }));
    setContent((current) => updateSection(current, sectionIndex, (section) => {
      const entries = [...(section.entries || [])];
      const currentEntry = entries[entryIndex];
      if (!currentEntry) return section;
      entries[entryIndex] = { ...currentEntry, hidden: !currentlyHidden };
      return { ...section, entries };
    }));
  };

  const styleKeys = useMemo(() => ['education', ...(content?.sections || []).map((section) => sectionKey(section.heading))]
    .filter((value, index, array) => array.indexOf(value) === index), [content]);
  const visibilityKeys = useMemo(() => ['education', ...(content?.sections || []).map((section) => sectionKey(section.heading))]
    .filter((value, index, array) => array.indexOf(value) === index), [content]);
  useEffect(() => {
    if (styleKeys.length && !styleKeys.includes(styleTarget)) setStyleTarget(styleKeys[0]);
  }, [styleKeys, styleTarget]);
  useEffect(() => {
    if (visibilityKeys.length && !visibilityKeys.includes(visibilityTarget)) setVisibilityTarget(visibilityKeys[0]);
  }, [visibilityKeys, visibilityTarget]);
  const activeStyle = { ...defaultSectionStyle, fontSize, ...(sectionStyles[styleTarget] || {}) };
  if (styleTarget === 'education') activeStyle.fontSize = fontSize;
  activeStyle.fontSize = clampFontSize(activeStyle.fontSize, fontSize);
  const updateActiveStyle = (field, value) => {
    if (styleTarget === 'education' && field === 'fontSize') {
      setFontSize(value);
      return;
    }
    setSectionStyles((current) => ({ ...current, [styleTarget]: { ...activeStyle, [field]: value } }));
  };
  const formatSection = (key, field, value) => setSectionStyles((current) => ({ ...current, [key]: { ...(current[key] || {}), [field]: value } }));
  const executeEditorCommand = (command, value = null) => {
    const editor = activeEditorRef.current;
    if (!editor) {
      setNotice('请先点击需要编辑的正文段落。');
      return;
    }
    editor.focus();
    const selection = window.getSelection();
    if (activeSelectionRef.current && selection) {
      selection.removeAllRanges();
      selection.addRange(activeSelectionRef.current);
    }
    document.execCommand(command, false, value);
    activeEditorChangeRef.current?.(editor.innerHTML);
  };
  const toggleEditorAccentColor = () => {
    const currentColor = document.queryCommandValue('foreColor').replace(/\s/g, '').toLowerCase();
    const isAccentColor = currentColor === '#b21f35' || currentColor === 'rgb(178,31,53)';
    executeEditorCommand('foreColor', isAccentColor ? '#17202a' : '#b21f35');
  };

  if (loading) return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>;

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <style>{resumeFontFaceCss}</style>
      <AppBar position="sticky">
        <Toolbar sx={{ gap: 1.5 }}>
          <Button color="inherit" startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/career')}>求职工作台</Button>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>A4 简历编辑器</Typography>
          <Chip label="用户数据隔离" color="primary" variant="outlined" />
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 2.5 }}>
        {(error || notice) && <Alert severity={error ? 'error' : 'success'} sx={{ mb: 2 }}>{error || notice}</Alert>}
        {!resumes.length ? (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <Typography variant="h5">还没有可编辑的定制简历</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>先在求职工作台导入职位并生成一份定制简历，之后可以在这里编辑、排序和导出。</Typography>
            <Button variant="contained" sx={{ mt: 2 }} onClick={() => navigate('/career')}>去生成定制简历</Button>
          </Paper>
        ) : (
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '260px minmax(0, 1fr) 300px' }, gap: 2, alignItems: 'start' }}>
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={700}>版本</Typography>
                <FormControl fullWidth size="small" sx={{ mt: 1.5 }}>
                  <InputLabel>选择简历版本</InputLabel>
                  <Select label="选择简历版本" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
                    {resumes.map((resume) => <MenuItem key={resume.id} value={String(resume.id)}>{resume.title}</MenuItem>)}
                  </Select>
                </FormControl>
                <TextField fullWidth size="small" label="版本名称" value={title} onChange={(event) => setTitle(event.target.value)} sx={{ mt: 1.5 }} />
                <Stack spacing={1} sx={{ mt: 1.5 }}>
                  <Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={save} disabled={working}>保存当前版本</Button>
                  <Button variant="outlined" startIcon={<DownloadRoundedIcon />} onClick={exportPdf} disabled={working}>导出 PDF</Button>
                  <Button variant="text" startIcon={<EditRoundedIcon />} onClick={() => setShowEditTools((current) => !current)}>{showEditTools ? '隐藏编辑工具' : '显示编辑工具'}</Button>
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>常用编辑</Typography>
                <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>
                  <Tooltip title="选中文字加粗"><IconButton size="small" onMouseDown={(event) => event.preventDefault()} onClick={() => executeEditorCommand('bold')}><FormatBoldRoundedIcon fontSize="small" /></IconButton></Tooltip>
                  <Tooltip title="选中文字斜体"><IconButton size="small" onMouseDown={(event) => event.preventDefault()} onClick={() => executeEditorCommand('italic')}><FormatItalicRoundedIcon fontSize="small" /></IconButton></Tooltip>
                  <Tooltip title="创建项目符号列表"><IconButton size="small" onMouseDown={(event) => event.preventDefault()} onClick={() => executeEditorCommand('insertUnorderedList')}><FormatListBulletedRoundedIcon fontSize="small" /></IconButton></Tooltip>
                  <Tooltip title="选中文字标红/取消标红"><IconButton size="small" onMouseDown={(event) => event.preventDefault()} onClick={toggleEditorAccentColor}><FormatColorTextRoundedIcon fontSize="small" sx={{ color: '#b21f35' }} /></IconButton></Tooltip>
                </Stack>
              </Paper>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={700}>证件照</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.7 }}>上传后显示在 A4 预览和后端 PDF 中，支持 PNG、JPG、WEBP，最大 5MB。</Typography>
                <Button component="label" fullWidth variant="outlined" startIcon={<UploadFileRoundedIcon />} sx={{ mt: 1.5 }} disabled={avatarWorking}>
                  {avatarWorking ? '处理中...' : currentUser?.avatar_url ? '更换证件照' : '上传证件照'}
                  <input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={handleAvatarUpload} />
                </Button>
                {currentUser?.avatar_url && <Button fullWidth color="error" startIcon={<DeleteOutlineRoundedIcon />} onClick={handleAvatarDelete} disabled={avatarWorking} sx={{ mt: 0.5 }}>移除证件照</Button>}
              </Paper>
            </Stack>

            <Paper sx={{ p: { xs: 1, md: 3 }, bgcolor: '#e9eef5', height: { xs: 'auto', lg: 'calc(100vh - 170px)' }, maxHeight: { xs: 'none', lg: 'calc(100vh - 170px)' }, overflowY: { xs: 'visible', lg: 'auto' }, overflowX: 'auto', minWidth: 0 }}>
              {content && <ResumePaper content={content} user={currentUser} hiddenSections={hiddenSections} hiddenProjects={hiddenProjects} sectionStyles={sectionStyles} fontSize={fontSize} sectionTitleSize={sectionTitleSize} padding={padding} onChange={setContent} onFormatSection={formatSection} showEditTools={showEditTools} activeEditorRef={activeEditorRef} activeSelectionRef={activeSelectionRef} activeEditorChangeRef={activeEditorChangeRef} />}
            </Paper>

            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={1} alignItems="center"><TuneRoundedIcon color="primary" /><Typography variant="subtitle1" fontWeight={700}>排版设置</Typography></Stack>
                <Typography variant="caption" color="text.secondary">内容字号：{fontSize}pt</Typography>
                <Slider value={fontSize} min={9.5} max={14} step={0.5} onChange={(_, value) => setFontSize(value)} size="small" />
                <Typography variant="caption" color="text.secondary">章节标题字号：{sectionTitleSize}pt</Typography>
                <Slider value={sectionTitleSize} min={11} max={16} step={0.5} onChange={(_, value) => setSectionTitleSize(value)} size="small" />
                <Typography variant="caption" color="text.secondary">页边距：{padding}mm</Typography>
                <Slider value={padding} min={8} max={24} step={1} onChange={(_, value) => setPadding(value)} size="small" />
              </Paper>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={700}>分区字体</Typography>
                <Typography variant="caption" color="text.secondary">先选择一个分区，再调整字号、粗细和颜色，避免重复堆叠控件。</Typography>
                <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                  <InputLabel>选择分区</InputLabel>
                  <Select label="选择分区" value={styleTarget} onChange={(event) => setStyleTarget(event.target.value)}>
                    {styleKeys.map((key) => <MenuItem key={key} value={key}>{styleLabels[key] || key}</MenuItem>)}
                  </Select>
                </FormControl>
                <Stack direction="row" spacing={0.6} sx={{ mt: 1 }}>
                  <FormControl size="small" sx={{ minWidth: 86, flex: 1 }}>
                    <InputLabel>字号</InputLabel>
                    <Select label="字号" aria-label={`${styleTarget}-font-size`} value={String(activeStyle.fontSize)} onChange={(event) => updateActiveStyle('fontSize', Number(event.target.value))}>
                      {[9.5, 10, 10.5, 11, 12, 13, 14].map((size) => <MenuItem key={size} value={String(size)}>{size}pt</MenuItem>)}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 86, flex: 1 }}>
                    <InputLabel>字重</InputLabel>
                    <Select label="字重" aria-label={`${styleTarget}-font-weight`} value={String(activeStyle.fontWeight)} onChange={(event) => updateActiveStyle('fontWeight', Number(event.target.value))}>
                      <MenuItem value="400">常规</MenuItem>
                      <MenuItem value="600">中等</MenuItem>
                      <MenuItem value="700">粗体</MenuItem>
                      <MenuItem value="800">特粗</MenuItem>
                    </Select>
                  </FormControl>
                  <TextField size="small" type="color" label="颜色" value={activeStyle.color} onChange={(event) => updateActiveStyle('color', event.target.value)} inputProps={{ 'aria-label': `${styleTarget}-font-color` }} sx={{ width: 64 }} />
                </Stack>
              </Paper>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={700}>显示与排序</Typography>
                <Typography variant="caption" color="text.secondary">控制章节显示，并调整项目经历的顺序。</Typography>
                <Stack spacing={1} sx={{ mt: 1 }}>
                  <FormControl fullWidth size="small">
                    <InputLabel>选择章节</InputLabel>
                    <Select label="选择章节" value={visibilityTarget} onChange={(event) => setVisibilityTarget(event.target.value)}>
                      {visibilityKeys.map((key) => <MenuItem key={key} value={key}>{sectionLabels[key] || key}</MenuItem>)}
                    </Select>
                  </FormControl>
                  <Button
                    fullWidth
                    size="small"
                    variant={hiddenSections[visibilityTarget] ? 'outlined' : 'contained'}
                    color={hiddenSections[visibilityTarget] ? 'inherit' : 'primary'}
                    onClick={() => setHiddenSections((current) => ({ ...current, [visibilityTarget]: !current[visibilityTarget] }))}
                  >
                    {hiddenSections[visibilityTarget] ? '显示章节' : '隐藏章节'}
                  </Button>
                </Stack>
                {content?.sections.map((section, sectionIndex) => sectionKey(section.heading) === '项目经历' && (
                  <Box key={`projects-${sectionIndex}`} sx={{ mt: 2, pt: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
                    <Typography variant="body2" fontWeight={700}>项目顺序</Typography>
                    <Stack spacing={0.35} sx={{ mt: 0.8 }}>
                      {(section.entries || []).map((entry, entryIndex) => {
                        const key = projectVisibilityKey(sectionIndex, entry, entryIndex);
                        const hidden = Boolean(entry.hidden || hiddenProjects[key]);
                        return <Stack key={key} direction="row" spacing={0.25} alignItems="center"><Typography variant="body2" sx={{ flex: 1, minWidth: 0, color: hidden ? 'text.disabled' : 'text.primary', overflowWrap: 'anywhere', fontSize: '0.82rem' }}>{entry.title || '未命名项目'}</Typography><Button size="small" variant={hidden ? 'outlined' : 'text'} color={hidden ? 'inherit' : 'primary'} onClick={() => toggleProjectVisibility(sectionIndex, entryIndex)} sx={{ minWidth: 44, px: 0.5 }}>{hidden ? '显示' : '隐藏'}</Button><Tooltip title="上移"><span><IconButton size="small" onClick={() => moveProject(sectionIndex, entryIndex, -1)} disabled={entryIndex === 0}><KeyboardArrowUpRoundedIcon fontSize="small" /></IconButton></span></Tooltip><Tooltip title="下移"><span><IconButton size="small" onClick={() => moveProject(sectionIndex, entryIndex, 1)} disabled={entryIndex === section.entries.length - 1}><KeyboardArrowDownRoundedIcon fontSize="small" /></IconButton></span></Tooltip></Stack>;
                      })}
                    </Stack>
                  </Box>
                ))}
              </Paper>
              <Typography variant="caption" color="text.secondary">编辑内容会保存到当前用户的简历版本，不会修改原始事实库。导出 PDF 时会自动同步当前内容和排版设置。</Typography>
            </Stack>
          </Box>
        )}
      </Container>
    </Box>
  );
};

export default ResumeOptimizer;
