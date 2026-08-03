import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  AppBar,
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
import ImportExportRoundedIcon from '@mui/icons-material/ImportExportRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import TuneRoundedIcon from '@mui/icons-material/TuneRounded';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import careerService from '../services/careerService';
import { useAuth } from '../contexts/AuthContext';

const sectionLabels = {
  education: '教育背景',
  '实习经历': '实习经历',
  '项目经历': '项目经历',
  '专业技能': '专业技能',
  '竞赛与荣誉': '竞赛与荣誉',
};

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

const updateSection = (content, index, updater) => {
  const next = clone(content);
  next.sections[index] = updater(next.sections[index]);
  return next;
};

const ResumePaper = ({ content, user, hiddenSections, hiddenProjects, fontSize, padding, onChange }) => {
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

  return (
    <Box
      sx={{
        width: '210mm',
        minHeight: '297mm',
        maxWidth: '100%',
        bgcolor: '#fff',
        color: '#17202a',
        p: `${padding}mm`,
        fontSize: `${fontSize}pt`,
        lineHeight: 1.55,
        boxShadow: '0 16px 40px rgba(15, 23, 42, 0.14)',
        overflowWrap: 'anywhere',
        fontFamily: 'Arial, "Microsoft YaHei", sans-serif',
      }}
    >
      <Box sx={{ borderLeft: '4px solid #0f766e', pl: 2, mb: 2.5 }}>
        <Typography sx={{ fontSize: `${Math.max(fontSize + 7, 17)}pt`, fontWeight: 800 }}>
          {user?.full_name || '姓名待确认'}
        </Typography>
        <Typography sx={{ color: '#0f766e', fontWeight: 700, mt: 0.25 }}>{content.headline}</Typography>
        <Typography variant="body2" sx={{ color: '#52606d', mt: 1 }}>
          {[user?.phone, user?.email, user?.target_role].filter(Boolean).join('  ·  ') || '请在个人档案补充联系方式'}
        </Typography>
      </Box>

      <TextField
        fullWidth
        variant="standard"
        label="职业摘要（可编辑）"
        value={content.summary || ''}
        onChange={(event) => onChange({ ...content, summary: event.target.value })}
        multiline
        sx={{ mb: 2, '& .MuiInputBase-root': { fontSize: 'inherit' } }}
      />

      {!hiddenSections.education && content.education?.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography sx={{ borderBottom: '1px solid #cbd5e1', pb: 0.5, mb: 1, fontWeight: 800 }}>教育背景</Typography>
          {content.education.map((item, index) => (
            <Box key={`${item.school || item.title}-${index}`} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, mb: 0.6 }}>
              <Typography fontWeight={700}>{[item.school, item.major, item.degree].filter(Boolean).join(' · ') || item.title || '教育经历'}</Typography>
              <Typography sx={{ whiteSpace: 'nowrap', color: '#52606d' }}>{[item.start_date, item.end_date].filter(Boolean).join(' - ')}</Typography>
            </Box>
          ))}
        </Box>
      )}

      {content.sections.map((section, sectionIndex) => {
        const key = sectionKey(section.heading);
        if (hiddenSections[key]) return null;
        return (
          <Box key={`${section.heading}-${sectionIndex}`} sx={{ mb: 2 }}>
            <Typography sx={{ borderBottom: '1px solid #cbd5e1', pb: 0.5, mb: 1, fontWeight: 800 }}>
              {sectionLabels[section.heading] || section.heading || '其他经历'}
            </Typography>
            {(section.entries || []).map((entry, entryIndex) => {
              const projectKey = `${sectionIndex}-${entryIndex}`;
              if (key === '项目经历' && hiddenProjects[projectKey]) return null;
              return (
                <Box key={`${entry.title}-${entryIndex}`} sx={{ mb: 1.3 }}>
                  <Stack direction="row" spacing={1} alignItems="baseline" justifyContent="space-between">
                    <TextField
                      variant="standard"
                      value={entry.title || ''}
                      onChange={(event) => updateEntry(sectionIndex, entryIndex, 'title', event.target.value)}
                      sx={{ flex: 1, '& .MuiInputBase-root': { fontWeight: 700, fontSize: 'inherit' } }}
                    />
                    <TextField
                      variant="standard"
                      value={entry.period || ''}
                      onChange={(event) => updateEntry(sectionIndex, entryIndex, 'period', event.target.value)}
                      sx={{ width: 125, '& .MuiInputBase-root': { fontSize: '0.92em', color: '#52606d' } }}
                    />
                  </Stack>
                  <TextField
                    variant="standard"
                    fullWidth
                    value={entry.subtitle || ''}
                    onChange={(event) => updateEntry(sectionIndex, entryIndex, 'subtitle', event.target.value)}
                    placeholder="角色 / 职位"
                    sx={{ '& .MuiInputBase-root': { fontSize: '0.94em', color: '#52606d' } }}
                  />
                  {entry.summary && (
                    <TextField
                      variant="standard"
                      fullWidth
                      multiline
                      value={entry.summary || ''}
                      onChange={(event) => updateEntry(sectionIndex, entryIndex, 'summary', event.target.value)}
                      sx={{ mt: 0.4, '& .MuiInputBase-root': { fontSize: '0.96em' } }}
                    />
                  )}
                  {entry.tech_stack?.length > 0 && <Typography variant="caption" sx={{ display: 'block', mt: 0.4, color: '#0f766e' }}>技术栈：{entry.tech_stack.join('、')}</Typography>}
                  {(entry.items || []).map((item, itemIndex) => (
                    <TextField
                      key={`${item.label}-${itemIndex}`}
                      variant="standard"
                      fullWidth
                      multiline
                      value={item.text || ''}
                      onChange={(event) => updateEntry(sectionIndex, entryIndex, 'items', (entry.items || []).map((current, index) => index === itemIndex ? { ...current, text: event.target.value } : current))}
                      sx={{ mt: 0.35, '& .MuiInputBase-root': { fontSize: '0.96em' } }}
                      InputProps={{ startAdornment: <Box component="span" sx={{ mr: 0.7, color: '#0f766e' }}>•</Box> }}
                    />
                  ))}
                </Box>
              );
            })}
            {(section.items || []).map((item, itemIndex) => (
              <TextField
                key={`${item.label}-${itemIndex}`}
                variant="standard"
                fullWidth
                multiline
                value={item.text || item.label || ''}
                onChange={(event) => updateItem(sectionIndex, itemIndex, event.target.value)}
                sx={{ mb: 0.35, '& .MuiInputBase-root': { fontSize: '0.96em' } }}
                InputProps={{ startAdornment: <Box component="span" sx={{ mr: 0.7, color: '#0f766e' }}>•</Box> }}
              />
            ))}
          </Box>
        );
      })}
      <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', textAlign: 'right', mt: 3 }}>职引 · 仅使用已确认职业事实</Typography>
    </Box>
  );
};

