import React, { useEffect, useMemo, useState } from 'react';
import { Box, Button, Chip, CircularProgress, Container, IconButton, MenuItem, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import DoneRoundedIcon from '@mui/icons-material/DoneRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import { useNavigate } from 'react-router-dom';
import trainingService from '../services/trainingService';
import careerService from '../services/careerService';

const labels = { resume: '简历深挖', interview: '面试复盘', jd: 'JD 新题', general: '通用挑战' };
const colors = { resume: '#7dd3fc', interview: '#fbbf24', jd: '#a7f3d0', general: '#f9a8d4' };

export default function TrainingCamp() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]); const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null); const [jobId, setJobId] = useState('');
  const [answer, setAnswer] = useState(''); const [feedback, setFeedback] = useState(null); const [referenceOpen, setReferenceOpen] = useState(false);
  const [loading, setLoading] = useState(true); const [working, setWorking] = useState(false);
  const selected = items.find((item) => item.id === selectedId) || items[0];
  const counts = useMemo(() => Object.fromEntries(Object.keys(labels).map((key) => [key, items.filter((item) => item.source_type === key && item.status === 'active').length])), [items]);
  const load = async () => { setLoading(true); try { const data = await trainingService.list(); setItems(data); setSelectedId((id) => id || data[0]?.id || null); } finally { setLoading(false); } };
  useEffect(() => { load(); careerService.listJobs().then((data) => { setJobs(data); setJobId(data[0]?.id ? String(data[0].id) : ''); }).catch(() => {}); }, []);
  useEffect(() => { setAnswer(''); setFeedback(null); setReferenceOpen(false); }, [selected?.id]);
  const createPlan = async () => { setWorking(true); try { const data = await trainingService.createDefaultPlan(jobId); setItems((prev) => [...data.items, ...prev]); setSelectedId(data.items[0]?.id || null); } finally { setWorking(false); } };
  const submit = async () => { if (!selected || !answer.trim()) return; setWorking(true); try { const data = await trainingService.answer(selected.id, answer); setFeedback(data); setReferenceOpen(true); setItems((prev) => prev.map((item) => item.id === selected.id ? data.item : item)); } finally { setWorking(false); } };
  const setStatus = async (status) => { if (!selected) return; const item = await trainingService.setStatus(selected.id, status); setItems((prev) => prev.map((value) => value.id === item.id ? item : value)); };
  const remove = async (id) => { await trainingService.remove(id); const next = items.filter((item) => item.id !== id); setItems(next); if (id === selectedId) setSelectedId(next[0]?.id || null); };

  return (
    <Box sx={{ minHeight: '100vh', py: { xs: 2, md: 4 } }}><Container maxWidth="xl">
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2} sx={{ mb: 3 }}>
        <Stack direction="row" spacing={1} alignItems="center"><Tooltip title="返回"><IconButton onClick={() => navigate('/chat')}><ArrowBackRoundedIcon /></IconButton></Tooltip><Box><Typography variant="h4">训练营</Typography><Typography color="text.secondary">基于简历、真实面试和目标 JD 的个人训练计划。</Typography></Box></Stack>
        <Stack direction="row" spacing={1}><TextField select size="small" value={jobId} onChange={(event) => setJobId(event.target.value)} sx={{ minWidth: 180 }}><MenuItem value="">通用岗位训练</MenuItem>{jobs.map((job) => <MenuItem key={job.id} value={String(job.id)}>{job.title}{job.company ? ` · ${job.company}` : ''}</MenuItem>)}</TextField><Button variant="contained" startIcon={<PlayArrowRoundedIcon />} onClick={createPlan} disabled={working}>生成训练</Button></Stack>
      </Stack>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>{Object.entries(labels).map(([key, label]) => <Chip key={key} label={`${label} ${counts[key]}`} sx={{ color: colors[key], bgcolor: `${colors[key]}16` }} />)}</Stack>
      {loading && <Box sx={{ display: 'grid', placeItems: 'center', minHeight: 360 }}><CircularProgress /></Box>}
      {!loading && !items.length && <Paper sx={{ p: 5, textAlign: 'center' }}><Typography variant="h6">还没有训练题</Typography><Button sx={{ mt: 2 }} variant="contained" onClick={createPlan}>生成第一组训练</Button></Paper>}
      {!loading && items.length > 0 && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '340px minmax(0, 1fr)' }, gap: 2 }}>
        <Paper sx={{ p: 1, maxHeight: { lg: 'calc(100vh - 210px)' }, overflowY: 'auto' }}>{items.map((item) => <Box key={item.id} onClick={() => setSelectedId(item.id)} sx={{ p: 1.5, mb: .75, cursor: 'pointer', borderRadius: 1.5, bgcolor: selected?.id === item.id ? 'rgba(125,211,252,.12)' : 'transparent' }}><Stack direction="row" justifyContent="space-between"><Chip size="small" label={labels[item.source_type]} /><Tooltip title="删除"><IconButton size="small" onClick={(event) => { event.stopPropagation(); remove(item.id); }}><DeleteOutlineRoundedIcon fontSize="small" /></IconButton></Tooltip></Stack><Typography variant="body2" sx={{ mt: 1 }}>{item.question}</Typography>{item.due_at && <Typography variant="caption" color="text.secondary">复习时间 {new Date(item.due_at).toLocaleDateString()}</Typography>}</Box>)}</Paper>
        {selected && <Paper sx={{ p: { xs: 2, md: 3 } }}><Stack spacing={2}><Box><Chip size="small" label={selected.source_label} /><Typography variant="h6" sx={{ mt: 1.5, lineHeight: 1.55 }}>{selected.question}</Typography></Box><Stack direction="row" spacing={.7} useFlexGap flexWrap="wrap">{selected.focus_points.map((point) => <Chip key={point} size="small" label={point} />)}</Stack>{selected.original_answer && <Paper variant="outlined" sx={{ p: 1.5 }}><Typography variant="caption">历史回答</Typography><Typography variant="body2">{selected.original_answer}</Typography></Paper>}<TextField label="现在重新作答" multiline minRows={7} value={answer} onChange={(event) => setAnswer(event.target.value)} /><Stack direction="row" spacing={1}><Button variant="contained" onClick={submit} disabled={working || !answer.trim()}>提交并评分</Button><Button variant="outlined" onClick={() => setStatus('snoozed')}>3 天后复习</Button><Tooltip title="标记已掌握"><IconButton color="success" onClick={() => setStatus('mastered')}><DoneRoundedIcon /></IconButton></Tooltip></Stack>{feedback && <Box sx={{ pt: 1.5, borderTop: '1px solid rgba(148,163,184,.18)' }}><Typography color="success.main">本次得分 {feedback.score}</Typography><Typography variant="body2" sx={{ mt: 1 }}>{feedback.feedback}</Typography></Box>}{(feedback || selected.attempts > 0) && <Box sx={{ pt: 1.5, borderTop: '1px solid rgba(148,163,184,.18)' }}><Button size="small" variant="text" onClick={() => setReferenceOpen((value) => !value)}>{referenceOpen ? '收起参考答题框架' : '查看参考答题框架'}</Button>{referenceOpen && <Box sx={{ mt: 1 }}><Typography variant="subtitle2">参考答题框架</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5, whiteSpace: 'pre-wrap', lineHeight: 1.75 }}>{selected.reference_answer || '暂无参考答题框架'}</Typography></Box>}</Box>}</Stack></Paper>}
      </Box>}
    </Container></Box>
  );
}