const ResumeOptimizer = () => {
  const navigate = useNavigate();
  const { currentUser } = useAuth();
  const importInput = useRef(null);
  const [resumes, setResumes] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [content, setContent] = useState(null);
  const [title, setTitle] = useState('');
  const [hiddenSections, setHiddenSections] = useState({});
  const [hiddenProjects, setHiddenProjects] = useState({});
  const [fontSize, setFontSize] = useState(10.5);
  const [padding, setPadding] = useState(15);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await careerService.listResumes();
      setResumes(data);
      setSelectedId((current) => current || (data[0] ? String(data[0].id) : ''));
    } catch (err) {
      setError(err.response?.data?.detail || '加载简历版本失败。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const selectedResume = useMemo(() => resumes.find((item) => String(item.id) === String(selectedId)), [resumes, selectedId]);

  useEffect(() => {
    if (!selectedResume) {
      setContent(null);
      return;
    }
    setContent(normalizeContent(selectedResume, currentUser));
    setTitle(selectedResume.title || '定制简历');
  }, [selectedResume, currentUser]);

  const save = async () => {
    if (!selectedResume || !content) return;
    setWorking(true); setError(''); setNotice('');
    try {
      const saved = await careerService.updateResume(selectedResume.id, { title: title.trim() || '定制简历', content });
      setResumes((items) => items.map((item) => item.id === saved.id ? saved : item));
      setNotice('当前版本已保存，导出 PDF 会使用最新内容。');
    } catch (err) {
      setError(err.response?.data?.detail || '保存编辑失败。');
    } finally {
      setWorking(false);
    }
  };

  const exportPdf = async () => {
    if (!selectedResume) return;
    setWorking(true); setError('');
    try {
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

  const importPrototypeJson = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setWorking(true); setError(''); setNotice('');
    try {
      const draft = JSON.parse(await file.text());
      const result = await careerService.importProfile(draft);
      setNotice(`已导入 ${result.imported_facts} 条待确认事实，跳过 ${result.skipped_facts} 条重复事实。请回到工作台确认后生成简历。`);
    } catch (err) {
      setError(err.response?.data?.detail || '原型 JSON 导入失败，请确认文件格式正确。');
    } finally {
      setWorking(false);
      event.target.value = '';
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

  if (loading) return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>;

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <AppBar position="sticky">
        <Toolbar sx={{ gap: 1.5 }}>
          <Button color="inherit" startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/career')}>求职工作台</Button>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>A4 简历编辑器</Typography>
          <Chip label="用户数据隔离" color="primary" variant="outlined" />
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 2.5 }}>
        {(error || notice) && <Alert severity={error ? 'error' : 'success'} sx={{ mb: 2 }}>{error || notice}</Alert>}
        <input ref={importInput} hidden type="file" accept="application/json,.json" onChange={importPrototypeJson} />
        {!resumes.length ? (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <Typography variant="h5">还没有可编辑的定制简历</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>先在求职工作台导入职位并生成一份定制简历，之后可以在这里编辑、排序和导出。</Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="center" sx={{ mt: 2 }}>
              <Button variant="outlined" startIcon={<ImportExportRoundedIcon />} onClick={() => importInput.current?.click()} disabled={working}>先导入原型 JSON</Button>
              <Button variant="contained" onClick={() => navigate('/career')}>去生成定制简历</Button>
            </Stack>
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
                </Stack>
              </Paper>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={700}>导入原型资料</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.7 }}>兼容原型的 `resume-profiles.json`，导入后进入事实库待确认。</Typography>
                <Button fullWidth variant="outlined" startIcon={<ImportExportRoundedIcon />} sx={{ mt: 1.5 }} onClick={() => importInput.current?.click()} disabled={working}>选择 JSON 导入</Button>
              </Paper>
            </Stack>

            <Paper sx={{ p: { xs: 1, md: 3 }, bgcolor: '#e9eef5', minHeight: 'calc(100vh - 130px)', overflow: 'auto' }}>
              {content && <ResumePaper content={content} user={currentUser} hiddenSections={hiddenSections} hiddenProjects={hiddenProjects} fontSize={fontSize} padding={padding} onChange={setContent} />}
            </Paper>

            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={1} alignItems="center"><TuneRoundedIcon color="primary" /><Typography variant="subtitle1" fontWeight={700}>排版设置</Typography></Stack>
                <Typography variant="caption" color="text.secondary">字号：{fontSize}pt</Typography>
                <Slider value={fontSize} min={8} max={14} step={0.5} onChange={(_, value) => setFontSize(value)} size="small" />
                <Typography variant="caption" color="text.secondary">页边距：{padding}mm</Typography>
                <Slider value={padding} min={8} max={24} step={1} onChange={(_, value) => setPadding(value)} size="small" />
              </Paper>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={700}>章节显示</Typography>
                <Stack spacing={0.6} sx={{ mt: 1 }}>
                  {['education', ...(content?.sections || []).map((section) => sectionKey(section.heading))].filter((value, index, array) => array.indexOf(value) === index).map((key) => (
                    <Button key={key} size="small" variant={hiddenSections[key] ? 'outlined' : 'contained'} onClick={() => setHiddenSections((current) => ({ ...current, [key]: !current[key] }))}>{hiddenSections[key] ? '显示 ' : '隐藏 '}{sectionLabels[key] || key}</Button>
                  ))}
                </Stack>
              </Paper>
              {content?.sections.map((section, sectionIndex) => sectionKey(section.heading) === '项目经历' && (
                <Paper key={`projects-${sectionIndex}`} sx={{ p: 2 }}>
                  <Typography variant="subtitle1" fontWeight={700}>项目顺序与显示</Typography>
                  <Stack spacing={0.7} sx={{ mt: 1 }}>
                    {(section.entries || []).map((entry, entryIndex) => {
                      const key = `${sectionIndex}-${entryIndex}`;
                      return <Stack key={`${entry.title}-${entryIndex}`} direction="row" spacing={0.4} alignItems="center"><Button size="small" sx={{ flex: 1, justifyContent: 'flex-start', textAlign: 'left', color: hiddenProjects[key] ? 'text.disabled' : 'text.primary' }} onClick={() => setHiddenProjects((current) => ({ ...current, [key]: !current[key] }))}>{hiddenProjects[key] ? '显示' : '隐藏'} {entry.title || '未命名项目'}</Button><Tooltip title="上移"><span><IconButton size="small" onClick={() => moveProject(sectionIndex, entryIndex, -1)} disabled={entryIndex === 0}><KeyboardArrowUpRoundedIcon fontSize="small" /></IconButton></span></Tooltip><Tooltip title="下移"><span><IconButton size="small" onClick={() => moveProject(sectionIndex, entryIndex, 1)} disabled={entryIndex === section.entries.length - 1}><KeyboardArrowDownRoundedIcon fontSize="small" /></IconButton></span></Tooltip></Stack>;
                    })}
                  </Stack>
                </Paper>
              ))}
              <Typography variant="caption" color="text.secondary">编辑内容会保存到当前用户的简历版本，不会修改原始事实库。导出前请先点击“保存当前版本”。</Typography>
            </Stack>
          </Box>
        )}
      </Container>
    </Box>
  );
};

export default ResumeOptimizer;
